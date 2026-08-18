"""Chart rendering, ported from REFERENCE_lf_confirm_charts.py and
REFERENCE_sit_chart.py. The golden PDF embeds exactly ONE chart — the
confirmation-ownership stacked bar on page 2 (verified against the canonical
artifact: 4 pages, one RGBA image + its alpha mask). The sit-vs-goal and
confirmed-vs-unconfirmed charts are ported for completeness but are NOT placed
in the document; see docs/REPORT_SPEC.md.

Style values are verbatim from the reference scripts. Only data and output
paths are parameterized.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

NAVY = "#12395B"; RED = "#A3231C"; GREEN = "#1D6236"; SLATE = "#5A6673"
RULE = "#D4DAE0"; LF = "#1F6F8B"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5,
    "axes.edgecolor": RULE, "axes.linewidth": 0.8, "axes.labelcolor": SLATE,
    "text.color": "#12181F", "xtick.color": SLATE, "ytick.color": SLATE,
    "axes.grid": True, "grid.color": RULE, "grid.linewidth": 0.6,
    "grid.alpha": 0.8, "figure.dpi": 200, "savefig.dpi": 200,
})


def _strip(ax):
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)


def ownership_chart(out_path: str, *, lf_matured: int, reece_matured: int,
                    lf_pcts: dict, reece_pcts: dict, headline_noconf_pct: float) -> str:
    """Page-2 stacked bar: who confirms whose book. pcts dicts carry keys
    desk, self, ai_other, none (percent shares summing ~100 per team)."""
    teams = [f"Lightfire-set\n({lf_matured} appts)", f"Reece-set\n({reece_matured} appts)"]
    seg = [
        ("Reece desk", [lf_pcts["desk"], reece_pcts["desk"]], NAVY),
        ("Lightfire self-confirmed", [lf_pcts["self"], reece_pcts["self"]], LF),
        ("AI / other", [lf_pcts["ai_other"], reece_pcts["ai_other"]], "#B9C6D2"),
        ("No confirmer of record", [lf_pcts["none"], reece_pcts["none"]], RED),
    ]
    fig, ax = plt.subplots(figsize=(7.0, 2.4))
    left = np.zeros(2)
    for nm, vals, col in seg:
        v = np.array(vals, dtype=float)
        ax.barh(teams, v, left=left, color=col, height=0.5, label=nm, zorder=2)
        for i, (x, l) in enumerate(zip(v, left)):
            if x >= 5:
                ax.text(l + x / 2, i, f"{x:.0f}%", ha="center", va="center",
                        fontsize=8, color="white", fontweight="bold")
        left += v
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of matured appointments")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:.0f}%"))
    _strip(ax)
    ax.grid(axis="y", visible=False)
    ax.invert_yaxis()
    ax.legend(frameon=False, fontsize=7.6, ncol=4, loc="upper center",
              bbox_to_anchor=(0.5, -0.32))
    ax.set_title(
        f"Who confirms whose book — {headline_noconf_pct:.0f}% of Lightfire's "
        "appointments carry no confirmer of record",
        loc="left", fontweight="bold", fontsize=9.6, color=NAVY, pad=8)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# Ported but NOT placed in the document (REPORT_SPEC): kept so a future edition
# can adopt them without re-deriving the style.
# ---------------------------------------------------------------------------


def sit_goal_chart(out_path: str, rows: list[tuple[str, str, int, float]],
                   *, goal_pct: float = 80.0) -> str:
    """rows: (name, 'R'|'L', net_issued, issued_sit_pct) for net_issued >= 20."""
    data = sorted(rows, key=lambda r: r[3])
    names = [f"{d[0]}  ({d[2]})" for d in data]
    vals = [d[3] for d in data]
    cols = [(GREEN if v >= goal_pct else (RED if v < 70 else "#C4802E")) for v in vals]
    fig, ax = plt.subplots(figsize=(7.0, 3.5))
    ax.barh(range(len(data)), vals, color=cols, height=0.62, zorder=2)
    ax.axvline(goal_pct, color=NAVY, lw=1.6, ls="--", zorder=4)
    ax.text(goal_pct + 0.7, len(data) - 0.35, f"goal {goal_pct:.0f}%",
            color=NAVY, fontsize=8, fontweight="bold")
    ax.set_yticks(range(len(data)))
    ax.set_yticklabels(names, fontsize=8)
    for i, (d, v) in enumerate(zip(data, vals)):
        ax.text(v + 0.8, i, f"{v:.1f}%", va="center", fontsize=7.8,
                color=(GREEN if v >= goal_pct else RED), fontweight="bold")
        if d[1] == "L":
            ax.text(1.5, i, "LF", va="center", fontsize=7, color="white", fontweight="bold")
    ax.set_xlim(0, 100)
    ax.set_xlabel("Sit % = sits ÷ (gross issued − cancels)")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:.0f}%"))
    _strip(ax)
    ax.grid(axis="y", visible=False)
    ax.set_title(
        "Sit % against the goal — setters with 20 or more net issued appointments",
        loc="left", fontweight="bold", fontsize=9.8, color=NAVY, pad=8)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path


def confirm_value_chart(out_path: str, groups: list[str], issued: list[float],
                        sat: list[float], zero_sale_idx: list[int]) -> str:
    x = np.arange(len(groups)); w = 0.36
    fig, ax = plt.subplots(figsize=(7.0, 2.75))
    cols_i = [LF, "#D9A7A5", NAVY, "#D9A7A5"][: len(groups)]
    cols_s = ["#7FB3C4", "#EBD3D2", "#7E93A8", "#EBD3D2"][: len(groups)]
    ax.bar(x - w / 2, issued, width=w, color=cols_i, label="Issued", zorder=2)
    ax.bar(x + w / 2, sat, width=w, color=cols_s, label="Sat", zorder=2)
    for i, (a, b) in enumerate(zip(issued, sat)):
        ax.text(i - w / 2, a + 2, f"{a:.0f}%", ha="center", fontsize=7.8,
                fontweight="bold", color=SLATE)
        ax.text(i + w / 2, b + 2, f"{b:.0f}%", ha="center", fontsize=7.8, color=SLATE)
    for i in zero_sale_idx:
        ax.text(i, 30, "0 sales", ha="center", fontsize=9, color=RED,
                fontweight="bold", style="italic")
    ax.set_xticks(x)
    ax.set_xticklabels(groups, fontsize=7.8)
    ax.set_ylabel("Share of appointments")
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:.0f}%"))
    _strip(ax)
    ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="upper right")
    ax.set_title("Every sale either team made came from a confirmed appointment",
                 loc="left", fontweight="bold", fontsize=10, color=NAVY, pad=8)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path
