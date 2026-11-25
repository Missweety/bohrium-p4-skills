#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""revise.py -- 选择"该自动改的"，只改命中处，并产出可复核修订稿。

自动修改边界（宁少不多）：
    1. 拉丁术语变体 -> 出现最多且带大写的规范写法（排版级；不允许把小写当规范去改专名）
    2. 运行时 workorder 显式给定的 术语 -> 目标术语（任务要求）
其余（符号多义、缩写不同全称、结论相反、编号重排、引用缺失）只报不改。

每条 edit 记 before/after/段落/规则/依据/置信度；落盘后重新打开 docx 复核：
    * 该段 after 出现；
    * 未命中段落逐字未变；
    * 段落总数未变、zip 与 XML 可解析。
"""
from __future__ import annotations

import difflib
import re

import docx_io


def _occurrences(text, needle, word_boundary=False):
    if not needle:
        return []
    if word_boundary:
        pat = re.compile(r"(?<![A-Za-z0-9_\-])%s(?![A-Za-z0-9_\-])" % re.escape(needle))
        return [(m.start(), m.end()) for m in pat.finditer(text)]
    out, start = [], 0
    while True:
        i = text.find(needle, start)
        if i < 0:
            return out
        out.append((i, i + len(needle)))
        start = i + len(needle)


def plan_edits(findings):
    by_para, dropped, seen = {}, [], set()
    for f in findings:
        if not f.get("auto_fixable"):
            continue
        pid = (f.get("location") or {}).get("paragraph_id")
        if not pid:
            continue
        if f["rule"] == "terminology.latin_variant":
            canonical = f.get("canonical")
            variants = [x for x in (f.get("variants") or []) if x != canonical]
            boundary = True
        elif f["rule"] == "terminology.workorder_term":
            canonical = f.get("canonical")
            variants = [x for x in (f.get("variants") or []) if x and x != canonical]
            boundary = False
        else:
            continue
        for v in variants:
            key = (pid, v, canonical)
            if key in seen:
                # 同一段落同一替换被多条规则/指令命中时只执行一次，但仍如实记录
                dropped.append({"finding_id": f["id"], "paragraph_id": pid,
                                "needle": v, "reason": "与更早命中的替换重复（同段同词同目标）"})
                continue
            seen.add(key)
            by_para.setdefault(pid, []).append(
                {"needle": v, "new": canonical, "finding_id": f["id"],
                 "rule": f["rule"], "basis": f.get("why", ""), "boundary": boundary})
    return by_para, dropped


def apply_edits(doc, findings):
    by_para, dropped = plan_edits(findings)
    para_by_id = {p["id"]: p for p in doc["paragraphs"]}
    edits, skipped, touched = [], [], 0
    for pid, items in by_para.items():
        p = para_by_id.get(pid)
        if p is None:
            skipped.append({"finding_id": items[0]["finding_id"], "reason": "段落 %s 不存在" % pid})
            continue
        original = p["text"]
        reps, meta, taken = [], [], []
        for it in items:
            for (s, e) in _occurrences(original, it["needle"], it["boundary"]):
                if any(not (e <= a or s >= b) for a, b in taken):
                    continue
                reps.append((s, e, it["new"]))
                taken.append((s, e))
                meta.append((s, e, it))
        if not reps:
            for it in items:
                skipped.append({"finding_id": it["finding_id"],
                                "reason": "段落 %s 内未逐字命中 “%s”" % (pid, it["needle"])})
            continue
        seg_applied = docx_io.patch_paragraph(p, reps)
        for s, e, it in meta:
            a, b = max(0, s - 12), min(len(original), e + 12)
            edits.append({
                "edit_id": "E%03d" % (len(edits) + 1),
                "finding_id": it["finding_id"], "rule": it["rule"],
                "paragraph_id": pid, "section": p.get("section"),
                "source_path": p.get("source_path"),
                "char_start": s, "char_end": e,
                "before": original[s:e], "after": it["new"],
                "context_before": original[a:s] + "[" + original[s:e] + "]" + original[e:b],
                "context_after": original[a:s] + "[" + it["new"] + "]" + original[e:b],
                "basis": it["basis"], "confidence": "high",
                "segments_written": seg_applied,
            })
        touched += 1
    return {"edits": edits, "skipped": skipped, "deduped": dropped,
            "paragraphs_touched": touched}


def _in_scope(p, scope):
    pid = scope.get("paragraph_id") or scope.get("para_id") or scope.get("paragraph")
    if pid:
        return p["id"].lower() == str(pid).lower()
    if scope.get("section"):
        return (p.get("section") or "") == scope["section"]
    if scope.get("chapter"):
        want = scope["chapter"]
        sec = (p.get("section") or "").split(".")[0].lstrip("§")
        return sec == want
    if scope.get("file"):
        return (p.get("source_path") or "").split("/")[-1] == str(scope["file"]).split("/")[-1]
    return True


def apply_target_edits(doc, targets):
    """机械执行 workorder 中 find/replace 形式的显式改稿目标。

    逐条回报 applied / not_found，applied 时给出段落、章节、出现次数；
    找不到就如实记 not_found，不做模糊匹配、不改写原意。
    """
    edits, report, skipped = [], [], []
    for i, t in enumerate(targets, start=1):
        tid = "W%03d" % i
        scope = t.get("scope") or {}
        cands = [p for p in doc["paragraphs"] if not p.get("in_table")]
        if scope:
            cands = [p for p in cands if _in_scope(p, scope)]
        hits = [(p, _occurrences(p["text"], t["find"])) for p in cands]
        hits = [(p, occ) for p, occ in hits if occ]
        if not hits:
            report.append({"target_id": tid, "find": t["find"], "replace": t["replace"],
                           "status": "not_found", "reason": t.get("reason", ""),
                           "scope": scope or {}, "searched_paragraphs": len(cands)})
            skipped.append({"target_id": tid, "needle": t["find"],
                            "reason": "工单目标在检索范围内未逐字命中"})
            continue
        paragraphs = []
        for p, occ in hits:
            original = p["text"]
            reps = [(s, e, t["replace"]) for s, e in occ]
            seg_applied = docx_io.patch_paragraph(p, reps)
            for s, e in occ:
                a, b = max(0, s - 12), min(len(original), e + 12)
                edits.append({
                    "edit_id": "E%03d" % (len(edits) + 1),
                    "target_id": tid, "finding_id": None, "rule": "workorder.target",
                    "paragraph_id": p["id"], "section": p.get("section"),
                    "source_path": p.get("source_path"),
                    "char_start": s, "char_end": e,
                    "before": original[s:e], "after": t["replace"],
                    "context_before": original[a:s] + "[" + original[s:e] + "]" + original[e:b],
                    "context_after": original[a:s] + "[" + t["replace"] + "]" + original[e:b],
                    "basis": t.get("reason") or "工单显式指定", "confidence": "high",
                    "segments_written": seg_applied,
                })
            paragraphs.append({"paragraph_id": p["id"], "section": p.get("section"),
                               "source_path": p.get("source_path"),
                               "occurrences": len(occ)})
        report.append({"target_id": tid, "find": t["find"], "replace": t["replace"],
                       "status": "applied", "reason": t.get("reason", ""),
                       "scope": scope or {}, "paragraphs": paragraphs,
                       "occurrences": sum(x["occurrences"] for x in paragraphs)})
    return {"edits": edits, "skipped": skipped, "report": report}


def edit_impact(doc, edits, limit=30):
    """改一处后，同一旧写法还出现在哪些段落（供作者继续跟进）。"""
    out = []
    for e in edits:
        for p in doc["paragraphs"]:
            if p["id"] == e["paragraph_id"] or p.get("in_table"):
                continue
            if e["before"] and e["before"] in p["text"]:
                out.append({"edit_id": e["edit_id"], "paragraph_id": p["id"],
                            "section": p.get("section"),
                            "source_path": p.get("source_path"),
                            "excerpt": p["text"][:60]})
                if len(out) >= limit:
                    return out
    return out


def verify(before_texts, out_path, edits):
    """重新打开产物做独立复核。"""
    texts, ok, err = docx_io.docx_text(out_path)
    info = docx_io.docx_info(out_path)
    checks, errors = {}, []
    checks["openable"] = bool(ok and info["ok"])
    if not ok:
        errors.append("产物无法复读: %s" % err)
    checks["paragraph_count_preserved"] = len(texts) == len(before_texts)
    if not checks["paragraph_count_preserved"]:
        errors.append("段落数变化: %d -> %d" % (len(before_texts), len(texts)))

    touched_ids = {e["paragraph_id"] for e in edits}
    mismatch, unchanged = [], 0
    for idx, txt in enumerate(before_texts):
        pid = "P%04d" % (idx + 1)
        if pid in touched_ids:
            continue
        unchanged += 1
        if idx < len(texts) and texts[idx] != txt:
            mismatch.append({"paragraph_id": pid, "before": txt[:80], "after": texts[idx][:80]})
    checks["untouched_paragraphs_identical"] = not mismatch
    checks["untouched_count"] = unchanged
    if mismatch:
        errors.append("非目标段落被改动: %s" % mismatch[:3])

    bad = []
    for e in edits:
        idx = int(e["paragraph_id"][1:]) - 1
        if idx >= len(texts) or e["after"] not in texts[idx]:
            bad.append({"paragraph_id": e["paragraph_id"], "after": e["after"]})
    checks["edits_present_in_output"] = not bad
    if bad:
        errors.append("编辑未落到产物: %s" % bad[:3])
    return {"ok": not errors, "checks": checks, "errors": errors}


def render_markdown_from_doc(doc, title=None):
    out = []
    if title:
        out += ["# " + title, ""]
    for p in doc["paragraphs"]:
        if p.get("in_table"):
            continue
        text = p["text"].strip()
        if not text:
            continue
        lvl = p.get("heading_level") or 0
        out.append(("#" * min(6, lvl) + " " + text) if lvl else text)
        out.append("")
    for t in doc.get("tables", []):
        if not t["rows"]:
            continue
        out.append("| " + " | ".join(str(c).replace("\n", " ") for c in t["rows"][0]) + " |")
        out.append("|" + "---|" * len(t["rows"][0]))
        for row in t["rows"][1:]:
            cells = [str(c).replace("\n", " ") for c in row]
            cells += [""] * (len(t["rows"][0]) - len(cells))
            out.append("| " + " | ".join(cells) + " |")
        out.append("")
    return "\n".join(out).strip() + "\n"


def unified_diff(before_texts, after_texts, name="document"):
    a = "\n".join(before_texts).splitlines(keepends=True)
    b = "\n".join(after_texts).splitlines(keepends=True)
    return "".join(difflib.unified_diff(a, b, fromfile=name + ".orig", tofile=name + ".revised"))
