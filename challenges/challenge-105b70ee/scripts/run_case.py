#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_case.py - one command for the field-extraction main path.

  python3 scripts/run_case.py
  python3 scripts/run_case.py --input /input --work /app/work --output /app/output

Reads /input/case.json + the requested field table (target-fields.json), indexes the
supplied paper materials, fills every requested field with a verbatim value + paragraph
anchor + quote, runs an independent audit, and writes result.json with all
output_contract fields. Missing / unreadable inputs degrade honestly (exit code 0):
a crashed harness would lose the whole attempt, so partial results are always saved.

Stdlib only, no network, no prepared answers.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.dont_write_bytecode = True

import doc_index          # noqa: E402
import field_extract      # noqa: E402

DEFAULT_FIELDS = ["case_id", "status", "answer", "fields", "evidence", "sources",
                  "uncertainty", "limits", "change_log"]

ALIASES = {
    "case_id": "case_id", "id": "case_id", "task_id": "case_id",
    "status": "status", "result_status": "status",
    "answer": "answer", "summary": "answer", "conclusion": "answer", "main_result": "answer",
    "fields": "fields", "field_results": "fields", "results": "fields", "items": "fields",
    "records": "fields", "extractions": "fields", "table": "fields", "rows": "fields",
    "evidence": "evidence", "citations": "evidence", "quotes": "evidence",
    "sources": "sources", "uncertainty": "uncertainty", "gaps": "uncertainty",
    "unknowns": "uncertainty", "limits": "limits", "limitations": "limits",
    "change_log": "change_log", "changes": "change_log",
    "coverage": "coverage", "metrics": "metrics", "audit": "audit",
    "structured": "structured", "protocol": "protocol", "field_schema": "protocol",
    "artifacts": "artifacts", "deliverables": "artifacts", "notes": "notes",
}
LIST_SLOTS = {"fields", "evidence", "sources", "uncertainty", "change_log", "notes"}


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def contract_fields(contract):
    names = []
    if isinstance(contract, list):
        names = [x for x in contract if isinstance(x, str)]
    elif isinstance(contract, dict):
        items = None
        for key in ("required", "fields", "properties"):
            val = contract.get(key)
            if isinstance(val, list) and val:
                items = val
                break
            if isinstance(val, dict) and val:
                items = list(val.keys())
                break
        if items is None:
            items = list(contract.keys())
        for item in items:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                for k in ("name", "field", "field_id", "id", "key"):
                    if isinstance(item.get(k), str):
                        names.append(item[k])
                        break
    out = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out


def slot_of(name):
    key = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in ALIASES:
        return ALIASES[key]
    cn = {"解析结果": "fields", "抽取结果": "fields", "字段": "fields", "结果": "fields",
          "证据": "evidence", "边界": "uncertainty", "状态": "status",
          "摘要": "answer", "运行状态": "status", "来源": "sources"}
    if key in cn:
        return cn[key]
    for alias, slot in ALIASES.items():
        if alias in key or key in alias:
            return slot
    return None


def find_case(input_dir, explicit):
    for cand in [explicit, os.path.join(input_dir, "case.json"),
                 "/input/case.json", "/app/input/case.json", "./case.json"]:
        if cand and os.path.isfile(cand):
            return os.path.abspath(cand)
    return None


def case_id_of(case, input_dir, case_path):
    for key in ("case_id", "id", "task_id", "name"):
        val = case.get(key) if isinstance(case, dict) else None
        if isinstance(val, (str, int)) and str(val).strip():
            return str(val).strip()
    if case_path:
        return os.path.splitext(os.path.basename(case_path))[0]
    return os.path.basename(os.path.abspath(input_dir)) or "case"


def build_result(case_id, contract, payload, status, limits, uncertainty, change_log):
    required = contract_fields(contract) or DEFAULT_FIELDS
    structured = payload["structured"]
    result = {}
    for name in required:
        slot = slot_of(name)
        if slot == "case_id":
            result[name] = case_id
        elif slot == "status":
            result[name] = status
        elif slot in payload:
            result[name] = payload[slot]
        elif slot == "structured":
            result[name] = structured
        else:
            fallback = dict(structured)
            fallback["_contract_field"] = name
            fallback["_note"] = "字段名未在别名表中，用 structured 填充，需人工确认"
            result[name] = fallback
    result["case_id"] = case_id
    result["status"] = status
    result["limits"] = limits
    result["uncertainty"] = uncertainty
    result["change_log"] = change_log
    result.setdefault("sources", payload.get("sources", []))
    result["contract_check"] = {
        "required": required,
        "present": [f for f in required if f in result],
        "missing": [f for f in required if f not in result],
    }
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="paper field extraction")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--output", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--case", default=None, help="explicit case.json (local dry run)")
    a = ap.parse_args(argv)

    t0 = time.time()
    os.makedirs(a.output, exist_ok=True)
    os.makedirs(a.work, exist_ok=True)
    result_path = os.path.join(a.output, "result.json")

    case, case_error = {}, None
    case_path = find_case(a.input, a.case)
    if case_path:
        try:
            case = load_json(case_path)
        except Exception as exc:  # noqa: BLE001
            case_error = "case.json 无法解析（%s）；已回退默认契约，未猜测字段内容" % exc
    case_id = case_id_of(case, a.input, case_path)
    contract = case.get("output_contract", {}) if isinstance(case, dict) else {}

    def emit(result):
        result["contract_check"] = {
            "required": contract_fields(contract) or DEFAULT_FIELDS,
            "present": [], "missing": [],
        }
        result["contract_check"]["present"] = [
            f for f in result["contract_check"]["required"] if f in result]
        result["contract_check"]["missing"] = [
            f for f in result["contract_check"]["required"] if f not in result]
        dump(result, result_path)
        return result

    try:
        doc = doc_index.build_doc(a.input)
        dump(doc, os.path.join(a.work, "doc.json"))
        materials = doc["meta"]["materials"]
        readable = [m for m in materials if m["readable"]]
        no_material = not readable or not doc["paragraphs"]
        reason = None
        if no_material:
            reason = ("输入目录没有可读的论文材料（materials=%d, paragraphs=%d）；"
                      "未猜测任何取值。" % (len(materials), len(doc["paragraphs"])))

        field_result = {"fields": [], "requested": 0}
        if not no_material:
            field_result = field_extract.run(doc, a.input, case)
            dump(field_result, os.path.join(a.work, "field_results.json"))
        elif field_result:
            pass

        rows = field_result.get("fields") or []
        if no_material and not rows:
            # keep one honest row per requested field so the contract shows coverage
            for field in field_extract.load_target_fields(a.input, case):
                rows.append({
                    "field_id": field["field_id"], "description": field["description"],
                    "status": "extraction_failed", "value": None, "unit": None,
                    "statistic": None, "experimental_condition": None, "comparator": None,
                    "paragraph_id": None, "quote": None,
                    "note": "材料不可读或缺失，需人工接管。",
                })
            field_result = {"fields": rows, "requested": len(rows), "note": reason}
            dump(field_result, os.path.join(a.work, "field_results.json"))

        reported = [r for r in rows if r.get("status") == "reported"]
        not_reported = [r for r in rows if r.get("status") == "not_reported"]
        conflicts = [r for r in rows if r.get("status") == "source_conflict"]
        failed = [r for r in rows if r.get("status") == "extraction_failed"]

        sources = []
        for m in materials:
            sources.append({"file": m["path"], "kind": m["kind"], "bytes": m["bytes"],
                            "readable": m["readable"], "note": m.get("note")})
        evidence = []
        for r in reported:
            evidence.append({
                "claim": "%s = %s%s" % (r["field_id"], r.get("value"),
                                        (" " + r["unit"]) if r.get("unit") else ""),
                "source_path": r.get("source_file"),
                "locator": r.get("paragraph_id"),
                "quote": r.get("quote"),
                "field_id": r["field_id"],
            })
        if no_material:
            evidence = [{"claim": "材料不可读", "source_path": None, "locator": None,
                         "quote": None}]

        counts = {
            "requested": field_result.get("requested", len(rows)),
            "reported": len(reported),
            "not_reported": len(not_reported),
            "source_conflict": len(conflicts),
            "extraction_failed": len(failed),
            "materials": len(materials),
            "readable_materials": len(readable),
            "paragraphs": len(doc["paragraphs"]),
        }
        if no_material:
            status = "blocked"
        elif not field_result.get("requested"):
            status = "partial"
        elif failed and not reported:
            status = "failed"
        elif not_reported or conflicts or failed:
            status = "partial"
        else:
            status = "success"

        limits = []
        if no_material:
            limits.append(reason)
        if not_reported:
            limits.append("以下字段原文未报告，未填 0/未推测：%s"
                          % ", ".join(r["field_id"] for r in not_reported))
        if conflicts:
            limits.append("以下字段存在矛盾取值，保留候选待人工判定：%s"
                          % ", ".join(r["field_id"] for r in conflicts))
        if failed:
            limits.append("以下字段抽取失败，需人工接管：%s"
                          % ", ".join(r["field_id"] for r in failed))
        if case_error:
            limits.append(case_error)
        if not field_result.get("requested"):
            limits.append("输入未提供目标字段表（target-fields.json），无法确定字段集合。")
        if not limits and status == "success":
            limits_text = ""
        else:
            limits_text = "；".join(limits)

        uncertainty = []
        for r in not_reported:
            uncertainty.append("%s：原文未报告（%s）" % (r["field_id"], r.get("note")))
        for r in conflicts:
            uncertainty.append("%s：取值冲突，候选见 candidates" % r["field_id"])
        for r in failed:
            uncertainty.append("%s：抽取失败（%s）" % (r["field_id"], r.get("note")))
        if not uncertainty:
            uncertainty.append("无开放不确定项：每个请求字段均有原文锚点与逐字引文。")
        if case_error:
            uncertainty.append(case_error)

        protocol = {
            "field_table": "target-fields.json" if field_result.get("requested") else None,
            "paragraph_ids": ("JATS <p id> when supplied; otherwise p.<page>¶<k> for PDF "
                              "and ¶<k> for text/Markdown"),
            "value_policy": "value must be a verbatim substring of the quoted sentence",
            "missing_policy": "not_reported / extraction_failed; never 0, null-filled guesses",
            "unit_policy": "unit only when stated in the source; no conventional defaults",
        }
        structured = {
            "fields": rows,
            "counts": counts,
            "coverage": {"materials": materials, "paragraphs": counts["paragraphs"],
                         "tables": len(doc.get("tables") or [])},
            "protocol": protocol,
            "not_reported": [r["field_id"] for r in not_reported],
            "conflicts": [{"field_id": r["field_id"], "candidates": r.get("candidates")}
                          for r in conflicts],
            "unreadable": [m["path"] for m in materials if not m["readable"]],
            "artifacts": {"result": "result.json", "doc_index": "work/doc.json",
                          "field_results": "work/field_results.json",
                          "audit": "work/audit.json"},
        }
        if no_material:
            answer = ("未能读取任何论文材料（可读文件 0 个）。未猜测字段取值；"
                      "请按 limits 补齐材料后重跑。")
        elif not field_result.get("requested"):
            answer = ("已索引材料 %d 个、段落 %d 个，但输入未提供目标字段表，"
                      "无法确定要抽取的字段集合；未自行编造字段。"
                      % (len(materials), counts["paragraphs"]))
        else:
            answer = ("按 target-fields.json 逐字段抽取 %d 项：reported=%d、not_reported=%d、"
                      "source_conflict=%d、extraction_failed=%d。每个 reported 字段都带段落锚点"
                      "（%s）与逐字引文，取值必须能在引文中逐字找到；缺项不填 0。"
                      % (counts["requested"], counts["reported"], counts["not_reported"],
                         counts["source_conflict"], counts["extraction_failed"],
                         "JATS p id / p.N¶k / ¶k"))

        change_log = [
            "读取 %s，解析 output_contract 必填字段 %d 项"
            % (case_path or "(未提供 case.json)", len(contract_fields(contract))),
            "索引材料 %d 个（可读 %d），得到段落 %d 个、表格 %d 个"
            % (len(materials), len(readable), counts["paragraphs"], len(doc.get("tables") or [])),
            "按 target-fields.json 逐字段抽取：requested=%d" % counts["requested"],
            "reported 行逐条核对 value 为引文逐字子串，并写入 paragraph_id/quote",
            "写出 work/doc.json、work/field_results.json",
        ]

        payload = {
            "answer": answer, "fields": rows, "evidence": evidence, "sources": sources,
            "uncertainty": uncertainty, "limits": limits_text, "change_log": change_log,
            "coverage": structured["coverage"], "metrics": counts, "protocol": protocol,
            "artifacts": structured["artifacts"], "structured": structured,
        }
        result = build_result(case_id, contract, payload, status, limits_text,
                              uncertainty, change_log)
        emit(result)

        # ---- independent audit (separate process) ----
        audit_out = os.path.join(a.work, "audit.json")
        cmd = [sys.executable, os.path.join(HERE, "audit_result.py"),
               "--result", result_path, "--doc", os.path.join(a.work, "doc.json"),
               "--fields", os.path.join(a.work, "field_results.json"), "--out", audit_out]
        if case_path and not case_error:
            cmd += ["--case", case_path]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=120)
            audit = load_json(audit_out) if os.path.isfile(audit_out) else {
                "pass": False, "errors": ["audit produced no report"], "checks": []}
        except Exception as exc:  # noqa: BLE001
            audit = {"pass": False, "errors": ["audit crashed: %s" % exc], "checks": []}

        result["audit"] = audit
        if not audit.get("pass"):
            result["status"] = "partial" if result["status"] == "success" else result["status"]
            result["limits"] = "；".join([x for x in [result["limits"],
                                      "独立复核发现 %d 项问题" % len(audit.get("errors") or [])] if x])
        result["change_log"] = change_log + [
            "独立进程运行 audit_result.py：checks=%d、errors=%d、pass=%s"
            % (len(audit.get("checks") or []), len(audit.get("errors") or []),
               audit.get("pass")),
            "本次运行耗时 %.1f 秒" % (time.time() - t0),
        ]
        emit(result)
        print("status=%s fields=%s audit=%s -> %s" % (
            result["status"], json.dumps(counts, ensure_ascii=False),
            audit.get("pass"), result_path))
        return 0
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("[run_case] fatal: %s\n%s\n" % (exc, traceback.format_exc()[-1200:]))
        try:
            payload = {
                "answer": "运行异常，未产出可核验字段；详见 limits。",
                "fields": [], "evidence": [], "sources": [],
                "uncertainty": ["run_case 内部异常：%s" % exc],
                "limits": "run_case 内部异常：%s" % exc, "change_log": ["运行失败"],
                "structured": {"fields": [], "counts": {},
                               "error": str(exc)[:500], "artifacts": {}},
                "metrics": {}, "coverage": {}, "protocol": {},
                "artifacts": {}, "notes": [],
            }
            result = build_result(case_id, contract, payload, "failed",
                                  "run_case 内部异常：%s" % exc,
                                  ["run_case 内部异常：%s" % exc], ["运行失败，已写降级 result.json"])
            emit(result)
        except Exception:  # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
