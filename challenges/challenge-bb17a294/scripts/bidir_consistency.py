#!/usr/bin/env python3
"""bidir_consistency.py - zh<->en fidelity check for bilingual academic drafts.
Per segment: locked terms in the actual direction, banned variants, numbers (万/亿 vs million/
billion), units, Figure/Table/Equation numbers, citations, empty/duplicate ids, script leakage.
Glossary: zh_term, en_term, code, banned_zh, banned_en ("|" splits; "#" comments).
Usage: python scripts/bidir_consistency.py --glossary work/glossary.tsv \
    --bilingual work/bilingual.json --out work/fidelity_check.json [--direction auto]
Exit 0 = pass, 1 = review. Stdlib only, no network.
"""
import argparse, json, os, re, sys

NUM_RE = re.compile(r"(?<![A-Za-z0-9_])([-+]?\d+(?:[.,]\d+)*)\s*(万|亿|thousand|million|billion|%)?", re.I)
SCALE = {"万": 1e4, "亿": 1e8, "thousand": 1e3, "million": 1e6, "billion": 1e9}
UNIT_RE = re.compile(r"(?<![A-Za-z])(mg|µg|μg|ng|kg|mmol|µmol|μmol|mol|mL|µL|μL|kDa|mV|nm|µm|μm|mm"
                     r"|cm|km|Pa|kPa|MPa|°C|℃|rpm|kHz|MHz|Hz|min|Å)(?![A-Za-z])")
LABEL_RE = re.compile(r"(Fig(?:ure)?s?\.?|Tables?|Eq(?:uation)?s?\.?|Sections?|Sec\.|Appendix"
                      r"|图|表|式)\s*\(?([0-9]+[A-Za-z0-9.\-]*)", re.I)
KIND = {"fig": "fig", "figure": "fig", "figs": "fig", "figures": "fig", "table": "tab", "tables": "tab",
        "eq": "eq", "equation": "eq", "equations": "eq", "section": "sec", "sections": "sec",
        "sec": "sec", "appendix": "app", "图": "fig", "表": "tab", "式": "eq"}
BRACKET_RE = re.compile(r"\[([0-9,\s\-–]+)\]")
AUTHOR_RE = re.compile(r"\(([A-Z][A-Za-z\-]+)(?:\s(?:et al\.|and\s[A-Z][A-Za-z\-]+))?"
                       r",?\s?((?:19|20)\d{2})[a-z]?\)")
CITE_RE = re.compile(r"\\cite\{([^}]+)\}")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

def has(text, term):
    if not term:
        return False
    if CJK_RE.search(term):
        return term in text
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.I) is not None

def numbers(text):
    text = LABEL_RE.sub(" ", AUTHOR_RE.sub(" ", BRACKET_RE.sub(" ", CITE_RE.sub(" ", text))))
    out = {}
    for m in NUM_RE.finditer(text):
        try:
            val = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        suffix = (m.group(2) or "").lower()
        out["%.6g%s" % (val * SCALE.get(suffix, 1), "%" if suffix == "%" else "")] = m.group(0).strip()
    return out

def units(text):
    return {u.replace("℃", "°C").replace("μ", "µ") for u in UNIT_RE.findall(text)}

def markers(text):
    return {KIND.get(m.group(1).lower().rstrip("."), "other") + ":" + m.group(2).rstrip(".") for m in LABEL_RE.finditer(text)}
def citations(text):
    keys = set()
    for m in BRACKET_RE.finditer(text):
        for part in re.split(r"[,，]", m.group(1)):
            part = part.strip()
            if part.isdigit():
                keys.add("[" + part + "]")
            elif re.fullmatch(r"\d+\s*[-–]\s*\d+", part):
                lo, hi = re.split(r"[-–]", part)
                keys.update("[%d]" % i for i in range(int(lo), min(int(hi), int(lo) + 50) + 1))
    keys.update("(%s,%s)" % (m.group(1).lower(), m.group(2)) for m in AUTHOR_RE.finditer(text))
    keys.update("cite:" + k.strip().lower() for m in CITE_RE.finditer(text) for k in m.group(1).split(",") if k.strip())
    return keys

def cite_kept(key, target):
    if key.startswith("cite:"):
        return key[5:] in target.lower()
    if key.startswith("("):
        surname, year = key[1:-1].split(",")
        return surname in target.lower() and year in target
    return key in target

def glossary(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.rstrip("\n").split("\t")]
        if not line.strip() or line.startswith("#") or cells[0].lower() in {"zh_term", "term", "中文术语", "原文术语"}:
            continue
        cells += [""] * (5 - len(cells))
        rows.append({"zh": cells[0], "en": cells[1], "code": cells[2],
                     "banned_zh": [v for v in cells[3].split("|") if v], "banned_en": [v for v in cells[4].split("|") if v]})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--bilingual", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--direction", default="auto", choices=["auto", "zh2en", "en2zh"])
    a = ap.parse_args()
    for p, label in ((a.glossary, "glossary"), (a.bilingual, "bilingual JSON")):
        if not os.path.exists(p):
            print("FAIL: %s missing: %s" % (label, p))
            return 2
    try:
        terms = glossary(a.glossary)
    except (OSError, UnicodeDecodeError) as exc:
        print("FAIL: glossary unreadable: %s" % exc)
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
    dropped = len([s for s in segs if not isinstance(s, dict)])
    segs = [s for s in segs if isinstance(s, dict)]
    names = ("missing_locked", "variant_drift", "numbers_missing", "numbers_added", "units_missing",
             "markers_missing", "citations_missing", "citations_added", "empty_targets",
             "duplicate_ids", "untranslated", "glossary_unused")
    b = {k: [] for k in names}
    seen, hits, occurrences, zh_to_en, en_to_zh = set(), 0, 0, 0, 0
    for seg in segs:
        sid, src, tgt = str(seg.get("id", "?")), seg.get("source") or "", seg.get("target") or ""
        b["duplicate_ids"] += [sid] if sid in seen else []
        seen.add(sid)
        if not tgt.strip():
            b["empty_targets"].append(sid)
            continue
        if sid.startswith("R"):
            continue
        direction = a.direction if a.direction != "auto" else ("zh2en" if CJK_RE.search(src) else "en2zh")
        zh_to_en += direction == "zh2en"; en_to_zh += direction == "en2zh"
        for t in terms:
            if not has(src, t["zh"]) and not has(src, t["en"]):
                continue
            occurrences += 1
            expect = t["en"] if direction == "zh2en" else t["zh"]
            if has(tgt, expect) or (direction == "zh2en" and has(tgt, t["code"])):
                hits += 1
            else:
                b["missing_locked"].append({"segment": sid, "term": t["zh"], "expected": expect})
            banned = t["banned_en"] if direction == "zh2en" else t["banned_zh"]
            b["variant_drift"] += [{"segment": sid, "term": t["zh"], "found": v} for v in banned if has(tgt, v)]
        sn, tn = numbers(src), numbers(tgt)
        b["numbers_missing"] += [{"segment": sid, "value": sn[k]} for k in sn if k not in tn]
        b["numbers_added"] += [{"segment": sid, "value": tn[k]} for k in tn if k not in sn]
        b["units_missing"] += [{"segment": sid, "unit": u} for u in sorted(units(src) - units(tgt))]
        b["markers_missing"] += [{"segment": sid, "marker": m} for m in sorted(markers(src) - markers(tgt))]
        b["citations_missing"] += [{"segment": sid, "cite": c} for c in sorted(citations(src)) if not cite_kept(c, tgt)]
        b["citations_added"] += [{"segment": sid, "cite": c} for c in sorted(citations(tgt) - citations(src))]
        if direction == "zh2en" and len(CJK_RE.findall(tgt)) >= 4:
            b["untranslated"].append({"segment": sid, "issue": "chinese left in english target"})
        if direction == "en2zh" and not CJK_RE.search(tgt):
            b["untranslated"].append({"segment": sid, "issue": "no chinese in zh target"})
    b["glossary_unused"] = [t["zh"] or t["en"] for t in terms
                            if (t["zh"] or t["en"]) and not any(
                                has(s.get("source") or "", t["zh"]) or has(s.get("source") or "", t["en"]) for s in segs)]
    report = {"segments": len(segs), "segments_translated": len(segs) - len(b["empty_targets"]),
              "non_object_segments_dropped": dropped,
              "direction_counts": {"zh2en": zh_to_en, "en2zh": en_to_zh}, "glossary_entries": len(terms),
              "term_occurrences": occurrences, "locked_hits": hits,
              "locked_hit_rate": round(hits / occurrences, 4) if occurrences else 1.0,
              "counts": {k: len(v) for k, v in b.items()},
              "verdict": "pass" if not any(v for k, v in b.items() if k != "glossary_unused") else "review"}
    report.update({k: v[:60] for k, v in b.items()})
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    json.dump(report, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("verdict=%s locked_hit_rate=%.3f zh2en=%d en2zh=%d counts=%s"
          % (report["verdict"], report["locked_hit_rate"], zh_to_en, en_to_zh, json.dumps(report["counts"])))
    return 0 if report["verdict"] == "pass" else 1

if __name__ == "__main__":
    sys.exit(main())
