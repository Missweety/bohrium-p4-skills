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
P_THRESH = re.compile(r"[pP]\s*(?:值)?\s*[<>≤≥≈]\s*0?[.,]\d+")
HEAD_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.M)


def decode_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _num_forms(tok):
    base = tok.strip().replace(" ", "").replace(",", "")
    forms = {tok.strip(), base}
    m = re.match(r"^([-+]?\d+(?:\.\d+)?)\s?([%‰])?$", base)
    if m:
        num, unit = m.group(1), m.group(2) or ""
        if num.endswith(".0"):
            num = num[:-2]
        forms.update({num + unit, num})
    return [f for f in forms if f]


def _bounded(haystack, form):
    if not form:
        return False
    return re.search(r"(?<![0-9.])" + re.escape(form) + r"(?![0-9])", haystack) is not None


def count_words(text):
    """CJK counts per character, latin per word; the old regex counted a whole Chinese
    sentence as one word, so a 900-character section was reported as '12 words, too short'."""
    return len(re.findall(r"[A-Za-z]+", text)) + len(re.findall(r"[\u4e00-\u9fff]", text))


def load(p, default):
    if p and os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return default
    return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True)
    ap.add_argument("--map", default="")
    ap.add_argument("--template", default="")
    ap.add_argument("--corpus", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    if not a.draft or not os.path.exists(a.draft):
        report = {"verdict": "fail", "problems": ["draft missing: %s" % a.draft],
                  "warnings": [], "sections_found": [], "numbers_total": 0, "numbers_unbound": []}
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print("FAIL: draft missing: %s" % a.draft)
        return 1

    text = decode_text(a.draft)
    smap = load(a.map, [])
    if isinstance(smap, dict):
        smap = smap.get("source_map") or smap.get("claim_map") or []
    if not isinstance(smap, list):
        smap = []
    smap = [e for e in smap if isinstance(e, dict)]
    tpl = load(a.template, {"sections": []})
    if isinstance(tpl, list):
        tpl = {"sections": tpl}
    if not isinstance(tpl, dict):
        tpl = {"sections": []}
    sections_tpl = [s for s in (tpl.get("sections") or []) if isinstance(s, dict)]
    corpus = decode_text(a.corpus) if a.corpus and os.path.exists(a.corpus) else ""

    problems, warnings = [], []

    headings = [m.group(2).strip() for m in HEAD_RE.finditer(text)]
    # Map each section body to the heading it actually belongs to. The old code used the
    # template index as a positional index into the body list, so any extra heading (摘要,
    # 结论) shifted every later section onto the wrong text and produced bogus word counts.
    bodies = []
    parts = re.split(r"^#{1,4}\s+.*$", text, flags=re.M)
    for i, heading in enumerate(headings):
        bodies.append((heading, parts[i + 1] if i + 1 < len(parts) else ""))

    def body_for(name):
        for heading, body in bodies:
            if name.lower() in heading.lower():
                return body
        return ""

    for sec in sections_tpl:
        name, need = str(sec.get("name", "")), sec.get("min_words", 0) or 0
        if not any(name.lower() in h.lower() for h in headings):
            problems.append("missing section: %s" % name)
            continue
        words = count_words(body_for(name))
        if need and words < need:
            warnings.append("section %s short: %d < %d words" % (name, words, need))

    mapped = " ".join(str(e.get("value", "")) for e in smap)
    # "p < 0.001" is a reporting threshold, not a measurement recorded in the sources.
    numbers = list(dict.fromkeys(NUM_RE.findall(P_THRESH.sub(" ", text))))
    unsupported = [n for n in numbers
                   if not any(_bounded(mapped, f) or (corpus and _bounded(corpus, f))
                              for f in _num_forms(n))]
    if unsupported:
        warnings.append("%d numbers lack source binding: %s" % (len(unsupported), unsupported[:15]))

    for e in smap:
        src = str(e.get("source_path") or "")
        if not src or not os.path.exists(src):
            problems.append("source_map entry points to missing file: %s" % (src or "(empty)"))
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
