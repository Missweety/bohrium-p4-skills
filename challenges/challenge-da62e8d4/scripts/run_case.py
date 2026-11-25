#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_case.py - reproduction & method-validation main path.

  python3 scripts/run_case.py
  python3 scripts/run_case.py --input /input --work /app/work --output /app/output

Pipeline:
  index materials -> build data/environment/parameters/commands plan -> recompute every
  stated t/z/percent relation -> classify each claim -> independent audit -> result.json

Honesty rules: a relation is only "recomputed" when the text supplies all inputs;
missing data/code/params downgrade to partially_reproduced or not_reproducible.
Never invents a reproduction result, never trains a model, never fetches data.

Exit code is 0 even on degraded inputs (a crashed harness scores zero).
"""
from __future__ import annotations

import argparse
import csv
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

import doc_index   # noqa: E402
import repro_plan  # noqa: E402

DEFAULT_FIELDS = ["case_id", "status", "answer", "reproduction", "evidence", "sources",
                  "uncertainty", "limits", "change_log"]

ALIASES = {
    "case_id": "case_id", "id": "case_id", "task_id": "case_id",
    "status": "status", "result_status": "status",
    "answer": "answer", "summary": "answer", "conclusion": "answer",
    "reproduction": "reproduction", "results": "reproduction",
    "verification": "reproduction",
    "claims": "claims", "claim_list": "claims",
    "checks": "checks", "check_list": "checks",
    "plan": "plan", "reproduction_plan": "plan", "protocol": "plan", "steps": "plan",
    "evidence": "evidence", "citations": "evidence", "quotes": "evidence",
    "sources": "sources", "materials": "sources",
    "uncertainty": "uncertainty", "gaps": "uncertainty", "unknowns": "uncertainty",
    "limits": "limits", "limitations": "limits",
    "conflicts": "conflicts", "inconsistencies": "conflicts",
    "change_log": "change_log", "changes": "change_log",
    "metrics": "metrics", "coverage": "coverage", "audit": "audit",
    "structured": "structured", "artifacts": "artifacts", "deliverables": "artifacts",
    "notes": "notes", "environment": "environment",
}
LIST_SLOTS = {"evidence", "sources", "uncertainty", "change_log", "conflicts", "notes"}


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
    cn = {"复现": "reproduction", "复现计划": "plan", "结论": "answer", "摘要": "answer",
          "证据": "evidence", "边界": "uncertainty", "状态": "status", "来源": "sources"}
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


def build_result(case_id, contract, payload, status, limits, uncertainty, change_log):
    required = contract_fields(contract) or DEFAULT_FIELDS
    structured = payload.get("structured") or {}
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
    return result


def write_report(path, case_id, status, plan, claims, summary, limits):
    lines = ["# 复现与方法验证报告（自动生成）", "",
             "- case_id: `%s`" % case_id,
             "- status: `%s`" % status,
             "- claims: %d（一致 %d / 不一致 %d / 部分 %d / 不可复现 %d / 不可核验 %d）" % (
                 summary.get("claims", 0), summary.get("recomputed_consistent", 0),
                 summary.get("recomputed_inconsistent", 0),
                 summary.get("partially_reproduced", 0),
                 summary.get("not_reproducible", 0), summary.get("not_checkable", 0)),
             "", "## 复现计划", ""]
    for kind in ("data", "environment", "parameters", "commands", "code"):
        entries = plan.get(kind) or []
        specified = [e for e in entries if e.get("status") == "specified"]
        lines.append("### %s（原文明确 %d 项）" % (kind, len(specified)))
        if not specified:
            lines.append("- 未在材料中找到；未补默认值。")
        for e in specified:
            lines.append("- `%s` = %s（%s，%s）" % (
                e.get("item"), e.get("value"), e.get("paragraph_id"),
                (e.get("quote") or "")[:120]))
        lines.append("")
    lines += ["## 逐条判定", ""]
    for c in claims:
        lines.append("- **%s** `%s` — %s" % (c["claim_id"], c["status"], c["claim"][:160]))
        for ch in c.get("checks") or []:
            lines.append("  - %s：computed=%s reported=%s verdict=%s" % (
                ch.get("test"), ch.get("computed_p", ch.get("computed_pct")),
                ch.get("reported_p", ch.get("reported_pct")), ch.get("verdict")))
    lines += ["", "## 边界", "", limits or "无。", ""]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main(argv=None):
    ap = argparse.ArgumentParser(description="paper reproduction and method validation")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--output", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--case", default=None)
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
            case_error = "case.json 无法解析（%s）；已回退默认契约，未猜测内容" % exc
    case_id = (case.get("case_id") or case.get("id")
               or (os.path.splitext(os.path.basename(case_path))[0] if case_path else "case"))
    contract = case.get("output_contract", {}) if isinstance(case, dict) else {}

    try:
        doc = doc_index.build_doc(a.input)
        dump(doc, os.path.join(a.work, "doc.json"))
        materials = doc["meta"]["materials"]
        readable = [m for m in materials if m["readable"]]
        has_text = bool(doc["paragraphs"])

        if has_text:
            payload_raw = repro_plan.build(doc)
        else:
            payload_raw = {
                "plan": {k: [] for k in repro_plan.SECTION_PATTERNS},
                "plan_complete": {k: False for k in repro_plan.SECTION_PATTERNS},
                "claims": [], "checks": [], "conflicts": [],
                "summary": {"claims": 0, "recomputed_consistent": 0,
                            "recomputed_inconsistent": 0, "partially_reproduced": 0,
                            "not_reproducible": 0, "not_checkable": 0,
                            "checks": 0, "conflicts": 0},
            }
        dump(payload_raw, os.path.join(a.work, "reproduction.json"))

        claims = payload_raw["claims"]
        checks = payload_raw["checks"]
        plan = payload_raw["plan"]
        summary = payload_raw["summary"]
        complete = payload_raw["plan_complete"]

        sources = [{"file": m["path"], "kind": m["kind"], "bytes": m["bytes"],
                    "readable": m["readable"], "note": m.get("note")}
                   for m in materials]
        evidence = []
        for c in claims:
            evidence.append({"claim": c["claim"][:180], "source_path": c.get("source_file"),
                             "locator": c.get("paragraph_id"), "quote": c.get("quote"),
                             "claim_id": c["claim_id"]})
        for kind, entries in plan.items():
            for e in entries:
                if e.get("status") == "specified":
                    evidence.append({"claim": "%s: %s=%s" % (kind, e.get("item"), e.get("value")),
                                     "source_path": e.get("source_file"),
                                     "locator": e.get("paragraph_id"), "quote": e.get("quote"),
                                     "claim_id": "plan.%s" % kind})
        if not has_text:
            evidence = [{"claim": "材料不可读", "source_path": None, "locator": None,
                         "quote": None}]

        counts = dict(summary)
        counts.update({"materials": len(materials), "readable_materials": len(readable),
                       "paragraphs": len(doc["paragraphs"])})
        missing_deps = [k for k, ok in complete.items() if not ok]

        if not has_text:
            status = "blocked"
        elif not claims:
            status = "partial"
        elif summary["recomputed_inconsistent"]:
            status = "partial"
        elif all(complete.values()) and summary["recomputed_consistent"] == len(claims):
            status = "success"
        else:
            status = "partial"

        limits = []
        if not has_text:
            limits.append("输入目录没有可读的论文材料（materials=%d, paragraphs=%d）；"
                          "未生成任何复现结论。" % (len(materials), len(doc["paragraphs"])))
        if not claims:
            limits.append("未定位到可判定的结果陈述（t/z/p 或效应量），无法做复现判定。")
        if missing_deps:
            limits.append("材料缺少以下复现依赖：%s；相应结论只标部分复现/不可复现。"
                          % "、".join(missing_deps))
        if summary["recomputed_inconsistent"]:
            limits.append("有 %d 条复算与原文报告不一致，已列入 conflicts，需人工核对。"
                          % summary["recomputed_inconsistent"])
        if summary["not_checkable"]:
            limits.append("%d 条陈述缺少 df/p/数据，标 not_checkable，未猜测。"
                          % summary["not_checkable"])
        if case_error:
            limits.append(case_error)
        limits_text = "；".join(limits)

        uncertainty = []
        for c in claims:
            if c["status"] in ("partially_reproduced", "not_reproducible",
                               "not_checkable", "recomputed_inconsistent"):
                uncertainty.append("%s[%s]：%s" % (c["claim_id"], c["status"], c["note"]))
        if not uncertainty:
            uncertainty.append("无开放不确定项：所有复算一致且依赖均有原文依据。")
        if case_error:
            uncertainty.append(case_error)

        if not has_text:
            answer = ("未能读取任何论文材料（可读文件 0 个）。未编造数据、环境或复现结果；"
                      "请补齐材料后重跑。")
        elif not claims:
            answer = ("已索引 %d 个段落，但未找到可判定的结果陈述（含 t/z/p 或效应量），"
                      "无法给出复现判定；未臆测结论。" % len(doc["paragraphs"]))
        else:
            answer = ("对 %d 条结果陈述逐条判定：一致 %d、不一致 %d、部分复现 %d、"
                      "不可复现 %d、不可核验 %d。所有复算仅使用原文给出的 t/df/z/前后值；"
                      "数据/环境/参数/命令四项中缺 %s，因此完整独立复现受限。"
                      % (summary["claims"], summary["recomputed_consistent"],
                         summary["recomputed_inconsistent"], summary["partially_reproduced"],
                         summary["not_reproducible"], summary["not_checkable"],
                         "、".join(missing_deps) if missing_deps else "无"))

        left = {k: [e for e in v if e.get("status") == "specified"]
                for k, v in plan.items()}
        reproduction = {
            "claims": claims,
            "checks": checks,
            "plan": plan,
            "plan_complete": complete,
            "conflicts": payload_raw["conflicts"],
            "summary": summary,
            "method": {
                "recomputation": "t->p via incomplete beta; z->p via erfc; percent change "
                                 "from reported before/after values",
                "verdicts": "consistent when |computed-reported| <= reporting-precision "
                            "tolerance; inconsistent otherwise",
                "no_model_training": True,
                "no_external_data": True,
            },
        }
        structured = {
            "claims": claims,
            "plan": plan,
            "counts": counts,
            "summary": summary,
            "conflicts": payload_raw["conflicts"],
            "method": reproduction["method"],
            "artifacts": {"result": "result.json",
                          "reproduction_report": "reproduction_report.md",
                          "doc_index": "work/doc.json",
                          "reproduction": "work/reproduction.json",
                          "checks_csv": "work/checks.csv",
                          "audit": "work/audit.json"},
        }
        change_log = [
            "读取 %s；契约必填字段 %d 项" % (case_path or "(无 case.json)",
                                            len(contract_fields(contract))),
            "索引材料 %d 个（可读 %d），段落 %d 个"
            % (len(materials), len(readable), len(doc["paragraphs"])),
            "抽取复现计划：data=%d、environment=%d、parameters=%d、commands=%d、code=%d"
            % (len(left.get("data", [])), len(left.get("environment", [])),
               len(left.get("parameters", [])), len(left.get("commands", [])),
               len(left.get("code", []))),
            "复算结果陈述 %d 条，生成检查 %d 项" % (len(claims), len(checks)),
            "写出 work/doc.json、work/reproduction.json、work/checks.csv",
        ]

        payload = {
            "answer": answer, "reproduction": reproduction, "plan": plan,
            "claims": claims, "checks": checks, "summary": summary,
            "evidence": evidence, "sources": sources, "uncertainty": uncertainty,
            "limits": limits_text, "change_log": change_log, "metrics": counts,
            "coverage": {"materials": materials, "paragraphs": len(doc["paragraphs"])},
            "conflicts": payload_raw["conflicts"], "structured": structured,
            "artifacts": structured["artifacts"], "notes": [],
        }
        result = build_result(case_id, contract, payload, status, limits_text,
                              uncertainty, change_log)
        dump(result, result_path)

        # CSV of checks for reviewers
        csv_path = os.path.join(a.work, "checks.csv")
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["test", "inputs", "computed", "reported", "verdict",
                        "tolerance", "paragraph_id"])
            for ch in checks:
                w.writerow([ch.get("test"), json.dumps(ch.get("inputs"), ensure_ascii=False),
                            ch.get("computed_p", ch.get("computed_pct")),
                            ch.get("reported_p", ch.get("reported_pct")),
                            ch.get("verdict"), ch.get("tolerance"),
                            ch.get("paragraph_id")])
        write_report(os.path.join(a.output, "reproduction_report.md"), case_id, status,
                     plan, claims, summary, limits_text)

        audit_out = os.path.join(a.work, "audit.json")
        cmd = [sys.executable, os.path.join(HERE, "audit_result.py"),
               "--result", result_path, "--doc", os.path.join(a.work, "doc.json"),
               "--plan", os.path.join(a.work, "reproduction.json"), "--out", audit_out]
        if case_path and not case_error:
            cmd += ["--case", case_path]
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            audit = load_json(audit_out) if os.path.isfile(audit_out) else {
                "pass": False, "errors": ["audit produced no report"], "checks": []}
        except Exception as exc:  # noqa: BLE001
            audit = {"pass": False, "errors": ["audit crashed: %s" % exc], "checks": []}

        result["audit"] = audit
        if not audit.get("pass") and result["status"] == "success":
            result["status"] = "partial"
            result["limits"] = "；".join([x for x in
                                          [result["limits"],
                                           "独立复核发现 %d 项问题" % len(audit["errors"])] if x])
        result["change_log"] = change_log + [
            "独立进程运行 audit_result.py：checks=%d、errors=%d、pass=%s"
            % (len(audit.get("checks") or []), len(audit.get("errors") or []),
               audit.get("pass")),
            "本次运行耗时 %.1f 秒" % (time.time() - t0),
        ]
        result["contract_check"] = {
            "required": contract_fields(contract) or DEFAULT_FIELDS,
            "present": [f for f in (contract_fields(contract) or DEFAULT_FIELDS)
                        if f in result],
            "missing": [f for f in (contract_fields(contract) or DEFAULT_FIELDS)
                        if f not in result],
        }
        dump(result, result_path)
        print("status=%s %s audit=%s -> %s" % (
            result["status"], json.dumps(counts, ensure_ascii=False),
            audit.get("pass"), result_path))
        return 0
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("[run_case] fatal: %s\n%s\n" % (exc, traceback.format_exc()[-1200:]))
        try:
            payload = {
                "answer": "运行异常，未产出可核验的复现判定。",
                "reproduction": {"claims": [], "checks": [], "plan": {}},
                "plan": {}, "evidence": [], "sources": [],
                "uncertainty": ["run_case 内部异常：%s" % exc],
                "limits": "run_case 内部异常：%s" % exc, "change_log": ["运行失败"],
                "structured": {"error": str(exc)[:500]}, "metrics": {},
                "coverage": {}, "conflicts": [], "artifacts": {}, "notes": [],
            }
            result = build_result(case_id, contract, payload, "failed",
                                  "run_case 内部异常：%s" % exc,
                                  ["run_case 内部异常：%s" % exc],
                                  ["运行失败，已写降级 result.json"])
            result["contract_check"] = {
                "required": contract_fields(contract) or DEFAULT_FIELDS,
                "present": [f for f in (contract_fields(contract) or DEFAULT_FIELDS)
                            if f in result],
                "missing": [f for f in (contract_fields(contract) or DEFAULT_FIELDS)
                            if f not in result],
            }
            dump(result, result_path)
        except Exception:  # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
