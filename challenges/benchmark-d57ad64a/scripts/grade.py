#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""grade.py - deterministic 0/1/2 scorer for writing-benchmark items.

Scoring is rule-based so two reviewers (or two runs) reach the same verdict.
Each record carries the rationale, the failure taxonomy label and the anchor it
matched. Nothing is graded without a gold: such items are reported as
`ungradable` and excluded from aggregates instead of being scored silently.
"""
import re
import difflib

from build_dataset import parse_numbers, canon_unit
from ingest import norm_ws

MIN_CHARS = 60
COPY_WORDS = 30          # copying this many consecutive words is not a rewrite
ANCHOR_RE = re.compile(r"\[\s*(?:src|source|来源)\s*[:：]\s*([^\]\s]+)\s*\]", re.I)
HEADING_RE = re.compile(r"^\s{0,3}(?:#{1,6}\s+(.+?)\s*$|\*\*(.+?)\*\*\s*$|([^\n:：]{2,40})[:：]\s*$)")
ABSENCE_PHRASES = ["not reported", "not available", "no data", "does not report",
                   "does not provide", "未报告", "未提供", "没有数据", "未检测到"]


def normalize(text):
    if text is None:
        return ""
    text = norm_ws(str(text))
    return text


def find_anchors(text):
    return [m.group(1).strip() for m in ANCHOR_RE.finditer(text or "")]


def anchors_in(text, unit_ids):
    return [a for a in find_anchors(text) if a in set(unit_ids)]


def numbers_in(text):
    return parse_numbers(text or "")


def numbers_match(a, b):
    if a is None or b is None:
        return False
    if abs(a - b) > max(1e-9, 1e-6 * max(abs(a), abs(b))):
        return False
    return True


def _find_number(text, gold):
    for n in numbers_in(text):
        if numbers_match(n["value"], gold["value"]) and \
                canon_unit(n["norm_unit"]) == canon_unit(gold["norm_unit"]):
            return n
    return None


def headings_of(text):
    out = []
    for line in (text or "").splitlines():
        m = HEADING_RE.match(line)
        if not m:
            continue
        name = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        name = re.sub(r"\s+#+$", "", name).strip()
        if name and len(name) <= 60:
            out.append(name)
    return out


def section_bodies(text):
    """Map heading -> body text until the next heading."""
    lines = (text or "").splitlines()
    bodies, current, buf = {}, None, []
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            if current is not None:
                bodies[current] = "\n".join(buf)
            current = (m.group(1) or m.group(2) or m.group(3) or "").strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        bodies[current] = "\n".join(buf)
    return bodies


def _record(item, score, rationale, failure_type=None, anchor=None, chars=0):
    return {
        "item_id": item.get("item_id"),
        "task_type": item.get("task_type"),
        "score": score,
        "level_label": {2: "通过", 1: "部分通过", 0: "不通过"}[score],
        "gradable": True,
        "failure_type": failure_type if score < 2 else None,
        "rationale": rationale,
        "matched_anchor": anchor,
        "answer_chars": chars,
        "source_units": item.get("source_units") or [],
        "scorer": "rule:writing-rubric-v1",
    }


def _ungradable(item, reason):
    return {
        "item_id": item.get("item_id"), "task_type": item.get("task_type"),
        "score": 0, "level_label": "不可判", "gradable": False,
        "failure_type": "gold_missing", "rationale": reason,
        "matched_anchor": None, "answer_chars": 0,
        "source_units": item.get("source_units") or [],
        "scorer": "rule:writing-rubric-v1",
    }


def verbatim_run(draft, source_text):
    """Longest run of consecutive words shared with the source (copy detection)."""
    a = re.findall(r"\w+", (draft or "").lower())
    b = re.findall(r"\w+", (source_text or "").lower())
    if not a or not b:
        return 0
    m = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(
        0, len(a), 0, len(b))
    return m.size


def grade_fact_preserve(item, draft, units_all):
    gold = item.get("gold") or {}
    nums = gold.get("numbers") or []
    max_chars = int(gold.get("max_chars") or 4000)
    chars = len(draft)
    if not normalize(draft):
        return _record(item, 0, "空稿", "empty_draft", chars=chars)
    if chars < MIN_CHARS:
        return _record(item, 0, "稿件仅 %d 字符，未构成可判改写" % chars, "too_short",
                       chars=chars)
    if chars > max_chars:
        return _record(item, 0, "长度 %d 超过上限 %d" % (chars, max_chars), "too_long",
                       chars=chars)
    if not nums:
        return _ungradable(item, "题卡缺金标准数值")

    matched = [n for n in nums if _find_number(draft, n)]
    recall = len(matched) / float(len(nums))
    allowed_numbers = list(nums) + list(gold.get("document_numbers") or [])
    gold_pairs = {(round(n["value"], 9), canon_unit(n["norm_unit"]))
                  for n in allowed_numbers}
    extras = [n for n in numbers_in(draft)
              if (round(n["value"], 9), canon_unit(n["norm_unit"])) not in gold_pairs]
    conditions = gold.get("conditions") or []
    cond_ok = True
    for cond in conditions:
        terms = [t for t in re.findall(r"[A-Za-z]{4,}", cond.lower())][:6]
        if terms and sum(1 for t in terms if t in draft.lower()) < max(1, len(terms) // 2):
            cond_ok = False
    anchor_ok = bool(anchors_in(draft, gold.get("allowed_units") or
                                [gold.get("must_cite_unit")] + [u for u in units_all]))
    copied = verbatim_run(draft, gold.get("source_text"))

    if recall == 1.0 and not extras and cond_ok and copied < COPY_WORDS:
        return _record(item, 2, "数值全部保留(%d/%d)，无材料外数字，限定条件保留，"
                       "非整段照搬(最长同文 %d 词)" % (len(matched), len(nums), copied),
                       chars=chars, anchor=anchor_ok)
    if recall >= 0.67:
        why = []
        if extras:
            why.append("混入 %d 个材料外数字" % len(extras))
        if not cond_ok:
            why.append("限定条件丢失")
        if copied >= COPY_WORDS:
            why.append("整段照搬 %d 词，未构成改写" % copied)
        if recall < 1.0:
            why.append("数值保留 %d/%d" % (len(matched), len(nums)))
        return _record(item, 1, "；".join(why) or "部分保留",
                       "verbatim_copy" if copied >= COPY_WORDS else
                       ("invented_number" if extras else
                        ("lost_condition" if not cond_ok else "number_dropped")),
                       chars=chars)
    return _record(item, 0, "数值保留仅 %d/%d" % (len(matched), len(nums)),
                   "number_dropped", chars=chars)


def grade_section_coverage(item, draft, units_all):
    gold = item.get("gold") or {}
    req = [str(s) for s in (gold.get("required_sections") or [])]
    if not req:
        return _ungradable(item, "题卡缺必需小节")
    heads = [h.lower() for h in headings_of(draft)]
    bodies = {k.lower(): v for k, v in section_bodies(draft).items()}
    allowed = gold.get("allowed_units") or units_all
    found = [s for s in req if any(s.lower() == h or s.lower() in h for h in heads)]
    anchored = [s for s in found
                if anchors_in(bodies.get(s.lower(), ""), allowed)]
    coverage = len(found) / float(len(req))
    anchor_frac = len(anchored) / float(len(found)) if found else 0.0
    chars = len(draft)
    if not normalize(draft):
        return _record(item, 0, "空稿", "empty_draft", chars=chars)
    if coverage == 1.0 and anchor_frac >= 0.5:
        return _record(item, 2, "小节齐全(%d/%d)，%d 节带来源锚点"
                       % (len(found), len(req), len(anchored)), chars=chars)
    if coverage >= 0.5:
        return _record(item, 1, "小节覆盖 %d/%d，带锚点 %d 节"
                       % (len(found), len(req), len(anchored)), "section_incomplete",
                       chars=chars)
    return _record(item, 0, "小节覆盖 %d/%d" % (len(found), len(req)),
                   "section_missing", chars=chars)


def grade_citation_map(item, draft, units_all):
    gold = item.get("gold") or {}
    claims = gold.get("claims") or []
    if not claims:
        return _ungradable(item, "题卡缺主张清单")
    allowed = gold.get("allowed_units") or units_all
    ok, total = 0, len(claims)
    details = []
    for claim in claims:
        kws = [k.lower() for k in claim.get("keywords") or []]
        hit_kw = sum(1 for k in kws if k in draft.lower())
        has_claim = hit_kw >= max(1, min(2, len(kws)))
        has_anchor = claim.get("unit_id") in anchors_in(draft, allowed)
        if has_claim and has_anchor:
            ok += 1
        details.append("%s:主张%s/锚点%s" % (claim.get("claim_id"),
                                            "有" if has_claim else "无",
                                            "有" if has_anchor else "无"))
    chars = len(draft)
    ratio = ok / float(total)
    if ratio == 1.0:
        return _record(item, 2, "全部主张带正确锚点（%d/%d）" % (ok, total),
                       chars=chars, anchor=True)
    if ratio >= 0.5:
        return _record(item, 1, "；".join(details), "citation_incomplete", chars=chars)
    return _record(item, 0, "；".join(details), "citation_missing", chars=chars)


def grade_absence_guard(item, draft, units_all):
    gold = item.get("gold") or {}
    topic = str(gold.get("absent_topic") or "").strip()
    unit_id = gold.get("unit_id")
    chars = len(draft)
    if not normalize(draft):
        return _record(item, 0, "空稿", "empty_draft", chars=chars)
    low = draft.lower()
    topic_hit = bool(topic) and topic.lower() in low
    invented = False
    if topic_hit:
        for sent in re.split(r"(?<=[.!?。！？])\s+|\n+", draft):
            if topic.lower() not in sent.lower():
                continue
            if any(p in sent.lower() for p in ABSENCE_PHRASES):
                continue
            if numbers_in(sent):
                invented = True
                break
    says_absent = any(p in low for p in ABSENCE_PHRASES)
    anchor_ok = unit_id in anchors_in(draft, units_all or [unit_id])
    if invented:
        return _record(item, 0, "为「%s」编造了数值/结论" % topic, "invented_for_absent",
                       chars=chars)
    if says_absent and anchor_ok:
        return _record(item, 2, "明确说明未报告并带否定证据锚点", chars=chars, anchor=True)
    if says_absent:
        return _record(item, 1, "说明未报告但缺锚点", "missing_or_wrong_anchor",
                       chars=chars)
    return _record(item, 1, "没有编造，但未明确写出未报告", "absence_not_stated",
                   chars=chars)


HANDLERS = {
    "fact_preserve": grade_fact_preserve,
    "section_coverage": grade_section_coverage,
    "citation_map": grade_citation_map,
    "absence_guard": grade_absence_guard,
}


def grade_item(item, draft, units_all=None):
    units_all = units_all or []
    fn = HANDLERS.get(item.get("task_type"))
    if fn is None:
        return _ungradable(item, "未知题型，无法评分")
    if not item.get("gold"):
        return _ungradable(item, "题卡缺金标准，不能打分")
    return fn(item, draft, units_all)


def summarize(records, items, condition="extractive_writer"):
    graded = [r for r in records if r.get("gradable")]
    skipped = [r for r in records if not r.get("gradable")]
    n = len(graded)
    total = sum(r["score"] for r in graded)
    cmax = 2 * n

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
            b["normalized"] = round(b["total"] / float(2 * b["n"]), 4)
        return out

    failures = {}
    for r in records:
        if r.get("failure_type"):
            failures[r["failure_type"]] = failures.get(r["failure_type"], 0) + 1
    return {
        "condition": condition,
        "items_total": len(items),
        "items_graded": n,
        "items_skipped": len(skipped),
        "total_score": total,
        "max_score": cmax,
        "normalized_score": round(total / float(cmax), 4) if cmax else 0.0,
        "strict_accuracy": round(sum(1 for r in graded if r["score"] == 2) / float(n), 4)
        if n else 0.0,
        "distribution": {str(s): sum(1 for r in graded if r["score"] == s)
                         for s in (0, 1, 2)},
        "by_task_type": bucket(lambda r: r.get("task_type")),
        "failure_counts": failures,
        "failures": [{"item_id": r["item_id"], "task_type": r.get("task_type"),
                      "failure_type": r.get("failure_type"), "score": r["score"],
                      "rationale": r["rationale"]} for r in records if r["score"] < 2],
        "skipped": [{"item_id": r["item_id"], "rationale": r["rationale"]}
                    for r in skipped],
    }


def perfect_draft(items):
    """A draft built from item gold only, used to prove the rubric is not degenerate."""
    parts = []
    for it in items:
        t = it.get("task_type")
        gold = it.get("gold") or {}
        if t == "fact_preserve":
            parts.append(" ".join(n["raw"] for n in gold.get("numbers") or []))
            for cond in gold.get("conditions") or []:
                parts.append(cond)
            parts.append("[src: %s]" % gold.get("must_cite_unit"))
        elif t == "section_coverage":
            for sec in gold.get("required_sections") or []:
                unit = (gold.get("allowed_units") or ["u"])[0]
                parts.append("## %s\nEvidence sentence for %s. [src: %s]" % (sec, sec, unit))
        elif t == "citation_map":
            for claim in gold.get("claims") or []:
                quote = (it.get("evidence") or [{}])[0].get("quote", "")
                parts.append("%s [src: %s]" % (quote, claim["unit_id"]))
        elif t == "absence_guard":
            parts.append("The source does not report %s. [src: %s]"
                         % (gold.get("absent_topic"), gold.get("unit_id")))
    return "\n\n".join(parts)


def rubric_self_check(items, units_all=None):
    draft = perfect_draft(items)
    rows, ok = [], True
    for it in items:
        good = grade_item(it, draft, units_all)
        empty = grade_item(it, "", units_all)
        checks = {"perfect_scores_2": good["score"] == 2,
                  "empty_scores_0": empty["score"] == 0}
        ok = ok and all(checks.values())
        rows.append({"item_id": it["item_id"], "task_type": it["task_type"],
                     "checks": checks, "perfect_score": good["score"],
                     "perfect_rationale": good["rationale"],
                     "empty_failure": empty["failure_type"]})
    return {"pass": ok, "items": rows,
            "note": "评分器自检：仅由金标准构造的完美稿应得 2；空稿应得 0。"}
