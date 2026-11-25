#!/usr/bin/env python3
"""stat_claim_checker.py - advisory audit for a results & discussion chapter draft.

Checks (stdlib, offline): significance needs p value + n; mean/± needs an error definition;
causal wording needs intervention evidence; figure/table first-citation order; results vs
discussion separation; literature claims need citations; limits need specifics; numbers must
occur in the corpus or the claim map.
Usage: python scripts/stat_claim_checker.py --draft work/results_discussion.md \
           --corpus work/corpus.txt --map work/claim_map.json --out work/stat_check.json
"""
import argparse
import json
import os
import re

NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
P_THRESH = re.compile(r"[pP]\s*(?:值)?\s*[<>≤≥≈]\s*0?[.,]\d+")


def _num_forms(tok):
    """Whitespace/percent/thousand-separator variants of one numeric token."""
    forms = {tok, tok.replace(" ", ""), re.sub(r"[%‰]$", "", tok).strip(),
             re.sub(r"(?<=\d),(?=\d{3}\b)", "", tok)}
    return [f for f in forms if f]


def _bounded(haystack, form):
    """Substring match that will not accept 12 inside 112.4 or 9 inside 0.9."""
    if not form:
        return False
    return re.search(r"(?<![0-9.])" + re.escape(form) + r"(?![0-9])", haystack) is not None


def _covered(tok, corpus, mapped):
    return any(_bounded(corpus, f) or _bounded(mapped, f) for f in _num_forms(tok))


SIG_RE = re.compile(r"显著|significan|统计学意义", re.I)
PVAL_RE = re.compile(r"[pP]\s*值?\s*[<=>≈]\s*0?[.,]\d+|\bns\b", re.I)
CAUSAL_RE = re.compile(r"导致|引起|致使|造成|caus|due to|leads? to|results? in|driv", re.I)
DISP_RE = re.compile(r"均值|平均数|\bmean\b|±", re.I)
N_RE = re.compile(r"\bn\s*=\s*\d+", re.I)
ERR_RE = re.compile(r"\bSD\b|\bSEM\b|标准差|标准误|\bCI\b|置信区间|误差棒|error bar", re.I)
INTERV = ["随机", "干预", "处理组", "对照组", "敲低", "敲除", "过表达", "抑制剂",
          "knock", "treated", "ablat", "intervention", "randomi"]
FIG_RE = re.compile(r"(?:图|Fig(?:ure)?\.?)\s*(\d+)")
TAB_RE = re.compile(r"(?:表|Table)\s*(\d+)")
CITE_RE = re.compile(r"\[[0-9,\s\-–]+\]|\\cite\{[^}]+\}|\([A-Z][A-Za-z\-]+[^)]{0,40}?(?:19|20)\d{2}[a-z]?\)")
LIT_RE = re.compile(r"文献|既往|已有研究|先前研究|previous|reported|earlier stud", re.I)
SPECIFIC = ["样本量", "单中心", "横断面", "回顾性", "测量", "统计", "体外", "动物模型",
            "随访", "选择偏倚", "混杂", "缺少", "未纳入", "无法区分", "cross-sectional",
            "sample size", "single-center", "measurement"]

def load(path, default):
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def read(path):
    if not path or not os.path.exists(path):
        return ""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")

def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True)
    ap.add_argument("--out", required=True)
    for opt in ("--corpus", "--map"):
        ap.add_argument(opt, default="")
    ap.add_argument("--strict", action="store_true", help="exit 1 on review-level warnings too")
    a = ap.parse_args()
    draft, corpus = read(a.draft), read(a.corpus)
    rep = {"draft": a.draft, "verdict": "pass", "problems": [], "warnings": [],
           "significance": [], "dispersion": [], "causal": [], "figures": {}, "sectioning": {},
           "literature": [], "limitations": {}, "unsourced_numbers": []}
    if not draft.strip():
        rep["verdict"] = "fail"
        rep["problems"].append("draft missing or empty: %s" % a.draft)
        dump(rep, a.out)
        print("FAIL: draft missing or empty")
        return 1
    blocks = re.split(r"^#{1,4}\s*(.+)$", draft, flags=re.M)
    sections = [(blocks[i].strip(), blocks[i + 1]) for i in range(1, len(blocks) - 1, 2)]
    if not sections: sections = [("", draft)]
    results_txt = "".join(b for n, b in sections if re.search(r"结果|results", n, re.I))
    disc_txt = "".join(b for n, b in sections if re.search(r"讨论|discussion", n, re.I))
    lim_txt = "".join(b for n, b in sections if re.search(r"局限|不足|limitation", n, re.I))
    rep["sectioning"] = {"sections": [n for n, _ in sections], "has_results": bool(results_txt),
                         "has_discussion": bool(disc_txt)}

    for para in re.split(r"\n{2,}", draft):
        for s in [x.strip() for x in re.split(r"[。;；!?]", para) if x.strip()]:
            if SIG_RE.search(s):
                has_p, has_n = bool(PVAL_RE.search(s) or PVAL_RE.search(para)), bool(N_RE.search(s))
                rep["significance"].append({"sentence": s[:100], "p_value": has_p, "n": has_n})
                if not has_p:
                    rep["warnings"].append("significance claim without p value: %s" % s[:70])
                elif not has_n:
                    rep["warnings"].append("significance claim without n: %s" % s[:70])
            if DISP_RE.search(s) and NUM_RE.search(s):
                ok = bool(ERR_RE.search(s) or ERR_RE.search(para))
                rep["dispersion"].append({"sentence": s[:100], "error_defined": ok})
                if not ok:
                    rep["warnings"].append("mean/± without SD/SEM/CI label: %s" % s[:70])
            if CAUSAL_RE.search(s):
                ok = any(k.lower() in (s + para).lower() for k in INTERV)
                rep["causal"].append({"sentence": s[:100], "intervention_evidence": ok})
                if not ok:
                    rep["warnings"].append("causal wording without intervention evidence: %s" % s[:70])
            if LIT_RE.search(s) and not CITE_RE.search(s):
                rep["literature"].append(s[:100])
                rep["warnings"].append("literature claim without citation: %s" % s[:70])
            if results_txt and s in results_txt and re.search(r"推测|可能是因为|提示可能|we speculate|suggest that", s, re.I):
                rep["warnings"].append("interpretation inside results: %s" % s[:70])

    for label, rgx in (("figure", FIG_RE), ("table", TAB_RE)):
        seen = list(dict.fromkeys(int(m.group(1)) for m in rgx.finditer(draft)))
        not_in_corpus = [n for n in seen if corpus and not _bounded(corpus, str(n))]
        rep["figures"][label] = {"first_citation_order": seen, "cited": seen,
                                 "not_in_material": not_in_corpus}
        if seen and seen != list(range(1, len(seen) + 1)):
            rep["warnings"].append("%s first-citation order not sequential: %s" % (label, seen))
        if not_in_corpus:
            rep["warnings"].append("%ss cited but absent from material: %s" % (label, not_in_corpus))

    if results_txt and disc_txt:
        fresh = [n for n in set(NUM_RE.findall(disc_txt))
                 if n not in results_txt and not _covered(n, corpus, "")]
        fresh = sorted(fresh)
        rep["sectioning"]["numbers_only_in_discussion"] = fresh[:20]
        if fresh:
            rep["warnings"].append("numbers appear first in discussion: %s" % fresh[:10])

    lim = rep["limitations"]
    lim["found"], lim["specific"] = bool(lim_txt), any(k in lim_txt for k in SPECIFIC)
    if not lim["found"]:
        rep["warnings"].append("no limitation paragraph found")
    elif not lim["specific"]:
        rep["warnings"].append("limitation paragraph looks generic (no method/sample/measure/stat axis)")

    smap = load(a.map, None)
    if smap is None:
        if a.map and os.path.exists(a.map):
            rep["problems"].append("claim map unreadable (invalid JSON): %s" % a.map)
        smap = []
    if isinstance(smap, dict):
        smap = smap.get("claim_map") or smap.get("source_map") or []
    if not isinstance(smap, list):
        rep["problems"].append("claim map is not a list of entries: %s" % a.map)
        smap = []
    smap = [e for e in smap if isinstance(e, dict)]
    mapped = " ".join(str(e.get("value", "")) for e in smap)
    # section numbers in headings ("3.1") are not measurements; drop heading lines first
    numeric_draft = re.sub(r"^#{1,6}\s.*$", "", draft, flags=re.M)
    # "p < 0.001" is a reporting threshold, not a measurement; the corpus stores the exact
    # p (0.0001), so counting 0.001 as untraceable made --strict unpassable by design.
    numeric_draft = P_THRESH.sub("p-threshold", numeric_draft)
    unsourced = [n for n in dict.fromkeys(NUM_RE.findall(numeric_draft))
                 if not _covered(n, corpus, mapped)]
    rep["unsourced_numbers"] = unsourced[:60]
    if unsourced:
        rep["warnings"].append("%d numbers not traceable to corpus or map" % len(unsourced))
    def resolve(src):
        """Resolve a relative source path against the map dir, cwd, corpus dir and /input."""
        cands = [src]
        if src and not os.path.isabs(src):
            bases = [os.path.dirname(os.path.abspath(a.map or ".")), os.getcwd(),
                     os.path.dirname(os.path.abspath(a.corpus or ".")), "/input"]
            cands += [os.path.join(b, src) for b in bases]
        return next((c for c in cands if c and os.path.exists(c)), "")

    for e in smap:
        src = str(e.get("source_path", ""))
        if not src:
            rep["problems"].append("map entry without source_path: %s" % e.get("claim"))
        elif not resolve(src):
            rep["problems"].append("map entry points to missing file: %s" % src)
        if not str(e.get("locator", "")).strip():
            rep["warnings"].append("map entry without locator: %s" % e.get("claim"))

    # every figure/table visible in the material should be cited at least once in Results
    for label, rgx, key in (("figure", FIG_RE, "figure"), ("table", TAB_RE, "table")):
        in_src = sorted({int(m.group(1)) for m in rgx.finditer(corpus)}) if corpus else []
        cited = rep["figures"].get(key, {}).get("cited", [])
        missing = [n for n in in_src if n not in cited]
        if missing:
            rep["warnings"].append("%ss present in material but not cited: %s" % (label, missing))
        rep["figures"].setdefault(key, {})["present_in_material"] = in_src
        rep["figures"][key]["not_cited"] = missing

    rep["verdict"] = ("fail" if rep["problems"] else ("review" if rep["warnings"] else "pass"))
    rep["summary"] = {"sig_claims": len(rep["significance"]), "causal_claims": len(rep["causal"]), "uncited_literature": len(rep["literature"])}
    dump(rep, a.out)
    print("verdict=%s problems=%d warnings=%d sig=%d causal=%d" % (
        rep["verdict"], len(rep["problems"]), len(rep["warnings"]),
        len(rep["significance"]), len(rep["causal"])))
    [print("  !", p) for p in rep["problems"]]
    [print("  ~", w) for w in rep["warnings"][:12]]
    if a.strict:
        return 0 if rep["verdict"] == "pass" else 1
    return 0 if rep["verdict"] != "fail" else 1

if __name__ == "__main__":
    raise SystemExit(main())
