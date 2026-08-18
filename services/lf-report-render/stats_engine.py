"""Statistical engine (Handoff V2 §7). Code only — no LLM ever computes or
interprets a test, and no verdict string is ever stored: the sentence is
selected from the computed p every week, so a verdict can never outlive the
number it describes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

SIGNIFICANT = "SIGNIFICANT"
NOT_DISTINGUISHABLE = "NOT_DISTINGUISHABLE"

# Source-mix explanation states (§7). Narrative is selected from the state —
# the strong conclusion is never asserted unless the state supports it.
INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
SOURCE_MIX_NOT_EXPLANATORY = "SOURCE_MIX_NOT_EXPLANATORY"
SOURCE_MIX_PARTIALLY_EXPLANATORY = "SOURCE_MIX_PARTIALLY_EXPLANATORY"
SOURCE_MIX_EXPLANATORY = "SOURCE_MIX_EXPLANATORY"


@dataclass(frozen=True)
class StatTest:
    name: str
    s1_n: int
    s1_x: int
    s2_n: int
    s2_x: int
    z: float
    p: float
    alpha: float
    verdict: str  # SIGNIFICANT | NOT_DISTINGUISHABLE

    def as_record(self) -> dict:
        """Row shape persisted to lf_report_metrics.stat_tests."""
        return {
            "name": self.name, "s1_n": self.s1_n, "s1_x": self.s1_x,
            "s2_n": self.s2_n, "s2_x": self.s2_x,
            "z": round(self.z, 4), "p": round(self.p, 6),
            "alpha": self.alpha, "verdict": self.verdict,
        }


def two_prop_z(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    """Two-proportion z, two-sided — exactly the §7 formula."""
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / se if se else 0.0
    return z, math.erfc(abs(z) / math.sqrt(2))


def run_test(name: str, x1: int, n1: int, x2: int, n2: int, alpha: float = 0.05) -> StatTest:
    """Validation gate #9 enforced here too: all n > 0, x <= n."""
    for x, n in ((x1, n1), (x2, n2)):
        if n <= 0 or x < 0 or x > n:
            raise ValueError(f"invalid test inputs for {name}: x={x}, n={n}")
    z, p = two_prop_z(x1, n1, x2, n2)
    return StatTest(name, n1, x1, n2, x2, z, p, alpha,
                    SIGNIFICANT if p < alpha else NOT_DISTINGUISHABLE)


def verdict_cell(t: StatTest) -> str:
    """Table-cell text. The wording rule (§7, non-negotiable): a null NEVER
    renders as 'the same' — it renders 'not distinguishable'.
    Canonical forms from the approved report: 'p < 0.0001' and
    'p = 0.14 — not distinguishable'."""
    if t.verdict == SIGNIFICANT:
        return "p < 0.0001" if t.p < 0.0001 else f"p = {t.p:.3f} — significant"
    return f"p = {t.p:.2f} — not distinguishable"


@dataclass(frozen=True)
class SourceMixResult:
    state: str
    shared_sources: int            # sources with >= min_n on BOTH sides
    expected_pct: float | None     # LF mix at Reece per-source rates
    actual_pct: float | None       # LF pooled sit over the shared sources
    reece_pct: float | None        # Reece pooled sit over the shared sources
    z: float | None
    p: float | None
    remaining_fraction: float | None  # (expected - actual) / raw gap


def source_mix_test(rows: list[dict], *, min_n_each_side: int = 10,
                    min_shared_sources: int = 3, alpha: float = 0.05) -> SourceMixResult:
    """Direct standardisation (§7 test 3): apply Reece per-source sit rates to
    Lightfire's source mix. rows = Q7 output dicts with keys
    source, reece_n, reece_sat, lf_n, lf_sat (counts, not percentages).

    remaining_fraction is how much of the raw LF-vs-Reece gap SURVIVES after
    handing LF the Reece rates on LF's own mix: >= 0.8 -> mix explains nothing.
    """
    shared = [r for r in rows if r["lf_n"] >= min_n_each_side and r["reece_n"] >= min_n_each_side]
    if len(shared) < min_shared_sources:
        return SourceMixResult(INSUFFICIENT_SAMPLE, len(shared), None, None, None, None, None, None)

    lf_n = sum(r["lf_n"] for r in shared)
    lf_sat = sum(r["lf_sat"] for r in shared)
    reece_n = sum(r["reece_n"] for r in shared)
    reece_sat = sum(r["reece_sat"] for r in shared)

    expected_sits = sum(r["lf_n"] * (r["reece_sat"] / r["reece_n"]) for r in shared)
    expected = expected_sits / lf_n
    actual = lf_sat / lf_n
    reece_rate = reece_sat / reece_n

    z, p = two_prop_z(round(expected_sits), lf_n, lf_sat, lf_n)

    raw_gap = reece_rate - actual
    remaining = (expected - actual) / raw_gap if raw_gap else 0.0
    if remaining >= 0.8:
        state = SOURCE_MIX_NOT_EXPLANATORY
    elif remaining >= 0.3:
        state = SOURCE_MIX_PARTIALLY_EXPLANATORY
    else:
        state = SOURCE_MIX_EXPLANATORY
    return SourceMixResult(state, len(shared), expected * 100, actual * 100,
                           reece_rate * 100, z, p, remaining)
