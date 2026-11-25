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
SENT = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")


def norm_sent(s):
    return re.sub(r"[\s，。！？；：、,.!?;:()（）\"'“”‘’]", "", s or "")


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

    # Sentence-level pass: a single copied sentence across two chapters is the most common
    # real duplication, and it is invisible to the paragraph floor above (a 35-character
    # Chinese sentence never reaches the 60-character paragraph floor).
    sents = []
    for p in paras:
        for k, s in enumerate(SENT.findall(p.get("text", "")), 1):
            body = s.strip()
            n = norm_sent(body)
            if len(n) >= (12 if CJK.search(n) else 30) and len(CJK.findall(n)) + len(WORD.findall(n)) >= 3:
                sents.append({"paragraph_id": p.get("paragraph_id"), "section": p.get("section"),
                              "sentence_index": k, "sentence": body[:200], "norm": n})
    sentence_pairs = []
    for i in range(len(sents)):
        for j in range(i + 1, len(sents)):
            x, y = sents[i], sents[j]
            if x["paragraph_id"] == y["paragraph_id"]:
                continue
            if x["norm"] == y["norm"]:
                ratio, exact = 1.0, True
            elif abs(len(x["norm"]) - len(y["norm"])) > 8:
                continue
            else:
                ratio = SequenceMatcher(None, x["norm"], y["norm"]).ratio()
                exact = False
                if ratio < 0.9:
                    continue
            sentence_pairs.append({
                "a": x["paragraph_id"], "b": y["paragraph_id"],
                "a_section": x["section"], "b_section": y["section"],
                "a_sentence_index": x["sentence_index"], "b_sentence_index": y["sentence_index"],
                "sentence": x["sentence"], "matched": y["sentence"][:200],
                "ratio": round(ratio, 3), "exact": exact,
                "cross_section": x["section"] != y["section"]})
    sentence_pairs.sort(key=lambda r: (-r["ratio"], r["a"], r["b"]))
    rep["sentence_pairs"] = sentence_pairs[:20]

    flags = [f for f in rep.get("flags", []) if f.get("code") != "cross_section_repetition"]
    flagged = set()
    for pair in pairs:
        if pair["cross_section"]:
            flags.append({"code": "cross_section_repetition", "severity": "medium",
                          "paragraph_id": pair["a"], "section": pair["a_section"],
                          "message": "%s 与 %s（%s）相似 ratio=%.2f"
                                     % (pair["a"], pair["b"], pair["b_section"], pair["ratio"])})
            flagged.add(pair["a"])
    for sp in sentence_pairs[:6]:
        if sp["cross_section"] and sp["a"] not in flagged:
            flags.append({"code": "cross_section_repetition", "severity": "medium",
                          "paragraph_id": sp["a"], "section": sp["a_section"],
                          "message": "%s 第%d句与 %s（%s）第%d句%s相似 ratio=%.2f"
                                     % (sp["a"], sp["a_sentence_index"], sp["b"], sp["b_section"],
                                        sp["b_sentence_index"], "逐字" if sp["exact"] else "",
                                        sp["ratio"])})
            flagged.add(sp["a"])
    rep["flags"] = flags
    os.makedirs(a.out, exist_ok=True)
    with open(a.structure, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    print("repetition_pairs=%d sentence_pairs=%d cross_section=%d flags=%d"
          % (len(pairs), len(rep["sentence_pairs"]), sum(1 for p in pairs if p["cross_section"]), len(flags)))
    for p in pairs[:10]:
        print("  ~", p["a"], "<->", p["b"], "ratio=%.2f" % p["ratio"], "cross=%s" % p["cross_section"])
    for s in rep["sentence_pairs"][:5]:
        print("  =", s["a"], s["a_sentence_index"], "<->", s["b"], s["b_sentence_index"],
              "%.2f" % s["ratio"], "exact=%s" % s["exact"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
