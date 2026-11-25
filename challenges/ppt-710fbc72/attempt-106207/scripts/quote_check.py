#!/usr/bin/env python3
"""quote_check.py - verify that every quoted evidence fragment is verbatim in the source corpus.

Reading/translation skills must cite原文 rather than paraphrase-and-claim. This checker
normalizes whitespace and common PDF artifacts (soft hyphen, ligatures, line breaks) before
matching, and reports a resolvable line number for each quote.

Usage:
  python3 scripts/quote_check.py --evidence work/evidence.json --corpus work/corpus.txt --out work/quote_check.json
Evidence format: [{"claim": str, "source_path": str, "quote": str, "locator": str}]
Exit 0 when every quote resolves (or evidence list is empty).
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-len", type=int, default=12,
                    help="quotes shorter than this are checked only for presence of first 12 chars")
    a = ap.parse_args()

    with open(a.evidence, encoding="utf-8") as fh:
        ev = json.load(fh)
    if isinstance(ev, dict):
        ev = ev.get("evidence", [])
    if not os.path.exists(a.corpus):
        print("FAIL: corpus missing:", a.corpus)
        return 1
    corpus_raw = open(a.corpus, encoding="utf-8").read()
    corpus = norm(corpus_raw)

    results, bad = [], 0
    for i, item in enumerate(ev):
        q = (item.get("quote") or "").strip()
        if not q:
            results.append({"index": i, "claim": item.get("claim"), "status": "no_quote"})
            bad += 1
            continue
        probe = norm(q)
        if len(probe) < a.min_len:
            probe = probe[:a.min_len]
        idx = corpus.find(probe)
        if idx < 0:
            results.append({"index": i, "claim": item.get("claim"), "status": "not_verbatim",
                            "quote": q[:120]})
            bad += 1
            continue
        # map normalized index back approximately using raw line count on prefix
        approx_chars = int(idx * (len(corpus_raw) / max(len(corpus), 1)))
        line = corpus_raw.count("\n", 0, approx_chars) + 1
        results.append({"index": i, "claim": item.get("claim"), "status": "ok",
                        "line": line, "declared_locator": item.get("locator")})

    report = {"total": len(ev), "failed": bad, "results": results,
              "verdict": "pass" if bad == 0 else "review"}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("verdict=%s failed=%d/%d" % (report["verdict"], bad, len(ev)))
    for r in results:
        if r["status"] != "ok":
            print("  !", r["status"], "|", str(r.get("claim"))[:60])
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
