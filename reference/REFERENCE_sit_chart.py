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

# net issued >= 20 only — the reliable core
data=[("Flanders, Jamal","R",25,84.0),("Elliott, Andre","R",30,83.3),("Avril, Chantal","R",41,82.9),
      ("Zeffield, Kevin","R",85,81.2),("Linan, Ashley","R",89,80.9),("Toussaint, Marcorie","R",29,79.3),
      ("Nunes, Dylan","R",81,77.8),("Jakob, Robert","R",40,77.5),("Manieri, John","R",76,76.3),
      ("Wright, Carla","L",30,66.7),("Walker, Shari","L",34,64.7),("Deer, Craig","L",97,61.9),
      ("Giraldo, Miguel","R",36,55.6)]
data.sort(key=lambda r:r[3])
names=[f"{d[0]}  ({d[2]})" for d in data]
vals=[d[3] for d in data]
cols=[(GREEN if v>=80 else (RED if v<70 else "#C4802E")) for v in vals]

fig, ax = plt.subplots(figsize=(7.0,3.5))
ax.barh(range(len(data)), vals, color=cols, height=0.62, zorder=2)
ax.axvline(80, color=NAVY, lw=1.6, ls="--", zorder=4)
ax.text(80.7, len(data)-0.35, "goal 80%", color=NAVY, fontsize=8, fontweight="bold")
ax.set_yticks(range(len(data)))
ax.set_yticklabels(names, fontsize=8)
for i,(d,v) in enumerate(zip(data,vals)):
    ax.text(v+0.8, i, f"{v:.1f}%", va="center", fontsize=7.8,
            color=(GREEN if v>=80 else RED), fontweight="bold")
    if d[1]=="L":
        ax.text(1.5, i, "LF", va="center", fontsize=7, color="white", fontweight="bold")
ax.set_xlim(0,100); ax.set_xlabel("Sit % = sits \u00f7 (gross issued \u2212 cancels)")
ax.xaxis.set_major_formatter(FuncFormatter(lambda v,p: f"{v:.0f}%"))
for sp in ("top","right"): ax.spines[sp].set_visible(False)
ax.grid(axis="y", visible=False)
ax.set_title("Sit % against the 80% goal \u2014 setters with 20 or more net issued appointments",
             loc="left", fontweight="bold", fontsize=9.8, color=NAVY, pad=8)
fig.tight_layout(); fig.savefig("/home/claude/report/sit_goal.png", bbox_inches="tight", facecolor="white")
plt.close(fig)
print("ok")
