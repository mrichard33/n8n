"""Visual regression (§11/§21): render the golden payload, rasterise at
150 dpi, compare per page against tests/baseline/. Fails when the differing
pixel fraction exceeds visual_diff_tolerance (0.005).

Re-blessing the baseline requires an explicit commit that also touches
docs/REPORT_SPEC.md stating the reason — CI fails a baseline change without
it. The baseline was blessed once from the first golden render (the §9 KPI
third row makes pixel-identity with the hand-issued 8/17 PDF impossible; §9
pre-authorises exactly that one re-bless).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from report_builder import build_report
from schema import ReportPayload

BASELINE = Path(__file__).parent / "baseline"
GOLDEN = Path(__file__).parent / "golden_payload.json"
TOLERANCE = 0.005
CHANNEL_SLACK = 12  # per-channel difference treated as anti-aliasing noise

pdftoppm_missing = shutil.which("pdftoppm") is None


@pytest.mark.skipif(pdftoppm_missing, reason="poppler-utils not installed")
def test_golden_render_matches_baseline(tmp_path):
    payload = ReportPayload.model_validate(json.loads(GOLDEN.read_text()))
    pdf = tmp_path / "render.pdf"
    build_report(payload, str(pdf))
    subprocess.run(["pdftoppm", "-r", "150", "-png", str(pdf), str(tmp_path / "page")],
                   check=True)

    baseline_pages = sorted(BASELINE.glob("page-*.png"))
    assert len(baseline_pages) == 4, "baseline must hold exactly four pages"
    for ref_path in baseline_pages:
        new_path = tmp_path / ref_path.name
        assert new_path.exists(), f"render produced no {ref_path.name}"
        ref = Image.open(ref_path).convert("RGB")
        new = Image.open(new_path).convert("RGB")
        assert ref.size == new.size, f"{ref_path.name}: size {new.size} != baseline {ref.size}"
        diff = ImageChops.difference(ref, new).convert("RGB")
        # count pixels whose max channel difference exceeds the AA slack
        thresholded = diff.point(lambda v: 255 if v > CHANNEL_SLACK else 0)
        bbox_hist = thresholded.convert("L").histogram()
        differing = sum(bbox_hist[1:])
        fraction = differing / (ref.size[0] * ref.size[1])
        assert fraction <= TOLERANCE, (
            f"{ref_path.name}: {fraction:.4%} of pixels differ (tolerance {TOLERANCE:.1%}). "
            "If this change is intentional, re-bless tests/baseline/ AND record the reason "
            "in docs/REPORT_SPEC.md in the same commit.")
