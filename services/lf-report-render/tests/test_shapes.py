"""§20 data-shape fixtures: degenerate weeks must either render cleanly at
exactly four pages or fail loudly at the right gate — never emit a wrong or
malformed document."""
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from assemble import GateFailure, assemble
from report_builder import build_report
from schema import ReportPayload

GOLDEN = json.loads((Path(__file__).parent / "golden_payload.json").read_text())


def payload_with(**changes) -> dict:
    data = copy.deepcopy(GOLDEN)
    data.update(changes)
    return data


def _lf(data, **kw):
    data["lightfire_base"].update(kw)
    return data


def test_zero_appointments_blocks():
    """Gate #2: a zero-matured team must BLOCK, not render an empty report."""
    data = payload_with()
    with pytest.raises(ValidationError):
        # matured is gt=0 at the schema layer already
        ReportPayload.model_validate(_lf(data, matured=0))


def test_single_lightfire_setter_renders(tmp_path):
    data = copy.deepcopy(GOLDEN)
    deer = next(a for a in data["agents"] if a["setter_name"] == "Deer, Craig")
    data["agents"] = [a for a in data["agents"] if a["team"] != "Lightfire"] + [deer]
    r = build_report(ReportPayload.model_validate(data), str(tmp_path / "one.pdf"))
    assert r.page_count == 4
    assert r.derived.lf_total.sat == deer["sat"]


def test_all_small_denominator_renders_neutral_credit(tmp_path):
    """Every LF agent under 20 net issued: the sit table renders all-asterisk,
    the headline is omitted (nobody eligible), the report is still 4 pages."""
    data = copy.deepcopy(GOLDEN)
    for a in data["agents"]:
        if a["team"] == "Lightfire":
            scale = min(a["net_issued"], 10)
            a["gross_issued"] = scale + a["cancels"]
            a["net_issued"] = scale
            a["sat"] = min(a["sat"], scale)
    d = assemble(ReportPayload.model_validate(data))
    assert d.headline is None
    assert any("headline" in w for w in d.warnings)
    r = build_report(ReportPayload.model_validate(data), str(tmp_path / "small.pdf"))
    assert r.page_count == 4


def test_no_sales_renders_null_safe(tmp_path):
    data = copy.deepcopy(GOLDEN)
    for a in data["agents"]:
        a["sold"] = 0
        a["gross_cents"] = 0
    data["lightfire_base"]["confirmed"]["sold"] = 0
    data["reece_base"]["confirmed"]["sold"] = 0
    del data["display_overrides"]  # the $206k pin would mask the null path
    d = assemble(ReportPayload.model_validate(data))
    assert d.fin.close_rate == 0.0 or d.fin.close_rate is None
    r = build_report(ReportPayload.model_validate(data), str(tmp_path / "nosales.pdf"))
    assert r.page_count == 4


def test_hundred_pct_sit(tmp_path):
    data = copy.deepcopy(GOLDEN)
    for a in data["agents"]:
        if a["team"] == "Lightfire":
            a["sat"] = a["net_issued"] if a["net_issued"] <= a["matured"] else a["matured"]
    d = assemble(ReportPayload.model_validate(data))
    assert d.lf_total.sits_short == 0.0


def test_zero_confirmations_and_all_confirmations():
    zero = copy.deepcopy(GOLDEN)
    zero["lightfire_base"].update(
        no_confirmer=446, confirmed_by_desk=0, self_confirmed=0, confirmed_ai_other=0,
        confirmed={"n": 0, "issued": 0, "sat": 0, "sold": 0, "stranded": 0},
        unconfirmed={"n": 446, "issued": 241, "sat": 157, "sold": 47, "stranded": 79})
    d = assemble(ReportPayload.model_validate(zero))
    assert d.narrative_states["confirmer_gap"] == "WIDE"

    all_conf = copy.deepcopy(GOLDEN)
    all_conf["lightfire_base"].update(
        no_confirmer=0, confirmed_by_desk=278, self_confirmed=168, confirmed_ai_other=0,
        confirmed={"n": 446, "issued": 241, "sat": 157, "sold": 47, "stranded": 79},
        unconfirmed={"n": 0, "issued": 0, "sat": 0, "sold": 0, "stranded": 0})
    with pytest.raises(GateFailure):
        # test 2's inputs are degenerate (n = 0) — gate #9 BLOCKS the run,
        # never a wrong PDF
        assemble(ReportPayload.model_validate(all_conf))


def test_duplicate_setter_rows_rejected():
    """§20 'duplicate appointment' analog at payload grain: the same setter
    twice on one team means the upstream join broke — refuse."""
    data = copy.deepcopy(GOLDEN)
    data["agents"].append(dict(data["agents"][0]))
    with pytest.raises(ValidationError):
        ReportPayload.model_validate(data)


def test_missing_source_feed_is_insufficient_sample(tmp_path):
    data = payload_with(source_mix=[])
    d = assemble(ReportPayload.model_validate(data))
    assert d.source_mix.state == "INSUFFICIENT_SAMPLE"
    assert "no conclusion" in d.source_mix_foot
    r = build_report(ReportPayload.model_validate(data), str(tmp_path / "nosrc.pdf"))
    assert r.page_count == 4


def test_retention_and_staffing_absent_still_four_pages(tmp_path):
    """§19: both verified gaps omitted cleanly, still exactly 4 pages, and the
    Method block states the set-based active-agent definition."""
    data = payload_with(retention=None)
    data["staffing"]["dialler"] = None
    d = assemble(ReportPayload.model_validate(data))
    assert "at least one appointment set during the reporting week" in d.method_text
    assert any("retention" in w for w in d.warnings)
    r = build_report(ReportPayload.model_validate(data), str(tmp_path / "gaps.pdf"))
    assert r.page_count == 4


def test_name_variation_display_override():
    """'Nievez Moriera' (LP misspelling) renders as 'Nievez Moreira'."""
    d = assemble(ReportPayload.model_validate(copy.deepcopy(GOLDEN)))
    names = [r.name for r in d.ranked]
    assert "Nievez Moreira, Jardel" in names
    assert "Nievez Moriera, Jardel" not in names


def test_large_outlier_flags_and_sentence():
    d = assemble(ReportPayload.model_validate(copy.deepcopy(GOLDEN)))
    assert "one contract" in d.retention_para
    data = copy.deepcopy(GOLDEN)
    data["retention"]["lightfire"]["largest_single_contract_cents"] = 100000  # tiny
    d2 = assemble(ReportPayload.model_validate(data))
    assert "one contract" not in d2.retention_para
    assert "spread across contracts" in d2.retention_para


def test_pagination_guard_raises(tmp_path):
    from report_builder import PaginationError
    data = copy.deepcopy(GOLDEN)
    data["config"]["expected_page_count"] = 5
    with pytest.raises(PaginationError):
        build_report(ReportPayload.model_validate(data), str(tmp_path / "x.pdf"))
