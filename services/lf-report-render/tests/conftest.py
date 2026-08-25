"""Shared fixtures. GOLDEN_LF_ROWS is the page-1 Lightfire table of the
approved 2026-08-17 report, reconstructed from the canonical reference
(page-1 sit table × page-3 ranking): each row's gross_issued/cancels/
net_issued/sat comes from page 1; matured/sold/gross come from page 3.
Cross-check: the 11 rows sum to 238 / 4 / 234 / 154 — exactly the approved
"Lightfire total" row, which is how we know the reconstruction is faithful.
"""
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from calculations import AgentCohort  # noqa: E402  (needs the path insert above)

# name, matured, gross_issued, cancels, net_issued, sat, sold, gross_dollars
_GOLDEN_LF = [
    ("Gordon, Grecian",    9,  7, 1,  6,  6,  2,  29613),
    ("Dennis, Jodian",    12,  7, 0,  7,  6,  1,   6500),
    ("Martin, Nickalos",  13,  7, 1,  6,  5,  1,   4198),
    ("Slowely, Diamoneke", 56, 17, 0, 17, 14,  3,  86905),
    ("Bryce, Shaday",     15,  8, 0,  8,  6,  1,  15500),
    ("Wright, Carla",     77, 30, 0, 30, 20,  7, 106712),
    ("Walker, Shari",     57, 34, 0, 34, 22,  7, 127953),
    ("Deer, Craig",      152, 99, 2, 97, 60, 20, 465543),
    ("Evans, Tresharna",  23, 13, 0, 13,  8,  4, 117787),
    ("Campbell, Brittany", 8,  5, 0,  5,  3,  1,  19561),
    ("Francis, Yanique",  15, 11, 0, 11,  4,  0,      0),
]


def golden_lf_agents() -> list[AgentCohort]:
    return [
        AgentCohort(
            setter_name=n, team="Lightfire", matured=m, gross_issued=gi,
            cancels=cx, net_issued=ni, sat=sat, sold=sold, gross_cents=gross * 100,
        )
        for n, m, gi, cx, ni, sat, sold, gross in _GOLDEN_LF
    ]
