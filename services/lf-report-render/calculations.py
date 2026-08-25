"""Derived metrics (Handoff V2 §6). Pure functions, no I/O.

Rounding doctrine: never round before presentation. Everything here is full
precision; the renderer formats. Null doctrine: a zero denominator yields
None — rendered as an em dash, never 0.0% and never NaN.

THE ONE TOTAL RULE (Mark, 2026-08-18 approval note): the page-1 team total is
derived by summing exactly the agent rows selected for display — one function
(team_display_total), one call site. The KPI card, "vs goal", team sits-short,
the financial opportunity and the executive paragraph all read that same
derived value. No cohort-level sit % exists anywhere in this codebase. The
full-cohort aggregates (TeamCohortBase) exist only for confirmation analysis
and statistical tests, none of which is a sit %.

With min_matured_for_table = 1 (Mark, 2026-08-18: lowered from 3), every
roster agent with at least one matured appointment gets a row, so the display
sum equals the true cohort total by construction, every week.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentCohort:
    """One Q3 row: an agent's matured-cohort outcomes."""
    setter_name: str
    team: str                    # 'Lightfire' | 'Reece' | 'Reece (W)'
    matured: int
    gross_issued: int
    cancels: int                 # cancels among issued
    net_issued: int
    sat: int
    sold: int
    gross_cents: int
    display_name: str | None = None
    roster_flag: str | None = None   # None | 'departed' | 'off_account'
    sets_period: int = 0
    sets_prior_period: int = 0


@dataclass(frozen=True)
class TeamCohortBase:
    """Full-cohort Q2 aggregates for ONE team — confirmation analysis and
    statistical-test inputs ONLY. Deliberately carries no sit %: deriving one
    from these fields is the defect the one-total rule exists to prevent."""
    team: str
    matured: int
    no_confirmer: int
    confirmed_by_desk: int
    self_confirmed: int
    confirmed_ai_other: int
    stranded: int
    stranded_no_confirmer: int   # Q5: stranded among the no-confirmer slice
    sold_no_confirmer: int       # Q5: sales among the no-confirmer slice


# ---------------------------------------------------------------------------
# Per-agent derivations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentDerived:
    agent: AgentCohort
    issued_sit_pct: float | None     # 100 * sat / net_issued, None if net_issued == 0
    matured_sit_pct: float | None    # 100 * sat / matured
    vs_goal_pts: float | None        # issued_sit_pct - 100*goal
    sits_short: float                # max(0, goal*net_issued - sat); 0.0 when at/above
    gross_per_appt_cents: float | None
    small_denominator: bool          # net_issued < small_denominator_min — a STYLING
                                     # flag only; it never excludes a row (Mark, 2026-08-18)
    rank_by_gross: int | None = None

    @property
    def name(self) -> str:
        return self.agent.display_name or self.agent.setter_name


def derive_agent(a: AgentCohort, *, goal: float, small_min: int) -> AgentDerived:
    issued = 100.0 * a.sat / a.net_issued if a.net_issued > 0 else None
    matured = 100.0 * a.sat / a.matured if a.matured > 0 else None
    return AgentDerived(
        agent=a,
        issued_sit_pct=issued,
        matured_sit_pct=matured,
        vs_goal_pts=None if issued is None else issued - 100.0 * goal,
        sits_short=max(0.0, goal * a.net_issued - a.sat),
        gross_per_appt_cents=(a.gross_cents / a.matured) if a.matured > 0 else None,
        small_denominator=a.net_issued < small_min,
    )


def rank_by_gross(agents: list[AgentDerived]) -> list[AgentDerived]:
    """Combined-team ranking for page 3, gross dollars descending. Ties break
    by matured volume then name so the order is deterministic."""
    ordered = sorted(agents, key=lambda d: (-d.agent.gross_cents, -d.agent.matured, d.name))
    return [replace(d, rank_by_gross=i + 1) for i, d in enumerate(ordered)]


def select_display_rows(agents: list[AgentDerived], team: str, *, min_matured: int) -> list[AgentDerived]:
    """Page-1 sit-table rows for one team: every agent at or above the matured
    floor, ordered by Issued Sit % descending with un-computable (None) rows
    last. With min_matured = 1 nothing with activity is excluded."""
    rows = [d for d in agents if d.agent.team == team and d.agent.matured >= min_matured]
    return sorted(rows, key=lambda d: (d.issued_sit_pct is None, -(d.issued_sit_pct or 0.0), d.name))


# ---------------------------------------------------------------------------
# THE team total — single derivation, single call site (see module docstring)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TeamDisplayTotal:
    team: str
    gross_issued: int
    cancels: int
    net_issued: int
    sat: int
    sold: int
    gross_cents: int
    issued_sit_pct: float | None
    vs_goal_pts: float | None
    sits_short: float


def team_display_total(rows: list[AgentDerived], *, goal: float) -> TeamDisplayTotal:
    """Sum of exactly the rows the page displays. The golden fixture pins this
    at 65.8% / 33.2 sits short for the approved 11-row table; with the matured
    floor at 1 it equals the full-cohort total by construction."""
    if not rows:
        raise ValueError("team_display_total on zero rows — the run should have BLOCKED upstream")
    team = rows[0].agent.team
    gi = sum(r.agent.gross_issued for r in rows)
    cx = sum(r.agent.cancels for r in rows)
    ni = sum(r.agent.net_issued for r in rows)
    sat = sum(r.agent.sat for r in rows)
    sold = sum(r.agent.sold for r in rows)
    gross = sum(r.agent.gross_cents for r in rows)
    pct = 100.0 * sat / ni if ni > 0 else None
    return TeamDisplayTotal(
        team=team, gross_issued=gi, cancels=cx, net_issued=ni, sat=sat, sold=sold,
        gross_cents=gross,
        issued_sit_pct=pct,
        vs_goal_pts=None if pct is None else pct - 100.0 * goal,
        sits_short=max(0.0, goal * ni - sat),
    )


# ---------------------------------------------------------------------------
# Financial opportunity (§6 — always framed as potential)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FinancialOpportunity:
    incremental_sits: float
    close_rate: float | None       # observed, this cohort
    avg_ticket_cents: float | None # observed
    potential_gross_cents: float | None

    def as_record(self) -> dict:
        return {
            "incremental_sits": round(self.incremental_sits, 2),
            "close_rate": None if self.close_rate is None else round(self.close_rate, 4),
            "avg_ticket_cents": None if self.avg_ticket_cents is None else round(self.avg_ticket_cents),
            "potential_gross_cents": None if self.potential_gross_cents is None else round(self.potential_gross_cents),
        }


def financial_opportunity(total: TeamDisplayTotal) -> FinancialOpportunity:
    """potential = sits_short × observed close rate × observed ticket. The
    renderer MUST wrap this in 'approximately … potential … An estimate, not
    revenue we can claim would certainly have occurred.' (§6)."""
    close = total.sold / total.sat if total.sat > 0 else None
    ticket = total.gross_cents / total.sold if total.sold > 0 else None
    potential = (total.sits_short * close * ticket) if (close is not None and ticket is not None) else None
    return FinancialOpportunity(total.sits_short, close, ticket, potential)


# ---------------------------------------------------------------------------
# Narrative-state computation (§8 states; sentences live in narrative.py)
# ---------------------------------------------------------------------------


def sit_trend(current_pct: float | None, prior_pct: float | None,
              *, material: float = 3.0, slight: float = 1.0) -> tuple[str, float | None]:
    if current_pct is None or prior_pct is None:
        return "NO_PRIOR", None
    delta = current_pct - prior_pct
    if abs(delta) < slight:
        return "FLAT", delta
    if delta >= material:
        return "IMPROVED_MATERIAL", delta
    if delta > 0:
        return "IMPROVED_SLIGHT", delta
    if delta <= -material:
        return "DECLINED_MATERIAL", delta
    return "DECLINED_SLIGHT", delta


def goal_status(pct: float | None, *, goal_pct: float) -> str:
    if pct is None:
        return "BELOW_15_PLUS"  # unknowable reads as the worst bucket, never as fine
    gap = goal_pct - pct
    if gap <= 0:
        return "AT_OR_ABOVE"
    if gap <= 5:
        return "WITHIN_5"
    if gap <= 15:
        return "BELOW_5_TO_15"
    return "BELOW_15_PLUS"


def staffing_trend(active: int, prior: int) -> str:
    if active > prior:
        return "GREW"
    if active == prior:
        return "STABLE"
    drop = (prior - active) / prior if prior else 0.0
    return "SHRANK_SEVERE" if drop >= 1 / 3 else "SHRANK_MODERATE"


def confirmer_gap(lf_no_conf_pct: float, reece_no_conf_pct: float) -> str:
    gap = abs(lf_no_conf_pct - reece_no_conf_pct)
    if gap >= 20:
        return "WIDE"
    if gap >= 10:
        return "MODERATE"
    if gap >= 3:
        return "NARROW"
    return "PARITY"


def actions_state(open_n: int, escalated_n: int, resolved_this_week_n: int) -> str:
    if escalated_n:
        return "ESCALATED"
    if open_n == 0:
        return "ALL_RESOLVED" if resolved_this_week_n else "NONE_OPEN"
    return "SOME_OPEN"


# ---------------------------------------------------------------------------
# Retention (§18 — verify against LP 137's own definition, do not infer)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetentionRow:
    team: str
    gross_written_cents: int
    cancellations_cents: int
    financing_denied_cents: int
    largest_single_contract_cents: int = 0

    @property
    def net_retained_cents(self) -> int:
        return self.gross_written_cents - self.cancellations_cents - self.financing_denied_cents

    @property
    def retention_pct(self) -> float | None:
        if self.gross_written_cents <= 0:
            return None
        return 100.0 * self.net_retained_cents / self.gross_written_cents

    @property
    def outlier_flag(self) -> bool:
        """A single contract above 20% of team gross written — so the report
        can say 'one contract, not a pattern' from state, not from memory."""
        return self.largest_single_contract_cents > 0.20 * self.gross_written_cents
