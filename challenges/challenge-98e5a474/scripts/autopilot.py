#!/usr/bin/env python3
"""Autopilot baseline for budget-constrained runs.

Builds a rule-extracted schematic plan from the case and its text materials, then
runs the real deliverer so a case always leaves an inspectable SVG, evidence map
and honest result.json. It never invents scientific relations: every label and
arrow is traced to a material line, and the output is marked partial for review.

Usage:
  python scripts/autopilot.py --case /input/case.json --out /app/output
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

MAX_ENTITIES = 6
WRAP = 12
FILLS = ['#dbeafe', '#dcfce7', '#fef3c7', '#fae8ff', '#e0f2fe', '#fee2e2']
STROKES = ['#1e40af', '#15803d', '#b45309', '#a21caf', '#0369a1', '#b91c1c']
BULLET = re.compile(r'^(?:[-*+\u2022]|\d+[.)\u3001]|\(\d+\))\s*(.{2,60})$')
RELATION = re.compile(
    r'([\u4e00-\u9fa5A-Za-z0-9/_\-]{1,16})\s*'
    r'(?:\u2192|->|\u2014>|\u6fc0\u6d3b|\u4fc3\u8fdb|\u6291\u5236|\u5305\u542b|'
    r'\u4ea7\u751f|\u8f6c\u5316\u4e3a|\u7ed3\u5408|\u964d\u89e3|\u6c27\u5316|'
    r'\u8fd8\u539f|\u8c03\u63a7|\u8bf1\u5bfc|\u5206\u6ccc|\u8868\u8fbe|\u8f6c\u8fd0)\s*'
    r'([\u4e00-\u9fa5A-Za-z0-9/_\-]{1,16})')
CHART_HINT = re.compile(
    r'bar chart|line chart|scatter|histogram|box ?plot|violin|\u67f1\u72b6\u56fe|'
    r'\u6298\u7ebf\u56fe|\u6563\u70b9\u56fe|\u76f4\u65b9\u56fe|\u7bb1\u7ebf\u56fe', re.I)
EDIT_HINT = re.compile(
    r'\u7f16\u8f91|\u4fee\u6539|\u66f4\u6b63|\u6539\u6210|edit|modify|correct|update the', re.I)


def wrap(text, width=WRAP, max_lines=3):
    text = ' '.join(str(text).split())
    if not text:
        return ['']
    lines = [text[i:i + width] for i in range(0, len(text), width)][:max_lines]
    if len(text) > width * max_lines:
        lines[-1] = lines[-1][:width - 1] + '\u2026'
    return lines


def read_materials(case_path):
    """Return [(label, lines)] for task.md and small text materials next to the case."""
    here = Path(case_path).parent
    paths = []
    for d in (here, Path('/input')):
        if not d.is_dir():
            continue
        for pat in ('task.md', '*.md', '*.txt'):
            paths.extend(sorted(d.glob(pat)))
    out, seen = [], set()
    for p in paths:
        try:
            rp = p.resolve()
        except OSError:
            continue
        if rp in seen or not rp.is_file():
            continue
        seen.add(rp)
        try:
            text = p.read_text(encoding='utf-8', errors='replace')[:20000]
        except OSError:
            continue
        out.append((p.name, text.splitlines()))
        if len(out) >= 4:
            break
    return out


def entity_candidates(materials, case):
    found = []
    for key in ('entities', 'nodes', 'labels', 'steps', 'items', 'terms'):
        value = case.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    found.append((item.strip()[:60], 'case.json#' + key))
                elif isinstance(item, dict):
                    for k in ('name', 'label', 'text', 'term'):
                        if isinstance(item.get(k), str) and item[k].strip():
                            found.append((item[k].strip()[:60], 'case.json#' + key))
                            break
    for label, lines in materials:
        for i, line in enumerate(lines, 1):
            m = BULLET.match(line.strip())
            if m and not m.group(1).lower().startswith(('http', 'see ')):
                found.append((m.group(1).strip(' \u3002.;\uff1b'), '%s#L%d' % (label, i)))
                for rel in RELATION.finditer(line):
                    for side in (rel.group(1).strip(), rel.group(2).strip()):
                        if 1 < len(side) <= 16:
                            found.append((side, '%s#L%d' % (label, i)))
    return found


def relations_from(materials):
    found = []
    for label, lines in materials:
        for i, line in enumerate(lines, 1):
            for m in RELATION.finditer(line):
                found.append((m.group(1), m.group(2), '%s#L%d' % (label, i)))
    return found


def csv_header(case_path):
    for p in sorted(Path(case_path).parent.glob('*.csv'))[:1]:
        try:
            with p.open(encoding='utf-8', errors='replace', newline='') as fh:
                row = next(csv.reader(fh))
        except (OSError, StopIteration, csv.Error):
            continue
        cells = [c.strip() for c in row if c.strip()][:MAX_ENTITIES]
        if cells:
            return cells, p.name
    return [], None


def build_plan(case_path, case, materials):
    case_id = case.get('case_id') or case.get('id') or 'case'
    ents, seen = [], set()
    for name, src in entity_candidates(materials, case):
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        ents.append((name, src))
    rels = [r for r in relations_from(materials)
            if r[0].lower() in seen or r[1].lower() in seen]
    endpoints = {r[0] for r in rels} | {r[1] for r in rels}
    if endpoints:
        named = [(n, s) for n, s in ents if n in endpoints]
        other = [(n, s) for n, s in ents
                 if n not in endpoints and len(n) <= 12 and not RELATION.search(n)]
        ents = named + other
    if len(ents) < 2:
        cells, cname = csv_header(case_path)
        for c in cells:
            if c.lower() not in seen:
                seen.add(c.lower())
                ents.append((c, cname + '#header'))
    ents = ents[:MAX_ENTITIES]
    names = [e[0] for e in ents]
    rels = [r for r in rels if r[0] in names and r[1] in names][:5]
    title = case.get('title') or case.get('task') or case.get('description') or ''
    if not isinstance(title, str) or not title.strip():
        for label, lines in materials:
            head = next((ln.lstrip('# ').strip() for ln in lines if ln.startswith('#')), '')
            if head:
                title = head
                break
    title = (title or case_id).strip().split('\n')[0]
    elements, emap = [], []
    elements.append({'id': 'title', 'tag': 'text', 'text': str(title)[:50],
                     'attrs': {'x': 600, 'y': 70, 'text-anchor': 'middle',
                               'font-size': 28, 'font-weight': 'bold'}})
    emap.append({'element': 'title', 'source': 'case.json#title'})
    positions = {}
    if rels:
        depth = {n: 0 for n in [e[0] for e in ents]}
        for _ in range(len(ents)):
            moved = False
            for s, d, _loc in rels:
                nd = depth[s] + 1
                if nd > depth.get(d, 0) and nd <= 3:
                    depth[d] = nd
                    moved = True
            if not moved:
                break
        columns = {}
        for n, _src in ents:
            columns.setdefault(min(depth.get(n, 0), 3), []).append(n)
        for level, nodes in columns.items():
            x = 150 + level * 300
            rows = len(nodes)
            step = 460 // max(1, rows - 1)
            for i, n in enumerate(nodes):
                positions[n] = (x, 170 + i * step)
    for i, (name, src) in enumerate(ents):
        if name not in positions:
            col, row = i % 3, i // 3
            positions[name] = (300 + col * 300, 220 + row * 180)
    for i, (name, src) in enumerate(ents):
        x, y = positions[name]
        elements.append({'id': 'entity-%d' % (i + 1), 'tag': 'rect',
                         'attrs': {'x': x - 130, 'y': y - 45, 'width': 260, 'height': 90,
                                   'rx': 12, 'fill': FILLS[i % len(FILLS)],
                                   'stroke': STROKES[i % len(STROKES)], 'stroke-width': 2}})
        elements.append({'id': 'label-%d' % (i + 1), 'tag': 'text', 'lines': [
            {'text': ln, 'attrs': {'x': x, 'y': y - 12 + j * 22,
                                   'text-anchor': 'middle', 'font-size': 18}}
            for j, ln in enumerate(wrap(name))],
            'attrs': {'x': x, 'y': y, 'text-anchor': 'middle', 'fill': '#172554'}})
        emap.append({'element': 'entity-%d' % (i + 1), 'source': src,
                     'claim': 'label from material line'})
        emap.append({'element': 'label-%d' % (i + 1), 'source': src})
    for j, (src, dst, loc) in enumerate(rels):
        x1, y1 = positions[src]
        x2, y2 = positions[dst]
        sx = x1 + 130 if x2 > x1 else x1 - 130
        tx = x2 - 130 if x2 > x1 else x2 + 130
        elements.append({'id': 'relation-%d' % (j + 1), 'tag': 'line', 'layer': 'relations',
                         'arrow': 'arrow',
                         'attrs': {'x1': sx, 'y1': y1, 'x2': tx, 'y2': y2,
                                   'stroke': '#334155', 'stroke-width': 3}})
        emap.append({'element': 'relation-%d' % (j + 1), 'source': loc,
                     'claim': '%s to %s as written in the material' % (src, dst)})
    return {
        'mode': 'create', 'canvas': [1200, 700], 'title': str(title)[:60],
        'formats': ['png', 'pdf'], 'dpi': 300,
        'caption': ('Autopilot baseline for %s: labels and arrows were extracted from the '
                    'supplied text by rule, are not yet domain-checked, and do not state a '
                    'conclusion.' % case_id),
        'elements': elements, 'element_map': emap, 'auto': True,
        'uncertainty': (['Autopilot found no entity or relation in the text materials; the '
                         'figure contains the task title only.'] if len(ents) < 2 else []) +
                       ['Autopilot baseline: entity identity, grouping, direction and '
                        'hierarchy require human confirmation against the sources.'],
    }


def blocked(case_id, out, reason, uncertainty):
    out.mkdir(parents=True, exist_ok=True)
    payload = {'case_id': case_id, 'status': 'blocked', 'limits': reason,
               'uncertainty': uncertainty, 'autopilot': True}
    (out / 'result.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'blocked', 'limits': reason}, ensure_ascii=False))
    return 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    case_path = Path(args.case)
    out = Path(args.out)
    try:
        case = json.loads(case_path.read_text(encoding='utf-8'))
    except Exception as exc:
        return blocked(None, out, 'case.json unreadable: %s' % exc,
                       ['Autopilot could not read the case.'])
    case_id = case.get('case_id') or case.get('id')
    materials = read_materials(case_path)
    blob = '\n'.join([case.get('task', '') if isinstance(case.get('task'), str) else '']
                     + [t for _, lines in materials for t in lines])
    if CHART_HINT.search(blob):
        return blocked(case_id, out,
                       'Autopilot covers schematics only; this task asks for a data chart, '
                       'which needs the real table and a plotting step.',
                       ['No chart was drawn; do not treat the source data as absent.'])
    svgs = sorted(Path(case_path).parent.glob('*.svg'))
    if Path('/input').is_dir():
        svgs += sorted(Path('/input').glob('*.svg'))
    if svgs and EDIT_HINT.search(blob):
        return blocked(case_id, out,
                       'Autopilot does not guess source-figure edits; author explicit edit '
                       'operations against %s.' % svgs[0].name,
                       ['Existing source figure left untouched.'])
    plan = build_plan(case_path, case, materials)
    plan_path = out / '_autopilot_plan.json'
    out.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    cmd = [sys.executable, str(Path(__file__).with_name('deliver.py')),
           '--case', str(case_path), '--plan', str(plan_path), '--out', str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


if __name__ == '__main__':
    raise SystemExit(main())
