#!/usr/bin/env python3
"""Independent self-check for a mind-map deliverable.

Re-reads result.json, the exported artifacts and (optionally) sources.json and
verifies that the delivered files agree with the self-reported metadata. Checks
carry a severity: only hard failures make the run fail, warnings are reported.

  hard  交付物损坏、契约字段缺失、节点数与产物不一致、引文与源文不符
  warn  建议性阈值（节点数、层级、节点类型、PNG 预览等）

Usage:
  python3 selfcheck.py --case /input/case.json --out /app/output \
      --plan /app/work/plan.json --sources /app/work/sources.json
Exit code 0 = all hard checks pass.
"""
import argparse
import csv
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

TYPES = {"question", "method", "evidence", "result", "conclusion", "task", "risk", "concept"}
RELS = {"causes", "depends_on", "supports", "contradicts", "compares", "precedes", "cites", "part_of"}
REQUIRED = ["case_id", "status", "sources", "uncertainty", "change_log", "mindmap",
            "nodes", "edges", "evidence_index", "issues", "contract_fields"]
PLACEHOLDERS = ("TODO", "TBD", "在此填写", "待补充", "待填写")


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def norm(text):
    text = (text or "").replace("\u3000", " ").replace("\xa0", " ")
    return re.sub(r"\s+", "", text)


def verify_quote(quote, index):
    q = norm(quote)
    for text in index.values():
        if q and q in text:
            return True
    return False


def contract_keys(case):
    oc = case.get("output_contract") if isinstance(case, dict) else None
    if oc is None and isinstance(case, dict):
        for alt in ("outputContract", "contract", "required_outputs"):
            if alt in case:
                oc = case.get(alt)
                break
    names = []
    if isinstance(oc, dict):
        for key in oc.keys():
            if key in ("required", "fields", "properties") and isinstance(oc[key], (list, dict)):
                continue
            names.append(key)
        for key in ("required", "fields", "properties"):
            val = oc.get(key)
            if isinstance(val, list):
                for item in val:
                    names.append(item if isinstance(item, str) else
                                 (item.get("name") or item.get("field") or item.get("key") or ""))
            elif isinstance(val, dict):
                names.extend(list(val.keys()))
    elif isinstance(oc, list):
        for item in oc:
            names.append(item if isinstance(item, str) else
                         (item.get("name") or item.get("field") or item.get("key") or ""))
    seen, out = set(), []
    for n in names:
        if isinstance(n, str) and n.strip() and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--plan", default="/app/work/plan.json")
    ap.add_argument("--sources", default="/app/work/sources.json")
    a = ap.parse_args()

    checks = []

    def add(name, ok, detail, severity="hard"):
        checks.append({"name": name, "ok": bool(ok), "severity": severity, "detail": detail})

    path_result = os.path.join(a.out, "result.json")
    result = load_json(path_result)
    case = load_json(a.case, {}) or {}
    if not isinstance(result, dict):
        add("result_json_parses", False, "result.json 缺失或不是 JSON 对象：%s" % path_result)
        payload = {"ok": False, "passed": 0, "failed": 1, "warnings": 0, "status": "missing",
                   "case_id": None, "issues": ["result.json missing or invalid"], "checks": checks}
        with open(os.path.join(a.out, "checks.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        print(json.dumps({"ok": False, "failed": 1, "checks": os.path.join(a.out, "checks.json")},
                         ensure_ascii=False))
        return 1
    add("result_json_parses", True, "result.json 可解析")

    status = result.get("status")
    failed_run = status == "failed"
    missing = [k for k in REQUIRED if k not in result]
    add("required_keys_present", not missing,
        "字段齐全（含 contract_fields）" if not missing else "缺字段：%s" % ", ".join(missing))
    add("status_enum", status in {"success", "partial", "failed"},
        "status=%r" % status)

    nodes = result.get("nodes") if isinstance(result.get("nodes"), list) else []
    edges = result.get("edges") if isinstance(result.get("edges"), list) else []
    mindmap = result.get("mindmap") if isinstance(result.get("mindmap"), dict) else {}
    stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
    issues = [i for i in (result.get("issues") or []) if isinstance(i, dict)]
    hard_issues = [i for i in issues if i.get("severity") == "error"]

    add("nodes_nonempty", bool(nodes), "节点 %d 个" % len(nodes))
    add("node_count_consistent", mindmap.get("node_count") == len(nodes),
        "mindmap.node_count=%r 实际 nodes=%d" % (mindmap.get("node_count"), len(nodes)))
    add("edge_count_consistent", mindmap.get("edge_count") == len(edges),
        "mindmap.edge_count=%r 实际 edges=%d" % (mindmap.get("edge_count"), len(edges)))
    add("stats_consistent", stats.get("node_count") == len(nodes) and stats.get("edge_count") == len(edges),
        "stats node/edge=%r/%r" % (stats.get("node_count"), stats.get("edge_count")))

    add("node_count_target", len(nodes) >= 8,
        "节点 %d 个（建议 ≥8；材料过短时应如实标注而不是凑数）" % len(nodes), severity="warn")
    add("edge_count_target", len(edges) >= 5,
        "关系 %d 条（建议 ≥5）" % len(edges), severity="warn")
    add("tree_depth_target", (stats.get("max_depth") or 0) <= 6,
        "最大层级 %r（建议 ≤5）" % stats.get("max_depth"), severity="warn")

    bad_conf = [n.get("id") for n in nodes if n.get("confidence") not in {"fact", "summary", "inference"}]
    add("confidence_valid", not bad_conf,
        "全部节点含合法 confidence" if not bad_conf else "confidence 非法：%s" % bad_conf, severity="warn")
    bad_type = [n.get("id") for n in nodes if n.get("type") not in TYPES]
    add("node_types_known", not bad_type,
        "节点类型均在约定集合内" if not bad_type else "未知类型：%s" % bad_type, severity="warn")

    missing_ev = [n.get("id") for n in nodes
                  if n.get("confidence") in {"fact", "summary"}
                  and not ((n.get("evidence") or {}).get("quote") and (n.get("evidence") or {}).get("anchor"))]
    add("claims_have_evidence", not missing_ev,
        "fact/summary 节点均带 quote+anchor" if not missing_ev else "缺证据：%s" % missing_ev)

    inference_no_basis = [n.get("id") for n in nodes
                          if n.get("confidence") == "inference" and not (n.get("basis") or "").strip()]
    add("inference_has_basis", not inference_no_basis,
        "推断节点均写明依据" if not inference_no_basis else "缺依据：%s" % inference_no_basis)

    sources = load_json(a.sources, {}) or {}
    index = {}
    for doc in (sources.get("documents") or []):
        for para in (doc.get("paragraphs") or []):
            index[para.get("anchor")] = norm(para.get("text"))
    if index:
        mismatched = []
        for n in nodes:
            if n.get("confidence") not in {"fact", "summary"}:
                continue
            quote = (n.get("evidence") or {}).get("quote")
            declared = bool(n.get("verified"))
            if quote and verify_quote(quote, index) != declared:
                mismatched.append(n.get("id"))
        add("verified_flags_true", not mismatched,
            "verified 标记与源文一致" if not mismatched else "verified 标记与源文不符：%s" % mismatched)
    else:
        add("verified_flags_true", True, "未提供 sources.json，跳过引文复核", severity="warn")

    checked = [n for n in nodes if n.get("confidence") in {"fact", "summary"}]
    rate = round(sum(1 for n in checked if n.get("verified")) / float(len(checked)), 4) if checked else 0.0
    add("verification_rate_consistent", stats.get("verification_rate") == rate,
        "declared=%r recomputed=%r" % (stats.get("verification_rate"), rate))
    add("success_all_verified", status != "success" or rate == 1.0,
        "success 需要 100%% 引文核验，当前 %r" % rate)
    add("status_consistent", not (hard_issues and status == "success"),
        "status=%s 时仍有 %d 条硬问题" % (status, len(hard_issues)))
    add("issues_structured", all({"code", "severity", "detail"} <= set(i) for i in issues),
        "issues 均为 {code,severity,detail}")

    known = {n.get("id") for n in nodes}
    bad_edges = [e for e in edges if e.get("from") not in known or e.get("to") not in known]
    add("edge_endpoints_exist", not bad_edges,
        "关系端点均存在" if not bad_edges else "%d 条关系端点缺失" % len(bad_edges))
    bad_rel = [e for e in edges if e.get("relation") not in RELS]
    add("edge_relations_known", not bad_rel,
        "关系类型均在约定集合内" if not bad_rel else "未知关系：%s" % bad_rel, severity="warn")
    edge_no_basis = [e for e in edges if e.get("confidence") == "inference" and not (e.get("basis") or "").strip()]
    add("inference_edges_have_basis", not edge_no_basis,
        "推断关系均写明依据" if not edge_no_basis else "%d 条推断关系缺依据" % len(edge_no_basis))

    ev_index = result.get("evidence_index") if isinstance(result.get("evidence_index"), dict) else {}
    missing_index = [n.get("id") for n in checked
                     if (n.get("evidence") or {}).get("anchor") not in ev_index]
    add("evidence_index_complete", not missing_index,
        "每条带证据节点均进入 evidence_index" if not missing_index else "缺失：%s" % missing_index)

    files = mindmap.get("files") if isinstance(mindmap.get("files"), dict) else {}
    add("files_declared", bool(files), "声明产物 %d 个" % len(files))
    sizes = {}
    for key in ("markdown", "freemind", "svg", "csv"):
        path = files.get(key) or ""
        size = os.path.getsize(path) if path and os.path.isfile(path) else 0
        sizes[key] = size
        add("file_%s" % key, size > 0, "%s: %d bytes" % (path or "(未声明)", size))

    mm_path = files.get("freemind") or ""
    if os.path.isfile(mm_path):
        try:
            tree = ET.parse(mm_path)
            count = len(tree.getroot().findall(".//node"))
            add("freemind_parses", True, "mindmap.mm 可解析，节点 %d 个" % count)
            add("freemind_node_count", count == len(nodes),
                "mindmap.mm 节点 %d 个 vs result.nodes %d 个" % (count, len(nodes)))
        except Exception as exc:  # noqa: BLE001
            add("freemind_parses", False, "mindmap.mm 解析失败：%s" % exc)
    else:
        add("freemind_parses", False, "mindmap.mm 不存在")

    svg_path = files.get("svg") or ""
    if os.path.isfile(svg_path):
        try:
            ET.parse(svg_path)
            add("svg_parses", True, "mindmap.svg 是合法 XML")
        except Exception as exc:  # noqa: BLE001
            add("svg_parses", False, "mindmap.svg 解析失败：%s" % exc)
    else:
        add("svg_parses", False, "mindmap.svg 不存在")

    csv_path = files.get("csv") or ""
    if os.path.isfile(csv_path):
        with open(csv_path, encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        add("csv_row_count", len(rows) - 1 == len(nodes),
            "nodes.csv 数据行 %d vs 节点 %d" % (len(rows) - 1, len(nodes)))
    else:
        add("csv_row_count", False, "nodes.csv 不存在")

    md_path = files.get("markdown") or ""
    md_text = ""
    if os.path.isfile(md_path):
        with open(md_path, encoding="utf-8") as fh:
            md_text = fh.read()
    labels = [n.get("label") for n in nodes if n.get("label")]
    absent = [lb for lb in labels if lb not in md_text]
    add("markdown_covers_nodes", not absent,
        "mindmap.md 覆盖全部节点标签" if not absent else "缺少标签：%s" % absent[:5])
    hits = [p for p in PLACEHOLDERS if p in md_text]
    add("no_placeholders", not hits,
        "未出现占位残句" if not hits else "发现占位文本：%s" % hits)
    add("png_preview", bool(files.get("png") and os.path.isfile(files["png"])),
        "PNG 预览已生成" if files.get("png") else "无 PNG 预览（依赖 rsvg-convert/cairosvg，SVG 已交付）",
        severity="warn")

    keys = contract_keys(case)
    contract = result.get("contract_fields") if isinstance(result.get("contract_fields"), dict) else {}
    if keys:
        absent_keys = [k for k in keys if k not in contract]
        null_keys = [k for k in keys if contract.get(k) is None]
        add("contract_keys_present", not absent_keys,
            "output_contract 全字段存在（%d）" % len(keys) if not absent_keys
            else "缺契约字段：%s" % ", ".join(absent_keys))
        add("contract_keys_nonnull", not null_keys or failed_run,
            "全部契约字段已取值" if not null_keys else "契约字段为 null：%s" % ", ".join(null_keys),
            severity="warn" if failed_run else "hard")
        add("contract_fields_echo", all(result.get(k) == contract.get(k) for k in keys),
            "result.json 顶层与 contract_fields 一致")
    else:
        add("contract_keys_present", True, "case.json 未声明 output_contract", severity="warn")

    hard_failed = [c for c in checks if not c["ok"] and c["severity"] == "hard"]
    warn_failed = [c for c in checks if not c["ok"] and c["severity"] == "warn"]
    payload = {
        "ok": not hard_failed,
        "passed": len([c for c in checks if c["ok"]]),
        "failed": len(hard_failed),
        "warnings": len(warn_failed),
        "status": status,
        "case_id": result.get("case_id"),
        "issues": ["%s: %s" % (c["name"], c["detail"]) for c in hard_failed],
        "warnings_detail": ["%s: %s" % (c["name"], c["detail"]) for c in warn_failed],
        "checks": checks,
    }
    with open(os.path.join(a.out, "checks.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": payload["ok"], "passed": payload["passed"],
                      "failed": payload["failed"], "warnings": payload["warnings"],
                      "checks": os.path.join(a.out, "checks.json")}, ensure_ascii=False))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
