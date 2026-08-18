"""Single derivation pass: ReportPayload -> everything the renderer places on
the page, plus the derived record the orchestrator persists to
lf_report_metrics. /validate and /render both run THIS function on the same
frozen payload, so the persisted metrics and the rendered document cannot
diverge.

All §15 gate checks that concern payload content run here (hard failures raise
GateFailure; soft findings accumulate as warnings for the approval email).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time

from calculations import (
    AgentDerived, FinancialOpportunity, TeamDisplayTotal, actions_state,
    confirmer_gap, derive_agent, financial_opportunity, goal_status,
    rank_by_gross, select_display_rows, sit_trend, staffing_trend,
    team_display_total,
)
from narrative import (
    HELD_CONSTANT, LF_BOX, PAGE2_AUDIT_ABSENT, PAGE2_AUDIT_FULL,
    PAGE2_DOWNSTREAM, PAGE2_DOWNSTREAM_NONZERO, PAGE2_VERDICT,
    PAGE2_VERDICT_CLOSE, REECE_BOX, RETENTION_OUTLIER, SOURCE_MIX_FOOT,
    STAFFING_LEAD, STAFFING_MOVEMENT, STAFFING_OFFDIALLER,
    executive_paragraph, kpi_delta_line, trend_clause,
)
from report_selectors import CreditResult, HeadlineObservation, select_credit, select_headline
from schema import ReportPayload, TeamBase
from stats_engine import StatTest, run_test, source_mix_test, verdict_cell
from windows import ET, et_abbrev


class GateFailure(Exception):
    """A §15 hard failure. The orchestrator marks the run BLOCKED."""

    def __init__(self, failures: list[str]):
        self.failures = failures
        super().__init__("; ".join(failures))


_NUM_WORDS = {0: "Zero", 1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
              6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten",
              11: "Eleven", 12: "Twelve", 13: "Thirteen", 14: "Fourteen",
              15: "Fifteen", 16: "Sixteen", 17: "Seventeen", 18: "Eighteen",
              19: "Nineteen", 20: "Twenty"}
_NUM_WORDS_LOWER = {k: v.lower() for k, v in _NUM_WORDS.items()}


def _word(n: int) -> str:
    return _NUM_WORDS.get(n, str(n))


def _dmon(d: date) -> str:
    return f"{d.day} {d.strftime('%B')}"


def _first_last(name: str) -> str:
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return name


@dataclass
class KpiCard:
    value: str
    label: str
    color_key: str          # 'G' | 'R' | 'A' | 'N'
    delta_text: str = ""
    delta_class: str = "flat"  # 'good' | 'bad' | 'flat'


@dataclass
class Derived:
    """Everything the builder places, plus the persistable record."""
    payload: ReportPayload
    lf_rows: list[AgentDerived]
    reece_rows: list[AgentDerived]
    lf_total: TeamDisplayTotal
    reece_total: TeamDisplayTotal
    ranked: list[AgentDerived]
    kpis: list[KpiCard]
    exec_paragraph: str
    credit: CreditResult
    headline: HeadlineObservation | None
    test_noconf: StatTest
    test_strand: StatTest
    source_mix: object
    fin: FinancialOpportunity
    potential_display_cents: float | None
    narrative_states: dict
    page1_footnote: str
    page2_audit: str
    page2_table_rows: list
    page2_held_constant: str
    page2_downstream: str
    reece_box: str
    lf_box: str
    source_mix_foot: str
    page3_footnote: str
    staffing_paras: list[str]
    retention_para: str | None
    next_step: str
    method_text: str
    warnings: list[str] = field(default_factory=list)
    stat_records: list[dict] = field(default_factory=list)

    def metrics_record(self) -> dict:
        """The lf_report_metrics row content, persisted by the orchestrator."""
        return {
            "stat_tests": self.stat_records,
            "narrative_states": self.narrative_states,
            "source_mix_state": self.source_mix.state,
            "credit_observations": [c.as_record() for c in self.credit.observations],
            "headline_observation": self.headline.as_record() if self.headline else None,
            "financial_opportunity": self.fin.as_record(),
            "team_display_totals": {
                t.team: {"gross_issued": t.gross_issued, "cancels": t.cancels,
                         "net_issued": t.net_issued, "sat": t.sat, "sold": t.sold,
                         "gross_cents": t.gross_cents,
                         "issued_sit_pct": None if t.issued_sit_pct is None else round(t.issued_sit_pct, 4),
                         "sits_short": round(t.sits_short, 2)}
                for t in (self.lf_total, self.reece_total)
            },
        }


def assemble(p: ReportPayload) -> Derived:  # noqa: C901 — one deliberate pass
    cfg = p.config
    goal = cfg.issued_sit_goal
    goal_pct = 100.0 * goal
    warnings: list[str] = []
    hard: list[str] = []

    # ---- gates #2/#3-adjacent (roster resolution is checked upstream in SQL;
    # here: every agent row already carries a team) --------------------------
    lfb, rb = p.lightfire_base, p.reece_base
    if lfb.matured <= 0 or rb.matured <= 0:
        hard.append("a team has zero matured appointments")

    # ---- derive agents -----------------------------------------------------
    derived_all = [derive_agent_from_row(a, goal=goal, small_min=cfg.small_denominator_min) for a in p.agents]
    lf_rows = select_display_rows(derived_all, "Lightfire", min_matured=cfg.min_matured_for_table)
    reece_rows_all = [d for d in derived_all if d.agent.team.startswith("Reece")]
    reece_rows = sorted(
        [d for d in reece_rows_all if d.agent.matured >= cfg.min_matured_for_table],
        key=lambda d: (d.issued_sit_pct is None, -(d.issued_sit_pct or 0.0), d.name))
    if not lf_rows or not reece_rows:
        hard.append("a team has no displayable agent rows")
    if hard:
        raise GateFailure(hard)

    ranked = rank_by_gross(derived_all)

    # ---- THE totals (one derivation, one call site per team) ---------------
    lf_total = team_display_total(lf_rows, goal=goal)
    reece_total = team_display_total(reece_rows, goal=goal)

    # gate #5: agent rows sum to team totals — checked on the DERIVED totals,
    # before any golden-fixture pin. With the matured floor at 1 this is true
    # by construction; assert it anyway so a future filter change cannot
    # silently break it.
    for total, rows in ((lf_total, lf_rows), (reece_total, reece_rows)):
        assert total.sat == sum(r.agent.sat for r in rows)
        assert total.net_issued == sum(r.agent.net_issued for r in rows)

    ov = p.display_overrides
    if ov and ov.reece_total:
        # Golden-fixture-only historical literal (see schema.DisplayOverrides).
        rt = ov.reece_total
        pct = 100.0 * rt.sat / rt.net_issued if rt.net_issued else None
        reece_total = TeamDisplayTotal(
            team="Reece", gross_issued=rt.gross_issued, cancels=rt.cancels,
            net_issued=rt.net_issued, sat=rt.sat,
            sold=reece_total.sold, gross_cents=reece_total.gross_cents,
            issued_sit_pct=pct,
            vs_goal_pts=None if pct is None else pct - goal_pct,
            sits_short=max(0.0, goal * rt.net_issued - rt.sat))
    if ov and (ov.reece_total or ov.potential_gross_cents is not None):
        warnings.append("display_overrides present — historical golden-fixture pins in payload; "
                        "a production run must never carry these")

    # gate #7: every displayed percentage recomputes from its stored parts —
    # inherent here because nothing is passed in pre-computed; gate #8 (no
    # NaN/null/negative in displayed cells) is enforced by formatters raising
    # on None where a number is mandatory.

    # ---- statistics (full-cohort bases ONLY) -------------------------------
    # gate #9 (hard): invalid statistical inputs BLOCK the run.
    try:
        test_noconf = run_test("no_confirmer_rate_by_team",
                               lfb.no_confirmer, lfb.matured, rb.no_confirmer, rb.matured,
                               alpha=cfg.alpha)
        test_strand = run_test("strand_rate_given_no_confirmer",
                               lfb.unconfirmed.stranded, lfb.unconfirmed.n,
                               rb.unconfirmed.stranded, rb.unconfirmed.n,
                               alpha=cfg.alpha)
    except ValueError as e:
        raise GateFailure([f"statistical inputs invalid (gate #9): {e}"])
    mix = source_mix_test([r.model_dump() for r in p.source_mix], alpha=cfg.alpha)
    stat_records = [test_noconf.as_record(), test_strand.as_record()]
    if mix.z is not None:
        stat_records.append({"name": "source_mix_standardised", "s1_n": None, "s1_x": None,
                             "s2_n": None, "s2_x": None, "z": round(mix.z, 4),
                             "p": None if mix.p is None else round(mix.p, 6),
                             "alpha": cfg.alpha, "verdict": mix.state})

    lf_noconf_pct = 100.0 * lfb.no_confirmer / lfb.matured
    reece_noconf_pct = 100.0 * rb.no_confirmer / rb.matured
    desk_share_lf = 100.0 * lfb.confirmed_by_desk / lfb.matured
    desk_share_reece = 100.0 * rb.confirmed_by_desk / rb.matured

    # ---- narrative states --------------------------------------------------
    prior = p.prior
    trend_state, trend_delta = sit_trend(
        lf_total.issued_sit_pct, prior.lf_issued_sit_pct if prior else None,
        material=cfg.material_delta_pts, slight=cfg.slight_delta_pts)
    g_status = goal_status(lf_total.issued_sit_pct, goal_pct=goal_pct)
    staffing = p.staffing
    st_trend = staffing_trend(staffing.active_agents, staffing.prior_active_agents) if staffing else "STABLE"
    c_gap = confirmer_gap(lf_noconf_pct, reece_noconf_pct)
    open_actions = [a for a in p.actions if a.status in ("OPEN", "IN_PROGRESS", "RECURRED")]
    esc = [a for a in p.actions if a.status == "ESCALATED"]
    a_state = actions_state(len(open_actions), len(esc), 0)
    states = {
        "sit_trend": trend_state, "goal_status": g_status,
        "stat_verdict": test_strand.verdict, "source_mix": mix.state,
        "staffing_trend": st_trend, "confirmer_gap": c_gap, "actions": a_state,
    }

    # ---- financial opportunity --------------------------------------------
    fin = financial_opportunity(lf_total)
    potential = fin.potential_gross_cents
    if p.display_overrides and p.display_overrides.potential_gross_cents is not None:
        potential = float(p.display_overrides.potential_gross_cents)

    # ---- KPI band (§9 third row) ------------------------------------------
    unconf_total = lfb.unconfirmed.n + rb.unconfirmed.n
    unconf_sales = lfb.unconfirmed.sold + rb.unconfirmed.sold
    dialler = staffing.dialler if staffing else None
    kpi5_now = dialler.agents_on_dialler if dialler else (staffing.active_agents if staffing else None)
    kpi5_prior = dialler.prior_agents_on_dialler if dialler else (staffing.prior_active_agents if staffing else None)
    kpi5_label = ("Your agents on our<br/>dialler, in one week" if dialler
                  else "Your agents setting<br/>appointments, week to week")

    def _kpi1_color():
        return {"AT_OR_ABOVE": "G", "WITHIN_5": "A"}.get(g_status, "R")

    kpis = [
        KpiCard(f"{lf_total.issued_sit_pct:.1f}%",
                f"Your sit % against<br/>our {goal_pct:.0f}% goal", _kpi1_color()),
        KpiCard(f"{reece_total.issued_sit_pct:.1f}%", "Reece setters,<br/>same measure", "N"),
        KpiCard(f"{lf_noconf_pct:.0f}%", "Your appointments with<br/>no confirmer of record",
                "R" if c_gap in ("WIDE", "MODERATE") else "N"),
        KpiCard(f"{unconf_sales}",
                f"Sales from {unconf_total} appts with<br/>no confirmer, either team",
                "R" if unconf_sales == 0 else "A"),
        KpiCard(f"{kpi5_prior} → {kpi5_now}" if kpi5_now is not None else "—",
                kpi5_label,
                {"GREW": "G", "STABLE": "N"}.get(st_trend, "R")),
    ]
    if prior:
        d1 = None if (prior.lf_issued_sit_pct is None or lf_total.issued_sit_pct is None) \
            else lf_total.issued_sit_pct - prior.lf_issued_sit_pct
        d2 = None if (prior.reece_issued_sit_pct is None or reece_total.issued_sit_pct is None) \
            else reece_total.issued_sit_pct - prior.reece_issued_sit_pct
        d3 = None if prior.lf_noconf_pct is None else lf_noconf_pct - prior.lf_noconf_pct
        d4 = None if prior.unconf_sales is None else float(unconf_sales - prior.unconf_sales)
        d5 = None if (prior.kpi5_prior is None or kpi5_now is None) else float(kpi5_now - prior.kpi5_prior)
        for card, delta, unit, fav_up in (
                (kpis[0], d1, "pts", True), (kpis[1], d2, "pts", True),
                (kpis[2], d3, "pts", False), (kpis[3], d4, "", False),
                (kpis[4], d5, "", True)):
            card.delta_text, card.delta_class = kpi_delta_line(delta, unit=unit, favourable_up=fav_up)

    # ---- exec paragraph ----------------------------------------------------
    week_named = None if (prior and prior.is_exactly_prior_week) else (prior.week_label if prior else None)
    exec_para = executive_paragraph(
        goal_pct=goal_pct, lf_pct=lf_total.issued_sit_pct, reece_pct=reece_total.issued_sit_pct,
        lf_noconf_pct=lf_noconf_pct, reece_noconf_pct=reece_noconf_pct,
        desk_share_lf_pct=desk_share_lf, desk_share_reece_pct=desk_share_reece,
        stat_verdict=test_strand.verdict,
        trend=trend_clause(trend_state, trend_delta,
                           prior.lf_issued_sit_pct if prior else None, week_named))

    # ---- credit + headline -------------------------------------------------
    conf_issue = lambda b: (100.0 * b.confirmed.issued / b.confirmed.n) if b.confirmed.n else None  # noqa: E731
    week_label = _dmon(p.meta.period_start)
    credit = select_credit(
        [d for d in derived_all if d.agent.team == "Lightfire"], ranked,
        goal_pct=goal_pct, week_label=week_label,
        lf_week_sets={a.setter_name: a.sets_period for a in p.agents},
        team_sit_pct=lf_total.issued_sit_pct,
        team_sit_prior_pct=prior.lf_issued_sit_pct if prior else None,
        lf_conf_issue_pct=conf_issue(lfb), reece_conf_issue_pct=conf_issue(rb),
        active_agents=staffing.active_agents if staffing else 0,
        prior_active_agents=staffing.prior_active_agents if staffing else 0,
        staffed_output_delta_pct=staffing.staffed_output_delta_pct if staffing else None)
    if credit.neutral_fallback_used:
        warnings.append("credit selector: zero qualifiers — neutral fallback line used (§8)")
    elif len(credit.observations) < 3:
        warnings.append(f"credit selector: only {len(credit.observations)} qualifier(s) this week")

    headline = select_headline(
        [d for d in derived_all if d.agent.team == "Lightfire"], ranked,
        goal_pct=goal_pct,
        agent_noconf_pct={a.setter_name: (100.0 * a.no_confirmer / a.matured if a.matured else 0.0)
                          for a in p.agents},
        agent_strand_pct={a.setter_name: (100.0 * a.stranded / a.matured if a.matured else 0.0)
                          for a in p.agents},
        team_noconf_pct=lf_noconf_pct)
    if headline is None:
        warnings.append("headline: no Lightfire agent at net_issued >= 20 — callout omitted")

    # ---- page 1 footnote ---------------------------------------------------
    volume = [r for r in lf_rows if not r.small_denominator]
    vol_list = ", ".join(f"{_first_last(r.name).split()[-1]} {r.issued_sit_pct:.1f}%"
                         for r in sorted(volume, key=lambda r: r.issued_sit_pct or 0))
    n_vol = len(volume)
    vol_sentence = (
        f"<b>The {_NUM_WORDS_LOWER.get(n_vol, str(n_vol))} agents carrying real volume are the ones "
        f"that matter: {vol_list}.</b> " if n_vol else "")
    potential_txt = (f" — at your observed close rate and ticket, approximately "
                     f"<b>${potential / 100:,.0f} in potential gross written business</b>. An estimate, "
                     f"not revenue we can claim would certainly have occurred."
                     if potential is not None else ".")
    page1_footnote = (
        f"* denominator under {cfg.small_denominator_min} — shown for completeness, not judgement. "
        f"{vol_sentence}Bringing your book to {goal_pct:.0f}% is <b>{lf_total.sits_short:.0f} more sits "
        f"over six weeks</b>{potential_txt}")

    # ---- page 2 ------------------------------------------------------------
    audit = p.stranded_audit
    if audit:
        page2_audit = PAGE2_AUDIT_FULL.format(
            stranded_n=lfb.stranded, any_evidence_n=_word(audit.any_evidence_n),
            desk_reached_n=_word(audit.desk_reached_n))
    else:
        page2_audit = PAGE2_AUDIT_ABSENT.format(stranded_n=lfb.stranded)

    lf_strand_pct = 100.0 * lfb.unconfirmed.stranded / lfb.unconfirmed.n if lfb.unconfirmed.n else 0.0
    reece_strand_pct = 100.0 * rb.unconfirmed.stranded / rb.unconfirmed.n if rb.unconfirmed.n else 0.0
    page2_rows = {
        "lf_matured": lfb.matured, "reece_matured": rb.matured,
        "lf_noconf": lfb.no_confirmer, "lf_noconf_pct": lf_noconf_pct,
        "reece_noconf": rb.no_confirmer, "reece_noconf_pct": reece_noconf_pct,
        "lf_desk": lfb.confirmed_by_desk, "lf_desk_pct": desk_share_lf,
        "reece_desk": rb.confirmed_by_desk, "reece_desk_pct": desk_share_reece,
        "lf_self": lfb.self_confirmed, "lf_self_pct": 100.0 * lfb.self_confirmed / lfb.matured,
        "reece_self": rb.self_confirmed, "reece_self_pct": 100.0 * rb.self_confirmed / rb.matured,
        "lf_strand": lfb.unconfirmed.stranded, "lf_unconf": lfb.unconfirmed.n,
        "lf_strand_pct": lf_strand_pct,
        "reece_strand": rb.unconfirmed.stranded, "reece_unconf": rb.unconfirmed.n,
        "reece_strand_pct": reece_strand_pct,
        "verdict_noconf": verdict_cell(test_noconf), "verdict_strand": verdict_cell(test_strand),
    }
    held = PAGE2_VERDICT[test_strand.verdict].format(
        lf_strand_pct=lf_strand_pct, reece_strand_pct=reece_strand_pct) + PAGE2_VERDICT_CLOSE

    rng = lambda a, b: f"{min(a, b):.0f}–{max(a, b):.0f}%"  # noqa: E731
    spct = lambda x, n: (100.0 * x / n) if n else 0.0  # noqa: E731 — degenerate slice reads 0%
    conf_issue_rng = rng(spct(lfb.confirmed.issued, lfb.confirmed.n),
                         spct(rb.confirmed.issued, rb.confirmed.n))
    conf_sit_rng = rng(spct(lfb.confirmed.sat, lfb.confirmed.n),
                       spct(rb.confirmed.sat, rb.confirmed.n))
    unconf_issue_rng = rng(spct(lfb.unconfirmed.issued, lfb.unconfirmed.n),
                           spct(rb.unconfirmed.issued, rb.unconfirmed.n))
    downstream_tpl = PAGE2_DOWNSTREAM if unconf_sales == 0 else PAGE2_DOWNSTREAM_NONZERO
    page2_downstream = downstream_tpl.format(
        conf_issue_range=conf_issue_rng, conf_sit_range=conf_sit_rng,
        unconf_issue_range=unconf_issue_rng, unconf_total=unconf_total,
        unconf_sales=unconf_sales)

    on_reece = lfb.stranded_on_reece_leads
    reece_box = REECE_BOX.format(
        desk_share_lf_pct=desk_share_lf, desk_share_reece_pct=desk_share_reece,
        stranded_on_reece_leads=(on_reece if on_reece is not None else "most"),
        stranded_n=lfb.stranded,
        desk_dial_no_confirm=_word(audit.desk_dial_no_confirm) if audit else "Some",
        reece_noconf_pct=reece_noconf_pct)

    sg = p.selfgen
    worst_unconf_strand = max(
        (100.0 * a.stranded / a.matured for a in p.agents
         if a.team == "Lightfire" and a.matured >= 5 and a.no_confirmer >= a.matured * 0.5),
        default=lf_strand_pct)
    best_selfconf = min(
        ((a, 100.0 * a.stranded / a.matured) for a in p.agents
         if a.team == "Lightfire" and a.matured >= 20 and a.no_confirmer <= a.matured * 0.2),
        key=lambda t: t[1], default=(None, None))
    lf_box = LF_BOX.format(
        selfgen_matured=sg.matured if sg else 0,
        selfgen_noconf=sg.no_confirmer if sg else 0,
        selfgen_stranded=sg.stranded if sg else 0,
        best_selfconf_name=_first_last(best_selfconf[0].setter_name).split()[-1] if best_selfconf[0] else "—",
        best_selfconf_strand_pct=best_selfconf[1] if best_selfconf[1] is not None else 0.0,
        worst_unconf_strand_pct=worst_unconf_strand,
        lf_cancel_pct=100.0 * lfb.cancels_all / lfb.matured,
        reece_cancel_pct=100.0 * rb.cancels_all / rb.matured) if sg else ""
    if sg is None:
        warnings.append("selfgen block absent — Lightfire accountability box omits the Self Generated detail")

    mix_foot = SOURCE_MIX_FOOT[mix.state].format(z=abs(mix.z) if mix.z is not None else 0.0)

    # ---- page 3 footnote ---------------------------------------------------
    example = max(ranked, key=lambda d: d.agent.matured)
    flags = {d.agent.roster_flag for d in ranked}
    legend = ""
    if "departed" in flags:
        legend += " † vacated their seat during this review."
    if "off_account" in flags:
        legend += f" ‡ did not appear on our account in the week of {week_label}."
    excl_min = (f", and anyone below {_NUM_WORDS_LOWER.get(cfg.min_matured_for_table, str(cfg.min_matured_for_table))} "
                f"matured appointments" if cfg.min_matured_for_table > 1 else "")
    page3_footnote = (
        "<b>Matured Sit %</b> is of <i>all</i> matured appointments and is necessarily lower than the "
        "<b>Issued Sit %</b> on page 1, which excludes appointments that never issued. "
        f"{_first_last(example.name)}, for example, is {example.issued_sit_pct:.1f}% issued and "
        f"{example.matured_sit_pct:.1f}% matured — both correct, measuring different things.{legend} "
        "Gross credits the full closed contract to the setter of record. Excluded: house and unassigned "
        "appointments, our AI setter, the GoHighLevel integration"
        f"{excl_min}.")

    # ---- page 4 staffing ---------------------------------------------------
    staffing_paras: list[str] = []
    if staffing:
        if dialler:
            lead = STAFFING_LEAD.format(
                prior_agents_word=_word(staffing.prior_active_agents),
                prior_week_label=_dmon(p.meta.prior_period_start),
                agents_word=_word(dialler.agents_on_dialler),
                week_label=week_label, named_detail=dialler.named_detail)
            departed = dialler.departed_detail + " " if dialler.departed_detail else ""
        else:
            lead = (f"<b>{_word(staffing.prior_active_agents)} of your agents set appointments in the week "
                    f"of {_dmon(p.meta.prior_period_start)}. {_word(staffing.active_agents)} set appointments "
                    f"in the week of {week_label}</b> — ")
            departed = ""
        movement = STAFFING_MOVEMENT[st_trend].format(
            departed_detail=departed,
            output_delta_pct=staffing.staffed_output_delta_pct or 0.0,
            board_prior=staffing.board_prior if staffing.board_prior is not None else "—",
            board_now=staffing.board_now if staffing.board_now is not None else "—")
        staffing_paras.append(lead + movement)
        if dialler:
            staffing_paras.append(STAFFING_OFFDIALLER)
    else:
        warnings.append("staffing payload absent (§15 soft #14)")

    # ---- retention ---------------------------------------------------------
    retention_para = None
    if p.retention:
        r = p.retention
        from calculations import RetentionRow
        lf_ret = RetentionRow("Lightfire", r.lightfire.gross_written_cents,
                              r.lightfire.cancellations_cents, r.lightfire.financing_denied_cents,
                              r.lightfire.largest_single_contract_cents)
        retention_para = RETENTION_OUTLIER[lf_ret.outlier_flag].format(
            outlier_amount=r.lightfire.largest_single_contract_cents / 100,
            outlier_agent=r.outlier_agent_name or "the setter of record",
            fin_amount=r.lightfire.financing_denied_cents / 100,
            fin_count=_NUM_WORDS_LOWER.get(r.lightfire.financing_denied_count,
                                           str(r.lightfire.financing_denied_count)),
            reece_fin=r.reece.financing_denied_cents / 100)
    else:
        warnings.append("retention payload absent (§15 soft #14 / §19 known gap)")

    # ---- soft gates #12/#15 ------------------------------------------------
    if prior and prior.lf_issued_sit_pct is not None and lf_total.issued_sit_pct is not None:
        if abs(lf_total.issued_sit_pct - prior.lf_issued_sit_pct) > 25:
            warnings.append("Lightfire sit % moved more than 25 pts WoW (§15 soft #15)")

    # ---- next step + method ------------------------------------------------
    from datetime import timedelta
    session_week = _dmon(p.meta.run_date + timedelta(days=7))
    who = _first_last(headline.setter_name) if headline else "your account lead's pick"
    next_step = (
        f"A working session in the week of {session_week} with your account lead and ours, plus {who} if "
        f"he is willing. <b>We will bring the record-level file for all {lfb.stranded} stranded "
        "appointments</b> — lead ID, setter, dates, source, branch and every confirmation touch we "
        "found — so any appointment can be examined line by line.")

    ret_limit = "retention is one week (Report 137)" if p.retention else "retention withheld this week (source feed pending)"
    active_def = ("" if (staffing and staffing.dialler) else
                  " <b>Active agents</b> = setters with at least one appointment set during the reporting week.")
    method_text = (
        f"<b>Cohort:</b> appointments set {_dmon(p.meta.cohort_set_start)} – "
        f"{_dmon(p.meta.cohort_set_end)} {p.meta.cohort_set_end.year} dated on or before "
        f"{_dmon(p.meta.cohort_appt_cutoff)}, identical filter both teams, agents merged across both name "
        "forms. <b>Issued Sit %</b> = sits ÷ (gross issued − cancels), not also stripping NIS/NOC. "
        "<b>Matured Sit %</b> = sits ÷ all matured appointments. <b>Confirmed</b> = a confirmer of "
        "record in Lead Perfection; the stranded audit used a wider test including desk dials, board "
        "messages and AI touches. <b>Tests</b> two-proportion z, two-sided — a null result means the "
        "rates cannot be distinguished, not that they are equal.{active}"
        " <b>Limits:</b> recent sales still pending; gross is written business; small denominators marked; "
        f"{ret_limit}. Underlying records available for any figure here.").format(active=active_def)

    return Derived(
        payload=p, lf_rows=lf_rows, reece_rows=reece_rows, lf_total=lf_total,
        reece_total=reece_total, ranked=ranked, kpis=kpis, exec_paragraph=exec_para,
        credit=credit, headline=headline, test_noconf=test_noconf, test_strand=test_strand,
        source_mix=mix, fin=fin, potential_display_cents=potential,
        narrative_states=states, page1_footnote=page1_footnote, page2_audit=page2_audit,
        page2_table_rows=[page2_rows], page2_held_constant=held,
        page2_downstream=page2_downstream, reece_box=reece_box, lf_box=lf_box,
        source_mix_foot=mix_foot, page3_footnote=page3_footnote,
        staffing_paras=staffing_paras, retention_para=retention_para,
        next_step=next_step, method_text=method_text, warnings=warnings,
        stat_records=stat_records)


def derive_agent_from_row(a, *, goal: float, small_min: int) -> AgentDerived:
    from calculations import AgentCohort
    return derive_agent(
        AgentCohort(setter_name=a.setter_name, team=a.team, matured=a.matured,
                    gross_issued=a.gross_issued, cancels=a.cancels, net_issued=a.net_issued,
                    sat=a.sat, sold=a.sold, gross_cents=a.gross_cents,
                    display_name=a.display_name, roster_flag=a.roster_flag,
                    sets_period=a.sets_period, sets_prior_period=a.sets_prior_period),
        goal=goal, small_min=small_min)


def generated_stamp(now_utc: datetime | None = None) -> str:
    """Displayed generation timestamp with the correct EST/EDT abbreviation
    derived from the zone (D9), e.g. '18 August 2026, 8:04 AM EDT'."""
    from datetime import timezone
    now = (now_utc or datetime.now(timezone.utc)).astimezone(ET)
    return f"{_dmon(now.date())} {now.year}, {now.strftime('%-I:%M %p')} {now.tzname()}"
