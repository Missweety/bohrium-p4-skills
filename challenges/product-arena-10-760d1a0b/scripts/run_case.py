#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_case.py - literature knowledge graph main path.

  python3 scripts/run_case.py
  python3 scripts/run_case.py --input /input --work /app/work --output /app/output

Reads corpus-manifest.json / material.json / primary-material.json / secondary-material.json
(any JSON with paragraph arrays, plus md/txt fallback), builds an evidence-anchored graph,
executes the review queries for real, exports JSON + CSV, audits itself, and writes
result.json with every output_contract field.

Degraded inputs never crash the harness (exit 0, blocked/partial result.json).
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

import graph_build  # noqa: E402

DEFAULT_FIELDS = ["case_id", "status", "answer", "graph", "queries", "alias_decisions",
                  "integrity", "evidence", "sources", "uncertainty", "limits", "change_log",
                  "notes"]

ALIASES = {
    "case_id": "case_id", "id": "case_id", "task_id": "case_id",
    "status": "status", "result_status": "status",
    "answer": "answer", "summary": "answer", "conclusion": "answer",
    "graph": "graph", "knowledge_graph": "graph", "nodes_edges": "graph",
    "nodes": "nodes", "entities": "nodes",
    "edges": "edges", "relations": "edges", "triples": "edges",
    "queries": "queries", "query_results": "queries", "qa": "queries",
    "alias_decisions": "alias_decisions", "aliases": "alias_decisions",
    "merge_decisions": "alias_decisions", "entity_resolution": "alias_decisions",
    "integrity": "integrity", "quality_checks": "integrity", "consistency": "integrity",
    "evidence": "evidence", "citations": "evidence", "quotes": "evidence",
    "sources": "sources", "materials": "sources", "corpus": "sources",
    "uncertainty": "uncertainty", "gaps": "uncertainty", "unknowns": "uncertainty",
    "limits": "limits", "limitations": "limits",
    "change_log": "change_log", "changes": "change_log",
    "metrics": "metrics", "coverage": "coverage", "audit": "audit",
    "structured": "structured", "artifacts": "artifacts", "deliverables": "artifacts",
    "conflicts": "conflicts", "notes": "notes",
}


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
    cn = {"图谱": "graph", "知识图谱": "graph", "节点": "nodes", "边": "edges",
          "查询": "queries", "别名": "alias_decisions", "证据": "evidence",
          "摘要": "answer", "状态": "status", "边界": "uncertainty"}
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
    required = contract_fields(contract) or DEFAULT_FIELDS
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
    ap = argparse.ArgumentParser(description="build an evidence-anchored knowledge graph")
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
        built = graph_build.build(a.input)
        dump(built, os.path.join(a.work, "graph.json"))
        nodes, edges = built["nodes"], built["edges"]
        queries = [q for q in built["queries"] if q.get("executed")]
        integrity = built["integrity"]
        docs = built["docs"]

        npath, epath = graph_build.export_csv(nodes, edges, a.work)
        graph_json = os.path.join(a.output, "knowledge_graph.json")
        dump({"docs": docs, "nodes": nodes, "edges": edges,
              "alias_candidates": built["alias_candidates"]}, graph_json)
        out_nodes = os.path.join(a.output, "nodes.csv")
        out_edges = os.path.join(a.output, "edges.csv")
        graph_build.export_csv(nodes, edges, a.output)

        evidence = []
        for n in nodes[:40]:
            ev = (n.get("evidence") or [{}])[0]
            evidence.append({"claim": "实体 %s（%s）出现于 %s" % (
                n["label"], n["type"], n["source_id"]),
                "source_path": n["source_id"], "locator": ev.get("paragraph_id"),
                "quote": ev.get("quote"), "node_id": n["node_id"]})
        for q in queries:
            for ev in (q.get("evidence") or [])[:2]:
                evidence.append({"claim": "查询 %s 的证据" % q["query_id"],
                                 "source_path": ev.get("source_id"),
                                 "locator": ev.get("paragraph_id"),
                                 "quote": ev.get("quote"), "query_id": q["query_id"]})

        sources = [{"source_id": d["source_id"], "file": d["source_file"],
                    "title": d.get("title"),
                    "paragraph_count": d["paragraphs"],
                    "paragraph_ids": d.get("paragraph_ids") or [],
                    "formats": d.get("formats") or [d["source_file"]],
                    "doi": (d.get("meta") or {}).get("doi"),
                    "authors": (d.get("meta") or {}).get("authors"),
                    "license": (d.get("meta") or {}).get("license")}
                   for d in docs]
        metrics = {"documents": len(docs), "paragraphs": sum(d["paragraphs"] for d in docs),
                   "nodes": len(nodes), "edges": len(edges),
                   "alias_candidates": len(built["alias_candidates"]),
                   "queries_executed": len(queries),
                   "integrity_issues": len(integrity["issues"])}

        has_text = bool(docs) and sum(d["paragraphs"] for d in docs) > 0
        if not has_text:
            status = "blocked"
        elif len(queries) < 3 or not nodes:
            status = "partial"
        elif len(docs) < 2:
            status = "partial"
        elif integrity["pass"]:
            status = "success"
        else:
            status = "partial"

        limits = []
        if not has_text:
            limits.append("输入未提供可读的段落（corpus-manifest/material/primary/secondary "
                          "均无可用段落数组）；未凭空构建图谱。")
        if len(docs) < 2 and has_text:
            limits.append("仅解析到 %d 篇材料；跨文献查询只能给出单篇结果，"
                          "不假装做了双文献对照。" % len(docs))
        if len(queries) < 3:
            limits.append("实际执行的查询少于 3 条（%d 条），未凑数。" % len(queries))
        if integrity["issues"]:
            limits.append("完整性检查发现 %d 类问题（%s），已在 integrity 中逐项列出。"
                          % (len(integrity["issues"]),
                             "、".join(i["type"] for i in integrity["issues"])))
        if case_error:
            limits.append(case_error)
        notes = list(built.get("warnings") or [])
        limits_text = "；".join(limits)

        uncertainty = []
        for c in built["alias_candidates"]:
            if c["decision"] == "not_merged":
                uncertainty.append("%s：跨文献同名标签未合并（%s）"
                                   % (" / ".join(c["labels"]), c["reason"]))
        for q in queries:
            if q.get("limitations"):
                uncertainty.append("%s 限制：%s" % (q["query_id"], q["limitations"]))
        if not uncertainty:
            uncertainty.append("无开放不确定项：节点/边/查询均有原文锚点。")
        if case_error:
            uncertainty.append(case_error)

        conflicts = next((q["result"] for q in queries
                          if q["type"] == "conflict_check"), [])
        if not has_text:
            answer = ("未读取到任何论文段落，未构建图谱；请补 corpus-manifest / "
                      "primary-material / secondary-material 后重跑。")
        elif not nodes:
            answer = ("已读取 %d 篇、%d 段，但未抽到带原文证据的实体；"
                      "未编造节点。" % (len(docs), metrics["paragraphs"]))
        else:
            answer = ("从 %d 篇文献、%d 个段落构建 %d 个节点、%d 条边；同标签跨文献不合并，"
                      "记录 %d 条别名判定；实际执行 %d 条查询（含 1 条冲突检查，命中 %d 组）。"
                      "所有节点与边均带 source_id + paragraph_id + 逐字引文。"
                      % (len(docs), metrics["paragraphs"], len(nodes), len(edges),
                         len(built["alias_candidates"]), len(queries), len(conflicts)))

        change_log = [
            "读取 %s；契约必填字段 %d 项"
            % (case_path or "(无 case.json)", len(contract_fields(contract))),
            "解析 %d 篇材料、%d 个段落" % (len(docs), metrics["paragraphs"]),
            "构建节点 %d 个、边 %d 条" % (len(nodes), len(edges)),
            "生成别名候选 %d 条（跨文献默认 not_merged）" % len(built["alias_candidates"]),
            "实际执行查询 %d 条，完整性检查 %d 类问题"
            % (len(queries), len(integrity["issues"])),
            "导出 work/graph.json、nodes.csv、edges.csv 与 output/knowledge_graph.json",
        ] + notes

        graph_payload = {"nodes": nodes, "edges": edges,
                         "alias_candidates": built["alias_candidates"],
                         "docs": docs, "integrity": integrity}
        structured = dict(graph_payload)
        structured.update({"counts": metrics, "queries": queries,
                           "conflicts": conflicts,
                           "artifacts": {"result": "result.json",
                                         "graph_json": "knowledge_graph.json",
                                         "nodes_csv": "nodes.csv",
                                         "edges_csv": "edges.csv",
                                         "doc_index": "work/graph.json",
                                         "audit": "work/audit.json"}})
        payload = {
            "answer": answer, "graph": graph_payload, "nodes": nodes, "edges": edges,
            "queries": queries, "alias_decisions": built["alias_candidates"],
            "integrity": integrity, "evidence": evidence, "sources": sources,
            "uncertainty": uncertainty, "limits": limits_text, "change_log": change_log,
            "metrics": metrics, "coverage": {"docs": docs},
            "conflicts": conflicts, "structured": structured,
            "artifacts": structured["artifacts"], "notes": notes,
        }
        result = build_result(case_id, contract, payload, status, limits_text,
                              uncertainty, change_log)
        dump(result, result_path)

        audit_out = os.path.join(a.work, "audit.json")
        cmd = [sys.executable, os.path.join(HERE, "audit_result.py"),
               "--result", result_path, "--graph", os.path.join(a.work, "graph.json"),
               "--out", audit_out]
        if case_path and not case_error:
            cmd += ["--case", case_path]
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            audit = load_json(audit_out) if os.path.isfile(audit_out) else {
                "pass": False, "errors": ["audit produced no report"], "checks": []}
        except Exception as exc:  # noqa: BLE001
            audit = {"pass": False, "errors": ["audit crashed: %s" % exc], "checks": []}

        result["audit"] = audit
        result["metrics"] = metrics
        result["conflicts"] = conflicts
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
        dump(result, result_path)
        print("status=%s %s queries=%d audit=%s -> %s" % (
            result["status"], json.dumps(metrics, ensure_ascii=False), len(queries),
            audit.get("pass"), result_path))
        return 0
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("[run_case] fatal: %s\n%s\n" % (exc, traceback.format_exc()[-1200:]))
        try:
            payload = {
                "answer": "运行异常，未产出可核验图谱。",
                "graph": {"nodes": [], "edges": []}, "nodes": [], "edges": [],
                "queries": [], "alias_decisions": [], "integrity": {},
                "evidence": [], "sources": [],
                "uncertainty": ["run_case 内部异常：%s" % exc],
                "limits": "run_case 内部异常：%s" % exc, "change_log": ["运行失败"],
                "structured": {"error": str(exc)[:500]}, "metrics": {},
                "coverage": {}, "conflicts": [], "artifacts": {}, "notes": [],
            }
            result = build_result(case_id, contract, payload, "failed",
                                  "run_case 内部异常：%s" % exc,
                                  ["run_case 内部异常：%s" % exc],
                                  ["运行失败，已写降级 result.json"])
            dump(result, result_path)
        except Exception:  # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
