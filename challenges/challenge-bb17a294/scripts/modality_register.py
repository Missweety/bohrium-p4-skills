#!/usr/bin/env python3
"""modality_register.py - hedge strength, negation scope and register check for bilingual drafts.

For each source/target segment pair it verifies that modal certainty and negation scope are
preserved in both directions (en->zh and zh->en), and flags promotional or colloquial wording
that does not belong to a journal register.

Pairs are read from the same bilingual JSON used by bidir_consistency.py.
Usage: python scripts/modality_register.py --bilingual work/bilingual.json \
    --out work/modality_check.json [--direction auto]
Exit 0 = pass, 1 = review. Stdlib only, no network.
"""
import argparse
import json
import os
import re
import sys

CJK_RE = re.compile(r"[\u4e00-\u9fff]")

EN2ZH = [
    (r"\b(?:may|might|could)\b", ["可能", "或许", "也许", "有望", "或可"],
     ["导致", "证明", "证实", "一定", "必然"], "hedge"),
    (r"\b(?:suggest|suggests|suggested|indicat(?:e|es|ed))\b", ["提示", "表明", "显示", "暗示"],
     ["证明", "证实", "确证"], "weak-claim"),
    (r"\b(?:demonstrat(?:e|es|ed)|show(?:s|ed)?)\b", ["显示", "证明", "表明", "呈现", "表现"],
     ["可能", "或许", "也许"], "strong-claim"),
    (r"\b(?:associat(?:ed|ion)|correlat(?:ed|ion))\b", ["相关", "关联"],
     ["导致", "引起", "造成", "驱动"], "association"),
    (r"\bconsistent with\b", ["一致", "相符"], ["证明", "证实"], "consistency"),
    (r"\bup to\b", ["最高", "可达", "至多", "高达", "最多"], ["达到"], "upper-bound"),
    (r"\b(?:approximately|about|roughly)\b|~", ["约", "大约", "近似"], [], "approximation"),
    (r"\b(?:not all|not every)\b", ["并非所有", "不是所有", "并非全部", "不是全部"], ["都不", "全部不"], "negation"),
    (r"\bno evidence\b", ["无证据", "没有证据", "尚无证据"], ["证明不存在", "证明没有"], "negation"),
    (r"\bneither\b[^.]{0,40}\bnor\b", ["既不", "既非", "也不"], ["或者"], "negation"),
]

ZH2EN = [
    (r"可能|或许|也许|有望", ["may", "might", "could", "possibly", "likely", "suggest"],
     ["demonstrate", "prove", "confirm", "cause", "lead to", "result in"], "hedge"),
    (r"提示|表明|暗示", ["suggest", "indicate", "imply", "point to"],
     ["prove", "demonstrate", "confirm"], "weak-claim"),
    (r"证明|证实", ["demonstrate", "show", "confirm", "prove"],
     ["suggest", "may", "might", "possibly"], "strong-claim"),
    (r"相关|关联", ["associat", "correlat", "related"],
     ["cause", "caus", "lead to", "result in", "drive"], "association"),
    (r"导致|引起|造成", ["cause", "caus", "lead to", "result in", "drive"],
     ["associat", "correlat"], "causation"),
    (r"最高可达|可达|至多", ["up to", "at most"], ["reach", "achiev"], "upper-bound"),
    (r"约|大约|近似", ["approximately", "about", "roughly", "~"], [], "approximation"),
    (r"并非所有|不是所有|并非全部", ["not all", "not every"], ["none of", "all of"], "negation"),
    (r"无证据|没有证据|尚无证据", ["no evidence", "no indication"], ["prove", "demonstrate"], "negation"),
]

PROMO = ["国际领先", "填补空白", "世界首创", "国内首创", "重大突破", "颠覆性", "完美解决",
         "world-leading", "world leading", "fill the gap", "fills the gap", "first ever",
         "first-ever", "groundbreaking", "breakthrough technology", "revolutionary"]
COLLOQUIAL = ["很多", "挺", "特别棒", "大家", "搞定", "东西", "差不多就行", "一下子",
              "a lot of", "huge", "big time", "tons of"]


def sentences(text):
    # "42.3%" and "Fig. 2" must not end a sentence: splitting there shifted the sentence
    # pairs and reported a strength change that came only from the misalignment.
    guarded = re.sub(r"(?<=\d)\.(?=\d)", "\u0000", text)
    guarded = re.sub(r"\b(Fig|Figs|Table|Tab|Eq|Eqs|Ref|Refs|No|vs|cf|al|e\.g|i\.e|approx)\.",
                     lambda m: m.group(1) + "\u0001", guarded, flags=re.I)
    out = [s.replace("\u0000", ".").replace("\u0001", ".")
           for s in re.split(r"(?<=[。！？.!?;；])\s*|\n+", guarded) if s.strip()]
    return out


CJK_BANNED_NOT_MODAL = {"一定": r"^一定(?:条件|程度|范围|时间|数量|比例|规格|区间|区间内)"}


def cjk_banned(text, bad):
    """CJK banned terms are matched literally, except fixed phrases that are not modal."""
    pat = CJK_BANNED_NOT_MODAL.get(bad)
    if not pat:
        return bad in text
    for m in re.finditer(re.escape(bad), text):
        if not re.match(pat, text[m.start():]):
            return True
    return False


def check_pair(src, tgt, rules):
    flags = []
    for pattern, allowed, banned, label in rules:
        if not re.search(pattern, src, re.I):
            continue
        if not any(a.lower() in tgt.lower() if a.isascii() else a in tgt for a in allowed):
            flags.append(("strength_not_preserved", label, src[:80]))
        for bad in banned:
            hit = re.search(r"\b" + re.escape(bad) + r"\b", tgt, re.I) if bad.isascii() else cjk_banned(tgt, bad)
            if hit:
                flags.append(("strength_changed", label, "%s -> %s" % (bad, src[:60])))
    return flags


def sentence_pairs(src, tgt):
    ss, ts = sentences(src), sentences(tgt)
    return list(zip(ss, ts)) if len(ss) == len(ts) else [(src, tgt)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bilingual", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--direction", default="auto", choices=["auto", "zh2en", "en2zh"])
    a = ap.parse_args()
    if not os.path.exists(a.bilingual):
        print("FAIL: bilingual JSON missing: %s" % a.bilingual)
        return 2
    try:
        with open(a.bilingual, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print("FAIL: bilingual JSON invalid: %s" % exc)
        return 2
    segs = data.get("segments", data) if isinstance(data, dict) else data
    if not isinstance(segs, list):
        print("FAIL: bilingual JSON must be a segment list or {\"segments\": [...]}")
        return 2
    segs = [s for s in segs if isinstance(s, dict)]
    report = {"segments": len(segs), "flags": [], "promotional": [], "colloquial": [],
              "verdict": "pass", "by_type": {}}
    for seg in segs:
        sid, src, tgt = str(seg.get("id", "?")), seg.get("source") or "", seg.get("target") or ""
        if not src.strip() or not tgt.strip():
            continue
        direction = a.direction if a.direction != "auto" else ("zh2en" if CJK_RE.search(src) else "en2zh")
        for s_src, s_tgt in sentence_pairs(src, tgt):
            for kind, label, detail in check_pair(s_src, s_tgt, ZH2EN if direction == "zh2en" else EN2ZH):
                report["flags"].append({"segment": sid, "type": kind, "rule": label, "detail": detail})
        for word in PROMO:
            if word.lower() in tgt.lower():
                report["promotional"].append({"segment": sid, "word": word})
        for word in COLLOQUIAL:
            if word.lower() in tgt.lower():
                report["colloquial"].append({"segment": sid, "word": word})
    for f in report["flags"]:
        report["by_type"][f["type"]] = report["by_type"].get(f["type"], 0) + 1
    report["counts"] = {"strength_flags": len(report["flags"]),
                        "promotional": len(report["promotional"]),
                        "colloquial": len(report["colloquial"])}
    if any(report["counts"].values()):
        report["verdict"] = "review"
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("verdict=%s counts=%s" % (report["verdict"], json.dumps(report["counts"])))
    for f in report["flags"][:8]:
        print("  !", f["type"], "|", f["rule"], "|", f["detail"])
    for p in report["promotional"][:5]:
        print("  ! promotional:", p["word"], "@", p["segment"])
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
