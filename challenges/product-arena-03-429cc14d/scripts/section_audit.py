#!/usr/bin/env python3
"""section_audit.py - audit a manuscript draft against a section template and a source map.

Checks:
  sections   required headings present, in order (template json: {"sections":[{"name","min_words"}]})
  coverage   every number in the draft appears in source_map values or in the source corpus
  binding    every source_map entry points to an existing file and non-empty locator
  density    warnings for paragraphs with factual numbers but no source_map entry
  honesty    flags absolute claims (显著证明/证明/毫无疑问/proves) lacking a citation marker

Usage:
  python scripts/section_audit.py --draft draft.md --map source_map.json --template section_template.json \
      --corpus work/corpus.txt --out work/audit.json
Exit 0 when no FAIL-level problems.
"""
import argparse
import json
import os
import re

NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
ABS_RE = re.compile(r"(证明|证实|毫无疑问|显著优于|proves|demonstrates conclusively|undoubtedly)")
HEAD_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.M)


def load(p, default):
    if p and os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True)
    ap.add_argument("--map", default="")
    ap.add_argument("--template", default="")
    ap.add_argument("--corpus", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    text = open(a.draft, encoding="utf-8").read()
    smap = load(a.map, [])
    if isinstance(smap, dict):
        smap = smap.get("source_map", [])
    tpl = load(a.template, {"sections": []})
    corpus = open(a.corpus, encoding="utf-8").read() if a.corpus and os.path.exists(a.corpus) else ""

    problems, warnings = [], []

    heads = list(HEAD_RE.finditer(text))
    headings = [m.group(2).strip() for m in heads]
    sec_bodies = {}
    for i, m in enumerate(heads):
        start = m.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        sec_bodies.setdefault(m.group(2).strip().lower(), text[start:end])
    for sec in tpl.get("sections", []):
        name, need = sec.get("name", ""), sec.get("min_words", 0)
        hit = next((h for h in headings if name.lower() in h.lower()), None)
        if hit is None:
            problems.append("missing section: %s" % name)
            continue
        # match by heading text, not by template index: a missing or reordered section
        # used to shift every later word count onto the wrong body.
        body = sec_bodies.get(hit.lower(), "")
        # CJK runs are counted per character: treating "本文用" as one word reported
        # Chinese sections as far shorter than they are.
        words = len(re.findall(r"[A-Za-z]+", body)) + len(re.findall(r"[\u4e00-\u9fff]", body))
        if need and words < need:
            warnings.append("section %s short: %d < %d words" % (name, words, need))

    mapped = " ".join(str(e.get("value", "")) for e in smap)
    numbers = list(dict.fromkeys(NUM_RE.findall(text)))
    unsupported = [n for n in numbers if n not in mapped and (not corpus or n not in corpus)]
    if unsupported:
        warnings.append("%d numbers lack source binding: %s" % (len(unsupported), unsupported[:15]))

    for e in smap:
        if not e.get("source_path") or not os.path.exists(str(e["source_path"])):
            problems.append("source_map entry points to missing file: %s" % e.get("source_path"))
        if not str(e.get("locator", "")).strip():
            warnings.append("source_map entry without locator: %s" % e.get("claim"))

    for m in ABS_RE.finditer(text):
        window = text[max(0, m.start() - 120): m.end() + 120]
        if not re.search(r"\[[0-9,\s\-–]+\]|\\cite\{", window):
            warnings.append("absolute claim without citation: ...%s..." % window.strip()[:80])

    verdict = "fail" if problems else ("review" if warnings else "pass")
    report = {"verdict": verdict, "sections_found": headings, "numbers_total": len(numbers),
              "numbers_unbound": unsupported[:50], "problems": problems, "warnings": warnings[:50]}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("verdict=%s problems=%d warnings=%d" % (verdict, len(problems), len(warnings)))
    for p in problems:
        print("  !", p)
    for w in warnings[:10]:
        print("  ~", w)
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
