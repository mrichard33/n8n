"""Four-page document assembly, ported from REFERENCE_lightfire_lean.py (D1).

CANONICAL REPORT TEMPLATE — DO NOT REDESIGN (D10). Kept verbatim from the
reference: the S style dict, table()/kpis()/callout()/chart() helpers, furn()
page furniture, all column widths, page breaks, section order and numbering,
confidentiality marking, and all non-numeric prose (which lives in
narrative.py). Replaced: every hardcoded number and date, sourced from the
assembled payload. The single approved structural change is the KPI third row
carrying week-over-week deltas (§9, authorised by Mark 2026-08-18) — it adds
~9pt to the KPI band, absorbed by page-1 slack.

Pagination guard (§11): build_report raises PaginationError when the page
count differs from config.expected_page_count. Never shrink fonts or leading —
if a week overflows, the levers are the §11 row filters, applied upstream.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, Image, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from assemble import Derived, assemble, generated_stamp
from charts import ownership_chart
from schema import ReportPayload

INK = colors.HexColor("#12181F"); SLATE = colors.HexColor("#5A6673")
RULE = colors.HexColor("#D4DAE0"); BAND = colors.HexColor("#F1F4F7")
NAVY = colors.HexColor("#12395B"); RED = colors.HexColor("#A3231C")
AMBER = colors.HexColor("#8A5A05"); GREEN = colors.HexColor("#1D6236"); LF = colors.HexColor("#1F6F8B")
G = "#1D6236"; R = "#A3231C"; A = "#8A5A05"; N = "#12395B"; LFH = "#1F6F8B"

_KPI_COLORS = {"G": G, "R": R, "A": A, "N": N}
_DELTA_COLORS = {"good": G, "bad": R, "flat": "#5A6673"}


def st(n, **k):
    b = dict(name=n, fontName="Helvetica", fontSize=9.3, leading=13, textColor=INK, alignment=TA_LEFT)
    b.update(k); return ParagraphStyle(**b)


S = {"title": st("title", fontName="Helvetica-Bold", fontSize=20, leading=23, textColor=NAVY, spaceAfter=2),
     "sub": st("sub", fontSize=10.5, leading=14, textColor=SLATE, spaceAfter=1),
     "h1": st("h1", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=NAVY, spaceBefore=10, spaceAfter=4),
     "h2": st("h2", fontName="Helvetica-Bold", fontSize=10, leading=13, spaceBefore=8, spaceAfter=3),
     "body": st("body", spaceAfter=5.0),
     "bullet": st("bullet", leftIndent=12, bulletIndent=3, spaceAfter=3),
     "small": st("small", fontSize=7.8, leading=10.0, textColor=SLATE, spaceAfter=3),
     "cell": st("cell", fontSize=8.1, leading=10.5),
     "cellb": st("cellb", fontSize=8.1, leading=10.5, fontName="Helvetica-Bold"),
     "cellh": st("cellh", fontSize=7.9, leading=10, fontName="Helvetica-Bold", textColor=colors.white),
     "kpin": st("kpin", fontName="Helvetica-Bold", fontSize=15, leading=17, textColor=NAVY),
     "kpil": st("kpil", fontSize=7.2, leading=9, textColor=SLATE),
     # §9: the KPI delta row — the one approved addition to the style dict.
     "kpid": st("kpid", fontSize=6.8, leading=8.4, textColor=SLATE),
     "call": st("call", fontSize=9.2, leading=12.8, leftIndent=8, rightIndent=6, spaceBefore=2, spaceAfter=2),
     "cap": st("cap", fontSize=7.6, leading=9.6, textColor=SLATE, spaceBefore=2, spaceAfter=6)}


def P(t, s="body"):
    return Paragraph(t, S[s])


def bl(x):
    return [Paragraph(t, S["bullet"], bulletText="•") for t in x]


def C(c, t):
    return Paragraph('<b><font color="%s">%s</font></b>' % (c, t), S["cell"])


def table(header, rows, widths, aligns=None, hl=None, hlc=None):
    body = [[Paragraph(h, S["cellh"]) for h in header]]
    for r in rows:
        body.append([c if isinstance(c, Paragraph) else Paragraph(str(c), S["cell"]) for c in r])
    cmds = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3.0), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE), ("LINEBELOW", (0, -1), (-1, -1), 0.7, RULE)]
    for i in range(1, len(body)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), BAND))
    for c, a in (aligns or []):
        cmds.append(("ALIGN", (c, 0), (c, -1), a))
    for i in (hl or []):
        cmds.append(("BACKGROUND", (0, i), (-1, i), hlc or colors.HexColor("#E8F1F5")))
    t = Table(body, colWidths=widths, hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle(cmds)); return t


def kpis(items, w):
    """Reference kpis() plus the §9 third row: (value, label, colorhex,
    delta_text, delta_colorhex). Empty delta_text on the first run keeps the
    band height constant across weeks."""
    cmds = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("BACKGROUND", (0, 0), (-1, -1), BAND), ("BOX", (0, 0), (-1, -1), 0.4, RULE),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 1), ("TOPPADDING", (0, 1), (-1, 1), 0),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 1), ("TOPPADDING", (0, 2), (-1, 2), 0)]
    for i in range(1, len(items)):
        cmds.append(("LINEBEFORE", (i, 0), (i, -1), 0.4, RULE))
    t = Table([[Paragraph(f'<font color="{c}">{v}</font>', S["kpin"]) for v, l, c, dt, dc in items],
               [Paragraph(l, S["kpil"]) for v, l, c, dt, dc in items],
               [Paragraph(f'<font color="{dc}">{dt}</font>' if dt else "", S["kpid"])
                for v, l, c, dt, dc in items]],
              colWidths=[w / len(items)] * len(items), hAlign="LEFT")
    t.setStyle(TableStyle(cmds)); return t


def callout(title, text, accent):
    t = Table([[Paragraph(f'<b><font color="{accent}">{title}</font></b><br/>{text}', S["call"])]],
              colWidths=[6.9 * inch], hAlign="LEFT")
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BAND), ("LINEBEFORE", (0, 0), (0, -1), 2.4, accent),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7)]))
    return t


def chart(p, w=6.9 * inch):
    from PIL import Image as PI
    iw, ih = PI.open(p).size
    return Image(p, width=w, height=w * ih / iw)


class PaginationError(Exception):
    def __init__(self, pages: int, expected: int):
        self.pages, self.expected = pages, expected
        super().__init__(f"pagination: built {pages} pages, expected {expected}")


@dataclass
class BuildResult:
    path: str
    page_count: int
    derived: Derived


def _dmon(d):
    return f"{d.day} {d.strftime('%B')}"


def _sit_color(pct, goal_pct):
    if pct is None:
        return None
    if pct >= goal_pct:
        return G
    if pct >= goal_pct - 5:
        return A
    return R


# §11 overflow ladder: floor 0 shows every agent (the golden and any week that
# fits render here and stop). Higher floors hold the lowest-volume Lightfire
# agents out of the page-1 table — matching the order in the handoff (drop
# below min_matured, already applied, then net_issued < 3, then wider) — until
# the report is exactly four pages again. Never fonts.
_PAGE1_NET_FLOORS = [0, 3, 5, 8]


def build_report(payload: ReportPayload, out_path: str, *, derived: Derived | None = None) -> BuildResult:
    """Render to exactly config.expected_page_count pages, applying the §11
    page-1 row-filter ladder when a full roster would overflow. A caller that
    passes its own `derived` gets a single pass with no laddering."""
    if derived is not None:
        return _build_report_at(payload, out_path, derived)
    last: PaginationError | None = None
    for floor in _PAGE1_NET_FLOORS:
        try:
            return _build_report_at(payload, out_path, assemble(payload, page1_net_floor=floor))
        except PaginationError as e:
            last = e
            if e.pages < e.expected:
                # trimming only ever removes content; fewer pages than expected
                # is not something a higher floor can fix.
                raise
    assert last is not None
    raise last


def _build_report_at(payload: ReportPayload, out_path: str, d: Derived) -> BuildResult:
    p = payload
    goal_pct = 100.0 * p.config.issued_sit_goal
    run = p.meta.run_date
    title_date = f"{_dmon(run)} {run.year}"

    def furn(c, _doc):
        c.saveState(); w, h = letter
        c.setStrokeColor(RULE); c.setLineWidth(0.5)
        c.line(0.75 * inch, h - 0.6 * inch, w - 0.75 * inch, h - 0.6 * inch)
        c.setFont("Helvetica", 7.3); c.setFillColor(SLATE)
        c.drawString(0.75 * inch, h - 0.53 * inch,
                     "Reece Windows & Doors  ·  Lightfire Partner Performance Review")
        c.drawRightString(w - 0.75 * inch, h - 0.53 * inch, title_date)
        c.line(0.75 * inch, 0.58 * inch, w - 0.75 * inch, 0.58 * inch)
        c.setFont("Helvetica", 7.3)
        c.drawString(0.75 * inch, 0.42 * inch,
                     f"Six-week review to {_dmon(p.meta.period_end)} {p.meta.period_end.year}  ·  Confidential")
        c.drawRightString(w - 0.75 * inch, 0.42 * inch, f"Page {c.getPageNumber()}")
        c.restoreState()

    doc = BaseDocTemplate(
        out_path, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.8 * inch, bottomMargin=0.75 * inch,
        title=f"Reece Windows & Doors — Lightfire Partner Performance Review, {title_date}",
        author="Reece Windows & Doors — Call Center Operations")
    doc.addPageTemplates([PageTemplate(id="s", frames=[Frame(
        doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
        id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=furn)])
    W = doc.width
    s = []

    # ================= PAGE 1
    s.append(P("Lightfire Partner Performance Review", "title"))
    s.append(P(f"Appointments set {_dmon(p.meta.cohort_set_start)} – {_dmon(p.meta.cohort_set_end)} "
               f"{p.meta.cohort_set_end.year} whose date has passed · issued {_dmon(run)}", "sub"))
    s.append(Spacer(1, 8))

    s.append(kpis([(k.value, k.label, _KPI_COLORS[k.color_key], k.delta_text,
                    _DELTA_COLORS[k.delta_class]) for k in d.kpis], W))
    s.append(Spacer(1, 9))

    s.append(callout("The whole review in one paragraph", d.exec_paragraph, NAVY))

    s.append(P("Credit first, because it is earned", "h2"))
    s.extend(bl([c.text for c in d.credit.observations]))

    s.append(P(f"1.  Issued Sit % by agent against the {goal_pct:.0f}% goal", "h1"))
    s.append(P(
        "<b>Issued Sit %</b> = sits ÷ (gross issued − cancels). Section 3 uses <b>Matured Sit %</b> (sits "
        "÷ all matured appointments), necessarily lower. The two are not comparable.", "small"))

    rows, hl = [], []
    max_short = max((r.sits_short for r in d.lf_rows), default=0.0)
    for i, r in enumerate(d.lf_rows):
        name = r.name + (" *" if r.small_denominator else "")
        name_cell = name if r.small_denominator else Paragraph(f"<b>{r.name}</b>", S["cellb"])
        if not r.small_denominator:
            hl.append(i + 1)
        if r.issued_sit_pct is None:
            sit_cell, vs_cell = "—", "—"
        else:
            col = _sit_color(r.issued_sit_pct, goal_pct)
            sit_cell = C(col, f"{r.issued_sit_pct:.1f}%")
            vs = r.vs_goal_pts
            vs_cell = C(col, f"{'+' if vs >= 0 else '−'}{abs(vs):.1f}")
        if r.sits_short <= 0:
            short_cell = "—"
        elif r.sits_short == max_short:
            short_cell = Paragraph(f"<b>{r.sits_short:.1f}</b>", S["cellb"])
        else:
            short_cell = f"{r.sits_short:.1f}"
        rows.append([name_cell, str(r.agent.gross_issued), str(r.agent.cancels),
                     str(r.agent.net_issued), str(r.agent.sat), sit_cell, vs_cell, short_cell])

    t = d.lf_total
    hl.append(len(rows) + 1)
    rows.append([Paragraph("<b>Lightfire total</b>", S["cellb"]),
                 Paragraph(f"<b>{t.gross_issued}</b>", S["cellb"]),
                 Paragraph(f"<b>{t.cancels}</b>", S["cellb"]),
                 Paragraph(f"<b>{t.net_issued}</b>", S["cellb"]),
                 Paragraph(f"<b>{t.sat}</b>", S["cellb"]),
                 Paragraph(f"<b>{t.issued_sit_pct:.1f}%</b>", S["cellb"]),
                 C(_sit_color(t.issued_sit_pct, goal_pct), f"−{abs(t.vs_goal_pts):.1f}")
                 if t.vs_goal_pts < 0 else C(G, f"+{t.vs_goal_pts:.1f}"),
                 Paragraph(f"<b>{t.sits_short:.0f}</b>", S["cellb"])])
    rt = d.reece_total
    rows.append([Paragraph("<b>Reece setters, same basis</b>", S["cellb"]),
                 str(rt.gross_issued), str(rt.cancels), str(rt.net_issued), str(rt.sat),
                 Paragraph(f"<b>{rt.issued_sit_pct:.1f}%</b>", S["cellb"]),
                 C(_sit_color(rt.issued_sit_pct, goal_pct),
                   f"{'+' if rt.vs_goal_pts >= 0 else '−'}{abs(rt.vs_goal_pts):.1f}"),
                 f"{rt.sits_short:.0f}"])

    s.append(table(
        ["Agent", "Gross issued", "Cancels", "Net issued", "Sits", "Issued Sit %", "vs goal", "Sits short"],
        rows,
        [1.42 * inch, 0.75 * inch, 0.58 * inch, 0.66 * inch, 0.44 * inch, 0.6 * inch, 0.62 * inch, 0.63 * inch],
        aligns=[(1, "CENTER"), (2, "CENTER"), (3, "CENTER"), (4, "CENTER"), (5, "CENTER"), (6, "CENTER"), (7, "CENTER")],
        hl=hl))
    s.append(Spacer(1, 4))
    s.append(P(d.page1_footnote, "small"))

    # ================= PAGE 2
    s.append(PageBreak())
    s.append(P("2.  Why they do not sit", "h1"))
    s.append(P(d.page2_audit))

    chart_path = os.path.join(tempfile.mkdtemp(prefix="lfchart"), "lf_ownership.png")
    b = d.page2_table_rows[0]
    ownership_chart(
        chart_path,
        lf_matured=b["lf_matured"], reece_matured=b["reece_matured"],
        lf_pcts={"desk": b["lf_desk_pct"], "self": b["lf_self_pct"],
                 "ai_other": 100.0 - b["lf_desk_pct"] - b["lf_self_pct"] - b["lf_noconf_pct"],
                 "none": b["lf_noconf_pct"]},
        reece_pcts={"desk": b["reece_desk_pct"], "self": b["reece_self_pct"],
                    "ai_other": 100.0 - b["reece_desk_pct"] - b["reece_self_pct"] - b["reece_noconf_pct"],
                    "none": b["reece_noconf_pct"]},
        headline_noconf_pct=b["lf_noconf_pct"])
    s.append(chart(chart_path))
    s.append(Spacer(1, 3))

    s.append(table(
        ["", f"Lightfire book ({b['lf_matured']})", f"Reece book ({b['reece_matured']})", "Verdict"],
        [[Paragraph("<b>No confirmer of record</b>", S["cellb"]),
          Paragraph(f"<b>{b['lf_noconf']} — {b['lf_noconf_pct']:.1f}%</b>", S["cellb"]),
          Paragraph(f"<b>{b['reece_noconf']} — {b['reece_noconf_pct']:.1f}%</b>", S["cellb"]),
          C(R, b["verdict_noconf"])],
         ["Confirmed by our desk",
          f"{b['lf_desk']} — {b['lf_desk_pct']:.1f}%",
          f"{b['reece_desk']} — {b['reece_desk_pct']:.1f}%",
          C(A, "our coverage gap")],
         ["Self-confirmed by your agents",
          f"{b['lf_self']} — {b['lf_self_pct']:.1f}%",
          f"{b['reece_self']} — {b['reece_self_pct']:.1f}%",
          "structural difference"],
         [Paragraph("<b>Strand rate among those</b>", S["cellb"]),
          f"{b['lf_strand']} of {b['lf_unconf']} — {b['lf_strand_pct']:.1f}%",
          f"{b['reece_strand']} of {b['reece_unconf']} — {b['reece_strand_pct']:.1f}%",
          C(G if d.test_strand.verdict == "NOT_DISTINGUISHABLE" else R, b["verdict_strand"])]],
        [1.85 * inch, 1.6 * inch, 1.55 * inch, 1.5 * inch],
        aligns=[(1, "CENTER"), (2, "CENTER"), (3, "CENTER")], hl=[1, 4]))
    s.append(Spacer(1, 5))
    s.append(P(d.page2_held_constant))
    s.append(P(d.page2_downstream))

    s.append(callout("Where Reece needs to act", d.reece_box, GREEN))
    if d.lf_box:
        s.append(callout("Where Lightfire needs to act", d.lf_box, LF))
    s.append(Spacer(1, 3))
    s.append(P(d.source_mix_foot, "small"))

    # ================= PAGE 3
    s.append(PageBreak())
    s.append(P("3.  Where your agents rank against ours", "h1"))
    s.append(P(
        "Ranked by gross contract dollars from each setter’s appointments, both teams on the same matured basis. "
        "Our own setters are named so you can see exactly what we are comparing you against."))

    rank_rows, rank_hl = [], []
    for i, rd in enumerate(d.ranked):
        isLF = rd.agent.team.startswith("Lightfire")
        team_label = rd.agent.team
        if rd.agent.roster_flag == "departed":
            team_label += " †"
        elif rd.agent.roster_flag == "off_account":
            team_label += " ‡"
        if isLF:
            rank_hl.append(i + 1)
        gross = rd.agent.gross_cents / 100
        per = (gross / rd.agent.matured) if rd.agent.matured else 0
        rank_rows.append([
            str(rd.rank_by_gross),
            Paragraph(f"<b>{rd.name}</b>", S["cellb"]) if (rd.rank_by_gross or 99) <= 6 else rd.name,
            Paragraph(f'<b><font color="{LFH}">{team_label}</font></b>', S["cell"]) if isLF else team_label,
            str(rd.agent.matured),
            f"{rd.matured_sit_pct:.0f}%" if rd.matured_sit_pct is not None else "—",
            str(rd.agent.sold), f"${gross:,.0f}", f"${round(per):,}"])
    s.append(table(
        ["#", "Setter", "Team", "Matured appts", "Matured Sit %", "Sold", "Gross sold", "Gross / appt"],
        rank_rows,
        [0.28 * inch, 1.42 * inch, 0.75 * inch, 0.7 * inch, 0.72 * inch, 0.42 * inch, 0.85 * inch, 0.76 * inch],
        aligns=[(0, "CENTER"), (3, "CENTER"), (4, "CENTER"), (5, "CENTER"), (6, "RIGHT"), (7, "RIGHT")],
        hl=rank_hl))
    s.append(Spacer(1, 4))
    s.append(P(d.page3_footnote, "small"))
    s.append(Spacer(1, 3))
    if d.headline:
        s.append(callout("The line worth sitting with", d.headline.text, LF))

    # ================= PAGE 4
    s.append(P("4.  Staffing and retention", "h1"))
    for para in d.staffing_paras:
        s.append(P(para))
    s.append(Spacer(1, 3))
    if p.retention:
        r = p.retention
        def _money(c):
            return f"${c / 100:,.0f}"
        lf_r, re_r = r.lightfire, r.reece
        lf_net = lf_r.gross_written_cents - lf_r.cancellations_cents - lf_r.financing_denied_cents
        re_net = re_r.gross_written_cents - re_r.cancellations_cents - re_r.financing_denied_cents
        lf_pct = 100.0 * lf_net / lf_r.gross_written_cents if lf_r.gross_written_cents else None
        re_pct = 100.0 * re_net / re_r.gross_written_cents if re_r.gross_written_cents else None
        s.append(table(
            [f"Week of {r.week_label}", "Gross written", "Cancellations", "Financing denied",
             "Net retained", "Retention %"],
            [[Paragraph("<b>Lightfire</b>", S["cellb"]), _money(lf_r.gross_written_cents),
              _money(lf_r.cancellations_cents), _money(lf_r.financing_denied_cents), _money(lf_net),
              C(R if (lf_pct or 0) < 75 else N, f"{lf_pct:.1f}%" if lf_pct is not None else "—")],
             [Paragraph("<b>Reece</b>", S["cellb"]), _money(re_r.gross_written_cents),
              _money(re_r.cancellations_cents), _money(re_r.financing_denied_cents), _money(re_net),
              C(N, f"{re_pct:.1f}%" if re_pct is not None else "—")]],
            [1.3 * inch, 1.0 * inch, 1.05 * inch, 1.1 * inch, 1.0 * inch, 0.95 * inch],
            aligns=[(1, "RIGHT"), (2, "RIGHT"), (3, "RIGHT"), (4, "RIGHT"), (5, "CENTER")], hl=[1]))
        s.append(Spacer(1, 4))
        if d.retention_para:
            s.append(P(d.retention_para, "small"))

    s.append(P("5.  What we are asking for", "h1"))
    imm = [a for a in p.actions if a.tier == "IMMEDIATE" and a.status not in ("DONE", "REMOVED")]
    sec = [a for a in p.actions if a.tier == "SECONDARY" and a.status not in ("DONE", "REMOVED")]
    s.append(P(
        f"{_num_word(len(imm))} immediate items tied to confirmation coverage and bench stability; "
        f"{_num_word(len(sec)).lower()} further review items that should not compete with them for "
        "attention.", "small"))

    def action_rows(items):
        out = []
        for a in items:
            done = a.done_means
            if a.weeks_open >= 1:
                note = f" — last week: {a.last_week_note}" if a.last_week_note else ""
                done = f"{done}<br/><i>Open {a.weeks_open} week{'s' if a.weeks_open != 1 else ''}{note}</i>"
            num_cell = C(R, str(a.number)) if a.status == "ESCALATED" else str(a.number)
            out.append([num_cell, a.title_html, Paragraph(done, S["cell"]), a.by_label])
        return out

    if imm:
        s.append(P("Immediate corrective actions", "h2"))
        s.append(table(["#", "Request", "Done means", "By"], action_rows(imm),
                       [0.28 * inch, 3.5 * inch, 1.7 * inch, 0.6 * inch],
                       aligns=[(0, "CENTER"), (3, "CENTER")]))
    if sec:
        s.append(P("Secondary review items", "h2"))
        s.append(table(["#", "Request", "Done means", "By"], action_rows(sec),
                       [0.28 * inch, 3.5 * inch, 1.7 * inch, 0.6 * inch],
                       aligns=[(0, "CENTER"), (3, "CENTER")]))
    s.append(Spacer(1, 5))
    s.append(callout("Proposed next step", d.next_step, GREEN))

    s.append(P("Method", "h2"))
    s.append(P(d.method_text, "small"))

    doc.build(s)
    pages = doc.page
    if pages != p.config.expected_page_count:
        raise PaginationError(pages, p.config.expected_page_count)
    return BuildResult(out_path, pages, d)


_NUM = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven"}


def _num_word(n: int) -> str:
    return _NUM.get(n, str(n))
