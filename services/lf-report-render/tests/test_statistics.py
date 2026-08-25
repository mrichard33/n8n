"""§7 statistical engine against the approved report's reference numbers."""
import pytest

from stats_engine import (
    INSUFFICIENT_SAMPLE, NOT_DISTINGUISHABLE, SIGNIFICANT,
    SOURCE_MIX_NOT_EXPLANATORY, run_test, source_mix_test, two_prop_z, verdict_cell,
)


def test_reference_no_confirmer_rate_by_team():
    """171/446 vs 73/678 — p < 0.0001 (§7 required test 1)."""
    t = run_test("no_confirmer_rate", 171, 446, 73, 678)
    assert t.p < 0.0001
    assert t.verdict == SIGNIFICANT
    assert verdict_cell(t) == "p < 0.0001"


def test_reference_strand_rate_given_no_confirmer():
    """76/171 vs 25/73 — p = 0.14, and the null wording rule (§7): renders
    'not distinguishable', NEVER 'the same'."""
    t = run_test("strand_given_no_confirmer", 76, 171, 25, 73)
    assert round(t.p, 2) == 0.14
    assert t.verdict == NOT_DISTINGUISHABLE
    assert verdict_cell(t) == "p = 0.14 — not distinguishable"
    assert "same" not in verdict_cell(t)


def test_verdict_flips_with_the_number():
    """§7: a hardcoded verdict must never outlive the number it describes —
    feed inputs across the 0.05 line and the sentence must flip."""
    null = run_test("x", 40, 100, 45, 100)          # p ~ 0.47
    sig = run_test("x", 40, 100, 75, 100)           # p << 0.05
    assert null.verdict == NOT_DISTINGUISHABLE and "not distinguishable" in verdict_cell(null)
    assert sig.verdict == SIGNIFICANT and "not distinguishable" not in verdict_cell(sig)


def test_two_prop_z_zero_se():
    z, p = two_prop_z(0, 10, 0, 10)
    assert z == 0.0 and p == 1.0


def test_invalid_inputs_rejected():
    """Validation gate #9: n > 0 and x <= n."""
    with pytest.raises(ValueError):
        run_test("bad", 5, 0, 1, 10)
    with pytest.raises(ValueError):
        run_test("bad", 11, 10, 1, 10)


def _mix_rows(k=4, lf_rate=0.35, reece_rate=0.61, n=50):
    return [
        {"source": f"s{i}", "lf_n": n, "lf_sat": int(n * lf_rate),
         "reece_n": n, "reece_sat": int(n * reece_rate)}
        for i in range(k)
    ]


def test_source_mix_reference_shape():
    """Uniform per-source rates: standardised expectation equals the Reece
    rate, the raw gap fully survives, and the state is NOT_EXPLANATORY —
    the approved report's finding (expected 60.5% vs actual 34.7%, z = 8.1)."""
    r = source_mix_test(_mix_rows())
    assert r.state == SOURCE_MIX_NOT_EXPLANATORY
    assert r.remaining_fraction is not None and r.remaining_fraction >= 0.8
    assert r.expected_pct is not None and r.expected_pct > r.actual_pct
    assert r.z is not None and abs(r.z) > 2


def test_source_mix_insufficient_sample():
    """Fewer than 3 shared sources with >= 10 each side."""
    r = source_mix_test(_mix_rows(k=2))
    assert r.state == INSUFFICIENT_SAMPLE
    r2 = source_mix_test([{"source": "a", "lf_n": 9, "lf_sat": 3, "reece_n": 50, "reece_sat": 30}] * 5)
    assert r2.state == INSUFFICIENT_SAMPLE
