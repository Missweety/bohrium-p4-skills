#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""grade.py - deterministic 0/1/2 rubric scorer for reading-benchmark items.

Scoring is rule-based and reproducible. Every score record carries a rationale,
a failure taxonomy label, and the evidence anchor it matched (or failed to match).
No score is produced for an item without a gold answer: such items are reported
as ungradable and excluded from aggregates instead of being silently scored.
"""
import re
import unicodedata

HARD_LIMIT = 2000       # answers longer than this cannot be graded reliably
CONCISE_LIMIT = 1200    # public contract limit; longer but containing gold -> 1

UNIT_CANON = {
    "milligram": "mg", "milligrams": "mg", "mg": "mg",
    "gram": "g", "grams": "g", "g": "g",
    "kilogram": "kg", "kg": "kg", "microgram": "µg", "ug": "µg", "µg": "µg",
    "nanogram": "ng", "ng": "ng",
    "milliliter": "mL", "millilitre": "mL", "ml": "mL", "mL": "mL",
    "microliter": "µL", "ul": "µL", "µL": "µL", "liter": "L", "litre": "L", "l": "L",
    "hour": "h", "hours": "h", "hr": "h", "hrs": "h", "h": "h",
    "minute": "min", "minutes": "min", "min": "min", "mins": "min",
    "second": "s", "seconds": "s", "sec": "s", "s": "s",
    "day": "day", "days": "day", "week": "week", "weeks": "week",
    "month": "month", "months": "month", "year": "year", "years": "year",
    "°c": "°C", "℃": "°C", "celsius": "°C",
    "kelvin": "K", "k": "K",
    "%": "%", "percent": "%", "percentage": "%", "wt%": "wt%", "vol%": "vol%",
    "ppm": "ppm", "ppb": "ppb",
    "millimolar": "mM", "mm": "mM", "micromolar": "µM", "um": "µM", "µm": "µM",
    "nanomolar": "nM", "nm": "nM", "molar": "M", "m": "M",
    "kj/mol": "kJ/mol", "kj": "kJ", "kcal/mol": "kcal/mol",
    "mpa": "MPa", "kpa": "kPa", "pa": "Pa", "bar": "bar",
    "rpm": "rpm", "hz": "Hz", "khz": "kHz", "mhz": "MHz", "v": "V", "kv": "kV",
    "w": "W", "kw": "kW", "da": "Da", "kda": "kDa",
}
NUM_RE = re.compile(r"(?<![\w.])([-+]?\d+(?:[.,]\d+)*)\s?([A-Za-zµμ%‰°℃/]+)?")
REFUSAL_RE = re.compile(
    r"(?:insufficient (?:evidence|information)|cannot (?:be )?determin|unable to answer|"
    r"not enough information|无法判断|无法确定|材料不足|证据不足|无法回答|不能确定)", re.I)
ABSENCE_HINTS = ["未报告", "未提供", "无数据", "没有数据", "未给出", "未检测到",
                 "not reported", "not available", "no data", "not provided"]
UNCERTAIN_HINTS = ["无法判断", "无法确定", "insufficient evidence", "cannot determine",
                   "unclear", "不确定"]


def normalize(text):
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = text.replace("μ", "µ").replace("，", ",").replace("。", ".")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonical_unit(unit):
    if not unit:
        return ""
    u = normalize(unit).lower().strip(" .")
    return UNIT_CANON.get(u, u)


def parse_numbers(text):
    out = []
    for m in NUM_RE.finditer(normalize(text)):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        out.append({"value": val, "unit": m.group(2) or "",
                    "norm_unit": canonical_unit(m.group(2) or "")})
    return out


def numbers_match(a, b, rel=1e-6, abs_tol=1e-9):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def unit_compatible(a, b):
    ca, cb = canonical_unit(a), canonical_unit(b)
    if not ca or not cb:
        return None  # unknown / missing
    return ca == cb


def content_terms(text):
    text = normalize(text).lower()
    terms = []
    for w in re.findall(r"[a-z][a-z0-9\-_]{1,}", text):
        if w not in {"the", "and", "for", "with", "from", "that", "this", "was", "were",
                     "are", "is", "were", "has", "have", "its", "their", "than", "then"}:
            terms.append(w)
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        terms.extend(run[i:i + 2] for i in range(len(run) - 1))
    return terms


def token_coverage(gold, candidate):
    g = set(content_terms(gold))
    if not g:
        return 1.0
    c = set(content_terms(candidate))
    return len(g & c) / float(len(g))


def _flatten_answer(answer):
    if isinstance(answer, str):
        return answer
    if answer is None:
        return ""
    if isinstance(answer, (int, float)):
        return str(answer)
    if isinstance(answer, (list, tuple)):
        return "; ".join(_flatten_answer(a) for a in answer)
    if isinstance(answer, dict):
        for key in ("answer", "text", "value", "content"):
            if key in answer:
                return _flatten_answer(answer[key])
        return ""
    return str(answer)


def _citations(answer_obj):
    cits = []
    if not isinstance(answer_obj, dict):
        return cits
    for key in ("citations", "evidence", "sources", "spans"):
        val = answer_obj.get(key)
        if isinstance(val, list):
            for c in val:
                if isinstance(c, dict):
                    cits.append(c)
                elif isinstance(c, str):
                    cits.append({"quote": c})
    if answer_obj.get("unit_id") or answer_obj.get("source_path"):
        cits.append({"unit_id": answer_obj.get("unit_id"),
                     "source_path": answer_obj.get("source_path"),
                     "locator": answer_obj.get("locator"),
                     "quote": answer_obj.get("quote", "")})
    return cits


def _quote_overlap(a, b):
    ta = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", normalize(a).lower()))
    tb = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", normalize(b).lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(min(len(ta), len(tb)))


def anchor_matches(item, citations):
    if not citations:
        return False, "no_citation"
    gold_units = {ev.get("unit_id") for ev in item.get("evidence", [])}
    gold_quotes = [ev.get("quote", "") for ev in item.get("evidence", [])]
    gold_paths = {ev.get("source_path") for ev in item.get("evidence", [])}
    for c in citations:
        if c.get("unit_id") and c.get("unit_id") in gold_units:
            return True, "unit_id"
        quote = c.get("quote") or c.get("text") or ""
        if quote:
            for gq in gold_quotes:
                if gq and _quote_overlap(quote, gq) >= 0.55:
                    return True, "quote_overlap"
        loc = c.get("locator") or {}
        if c.get("source_path") in gold_paths and loc:
            for ev in item.get("evidence", []):
                gl = ev.get("locator") or {}
                if loc.get("table_id") and loc.get("table_id") == gl.get("table_id") \
                        and str(loc.get("row_index")) == str(gl.get("row_index")):
                    return True, "table_locator"
                if loc.get("paragraph_id") and loc.get("paragraph_id") == gl.get("paragraph_id") \
                        and c.get("source_path") == ev.get("source_path"):
                    return True, "paragraph_id"
    return False, "citation_not_matching_gold"


def compare_value(item, answer):
    """Return (level, detail). level in exact / partial / wrong / none."""
    gold = item.get("gold_answer") or ""
    variants = item.get("acceptable_variants") or [gold]
    typ = item.get("task_type")
    ans = normalize(answer)
    if not ans:
        return "none", "answer is empty"
    if not normalize(gold):
        return "none", "gold answer missing"

    gold_numbers = parse_numbers(gold)
    ans_numbers = parse_numbers(ans)

    if typ in ("numeric", "table") and gold_numbers:
        g = gold_numbers[0]
        best = None
        for a in ans_numbers:
            if numbers_match(a["value"], g["value"]):
                best = a
                break
        if best is None:
            for v in variants:
                if normalize(v) and normalize(v).lower() in ans.lower():
                    return "exact", "matched acceptable variant text"
            return "wrong", "no number matches gold %s" % gold
        compat = unit_compatible(best["unit"], g["unit"])
        if not canonical_unit(g["unit"]):
            return "exact", "value %.6g (gold has no unit requirement)" % best["value"]
        if compat:
            return "exact", "value %.6g with unit %s" % (best["value"], best["unit"] or "-")
        if compat is None:
            return "partial", "value matches but unit missing"
        return "partial", "value matches but unit %r != %r" % (best["unit"], g["unit"])

    # qualitative answers
    for v in variants:
        vn = normalize(v).lower()
        if vn and vn in ans.lower():
            return "exact", "matched acceptable variant"
    if typ == "absence":
        for hint in ABSENCE_HINTS:
            if hint in ans.lower():
                return "exact", "negative-evidence statement matches"
        for hint in UNCERTAIN_HINTS:
            if hint in ans.lower():
                return "partial", "hedged as uncertain instead of not reported"
        if ans_numbers:
            return "wrong", "fabricated numeric value for an unreported result"
        return "wrong", "does not state that the result is unreported"

    cov = token_coverage(gold, ans)
    if cov >= 0.9:
        return "exact", "gold content coverage %.2f" % cov
    if cov >= 0.6:
        return "partial", "gold content coverage %.2f" % cov
    return "wrong", "gold content coverage %.2f" % cov


def grade_item(item, answer_obj, policy=None):
    """Grade one item; returns a fully traceable score record."""
    policy = policy or {}
    typ = item.get("task_type", "unknown")
    gold = item.get("gold_answer") or ""
    rec = {
        "item_id": item.get("item_id"),
        "task_type": typ,
        "gold_answer": gold,
        "score": 0,
        "level_label": "不通过",
        "gradable": bool(normalize(gold)),
        "failure_type": None,
        "rationale": "",
        "matched_anchor": None,
        "answer_chars": 0,
        "source_path": (item.get("evidence") or [{}])[0].get("source_path"),
        "evidence_unit": (item.get("evidence") or [{}])[0].get("unit_id"),
        "scorer": "rule:rubric-v1",
    }
    if not rec["gradable"]:
        rec["failure_type"] = "gold_missing"
        rec["rationale"] = "题卡缺参考答案，不能打分；已从汇总中排除并标记 ungradable"
        rec["level_label"] = "不可判"
        return rec

    if not isinstance(answer_obj, dict):
        rec["failure_type"] = "format_invalid"
        rec["rationale"] = "回答不是对象格式，无法提取 answer/citations"
        return rec

    ans = _flatten_answer(answer_obj.get("answer"))
    ans = normalize(ans)
    rec["answer_chars"] = len(ans)
    if not ans.strip():
        rec["failure_type"] = "empty_answer"
        rec["rationale"] = "回答为空或仅空白字符"
        return rec
    if len(ans) > HARD_LIMIT:
        rec["failure_type"] = "answer_too_long"
        rec["rationale"] = "回答长度 %d 超过硬上限 %d，无法可靠判分" % (len(ans), HARD_LIMIT)
        return rec

    qn = normalize(item.get("question", "")).lower()
    if qn and qn in ans.lower() and len(qn) >= 12:
        rec["failure_type"] = "question_echo"
        rec["rationale"] = "回答直接复述题干，不构成答案"
        return rec

    level, detail = compare_value(item, ans)
    anchor_ok, anchor_kind = anchor_matches(item, _citations(answer_obj))
    rec["matched_anchor"] = anchor_kind if anchor_ok else None

    if len(ans) > CONCISE_LIMIT and level != "wrong":
        level = "partial"
        detail += "; answer exceeds concise limit of %d chars" % CONCISE_LIMIT

    if level == "exact" and anchor_ok:
        score, label = 2, "通过"
    elif level == "exact":
        score, label = 1, "部分通过"
        rec["failure_type"] = "missing_or_wrong_anchor"
    elif level == "partial":
        score, label = (1, "部分通过") if anchor_ok else (0, "不通过")
        if not anchor_ok:
            rec["failure_type"] = "partial_without_anchor"
        else:
            rec["failure_type"] = "partial_value"
    else:
        score, label = 0, "不通过"
        if REFUSAL_RE.search(ans) and typ != "absence":
            rec["failure_type"] = "refusal_mismatch"
            detail += "; refused although the material contains the answer"
        elif not anchor_ok and level != "wrong":
            rec["failure_type"] = "missing_or_wrong_anchor"
        else:
            rec["failure_type"] = "wrong_value" if typ in ("numeric", "table") else "wrong_content"

    rec["score"] = score
    rec["level_label"] = label
    rec["value_check"] = detail
    rec["rationale"] = "%s；值判定=%s；定位=%s（%s）" % (
        detail, level, "命中" if anchor_ok else "未命中", anchor_kind)
    return rec


def summarize(records, items, condition="baseline"):
    graded = [r for r in records if r.get("gradable")]
    skipped = [r for r in records if not r.get("gradable")]
    n = len(graded)
    total = sum(r["score"] for r in graded)
    max_score = 2 * n

    def bucket(keyfn):
        out = {}
        for r in graded:
            k = keyfn(r) or "unknown"
            b = out.setdefault(k, {"n": 0, "total": 0, "dist": {"0": 0, "1": 0, "2": 0}})
            b["n"] += 1
            b["total"] += r["score"]
            b["dist"][str(r["score"])] += 1
        for b in out.values():
            b["mean_score"] = round(b["total"] / float(b["n"]), 4)
            b["mean_normalized"] = round(b["total"] / float(2 * b["n"]), 4)
            b["strict_accuracy"] = round(b["dist"]["2"] / float(b["n"]), 4)
        return out

    failure_counts = {}
    for r in records:
        ft = r.get("failure_type")
        if ft:
            failure_counts[ft] = failure_counts.get(ft, 0) + 1

    return {
        "condition": condition,
        "items_total": len(items),
        "items_graded": n,
        "items_skipped": len(skipped),
        "total_score": total,
        "max_score": max_score,
        "normalized_score": round(total / float(max_score), 4) if max_score else 0.0,
        "strict_accuracy": round(sum(1 for r in graded if r["score"] == 2) / float(n), 4) if n else 0.0,
        "macro_score": round(sum(r["score"] / 2.0 for r in graded) / float(n), 4) if n else 0.0,
        "distribution": {str(s): sum(1 for r in graded if r["score"] == s) for s in (0, 1, 2)},
        "by_task_type": bucket(lambda r: r.get("task_type")),
        "by_difficulty": bucket(lambda r: "d%d" % _difficulty_of(items, r.get("item_id"))),
        "failure_counts": failure_counts,
        "failures": [{"item_id": r["item_id"], "task_type": r.get("task_type"),
                      "failure_type": r.get("failure_type"),
                      "score": r.get("score"), "rationale": r.get("rationale"),
                      "answer_chars": r.get("answer_chars")}
                     for r in records if r.get("score") == 0 or r.get("failure_type")],
        "skipped": [{"item_id": r["item_id"], "failure_type": r.get("failure_type"),
                     "rationale": r.get("rationale")} for r in skipped],
    }


def _difficulty_of(items, item_id):
    for it in items:
        if it.get("item_id") == item_id:
            return it.get("difficulty", 0)
    return 0


def rubric_self_check(items):
    """Prove the rubric is not degenerate: gold -> 2, empty -> 0, overlong -> 0."""
    rows, ok = [], True
    for it in items:
        gold_answer = {
            "item_id": it["item_id"],
            "answer": it["gold_answer"],
            "citations": [{"unit_id": ev["unit_id"], "source_path": ev["source_path"],
                           "quote": ev["quote"], "locator": ev.get("locator")}
                          for ev in it.get("evidence", [])],
        }
        gold_rec = grade_item(it, gold_answer)
        empty_rec = grade_item(it, {"item_id": it["item_id"], "answer": ""})
        long_rec = grade_item(it, {"item_id": it["item_id"],
                                   "answer": (it["gold_answer"] + " ") * 800})
        checks = {"gold_scores_2": gold_rec["score"] == 2,
                  "empty_scores_0": empty_rec["score"] == 0,
                  "overlong_scores_0": long_rec["score"] == 0}
        ok = ok and all(checks.values())
        rows.append({"item_id": it["item_id"], "checks": checks,
                     "gold_score": gold_rec["score"],
                     "empty_failure": empty_rec["failure_type"],
                     "overlong_failure": long_rec["failure_type"]})
    return {"pass": ok, "items": rows,
            "note": "规则自检：金标准与自带定位应得 2 分；空回答与超长回答应得 0 分。"}
