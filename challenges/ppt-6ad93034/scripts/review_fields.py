#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""review_fields.py - 把「人工/模型语义复核」的判定写回 result.json（纯标准库）。

分工：
    field_extract.py  词面检索 → 给出候选（needs_review=true）
    **你（Agent）**   读候选原文，判断该句是否真的在报告这个字段
    review_fields.py  把你的判定确定性地写回结果并复跑审计

之所以要有这一步：题面铁律「字面引文命中不等于语义正确」。词面检索能保证
引文逐字来自原文，但「这句在讲这个字段」需要语义判断。本脚本不替你判断，
只负责把你已经做出的判断落到文件里，并保证：
    * 引文必须逐字出现在锚点页，否则拒绝写入（防止编造引文）
    * not_reported / source_conflict 时 value 必须为空（防止用 0 充数）
    * 写回后把 needs_review 置为 false，并在 change_log 追加一条

判定文件格式（JSON）：

    {
      "fields": {
        "f_bleu": {
          "status": "reported",
          "value": "34.81",
          "unit": "",
          "statistic": "BLEU",
          "experimental_condition": "WMT'14 English to French, LSTM 80k vocab",
          "comparator": null,
          "paragraph_id": "p.5/sec.11/sent.3",
          "quote": "<必须逐字取自原文>"
        },
        "f_human_eval": {"status": "not_reported"},
        "f_x": {"status": "source_conflict",
                "conflicts": [{"paragraph_id": "...", "quote": "..."},
                              {"paragraph_id": "...", "quote": "..."}]}
      }
    }

用法：
    python3 scripts/review_fields.py --result /app/output/result.json \
        --verdicts /app/work/verdicts.json --doc /app/work/doc.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

VALID_STATUS = ("reported", "not_reported", "source_conflict", "extraction_failed")
ANCHOR_RE = re.compile(r"p\.(\d+)")


def _norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def _doc_pages(doc):
    pages = {}
    if not isinstance(doc, dict):
        return pages, {}
    full = doc.get("text", "")
    if isinstance(full, str) and full:
        for i, chunk in enumerate(full.split("\f"), 1):
            pages[i] = _norm(chunk)
    sections = {}
    for u in doc.get("units", []) or []:
        if u.get("id"):
            sections[u["id"]] = _norm(u.get("text", ""))
    return pages, sections


_TYPO_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
}


def _canon(text):
    """排版归一：统一弯引号/破折号，去掉 PDF 换行断词连字符。"""
    s = (text or "")
    for k, v in _TYPO_MAP.items():
        s = s.replace(k, v)
    s = re.sub(r"-\s+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _quote_matches(quote, text):
    q = _canon(quote)
    t = _canon(text)
    if len(q) < 12:
        return True
    if q in t:
        return True
    # PDF 换行断词：文档里 "beam-\nsearch" 归一后是 "beamsearch"，
    # 而引文写的是 "beam search"。再比一次「去掉全部空白」的形态。
    qc = re.sub(r"\s+", "", q)
    tc = re.sub(r"\s+", "", t)
    return len(qc) >= 12 and qc in tc


def _quote_on_page(pages, sections, anchor, quote):
    """引文是否逐字出现在锚点页（或锚点章节单元）内。"""
    if not anchor or not quote:
        return None
    m = ANCHOR_RE.search(anchor)
    if m:
        pno = int(m.group(1))
        page_text = pages.get(pno)
        if page_text is not None:
            if _quote_matches(quote, page_text):
                return True
    ms = re.search(r"sec\.(\d+)", anchor or "")
    if ms:
        unit = sections.get("sec.%s" % ms.group(1))
        if unit:
            return _quote_matches(quote, unit)
    return False


def _find_field_rows(result, prefix=""):
    """在 result.json 里递归找到所有字段结果列表。

    同一批字段可能同时出现在顶层 fields 与嵌套槽位（例如 parsed.fields），
    复核判定必须落到每一份拷贝上，否则会出现「改了一半」的残留。
    """
    out = []
    if isinstance(result, dict):
        for key, val in result.items():
            out.extend(_find_field_rows(val, prefix + "/" + str(key)))
    elif isinstance(result, list):
        if result and isinstance(result[0], dict) and "field_id" in result[0]:
            out.append((prefix, result))
        else:
            for i, val in enumerate(result):
                out.extend(_find_field_rows(val, prefix + "[%d]" % i))
    return out


def apply_verdicts(result, verdicts, doc):
    """把判定写回 result.json，返回 (applied, rejected, notes)。"""
    pages, sections = _doc_pages(doc)
    applied, rejected, notes = [], [], []
    vfields = verdicts.get("fields") if isinstance(verdicts, dict) else None
    if not isinstance(vfields, dict):
        return applied, rejected, ["verdicts 文件缺少 fields 对象"]

    rows_by_id = {}
    for _key, rows in _find_field_rows(result):
        for row in rows:
            fid = row.get("field_id")
            if fid:
                rows_by_id.setdefault(fid, []).append(row)

    for fid, verdict in vfields.items():
        target_rows = rows_by_id.get(fid)
        if not target_rows:
            rejected.append({"field_id": fid, "reason": "result.json 中没有该 field_id"})
            continue
        if not isinstance(verdict, dict):
            rejected.append({"field_id": fid, "reason": "判定不是对象"})
            continue
        status = verdict.get("status")
        if status not in VALID_STATUS:
            rejected.append({"field_id": fid, "reason": "status 非法: %r" % status})
            continue

        if status == "reported":
            quote = verdict.get("quote") or ""
            anchor = verdict.get("paragraph_id") or ""
            if not quote or not anchor:
                rejected.append({"field_id": fid, "reason": "reported 必须给 quote 与 paragraph_id"})
                continue
            ok = _quote_on_page(pages, sections, anchor, quote)
            if ok is False:
                rejected.append({"field_id": fid,
                                "reason": "引文未在锚点页逐字命中，拒绝写入"})
                continue
        elif status == "not_reported":
            if verdict.get("value") not in (None, "", []):
                rejected.append({"field_id": fid,
                                "reason": "not_reported 不得带 value（缺失不等于 0）"})
                continue
        elif status == "source_conflict":
            if len(verdict.get("conflicts") or []) < 2:
                rejected.append({"field_id": fid, "reason": "source_conflict 至少给两处冲突"})
                continue

        for row in target_rows:
            if status == "reported":
                row["status"] = "reported"
                row["quote"] = verdict.get("quote")
                row["paragraph_id"] = verdict.get("paragraph_id")
                row["value"] = verdict.get("value")
                row["unit"] = verdict.get("unit", "")
                row["statistic"] = verdict.get("statistic")
                row["experimental_condition"] = verdict.get("experimental_condition")
                row["comparator"] = verdict.get("comparator")
                row.pop("conflicts", None)
            elif status == "not_reported":
                row["status"] = "not_reported"
                row["value"] = None
                row["unit"] = None
                row["quote"] = None
                row["paragraph_id"] = None
                row.pop("conflicts", None)
            elif status == "source_conflict":
                row["status"] = "source_conflict"
                row["value"] = None
                row["unit"] = None
                row["quote"] = None
                row["paragraph_id"] = None
                row["conflicts"] = verdict.get("conflicts")
            else:  # extraction_failed
                row["status"] = "extraction_failed"
                row["value"] = None
                row["unit"] = None
                row["quote"] = None
                row["paragraph_id"] = None
                row.pop("conflicts", None)
            row["needs_review"] = False
            if verdict.get("note"):
                row["note"] = verdict["note"]
        applied.append(fid)

    # 同步：结果里另有一份 evidence 清单（每条带 field_id），
    # 它的引文/锚点必须跟着字段行一起更新，否则两份引用会互相矛盾。
    row_map = {}
    for _key, rows in _find_field_rows(result):
        for row in rows:
            fid = row.get("field_id")
            if fid and fid not in row_map:
                row_map[fid] = row

    def _sync(node):
        if isinstance(node, dict):
            fid = node.get("field_id")
            src = row_map.get(fid)
            if src is not None and src is not node:
                if "quote" in node or "anchor" in node:
                    node["quote"] = src.get("quote")
                    if "anchor" in node:
                        node["anchor"] = src.get("paragraph_id")
                if "status" in node:
                    node["status"] = src.get("status")
            for v in node.values():
                _sync(v)
        elif isinstance(node, list):
            for v in node:
                _sync(v)

    _sync(result)

    # 复核完成后重算运行状态：全部字段已复核且无抽取失败 → success；
    # 仍有未复核字段或抽取失败 → partial。
    rows_all = []
    for _key, rows in _find_field_rows(result):
        for row in rows:
            if row.get("field_id"):
                rows_all.append(row)
    if rows_all:
        pending_n = len([r for r in rows_all if r.get("needs_review") is True])
        failed_n = len([r for r in rows_all if r.get("status") == "extraction_failed"])
        if pending_n or failed_n:
            result["status"] = "partial"
        else:
            result["status"] = "success"

    # 仍未复核的字段保持 needs_review=true，并进 unresolved
    unresolved = []
    for _key, rows in _find_field_rows(result):
        for row in rows:
            if row.get("needs_review") is True and row.get("field_id") not in unresolved:
                unresolved.append(row.get("field_id"))
    unc = result.get("uncertainty")
    if isinstance(unc, dict):
        cur = list(unc.get("unresolved", []) or [])
        for u in unresolved:
            if u not in cur:
                cur.append(u)
        unc["unresolved"] = cur
        if unresolved:
            notes.append("仍有 %d 个字段未语义复核：%s"
                         % (len(unresolved), ", ".join(str(u) for u in unresolved)))
    return applied, rejected, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description="把语义复核判定写回 result.json")
    ap.add_argument("--result", required=True)
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--doc")
    ap.add_argument("--case", help="case.json，用于契约字段核对")
    ap.add_argument("--out", help="写回目标，默认原地覆盖")
    ap.add_argument("--audit-out", help="复核报告输出路径")
    ap.add_argument("--no-audit", action="store_true")
    args = ap.parse_args(argv)

    with open(args.result, "r", encoding="utf-8") as fh:
        result = json.load(fh)
    with open(args.verdicts, "r", encoding="utf-8") as fh:
        verdicts = json.load(fh)
    doc = {}
    if args.doc and os.path.isfile(args.doc):
        with open(args.doc, "r", encoding="utf-8") as fh:
            doc = json.load(fh)

    applied, rejected, notes = apply_verdicts(result, verdicts, doc)

    log = result.get("change_log")
    if not isinstance(log, list):
        log = []
    log.append("按语义复核判定回写 %d 个字段（%s）；已逐条核对引文在锚点页逐字命中"
               % (len(applied), ", ".join(applied) if applied else "无"))
    result["change_log"] = log

    out_path = args.out or args.result
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    if not args.no_audit:
        import subprocess
        cmd = [sys.executable, os.path.join(HERE, "audit_result.py"),
               "--result", out_path]
        if args.doc:
            cmd += ["--doc", args.doc]
        if args.case:
            cmd += ["--case", args.case]
        if args.audit_out:
            cmd += ["--out", args.audit_out]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(p.stdout.decode("utf-8", "replace")[-4000:])

    print("applied=%d rejected=%d" % (len(applied), len(rejected)))
    for r in rejected:
        print("  REJECTED %s: %s" % (r["field_id"], r["reason"]))
    for n in notes:
        print("  NOTE %s" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
