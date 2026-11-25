#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge.py - turn locatable source units into source-conditioned benchmark items.

Each item carries:
  question (never contains the gold answer), gold answer + variants,
  evidence quote with locator, 0/1/2 rubric, difficulty and data licence.

Anti-leakage is enforced twice: candidate generation and a final audit pass.
Candidates that would echo the answer are rejected and logged, not silently kept.
"""
import json
import re
import unicodedata

from ingest import content_terms, cjk_ratio, norm_ws

try:
    from grade import UNIT_CANON, canonical_unit
except Exception:  # pragma: no cover - grade.py ships alongside
    UNIT_CANON = {}
    canonical_unit = lambda u: (u or "").strip()

NUM_UNIT_ALTERNATION = (
    r"%|‰|wt%|vol%|°C|℃|mg|kg|µg|ug|ng|g|mL|ml|µL|uL|dL|L|mmol|µmol|umol|mol|"
    r"mM|µM|uM|nM|kJ/mol|kJ|kcal/mol|MPa|kPa|Pa|bar|mm|cm|nm|km|m|"
    r"rpm|Hz|kHz|MHz|kV|V|mA|kW|W|min|mins|minute|minutes|h|hr|hrs|hour|hours|"
    r"s|sec|day|days|week|weeks|month|months|year|years|ppm|ppb|Da|kDa|mL/min|"
    r"mL/min/g|cm3/g|m2/g")
NUMBER_RE = re.compile(r"(?<![\w.])([-+]?\d+(?:[.,]\d+)*)\s?(%s)?" % NUM_UNIT_ALTERNATION,
                       re.I)
ZH_COND_RE = re.compile(
    r"(?:仅当|只有当|只有在|在[^，。；]{1,24}(?:条件|情况|范围)下|前提是|"
    r"不适用于|仅限于|超过[^，。；]{1,12}(?:后|以后|之后)|"
    r"在[^，。；]{1,16}(?:存在|加入|不含|含)[^，。；]{0,12}(?:时|条件下))")
EN_COND_RE = re.compile(
    r"\b(?:only if|only when|provided that|under (?:the )?conditions?|"
    r"in the presence of|in the absence of|at (?:pH|a feed|pressures?|temperatures?)|"
    r"limited to|does not apply|not applicable|beyond \d+|"
    r"when [^,.;]{2,60})\b", re.I)
ABSENCE_RE = re.compile(
    r"(?:was|were|is|are)?\s*not (?:reported|available|measured|provided)|"
    r"\bno data\b|\bnot determined\b|未报告|未见报告|未给出|没有数据|未检测到|"
    r"无法获得|未提供", re.I)
NO_DATA_ON_RE = re.compile(
    r"No data on ([^.;]{3,80}?)\s+(?:are|is|was|were) (?:available|reported)", re.I)
DEF_EN_RE = re.compile(
    r"^([A-Z][A-Za-z0-9 ,/\-]{2,48}?)\s+(?:is|are)\s+(?:defined as|referred to as|"
    r"used to|the\s+[a-z ]{2,30}\s+that|the\s+[a-z ]{2,30}\s+of)\s+(.{8,220})$")
DEF_EN_SIMPLE_RE = re.compile(
    r"^([A-Z][A-Za-z0-9 ,/\-]{2,48}?)\s+(?:refers to|means|is defined as)\s+(.{8,220})$")
DEF_ZH_RE = re.compile(r"^([\u4e00-\u9fffA-Za-z0-9\-（）() ]{2,24}?)(?:是指|指的是|定义为|称为|即)(.{6,200})$")
REL_EN_RE = re.compile(
    r"([A-Za-z0-9\-]+(?: [A-Za-z0-9\-]+){0,4})\s+(?:was|were|is|are)\s+"
    r"(higher|lower|greater|smaller|more|less)\s+than\s+([A-Za-z0-9\-]+(?: [A-Za-z0-9\-]+){0,4})",
    re.I)

TYPE_KEYWORDS = {
    "numeric": ["数值", "数字", "多少", "量值", "百分比", "浓度", "温度", "时间", "value",
                "number", "how much", "how many", "quantity", "percentage", "metric"],
    "table": ["表格", "表中", "单元格", "行", "列", "table", "cell", "row", "column"],
    "definition": ["定义", "含义", "概念", "指什么", "definition", "define", "meaning",
                   "refers"],
    "condition": ["条件", "范围", "前提", "适用", "限制", "边界", "condition", "scope",
                  "limitation", "applicable", "only if"],
    "absence": ["未报告", "缺失", "没有报告", "不存在", "反幻觉", "幻觉", "not reported",
                "missing", "absence", "no data", "unsupported"],
    "relation": ["比较", "相比", "对比", "高", "低", "compare", "versus", "higher",
                 "lower", "relative"],
}
BASE_DIFFICULTY = {"numeric": 2, "table": 2, "definition": 1, "condition": 3,
                   "absence": 2, "relation": 3}

FORBIDDEN_SUBJECTS = {"this", "these", "that", "those", "it", "they", "we", "our",
                      "该", "这", "其", "本文"}


# ---------------------------------------------------------------- language utils
def detect_lang(text):
    return "zh" if cjk_ratio(text) > 0.05 else "en"


def norm_compare(text):
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def tokens(text):
    out = []
    for w in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text or ""):
        out.append(w.lower())
    return out


def ngram_overlap(a, b, n=8):
    ta, tb = tokens(a), tokens(b)
    if len(ta) < n or len(tb) < n:
        n = max(3, min(len(ta), len(tb)))
        if n < 3:
            return 0.0
    sa = set(tuple(ta[i:i + n]) for i in range(len(ta) - n + 1))
    sb = set(tuple(tb[i:i + n]) for i in range(len(tb) - n + 1))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(min(len(sa), len(sb)))


def find_numbers(text):
    out = []
    for m in NUMBER_RE.finditer(text or ""):
        raw = norm_ws(m.group(0))
        val = m.group(1).replace(",", "")
        unit = m.group(2) or ""
        try:
            fval = float(val)
        except ValueError:
            fval = None
        out.append({"raw": raw, "value": fval, "unit": unit,
                    "start": m.start(), "end": m.end()})
    return out


# ---------------------------------------------------------------- workorder
def _clause_text(obj):
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for k in ("question", "task", "text", "instruction", "prompt", "request",
                  "description", "title"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _split_clauses(text):
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    numbered = [re.sub(r"^(?:\d+[.)、]|[-*•]|\(\d+\))\s*", "", ln) for ln in lines
                if re.match(r"^(?:\d+[.)、]|[-*•]|\(\d+\))\s+", ln)]
    if len(numbered) >= 2:
        return numbered
    if len(lines) == 1 and len(lines[0]) > 220:
        return [s.strip() for s in re.split(r"(?<=[。；;])\s*", lines[0]) if len(s.strip()) > 8]
    return lines


def _clause_type(text):
    low = text.lower()
    best, best_n = None, 0
    for typ, words in TYPE_KEYWORDS.items():
        n = sum(1 for w in words if w.lower() in low)
        if n > best_n:
            best, best_n = typ, n
    return best


def _extract_workorder_block(task_text):
    if not task_text:
        return ""
    pat = re.compile(r"(?:^|\n)\s*(?:#{1,6}\s*)?(workorder|work order|工作单|任务单|题单|"
                     r"benchmark[- ]draft)\s*:?\s*\n(.*?)(?=\n\s*#{1,6}\s|\Z)", re.I | re.S)
    m = pat.search(task_text)
    return m.group(2).strip() if m else ""


def parse_workorder(case, task_text):
    raw, src = None, None
    for key in ("workorder", "work_order", "benchmark_draft", "benchmark_items",
                "requests", "deliverables", "items", "tasks"):
        val = case.get(key)
        if val not in (None, "", [], {}):
            if key in ("items", "tasks") and isinstance(val, list):
                if not any(_clause_text(x) for x in val):
                    continue
            raw, src = val, "case.%s" % key
            break
    if raw is None:
        block = _extract_workorder_block(task_text)
        if block:
            raw, src = block, "task.md#workorder"
    if raw is None:
        raw, src = "", "default"

    clauses = []
    if isinstance(raw, list):
        for i, obj in enumerate(raw):
            text = _clause_text(obj)
            if not text:
                continue
            cid = "W%02d" % (i + 1)
            if isinstance(obj, dict) and (obj.get("id") or obj.get("item_id")):
                cid = str(obj.get("id") or obj.get("item_id"))
            clauses.append({"clause_id": cid, "text": text, "type": _clause_type(text),
                            "keywords": content_terms(text),
                            "answer_hint": (obj.get("answer") or obj.get("reference_answer")
                                            if isinstance(obj, dict) else None)})
    elif isinstance(raw, str) and raw.strip():
        for i, text in enumerate(_split_clauses(raw)):
            if len(text) < 4:
                continue
            clauses.append({"clause_id": "W%02d" % (i + 1), "text": text,
                            "type": _clause_type(text),
                            "keywords": content_terms(text), "answer_hint": None})

    requested = None
    for key in ("n_items", "item_count", "num_items", "target_items"):
        v = case.get(key)
        if isinstance(v, int) and 1 <= v <= 20:
            requested = v
            break
    if requested is None:
        if clauses:
            requested = max(1, min(20, len(clauses)))
        else:
            requested = 4
    if not clauses:
        for typ, kw in (("numeric", "数值"), ("table", "表格"),
                        ("condition", "限定条件"), ("absence", "未报告")):
            clauses.append({"clause_id": "W%02d" % (len(clauses) + 1),
                            "text": "从来源构造一道%s题，须带原文定位且不回显答案" % kw,
                            "type": typ, "keywords": content_terms(kw),
                            "answer_hint": None})
    return {"clauses": clauses, "requested_items": requested, "source": src,
            "language": detect_lang(raw if isinstance(raw, str) else " ".join(
                c["text"] for c in clauses))}


# ---------------------------------------------------------------- leak audit
def leak_check(question, gold, variants, quote):
    flags = []
    qn = norm_compare(question)
    gn = norm_compare(gold)
    if not gn:
        return ["empty_gold"]
    if gn == qn:
        flags.append("question_equals_gold")
    elif len(gn) >= 2 and gn in qn:
        flags.append("gold_in_question")
    for v in variants or []:
        vn = norm_compare(v)
        if len(vn) >= 2 and vn != gn and vn in qn:
            flags.append("variant_in_question:%s" % vn[:40])
    for num in find_numbers(gold):
        raw = norm_compare(num["raw"])
        if raw and raw in qn:
            flags.append("number_in_question:%s" % raw)
    if quote:
        if ngram_overlap(question, quote, n=8) >= 0.6:
            flags.append("quote_echo")
    return sorted(set(flags))


def _evidence(unit, sentence):
    return {
        "unit_id": unit["unit_id"],
        "source_path": unit["source_path"],
        "quote": sentence["text"],
        "locator": unit["locator"],
        "char_start": sentence.get("start", 0),
        "char_end": sentence.get("end", len(sentence["text"])),
    }


def _subject_before(sentence_text, pos, lang):
    head = sentence_text[:pos].strip()
    if lang == "zh":
        head = re.split(r"[，。；：,;:]", head)[-1].strip()
        head = re.sub(r"^(?:其中|而|且|并且|同时|此外|另外)", "", head).strip()
        subj = head[-24:]
    else:
        head = re.split(r"[,;:]", head)[-1] if "," in head else head
        words = re.findall(r"[A-Za-z0-9%\-]+", head)
        words = [w for w in words if w.lower() not in ("the", "a", "an", "of", "in", "was",
                                                       "were", "is", "are", "at", "and")]
        words = words[-6:]
        # A quantity is reported *for* a noun phrase, so trailing verbs and
        # prepositions must not leak into the question subject.
        verbs = {"reached", "averaged", "measured", "recorded", "showed", "remained",
                 "dropped", "rose", "increased", "decreased", "maintained", "harvested",
                 "weighed", "contained", "given", "reported", "observed", "exceeded",
                 "exceeding", "provided", "held", "kept", "is", "was", "were", "are",
                 "had", "has", "have", "receive", "received", "produced", "yielded"}
        while words and words[-1].lower() in verbs:
            words.pop()
        while words and words[-1].lower() in ("at", "in", "of", "with", "by", "for", "to"):
            words.pop()
        subj = " ".join(words)
    return subj.strip(" ,;:-")


def _trim_clause(text, limit=220):
    text = norm_ws(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("; ", "；", ", which", "，这", " (", "（"):
        idx = cut.rfind(sep)
        if idx > limit * 0.5:
            return cut[:idx].strip()
    return cut.rstrip() + "…"


def _candidate(unit, sentence, typ, question, gold, variants, difficulty, basis,
               template_id, score):
    ev = _evidence(unit, sentence)
    flags = leak_check(question, gold, variants, ev["quote"])
    return {
        "task_type": typ,
        "question": question,
        "gold_answer": gold,
        "acceptable_variants": sorted(set([gold] + list(variants or []))),
        "evidence": [ev],
        "difficulty": difficulty,
        "difficulty_basis": basis,
        "template_id": template_id,
        "relevance": round(score, 4),
        "leak_flags": flags,
        "source_path": unit["source_path"],
        "section": unit.get("section"),
        "unit_id": unit["unit_id"],
    }


# ---------------------------------------------------------------- generators
def is_exponent_number(text, num):
    """True for numerals that belong to unit exponents, e.g. 'm-2' or 's-1'.

    Those are not reported measurements; taking them as gold produces a gold
    value like '2 s' for '120 µmol m-2 s-1' and an unanswerable question.
    """
    start, end = num["start"], num["end"]
    prev = text[start - 1] if start > 0 else ""
    nxt = text[end:end + 1]
    after = text[end + 1:end + 2]
    if prev in "-−^":
        return True
    if nxt in "-−^" and after.isdigit():
        return True
    return False


def numeric_candidates(units, lang):
    out = []
    for unit in units:
        if unit["kind"] != "paragraph":
            continue
        for si, sent in enumerate(unit.get("sentences") or []):
            text = sent["text"]
            nums = [n for n in find_numbers(text)
                    if n["unit"] and not is_exponent_number(text, n)]
            # One measurement per sentence keeps the question unambiguous: with
            # two values in the same sentence the subject alone cannot tell the
            # solver which group the gold value belongs to.
            if len(nums) != 1:
                continue
            # skip years, citation brackets and table references
            if re.search(r"\b(?:19|20)\d{2}\b", text) and not re.search(r"%|°C|mg|mL|h\b", text):
                continue
            confusions = len(find_numbers(text))
            for n in nums[:2]:
                subject = _subject_before(text, n["start"], lang)
                if not subject or subject.lower() in FORBIDDEN_SUBJECTS:
                    continue
                if len(subject) < 2:
                    continue
                # If another number is already inside the subject, the question
                # would be ambiguous ("for cultures at 22 °C, what is 65 %?").
                if re.search(r"\d", subject):
                    continue
                if lang != "zh" and len(subject.split()) < 2:
                    continue
                if lang == "zh":
                    q = "根据材料原文，%s 的报告数值是多少（请保留单位）？" % subject
                    if unit.get("section"):
                        q = "在「%s」一节中，%s 的报告数值是多少（请保留单位）？" % (
                            unit["section"], subject)
                else:
                    q = "According to the provided source, what value (with unit) is reported for %s?" % subject
                    if unit.get("section"):
                        q = "In the \"%s\" section, what value (with unit) is reported for %s?" % (
                            unit["section"], subject)
                variants = [n["raw"], "%s %s" % (n["value"], n["unit"]) if n["value"] else n["raw"]]
                basis = ["numeric_extraction", "unit_required"]
                diff = BASE_DIFFICULTY["numeric"]
                if confusions >= 3:
                    diff += 1
                    basis.append("multiple_numbers_in_sentence")
                if len(text) > 320:
                    diff += 1
                    basis.append("long_context")
                c = _candidate(unit, sent, "numeric", q, n["raw"], variants,
                               min(5, diff), basis, "numeric_v1", 1.0 / (1 + si * 0.1))
                out.append(c)
    return out


def table_candidates(tables, units, lang):
    out = []
    for table in tables:
        cols = table["columns"]
        for i, row in enumerate(table["rows"]):
            non_empty = [j for j, v in enumerate(row) if v.strip()]
            if len(non_empty) < 2:
                continue
            row_label = row[0].strip() if row[0].strip() else "row%d" % (i + 1)
            for j in non_empty[1:]:
                value = row[j].strip()
                col = cols[j].strip() if j < len(cols) else "col%d" % j
                if not value or norm_compare(value) in norm_compare(row_label):
                    continue
                if lang == "zh":
                    q = "在表 %s 中，%s 的「%s」取值是多少？" % (
                        table["table_id"], row_label, col)
                else:
                    q = "In Table %s, what is the \"%s\" value for %s?" % (
                        table["table_id"], col, row_label)
                unit = None
                for u in units:
                    if u.get("table") and u["table"]["table_id"] == table["table_id"] \
                            and u["table"]["row_index"] == i:
                        unit = u
                        break
                if unit is None:
                    continue
                sent = unit["sentences"][0]
                variants = [value, value.replace(" ", "")]
                basis = ["table_lookup", "row_and_column_binding"]
                diff = BASE_DIFFICULTY["table"] + (1 if len(cols) >= 5 else 0)
                c = _candidate(unit, sent, "table", q, value, variants, min(5, diff),
                               basis, "table_v1", 1.0)
                out.append(c)
    return out


def definition_candidates(units, lang):
    out = []
    for unit in units:
        if unit["kind"] != "paragraph":
            continue
        for sent in unit.get("sentences") or []:
            text = sent["text"].strip()
            m = None
            if lang == "zh":
                m = DEF_ZH_RE.match(text)
            if not m:
                m = DEF_EN_RE.match(text) or DEF_EN_SIMPLE_RE.match(text)
            if not m:
                continue
            term, predicate = m.group(1).strip(" ,;:"), m.group(2).strip()
            if term.lower() in FORBIDDEN_SUBJECTS or len(predicate) < 8:
                continue
            gold = _trim_clause(re.split(r";|；", predicate)[0], 180)
            q = ("材料如何定义或说明「%s」？" % term) if lang == "zh" else \
                ("How does the source define or describe \"%s\"?" % term)
            variants = [gold, predicate[:len(gold)]]
            c = _candidate(unit, sent, "definition", q, gold, variants,
                           BASE_DIFFICULTY["definition"],
                           ["definition_extraction"], "definition_v1", 0.9)
            out.append(c)
    return out


def condition_candidates(units, lang):
    out = []
    for unit in units:
        if unit["kind"] != "paragraph":
            continue
        for sent in unit.get("sentences") or []:
            text = sent["text"]
            m = (ZH_COND_RE.search(text) if lang == "zh" else EN_COND_RE.search(text)) \
                or ZH_COND_RE.search(text) or EN_COND_RE.search(text)
            if not m:
                continue
            clause = _trim_clause(text[m.start():], 200)
            if len(clause) < 10:
                continue
            marker = m.group(0)
            before = text[:m.start()].strip(" ,;:")
            subject = _trim_clause(before, 90)
            if lang == "zh":
                q = ("材料为「%s」设定的适用条件或范围是什么？" % subject
                     if len(subject) >= 4 else
                     "材料为该结论设定的适用条件或边界是什么？")
            else:
                q = ("What condition or scope does the source set for \"%s\"?" % subject
                     if len(subject) >= 8 else
                     "What condition or scope does the source set for this claim?")
            variants = [clause]
            basis = ["condition_or_scope_binding", "marker:%s" % marker[:30]]
            diff = BASE_DIFFICULTY["condition"]
            if len(text) > 300:
                diff += 1
                basis.append("long_context")
            c = _candidate(unit, sent, "condition", q, clause, variants, min(5, diff),
                           basis, "condition_v1", 0.8)
            out.append(c)
    return out


def relation_candidates(units, lang):
    out = []
    for unit in units:
        if unit["kind"] != "paragraph":
            continue
        for sent in unit.get("sentences") or []:
            text = sent["text"]
            m = REL_EN_RE.search(text)
            if not m:
                continue
            a, direction, b = m.group(1).strip(), m.group(2).lower(), m.group(3).strip()
            if a.lower() in FORBIDDEN_SUBJECTS or b.lower() in FORBIDDEN_SUBJECTS:
                continue
            gold = "%s than %s" % (direction, b)
            if lang == "zh":
                q = "与 %s 相比，%s 的相对高低如何？" % (b, a)
            else:
                q = "Compared with %s, how does %s compare?" % (b, a)
            c = _candidate(unit, sent, "relation", q, gold, [gold], BASE_DIFFICULTY["relation"],
                           ["explicit_comparison"], "relation_v1", 0.7)
            out.append(c)
    return out


def absence_candidates(units, lang):
    out = []
    for unit in units:
        if unit["kind"] != "paragraph":
            continue
        for sent in unit.get("sentences") or []:
            text = sent["text"]
            m = NO_DATA_ON_RE.search(text)
            term = ""
            if m:
                term = m.group(1).strip()
            elif ABSENCE_RE.search(text):
                idx = ABSENCE_RE.search(text).start()
                term = _subject_before(text, idx, lang)
                term = re.sub(r"^(?:no|the|a|an)\s+", "", term, flags=re.I).strip()
            if not term or len(term) < 3:
                continue
            gold = "未报告" if lang == "zh" else "not reported"
            variants = ["未报告", "材料未报告", "未提供", "无数据",
                        "not reported", "not available", "no data"]
            if lang == "zh":
                q = "材料是否报告了「%s」的结果或数值？" % _trim_clause(term, 70)
            else:
                q = "Does the source report a result or value for \"%s\"?" % _trim_clause(term, 90)
            c = _candidate(unit, sent, "absence", q, gold, variants,
                           BASE_DIFFICULTY["absence"],
                           ["negative_evidence", "hallucination_control"],
                           "absence_v1", 0.85)
            out.append(c)
    return out


GENERATORS = {
    "numeric": numeric_candidates,
    "table": table_candidates,
    "definition": definition_candidates,
    "condition": condition_candidates,
    "relation": relation_candidates,
    "absence": absence_candidates,
}


def _relevance(cand, clause):
    cterms = set(content_terms(cand["question"] + " " + cand["gold_answer"]))
    kws = set(clause.get("keywords") or [])
    if not kws:
        return 0.0
    return len(cterms & kws) / float(len(kws))


def _dedupe_key(c):
    gold = norm_compare(c["gold_answer"])
    if c["task_type"] == "table":
        return (c["task_type"], c["unit_id"], gold, c["question"])
    return (c["task_type"], gold, c["source_path"])


def forge(units, tables, workorder, case=None):
    case = case or {}
    lang = workorder.get("language") or "en"
    pools = {}
    for typ, fn in GENERATORS.items():
        if typ == "table":
            pools[typ] = fn(tables, units, lang)
        else:
            pools[typ] = fn(units, lang)

    items, rejected, warnings = [], [], []
    used = set()
    type_used = {}

    def take(typ, clause):
        best = None
        for cand in pools.get(typ, []):
            if _dedupe_key(cand) in used:
                continue
            if cand["leak_flags"]:
                continue
            rel = _relevance(cand, clause) if clause else 0.0
            key = (rel, cand["difficulty"], -len(cand["gold_answer"]))
            if best is None or key > best[0]:
                best = (key, cand)
        if best is None:
            return None
        cand = best[1]
        used.add(_dedupe_key(cand))
        return cand

    # one item per workorder clause, in clause order
    per_clause = []
    for clause in workorder["clauses"]:
        typ = clause["type"]
        order = ([typ] if typ else []) + [t for t in ("numeric", "table", "condition",
                                                      "absence", "definition", "relation")
                                         if t != typ]
        picked = None
        for t in order:
            cand = take(t, clause)
            if cand:
                cand["clause_id"] = clause["clause_id"]
                cand["clause_type_requested"] = typ
                picked = cand
                break
        if picked:
            per_clause.append((clause, picked))
        else:
            warnings.append("no leak-free candidate for clause %s (%s)"
                            % (clause["clause_id"], clause["text"][:60]))

    # fill up to requested count with the strongest remaining diverse candidates
    requested = workorder.get("requested_items") or len(per_clause) or 4
    chosen = [c for _, c in per_clause]
    if len(chosen) < requested:
        all_types = ["numeric", "table", "condition", "absence", "definition", "relation"]
        leftovers = []
        for t in all_types:
            for cand in pools.get(t, []):
                if _dedupe_key(cand) in used or cand["leak_flags"]:
                    continue
                leftovers.append(cand)
        leftovers.sort(key=lambda c: (-c["difficulty"], -c["relevance"], c["question"]))
        for cand in leftovers:
            if len(chosen) >= requested:
                break
            if _dedupe_key(cand) in used:
                continue
            if sum(1 for c in chosen if c["task_type"] == cand["task_type"]) >= 2:
                continue
            used.add(_dedupe_key(cand))
            cand["clause_id"] = "auto-fill"
            cand["clause_type_requested"] = cand["task_type"]
            chosen.append(cand)

    # final leak audit + numbering
    final = []
    for i, cand in enumerate(chosen):
        flags = leak_check(cand["question"], cand["gold_answer"],
                           cand["acceptable_variants"], cand["evidence"][0]["quote"])
        if flags:
            rejected.append({"reason": "final_leak_audit", "task_type": cand["task_type"],
                             "question": cand["question"], "gold_answer": cand["gold_answer"],
                             "flags": flags})
            continue
        item = dict(cand)
        item["item_id"] = "B%02d" % (len(final) + 1)
        item["leakage_status"] = "clean"
        item["leak_flags"] = []
        item["data_license"] = str(case.get("data_license") or
                                   case.get("license") or "provided-by-organizer")
        item["rubric"] = rubric_for(item)
        item["gold_source"] = "material-derived"
        final.append(item)

    # rejected candidates (cap for artifact size)
    for typ, pool in pools.items():
        for cand in pool:
            if cand["leak_flags"] and len(rejected) < 40:
                rejected.append({"reason": "candidate_leak", "task_type": typ,
                                 "question": cand["question"],
                                 "gold_answer": cand["gold_answer"],
                                 "flags": cand["leak_flags"]})

    coverage = {
        "requested_items": requested,
        "forged_items": len(final),
        "clauses": len(workorder["clauses"]),
        "clauses_covered": len([c for c in chosen if c.get("clause_id") not in (None, "auto-fill")]),
        "by_type": {},
        "by_source": {},
        "unit_count": len(units),
        "table_count": len(tables),
        "rejected_candidates": len(rejected),
    }
    for item in final:
        coverage["by_type"][item["task_type"]] = \
            coverage["by_type"].get(item["task_type"], 0) + 1
        coverage["by_source"][item["source_path"]] = \
            coverage["by_source"].get(item["source_path"], 0) + 1
    return {"items": final, "rejected": rejected, "warnings": warnings,
            "coverage": coverage, "language": lang}


def rubric_for(item):
    typ = item["task_type"]
    if typ in ("numeric", "table"):
        return {
            "levels": {"2": "数值与单位正确，且引用定位与金标准证据一致",
                       "1": "数值正确但单位或定位之一不符/缺失",
                       "0": "数值错误、空回答、超长不可判或拒绝回答"},
            "gold_value": item["gold_answer"],
            "unit_policy": "单位等价视为正确；缺失单位最高 1 分",
            "anchor_policy": "必须给出 source_path 与段落/表格定位或原文短引文",
        }
    if typ == "absence":
        return {
            "levels": {"2": "明确说明材料未报告，并给出否定证据定位",
                       "1": "仅说无法判断，但未编造数值",
                       "0": "编造数值或声称材料报告了不存在的结果"},
            "gold_value": item["gold_answer"],
            "unit_policy": "不适用",
            "anchor_policy": "定位到含否定表述的原文句子",
        }
    return {
        "levels": {"2": "核心表述与金标准一致，且定位正确",
                   "1": "核心要素部分命中，或定位缺失/不符",
                   "0": "与金标准冲突、空回答、超长不可判"},
        "gold_value": item["gold_answer"],
        "unit_policy": "术语与单位按等价表比较",
        "anchor_policy": "定位到金标准证据句",
    }


def public_items(items):
    """What a solver is allowed to see: no gold, no evidence, no rubric."""
    out = []
    for it in items:
        out.append({"item_id": it["item_id"], "question": it["question"],
                    "task_type": it["task_type"], "max_answer_chars": 1200})
    return out
