#!/usr/bin/env python3
"""repetition_probe.py - cross-section repetition candidates (stdlib only).

Reads structure.json, writes back repetition_pairs + cross_section_repetition flags.
Similarity uses word tokens for Latin text and character bigrams for CJK text, so
Chinese manuscripts are covered too. Candidates still need a human/model re-read:
high similarity is not a semantic verdict.

Usage: python repetition_probe.py --structure work/structure.json --out work
"""
import argparse
import json
import os
import re
import sys
from difflib import SequenceMatcher

WORD = re.compile(r"[A-Za-z][A-Za-z\-']+")
CJK = re.compile(r"[\u4e00-\u9fff]")


def toks(text):
    words = [w.lower() for w in WORD.findall(text)]
    if len(words) >= 12 or len(CJK.findall(text)) < 60:
        return set(words)
    chars = [c for c in text if not c.isspace()]
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--structure", default="work/structure.json")
    ap.add_argument("--out", default="work")
    a = ap.parse_args()
    if not os.path.exists(a.structure):
        print("FAIL: structure.json missing:", a.structure)
        return 1
    rep = json.load(open(a.structure, encoding="utf-8"))
    paras = rep.get("paragraphs") or []
    # CJK paragraphs carry more information per character; use a lower floor for them.
    cand = [p for p in paras
            if p.get("chars", 0) >= (60 if len(CJK.findall(p.get("text", ""))) >= 40 else 120)]

    pairs = []
    for i in range(len(cand)):
        for j in range(i + 1, len(cand)):
            x, y = cand[i], cand[j]
            tx, ty = toks(x["text"]), toks(y["text"])
            jac = len(tx & ty) / len(tx | ty) if tx | ty else 0.0
            if jac < 0.55:
                continue
            ratio = SequenceMatcher(None, x["text"].lower(), y["text"].lower()).ratio()
            if ratio >= 0.6:
                pairs.append({"a": x["paragraph_id"], "b": y["paragraph_id"], "a_section": x["section"],
                              "b_section": y["section"], "jaccard": round(jac, 3), "ratio": round(ratio, 3),
                              "cross_section": x["section"] != y["section"]})

    rep["repetition_pairs"] = pairs
    flags = [f for f in rep.get("flags", []) if f.get("code") != "cross_section_repetition"]
    for pair in pairs:
        if pair["cross_section"]:
            flags.append({"code": "cross_section_repetition", "severity": "medium",
                          "paragraph_id": pair["a"], "section": pair["a_section"],
                          "message": "%s 与 %s（%s）相似 ratio=%.2f"
                                     % (pair["a"], pair["b"], pair["b_section"], pair["ratio"])})
    rep["flags"] = flags
    os.makedirs(a.out, exist_ok=True)
    with open(a.structure, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    print("repetition_pairs=%d cross_section=%d flags=%d"
          % (len(pairs), sum(1 for p in pairs if p["cross_section"]), len(flags)))
    for p in pairs[:10]:
        print("  ~", p["a"], "<->", p["b"], "ratio=%.2f" % p["ratio"], "cross=%s" % p["cross_section"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
