#!/usr/bin/env python3
"""POC-39 R6: what counts as a source for a claim that names a measurement.

R6 says a section that claims a measurement ("实测") must name where the number came
from. The audit recognised a POC id, an ADR id, a section reference, an external
paper, a probe date, a runtime trace and an appendix — but not the evidence form this
project uses most: a GitHub Actions run id. Section 49.5 cited run 41290647076 and was
reported unsourced on three consecutive pushes, so the gate was red every time and
therefore stopped being read. A check that always fails is not a check.

A run id is a source in the strongest sense: it is the artifact the number was
computed from, and it is the only identifier that survives the document. It is
accepted here narrowly — eleven digits starting with 41, which is the shape Actions
issues — so that a year, a token count, a column count or a case count cannot pass as
a citation by accident, and a run id cannot be smuggled in as part of a longer number.

The block splitting moved out of audit.py at the same time. It was the untested half
of the rule: the whitelist was visible in the source, the granularity was not, and a
whitelist bug is only observable through the granularity.
"""
import argparse
import json
import re
import sys

RUN_ID = r'(?<!\d)41\d{9}(?!\d)'

SOURCES = re.compile('|'.join([
    r'POC-\d+',         # the probe that produced the number
    r'ADR-\d+',         # the decision that fixed it
    r'§\s*\d',          # another section of the same document
    r'该论文',           # the paper a baseline is quoted from
    r'探针日期',         # the date of the probe
    r'实测\s*20\d\d-',   # the date the measurement was taken
    r'运行时',           # a runtime trace
    r'附录',             # an appendix table
    RUN_ID,             # a workflow run, which is an artifact and not a claim
]))

CLAIM = '实测'
HEADING = re.compile(r'^#{2,4} ')


def has_source(text):
    """True when a block that claims a measurement also names its source."""
    return bool(SOURCES.search(text))


def blocks(text):
    """Split a document into (heading, text) pairs at level 2-4 headings.

    The heading line belongs to the block's text, because the claim word almost
    always lives in the heading ("#### 49.5 实测：…"). Folded into the body, a rule
    that only looks at prose would report zero forever. A heading that leaves no
    body still forms a block: an empty section is a claim without evidence, not an
    absence of claim.
    """
    out, title, body = [], None, []
    for line in text.split('\n'):
        if HEADING.match(line):
            if title is not None:
                out.append((title, '\n'.join(body)))
            title, body = line.strip(), [line]
        else:
            body.append(line)
    if title is not None:
        out.append((title, '\n'.join(body)))
    return out


def unsourced_sections(text):
    """Headings whose block claims a measurement and names no source for it."""
    return [title[:80] for title, body in blocks(text)
            if CLAIM in body and not has_source(body)]


def selftest():
    mutations = []

    def expect(name, body, sourced):
        got = has_source(body)
        mutations.append({'mutation': name, 'expected': sourced, 'caught': got == sourced})

    expect('run id alone is a source', '`41290647076` 三臂读数', True)
    expect('no source at all', '臂比父臂低 3.43pp', False)
    expect('a four-digit number is not a run id', '共 4129 次调用', False)
    expect('ten digits is one short of a run id', '运行 4129064707', False)
    expect('twelve digits is one long', '运行 412906470761', False)
    expect('run ids start with 41', '运行 40123456789', False)
    expect('a run id inside a longer number', '运行 941234567890', False)
    expect('POC id still counts', '见 POC-72', True)
    expect('ADR id still counts', '见 ADR-031', True)
    expect('section reference still counts', '见 § 49.4', True)
    expect('measurement date still counts', '实测 2026-11-01 的读数', True)
    expect('paper still counts', '该论文给出 73.2%', True)

    # Granularity: a source in the previous section must not pay for this one.
    doc = '\n'.join([
        '#### 1.1 实测：有出处',
        '',
        '参见 `41290647076`。',
        '',
        '#### 1.2 实测：没有出处',
        '',
        '臂比父臂低 3.43pp。',
        '',
        '## 2 章节',
        '',
        '正文不带数字。',
    ])
    got = unsourced_sections(doc)
    mutations.append({'mutation': 'a source does not leak across headings',
                      'expected': ['#### 1.2 实测：没有出处'],
                      'caught': got == ['#### 1.2 实测：没有出处']})
    mutations.append({'mutation': 'a heading without the claim is not reported',
                      'expected': 1, 'caught': len(unsourced_sections(doc)) == 1})

    ok = all(m['caught'] for m in mutations)
    print(json.dumps({'selftest': mutations, 'ok': ok}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--document', default='')
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.document:
        print('usage: --selftest | --document 技术设计方案.md')
        return 2
    with open(args.document, encoding='utf-8') as handle:
        found = unsourced_sections(handle.read())
    print(json.dumps({'unsourced': found, 'count': len(found)}, ensure_ascii=False, indent=1))
    return 0 if not found else 1


if __name__ == '__main__':
    sys.exit(main())
