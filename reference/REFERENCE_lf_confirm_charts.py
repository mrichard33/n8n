#!/usr/bin/env python3
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter

NAVY="#12395B"; RED="#A3231C"; GREEN="#1D6236"; SLATE="#5A6673"; RULE="#D4DAE0"; LF="#1F6F8B"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":8.5,
 "axes.edgecolor":RULE,"axes.linewidth":0.8,"axes.labelcolor":SLATE,"text.color":"#12181F",
 "xtick.color":SLATE,"ytick.color":SLATE,"axes.grid":True,"grid.color":RULE,
 "grid.linewidth":0.6,"grid.alpha":0.8,"figure.dpi":200,"savefig.dpi":200})
def strip(ax):
    for sp in ("top","right"): ax.spines[sp].set_visible(False)

# ---------- 1. Who confirms whose book (stacked)
teams=["Lightfire-set\n(446 appts)","Reece-set\n(678 appts)"]
seg=[("Reece desk",[22.4,87.0],NAVY),("Lightfire self-confirmed",[37.7,0.9],LF),
     ("AI / other",[1.6,1.3],"#B9C6D2"),("No confirmer of record",[38.3,10.8],RED)]
fig, ax = plt.subplots(figsize=(7.0,2.4))
left=np.zeros(2)
for nm,vals,col in seg:
    v=np.array(vals,dtype=float)
    ax.barh(teams, v, left=left, color=col, height=0.5, label=nm, zorder=2)
    for i,(x,l) in enumerate(zip(v,left)):
        if x>=5:
            ax.text(l+x/2, i, f"{x:.0f}%", ha="center", va="center", fontsize=8,
                    color="white", fontweight="bold")
    left+=v
ax.set_xlim(0,100); ax.set_xlabel("Share of matured appointments")
ax.xaxis.set_major_formatter(FuncFormatter(lambda v,p: f"{v:.0f}%"))
strip(ax); ax.grid(axis="y", visible=False)
ax.invert_yaxis()
ax.legend(frameon=False, fontsize=7.6, ncol=4, loc="upper center", bbox_to_anchor=(0.5,-0.32))
ax.set_title("Who confirms whose book \u2014 38% of Lightfire's appointments carry no confirmer of record",
             loc="left", fontweight="bold", fontsize=9.6, color=NAVY, pad=8)
fig.savefig("/home/claude/report/lf_ownership.png", bbox_inches="tight", facecolor="white")
plt.close(fig)

# ---------- 2. Outcomes with vs without a confirmer
groups=["Lightfire\nconfirmed\n(275)","Lightfire\nnot confirmed\n(171)","Reece\nconfirmed\n(605)","Reece\nnot confirmed\n(73)"]
issued=[85.1,4.1,92.9,13.7]; sat=[55.3,2.9,73.4,1.4]
x=np.arange(4); w=0.36
fig, ax = plt.subplots(figsize=(7.0,2.75))
cols_i=[LF,"#D9A7A5",NAVY,"#D9A7A5"]; cols_s=["#7FB3C4","#EBD3D2","#7E93A8","#EBD3D2"]
ax.bar(x-w/2, issued, width=w, color=cols_i, label="Issued", zorder=2)
ax.bar(x+w/2, sat,    width=w, color=cols_s, label="Sat", zorder=2)
for i,(a,b) in enumerate(zip(issued,sat)):
    ax.text(i-w/2, a+2, f"{a:.0f}%", ha="center", fontsize=7.8, fontweight="bold", color=SLATE)
    ax.text(i+w/2, b+2, f"{b:.0f}%", ha="center", fontsize=7.8, color=SLATE)
for i,lbl in [(1,"0 sales"),(3,"0 sales")]:
    ax.text(i, 30, lbl, ha="center", fontsize=9, color=RED, fontweight="bold", style="italic")
ax.set_xticks(x); ax.set_xticklabels(groups, fontsize=7.8)
ax.set_ylabel("Share of appointments"); ax.set_ylim(0,105)
ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p: f"{v:.0f}%"))
strip(ax); ax.grid(axis="x", visible=False)
ax.legend(frameon=False, fontsize=8, ncol=2, loc="upper right")
ax.set_title("Every sale either team made came from a confirmed appointment",
             loc="left", fontweight="bold", fontsize=10, color=NAVY, pad=8)
fig.tight_layout(); fig.savefig("/home/claude/report/lf_confirm_value.png", bbox_inches="tight", facecolor="white")
plt.close(fig)
print("ok")
