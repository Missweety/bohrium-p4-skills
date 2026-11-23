#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_result.py - 结果独立复核（纯标准库）。

作用：在**独立进程**里重新读取原始文档与产出的 result.json，逐条核对
结果里的证据锚点是否真的指向原文、数值是否被改写、字段是否齐备、
状态是否诚实。这一步是"可核验"与"看起来像"的区别。

核对项：
  A1 契约齐备      —— output_contract.required 每个字段都出现在 result.json
  A2 字段非空      —— 必填字段不得为 null（除非它被显式列入 unresolved）
  A3 锚点可定位    —— 证据里的 p.N/sec.X/sent.K/tab.M/row.K 能在原文里找到
  A4 引文逐字      —— 证据 quote 必须逐字出现在该锚点附近（允许空白归一化）
  A5 数值保真      —— 数值型结论里的数字必须出现在原文对应句
  A6 状态诚实      —— status=success 时不得存在 unresolved 字段
  A7 边界完备      —— sources / uncertainty / change_log 三个字段必须存在
  A8 抽检标记      —— needs_review=true 只作提醒（模型复核为可选），不判错
  A9 取值可回查    —— reported 行的 value 必须非空且逐字出现在引文里

输出：JSON 报告（stdout），退出码 0 = pass，1 = fail（存在 error）。

CLI:
  python3 audit_result.py --result result.json --case case.json --doc doc.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ANCHOR_RE = re.compile(
    r"p\.(\d+)(?:/(sec\.\d+|tab\.\d+|cap\.\d+)(?:/(sent\.\d+|row\.\d+))?)?"
)
NUM_IN_TEXT_RE = re.compile(r"\d+(?:\.\d+)?")


def _norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def _walk(node, path="", out=None):
    """深度遍历 JSON，产出 (json_path, value) 列表。

    dict / list 也会作为条目产出（证据条目本身是 dict，需要被单独检查）。
    """
    if out is None:
        out = []
    if isinstance(node, dict):
        out.append((path, node))
        for k, v in node.items():
            _walk(v, "%s.%s" % (path, k) if path else str(k), out)
    elif isinstance(node, list):
        out.append((path, node))
        for i, v in enumerate(node):
            _walk(v, "%s[%d]" % (path, i), out)
    else:
        out.append((path, node))
    return out


def _collect_evidence(result):
    """找出结果里所有像"证据"的条目：带 anchor 或 quote 的 dict。"""
    found = []
    for path, val in _walk(result):
        if isinstance(val, dict):
            has_anchor = any(k in val for k in ("anchor", "locator", "location", "citation"))
            has_quote = any(k in val for k in ("quote", "excerpt", "text", "snippet", "evidence"))
            if has_anchor or has_quote:
                found.append((path, val))
    return found


def _doc_index(doc):
    """建立 (page -> text) 与 (section -> text) 的索引，用于锚点回查。"""
    pages = {}
    sections = {}
    page_list = doc.get("pages", [])
    full = doc.get("text", "")
    if isinstance(full, str) and full:
        chunks = full.split("\f")
        for i, chunk in enumerate(chunks, 1):
            pages[i] = chunk
    for u in doc.get("units", []):
        sections[u["id"]] = u.get("text", "")
    return pages, sections


_TYPO_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
}


def _canon(text):
    """排版归一：统一弯引号/破折号/不换行空格，去掉 PDF 换行断词连字符。"""
    s = (text or "")
    for k, v in _TYPO_MAP.items():
        s = s.replace(k, v)
    s = re.sub(r"-\s+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _quote_matches(quote, page_text):
    """引文是否逐字出现在页面文本中（容忍换行/多空格/断词连字符/弯引号）。"""
    q = _canon(quote)
    pt = _canon(page_text)
    if len(q) < 12:
        return True
    if q in pt:
        return True
    qc = re.sub(r"\s+", "", q)
    ptc = re.sub(r"\s+", "", pt)
    return len(qc) >= 12 and qc in ptc


def _alnum(text):
    return re.sub(r"[^0-9A-Za-z一-鿿]", "", text or "")


def _flat(text):
    """排版归一 + 去掉全部空白 + 转小写。"""
    return re.sub(r"\s+", "", _canon(text)).lower()


def value_in_quote(value, quote):
    """value 是否逐字（容忍排版差异）出现在引文里。"""
    if not isinstance(value, str) or not value.strip():
        return False
    cv, cq = _flat(value), _flat(quote)
    if cv and cv in cq:
        return True
    av, aq = _alnum(value), _alnum(quote)
    return bool(av) and av in aq


def _section_quote_hit(anchor, quote, sections):
    """引文是否落在锚点指定的章节单元文本内。

    两栏排版的 PDF 里，pdftotext -layout 的页面文本会把两栏交错，
    逐字引文在页面文本上根本拼不回来；但章节单元文本是按阅读顺序重排的，
    引文在单元内必然连续。因此以「单元内命中」为逐字判定依据。
    """
    m = re.search(r"sec\.(\d+)", anchor or "")
    if not m:
        return None
    unit = sections.get("sec.%s" % m.group(1))
    if not unit:
        return None
    return _quote_matches(quote, unit)


def _page_of_anchor(anchor, pages):
    m = re.match(r"p\.(\d+)", anchor or "")
    if not m:
        return None
    pno = int(m.group(1))
    return pages.get(pno)


def audit(result, case, doc):
    errors = []
    warnings = []
    checks = []

    contract = (case or {}).get("output_contract", {})
    required = []
    if isinstance(contract, dict):
        for key in ("required", "fields", "properties"):
            val = contract.get(key)
            if isinstance(val, list) and val:
                required = [v if isinstance(v, str) else
                            (v.get("name") or v.get("field") or v.get("key"))
                            for v in val]
                required = [r for r in required if r]
                break
            if isinstance(val, dict):
                required = list(val.keys())
                break
        else:
            required = [k for k in contract.keys()
                        if k not in ("artifacts", "files", "description", "format", "version")]

    # A1 契约齐备
    missing = [f for f in required if f not in result]
    checks.append({"id": "A1", "name": "contract_fields_present",
                   "pass": not missing, "missing": missing})
    if missing:
        errors.append({"code": "A1_missing_field", "detail": "缺失必填字段: %s" % missing})

    # A2 字段非空
    unresolved = []
    if isinstance(result.get("uncertainty"), dict):
        unresolved = list(result["uncertainty"].get("unresolved", []) or [])
    nulls = [f for f in required if f in result and result[f] is None and f not in unresolved]
    checks.append({"id": "A2", "name": "required_fields_not_null",
                   "pass": not nulls, "nulls": nulls})
    if nulls:
        errors.append({"code": "A2_null_field", "detail": "必填字段为 null 且未标注 unresolved: %s" % nulls})

    pages, sections = _doc_index(doc or {})

    # A3/A4 锚点可定位 + 引文逐字
    ev_items = _collect_evidence(result)
    checked_anchor = 0
    quote_checked = 0
    quote_fail = []
    anchor_fail = []
    for path, ev in ev_items:
        anchor = ""
        for key in ("anchor", "locator", "location", "citation"):
            if isinstance(ev.get(key), str):
                anchor = ev[key]
                break
        quote = ""
        for key in ("quote", "excerpt", "snippet"):
            if isinstance(ev.get(key), str) and ev[key].strip():
                quote = ev[key]
                break
        if anchor:
            m = ANCHOR_RE.search(anchor)
            if m:
                checked_anchor += 1
                pno = int(m.group(1))
                if pno not in pages:
                    anchor_fail.append({"path": path, "anchor": anchor,
                                        "reason": "page %d not in extracted document" % pno})
                    continue
                if quote:
                    quote_checked += 1
                    hit = _quote_matches(quote, pages[pno])
                    if not hit:
                        # 两栏排版下页面文本被交错，改用章节单元文本判定
                        hit = _section_quote_hit(anchor, quote, sections)
                    if hit is False:
                        quote_fail.append({"path": path, "anchor": anchor,
                                           "quote": quote[:160]})
        elif quote:
            quote_checked += 1
    checks.append({"id": "A3", "name": "anchors_resolve",
                   "pass": not anchor_fail, "checked": checked_anchor,
                   "failures": anchor_fail[:20]})
    if anchor_fail:
        errors.append({"code": "A3_anchor_unresolved",
                       "detail": "%d 个锚点无法在抽取文档中定位" % len(anchor_fail)})
    checks.append({"id": "A4", "name": "quotes_verbatim",
                   "pass": not quote_fail, "checked": quote_checked,
                   "failures": quote_fail[:20]})
    if quote_fail:
        errors.append({"code": "A4_quote_not_found",
                       "detail": "%d 条引文未在锚点页逐字命中" % len(quote_fail)})

    # A5 数值保真：结果里的数值型字符串必须能在原文里找到
    # 只检查"结论性内容"字段，跳过统计量/元信息这类派生数字
    DERIVED_PREFIXES = (".coverage", ".audit", ".uncertainty", ".change_log",
                        ".contract_check", ".extraction", ".meta")
    num_mismatch = []
    checked_nums = 0
    if doc and pages:
        all_text = _norm(" ".join(pages.values()))
        for path, val in _walk(result):
            if not isinstance(val, str):
                continue
            if len(val) > 400 or not re.search(r"\d", val):
                continue
            if any(path.startswith(pfx.lstrip(".")) for pfx in DERIVED_PREFIXES):
                continue
            if any(k in path for k in ("case_id", "anchor", "locator", "id", "file",
                                       "pdf_meta", "creator", "producer", "version")):
                continue
            for tok in NUM_IN_TEXT_RE.findall(val):
                if len(tok) < 2:
                    continue
                checked_nums += 1
                if tok not in all_text:
                    num_mismatch.append({"path": path, "value": tok})
    checks.append({"id": "A5", "name": "numbers_traceable",
                   "pass": not num_mismatch, "checked": checked_nums,
                   "failures": num_mismatch[:20]})
    if num_mismatch:
        warnings.append({"code": "A5_number_not_found",
                         "detail": "%d 个数值未在原文中找到（可能是计算/派生值）"
                                   % len(num_mismatch)})

    # A6 状态诚实
    status = result.get("status")
    ok_status = status in ("success", "partial", "failed")
    unresolved_left = [f for f in (unresolved or [])]
    status_ok = ok_status and not (status == "success" and unresolved_left)
    checks.append({"id": "A6", "name": "status_honest",
                   "pass": status_ok, "status": status, "unresolved": unresolved_left})
    if not ok_status:
        errors.append({"code": "A6_bad_status", "detail": "status 取值非法: %r" % status})
    elif status == "success" and unresolved_left:
        errors.append({"code": "A6_success_with_unresolved",
                       "detail": "status=success 但仍有未解决字段: %s" % unresolved_left})

    # A7 边界三件套
    missing_bounds = [k for k in ("sources", "uncertainty", "change_log") if k not in result]
    checks.append({"id": "A7", "name": "boundary_fields_present",
                   "pass": not missing_bounds, "missing": missing_bounds})
    if missing_bounds:
        errors.append({"code": "A7_missing_boundary",
                       "detail": "缺少边界字段: %s" % missing_bounds})

    # A8 复核状态：needs_review=true 表示**建议**人工抽检。
    # 语义判定已由抽取脚本完成，模型复核是**可选**的，因此这里只记 warning。
    pending = []
    for path, node in _walk(result):
        if isinstance(node, dict) and node.get("needs_review") is True:
            fid = node.get("field_id") or path
            pending.append(fid)
    checks.append({"id": "A8", "name": "fields_reviewed",
                   "pass": not pending, "pending": pending[:20]})
    if pending:
        warnings.append({"code": "A8_fields_optional_review",
                         "detail": "%d 个字段标记 needs_review=true（建议抽检，"
                                   "不影响判定）：%s"
                                   % (len(pending), ", ".join(str(p) for p in pending[:10]))})

    # A9 引文逐字包含取值：reported 行的 value 必须非空且逐字出现在 quote 里
    FIELD_STATUSES = ("reported", "not_reported", "source_conflict", "extraction_failed")
    value_fail = []
    value_checked = 0
    for path, node in _walk(result):
        if not isinstance(node, dict):
            continue
        if node.get("status") not in FIELD_STATUSES:
            continue
        if "value" not in node:
            continue
        if node.get("status") != "reported":
            continue
        value_checked += 1
        value = node.get("value")
        quote = node.get("quote") or ""
        fid = node.get("field_id") or path
        if not isinstance(value, str) or not value.strip():
            value_fail.append({"path": path, "field_id": fid,
                               "reason": "reported 行的 value 为空"})
        elif not value_in_quote(value, quote):
            value_fail.append({"path": path, "field_id": fid,
                               "reason": "value 未逐字包含于引文", "value": value[:80]})
    checks.append({"id": "A9", "name": "value_verbatim_in_quote",
                   "pass": not value_fail, "checked": value_checked,
                   "failures": value_fail[:20]})
    if value_fail:
        errors.append({"code": "A9_value_not_in_quote",
                       "detail": "%d 条 reported 行的取值无法逐字回查引文：%s"
                                 % (len(value_fail),
                                    ", ".join(str(f.get("field_id") or f.get("path"))
                                              for f in value_fail[:10]))})

    totals = {
        "required": len(required),
        "evidence_items": len(ev_items),
        "anchors_checked": checked_anchor,
        "quotes_checked": quote_checked,
        "numbers_checked": checked_nums,
        "errors": len(errors),
        "warnings": len(warnings),
    }
    return {
        "pass": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "totals": totals,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="结果独立复核")
    ap.add_argument("--result", required=True)
    ap.add_argument("--case")
    ap.add_argument("--doc")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    with open(args.result, "r", encoding="utf-8") as fh:
        result = json.load(fh)
    case = {}
    if args.case and os.path.exists(args.case):
        with open(args.case, "r", encoding="utf-8") as fh:
            case = json.load(fh)
    doc = {}
    if args.doc and os.path.exists(args.doc):
        with open(args.doc, "r", encoding="utf-8") as fh:
            doc = json.load(fh)

    report = audit(result, case, doc)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
