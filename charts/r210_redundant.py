"""Round 210: the bucket that was a measurement bug, and the correction.

Left: what round 209 published — 41.8% of statements that read an extra table were said to read one
two joins away from the gold. Right: the corrected reading, taken after `swapOf` stopped measuring a
distance to an empty displaced set. The 38 cases did not displace a gold table at all: they read
every gold table and one more.

Numbers: `pnpm bench:bird:choice --artifact eval/out/bird-eval-dev-44991167518.json`, dev run
44991167518, macsql-prompt, 522 wrong of 1,532, 91 cases read an extra table.
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = json.loads(Path("/workspace/nl2charts/eval/out/choice-macsql-prompt-dev.json").read_text())
kinds = OUT["kinds"]
n = OUT["casesWithExtra"]

LABELS = ["neighbour", "sibling", "distant", "redundant"]
OLD = [32, 21, 38, 0]
NEW = [kinds[k] for k in LABELS]
COLOURS = ["#2b6cb0", "#b7791f", "#c53030", "#2f855a"]

fig, (left, right) = plt.subplots(1, 2, figsize=(11.8, 5.0), gridspec_kw={"width_ratios": [1, 1]})

for ax, values, title, subtitle in [
    (left, OLD, "Round 209: what was published", "a distance measured to an empty displaced set"),
    (right, NEW, "Round 210: after the fix", "no gold table displaced -> not a distance"),
]:
    bars = ax.bar(range(len(LABELS)), values, color=COLOURS, width=0.64)
    for bar, v in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.8,
            f"{v}\n{v / n * 100:.1f}%",
            ha="center", va="bottom", fontsize=10,
        )
    ax.set_xticks(range(len(LABELS)))
    ax.set_xticklabels(LABELS, fontsize=10)
    ax.set_ylim(0, max(max(OLD), max(NEW)) * 1.4)
    ax.set_ylabel(f"dev cases (of {n} that read an extra table)", fontsize=9.5)
    ax.set_title(f"{title}\n{subtitle}", fontsize=11, loc="left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#e2e8f0", linewidth=0.8)
    ax.set_axisbelow(True)

left.annotate(
    "the largest bucket was\nthis measurement artefact",
    xy=(2, 38), xytext=(1.15, 46),
    fontsize=9.5, color="#c53030", ha="center",
    arrowprops=dict(arrowstyle="->", color="#c53030", lw=1.4),
)
right.annotate(
    "every gold table was read;\none extra table was not a join choice",
    xy=(3, 38), xytext=(1.9, 47),
    fontsize=9.5, color="#2f855a", ha="center",
    arrowprops=dict(arrowstyle="->", color="#2f855a", lw=1.4),
)

fig.text(
    0.01, 0.015,
    "BIRD dev, run 44991167518, macsql-prompt. Zero cases read a table beyond two hops of a displaced "
    "gold table; the generation-side work item built on the old bucket was withdrawn. ¥0, no dispatch.",
    fontsize=8.2, color="#4a5568",
)
fig.subplots_adjust(left=0.07, right=0.985, top=0.84, bottom=0.16, wspace=0.26)
fig.savefig("/workspace/charts/r210_redundant.png", dpi=150)
print("wrote r210_redundant.png")
