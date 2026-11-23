#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""contract_map.py - 输出契约解析与结果装配（纯标准库）。

赛题在运行时会给出 `case.json`，其中 `output_contract` 描述了本次评测
真正要求的字段。本模块做三件事：

  1. contract_fields(contract)  —— 从 case.output_contract 里解析出必填字段名
     （兼容 required / fields / properties / 顶层 key 四种写法）
  2. field_plan(contract, doc)   —— 为每个必填字段给出一个"取值建议"：
     用字段名与别名表匹配抽取结果里的候选值，避免凭空编造
  3. build_result(...)           —— 按契约装配最终 result.json，
     保证每个必填字段都出现（缺失时写诚实的占位，而不是省略）

设计原则：
  * 契约是数据驱动的。不同赛题的 output_contract 不同，本模块不做硬编码假设。
  * 任何字段都带上取值来源（anchor + 摘录），无法定位时写 null 并在
    uncertainty 里说明，不编造内容。
"""
from __future__ import annotations

import json
import re

# 元字段：不属于"内容契约"，不应被当成正文结果字段
META_KEYS = {
    "artifacts", "files", "description", "format", "version", "deliverables",
    "paths", "instructions", "outputs_dir", "required", "fields", "properties",
    "type", "title", "name", "schema", "example", "examples", "notes",
}

# 字段名 → 抽取结果的语义槽位。别名表越全，自动装配越准。
FIELD_ALIASES = {
    # 身份与状态
    "case_id": "case_id", "id": "case_id", "task_id": "case_id",
    "status": "status", "state": "status", "result_status": "status",
    "summary": "summary", "overview": "summary", "digest": "summary",
    # 解析结果
    "parsed": "parsed", "parsed_result": "parsed", "parse_result": "parsed",
    "extraction": "extraction", "extracted": "extracted",
    "entities": "entities", "entity_list": "entities",
    "relations": "relations", "relation_list": "relations",
    "events": "events", "timeline": "events",
    "questions": "questions", "qas": "questions", "qa_pairs": "questions",
    "answers": "answers", "responses": "answers",
    "fields": "fields", "field_values": "fields", "targets": "fields",
    "items": "items", "entries": "items", "records": "items", "list": "items",
    "results": "results", "findings": "results",
    "sections": "sections", "structure": "sections", "outline": "sections",
    "claims": "claims", "arguments": "claims",
    "key_results": "key_results", "key_findings": "key_results",
    "limitations": "limitations", "caveats": "limitations",
    "method": "method", "methods": "method", "approach": "method",
    "data": "data", "dataset": "data", "datasets": "data",
    "research_question": "research_question", "question": "research_question",
    "gap": "gap", "contribution": "contribution", "contributions": "contribution",
    "tables": "tables", "figures": "figures", "charts": "figures",
    "glossary": "glossary", "terms": "glossary",
    "notes": "notes", "note": "notes", "notes_md": "notes", "reading_notes": "notes",
    "markdown": "markdown", "document": "document", "content": "document",
    "paper": "paper", "metadata": "paper", "bibliography": "paper",
    "cover_letter": "cover_letter", "reply": "reply", "review": "review",
    "slides": "slides", "deck": "slides", "outline_slides": "slides",
    "agenda": "agenda", "schedule": "agenda",
    # 证据与边界
    "evidence": "evidence", "citations": "evidence", "sources": "sources",
    "quotes": "evidence", "anchors": "evidence",
    "coverage": "coverage", "completeness": "coverage",
    "not_reported": "not_reported", "missing": "not_reported",
    "unreadable": "unreadable", "conflicts": "conflicts",
    "uncertainty": "uncertainty", "confidence": "uncertainty",
    "limitations_of_analysis": "uncertainty",
    "change_log": "change_log", "changes": "change_log", "versions": "change_log",
    "audit": "audit", "verification": "audit", "audit_result": "audit",
    "contract_check": "contract_check",
    "risks": "risks", "risk": "risks", "issues": "risks",
    "recommendations": "recommendations", "next_steps": "recommendations",
}

# 列表型槽位：取不到值时补空列表（诚实的「本次没有产出」），不补 null
LIST_SLOTS = {
    "fields", "items", "results", "answers", "questions", "qas", "evidence",
    "sections", "tables", "figures", "claims", "events", "entities", "relations",
    "not_reported", "unreadable", "conflicts", "recommendations", "limitations",
    "notes", "slides", "outline_slides", "agenda", "schedule", "glossary",
    "terms", "risks", "issues", "next_steps",
}

# 边界槽位：这些字段由运行骨架保证存在，不算「未取到值的内容字段」
BOUNDARY_SLOTS = {
    "case_id", "status", "sources", "uncertainty", "change_log", "audit",
    "contract_check",
}

# 中文契约名（部分赛题的 output_contract 用中文键）→ 英文槽位
CN_ALIASES = {
    "解析结果": "parsed", "抽取结果": "parsed", "结果": "parsed",
    "证据": "evidence", "证据与边界": "evidence",
    "运行状态": "status", "状态": "status",
    "目标产物": "document", "产物": "document",
    "事实与来源映射": "evidence", "版本与边界": "change_log",
    "页级证据映射": "evidence", "渲染与版本记录": "change_log",
    "可编辑源文件": "document", "导出件": "document",
    "来源与修改记录": "sources", "摘要": "summary",
    "限制": "limitations", "结论": "summary",
}


def _as_name(item):
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("name", "field", "key", "id", "field_id", "column"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def contract_fields(contract):
    """从 output_contract 解析必填字段名（保序、去重）。"""
    names = []
    if isinstance(contract, dict):
        for key in ("required", "fields", "properties"):
            val = contract.get(key)
            if isinstance(val, list) and val:
                items = val
                break
            if isinstance(val, dict):
                items = list(val.keys())
                break
        else:
            items = [k for k in contract.keys() if k not in META_KEYS]
        for item in items:
            name = _as_name(item)
            if name:
                names.append(name)
    elif isinstance(contract, list):
        for item in contract:
            name = _as_name(item)
            if name:
                names.append(name)
    elif isinstance(contract, str):
        names = [contract]
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def slot_of(field_name):
    """字段名 → 语义槽位。"""
    key = (field_name or "").strip()
    if key in FIELD_ALIASES:
        return FIELD_ALIASES[key]
    if key in CN_ALIASES:
        return CN_ALIASES[key]
    low = key.lower().replace("-", "_").replace(" ", "_")
    if low in FIELD_ALIASES:
        return FIELD_ALIASES[low]
    if low in CN_ALIASES:
        return CN_ALIASES[low]
    for alias, slot in FIELD_ALIASES.items():
        if alias in low or low in alias:
            return slot
    return None


def placeholder_for(name, slot=None):
    """给取不到值的必填字段一个**诚实**占位值（不编造、不用 null 充数）。

    列表型槽位补空列表；其余补 {"status": "not_reported", "reason": ...}，
    由调用方把字段名登记进 uncertainty.unresolved，供人工接管。
    """
    s = slot if slot is not None else slot_of(name)
    if s in LIST_SLOTS:
        return []
    return {
        "status": "not_reported",
        "reason": "本次运行未能从材料中自动取值，需人工复核补齐（未填入任何推测内容）",
    }


def empty_result(case_id, contract, reason):
    """诚实降级：契约里声明的每个必填字段都出现（占位值），边界三件套齐全。"""
    fields = contract_fields(contract)
    result = {}
    unresolved = []
    for name in fields:
        slot = slot_of(name)
        if slot == "case_id":
            result[name] = case_id
            continue
        if slot == "status":
            result[name] = "failed"
            continue
        result[name] = placeholder_for(name, slot)
        if slot not in BOUNDARY_SLOTS:
            unresolved.append(name)
    result["case_id"] = case_id
    result["status"] = "failed"
    result["sources"] = []
    result["uncertainty"] = {
        "level": "high",
        "notes": [reason],
        "unresolved": unresolved,
    }
    result["change_log"] = [
        "读取 case.json 并解析 output_contract 必填字段 %d 项" % len(fields),
        "在输入目录中未发现可抽取材料，按契约生成诚实降级骨架，未填入任何推测内容",
    ]
    return result


def finalize_result(result, contract, case_id=None):
    """契约完整性兜底：**绝不缺键**。

    - output_contract.required 里声明的每个字段都出现在 result 中；
      缺的补诚实占位值，并把字段名登记进 uncertainty.unresolved。
    - case_id / status / sources / uncertainty / change_log 五个边界键始终存在。
    返回 (result, missing_names)。
    """
    if not isinstance(result, dict):
        result = {}
    fields = contract_fields(contract)
    missing = []
    for name in fields:
        if name not in result:
            slot = slot_of(name)
            if slot == "case_id":
                result[name] = case_id
            elif slot == "status":
                result[name] = "partial"
            else:
                result[name] = placeholder_for(name, slot)
            missing.append(name)
    if case_id is not None:
        result["case_id"] = result.get("case_id") or case_id
    if not isinstance(result.get("status"), str) or not result.get("status"):
        result["status"] = "partial"
    if not isinstance(result.get("sources"), list):
        result["sources"] = []
    if not isinstance(result.get("change_log"), list):
        result["change_log"] = []
    unc = result.get("uncertainty")
    if not isinstance(unc, dict):
        unc = {"level": "medium", "notes": [], "unresolved": []}
    unresolved = list(unc.get("unresolved", []) or [])
    for name in missing:
        if name not in unresolved:
            unresolved.append(name)
    unc["unresolved"] = unresolved
    notes = list(unc.get("notes", []) or [])
    if missing:
        notes.append("以下契约必填字段本次未能自动取值，已补诚实占位并列入 unresolved：%s"
                     % ", ".join(missing))
    unc["notes"] = notes
    unc.setdefault("level", "medium")
    result["uncertainty"] = unc
    result["contract_check"] = {
        "required": fields,
        "present": [f for f in fields if f in result],
        "missing": missing,
    }
    return result, missing


def _value_from_slot(slot, doc, extra=None):
    """按语义槽位从抽取结果里取一个合理的值（带证据）。"""
    extra = extra or {}
    if slot == "parsed":
        return {"units": [{"id": u["id"], "title": u["title"], "role": u["role"],
                           "page": u["page_start"], "words": u["words"]}
                          for u in doc.get("units", [])],
                "source": "doc_extract"}
    if slot == "extracted":
        return {"numbers": doc.get("numbers", [])[:200],
                "tables": [{"id": t["id"], "rows": len(t["rows"]),
                            "caption": t.get("caption", "")} for t in doc.get("tables", [])],
                "captions": doc.get("captions", []),
                "source": "doc_extract"}
    if slot == "sections":
        return [{"id": u["id"], "title": u["title"], "role": u["role"],
                 "page_start": u["page_start"], "page_end": u["page_end"]}
                for u in doc.get("units", [])]
    if slot == "tables":
        return [{"id": t["id"], "page": t["page"], "caption": t.get("caption", ""),
                 "layout": t.get("layout", ""),
                 "rows": [{"row": r["row"], "cells": r["cells"], "anchor": r["anchor"]}
                          for r in t["rows"][:60]]}
                for t in doc.get("tables", [])]
    if slot == "figures":
        return doc.get("captions", [])
    if slot == "evidence":
        out = []
        rows = extra.get("field_results")
        if isinstance(rows, list):
            for r in rows:
                if r.get("status") != "reported":
                    continue
                out.append({"anchor": r.get("paragraph_id") or "",
                            "quote": r.get("quote") or "",
                            "kind": "field_evidence",
                            "field_id": r.get("field_id")})
        for t in doc.get("tables", []):
            if t.get("caption"):
                out.append({"anchor": "p.%d/%s" % (t["page"], t["id"]),
                            "quote": t["caption"], "kind": "table_caption"})
        for c in doc.get("captions", []):
            out.append({"anchor": c["anchor"], "quote": c["text"], "kind": "caption"})
        for u in doc.get("units", [])[:20]:
            out.append({"anchor": "p.%d/%s" % (u["page_start"], u["id"]),
                        "quote": u["title"], "kind": "section_heading"})
        return out
    if slot == "coverage":
        pages = len(doc.get("pages", []))
        chars = sum(p["chars"] for p in doc.get("pages", []))
        return {"pages_extracted": pages, "chars_extracted": chars,
                "units": len(doc.get("units", [])),
                "tables": len(doc.get("tables", [])),
                "numbers": len(doc.get("numbers", [])),
                "tier": doc.get("meta", {}).get("tier", "unknown")}
    if slot in ("fields", "items", "results"):
        # 字段表驱动抽取的结果优先落到「字段/条目/结果」类槽位
        rows = extra.get("field_results")
        if isinstance(rows, list) and rows:
            return rows
        return extra.get(slot)
    if slot == "not_reported":
        return []
    if slot == "unreadable":
        return [] if doc.get("meta", {}).get("tier") != "unreadable" else [
            {"file": doc.get("meta", {}).get("source_file"),
             "reason": "no extractable text layer"}]
    if slot == "conflicts":
        return []
    if slot == "sources":
        return [{"file": doc.get("meta", {}).get("source_file"),
                 "locator": doc.get("meta", {}).get("text_path") or "in-package",
                 "tier": doc.get("meta", {}).get("tier", "unknown")}]
    if slot == "uncertainty":
        return {"level": "medium", "notes": [], "unresolved": []}
    if slot == "change_log":
        return []
    if slot == "audit":
        return {"pass": False, "errors": [], "warnings": [], "checks": []}
    if slot == "contract_check":
        return {"required": [], "present": [], "missing": []}
    if slot == "status":
        return "partial"
    if slot == "summary":
        return ""
    if slot == "case_id":
        return None
    if slot in extra:
        return extra[slot]
    return None


def build_result(case_id, contract, doc, extra=None, status=None,
                 uncertainty=None, change_log=None, sources=None):
    """按 output_contract 装配 result.json。

    每个必填字段都会出现；无法自动取值时填**诚实占位值**（不省略、不填 null），
    并在 uncertainty.unresolved 中列出，等待人工接管。
    """
    fields = contract_fields(contract)
    result = {}
    unresolved = []
    for name in fields:
        slot = slot_of(name)
        if slot == "case_id":
            result[name] = case_id
            continue
        if slot == "status":
            result[name] = status or "partial"
            continue
        val = _value_from_slot(slot, doc, extra)
        if val is None:
            unresolved.append(name)
            val = placeholder_for(name, slot)
        result[name] = val
    result["case_id"] = case_id
    result["status"] = status or ("partial" if unresolved else "success")
    result["sources"] = sources if sources is not None else _value_from_slot("sources", doc)
    unc = _value_from_slot("uncertainty", doc)
    if isinstance(unc, dict):
        unc = dict(unc)
        unc["unresolved"] = sorted(set(list(unc.get("unresolved", [])) + unresolved))
        if uncertainty:
            unc.update(uncertainty)
    else:
        unc = uncertainty or {"level": "medium", "notes": [], "unresolved": unresolved}
    result["uncertainty"] = unc
    result["change_log"] = change_log if change_log is not None else []
    return result


def main(argv=None):
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="解析 output_contract 字段")
    ap.add_argument("case_json")
    args = ap.parse_args(argv)
    with open(args.case_json, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    contract = case.get("output_contract", {})
    fields = contract_fields(contract)
    print(json.dumps({
        "fields": fields,
        "slots": {f: slot_of(f) for f in fields},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
