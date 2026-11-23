#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_dataset.py - build a writing benchmark from real source material.

Four item families, each judgeable by observable evidence instead of taste:

  fact_preserve    rewrite a paragraph for an audience and keep every number,
                   unit and limiting condition; no number absent from source
  section_coverage the draft must contain the required sections, each with at
                   least one source anchor
  citation_map     each required claim must appear with an anchor pointing at
                   the very unit that supports it
  absence_guard    a result the source does not report must not be invented

Gold is derived from the source units only. Items never echo their own gold,
and every item keeps a quote + locator so a reviewer can re-check it.
"""
import json
import re

from ingest import content_terms, norm_ws

# A compact unit table: enough to compare written drafts with source values.
UNIT_ALIASES = {
    "%": "%", "percent": "%", "percentage": "%",
    "°c": "°C", "℃": "°C", "celsius": "°C",
    "mg": "mg", "milligram": "mg", "milligrams": "mg",
    "g": "g", "gram": "g", "grams": "g", "kg": "kg", "µg": "µg", "ug": "µg", "ng": "ng",
    "ml": "mL", "milliliter": "mL", "millilitre": "mL", "µl": "µL", "ul": "µL", "dl": "dL",
    "l": "L", "liter": "L", "litre": "L",
    "h": "h", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
    "min": "min", "mins": "min", "minute": "min", "minutes": "min",
    "s": "s", "sec": "s", "second": "s", "seconds": "s",
    "day": "day", "days": "day", "week": "week", "weeks": "week",
    "month": "month", "months": "month", "year": "year", "years": "year",
    "ppm": "ppm", "ppb": "ppb",
    "mm": "mm", "cm": "cm", "nm": "nm", "m": "m", "µm": "µm", "um": "µm",
    "kda": "kDa", "da": "Da",
    "mmol": "mmol", "µmol": "µmol", "umol": "µmol", "mol": "mol",
}
_UNITS = sorted({"mmol", "µmol", "umol", "mol", "mg", "kg", "µg", "ug", "ng", "mL", "ml",
                 "µL", "uL", "dL", "L", "g", "mm", "cm", "nm", "m", "°C", "℃", "%",
                 "ppm", "ppb", "h", "hr", "hrs", "min", "minute", "minutes", "s", "sec",
                 "day", "days", "week", "weeks", "month", "months", "year", "years",
                 "Da", "kDa"}, key=len, reverse=True)
NUM_UNIT_RE = re.compile(
    r"(?<![\w.])([-+]?\d+(?:[.,]\d+)*)\s?(" + "|".join(re.escape(u) for u in _UNITS) +
    r")(?![A-Za-zµ])", re.I)
ABSENCE_RE = re.compile(
    r"(?:no data on|not reported|not available|not determined|未报告|未提供|没有数据|未检测)",
    re.I)
ABSENCE_TOPIC_RE = re.compile(
    r"No data on ([^.;]{3,80}?)\s+(?:are|is|was|were) (?:available|reported)", re.I)
COND_RE = re.compile(
    r"\b(?:only when|only if|provided that|in the absence of|in the presence of|"
    r"at (?:pH|22|a )|limited to|does not apply)\b|(?:仅当|只有在|前提是|不适用于)", re.I)
DEFAULT_SECTIONS = ["Background", "Methods", "Results", "Limitations"]


def canon_unit(unit):
    u = (unit or "").strip().lower()
    return UNIT_ALIASES.get(u, u)


def parse_numbers(text):
    out = []
    for m in NUM_UNIT_RE.finditer(text or ""):
        start, end = m.start(), m.end()
        prev = text[start - 1] if start > 0 else ""
        nxt = text[end:end + 1]
        after = text[end + 1:end + 2]
        if prev in "-−^":            # exponent like m-2
            continue
        if nxt in "-−^" and after.isdigit():   # exponent like s-1
            continue
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.append({"raw": norm_ws(m.group(0)), "value": value,
                    "unit": m.group(2), "norm_unit": canon_unit(m.group(2))})
    return out


def _quote(unit, sentence):
    return {"unit_id": unit["unit_id"], "source_path": unit["source_path"],
            "quote": sentence["text"], "locator": unit.get("locator")}


def _difficulty(base, unit, n_numbers=0):
    d = base
    if unit and len(unit.get("text", "")) > 320:
        d += 1
    if n_numbers >= 2:
        d += 1
    return max(1, min(5, d))


def _fact_items(units, audience, max_chars, doc_numbers, limit=3):
    items = []
    for unit in units:
        if len(items) >= limit:
            break
        if unit["kind"] != "paragraph":
            continue
        nums = parse_numbers(unit["text"])
        if not nums:
            continue
        conds = [s for s in (unit.get("sentences") or []) if COND_RE.search(s["text"])]
        evidence = [_quote(unit, s) for s in (unit.get("sentences") or [])[:1]]
        items.append({
            "item_id": "F%02d" % (len(items) + 1),
            "task_type": "fact_preserve",
            "task": ("改写 %s 中该段，面向%s；必须保留全部数值、单位与限定条件，"
                     "不得出现材料中没有的数字，不得整段照搬原文，长度不超过 %d 字符。"
                     % (unit["source_path"], audience, max_chars)),
            "gold": {
                "numbers": nums,
                "document_numbers": doc_numbers,
                "conditions": [norm_ws(s["text"]) for s in conds],
                "source_text": unit["text"],
                "max_chars": max_chars,
                "must_cite_unit": unit["unit_id"],
            },
            "source_units": [unit["unit_id"]],
            "evidence": evidence,
            "rubric": {
                "2": "全部数值与单位保留，无材料外数字，限定条件未丢，长度合规",
                "1": "≥2/3 数值保留，或保留但混入材料外数字/丢限定条件",
                "0": "数值丢失/改错过半、长度不合规或空稿",
            },
            "difficulty": _difficulty(2, unit, len(nums)),
            "data_license": "provided-by-organizer",
        })
    return items


def _section_item(units, sections, max_chars):
    if not units:
        return []
    anchors = [u for u in units if u["kind"] in ("paragraph", "table_row")][:6]
    return [{
        "item_id": "S01",
        "task_type": "section_coverage",
        "task": ("按 %s 组织成稿；每一节至少给出一条带来源定位的事实，"
                 "总长不超过 %d 字符。" % ("、".join(sections), max_chars)),
        "gold": {
            "required_sections": sections,
            "max_chars": max_chars,
            "allowed_units": [u["unit_id"] for u in units],
        },
        "source_units": [u["unit_id"] for u in anchors],
        "evidence": [{"unit_id": u["unit_id"], "source_path": u["source_path"],
                      "quote": (u.get("sentences") or [{"text": u["text"]}])[0]["text"],
                      "locator": u.get("locator")} for u in anchors[:2]],
        "rubric": {
            "2": "全部小节都在，且过半小节带有效来源锚点",
            "1": "小节覆盖≥1/2，或小节全在但锚点缺失",
            "0": "小节覆盖<1/2 或空稿",
        },
        "difficulty": 2,
        "data_license": "provided-by-organizer",
    }]


def _citation_items(units, limit=3):
    items = []
    for unit in units:
        if len(items) >= limit:
            break
        if unit["kind"] != "paragraph":
            continue
        sents = [s for s in (unit.get("sentences") or [])
                 if len(s["text"]) >= 40 and (parse_numbers(s["text"]) or
                                              ABSENCE_RE.search(s["text"]))]
        if not sents:
            continue
        sent = sents[0]
        terms = [t for t in content_terms(sent["text"]) if len(t) > 3][:4]
        if len(terms) < 2:
            continue
        items.append({
            "item_id": "C%02d" % (len(items) + 1),
            "task_type": "citation_map",
            "claims": [{
                "claim_id": "C%02d-1" % (len(items) + 1),
                "keywords": terms,
                "unit_id": unit["unit_id"],
                "quote": sent["text"],
            }],
            "task": ("下列主张必须写入稿件，并各自附来源定位：%s" % sent["text"][:120]),
            "gold": {"claims": [{"claim_id": "C%02d-1" % (len(items) + 1),
                                 "keywords": terms, "unit_id": unit["unit_id"]}],
                     "allowed_units": [u["unit_id"] for u in units]},
            "source_units": [unit["unit_id"]],
            "evidence": [_quote(unit, sent)],
            "rubric": {
                "2": "每条主张都出现且锚点指向支持它的单元",
                "1": "主张出现但锚点错/缺，或覆盖一半以上",
                "0": "主张缺失或锚点全错",
            },
            "difficulty": _difficulty(3, unit, len(parse_numbers(sent["text"]))),
            "data_license": "provided-by-organizer",
        })
    return items


def _absence_item(units):
    for unit in units:
        if unit["kind"] != "paragraph":
            continue
        for sent in unit.get("sentences") or []:
            m = ABSENCE_TOPIC_RE.search(sent["text"])
            topic = m.group(1).strip() if m else ""
            if not topic and ABSENCE_RE.search(sent["text"]):
                topic = "the stated result"
            if not ABSENCE_RE.search(sent["text"]):
                continue
            return [{
                "item_id": "A01",
                "task_type": "absence_guard",
                "task": ("稿件不得为「%s」编造数值或结论；材料未报告时须明确写出未报告，"
                         "并给出否定证据定位。" % topic),
                "gold": {"absent_topic": topic, "unit_id": unit["unit_id"],
                         "max_chars": 4000},
                "source_units": [unit["unit_id"]],
                "evidence": [_quote(unit, sent)],
                "rubric": {
                    "2": "明确写出未报告并给出否定证据锚点",
                    "1": "没有为该主题编造内容，但也未明确说明未报告",
                    "0": "为该主题编造了数值或结论",
                },
                "difficulty": 2,
                "data_license": "provided-by-organizer",
            }]
    return []


def build(case, units, task_text=""):
    """Return a deterministic writing dataset for one case."""
    audience = str(case.get("audience") or "同行评审读者")
    max_chars = case.get("max_chars")
    if not isinstance(max_chars, int) or not 200 <= max_chars <= 40000:
        max_chars = 4000
    sections = case.get("required_sections")
    if not (isinstance(sections, list) and sections):
        sections = DEFAULT_SECTIONS
    sections = [str(s).strip() for s in sections if str(s).strip()]

    items = []
    doc_numbers = []
    for u in units:
        if u["kind"] == "paragraph":
            doc_numbers.extend(parse_numbers(u["text"]))
    items.extend(_fact_items(units, audience, max_chars, doc_numbers))
    items.extend(_section_item(units, sections, max_chars))
    items.extend(_citation_items(units))
    items.extend(_absence_item(units))

    by_type = {}
    for it in items:
        by_type[it["task_type"]] = by_type.get(it["task_type"], 0) + 1
    payload = {"dataset_version": "writing-bench-v2", "items": items,
               "required_sections": sections,
               "audience": audience, "max_chars": max_chars}
    return {
        "dataset_version": "writing-bench-v2",
        "case_id": case.get("case_id") or case.get("id") or "unknown",
        "audience": audience,
        "required_sections": sections,
        "max_chars": max_chars,
        "items": items,
        "by_type": by_type,
        "unit_count": len(units),
        "task_text_chars": len(task_text or ""),
        "dataset_sha256": _sha(payload),
    }


def _sha(obj):
    import hashlib
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    import argparse
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ingest
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/input")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    case, _, _ = ingest.load_case(args.input)
    task_text, _ = ingest.load_task(args.input, case)
    ing = ingest.ingest(case, args.input, task_text)
    data = build(case, ing["units"], task_text)
    blob = json.dumps(data, ensure_ascii=False, indent=1)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(blob)
    print(json.dumps({"case_id": data["case_id"], "items": len(data["items"]),
                      "by_type": data["by_type"],
                      "dataset_sha256": data["dataset_sha256"]}, ensure_ascii=False))
