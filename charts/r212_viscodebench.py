"""Round 212: the VisCodeBench row becomes instrumented, not measured.

No accuracy reading moved this round. The work was to port the LLM-independent half of the
VisCodeBench score engine locally and to promote the row from `absent` to `instrumented` — because the
primary score is computed on the Codabench server against private reference logs, so this repository
can never hold a `measured` number. Both figures are redrawn from the standing numbers.

Figure 1 is Text2SQL, unchanged: Spider dev EM and BIRD dev accuracy-vs-cost.
Figure 2 is Text2Viz. Its new left panel makes this round's point: the leaderboard-best displayed-data
similarity (0.81, 0.69 on the hardest subset) is a *cited rival*, not a paired reading — the row shows
a judge that passes 13/13 oracle checks but no number of our own. The right panel is nvBench 2.0.

Competitor figures are fixed baselines, taken once from the system's own paper/repository and not
re-measured. The ported engine's own values are oracle checks, not product accuracy, and are labelled
as such.
"""
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

INK = '#161616'
MUTED = '#5c5c5c'
OURS = '#27ae60'
OURS_LIGHT = '#a9dfbf'
CLOSED = '#3b6ea5'
TRAINED = '#b8860b'
JUDGE = '#7d3c98'
GRID = '#e5e5df'

matplotlib.rcParams.update({
    'font.family': 'DejaVu Sans',
    'font.size': 9.5,
    'axes.edgecolor': GRID,
    'axes.labelcolor': MUTED,
    'xtick.color': MUTED,
    'ytick.color': INK,
    'axes.spines.top': False,
    'axes.spines.right': False,
})


def text2sql(path):
    fig, (left, right) = plt.subplots(
        1, 2, figsize=(12.6, 5.2), dpi=170, gridspec_kw={'width_ratios': [1, 1.15]}
    )
    fig.suptitle('Text2SQL — accuracy vs cost (standing numbers, round 212)',
                 fontsize=11.5, color=INK, y=0.98)

    # Spider 1.0 dev EM.
    left.set_title('Spider 1.0 dev — exact match (%)', color=INK, fontsize=10)
    names = ['Graphix-T5-3B\n+PICARD', 'DAIL-SQL\n+GPT-4 (dev)', 'nl2charts\n(grammar+repair)']
    vals = [77.1, 70.0, 61.90]
    colors = [TRAINED, TRAINED, OURS]
    y = np.arange(len(names))
    left.barh(y, vals, color=colors, height=0.62)
    left.set_yticks(y); left.set_yticklabels(names, fontsize=8.5)
    left.invert_yaxis(); left.set_xlim(0, 100)
    left.set_xlabel('dev EM (%)')
    for i, v in enumerate(vals):
        left.text(v + 1, i, f'{v:.2f}', va='center', fontsize=8.5, color=INK)
    left.axvline(61.90, color=OURS, lw=0.8, ls='--', alpha=0.6)
    left.text(63, 2.4, 'gap to verified dev EM: 15.2pp', color=MUTED, fontsize=8)
    left.grid(axis='x', color=GRID, lw=0.7); left.set_axisbelow(True)

    # BIRD dev accuracy vs cost.
    right.set_title('BIRD dev — execution accuracy vs cost', color=INK, fontsize=10)
    # x = relative token cost (log-ish), y = dev EX
    systems = [
        ('nl2charts (macsql-prompt)', 65.93, 1.0, OURS, 'self-hosted, ¥3.22/1k'),
        ('AskData (GPT-4o, 8+ calls)', 78.49, 7.5, TRAINED, 'closed / training-free'),
        ('DAIL-SQL + GPT-4', 66.5, 6.0, CLOSED, 'closed service'),
    ]
    for name, ex, cost, color, tag in systems:
        right.scatter(cost, ex, s=150, color=color, zorder=3, edgecolor='white', lw=1)
        right.annotate(f'{name}\n{ex:.2f} EX · {tag}', (cost, ex),
                       textcoords='offset points', xytext=(8, 6), fontsize=8, color=INK)
    right.set_xlabel('relative token cost (1× = nl2charts, log scale)')
    right.set_ylabel('dev EX (%)')
    right.set_xscale('log'); right.set_ylim(58, 84); right.set_xlim(0.6, 14)
    right.grid(color=GRID, lw=0.7); right.set_axisbelow(True)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(path, bbox_inches='tight', facecolor='#fbfbf8')
    plt.close(fig)


def text2viz(path):
    fig, (left, right) = plt.subplots(1, 2, figsize=(12.6, 5.2), dpi=170)
    fig.suptitle('Text2Viz — accuracy vs cost (round 212: VisCodeBench instrumented)',
                 fontsize=11.5, color=INK, y=0.98)

    # VisCodeBench: cited rival, no paired local reading.
    left.set_title('VisCodeBench — displayed-data similarity (0–1)', color=INK, fontsize=10)
    labels = ['leaderboard best\n(cited rival)', 'hardest subset\n(OWID, cited)', 'nl2charts\n(no reading)']
    vals = [0.81, 0.69, None]
    y = np.arange(len(labels))
    left.barh(y[:2], vals[:2], color=[TRAINED, TRAINED], height=0.55)
    # No local bar: show the instrumented judge with a hollow marker instead.
    left.scatter([0], [2], s=170, facecolors='white', edgecolors=JUDGE, lw=2, zorder=4)
    left.text(0.03, 2, 'judge ported · 13/13 oracle · ¥0 · NO score', va='center', fontsize=8.5, color=JUDGE)
    left.set_yticks(y); left.set_yticklabels(labels, fontsize=8.5); left.invert_yaxis()
    left.set_xlim(0, 1.05); left.set_xlabel('displayed-data similarity (0–1)')
    for i, v in enumerate(vals[:2]):
        left.text(v + 0.01, i, f'{v:.2f}', va='center', fontsize=8.5, color=INK)
    left.text(0.5, 2.55, 'private references → score lives on Codabench server',
              ha='center', fontsize=8, color=MUTED)
    left.grid(axis='x', color=GRID, lw=0.7); left.set_axisbelow(True)

    # nvBench 2.0 F1@3.
    right.set_title('nvBench 2.0 — F1@3', color=INK, fontsize=10)
    names = ['Step-NL2VIS\n(SFT, different claim)', 'corpus prompt\nbaseline', 'nl2charts\n(reasoning tier)']
    vals = [81.50, 58.96, 32.23]
    colors = [TRAINED, CLOSED, OURS]
    y = np.arange(len(names))
    right.barh(y, vals, color=colors, height=0.6)
    right.set_yticks(y); right.set_yticklabels(names, fontsize=8.5); right.invert_yaxis()
    right.set_xlim(0, 100); right.set_xlabel('F1@3')
    for i, v in enumerate(vals):
        right.text(v + 1, i, f'{v:.2f}', va='center', fontsize=8.5, color=INK)
    right.grid(axis='x', color=GRID, lw=0.7); right.set_axisbelow(True)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(path, bbox_inches='tight', facecolor='#fbfbf8')
    plt.close(fig)


if __name__ == '__main__':
    text2sql('/workspace/charts/r212_text2sql_two_axes.png')
    text2viz('/workspace/charts/r212_text2viz_two_axes.png')
    print('wrote r212_text2sql_two_axes.png, r212_text2viz_two_axes.png')
