"""ReportPayload — the exact render input, frozen per version (D5).

The payload carries RAW data (query results, roster-tagged agent rows, the
prior approved snapshot, actions). Everything displayed is DERIVED from it
deterministically in assemble.py — same payload, same document. n8n never
formats or computes (§2); it only fills this structure from SQL and posts it.

Null doctrine: optional blocks (retention, staffing dialler detail, stranded
audit, prior) may be None and the renderer omits them cleanly (§19) — the
report is still exactly four pages.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Team = Literal["Lightfire", "Reece", "Reece (W)"]


class Meta(BaseModel):
    run_date: date
    period_start: date
    period_end: date
    prior_period_start: date
    prior_period_end: date
    cohort_set_start: date
    cohort_set_end: date
    cohort_appt_cutoff: date
    iso_year: int
    iso_week: int
    version_no: int = 1
    partner_display_name: str = "Lightfire"


class ConfigBlock(BaseModel):
    issued_sit_goal: float = 0.80
    small_denominator_min: int = 20
    # 1, not 3 (Mark, 2026-08-18): every agent with >=1 matured appointment
    # displays, so the summed page-1 total equals the cohort total by
    # construction. small_denominator stays a styling flag, never an exclusion.
    min_matured_for_table: int = 1
    alpha: float = 0.05
    material_delta_pts: float = 3.0
    slight_delta_pts: float = 1.0
    expected_page_count: int = 4


class AgentRow(BaseModel):
    setter_name: str
    team: Team
    matured: int = Field(ge=0)
    gross_issued: int = Field(ge=0)
    cancels: int = Field(ge=0)          # cancels among issued
    net_issued: int = Field(ge=0)
    sat: int = Field(ge=0)
    sold: int = Field(ge=0)
    gross_cents: int = Field(ge=0)
    display_name: Optional[str] = None
    roster_flag: Optional[Literal["departed", "off_account"]] = None
    sets_period: int = Field(default=0, ge=0)
    sets_prior_period: int = Field(default=0, ge=0)
    no_confirmer: int = Field(default=0, ge=0)   # of this agent's matured appts
    stranded: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _identities(self):
        # Validation gate #4: net_issued = gross_issued - cancels, every row.
        if self.net_issued != self.gross_issued - self.cancels:
            raise ValueError(
                f"{self.setter_name}: net_issued {self.net_issued} != "
                f"gross_issued {self.gross_issued} - cancels {self.cancels}")
        if self.sat > self.matured or self.gross_issued > self.matured:
            raise ValueError(f"{self.setter_name}: sat/issued exceed matured")
        return self


class ConfirmSplit(BaseModel):
    """Q5 slice: appointments with (confirmed) / without (unconfirmed) a
    confirmer of record, one slice per team."""
    n: int = Field(ge=0)
    issued: int = Field(ge=0)
    sat: int = Field(ge=0)
    sold: int = Field(ge=0)
    stranded: int = Field(ge=0)


class TeamBase(BaseModel):
    """Full-cohort Q2 aggregates for confirmation analysis and statistical
    tests ONLY. Deliberately no sit %: the one-total rule (see calculations)."""
    matured: int = Field(gt=0)          # gate #2: zero matured must BLOCK upstream
    no_confirmer: int = Field(ge=0)
    confirmed_by_desk: int = Field(ge=0)
    self_confirmed: int = Field(ge=0)
    confirmed_ai_other: int = Field(ge=0)
    stranded: int = Field(ge=0)
    cancels_all: int = Field(ge=0)      # all CXL in cohort (page-2 LF box rate)
    confirmed: ConfirmSplit
    unconfirmed: ConfirmSplit
    stranded_on_reece_leads: Optional[int] = None  # LF box; None omits the clause

    @model_validator(mode="after")
    def _sums(self):
        # Validation gate #6: confirmation categories sum to matured.
        parts = (self.no_confirmer + self.confirmed_by_desk
                 + self.self_confirmed + self.confirmed_ai_other)
        if parts != self.matured:
            raise ValueError(f"confirmation categories {parts} != matured {self.matured}")
        if self.confirmed.n + self.unconfirmed.n != self.matured:
            raise ValueError("confirmed + unconfirmed slices != matured")
        return self


class SelfGen(BaseModel):
    matured: int
    no_confirmer: int
    stranded: int


class StrandedAudit(BaseModel):
    """Record-level manual audit (page-2 opener + Reece box detail). Not
    derivable from lp_leads; omit the block when the audit was not run."""
    any_evidence_n: int
    desk_reached_n: int
    desk_dial_no_confirm: int = 0


class SourceMixRow(BaseModel):
    source: str
    lf_n: int = Field(ge=0)
    lf_sat: int = Field(ge=0)
    reece_n: int = Field(ge=0)
    reece_sat: int = Field(ge=0)


class DiallerDetail(BaseModel):
    """Five9-derived staffing detail (Phase 2). When absent, the report renders
    the §19 Phase-1 set-based staffing with its definition stated in Method."""
    agents_on_dialler: int
    prior_agents_on_dialler: int
    named_detail: str            # e.g. "Deer, Walker and Wright for full weeks, Slowely for one day"
    departed_detail: str = ""    # e.g. "Evans and Gordon left the account entirely, ..."


class Staffing(BaseModel):
    active_agents: int                       # setters with >=1 set in the week
    prior_active_agents: int
    board_prior: Optional[int] = None        # Monday-board appointment counts
    board_now: Optional[int] = None
    staffed_output_delta_pct: Optional[float] = None
    dialler: Optional[DiallerDetail] = None


class RetentionTeamRow(BaseModel):
    gross_written_cents: int = Field(ge=0)
    cancellations_cents: int = Field(ge=0)
    financing_denied_cents: int = Field(ge=0)
    largest_single_contract_cents: int = Field(default=0, ge=0)
    financing_denied_count: int = Field(default=0, ge=0)


class Retention(BaseModel):
    week_label: str                          # e.g. "2–8 August"
    lightfire: RetentionTeamRow
    reece: RetentionTeamRow
    outlier_agent_name: Optional[str] = None # first-last, for the outlier sentence


class ActionItem(BaseModel):
    number: int
    title_html: str
    done_means: str
    by_label: str                            # e.g. "1 Sep"
    tier: Literal["IMMEDIATE", "SECONDARY"]
    status: Literal["OPEN", "IN_PROGRESS", "DONE", "RECURRED", "ESCALATED", "REMOVED"] = "OPEN"
    weeks_open: int = 0
    last_week_note: Optional[str] = None     # "last week: 6 active"


class PriorSnapshot(BaseModel):
    """From the most recent APPROVED/SENT frozen snapshot (§9) — never
    recomputed from live data. None on the first ever run."""
    week_label: str                          # "9–15 August"
    is_exactly_prior_week: bool = True
    lf_issued_sit_pct: Optional[float] = None
    reece_issued_sit_pct: Optional[float] = None
    lf_noconf_pct: Optional[float] = None
    unconf_sales: Optional[int] = None
    kpi5_prior: Optional[int] = None         # prior agents (dialler or set-based)


class TeamTotalOverride(BaseModel):
    gross_issued: int
    cancels: int
    net_issued: int
    sat: int


class DisplayOverrides(BaseModel):
    """Explicit, auditable GOLDEN-FIXTURE-ONLY historical literals (Mark,
    2026-08-18: 'a golden-fixture-only historical literal, never a live code
    path'). Production payloads leave this None; assemble() emits a warning
    whenever any pin is present so a live payload carrying one is visible in
    the approval email.

    - potential_gross_cents: the approved report's hand-calculated ~$206,000
      opportunity figure (mixed-basis hand arithmetic; §6's formula on the
      frozen rows yields ~$211k — REPORT_SPEC §financial).
    - reece_total: the approved artifact's Reece summary row (570/7/563/444).
      Its own agent rows sum to sat 445 — the hand-built table understated the
      total by one. The golden must render the approved 78.9%, so the artifact
      row is pinned here; the live path always derives the total from the
      displayed rows."""
    potential_gross_cents: Optional[int] = None
    reece_total: Optional[TeamTotalOverride] = None


class ReportPayload(BaseModel):
    meta: Meta
    config: ConfigBlock = ConfigBlock()
    agents: list[AgentRow]
    lightfire_base: TeamBase
    reece_base: TeamBase
    selfgen: Optional[SelfGen] = None
    stranded_audit: Optional[StrandedAudit] = None
    source_mix: list[SourceMixRow] = []
    staffing: Optional[Staffing] = None
    retention: Optional[Retention] = None
    actions: list[ActionItem] = []
    prior: Optional[PriorSnapshot] = None
    display_overrides: Optional[DisplayOverrides] = None

    @model_validator(mode="after")
    def _window_shape(self):
        # Validation gate #1: Sunday..Saturday, exactly 7 calendar days.
        m = self.meta
        if m.period_start.weekday() != 6 or m.period_end.weekday() != 5:
            raise ValueError("period must run Sunday to Saturday (ET calendar dates)")
        if (m.period_end - m.period_start).days != 6:
            raise ValueError("period must span exactly 7 calendar days")
        if not self.agents:
            raise ValueError("no agent rows — the run should have BLOCKED upstream")
        seen = set()
        for a in self.agents:
            if a.setter_name in seen:
                raise ValueError(f"duplicate agent row for {a.setter_name!r} — upstream join broke")
            seen.add(a.setter_name)
        return self
