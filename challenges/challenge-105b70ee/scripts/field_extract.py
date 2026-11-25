#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""field_extract.py - fill a requested field table from addressed paragraphs.

Each requested field becomes one row:

  {field_id, description, status, value, unit, statistic, experimental_condition,
   comparator, paragraph_id, quote, candidates, note}

Rules (see references/extraction-protocol.md):
  * reported      value is a verbatim substring of quote and quote is verbatim source text
  * not_reported  no supporting sentence exists; value stays null (never 0/guess)
  * source_conflict  two mutually exclusive values for the same field in the same sentence
  * extraction_failed material unreadable / no paragraph index

Stdlib only. No network, no prepared answers.
"""
from __future__ import annotations

import json
import os
import re

NUM_RE = re.compile(
    r"(?<![\w.])"
    r"((?:[-+<>≤≥~]\s*)?\d+(?:,\d{3})*(?:\.\d+)?"
    r"(?:\s*(?:±|\+/-|\+-)\s*\d+(?:\.\d+)?)?"
    r"(?:\s*(?:%|‰))?)")
UNIT_AFTER = re.compile(
    r"^\s*([A-Za-zµμΩ%‰°][A-Za-z0-9µμΩ%‰°/·^.^+-]{0,16})")
UNIT_HINT = re.compile(
    r"(?:\bin\s+|\bmeasured in\s+|\bunits?\s+of\s+|单位为\s*|单位[:：]\s*)"
    r"([A-Za-zµμ%‰°][A-Za-z0-9µμ%‰°/·^.^+-]{0,14})", re.I)
UNIT_STOP = {"eq", "eq.", "fig", "fig.", "table", "section", "the", "this", "which",
             "our", "study", "paper", "work", "total", "order", "turn", "addition"}
UNIT_WORDS = {"mg", "g", "kg", "ug", "µg", "ng", "ml", "l", "dl", "ul", "µl", "mmol",
              "mol", "µmol", "umol", "nm", "cm", "mm", "m", "km", "s", "ms", "min",
              "h", "hr", "d", "day", "days", "week", "weeks", "month", "months",
              "year", "years", "k", "pa", "kpa", "mpa", "hz", "khz", "v", "mv", "a",
              "ma", "w", "kw", "j", "kj", "cal", "kcal", "c", "°c", "da", "ppm",
              "ppb", "au", "a.u", "copies", "cells"}


def _plausible_unit(u):
    if not u:
        return False
    s = u.strip().strip(".,;:")
    if not s:
        return False
    if s.lower() in UNIT_STOP:
        return False
    if any(ch in s for ch in "/%‰^µμ°"):
        return True
    return s.lower() in UNIT_WORDS
STAT_RE = re.compile(
    r"(\b95\s*%?\s*CI\b|\bCI\b|\bp\s*[=<>≤≥]\s*0?\.\d+|\bmean\s*(?:±|SD|SE\b)|\b±\b|"
    r"\bmedian\b|\bIQR\b|\bSD\b|\bSE\b|\bn\s*=\s*\d+|\bSEM\b|置信区间|显著性)", re.I)
COND_RE = re.compile(
    r"((?:at|under|in|during|after|with|for)\s+[^,.;]{2,80}?(?=\s+(?:was|were|is|are|the|a|an)\b|[,.;]|$)"
    r"|在[^，。；]{2,40}条件下)", re.I)
COMP_RE = re.compile(
    r"((?:compared\s+(?:with|to|against)|versus|\bvs\.?|对照|相比(?:于)?)\s*[^,.;]{2,60})", re.I)
CUE_RE = re.compile(
    r"(?:denotes|represents|refers to|defined as|corresponds to|indicates|shows?|"
    r"表示|定义为|指的是|表明|显示)", re.I)
STOPWORDS = {"the", "and", "for", "with", "from", "that", "this", "were", "was", "are",
             "into", "than", "then", "they", "their", "which", "while", "when", "where",
             "have", "been", "also", "more", "most", "only", "such", "some", "value",
             "values", "field", "extract", "reported", "report", "paper", "study",
             "数据", "字段", "提取", "报告", "研究", "结果", "值"}


def norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _as_field_def(item, idx):
    if isinstance(item, str):
        return {"field_id": item, "description": item, "aliases": [], "unit": None}
    if not isinstance(item, dict):
        return None
    fid = None
    for key in ("field_id", "id", "key", "name", "field", "column"):
        if isinstance(item.get(key), str) and item[key].strip():
            fid = item[key].strip()
            break
    if not fid:
        return None
    desc = ""
    for key in ("description", "desc", "label", "question", "prompt", "hint", "title"):
        if isinstance(item.get(key), str) and item[key].strip():
            desc = item[key].strip()
            break
    aliases = item.get("aliases") or item.get("synonyms") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    return {
        "field_id": fid,
        "description": desc,
        "aliases": [str(a) for a in aliases if str(a).strip()],
        "unit": item.get("unit") if isinstance(item.get("unit"), str) else None,
        "expect_numeric": item.get("type") in ("number", "numeric", "float", "int", "integer")
        or bool(item.get("unit"))
        or bool(re.search(r"\d|数值|值|amount|count|rate|concentration|percentage|dose",
                          desc + " " + fid, re.I)),
    }


def load_target_fields(input_dir, case):
    """Find the requested field table in /input (target-fields.json or case.json)."""
    candidates = []
    for name in ("target-fields.json", "target_fields.json", "fields.json", "workorder.json"):
        path = os.path.join(input_dir, name)
        if os.path.isfile(path):
            candidates.append(path)
    for dirpath, dirnames, names in os.walk(input_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in sorted(names):
            if name.endswith(".json") and name not in (
                    "case.json", "corpus-manifest.json", "material.json",
                    "primary-material.json", "secondary-material.json") and \
                    os.path.join(dirpath, name) not in candidates:
                candidates.append(os.path.join(dirpath, name))

    raw = None
    for path in candidates:
        try:
            data = load_json(path)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, list) and data and _as_field_def(data[0], 0):
            raw = data
            break
        if isinstance(data, dict):
            for key in ("fields", "target_fields", "targets", "requested_fields", "items"):
                if isinstance(data.get(key), list) and data[key]:
                    raw = data[key]
                    break
        if raw:
            break
    if raw is None and isinstance(case, dict):
        for key in ("target_fields", "fields", "targets"):
            if isinstance(case.get(key), list) and case[key]:
                raw = case[key]
                break
    defs = []
    for i, item in enumerate(raw or [], 1):
        d = _as_field_def(item, i)
        if d:
            defs.append(d)
    return defs


def _tokens(text):
    out = []
    for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,}|[\u4e00-\u9fff]{2,}", text or ""):
        w = w.lower()
        if w in STOPWORDS:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if w not in out:
            out.append(w)
    return out


def _sentences(text):
    parts = re.split(r"(?<=[.!?。！？])\s+", text or "")
    return [p.strip() for p in parts if len(p.strip()) >= 12]


def _score(text, tokens):
    low = text.lower()
    score = 0.0
    for t in tokens:
        hits = low.count(t)
        if hits:
            score += 2.0 + min(hits, 3) * 0.5
    return score


def _pick_numeric(sentence, field, tokens):
    """Choose the number the field actually refers to (proximity + unit + context)."""
    matches = list(NUM_RE.finditer(sentence or ""))
    if not matches:
        return None
    expected = (field.get("unit") or "").strip()
    field_pos = [m.start() for t in tokens for m in re.finditer(re.escape(t), sentence.lower())]
    best = None
    for m in matches:
        token = m.group(1).strip()
        after = sentence[m.end():m.end() + 18]
        um = UNIT_AFTER.match(after)
        unit = um.group(1).strip().rstrip(".,;:") if um else ""
        if not _plausible_unit(unit):
            unit = ""
        score = 0.0
        if field_pos:
            dist = min(abs(m.start() - p) for p in field_pos)
            score += max(0.0, 30.0 - dist / 3.0)
        if expected and unit == expected:
            score += 14
        if re.search(r"±|\+/-|CI|p\s*[=<>]", sentence, re.I):
            score += 1
        if re.match(r"^(?:19|20)\d{2}$", token):
            score -= 8  # a year is rarely the requested measurement
        if re.match(r"^\s*(?:years?|months?|days?|weeks?|yr)\b", after, re.I) and not \
                re.search(r"year|month|day|week|时间|随访", " ".join(tokens)):
            score -= 10
        if best is None or score > best[0]:
            best = (score, token, unit)
    return {"value": best[1], "unit": best[2] or None}


def _ci_value(sentence, field, tokens):
    m = re.search(r"(?:95\s*%\s*CI|confidence interval)[^0-9]{0,12}"
                  r"(\d+(?:\.\d+)?\s*(?:[-–—~]|to)\s*\d+(?:\.\d+)?)", sentence, re.I)
    if not m:
        return None
    value = re.sub(r"\s*to\s*", "-", m.group(1))
    quote_num = re.sub(r"\s*to\s*", "-", m.group(1))
    if quote_num not in sentence and value not in sentence:
        return None
    return {"value": value, "unit": None, "statistic": "95% CI"}


def _is_ci_field(field):
    key = (field["field_id"] + " " + field["description"]).lower()
    return bool(re.search(r"\bci\b|confidence interval|置信区间", key))


def _is_comparator_field(field):
    key = (field["field_id"] + " " + field["description"]).lower()
    return bool(re.search(r"comparator|comparison group|control group|对照|对照组", key))


def _is_conclusion_field(field):
    key = (field["field_id"] + " " + field["description"]).lower()
    return bool(re.search(r"conclusion|conclude|implication|结论|作者观点|总体判断", key))


def _conclusion_value(sentence):
    m = re.search(r"(?:conclude[ds]?|conclusion|we find|authors? (?:report|state|note)|"
                  r"结论(?:是|为)?|作者(?:认为|指出|指出?))"
                  r"(?:\s*that\s+|\s*:\s*|\s+)(.{8,200})", sentence, re.I)
    if not m:
        return None
    val = _clause(m.group(1))
    val = re.sub(r"^that\s+", "", val, flags=re.I)
    return val if len(val) >= 8 else None


def _condition(sentence):
    m = COND_RE.search(sentence)
    return norm(m.group(1)) if m else None


def _comparator(sentence):
    m = COMP_RE.search(sentence)
    if not m:
        return None
    txt = norm(m.group(1))
    txt = re.sub(r"^(?:compared\s+(?:with|to|against)|versus|\bvs\.?|对照|相比(?:于)?)\s*",
                 "", txt, flags=re.I)
    return txt.strip() or None


def _statistic(sentence):
    found = []
    for m in STAT_RE.finditer(sentence):
        tok = m.group(1).strip()
        if tok not in found:
            found.append(tok)
    return " + ".join(found) if found else None


def _clause(text):
    """Cut at a sentence end without splitting decimals such as 1.42."""
    return re.split(r"[。；]|\.(?=\s|$)", text)[0].strip()


def _text_value(sentence, tokens):
    """No number: take a verbatim clause right after a definition cue."""
    low = sentence.lower()
    pos = -1
    for t in tokens:
        pos = low.find(t)
        if pos >= 0:
            break
    if pos < 0:
        return None
    tail = sentence[pos:]
    m = re.match(r"^.{0,60}?(?:is|are|was|were|defined as|refers to|表示|指的是|定义为)\s+(.{3,120})",
                 tail, re.S)
    if not m:
        return None
    val = _clause(m.group(1))
    return val if len(val) >= 3 else None


def _table_candidate(field, doc):
    tokens = _tokens(field["description"] + " " + " ".join(field["aliases"]))
    headers = None
    best = None
    for row in doc.get("tables") or []:
        cells = row.get("cells") or []
        if not cells:
            continue
        joined = " ".join(cells)
        score = _score(joined, tokens)
        if headers is None:
            if tokens and score < 2:
                continue
            headers = cells
            continue
        if tokens and score < 2 and not any(_score(h, tokens) >= 2 for h in headers):
            continue
        for idx, (h, c) in enumerate(zip(headers, cells)):
            hscore = _score(h, tokens)
            if hscore < 2 or not re.search(r"\d", c):
                continue
            if best is None or hscore + score > best[0]:
                rate_note = ""
                if re.search(r"rate|proportion|percentage|比例|率", h, re.I) and "%" not in c:
                    rate_note = ("表格该列为计数/比例口径，按单元格原文记录，未换算为率。")
                best = (hscore + score, {
                    "value": c, "unit": None, "anchor": row.get("anchor"),
                    "quote": " | ".join(cells), "paragraph_id": row.get("anchor"),
                    "header": h, "note": rate_note,
                    "match_score": hscore,
                })
    return best[1] if best else None


def _row_for(field, doc):
    tokens = _tokens(" ".join([field["description"], field["field_id"]] +
                              field["aliases"]))
    if not tokens:
        return {"field_id": field["field_id"], "description": field["description"],
                "status": "not_reported", "value": None, "note": "字段无可用关键词，未猜测",
                "paragraph_id": None, "quote": None}

    scored = []
    special_field = (_is_comparator_field(field) or _is_conclusion_field(field)
                     or _is_ci_field(field))
    for p in doc.get("paragraphs") or []:
        s = _score(p["text"], tokens)
        if s > 0 or special_field:
            scored.append((s, p))
    scored.sort(key=lambda x: (-x[0], x[1]["paragraph_id"]))

    best = None
    for pscore, para in scored[:(8 if special_field else 3)]:
        for sent in _sentences(para["text"]):
            ss = _score(sent, tokens)
            special = ((_is_comparator_field(field) and COMP_RE.search(sent)) or
                       (_is_conclusion_field(field) and
                        re.search(r"conclu|结论|作者", sent, re.I)) or
                       (_is_ci_field(field) and _ci_value(sent, field, tokens)))
            if ss <= 0 and not special:
                continue
            if ss <= 0:
                ss = 1.0
            numeric = bool(NUM_RE.search(sent))
            total = pscore * 0.3 + ss + (2 if numeric and field.get("expect_numeric") else 0)
            if CUE_RE.search(sent):
                total += 0.5
            if special:
                total += 8
            if best is None or total > best[0]:
                best = (total, para, sent)

    table = _table_candidate(field, doc)

    if best is None and table is None:
        return {
            "field_id": field["field_id"],
            "description": field["description"],
            "status": "not_reported",
            "value": None, "unit": None, "statistic": None,
            "experimental_condition": None, "comparator": None,
            "paragraph_id": None, "quote": None, "candidates": [],
            "note": "在已索引材料中未找到与该字段匹配的陈述，按 not_reported 处理（不填 0、不推测）。",
        }

    if best is None:
        return {
            "field_id": field["field_id"],
            "description": field["description"],
            "status": "reported",
            "value": table["value"], "unit": table.get("unit"),
            "statistic": None, "experimental_condition": None,
            "comparator": None, "paragraph_id": table.get("paragraph_id"),
            "quote": table.get("quote"), "candidates": [],
            "note": "取值来自表格行；value 为该单元格逐字内容。",
        }

    total, para, sentence = best
    value, unit, note = None, None, None
    statistic = _statistic(sentence)

    if _is_ci_field(field):
        ci = _ci_value(sentence, field, tokens)
        if ci:
            value, unit, statistic = ci["value"], ci["unit"], ci["statistic"]
            note = "区间按原文逐字记录，未合并成点估计。"
    elif _is_comparator_field(field):
        comp = _comparator(sentence)
        if comp:
            value = comp
            note = "对照组按原文表述逐字记录，未推断其定义。"
    elif _is_conclusion_field(field):
        val = _conclusion_value(sentence)
        if val:
            value = val
            note = "作者结论按原文从句逐字截取，未升级为确定事实。"
    elif field.get("expect_numeric"):
        num = _pick_numeric(sentence, field, tokens)
        if num:
            value = num["value"]
            unit = num["unit"]
            note = "取值与该句逐字一致；单位按数值后紧随文本记录，缺失则留空。"

    if value is None and not field.get("expect_numeric"):
        val = _text_value(sentence, tokens)
        if val:
            value = val
            note = "非数值字段：取定义线索后的原文短语，未改写。"

    # A matching table column outranks a nearby body number for numeric fields.
    table = _table_candidate(field, doc)
    if table and (value is None or (field.get("expect_numeric")
                                    and table.get("match_score", 0) >= 4)):
        row = {
            "field_id": field["field_id"],
            "description": field["description"],
            "status": "reported",
            "value": table["value"], "unit": table.get("unit"),
            "statistic": None, "experimental_condition": None,
            "comparator": None, "paragraph_id": table.get("paragraph_id"),
            "source_file": None, "page": None, "section": None,
            "quote": table.get("quote"), "candidates": [],
            "header": table.get("header"),
            "note": (table.get("note") or "") + "取值来自表格单元格，逐字记录。",
        }
        row["value_is_verbatim"] = table["value"] in (table.get("quote") or "")
        return row

    if value is None:
        return {
            "field_id": field["field_id"],
            "description": field["description"],
            "status": "not_reported",
            "value": None, "unit": None, "statistic": None,
            "experimental_condition": None, "comparator": None,
            "paragraph_id": para["paragraph_id"], "quote": sentence,
            "candidates": [],
            "note": "命中相关段落但未给出可直接引用的取值，按 not_reported 处理（不推测）。",
        }

    row = {
        "field_id": field["field_id"],
        "description": field["description"],
        "status": "reported",
        "value": value,
        "unit": unit,
        "statistic": statistic,
        "experimental_condition": _condition(sentence),
        "comparator": _comparator(sentence),
        "paragraph_id": para["paragraph_id"],
        "source_file": para.get("source_file"),
        "page": para.get("page"),
        "section": para.get("section") or None,
        "quote": sentence[:400],
        "candidates": [],
        "note": note,
    }
    row["value_is_verbatim"] = value in sentence
    return row


def run(doc, input_dir, case):
    fields = load_target_fields(input_dir, case)
    if not fields:
        return {"fields": [], "requested": 0,
                "note": "输入未提供目标字段表；未猜测字段集合"}
    rows = []
    for field in fields:
        if not doc.get("paragraphs") and not doc.get("tables"):
            rows.append({
                "field_id": field["field_id"], "description": field["description"],
                "status": "extraction_failed", "value": None,
                "unit": None, "statistic": None, "experimental_condition": None,
                "comparator": None, "paragraph_id": None, "quote": None,
                "note": "材料不可读或未索引到段落，需人工接管。",
            })
            continue
        rows.append(_row_for(field, doc))
    return {"fields": rows, "requested": len(fields)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="fill a requested field table")
    ap.add_argument("--doc", required=True)
    ap.add_argument("--input", default="/input")
    ap.add_argument("--case", default=None)
    ap.add_argument("--out", default="work/field_results.json")
    a = ap.parse_args()
    case = {}
    if a.case and os.path.isfile(a.case):
        try:
            case = load_json(a.case)
        except Exception:  # noqa: BLE001
            case = {}
    with open(a.doc, encoding="utf-8") as fh:
        doc = json.load(fh)
    res = run(doc, a.input, case)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print("fields=%d reported=%d" % (
        res["requested"], sum(1 for r in res["fields"] if r.get("status") == "reported")))
