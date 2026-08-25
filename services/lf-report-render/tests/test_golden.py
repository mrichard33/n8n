"""Acceptance #4: the golden payload renders 4 pages containing the canonical
strings, and the §22 #12 first-run behavior holds (no prior -> empty KPI third
lines, no trend parenthetical)."""
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from assemble import assemble
from report_builder import build_report
from schema import ReportPayload

GOLDEN = Path(__file__).parent / "golden_payload.json"


@pytest.fixture(scope="module")
def payload() -> ReportPayload:
    return ReportPayload.model_validate(json.loads(GOLDEN.read_text()))


@pytest.fixture(scope="module")
def built(payload, tmp_path_factory):
    out = tmp_path_factory.mktemp("golden") / "golden.pdf"
    result = build_report(payload, str(out))
    raw = "\n".join(page.extract_text() for page in PdfReader(str(out)).pages)
    # pypdf breaks lines at table-cell wraps; acceptance strings are asserted
    # against whitespace-normalized reading order.
    import re
    text = re.sub(r"\s+", " ", raw)
    return result, text


def test_four_pages(built):
    result, _ = built
    assert result.page_count == 4


REQUIRED = ["65.8%", "78.9%", "38.3%", "10.8%", "p = 0.14 — not distinguishable",
            "Craig Deer", "$206,000"]


@pytest.mark.parametrize("needle", REQUIRED)
def test_canonical_strings_present(built, needle):
    _, text = built
    assert needle in text, f"golden render missing {needle!r}"


def test_negative_guard_no_cohort_sit_pct(built):
    """The full-cohort 66.2% (157/237) must appear in no rendered cell."""
    _, text = built
    assert "66.2" not in text


def test_reference_cells(built):
    _, text = built
    for needle in ["61.9%", "17.6", "Gordon, Grecian *", "Lightfire total",
                   "Reece setters, same basis", "$95,698", "60.6%", "90.9%",
                   "244 matured appointments with no confirmer of record produced zero sales",
                   "p < 0.0001", "Restore the bench", "22% of your book and 87% of our own",
                   "ranks sixth in dollars while setting the most appointments",
                   "Fifteen showed any evidence at all. Three reached a Reece confirmer"]:
        assert needle in text, f"missing {needle!r}"


def test_first_run_has_no_delta_lines(payload):
    """§22 #12: no prior snapshot -> KPI third lines empty, exec paragraph has
    no comparison parenthetical."""
    d = assemble(payload)
    assert all(k.delta_text == "" for k in d.kpis)
    assert "last week" not in d.exec_paragraph
    assert "(" not in d.exec_paragraph.split("Your book runs")[1][:40]


def test_prior_week_adds_deltas_and_trend(payload):
    data = json.loads(GOLDEN.read_text())
    data["prior"] = {"week_label": "2–8 August", "is_exactly_prior_week": True,
                     "lf_issued_sit_pct": 63.7, "reece_issued_sit_pct": 79.4,
                     "lf_noconf_pct": 41.0, "unconf_sales": 0, "kpi5_prior": 12}
    d = assemble(ReportPayload.model_validate(data))
    assert "up 2.1 points from 63.7% last week" in d.exec_paragraph
    k1 = d.kpis[0]
    assert k1.delta_text == "▲ 2.1 pts vs prior week" and k1.delta_class == "good"
    k3 = d.kpis[2]  # no-confirmer down = favourable
    assert k3.delta_class == "good" and k3.delta_text.startswith("▼")


def test_stat_wording_flips_on_significant_strand(payload):
    """Acceptance #5: p < 0.05 on test 2 renders the significant sentence."""
    data = json.loads(GOLDEN.read_text())
    data["reece_base"]["unconfirmed"]["stranded"] = 8   # 76/171 vs 8/73 -> p << 0.05
    data["reece_base"]["stranded"] = 9
    d = assemble(ReportPayload.model_validate(data))
    assert d.test_strand.verdict == "SIGNIFICANT"
    assert "no statistically distinguishable difference" not in d.page2_held_constant
    assert "a statistically significant gap remains" in d.exec_paragraph


def test_golden_warnings_flag_the_overrides(payload):
    d = assemble(payload)
    assert any("display_overrides" in w for w in d.warnings)
