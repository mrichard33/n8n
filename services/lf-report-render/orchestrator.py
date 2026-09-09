"""Weekly pipeline and approval/delivery state machine (Handoff V2 §13).

This is the business logic n8n used to be imagined to hold. It does not touch
HTTP or SMTP: it reads and writes LP state through a Db handle, computes the
frozen payload, renders through the existing build_report, and returns the
fields n8n needs to actually send mail. Keeping it here (not in workflow JSON)
means the maturity rule, the gates and the §14 routing stay unit-tested in one
place; n8n is triggers + HTTP + Gmail only.

build_payload is a pure function (query rows in, ReportPayload out) so the
translation that every downstream number depends on is tested directly, no DB.
The run_* / *_decision / *_delivery functions take a Db (or any object with the
same surface), so they are exercised against an in-memory stand-in in tests.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from assemble import GateFailure
from parsing import classify_reply
from report_builder import BuildResult, PaginationError, build_report
from schema import (ActionItem, AgentRow, ConfigBlock, ConfirmSplit, DiallerDetail,
                    Meta, PriorSnapshot, ReportPayload, SelfGen, SourceMixRow, Staffing, TeamBase)
from windows import Windows, approval_token, compute_windows

# A run in one of these states is already done or in motion — the Monday
# schedule must not start it again (idempotency, §13). BLOCKED and
# GENERATION_FAILED are retryable via Workflow 90 (force=True).
SKIP_STATES = frozenset({
    "INGESTING", "VALIDATING", "READY_FOR_REVIEW", "REVISION_REQUESTED",
    "REGENERATING", "APPROVED", "SENDING", "SENT", "DENIED"})


# ===========================================================================
# Pure translation: query rows -> ReportPayload
# ===========================================================================

def _f(v) -> Optional[float]:
    return None if v is None else float(v)


def _team_key(t: str) -> str:
    return "Reece" if t.startswith("Reece") else "Lightfire"


def _period_label(period_start: date, period_end: date) -> str:
    if period_start.month == period_end.month:
        return f"{period_start.day}–{period_end.day} {period_end:%B}"
    return f"{period_start.day} {period_start:%B} – {period_end.day} {period_end:%B}"


def _by_label(d: Optional[date]) -> str:
    return "" if d is None else f"{d.day} {d:%b}"


def _title_html(title: str) -> str:
    """Bold the lead clause, matching the approved report's action styling.
    The DB title is the canonical text; the em-dash (when present) separates
    the headline from its qualifier."""
    sep = " — "
    if sep in title:
        head, rest = title.split(sep, 1)
        return f"<b>{head}</b>{sep}{rest}"
    return f"<b>{title}</b>"


def build_payload(w: Windows, config: dict, cohort: dict,
                  prior_rows: list[dict], action_rows: list[dict],
                  *, partner_display_name: str = "Lightfire") -> ReportPayload:
    """Translate the frozen query results into the exact render input. Every
    schema validator (window shape, net = gross - cancels, confirmation sums)
    runs on the way out; a violation raises and the caller BLOCKs the run."""
    cfg = ConfigBlock(
        issued_sit_goal=float(config.get("issued_sit_goal", 0.80)),
        small_denominator_min=int(config.get("small_denominator_min", 20)),
        min_matured_for_table=int(config.get("min_matured_for_table", 1)),
        alpha=float(config.get("alpha", 0.05)),
        material_delta_pts=float(config.get("material_delta_pts", 3.0)),
        slight_delta_pts=float(config.get("slight_delta_pts", 1.0)),
        expected_page_count=int(config.get("expected_page_count", 4)))

    meta = Meta(
        run_date=w.run_date, period_start=w.period_start, period_end=w.period_end,
        prior_period_start=w.prior_period_start, prior_period_end=w.prior_period_end,
        cohort_set_start=w.cohort_set_start, cohort_set_end=w.cohort_set_end,
        cohort_appt_cutoff=w.cohort_appt_cutoff, iso_year=w.iso_year, iso_week=w.iso_week,
        version_no=1, partner_display_name=partner_display_name)

    # -- activity (Q6): sets per setter, and Phase-1 staffing counts ----------
    acts = {r["setter_name"]: (int(r["sets_activity_wk"]), int(r["sets_prior_wk"]))
            for r in cohort["activity"]}
    lf_acts = [r for r in cohort["activity"] if r["team"] == "Lightfire"]
    active_now = sum(1 for r in lf_acts if int(r["sets_activity_wk"]) > 0)
    active_prior = sum(1 for r in lf_acts if int(r["sets_prior_wk"]) > 0)
    board_now = sum(int(r["sets_activity_wk"]) for r in lf_acts)
    board_prior = sum(int(r["sets_prior_wk"]) for r in lf_acts)

    # -- agents (Q3) ----------------------------------------------------------
    agents: list[AgentRow] = []
    for r in cohort["agents"]:
        sp, spp = acts.get(r["setter_name"], (0, 0))
        agents.append(AgentRow(
            setter_name=r["setter_name"], team=r["team"], matured=int(r["matured"]),
            gross_issued=int(r["gross_issued"]), cancels=int(r["cancels"]),
            net_issued=int(r["net_issued"]), sat=int(r["sat"]), sold=int(r["sold"]),
            gross_cents=int(r["gross_cents"]), display_name=r.get("display_name"),
            roster_flag=r.get("roster_flag"), sets_period=sp, sets_prior_period=spp,
            no_confirmer=int(r["no_confirmer"]), stranded=int(r["stranded"])))

    # -- team bases (Q2) + confirmation splits (Q5) + self-gen (Q5b) ----------
    totals = {_team_key(t["team"]): t for t in cohort["team_totals"]}
    splits: dict[tuple[str, bool], dict] = {
        (_team_key(s["team"]), bool(s["confirmed"])): s for s in cohort["confirm_splits"]}
    sg = cohort["selfgen"] or {}

    def _split(team: str, confirmed: bool) -> ConfirmSplit:
        s = splits.get((team, confirmed), {})
        return ConfirmSplit(n=int(s.get("n", 0)), issued=int(s.get("issued", 0)),
                            sat=int(s.get("sat", 0)), sold=int(s.get("sold", 0)),
                            stranded=int(s.get("stranded", 0)))

    def _base(team: str, *, stranded_on_reece: Optional[int]) -> TeamBase:
        t = totals[team]
        return TeamBase(
            matured=int(t["matured"]), no_confirmer=int(t["no_confirmer"]),
            confirmed_by_desk=int(t["confirmed_by_desk"]), self_confirmed=int(t["self_confirmed"]),
            confirmed_ai_other=int(t["confirmed_ai_other"]), stranded=int(t["stranded"]),
            cancels_all=int(t["cxl_all"]), confirmed=_split(team, True),
            unconfirmed=_split(team, False), stranded_on_reece_leads=stranded_on_reece)

    lightfire_base = _base("Lightfire", stranded_on_reece=(
        int(sg["stranded_on_reece_leads"]) if sg.get("stranded_on_reece_leads") is not None else None))
    reece_base = _base("Reece", stranded_on_reece=None)

    selfgen = None
    if sg and int(sg.get("selfgen_matured", 0)) > 0:
        selfgen = SelfGen(matured=int(sg["selfgen_matured"]),
                          no_confirmer=int(sg["selfgen_no_confirmer"]),
                          stranded=int(sg["selfgen_stranded"]))

    # -- source mix (Q7) ------------------------------------------------------
    source_mix = [SourceMixRow(source=r["source"], lf_n=int(r["lf_n"]), lf_sat=int(r["lf_sat"]),
                               reece_n=int(r["reece_n"]), reece_sat=int(r["reece_sat"]))
                  for r in cohort["source_mix"] if r["source"]]

    # -- staffing (Phase 1, no Five9 dialler) --------------------------------
    staffing = Staffing(active_agents=active_now, prior_active_agents=active_prior,
                        board_prior=board_prior, board_now=board_now,
                        staffed_output_delta_pct=None, dialler=None)

    # -- prior approved snapshot (Q8, §9) ------------------------------------
    prior = _prior_snapshot(prior_rows, w)

    # -- actions (§10 carry-forward) -----------------------------------------
    actions = [ActionItem(
        number=int(a["sort_order"]), title_html=_title_html(a["title"]),
        done_means=a["success_definition"], by_label=_by_label(a.get("due_date")),
        tier=a["tier"], status=a.get("status", "OPEN"), weeks_open=int(a.get("weeks_open", 0)))
        for a in action_rows]

    return ReportPayload(
        meta=meta, config=cfg, agents=agents, lightfire_base=lightfire_base,
        reece_base=reece_base, selfgen=selfgen, stranded_audit=None, source_mix=source_mix,
        staffing=staffing, retention=None, actions=actions, prior=prior, display_overrides=None)


def _prior_snapshot(prior_rows: list[dict], w: Windows) -> Optional[PriorSnapshot]:
    if not prior_rows:
        return None
    latest_start = max(r["period_start"] for r in prior_rows)
    rows = [r for r in prior_rows if r["period_start"] == latest_start]
    by_team = {_team_key(r["team"]): r for r in rows}
    lf = by_team.get("Lightfire", {})
    reece = by_team.get("Reece", {})
    period_start = latest_start
    period_end = rows[0]["period_end"]
    lf_matured = lf.get("matured") or 0
    lf_noconf_pct = (100.0 * float(lf["no_confirmer"]) / float(lf_matured)) if lf_matured else None
    return PriorSnapshot(
        week_label=_period_label(period_start, period_end),
        is_exactly_prior_week=(period_start == w.prior_period_start),
        lf_issued_sit_pct=_f(lf.get("issued_sit_pct")),
        reece_issued_sit_pct=_f(reece.get("issued_sit_pct")),
        lf_noconf_pct=lf_noconf_pct, unconf_sales=None,
        kpi5_prior=(int(lf["active_agents"]) if lf.get("active_agents") is not None else None))


# ===========================================================================
# Persistence shaping: BuildResult -> frozen metric rows
# ===========================================================================

def _team_metric_rows(d, staffing: Staffing) -> list[dict]:
    def row(total, base, *, active, active_prior):
        matured = base.matured
        return {
            "team": total.team, "matured": matured, "gross_issued": total.gross_issued,
            "cancels_in_issued": total.cancels, "net_issued": total.net_issued, "sat": total.sat,
            "sold": total.sold, "gross_cents": total.gross_cents, "cxl_all": base.cancels_all,
            "stranded": base.stranded, "no_confirmer": base.no_confirmer,
            "confirmed_by_desk": base.confirmed_by_desk, "self_confirmed": base.self_confirmed,
            "confirmed_ai_other": base.confirmed_ai_other,
            "issued_sit_pct": None if total.issued_sit_pct is None else round(total.issued_sit_pct, 2),
            "matured_sit_pct": round(100.0 * total.sat / matured, 2) if matured else None,
            "sits_short": round(total.sits_short, 2), "active_agents": active,
            "active_agents_prior": active_prior,
        }
    p = d.payload
    return [
        row(d.lf_total, p.lightfire_base, active=staffing.active_agents,
            active_prior=staffing.prior_active_agents),
        row(d.reece_total, p.reece_base, active=None, active_prior=None),
    ]


def _agent_metric_rows(d) -> list[dict]:
    rows = []
    for ad in d.ranked:
        a = ad.agent
        rows.append({
            "setter_name": a.setter_name, "display_name": a.display_name, "team": a.team,
            "roster_flag": a.roster_flag, "matured": a.matured, "gross_issued": a.gross_issued,
            "cancels": a.cancels, "net_issued": a.net_issued, "sat": a.sat, "sold": a.sold,
            "gross_cents": a.gross_cents,
            "issued_sit_pct": None if ad.issued_sit_pct is None else round(ad.issued_sit_pct, 2),
            "matured_sit_pct": None if ad.matured_sit_pct is None else round(ad.matured_sit_pct, 2),
            "sits_short": round(ad.sits_short, 2), "sets_period": a.sets_period,
            "sets_prior_period": a.sets_prior_period, "rank_by_gross": ad.rank_by_gross,
            "small_denominator": ad.small_denominator,
        })
    return rows


def _source_snapshot_hash(cohort: dict) -> str:
    material = {k: cohort[k] for k in ("team_totals", "agents", "confirm_splits", "selfgen",
                                       "activity", "source_mix")}
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()


# ===========================================================================
# Approval / vendor email fields (deterministic; n8n only sends)
# ===========================================================================

def approval_email(d, *, token: str, version_no: int, run_id: str, version_id: str,
                   recipients: list[str], warnings: list[str]) -> dict:
    p = d.payload
    label = _period_label(p.meta.period_start, p.meta.period_end)
    lf = d.lf_total
    open_actions = [a for a in p.actions if a.status in ("OPEN", "IN_PROGRESS", "RECURRED")]
    carry = [{"number": a.number, "title": a.title_html, "weeks_open": a.weeks_open,
              "by": a.by_label} for a in open_actions]
    credit_warn = [w for w in warnings if "credit" in w.lower()]
    wow = [{"label": k.label.replace("<br/>", " "), "value": k.value, "delta": k.delta_text}
           for k in d.kpis if k.delta_text]
    filename = f"Lightfire Partner Performance Review — {p.meta.period_end:%d %B %Y}.pdf"
    subject = f"ACTION REQUIRED — Lightfire weekly review, {label} [{token}]"
    html = _approval_html(d, label=label, token=token, version_no=version_no,
                          wow=wow, carry=carry, credit_warn=credit_warn)
    return {
        "subject": subject, "to": recipients, "token": token, "version_no": version_no,
        "run_id": run_id, "version_id": version_id, "pdf_filename": filename,
        "pdf_path": f"/reports/{version_id}/pdf",
        "headline": {
            "lf_issued_sit_pct": None if lf.issued_sit_pct is None else round(lf.issued_sit_pct, 1),
            "reece_issued_sit_pct": None if d.reece_total.issued_sit_pct is None
            else round(d.reece_total.issued_sit_pct, 1),
            "lf_matured": p.lightfire_base.matured, "lf_net_issued": lf.net_issued, "lf_sat": lf.sat,
            "lf_no_confirmer": p.lightfire_base.no_confirmer, "lf_stranded": p.lightfire_base.stranded,
        },
        "wow": wow, "carry_forward": carry, "credit_warning": credit_warn,
        "warnings": warnings, "html": html,
    }


def _approval_html(d, *, label: str, token: str, version_no: int, wow: list[dict],
                   carry: list[dict], credit_warn: list[str]) -> str:
    p = d.payload
    lf, reece = d.lf_total, d.reece_total
    lf_pct = "—" if lf.issued_sit_pct is None else f"{lf.issued_sit_pct:.1f}%"
    reece_pct = "—" if reece.issued_sit_pct is None else f"{reece.issued_sit_pct:.1f}%"
    wow_html = "".join(f"<li>{w['label']}: <b>{w['value']}</b> ({w['delta']})</li>" for w in wow)
    carry_html = "".join(f"<li>#{c['number']} {c['title']} — open {c['weeks_open']}w, by {c['by']}</li>"
                         for c in carry)
    warn_html = ("<p style='color:#A3231C'><b>Warnings:</b> " + "; ".join(credit_warn) + "</p>"
                 if credit_warn else "")
    return f"""<div style="font-family:Helvetica,Arial,sans-serif;font-size:14px;color:#12181F">
<p>The Lightfire weekly partner review for <b>{label}</b> is ready for your approval
(version {version_no}, reference <b>{token}</b>). The PDF is attached.</p>
<p><b>Headline</b> — Lightfire issued sit {lf_pct} against the {100 * p.config.issued_sit_goal:.0f}% goal;
Reece {reece_pct} on the same measure. {p.lightfire_base.matured} matured appointments,
{p.lightfire_base.no_confirmer} with no confirmer of record, {p.lightfire_base.stranded} stranded.</p>
{"<p><b>Week over week</b></p><ul>" + wow_html + "</ul>" if wow_html else ""}
{"<p><b>Open actions carried forward</b></p><ul>" + carry_html + "</ul>" if carry_html else ""}
{warn_html}
<p><b>To decide</b>, reply to this email with one of:</p>
<ul>
<li><b>APPROVED</b> — the report is sent to Lightfire as attached.</li>
<li><b>DENY: &lt;reason&gt;</b> — nothing is sent; we discuss.</li>
<li><b>EDIT: &lt;what to change&gt;</b> — a corrected version is produced for a fresh approval.</li>
</ul>
<p style="color:#5A6673;font-size:12px">Anything else is treated as unclear and the report stays pending —
silence never approves. Reminders follow at 24 and 48 hours.</p>
</div>"""


def vendor_email(version: dict, run: dict, *, period_start: date, period_end: date,
                 recipients: list[str]) -> dict:
    label = _period_label(period_start, period_end)
    filename = f"Lightfire Partner Performance Review — {period_end:%d %B %Y}.pdf"
    subject = f"Lightfire Partner Performance Review — week of {label}"
    html = (f"<div style=\"font-family:Helvetica,Arial,sans-serif;font-size:14px\">"
            f"<p>Please find attached the partner performance review for the week of {label}.</p>"
            f"<p>Reece Windows &amp; Doors</p></div>")
    return {"subject": subject, "to": recipients, "pdf_filename": filename, "html": html}


# ===========================================================================
# Pipeline
# ===========================================================================

@dataclass
class OrchestrationError(Exception):
    status: str          # BLOCKED | GENERATION_FAILED
    reasons: list[str]

    def __str__(self) -> str:
        return f"{self.status}: {'; '.join(self.reasons)}"


def _render(payload: ReportPayload) -> tuple[BuildResult, bytes, str, int]:
    out = os.path.join(tempfile.mkdtemp(prefix="lforch"), "report.pdf")
    started = time.monotonic()
    result = build_report(payload, out)
    render_ms = int((time.monotonic() - started) * 1000)
    with open(result.path, "rb") as fh:
        pdf = fh.read()
    return result, pdf, hashlib.sha256(pdf).hexdigest(), render_ms


def run_weekly(db, run_date: date, *, force: bool = False,
               manual_regeneration: bool = False) -> dict:
    """Workflow-01 steps 3–13. Returns a status dict; on a hard gate it marks
    the run BLOCKED/GENERATION_FAILED and returns that status rather than
    raising, so n8n emails the internal error and stops."""
    if not force and not db.is_report_enabled():
        return {"status": "DISABLED", "skipped": True}

    w = compute_windows(run_date)
    partner_id = db.get_partner_id()

    existing = db.get_existing_run(partner_id, w.period_start, w.period_end)
    if existing and existing["status"] in SKIP_STATES and not force:
        return {"status": existing["status"], "run_id": str(existing["id"]),
                "skipped": True, "idempotent": True}

    run_id, created = db.create_run(partner_id, w, manual_regeneration=manual_regeneration)
    if created:
        db.roll_forward_actions(partner_id)          # §10, once per fresh run
    else:
        db.set_run_status(run_id, "INGESTING")       # force / retry
    db.audit(run_id=run_id, version_id=None, event_type="REPORT_CREATED",
             metadata={"run_date": str(run_date), "force": force})

    cohort = db.fetch_cohort(w)

    # gate #3 — an unmapped setter hard-BLOCKs (a silently-excluded name is how
    # a top setter went missing from a draft).
    if cohort["unmapped"]:
        names = [r["unmapped_setter"] for r in cohort["unmapped"]]
        return _block(db, run_id, ["unmapped setters: " + ", ".join(names[:10])])

    # gate #2 — zero matured must block, never render an empty week.
    totals = {_team_key(t["team"]): t for t in cohort["team_totals"]}
    if "Lightfire" not in totals or int(totals["Lightfire"]["matured"]) <= 0:
        return _block(db, run_id, ["Lightfire cohort has zero matured appointments"])
    if "Reece" not in totals or int(totals["Reece"]["matured"]) <= 0:
        return _block(db, run_id, ["Reece cohort has zero matured appointments"])

    prior_rows = db.get_prior_snapshot(partner_id, w)
    action_rows = db.get_actions(partner_id)

    try:
        payload = build_payload(w, db.get_config(), cohort, prior_rows, action_rows)
    except Exception as e:                            # pydantic ValidationError etc.
        return _block(db, run_id, [f"payload build failed (gate #1/#4/#6): {e}"])

    db.set_run_status(run_id, "VALIDATING")
    db.audit(run_id=run_id, version_id=None, event_type="SOURCE_SNAPSHOT_TAKEN",
             metadata={"source_snapshot_hash": _source_snapshot_hash(cohort)})

    try:
        result, pdf, pdf_sha, render_ms = _render(payload)
    except GateFailure as g:
        return _block(db, run_id, [f"validation gate: {'; '.join(g.failures)}"])
    except PaginationError as e:
        db.set_run_status(run_id, "GENERATION_FAILED",
                          blocked_reason=f"pagination: {e.pages} pages")
        db.audit(run_id=run_id, version_id=None, event_type="VALIDATION_FAILED",
                 metadata={"error": "pagination", "pages": e.pages})
        return {"status": "GENERATION_FAILED", "run_id": run_id, "reasons": [str(e)]}

    d = result.derived
    version_no = payload.meta.version_no
    token = approval_token(w.iso_year, w.iso_week, version_no)
    recipients = sorted(db.get_approvers())
    payload_json = payload.model_dump(mode="json")

    ids = db.persist_version(
        run_id=run_id, version_no=version_no, payload=payload_json,
        payload_sha256=hashlib.sha256(json.dumps(payload_json, sort_keys=True).encode()).hexdigest(),
        pdf_bytes=pdf, pdf_sha256=pdf_sha, page_count=result.page_count, render_ms=render_ms,
        source_snapshot_hash=_source_snapshot_hash(cohort),
        team_metrics=_team_metric_rows(d, payload.staffing), agent_metrics=_agent_metric_rows(d),
        report_metrics=d.metrics_record(), approval_token=token, sent_to=recipients)

    db.audit(run_id=run_id, version_id=ids["version_id"], event_type="APPROVAL_REQUESTED",
             metadata={"token": token, "recipients": recipients})
    email = approval_email(d, token=token, version_no=version_no, run_id=run_id,
                           version_id=ids["version_id"], recipients=recipients, warnings=d.warnings)
    return {"status": "READY_FOR_REVIEW", "run_id": run_id, "version_id": ids["version_id"],
            "approval_token": token, "page_count": result.page_count, "pdf_sha256": pdf_sha,
            "warnings": d.warnings, "email": email}


def _block(db, run_id: str, reasons: list[str]) -> dict:
    db.set_run_status(run_id, "BLOCKED", blocked_reason="; ".join(reasons),
                      validation_report={"failures": reasons})
    db.audit(run_id=run_id, version_id=None, event_type="VALIDATION_FAILED",
             metadata={"failures": reasons})
    return {"status": "BLOCKED", "run_id": run_id, "reasons": reasons}


# ===========================================================================
# Approval decision (§14 routing)
# ===========================================================================

def apply_decision(db, *, token: str, sender_email: str, raw_reply: str, channel: str) -> dict:
    rec = db.get_run_by_token(token)
    if not rec:
        return {"action": "noop", "reason": "unknown_token"}
    ar_id = str(rec["approval_request_id"])
    run_id = str(rec["run_id"])
    version_id = str(rec["version_id"])
    sender = (sender_email or "").strip().lower()
    approvers = db.get_approvers()

    cls = classify_reply(raw_reply)

    if rec["run_status"] != "READY_FOR_REVIEW":
        # A late APPROVED on an already-approved/sent run is a duplicate, not an
        # error; anything else on a settled run is a no-op.
        db.record_approval_event(
            approval_request_id=ar_id, actor_email=sender or None,
            classification=cls.classification, revision_kind=cls.revision_kind,
            raw_reply=raw_reply, cleaned_reply=cls.cleaned, channel=channel,
            accepted=False, reject_reason=f"run already {rec['run_status']}")
        return {"action": "noop", "reason": f"run_{rec['run_status'].lower()}",
                "run_id": run_id}

    if sender not in approvers:
        db.record_approval_event(
            approval_request_id=ar_id, actor_email=sender or None, classification="UNAUTHORIZED",
            revision_kind=None, raw_reply=raw_reply, cleaned_reply=cls.cleaned, channel=channel,
            accepted=False, reject_reason="sender not an active approver")
        db.audit(run_id=run_id, version_id=version_id, event_type="APPROVAL_REQUESTED",
                 actor=sender or "unknown", metadata={"unauthorized": True})
        return {"action": "unauthorized", "alert": True, "sender": sender, "run_id": run_id}

    if cls.classification == "APPROVED":
        db.resolve_approval(approval_request_id=ar_id, run_id=run_id, outcome="APPROVED",
                            approved_version_id=version_id, run_status="APPROVED")
        db.record_approval_event(approval_request_id=ar_id, actor_email=sender,
                                 classification="APPROVED", revision_kind=None, raw_reply=raw_reply,
                                 cleaned_reply=cls.cleaned, channel=channel, accepted=True)
        db.audit(run_id=run_id, version_id=version_id, event_type="APPROVED", actor=sender)
        return {"action": "approved", "deliver": True, "run_id": run_id, "version_id": version_id}

    if cls.classification == "DENY":
        db.resolve_approval(approval_request_id=ar_id, run_id=run_id, outcome="DENIED",
                            run_status="DENIED")
        db.record_approval_event(approval_request_id=ar_id, actor_email=sender, classification="DENY",
                                 revision_kind=None, raw_reply=raw_reply, cleaned_reply=cls.cleaned,
                                 channel=channel, accepted=True, reject_reason=cls.reason)
        db.audit(run_id=run_id, version_id=version_id, event_type="DENIED", actor=sender,
                 metadata={"reason": cls.reason})
        return {"action": "deny", "notify_internal": True, "reason": cls.reason, "run_id": run_id}

    if cls.classification == "EDIT":
        db.resolve_approval(approval_request_id=ar_id, run_id=run_id, outcome="EDIT",
                            run_status="REVISION_REQUESTED")
        db.record_approval_event(approval_request_id=ar_id, actor_email=sender, classification="EDIT",
                                 revision_kind=cls.revision_kind, raw_reply=raw_reply,
                                 cleaned_reply=cls.cleaned, channel=channel, accepted=True)
        db.audit(run_id=run_id, version_id=version_id, event_type="EDIT_REQUESTED", actor=sender,
                 metadata={"revision_kind": cls.revision_kind, "instruction": cls.instruction})
        return {"action": "edit", "revision_kind": cls.revision_kind, "instruction": cls.instruction,
                "run_id": run_id}

    # UNKNOWN — never guess; clarify and stay pending.
    db.record_approval_event(approval_request_id=ar_id, actor_email=sender, classification="UNKNOWN",
                             revision_kind=None, raw_reply=raw_reply, cleaned_reply=cls.cleaned,
                             channel=channel, accepted=False, reject_reason="unrecognised reply")
    return {"action": "unknown", "clarify": True, "run_id": run_id}


# ===========================================================================
# Revision (§13.3)
# ===========================================================================

def _apply_overrides(payload_json: dict, overrides: list[dict]) -> dict:
    """Apply data corrections to the FROZEN payload (never a fresh live pull —
    D3), then let schema validation reject an inconsistent correction."""
    p = json.loads(json.dumps(payload_json))  # deep copy
    for ov in overrides:
        scope, key, field, value = ov["scope"], ov["scope_key"], ov["field"], ov["override_value"]
        if scope == "agent":
            for a in p["agents"]:
                if a["setter_name"] == key or a.get("display_name") == key:
                    a[field] = value
                    a["net_issued"] = a["gross_issued"] - a["cancels"]
        elif scope == "team":
            base = p["lightfire_base"] if key == "Lightfire" else p["reece_base"]
            base[field] = value
    return p


def revise(db, *, run_id: str, revision_kind: str, instruction: str, requested_by: str,
           overrides: Optional[list[dict]] = None) -> dict:
    run = db.get_run(run_id)
    if not run:
        return {"ok": False, "reason": "unknown_run"}
    if run["status"] not in ("REVISION_REQUESTED", "READY_FOR_REVIEW"):
        return {"ok": False, "reason": f"run_{run['status'].lower()}"}
    latest = db.get_latest_version(run_id)
    new_version_no = int(latest["version_no"]) + 1

    payload_json = latest["payload"]
    if revision_kind == "DATA_CORRECTION" and overrides:
        payload_json = _apply_overrides(payload_json, overrides)
        for ov in overrides:
            db.insert_override(run_id=run_id, scope=ov["scope"], scope_key=ov["scope_key"],
                               field=ov["field"], original_value=ov.get("original_value"),
                               override_value=ov["override_value"],
                               reason=ov.get("reason", instruction), requested_by=requested_by)

    payload_json = json.loads(json.dumps(payload_json))
    payload_json["meta"]["version_no"] = new_version_no
    db.set_run_status(run_id, "REGENERATING")

    try:
        payload = ReportPayload.model_validate(payload_json)
        result, pdf, pdf_sha, render_ms = _render(payload)
    except GateFailure as g:
        return _block(db, run_id, [f"revision gate: {'; '.join(g.failures)}"]) | {"ok": False}
    except PaginationError as e:
        db.set_run_status(run_id, "GENERATION_FAILED", blocked_reason=f"pagination: {e.pages}")
        return {"ok": False, "status": "GENERATION_FAILED", "reasons": [str(e)]}
    except Exception as e:
        return {"ok": False, "reason": f"revision_invalid: {e}"}

    d = result.derived
    w = compute_windows(payload.meta.run_date)
    token = approval_token(w.iso_year, w.iso_week, new_version_no)
    recipients = sorted(db.get_approvers())
    pj = payload.model_dump(mode="json")
    ids = db.persist_version(
        run_id=run_id, version_no=new_version_no, payload=pj,
        payload_sha256=hashlib.sha256(json.dumps(pj, sort_keys=True).encode()).hexdigest(),
        pdf_bytes=pdf, pdf_sha256=pdf_sha, page_count=result.page_count, render_ms=render_ms,
        source_snapshot_hash=latest.get("source_snapshot_hash") or "",
        team_metrics=_team_metric_rows(d, payload.staffing), agent_metrics=_agent_metric_rows(d),
        report_metrics=d.metrics_record(), approval_token=token, sent_to=recipients,
        revision_reason=instruction, revision_kind=revision_kind)
    db.audit(run_id=run_id, version_id=ids["version_id"], event_type="VERSION_GENERATED",
             actor=requested_by, metadata={"version_no": new_version_no, "kind": revision_kind})
    email = approval_email(d, token=token, version_no=new_version_no, run_id=run_id,
                           version_id=ids["version_id"], recipients=recipients, warnings=d.warnings)
    return {"ok": True, "status": "READY_FOR_REVIEW", "run_id": run_id,
            "version_id": ids["version_id"], "approval_token": token, "email": email}


# ===========================================================================
# Delivery (§13.4 — hash-verified, recipients-guarded)
# ===========================================================================

def _delivery_guards(db, version_id: str) -> tuple[Optional[dict], Optional[dict], Optional[dict]]:
    version = db.get_version(version_id)
    if not version:
        return None, None, {"ok": False, "reason": "unknown_version", "abort": True}
    run = db.get_run(str(version["run_id"]))
    if run["status"] not in ("APPROVED", "SENDING"):
        return version, run, {"ok": False, "reason": f"run_{run['status'].lower()}", "abort": True}
    if str(run.get("approved_version_id")) != str(version_id):
        return version, run, {"ok": False, "reason": "not_the_approved_version", "abort": True}
    if run.get("sent_at") is not None:
        return version, run, {"ok": False, "reason": "already_sent", "abort": True}
    return version, run, None


def prepare_delivery(db, version_id: str) -> dict:
    version, run, err = _delivery_guards(db, version_id)
    if err:
        return err | {"alert": True}
    recipients = db.get_vendor_recipients(str(run["partner_id"]))
    if not recipients:
        # An approved run with no vendor recipients aborts loudly — never
        # "sent to nobody". This is the go-live guard until Mark seeds addresses.
        return {"ok": False, "reason": "no_recipients", "abort": True, "alert": True,
                "run_id": str(run["id"]), "version_id": version_id}
    pdf = db.get_pdf(version_id)
    if not pdf:
        return {"ok": False, "reason": "pdf_missing", "abort": True, "alert": True}
    recomputed = hashlib.sha256(pdf["pdf_bytes"]).hexdigest()
    approved = version["pdf_sha256"]
    if recomputed != approved or recomputed != pdf["sha256"]:
        db.audit(run_id=str(run["id"]), version_id=version_id, event_type="FAILED",
                 metadata={"hash_mismatch": True, "approved": approved, "recomputed": recomputed})
        return {"ok": False, "reason": "hash_mismatch", "abort": True, "alert": True,
                "approved_sha256": approved, "recomputed_sha256": recomputed}
    vmail = vendor_email(version, run, period_start=run["period_start"],
                         period_end=run["period_end"], recipients=recipients)
    db.set_run_status(str(run["id"]), "SENDING")
    return {"ok": True, "run_id": str(run["id"]), "version_id": version_id,
            "recipients": recipients, "approved_sha256": approved, "sent_sha256": recomputed,
            "pdf_path": f"/reports/{version_id}/pdf", "email": vmail}


def confirm_delivery(db, version_id: str, *, provider_message_id: Optional[str] = None) -> dict:
    version, run, err = _delivery_guards(db, version_id)
    if err and err.get("reason") != "run_sending":
        return err
    version = version or db.get_version(version_id)
    run = run or db.get_run(str(version["run_id"]))
    pdf = db.get_pdf(version_id)
    recomputed = hashlib.sha256(pdf["pdf_bytes"]).hexdigest()
    approved = version["pdf_sha256"]
    verified = (recomputed == approved)
    recipients = db.get_vendor_recipients(str(run["partner_id"]))
    db.record_delivery_event(run_id=str(run["id"]), version_id=version_id, approved_sha256=approved,
                             sent_sha256=recomputed, hash_verified=verified, recipients=recipients,
                             provider_message_id=provider_message_id)
    db.audit(run_id=str(run["id"]), version_id=version_id,
             event_type="SENT" if verified else "FAILED",
             metadata={"hash_verified": verified, "provider_message_id": provider_message_id})
    if not verified:
        return {"ok": False, "reason": "hash_mismatch", "approved_sha256": approved,
                "recomputed_sha256": recomputed}
    return {"ok": True, "status": "SENT", "run_id": str(run["id"]), "recipients": recipients}


# ===========================================================================
# Reminders (§13.2 — never auto-approves)
# ===========================================================================

def reminders_tick(db, *, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cfg = db.get_config()
    thresholds = sorted(cfg.get("approval_reminder_hours", [24, 48]))
    due = []
    for ar in db.pending_approvals():
        sent_at = ar["sent_at"]
        hours = (now - sent_at).total_seconds() / 3600.0
        n_due = sum(1 for h in thresholds if hours >= h)
        n_sent = len(ar.get("reminded_at") or [])
        if n_due > n_sent:
            db.append_reminded_at(str(ar["approval_request_id"]), now)
            db.audit(run_id=str(ar["run_id"]), version_id=None, event_type="REMINDER_SENT",
                     metadata={"tier_hours": thresholds[n_sent], "hours_elapsed": round(hours, 1)})
            due.append({"run_id": str(ar["run_id"]), "token": ar["approval_token"],
                        "sent_to": ar["sent_to"], "tier_hours": thresholds[n_sent]})
    return {"reminders": due}
