#!/usr/bin/env python3
"""term_consistency.py - check a bilingual translation against a locked glossary.

Per segment it checks: locked term rendering, banned-variant drift, number survival,
Figure/Table/Eq numbering, citation keys.
Glossary TSV: source_term <TAB> target_term <TAB> code <TAB> banned_variants ("|" split).
Bilingual JSON: {"segments":[{"id","source","target","locator","section"}]}
Usage: python3 scripts/term_consistency.py --glossary work/glossary.tsv \
    --bilingual work/bilingual.json --out work/term_check.json
Exit 0 = pass, 1 = review. Stdlib only, no network.
"""
import argparse
import json
import os
import re
import sys

NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
LABEL_RE = re.compile(r"(?<![A-Za-z])(Fig(?:ure)?s?\.?|Tables?|Eq(?:uation)?s?\.?|Sections?|Sec\.|Appendix|图|表|式)\s*\(?(\d+[A-Za-z0-9.\-]*)", re.I)
CN_ORDINAL_RE = re.compile(r"第\s*(\d+)\s*[节章]")
KIND = {"fig": "fig", "figure": "fig", "figs": "fig", "figures": "fig", "table": "tab",
        "tables": "tab", "eq": "eq", "equation": "eq", "equations": "eq",
        "section": "sec", "sections": "sec", "sec": "sec", "appendix": "app",
        "图": "fig", "表": "tab", "式": "eq"}
SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
BRACKET_RE = re.compile(r"\[([0-9,\s\-–]+)\]")
AUTHOR_RE = re.compile(r"\(([A-Z][A-Za-z\-]+)[^)]{0,40}?((?:19|20)\d{2})[a-z]?\)")
CITE_RE = re.compile(r"\\cite\{([^}]+)\}")

def has_term(text, term):
    term = (term or "").strip()
    if not term:
        return False
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.I) is not None

def strip_marked(text):
    # Chinese ordinals ("第 2 节") must be stripped like "Section 2", else the same number is
    # removed on the source side but counted as newly invented on the target side.
    text = CN_ORDINAL_RE.sub(" ", text)
    text = LABEL_RE.sub(" ", AUTHOR_RE.sub(" ", BRACKET_RE.sub(" ", CITE_RE.sub(" ", text))))
    return text

def numbers(text):
    # Superscript exponents ("10⁻⁴") must compare equal to the linear form ("10-4"),
    # otherwise a faithful translation is reported as dropping a number.
    out = [m.group(0).replace(" ", "") for m in NUM_RE.finditer(strip_marked(text.translate(SUPERSCRIPT)))]
    return [t for t in out if t not in {"-", "+"}]


def panel_key(value):
    """Panel suffixes are compared case-insensitively: Figure 3A == 图 3a (same panel)."""
    return value.rstrip(".").lower()


def markers(text):
    out = set()
    for m in LABEL_RE.finditer(text):
        label = m.group(1).lower().rstrip(".")
        out.add(KIND.get(label, label) + panel_key(m.group(2)))
    for m in CN_ORDINAL_RE.finditer(text):  # "第 2 节" / "第 2 章" == Section 2
        out.add("sec" + panel_key(m.group(1)))
    return out

def cite_keys(text):
    keys = set()
    for m in BRACKET_RE.finditer(text):
        for part in re.split(r"[,，]", m.group(1)):
            part = part.strip()
            if re.fullmatch(r"\d+", part):
                keys.add("b" + part)
            elif re.fullmatch(r"\d+\s*[-–]\s*\d+", part):
                a, b = re.split(r"[-–]", part)
                for i in range(int(a), min(int(b), int(a) + 50) + 1):
                    keys.add("b%d" % i)
    for m in AUTHOR_RE.finditer(text):
        keys.add("a:%s:%s" % (m.group(1).lower(), m.group(2)))
    for m in CITE_RE.finditer(text):
        for k in m.group(1).split(","):
            if k.strip():
                keys.add("k:" + k.strip().lower())
    return keys

def cite_present(key, target, target_keys):
    if key in target_keys:
        return True
    if key.startswith("a:"):
        _, surname, year = key.split(":")
        return surname in target.lower() and year in target
    return False

def load_glossary(path):
    """Load the TSV glossary. utf-8-sig: a BOM made the first term invisible to has_term."""
    if not os.path.exists(path):
        raise SystemExit("FAIL: glossary not found: %s (write work/glossary.tsv first)" % path)
    rows, by_source, conflicts = [], {}, []
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            cells = [c.replace("\ufeff", "").strip() for c in line.rstrip("\n").split("\t")]
            if not cells or not cells[0]:
                continue
            if cells[0].lower() in {"source_term", "term", "原文术语"}:
                continue
            cells += [""] * (4 - len(cells))
            key = cells[0].lower()
            if key in by_source:
                first = by_source[key]
                if cells[1] and first["target"] and cells[1] != first["target"]:
                    conflicts.append({"term": cells[0], "kept": first["target"], "ignored": cells[1]})
                for v in cells[3].split("|"):
                    if v.strip() and v.strip() not in first["banned"]:
                        first["banned"].append(v.strip())
                continue
            row = {"source": cells[0], "target": cells[1], "code": cells[2],
                   "banned": [v.strip() for v in cells[3].split("|") if v.strip()],
                   "segments": []}
            by_source[key] = row
            rows.append(row)
    return rows, conflicts


def load_segments(path):
    """Accept {"segments":[...]}, {"segments":{id: {...}}}, a bare list, or {id: {...}}.

    A dict-shaped bilingual file used to raise AttributeError on seg.get().
    """
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SystemExit("FAIL: bilingual file is not valid JSON: %s (%s)" % (path, exc))
    if isinstance(data, dict):
        body = data.get("segments", data)
        if isinstance(body, dict):
            body = [dict(v, id=v.get("id", k)) for k, v in body.items() if isinstance(v, dict)]
        if isinstance(body, list):
            return [s for s in body if isinstance(s, dict)]
        return []
    if isinstance(data, list):
        return [s for s in data if isinstance(s, dict)]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--bilingual", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    terms, conflicts = load_glossary(a.glossary)
    if not os.path.exists(a.bilingual):
        raise SystemExit("FAIL: bilingual file not found: %s" % a.bilingual)
    segs = load_segments(a.bilingual)
    buckets = {k: [] for k in ("missing_locked", "variant_drift", "numbers_missing",
                               "numbers_added", "markers_missing", "citations_missing",
                               "citations_added", "empty_targets")}
    occurrences = hits = 0
    for seg in segs:
        sid, src, tgt = str(seg.get("id", "?")), seg.get("source") or "", seg.get("target") or ""
        if not tgt.strip():
            buckets["empty_targets"].append(sid)
            continue
        for t in terms:
            if not has_term(src, t["source"]):
                continue
            occurrences += 1
            t["segments"].append(sid)
            if has_term(tgt, t["target"]) or (t["code"] and has_term(tgt, t["code"])):
                hits += 1
            else:
                buckets["missing_locked"].append({"segment": sid, "term": t["source"], "expected": t["target"]})
            for v in t["banned"]:
                if has_term(tgt, v):
                    buckets["variant_drift"].append({"segment": sid, "term": t["source"], "found": v})
        sn, tn = numbers(src), numbers(tgt)
        buckets["numbers_missing"] += [{"segment": sid, "value": n} for n in dict.fromkeys(sn) if n not in tn]
        buckets["numbers_added"] += [{"segment": sid, "value": n} for n in dict.fromkeys(tn) if n not in sn]
        buckets["markers_missing"] += [{"segment": sid, "marker": m} for m in sorted(markers(src) - markers(tgt))]
        tk = cite_keys(tgt)
        buckets["citations_missing"] += [{"segment": sid, "cite": c} for c in sorted(cite_keys(src))
                                         if not cite_present(c, tgt, tk)]
        buckets["citations_added"] += [{"segment": sid, "cite": c} for c in sorted(tk - cite_keys(src))]
    # numbers_added = the target carries a number the source does not; the SKILL
    # requires every such case to be reverted or explained, so it is review-level.
    # citations_added stays informational because target-side author-year spellings
    # can produce false positives.
    errors = sum(len(v) for k, v in buckets.items()
                 if k not in {"citations_added"})
    warnings = []
    if not terms:
        warnings.append("glossary has no entries: term locking was not checked")
    if not segs:
        warnings.append("bilingual file has no segments: nothing was checked")
    if terms and segs and occurrences == 0:
        warnings.append("glossary terms never occur in the source segments: term locking was not exercised")
    if conflicts:
        warnings.append("%d glossary term(s) declared with conflicting targets; first target kept: %s"
                        % (len(conflicts), ", ".join(c["term"] for c in conflicts[:5])))
    verdict = "pass" if (errors == 0 and not warnings) else "review"
    report = {"segments": len(segs), "segments_translated": len(segs) - len(buckets["empty_targets"]),
              "glossary_entries": len(terms), "term_occurrences": occurrences, "locked_hits": hits,
              "locked_hit_rate": round(hits / occurrences, 4) if occurrences else None,
              "glossary_unused": [t["source"] for t in terms if not t["segments"]],
              "glossary_conflicts": conflicts, "warnings": warnings,
              "counts": {k: len(v) for k, v in buckets.items()},
              "verdict": verdict}
    report.update({k: v[:60] for k, v in buckets.items()})
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("verdict=%s locked_hit_rate=%s counts=%s"
          % (report["verdict"],
             "n/a" if report["locked_hit_rate"] is None else "%.3f" % report["locked_hit_rate"],
             json.dumps(report["counts"])))
    for w in warnings:
        print("  ~", w)
    for k in ("missing_locked", "variant_drift", "numbers_missing", "numbers_added", "markers_missing",
              "citations_missing", "empty_targets"):
        for row in report[k][:6]:
            print("  !", k, row)
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
