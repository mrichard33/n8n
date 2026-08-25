"""§6 calculation engine against the approved report's numbers, including the
one-total rule and its guards."""
import pytest

from calculations import (
    AgentCohort, RetentionRow, confirmer_gap, derive_agent, financial_opportunity,
    goal_status, rank_by_gross, select_display_rows, sit_trend, staffing_trend,
    team_display_total,
)
from conftest import golden_lf_agents

GOAL = 0.80
SMALL = 20


def _derived(min_matured=1):
    agents = [derive_agent(a, goal=GOAL, small_min=SMALL) for a in golden_lf_agents()]
    return select_display_rows(agents, "Lightfire", min_matured=min_matured)


# ---------------------------------------------------------------------------
# THE one-total rule (Mark, 2026-08-18): page-1 total is the sum of exactly
# the displayed rows, one derivation, and the golden expectation is 65.8%.
# ---------------------------------------------------------------------------


def test_golden_team_total_is_65_8():
    total = team_display_total(_derived(), goal=GOAL)
    assert (total.gross_issued, total.cancels, total.net_issued, total.sat) == (238, 4, 234, 154)
    assert round(total.issued_sit_pct, 1) == 65.8
    assert round(total.vs_goal_pts, 1) == -14.2
    assert round(total.sits_short, 1) == 33.2   # rendered whole as "33" on the total row


def test_negative_guard_cohort_sit_pct_never_appears():
    """The full-cohort figure (157/237 = 66.2%) must not be derivable from the
    display path: the derivation over the approved rows yields 65.8, and no
    field of the total carries the cohort numbers."""
    total = team_display_total(_derived(), goal=GOAL)
    assert round(total.issued_sit_pct, 1) != 66.2
    assert (total.net_issued, total.sat) != (237, 157)


def test_matured_floor_one_includes_every_active_agent():
    """Mark's 2026-08-18 fix: at min_matured=3 a 1-matured agent drops and the
    total becomes a third, undisclosed number. At 1, adding such agents keeps
    the sum equal to the sum over ALL agents by construction."""
    extra = [
        AgentCohort("Smith, Shakeriah", "Lightfire", 1, 1, 0, 1, 1, 0, 0),
        AgentCohort("Miller, Afiya", "Lightfire", 1, 0, 0, 0, 0, 0, 0),
    ]
    agents = [derive_agent(a, goal=GOAL, small_min=SMALL) for a in golden_lf_agents() + extra]
    rows_at_1 = select_display_rows(agents, "Lightfire", min_matured=1)
    assert len(rows_at_1) == 13  # nobody with activity excluded
    total = team_display_total(rows_at_1, goal=GOAL)
    assert total.net_issued == sum(a.agent.net_issued for a in agents)
    assert total.sat == sum(a.agent.sat for a in agents)
    # at the old floor of 3, both drop — the defect the fix removes
    assert len(select_display_rows(agents, "Lightfire", min_matured=3)) == 11


def test_small_denominator_is_a_flag_not_an_exclusion():
    rows = _derived()
    small = [r for r in rows if r.small_denominator]
    assert small, "reference table has sub-20 denominators"
    assert all(r in rows for r in small)  # flagged rows still display
    gordon = next(r for r in rows if r.name == "Gordon, Grecian")
    assert gordon.small_denominator and round(gordon.issued_sit_pct, 1) == 100.0


# ---------------------------------------------------------------------------
# Per-agent derivations against reference cells
# ---------------------------------------------------------------------------


def test_reference_agent_cells():
    rows = {r.name: r for r in _derived()}
    deer = rows["Deer, Craig"]
    assert round(deer.issued_sit_pct, 1) == 61.9
    assert round(deer.matured_sit_pct, 1) == 39.5
    assert round(deer.sits_short, 1) == 17.6
    assert round(rows["Walker, Shari"].sits_short, 1) == 5.2
    assert round(rows["Wright, Carla"].sits_short, 1) == 4.0
    assert round(rows["Francis, Yanique"].vs_goal_pts, 1) == -43.6


def test_null_safety_zero_net_issued():
    a = derive_agent(AgentCohort("X", "Lightfire", 5, 0, 0, 0, 0, 0, 0), goal=GOAL, small_min=SMALL)
    assert a.issued_sit_pct is None       # rendered as an em dash, never 0.0%
    assert a.sits_short == 0.0
    ordered = select_display_rows([a] + _derived(), "Lightfire", min_matured=1)
    assert ordered[-1].name == "X"        # un-computable rows sort last


def test_rank_by_gross_deterministic():
    ranked = rank_by_gross(_derived())
    assert ranked[0].name == "Deer, Craig" and ranked[0].rank_by_gross == 1
    assert ranked[-1].name == "Francis, Yanique"


# ---------------------------------------------------------------------------
# Financial opportunity (§6)
# ---------------------------------------------------------------------------


def test_financial_opportunity_formula_on_displayed_total():
    """§6 formula on the frozen 11-row basis: 33.2 × (47/154) × (98,027,200/47)
    = ~$211.3k. The approved report's hand calculation printed ~$206,000 on a
    mixed basis; with the matured floor at 1 the display total equals the
    cohort total going forward, so this ambiguity no longer exists. The golden
    payload pins the approved $206,000 as frozen render input (REPORT_SPEC)."""
    total = team_display_total(_derived(), goal=GOAL)
    fo = financial_opportunity(total)
    assert round(fo.close_rate, 4) == round(47 / 154, 4)
    assert round(fo.avg_ticket_cents) == round(98027200 / 47)
    assert fo.potential_gross_cents == pytest.approx(33.2 * (47 / 154) * (98027200 / 47), rel=1e-6)
    assert 20_000_000 < fo.potential_gross_cents < 22_000_000  # ~$211k, sane range


def test_financial_opportunity_null_safe():
    t = team_display_total(
        [derive_agent(AgentCohort("X", "Lightfire", 3, 2, 0, 2, 0, 0, 0), goal=GOAL, small_min=SMALL)],
        goal=GOAL)
    fo = financial_opportunity(t)
    assert fo.close_rate is None and fo.potential_gross_cents is None


# ---------------------------------------------------------------------------
# Narrative states (§8) — computation side
# ---------------------------------------------------------------------------


def test_sit_trend_states_and_boundaries():
    assert sit_trend(65.8, None) == ("NO_PRIOR", None)
    assert sit_trend(65.8, 63.7)[0] == "IMPROVED_SLIGHT"
    assert sit_trend(67.0, 63.7)[0] == "IMPROVED_MATERIAL"   # 3.3 >= 3.0
    assert sit_trend(63.7, 63.0)[0] == "FLAT"                # 0.7 < 1.0
    assert sit_trend(60.0, 63.7)[0] == "DECLINED_MATERIAL"
    assert sit_trend(62.8, 63.7)[0] == "FLAT"
    assert sit_trend(61.9, 63.7)[0] == "DECLINED_SLIGHT"


def test_goal_status_buckets():
    assert goal_status(81.0, goal_pct=80) == "AT_OR_ABOVE"
    assert goal_status(76.0, goal_pct=80) == "WITHIN_5"
    assert goal_status(65.8, goal_pct=80) == "BELOW_5_TO_15"
    assert goal_status(64.0, goal_pct=80) == "BELOW_15_PLUS"
    assert goal_status(None, goal_pct=80) == "BELOW_15_PLUS"


def test_staffing_trend_reference():
    """12 -> 4 agents is the approved report's severe drop (>= 33%)."""
    assert staffing_trend(4, 12) == "SHRANK_SEVERE"
    assert staffing_trend(9, 12) == "SHRANK_MODERATE"
    assert staffing_trend(12, 12) == "STABLE"
    assert staffing_trend(13, 12) == "GREW"


def test_confirmer_gap_reference():
    assert confirmer_gap(38.3, 10.8) == "WIDE"     # 27.5 pts
    assert confirmer_gap(20.0, 8.0) == "MODERATE"
    assert confirmer_gap(12.0, 8.0) == "NARROW"
    assert confirmer_gap(9.0, 8.0) == "PARITY"


# ---------------------------------------------------------------------------
# Retention (§18) — both reference rows must reconcile
# ---------------------------------------------------------------------------


def test_retention_reference_rows_reconcile():
    lf = RetentionRow("Lightfire", 33104200, 9569800, 3482600, largest_single_contract_cents=9569800)
    assert lf.net_retained_cents == 20051800
    assert round(lf.retention_pct, 1) == 60.6
    assert lf.outlier_flag  # the $95,698 single cancellation is 29% of gross
    reece = RetentionRow("Reece", 53749600, 4909300, 0)
    assert reece.net_retained_cents == 48840300
    assert round(reece.retention_pct, 1) == 90.9
    assert not reece.outlier_flag
    assert RetentionRow("X", 0, 0, 0).retention_pct is None
