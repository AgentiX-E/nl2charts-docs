"""The standing figures for round 204, and one new one: what the rewrites are actually worth.

No accuracy reading moved this round — the round priced the same Mini-Dev artifact and dispatched no
run — so the two position charts carry the round-203 numbers unchanged. They are redrawn rather than
re-linked because a report that points at last round's figure is quietly claiming the figure is this
round's, and these charts exist to be checked rather than admired.

The third figure is new and it is the round's finding: the pricer's union, the number a product
sentence would quote as "what the deterministic rewrites are worth", was computed over `net > 0`. On
496 Mini-Dev questions that reads 21 cases; over the three rules the pipeline actually applies it
reads 11. The segments are the cases each rule adds to the union, in the order they are counted, so
the stacks are the two definitions rather than an artistic impression of them.

Competitor numbers are a fixed baseline: each is what the system's own paper or repository prints,
taken once and not re-measured (the rule that keeps a benchmark from being re-litigated every round).
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
UNSTATED = '#c9ccd1'
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


def bird_dev(path):
    """Text2SQL on BIRD dev: accuracy for everyone, cost for the one system that measured it."""
    # (name, EX, kind). `trained` is drawn separately because this repository does not train a
    # generator, so a system that does is a different kind of object rather than a better version.
    systems = [
        ('AskData (2025)', 78.49, 'closed'),
        ('CHASE-SQL (2024)', 76.02, 'trained'),
        ('XiYan-SQL (2025)', 75.63, 'trained'),
        ('CSC-SQL (2025)', 73.67, 'trained'),
        ('Reasoning-SQL (2025)', 72.78, 'trained'),
        ('OpenSearch-SQL (2025)', 72.28, 'closed'),
        ('OmniSQL (2025)', 72.06, 'trained'),
        ('Distillery (2024)', 71.83, 'unstated'),
        ('CHESS (2024)', 71.10, 'closed'),
        ('this repository — EX, shipped arm', 65.93, 'ours'),
        ('this repository — R-VES, same statements', 59.81, 'ours-lite'),
    ]
    colour = {'closed': CLOSED, 'trained': TRAINED, 'unstated': UNSTATED, 'ours': OURS, 'ours-lite': OURS_LIGHT}

    fig, (left, right) = plt.subplots(
        1, 2, figsize=(12.4, 6.2), dpi=170, gridspec_kw={'width_ratios': [1.55, 1], 'wspace': 0.28}
    )

    for index, (name, score, kind) in enumerate(systems):
        left.barh(index, score, color=colour[kind], height=0.58, zorder=2)
        left.text(
            score - 0.7, index, f'{score:.2f}', va='center', ha='right', fontsize=8.8,
            color='white' if kind in ('closed', 'trained', 'ours', 'ours-lite') else '#333333', zorder=4,
        )
        if kind in ('closed', 'trained', 'unstated'):
            left.scatter(score + 1.5, index, s=24, facecolor='white', edgecolor='#999999', linewidth=1.0, zorder=3)
    left.set_yticks(range(len(systems)))
    left.set_yticklabels([s[0] for s in systems], fontsize=9.2)
    left.invert_yaxis()
    left.set_xlim(55, 86)
    left.set_xlabel('BIRD dev execution accuracy, as each system reports it (%)', fontsize=9.3)
    left.set_title('Accuracy: 12.56pp behind the field top', fontsize=10.6, loc='left', pad=8)
    left.axvline(65.93, color=OURS, linestyle=':', linewidth=0.9, zorder=1)
    left.grid(axis='x', color=GRID, linewidth=0.6, zorder=0)

    # The cost axis has exactly one point on it, and that is the finding rather than a gap in the
    # drawing: no system in this field publishes a bill, so the ring band is where the nine others
    # would have to be plotted if they did.
    right.axhspan(1.62, 2.24, color='#f4f4f0', zorder=0)
    right.text(56.7, 2.16, '9 systems,\nno published bill', fontsize=8.2, color=MUTED, va='top', linespacing=1.35)
    for index, (_, score, kind) in enumerate(systems):
        if kind in ('closed', 'trained', 'unstated'):
            right.scatter(score, 1.93, s=26, facecolor='white', edgecolor='#999999', linewidth=1.0, zorder=3)
    right.scatter(65.93, 0.62, s=74, marker='D', color=OURS, zorder=4)
    right.annotate(
        'EX 65.93 · ¥3.22\nper 1,000 questions', (65.93, 0.62), xytext=(67.4, 0.86), fontsize=8.8,
        color='#1e7a46', va='center',
        arrowprops={'arrowstyle': '-', 'color': OURS, 'linewidth': 0.9},
    )
    right.scatter(59.81, 0.18, s=58, marker='s', color=OURS_LIGHT, zorder=4)
    right.annotate(
        'R-VES 59.81 · ¥0.47\nsame statements, reward table', (59.81, 0.18), xytext=(61.5, 0.40), fontsize=8.6,
        color='#1e7a46', va='center',
        arrowprops={'arrowstyle': '-', 'color': OURS_LIGHT, 'linewidth': 0.9},
    )
    right.set_xlim(56, 82)
    right.set_ylim(0, 2.45)
    right.set_yticks([1.93, 0.62, 0.18])
    right.set_yticklabels(['no bill', '¥3.22', '¥0.47'], fontsize=8.8)
    right.set_xlabel('BIRD dev (%)', fontsize=9.3)
    right.set_title('Cost: the axis only one system can be placed on', fontsize=10.6, loc='left', pad=8)

    fig.suptitle(
        'Text2SQL, round 204: everyone publishes accuracy, and only this repository publishes a bill',
        fontsize=12.6, x=0.007, ha='left', y=0.975, color=INK,
    )
    fig.text(
        0.007, 0.012,
        'Blue: closed cloud service.   Gold: trains its own generator (out of scope by policy, drawn for scale).   '
        'Grey: licence unstated.   Green: this repository.   R-VES is the reward-validated reading of the same statements.',
        fontsize=8.2, color=MUTED,
    )
    fig.savefig(path, bbox_inches='tight', facecolor='#fbfbf8')
    plt.close(fig)


def nvbench(path):
    """Text2Viz on nvBench 2.0: F1@3 for every system the corpus compares, ours among them."""
    systems = [
        ('Step-Text2Vis (trained, SFT+DPO)', 81.50, 'trained'),
        ('GPT-4o-Step (prompted)', 60.78, 'closed'),
        ('GPT-4o (prompted, the baseline)', 58.96, 'closed'),
        ('this repository — reasoning tier', 32.23, 'ours'),
        ('this repository — chat tier', 26.28, 'ours-lite'),
    ]
    colour = {'trained': TRAINED, 'closed': CLOSED, 'ours': OURS, 'ours-lite': OURS_LIGHT}

    fig, ax = plt.subplots(figsize=(11.4, 5.4), dpi=170)
    for index, (name, score, kind) in enumerate(systems):
        ax.barh(index, score, color=colour[kind], height=0.56, zorder=2)
        ax.text(
            score - 0.9, index, f'{score:.2f}', va='center', ha='right', fontsize=9.0,
            color='white' if kind != 'ours-lite' else '#14512f', zorder=4,
        )
    ax.axvline(58.96, color=MUTED, linestyle=':', linewidth=0.9, zorder=1)
    ax.axvline(84.96, color=MUTED, linestyle='--', linewidth=0.9, zorder=1)
    ax.text(60.0, -0.52, 'corpus baseline 58.96', fontsize=8.4, color=MUTED, va='center')
    ax.text(84.2, -0.52, 'ceiling 84.96', fontsize=8.4, color=MUTED, ha='right', va='center')
    ax.set_yticks(range(len(systems)))
    ax.set_yticklabels([s[0] for s in systems], fontsize=9.3)
    ax.invert_yaxis()
    ax.set_xlim(0, 92)
    ax.set_ylim(4.75, -0.75)
    ax.set_xlabel('nvBench 2.0 dev F1@3 (%), as each system reports it', fontsize=9.3)
    ax.set_title(
        'Text2Viz, round 204: a prompted GPT-4o reads 60.78 — 28.6 points above our best tier',
        fontsize=11.6, loc='left', pad=10,
    )
    ax.grid(axis='x', color=GRID, linewidth=0.6, zorder=0)
    fig.text(
        0.007, 0.012,
        'Trained: the corpus winner, SFT + step-wise DPO.   Blue: prompted, no training — the class this repository competes in.   '
        'Green: this repository, 750 questions, the shipped rule bundle. The chat tier costs ¥2.59 a split; no competitor publishes a bill.',
        fontsize=8.1, color=MUTED,
    )
    fig.savefig(path, bbox_inches='tight', facecolor='#fbfbf8')
    plt.close(fig)





def union(path):
    """What the rewrites are worth: the pipeline's share, and the cases that were only ever arithmetic."""
    # The pipeline repairs 11 of 496 questions. The wider reading added ten more, all of them from
    # rules no product runs; drawing the same eleven in both bars is the whole finding.
    rows = [
        ('over `net > 0`\n(what the report printed until this round)', 11, 10, '21 cases  =  4.23pp'),
        ('over the three edits\nthe pipeline applies', 11, 0, '11 cases  =  2.22pp'),
    ]

    fig, ax = plt.subplots(figsize=(11.6, 4.4), dpi=170)
    fig.subplots_adjust(bottom=0.3, top=0.86)
    for index, (_label, shipped, extra, total) in enumerate(rows):
        ax.barh(index, shipped, color=OURS, height=0.44, zorder=2)
        ax.text(shipped / 2, index, str(shipped), va='center', ha='center', fontsize=10.0, color='white', zorder=4)
        if extra > 0:
            ax.barh(index, extra, left=shipped, color='#9aa0a6', height=0.44, zorder=2)
            ax.text(shipped + extra / 2, index, str(extra), va='center', ha='center', fontsize=10.0, color='white', zorder=4)
        ax.text(shipped + extra + 0.5, index, total, va='center', ha='left', fontsize=10.0, color=INK)

    # The extra block is named once, under the bar it belongs to: inside it, the words would sit on
    # top of the number that is the point.
    ax.text(16, 0.3, 'no product runs these ten', fontsize=8.6, color=MUTED, ha='center', va='top')
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=9.4, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, 27)
    ax.set_ylim(1.4, -0.55)
    ax.set_xticks([0, 5, 10, 15, 20, 25])
    ax.set_xlabel('distinct Mini-Dev questions at least one rule repairs (of 496)', fontsize=9.3)
    ax.set_title(
        'Round 204: a sign is not a verdict — ten of the twenty-one cases came from a refused rule',
        fontsize=11.4, loc='left', pad=12,
    )
    ax.grid(axis='x', color=GRID, linewidth=0.6, zorder=0)
    fig.text(
        0.007, 0.012,
        'Green: repaired by the three edits the pipeline applies (null-order 1, ground-shipped 10).   Grey: repaired by refused '
        'rules (drop-count-distinct 9, integer-division 1).   The shipped eleven are the same in both bars — `ground-case-any` '
        'and `ground-case-empty` add nothing of their own, because all of their wins sit inside `ground-shipped`\'s ten.',
        fontsize=8.1, color=MUTED,
    )
    fig.savefig(path, bbox_inches='tight', facecolor='#fbfbf8')
    plt.close(fig)


if __name__ == '__main__':
    bird_dev('/workspace/charts/r204_text2sql_two_axes.png')
    nvbench('/workspace/charts/r204_text2viz_two_axes.png')
    union('/workspace/charts/r204_union.png')
    print('wrote r204_text2sql_two_axes.png, r204_text2viz_two_axes.png and r204_union.png')
