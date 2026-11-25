#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""baselines.py - deterministic local baseline readers.

These are real program runs over the public item view + provided source units.
They are NOT DeepSeek Harness scores and must never be reported as such.

  extractive : simple IDF retrieval + type-aware span extraction, always cites
  naive      : deliberately weak control (no retrieval, no citation)
"""
import math
import re

from ingest import content_terms, norm_ws

TYPE_HINTS = [
    ("table", ["表 ", "表格", "table", "cell", "row", "column"]),
    ("absence", ["是否报告", "未报告", "does the source report", "unreported"]),
    ("condition", ["条件", "范围", "边界", "适用", "scope", "condition"]),
    ("definition", ["定义", "说明", "describe", "define", "meaning"]),
    ("relation", ["相比", "compare", "compared"]),
    ("numeric", ["数值", "多少", "value", "how much", "how many"]),
]
COND_MARKERS = ["only if", "only when", "provided that", "in the presence of",
                "in the absence of", "beyond", "仅当", "只有在", "不适用于",
                "仅限于", "前提是", "超过", "在低", "在高"]
ABSENCE_HINTS = ["not reported", "not available", "no data", "not provided",
                 "未报告", "未提供", "无数据", "未检测到", "没有数据"]
NUMBER_RE = re.compile(r"(?<![\w.])([-+]?\d+(?:[.,]\d+)*)\s?([A-Za-zµμ%‰°℃/]+)?")


ABSENCE_Q_RE = re.compile(
    r"^(?:was|were|is|are|did|does|do)\b[^?]{0,80}\breported\b|"
    r"\bwhether\b[^?]{0,60}\breported\b|是否(?:报告|提及|给出)|有没有", re.I)


def infer_type(question, default=None):
    if ABSENCE_Q_RE.search(question):
        return "absence"
    low = question.lower()
    for typ, words in TYPE_HINTS:
        if any(w.lower() in low for w in words):
            return typ
    return default or "numeric"


def _sentence_units(units):
    for u in units:
        for s in u.get("sentences") or []:
            yield u, s


def build_index(units):
    df, docs = {}, {}
    for u in units:
        terms = content_terms(u["text"])
        docs[u["unit_id"]] = set(terms)
        for t in set(terms):
            df[t] = df.get(t, 0) + 1
    n = max(1, len(units))
    idf = {t: math.log((n + 1.0) / (c + 1.0)) + 1.0 for t, c in df.items()}
    return {"idf": idf, "docs": docs, "n": n}


def _quoted(question):
    out = re.findall(r"[「“\"]([^」”\"]{2,80})[」”\"]", question)
    return out


def _retrieve(question, units, index, kind=None, top_k=5):
    qterms = content_terms(question)
    qset = set(qterms)
    quoted = " ".join(_quoted(question)).lower()
    scored = []
    for u in units:
        doc = index["docs"].get(u["unit_id"], set())
        matched = qset & doc
        if not matched and not quoted:
            continue
        base = sum(index["idf"].get(t, 1.0) for t in matched)
        denom = sum(index["idf"].get(t, 1.0) for t in qset) or 1.0
        score = base / denom
        if quoted and quoted in u["text"].lower():
            score += 0.35
        if kind == "table" and u["kind"] == "table_row":
            score += 0.15
        if kind == "numeric" and re.search(r"\d", u["text"]):
            score += 0.05
        scored.append((score, u))
    scored.sort(key=lambda x: (-x[0], x[1]["unit_id"]))
    return scored[:top_k]


def _cite(unit, sentence):
    return {"unit_id": unit["unit_id"], "source_path": unit["source_path"],
            "quote": sentence["text"][:400], "locator": unit.get("locator")}


def _answer_numeric(question, hits):
    quoted_terms = [q.lower() for q in _quoted(question)]
    best = None
    for score, unit in hits:
        if unit["kind"] != "paragraph":
            continue
        for sent in unit.get("sentences") or []:
            numbers = list(NUMBER_RE.finditer(sent["text"]))
            if not numbers:
                continue
            local = score
            stext = sent["text"].lower()
            for q in quoted_terms:
                if q in stext:
                    local += 0.2
            for m in numbers:
                if m.group(2):
                    local += 0.1
                    break
            if best is None or local > best[0]:
                best = (local, unit, sent, m)
    if not best:
        return None
    _, unit, sent, m = best
    return {"answer": norm_ws(m.group(0)),
            "citations": [_cite(unit, sent)],
            "confidence": round(best[0], 4)}


def _answer_table(question, units, hits):
    m = re.search(r"(?:表|Table)\s*([A-Za-z]?\d+)", question)
    wanted_table = m.group(1) if m else None
    quoted = _quoted(question)
    question_wo_quote = re.sub(r"[「“\"][^」”\"]+[」”\"]", "", question)
    for score, unit in hits:
        if unit["kind"] != "table_row" or not unit.get("table"):
            continue
        t = unit["table"]
        if wanted_table and wanted_table.lstrip("Tt") != t["table_id"].lstrip("Tt"):
            continue
        row_label = t["row_label"]
        if row_label and row_label.lower() not in question_wo_quote.lower():
            continue
        cols = t["columns"]
        target_col = None
        if quoted:
            for c in cols:
                if quoted[0].lower() in c.lower() or c.lower() in quoted[0].lower():
                    target_col = c
                    break
        if target_col is None:
            for c in cols[1:]:
                if c.lower() in question_wo_quote.lower():
                    target_col = c
                    break
        if target_col is None:
            continue
        j = cols.index(target_col)
        if j >= len(t["values"]):
            continue
        value = t["values"][j].strip()
        if not value:
            continue
        sent = unit["sentences"][0]
        return {"answer": value, "citations": [_cite(unit, sent)],
                "confidence": round(score, 4)}
    return None


def _answer_condition(question, hits):
    for score, unit in hits:
        for sent in unit.get("sentences") or []:
            text = sent["text"]
            positions = [(text.lower().find(mk), mk) for mk in COND_MARKERS
                         if text.lower().find(mk) >= 0]
            if not positions:
                continue
            pos = min(positions)[0]
            clause = text[pos:]
            return {"answer": clause[:240], "citations": [_cite(unit, sent)],
                    "confidence": round(score, 4)}
    return None


def _answer_definition(question, hits):
    quoted = _quoted(question)
    term = quoted[0] if quoted else ""
    for score, unit in hits:
        for sent in unit.get("sentences") or []:
            text = sent["text"]
            if term and term.lower() not in text.lower():
                continue
            m = re.search(r"^(.*?)\s+(?:is|are)\s+(?:defined as|referred to as|refers to|means|used to)?\s*(.{8,200})$",
                          text)
            if not m:
                m2 = re.search(r"(?:是指|指的是|定义为|称为|即)(.{6,200})$", text)
                if m2:
                    return {"answer": m2.group(1).strip(), "citations": [_cite(unit, sent)],
                            "confidence": round(score, 4)}
                continue
            predicate = m.group(2).strip()
            return {"answer": predicate[:200], "citations": [_cite(unit, sent)],
                    "confidence": round(score, 4)}
    return None


def _answer_absence(question, hits):
    quoted = _quoted(question)
    term = quoted[0].lower() if quoted else ""
    for score, unit in hits:
        for sent in unit.get("sentences") or []:
            text = sent["text"].lower()
            if term and term not in text and not any(h in text for h in ABSENCE_HINTS):
                continue
            if any(h in text for h in ABSENCE_HINTS):
                return {"answer": "未报告" if re.search(r"[\u4e00-\u9fff]", question) else "not reported",
                        "citations": [_cite(unit, sent)],
                        "confidence": round(score, 4)}
    return None


def _answer_relation(question, hits):
    for score, unit in hits:
        for sent in unit.get("sentences") or []:
            m = re.search(r"\b(higher|lower|greater|smaller)\s+than\b\s*([A-Za-z0-9\- ]{2,30})",
                          sent["text"], re.I)
            if m:
                return {"answer": "%s than %s" % (m.group(1).lower(), m.group(2).strip()),
                        "citations": [_cite(unit, sent)],
                        "confidence": round(score, 4)}
    return None


def extractive_answer(item, units, index):
    question = item["question"]
    typ = infer_type(question, item.get("task_type"))
    hits = _retrieve(question, units, index, kind=typ)
    best_score = hits[0][0] if hits else 0.0
    if not hits or best_score < 0.10:
        return {"item_id": item["item_id"], "answer": "", "citations": [],
                "strategy": "extractive-v1",
                "confidence": round(best_score, 4),
                "failure_reason": "retrieval_below_threshold"}
    fn = {"numeric": _answer_numeric, "table": _answer_table,
          "condition": _answer_condition, "definition": _answer_definition,
          "absence": _answer_absence, "relation": _answer_relation}[typ]
    if typ == "table":
        res = fn(question, units, hits)
    else:
        res = fn(question, hits)
    if not res:
        return {"item_id": item["item_id"], "answer": "", "citations": [],
                "strategy": "extractive-v1", "confidence": round(best_score, 4),
                "failure_reason": "no_extractable_span"}
    res.update({"item_id": item["item_id"], "strategy": "extractive-v1"})
    return res


def naive_answer(item, units, index=None):
    """Control baseline: no retrieval, no citations. Expected to score poorly."""
    question = item["question"]
    typ = infer_type(question, item.get("task_type"))
    if typ == "table":
        text = "Please check the table in the source."
    elif typ == "numeric":
        text = "The source does not provide a numeric value."
    elif units:
        text = norm_ws(units[0]["text"])[:200]
    else:
        text = "No material available."
    return {"item_id": item["item_id"], "answer": text, "citations": [],
            "strategy": "naive-v1", "confidence": 0.0}


def run_baselines(public_items, units, agents=("extractive", "naive")):
    index = build_index(units)
    runs = {}
    for agent in agents:
        answers = []
        for item in public_items:
            if agent == "extractive":
                answers.append(extractive_answer(item, units, index))
            else:
                answers.append(naive_answer(item, units, index))
        runs[agent] = answers
    return runs
