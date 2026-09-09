"""§11 overflow lever: a full-roster week has more Lightfire agents than fit on
page 1 (proven live: the 2026-08-17 reference window renders 14 LF rows and
spills to 5 pages at floor 0). build_report must apply the page-1 net-issued
ladder to bring it back to exactly four pages, hold the lowest-volume agents
out of the page-1 table, disclose them in the footnote, and keep them in the
section-3 ranking — never shrinking fonts. The golden (11 rows) fits at floor 0
and must be untouched.
"""
import copy
import json
from pathlib import Path

from report_builder import build_report
from schema import ReportPayload

GOLDEN = json.loads((Path(__file__).parent / "golden_payload.json").read_text())


def _overflowing_payload():
    """The production Phase-1 shape (no dialler / retention / stranded-audit
    block, as those feeds are Phase 2) plus three tiny Lightfire agents (each
    < 3 net issued) — the live 2026-08-17 reference window in miniature: enough
    extra page-1 rows to spill to a fifth page at floor 0."""
    p = copy.deepcopy(GOLDEN)
    p["prior"] = None
    p["display_overrides"] = None
    p["retention"] = None
    p["stranded_audit"] = None
    p["staffing"]["dialler"] = None
    for name, net, sat in [("Extra One", 1, 1), ("Extra Two", 0, 0), ("Extra Three", 2, 2)]:
        p["agents"].append({
            "setter_name": name, "team": "Lightfire", "matured": 4,
            "gross_issued": net, "cancels": 0, "net_issued": net, "sat": sat, "sold": 0,
            "gross_cents": 0, "no_confirmer": 2, "stranded": 1})
    return p


def test_overflow_ladder_returns_four_pages_and_holds_low_agents():
    payload = ReportPayload.model_validate(_overflowing_payload())
    result = build_report(payload, "/tmp/lf_overflow.pdf")
    assert result.page_count == 4
    # the three sub-3-net agents were held out of the page-1 sit table
    shown = {r.agent.setter_name for r in result.derived.lf_rows}
    assert "Extra Two" not in shown and "Extra One" not in shown and "Extra Three" not in shown
    # but they remain in the section-3 ranking (comprehensive)
    ranked = {r.agent.setter_name for r in result.derived.ranked}
    assert {"Extra One", "Extra Two", "Extra Three"} <= ranked
    # the omission is disclosed, not silent
    assert "held out of" in result.derived.page1_footnote
    # the one-total rule still holds on the shown rows
    assert result.derived.lf_total.sat == sum(r.agent.sat for r in result.derived.lf_rows)


def test_golden_does_not_trigger_the_ladder():
    payload = ReportPayload.model_validate(GOLDEN)
    result = build_report(payload, "/tmp/lf_golden_ladder.pdf")
    assert result.page_count == 4
    assert len(result.derived.lf_rows) == 11          # all approved rows shown
    assert "held out of" not in result.derived.page1_footnote
