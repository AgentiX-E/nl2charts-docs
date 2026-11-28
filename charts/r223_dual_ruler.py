"""Round 223: the second ruler is dispatchable, and the cost gate now covers both.

No accuracy reading moved. r223 did three things: (1) found and fixed a cost-discipline hole —
bench:bird:partial-coverage ignored VALUE_PRICING_ACCEPT_COST while bench:bird:price honoured it,
so a hosted dispatch could spend under one ruler what the other refused; (2) added an `instrument`
choice to the value-pricing workflow so both rulers share one cache/secret/data contract and their
reports cannot overwrite each other; (3) read OpenSearch-SQL source line-by-line to upgrade the P1
schema-linking list from second-hand claims to confirmed algorithm (next round's work).

Figure 1 is Text2SQL (standing numbers + a boxed note on the r223 work). Figure 2 is Text2Viz
(standing numbers). Competitor figures are fixed baselines taken once. The partial-coverage reading
is from a hash harness and is labelled HARNESS PROOF, not accuracy. No SOTA claim is made.
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
GATE = '#c0392b'
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
        1, 2, figsize=(12.6, 5.4), dpi=170, gridspec_kw={'width_ratios': [1, 1.15]}
    )
    fig.suptitle('Text2SQL — accuracy vs cost (standing numbers, round 223: dual-ruler dispatch)',
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
    right.text(0.62, 59.2,
               'r223 hosted dispatch (run 46149078979):\n'
               '37 wins / 1 loss, p=2.8e-10, delta=+60pp\n'
               '[39.9,80.1]. GROUNDING COVERAGE, NOT accuracy.\n'
               'No SHIPPED_SQL promotion; no SOTA claim.',
               fontsize=6.9, color=GATE, va='bottom',
               bbox=dict(boxstyle='round,pad=0.3', fc='#fdf2f0', ec=GATE, lw=0.6, alpha=0.95))

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(path, bbox_inches='tight', facecolor='#fbfbf8')
    plt.close(fig)


def text2viz(path):
    fig, (left, right) = plt.subplots(1, 2, figsize=(12.6, 5.4), dpi=170)
    fig.suptitle('Text2Viz — accuracy vs cost (round 223: readings unchanged)',
                 fontsize=11.5, color=INK, y=0.98)

    left.set_title('VisCodeBench — displayed-data similarity (0–1)', color=INK, fontsize=10)
    left.barh([0, 1], [0.81, 0.69], color=[TRAINED, TRAINED], height=0.5)
    left.text(0.82, 0, '0.81', va='center', fontsize=8.5, color=INK)
    left.text(0.70, 1, '0.69', va='center', fontsize=8.5, color=INK)
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
    right.text(0.5, 0.02, 'round 223 changed the TEXT2SQL ruler only; Text2Viz readings unchanged',
               ha='center', va='bottom', fontsize=7.6, color=MUTED, transform=right.transAxes)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(path, bbox_inches='tight', facecolor='#fbfbf8')
    plt.close(fig)


if __name__ == '__main__':
    text2sql('/workspace/docs-src/charts/r223_text2sql_two_axes.png')
    text2viz('/workspace/docs-src/charts/r223_text2viz_two_axes.png')
    print('wrote r223_text2sql_two_axes.png, r223_text2viz_two_axes.png')
