"""Round 211: the comparison column stops being prose, and Spider's dev EM gets its split back.

No accuracy reading moved this round — the work was to make the leaderboard rivals data instead of
sentences and to correct a DAIL-SQL test EM that had been printed under a dev heading. Both figures
are redrawn from the standing numbers so a reader sees this round's figures, not last round's.

Figure 1 is Text2SQL. The left panel puts this repository on Spider 1.0 dev beside the two verified
dev-EM rivals recorded in `eval/benchmarks.ts`: Graphix-T5-3B + PICARD at 77.1 and DAIL-SQL + GPT-4
at 70.0. The 66.5 that used to sit in this column is DAIL-SQL's TEST EM, marked where it belongs.
The right panel is the BIRD dev accuracy-vs-cost standing: everyone publishes accuracy, only this
repository publishes a bill. Figure 2 is Text2Viz on nvBench 2.0, likewise unchanged in number.

Competitor figures are fixed baselines: each is what the system's own paper or repository prints,
taken once and not re-measured — the rule that keeps a benchmark from being re-litigated every round.
"""
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

INK = '#161616'
MUTED = '#5c5c5c'
OURS = '#27ae60'
OURS_LIGHT = '#a9dfbf'
CLOSED = '#3b6ea5'
TRAINED = '#b8860b'
WRONG = '#b03a2e'
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
        1, 2, figsize=(12.6, 6.2), dpi=170,
        gridspec_kw={'width_ratios': [1.35, 1], 'wspace': 0.34},
    )

    # --- Spider 1.0 dev EM: the corrected column -------------------------------------------------
    spider = [
        ('Graphix-T5-3B + PICARD (dev EM)', 77.1, TRAINED),
        ('DAIL-SQL + GPT-4 (dev EM)', 70.0, CLOSED),
        ('this repository (dev EM, chat)', 61.9, OURS),
        ('DAIL-SQL + GPT-4 (TEST EM — misfiled)', 66.5, WRONG),
    ]
    for index, (name, score, colour) in enumerate(spider):
        left.barh(index, score, color=colour, height=0.56, zorder=2,
                  alpha=0.55 if colour == WRONG else 1.0)
        left.text(score - 0.8, index, f'{score:.1f}', va='center', ha='right', fontsize=8.8,
                  color='white' if colour != WRONG else '#333333', zorder=4)
    left.set_yticks(range(len(spider)))
    left.set_yticklabels([s[0] for s in spider], fontsize=8.9)
    left.invert_yaxis()
    left.set_xlim(55, 84)
    left.set_xlabel('Spider 1.0 dev exact match (%)', fontsize=9.3)
    left.set_title('Spider dev EM: the test number (red) was filed as dev', fontsize=10.2, loc='left', pad=8)
    left.axvline(61.9, color=OURS, linestyle=':', linewidth=0.9, zorder=1)
    left.annotate('15.2pp to the verified dev top', (77.1, 0.0), xytext=(66.5, -0.42),
                  fontsize=8.4, color=MUTED, arrowprops={'arrowstyle': '-', 'color': MUTED, 'lw': 0.8})
    left.grid(axis='x', color=GRID, linewidth=0.6, zorder=0)

    # --- BIRD dev: accuracy vs the one published bill --------------------------------------------
    bird = [
        ('AskData', 78.49, CLOSED),
        ('CHASE-SQL', 74.90, TRAINED),
        ('XiYan-SQL', 73.34, TRAINED),
        ('OpenSearch-SQL', 69.30, CLOSED),
        ('this repository — EX, shipped', 65.93, OURS),
        ('this repository — R-VES', 59.81, OURS_LIGHT),
    ]
    for index, (name, score, colour) in enumerate(bird):
        right.barh(index, score, color=colour, height=0.56, zorder=2,
                   alpha=0.55 if colour == OURS_LIGHT else 1.0)
        right.text(score - 0.8, index, f'{score:.2f}', va='center', ha='right', fontsize=8.6,
                   color='white', zorder=4)
    right.set_yticks(range(len(bird)))
    right.set_yticklabels([b[0] for b in bird], fontsize=8.9)
    right.invert_yaxis()
    right.set_xlim(55, 84)
    right.set_xlabel('BIRD dev execution accuracy (%)', fontsize=9.3)
    right.set_title('BIRD dev: accuracy for all, a bill only here', fontsize=10.2, loc='left', pad=8)
    right.axvline(65.93, color=OURS, linestyle=':', linewidth=0.9, zorder=1)
    right.text(66.6, 5.35, '¥3.22 / 1,000 Q', fontsize=8.2, color='#1e7a46')
    right.grid(axis='x', color=GRID, linewidth=0.6, zorder=0)

    fig.suptitle(
        'Text2SQL, round 211: every rival now carries its split, conditions and model (rule D58)',
        fontsize=12.4, x=0.007, ha='left', y=0.98, color=INK,
    )
    fig.text(
        0.007, 0.012,
        'Green: this repository.   Blue: no training — the class this repository competes in.   '
        'Gold: fine-tunes its generator (out of scope by policy, drawn for scale).   '
        'Red: a number with the wrong split heading.   '
        'Spider dev EM is exact match on 1,034 dev questions; BIRD dev EX is execution accuracy on 1,532.',
        fontsize=8.0, color=MUTED,
    )
    fig.savefig(path, bbox_inches='tight', facecolor='#fbfbf8')
    plt.close(fig)


def text2viz(path):
    fig, ax = plt.subplots(figsize=(8.2, 5.0), dpi=170)
    arms = [
        ('corpus prompting baseline', 58.96, TRAINED),
        ('ceiling', 84.96, CLOSED),
        ('this repository — F1@3, reasoning', 32.23, OURS),
        ('this repository — F1@3, chat', 26.28, OURS_LIGHT),
    ]
    for index, (name, score, colour) in enumerate(arms):
        ax.barh(index, score, color=colour, height=0.55, zorder=2,
                alpha=0.55 if colour == OURS_LIGHT else 1.0)
        ax.text(score - 1.2, index, f'{score:.2f}', va='center', ha='right', fontsize=8.8,
                color='white', zorder=4)
    ax.set_yticks(range(len(arms)))
    ax.set_yticklabels([a[0] for a in arms], fontsize=9.2)
    ax.invert_yaxis()
    ax.set_xlim(0, 95)
    ax.set_xlabel('nvBench 2.0 dev F1@3', fontsize=9.5)
    ax.set_title('Text2Viz, round 211: the trained decoder is a different claim, not this rival',
                 fontsize=11.0, loc='left', pad=10)
    ax.grid(axis='x', color=GRID, linewidth=0.6, zorder=0)
    fig.text(
        0.007, 0.012,
        'Green: this repository, one chart per question.   Gold: the corpus prompting baseline.   '
        'Blue: the ceiling (gold sets hold 2–5 charts, capping recall at k/|G|).   '
        'Step-NL2VIS 81.50 F1@3 trains on the benchmark and is cited, not filed as the rival.',
        fontsize=8.0, color=MUTED,
    )
    fig.savefig(path, bbox_inches='tight', facecolor='#fbfbf8')
    plt.close(fig)


if __name__ == '__main__':
    text2sql('/workspace/charts/r211_text2sql_two_axes.png')
    text2viz('/workspace/charts/r211_text2viz_two_axes.png')
    print('wrote r211_text2sql_two_axes.png, r211_text2viz_two_axes.png')
