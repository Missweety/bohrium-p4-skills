#!/usr/bin/env python3
"""quote_check.py - verify that every quoted evidence fragment is verbatim in the source corpus.

Reading/translation skills must cite原文 rather than paraphrase-and-claim. This checker
normalizes whitespace and common PDF artifacts (soft hyphen, ligatures, line breaks) before
matching, and reports a resolvable line number for each quote.

Usage:
  python3 scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt --out work/quote_check.json
Evidence format: [{"claim": str, "source_path": str, "quote": str, "locator": str}]
Exit 0 only when the list is non-empty and every quote resolves.
"""
import argparse
import json
import os
import re
import sys

LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "\u00ad": "", "\u2019": "'", "\u201c": '"', "\u201d": '"'}
WS = re.compile(r"\s+")


def norm(s):
    for k, v in LIGATURES.items():
        s = s.replace(k, v)
    s = WS.sub(" ", s)
    return s.strip().lower()


def load_evidence(path):
    """Accept a bare list or {"evidence"|"quotes"|"items": [...]}. Bad JSON must not crash."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SystemExit("FAIL: evidence file is not valid JSON: %s (%s)" % (path, exc))
    if isinstance(data, dict):
        for k in ("evidence", "quotes", "items"):
            if isinstance(data.get(k), list):
                return data[k]
        return []
    return data if isinstance(data, list) else []


def segment_ids(path):
    """Segment ids from bilingual.json so quote coverage can be checked."""
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    body = data.get("segments", data) if isinstance(data, dict) else data
    if isinstance(body, dict):
        return [str(v.get("id", k)) for k, v in body.items() if isinstance(v, dict)]
    if isinstance(body, list):
        return [str(s.get("id")) for s in body if isinstance(s, dict) and s.get("id")]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bilingual", default="",
                    help="optional bilingual.json; fails the run when a segment has no quote")
    ap.add_argument("--min-len", type=int, default=12,
                    help="quotes shorter than this cannot prove verbatim text and are flagged")

    a = ap.parse_args()

    ev = load_evidence(a.evidence)
    if not os.path.exists(a.corpus):
        print("FAIL: corpus missing:", a.corpus)
        return 1
    corpus_raw = open(a.corpus, encoding="utf-8").read()
    corpus = norm(corpus_raw)

    results, bad, short = [], 0, 0
    for i, item in enumerate(ev):
        if not isinstance(item, dict):
            results.append({"index": i, "status": "bad_entry", "quote": str(item)[:120]})
            bad += 1
            continue
        q = (item.get("quote") or "").strip()
        if not q:
            results.append({"index": i, "claim": item.get("claim"), "status": "no_quote"})
            bad += 1
            continue
        probe = norm(q)
        is_short = len(probe) < a.min_len
        if is_short:
            short += 1
        idx = corpus.find(probe)
        if idx < 0:
            results.append({"index": i, "claim": item.get("claim"), "status": "not_verbatim",
                            "quote": q[:120]})
            bad += 1
            continue
        # map normalized index back approximately using raw line count on prefix
        approx_chars = int(idx * (len(corpus_raw) / max(len(corpus), 1)))
        line = corpus_raw.count("\n", 0, approx_chars) + 1
        entry = {"index": i, "claim": item.get("claim"), "status": "ok",
                 "line": line, "declared_locator": item.get("locator")}
        if is_short:
            entry["short"] = True
        results.append(entry)

    ids = segment_ids(a.bilingual)
    claims = " ".join(str(item.get("claim") or item.get("id") or "")
                      for item in ev if isinstance(item, dict))
    uncovered = [i for i in ids
                 if not re.search(r"(?<![A-Za-z0-9])" + re.escape(i) + r"(?![A-Za-z0-9])", claims)]
    notes = []
    if not ev:
        # Zero quotes used to report "pass 0/0": nothing was actually verified.
        notes.append("no quotes supplied: verbatim check did not run")
    if ids and uncovered:
        notes.append("%d/%d segments have no quote: %s"
                     % (len(uncovered), len(ids), ", ".join(uncovered[:10])))
    if short:
        notes.append("%d quotes shorter than %d chars cannot prove verbatim reuse"
                     % (short, a.min_len))

    code_bad = bad + len(uncovered) + (1 if not ev else 0) + (1 if short else 0)
    report = {"total": len(ev), "failed": bad, "results": results,
              "segments_total": len(ids), "segments_quoted": len(ids) - len(uncovered) if ids else 0,
              "segments_uncovered": uncovered[:50], "short_quotes": short, "notes": notes,
              "verdict": "pass" if code_bad == 0 else "review"}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("verdict=%s failed=%d/%d segments_quoted=%s/%s"
          % (report["verdict"], bad, len(ev), report["segments_quoted"], len(ids)))
    for n in notes:
        print("  ~", n)
    for r in results:
        if r["status"] != "ok":
            print("  !", r["status"], "|", str(r.get("claim"))[:60])
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
