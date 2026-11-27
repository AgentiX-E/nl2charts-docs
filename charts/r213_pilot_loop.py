"""Round 213: the VisCodeBench generate → log → score loop closes locally.

No leaderboard reading moved. r212 delivered the comparator; r213 delivered the input contract that
was missing — code emission, a real matplotlib log producer, log parsing and the nested assignment
that wraps the comparators — so the loop now runs end to end at zero cost against an authority oracle.

Figure 1 is Text2SQL, unchanged (standing numbers). Figure 2 is Text2Viz: the VisCodeBench panel now
shows real locally-held *self-check* readings (identity 1.0, a different pie 0.667, a different line
0.903) as hollow markers, kept visually separate from the cited rival's 0.81/0.69. They are explicitly
not a leaderboard score — the row stays instrumented. The right panel is nvBench 2.0, unchanged.

Competitor figures are fixed baselines taken once; self-check readings are harness proofs, not
product accuracy.
"""
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

INK = '#161616'
MUTED = '#5c5c5c'
OURS = '#27ae60'
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
    fig.suptitle('Text2SQL — accuracy vs cost (standing numbers, round 213)',
                 fontsize=11.5, color=INK, y=0.98)

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

    right.set_title('BIRD dev — execution accuracy vs cost', color=INK, fontsize=10)
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
    fig.suptitle('Text2Viz — accuracy vs cost (round 213: pilot loop closed)',
                 fontsize=11.5, color=INK, y=0.98)

    left.set_title('VisCodeBench — displayed-data similarity (0–1)', color=INK, fontsize=10)
    # Cited rival (fixed baseline), visually separate from local self-check readings.
    left.barh([0, 1], [0.81, 0.69], color=[TRAINED, TRAINED], height=0.5)
    left.text(0.82, 0, '0.81', va='center', fontsize=8.5, color=INK)
    left.text(0.70, 1, '0.69', va='center', fontsize=8.5, color=INK)
    # Locally-held self-check readings from the closed loop (hollow diamonds), NOT a leaderboard score.
    checks = [(2, 1.0, 'identity'), (3, 0.903, 'different line'), (4, 0.667, 'different pie')]
    for row, val, label in checks:
        left.scatter([val], [row], marker='D', s=95, facecolors='white', edgecolors=JUDGE, lw=1.8, zorder=4)
        left.text(val + 0.02, row, f'{label} · {val:.3f}', va='center', fontsize=8, color=JUDGE)
    labels = ['leaderboard best\n(cited rival)', 'hardest subset\n(cited rival)',
              'identity', 'different line', 'different pie']
    left.set_yticks(np.arange(5)); left.set_yticklabels(labels, fontsize=8)
    left.invert_yaxis(); left.set_xlim(0, 1.22); left.set_xlabel('displayed-data similarity (0–1)')
    left.text(0.5, 0.99, 'hollow diamonds = local self-check · row stays instrumented',
              ha='center', va='top', fontsize=7.8, color=MUTED, transform=left.transAxes)
    left.grid(axis='x', color=GRID, lw=0.7); left.set_axisbelow(True)

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
    text2sql('/workspace/charts/r213_text2sql_two_axes.png')
    text2viz('/workspace/charts/r213_text2viz_two_axes.png')
    print('wrote r213_text2sql_two_axes.png, r213_text2viz_two_axes.png')
