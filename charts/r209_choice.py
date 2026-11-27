"""Round 209: where the wrong table sits, and the reordering that measured as a wash.

Left: the 91 dev cases that read a table the gold does not, by distance in the join graph the prompt
is built from. Right: the gold tables a card's first three lines would carry, as printed against
ordered by the question's own words — the only prompt change that cannot move the token bill.

Numbers: `pnpm bench:bird:choice --artifact eval/out/bird-eval-dev-44991167518.json` (522 wrong of
1,532, `macsql-prompt`).
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ART = Path("/workspace/nl2charts/eval/out/choice-macsql-prompt-dev.json")
out = json.loads(ART.read_text())
kinds = out["kinds"]
swaps = out["swapKinds"]
windows = {row["at"]: row for row in out["windows"]}
displaced = out["positions"]
total = out["total"]
wrong = out["population"]

LABELS = {"neighbour": "neighbour\n(declared hop)", "sibling": "sibling\n(shared column)", "distant": "distant\n(≥3 hops)"}
COLOURS = {"neighbour": "#2b6cb0", "sibling": "#b7791f", "distant": "#c53030"}

fig, (left, right) = plt.subplots(1, 2, figsize=(11.6, 4.9), gridspec_kw={"width_ratios": [1, 1.06]})

keys = list(LABELS)
values = [kinds[key] for key in keys]
bars = left.bar(range(len(keys)), values, color=[COLOURS[key] for key in keys], width=0.62)
for bar, key in zip(bars, keys):
    share = values[keys.index(key)] / out["casesWithExtra"] * 100
    left.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 0.8,
        f"{kinds[key]}\n{share:.1f}%  ({swaps[key]} tables)",
        ha="center",
        va="bottom",
        fontsize=9.5,
    )
left.set_xticks(range(len(keys)))
left.set_xticklabels([LABELS[key] for key in keys], fontsize=9.5)
left.set_ylim(0, max(values) * 1.42)
left.set_ylabel("dev cases (of 91 that read an extra table)", fontsize=9.5)
left.set_title(
    f"The wrong table is usually not a near miss\n{out['casesWithExtra']} of {wrong} wrong cases read a table the gold does not",
    fontsize=11,
    loc="left",
)
left.spines["top"].set_visible(False)
left.spines["right"].set_visible(False)
left.grid(axis="y", color="#e2e8f0", linewidth=0.8)
left.set_axisbelow(True)

positions = [1, 3, 5]
before = [windows[at]["before"] for at in positions]
after = [windows[at]["after"] for at in positions]
x = range(len(positions))
width = 0.36
b1 = right.bar([i - width / 2 for i in x], before, width, label="as printed", color="#4a5568")
b2 = right.bar([i + width / 2 for i in x], after, width, label="ordered by the question's words", color="#2f855a")
for bar in list(b1) + list(b2):
    right.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2, f"{int(bar.get_height())}", ha="center", fontsize=9.5)
for i, at in enumerate(positions):
    moved, lost = windows[at]["moved"], windows[at]["lost"]
    right.text(i, max(before[i], after[i]) + 26, f"+{moved} in / −{lost} out", ha="center", fontsize=9, color="#2d3748")
right.set_xticks(list(x))
right.set_xticklabels([f"first {at} line{'s' if at > 1 else ''}" for at in positions], fontsize=9.5)
right.set_ylim(0, max(after) * 1.35)
right.set_ylabel(f"displaced gold tables inside the window (of {len(displaced)} displaced)", fontsize=9.5)
right.set_title(
    "The lever that costs no tokens is a wash\nmedian position 3 of ~7, before and after",
    fontsize=11,
    loc="left",
)
right.legend(frameon=False, fontsize=9, loc="upper left")
right.spines["top"].set_visible(False)
right.spines["right"].set_visible(False)
right.grid(axis="y", color="#e2e8f0", linewidth=0.8)
right.set_axisbelow(True)

fig.text(
    0.01,
    0.015,
    f"BIRD dev, run 44991167518, macsql-prompt, {wrong} of {total} wrong ({wrong / total * 100:.1f}%). "
    "Nothing here executes: a difference is not a defect and a position is not a cause.",
    fontsize=8.4,
    color="#4a5568",
)
fig.subplots_adjust(left=0.07, right=0.985, top=0.84, bottom=0.16, wspace=0.28)
fig.savefig("/workspace/charts/r209_choice.png", dpi=150)
print("wrote r209_choice.png")
