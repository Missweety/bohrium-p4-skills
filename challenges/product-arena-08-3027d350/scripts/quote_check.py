#!/usr/bin/env python3
"""quote_check.py - verify that every quoted evidence fragment is verbatim in the source corpus.

Reading/parsing skills must cite the original text rather than paraphrase-and-claim. This checker
normalizes whitespace and common PDF artifacts (soft hyphen, ligatures, line breaks) before
matching, and reports a resolvable line number for each quote.

Honesty rules:
  - an empty evidence list is NOT a pass (nothing was verified);
  - a quote shorter than --min-len cannot prove verbatim reuse, so it is reported as `short_quote`
    and forces verdict=review instead of silently passing on a substring hit.

Usage:
  python3 scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt --out work/quote_check.json
Evidence format: [{"claim": str, "source_path": str, "quote": str, "locator": str}]
Exit 0 only when every quote resolves and the list is non-empty.
"""
import argparse
import json
import os
import re
import sys

LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "\u00ad": "", "\u2019": "'",
             "\u201c": '"', "\u201d": '"'}
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
                    help="quotes shorter than this are reported as short_quote (cannot prove verbatim reuse)")
    a = ap.parse_args()

    try:
        with open(a.evidence, encoding="utf-8") as fh:
            ev = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print("FAIL: evidence file is not valid JSON: %s" % exc)
        return 2
    if isinstance(ev, dict):
        ev = ev.get("evidence", ev.get("quotes", ev.get("items", [])))
    if not isinstance(ev, list):
        print("FAIL: evidence must be a list of {claim, quote, ...} objects")
        return 2
    if not os.path.exists(a.corpus):
        print("FAIL: corpus missing:", a.corpus)
        return 2
    corpus_raw = open(a.corpus, encoding="utf-8").read()
    corpus = norm(corpus_raw)
    line_set = {norm(l) for l in corpus_raw.split("\n") if l.strip()}

    results, bad, short = [], 0, 0
    for i, item in enumerate(ev):
        if not isinstance(item, dict):
            results.append({"index": i, "status": "bad_entry"})
            bad += 1
            continue
        q = (item.get("quote") or "").strip()
        if not q:
            results.append({"index": i, "claim": item.get("claim"), "status": "no_quote"})
            bad += 1
            continue
        probe = norm(q)
        if len(probe) < a.min_len:
            # A short fragment can still be truthful if it equals a whole source line
            # (e.g. a section heading); only then accept it, and say so.
            if probe in line_set:
                results.append({"index": i, "claim": item.get("claim"), "status": "ok",
                                "mode": "whole_line", "quote": q[:120], "length": len(probe)})
                continue
            results.append({"index": i, "claim": item.get("claim"), "status": "short_quote",
                            "quote": q[:120], "length": len(probe)})
            bad += 1
            short += 1
            continue
        idx = corpus.find(probe)
        if idx < 0:
            results.append({"index": i, "claim": item.get("claim"), "status": "not_verbatim",
                            "quote": q[:120]})
            bad += 1
            continue
        approx_chars = int(idx * (len(corpus_raw) / max(len(corpus), 1)))
        line = corpus_raw.count("\n", 0, approx_chars) + 1
        results.append({"index": i, "claim": item.get("claim"), "status": "ok",
                        "line": line, "declared_locator": item.get("locator")})

    if not ev:
        verdict = "review"
        print("verdict=review total=0 -> no quotes supplied; nothing was verified")
    else:
        verdict = "pass" if bad == 0 else "review"
        print("verdict=%s failed=%d/%d short_quotes=%d" % (verdict, bad, len(ev), short))
    report = {"total": len(ev), "failed": bad, "short_quotes": short, "min_len": a.min_len,
              "results": results, "verdict": verdict}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    for r in results:
        if r["status"] != "ok":
            print("  !", r["status"], "|", str(r.get("claim"))[:60])
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
