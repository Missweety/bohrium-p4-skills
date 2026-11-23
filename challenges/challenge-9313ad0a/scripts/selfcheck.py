#!/usr/bin/env python3
"""Independent self-check for the evidence-mindmap output.

Checks contract fields, deliverable presence, XML validity, node/edge integrity,
quote verification, and placeholder text. Writes /app/output/checks.json.

Usage: python3 selfcheck.py --case /input/case.json --out /app/output --plan /app/work/plan.json
"""
import argparse
import json
import os
import xml.etree.ElementTree as ET

REQUIRED = ["case_id", "status", "sources", "uncertainty", "change_log",
            "mindmap", "nodes", "edges", "evidence_index"]
PLACEHOLDERS = ["TODO", "PLACEHOLDER", "lorem ipsum", "待填写", "示例答案"]


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def contract_keys(case):
    oc = case.get("output_contract") if isinstance(case, dict) else None
    if isinstance(oc, dict):
        return list(oc.keys())
    if isinstance(oc, list):
        keys = []
        for item in oc:
            if isinstance(item, str):
                keys.append(item)
            elif isinstance(item, dict):
                keys.append(item.get("name") or item.get("field") or item.get("key"))
        return [k for k in keys if k]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--plan", default="/app/work/plan.json")
    a = ap.parse_args()
    checks, errors = [], []

    def add(name, ok, detail):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})
        if not ok:
            errors.append("%s: %s" % (name, detail))

    rj = os.path.join(a.out, "result.json")
    add("result_json_exists", os.path.exists(rj), rj)
    if not os.path.exists(rj):
        write_checks(a.out, checks, errors)
        raise SystemExit(1)
    result = load(rj)
    case = {}
    if os.path.exists(a.case):
        try:
            case = load(a.case)
        except Exception as exc:  # noqa: BLE001
            add("case_json_parses", False, str(exc)[:200])
    for key in REQUIRED:
        add("required_%s" % key, key in result, "present" if key in result else "missing")
    expected = case.get("case_id") or case.get("id")
    if expected:
        add("case_id_matches", result.get("case_id") == expected,
            "%r vs %r" % (result.get("case_id"), expected))
    for key in contract_keys(case):
        add("contract_%s" % key, key in result and result.get(key) is not None,
            "present" if key in result else "missing")
    add("status_valid", result.get("status") in {"success", "partial", "failed"},
        str(result.get("status")))
    issues = result.get("issues") or []
    add("status_consistent", not (issues and result.get("status") == "success"),
        "%d issues with status %s" % (len(issues), result.get("status")))

    deliverables = {"mindmap.md": ".md", "mindmap.mm": ".mm", "mindmap.svg": ".svg", "nodes.csv": ".csv"}
    for name, _ext in deliverables.items():
        path = os.path.join(a.out, name)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        add("file_%s" % name, size > 0, "%d bytes" % size)
    for name in ("mindmap.mm", "mindmap.svg"):
        path = os.path.join(a.out, name)
        if os.path.exists(path):
            try:
                ET.parse(path)
                add("xml_%s" % name, True, "parsed")
            except Exception as exc:  # noqa: BLE001
                add("xml_%s" % name, False, str(exc)[:160])
    svg = os.path.join(a.out, "mindmap.svg")
    if os.path.exists(svg):
        body = open(svg, encoding="utf-8", errors="replace").read()
        add("svg_has_text", "<text" in body and len(body) > 400, "%d chars" % len(body))

    nodes = result.get("nodes") or []
    edges = result.get("edges") or []
    add("node_count", len(nodes) >= 8, "%d nodes" % len(nodes))
    add("edge_count", len(edges) >= 5, "%d edges" % len(edges))
    checked = [n for n in nodes if n.get("confidence") in {"fact", "summary"}]
    verified = [n for n in checked if n.get("verified")]
    rate = (len(verified) / float(len(checked))) if checked else 1.0
    add("quote_verification", rate >= 0.8, "%.2f of %d checked" % (rate, len(checked)))
    ids = {n.get("id") for n in nodes}
    add("edge_endpoints", all(e.get("from") in ids and e.get("to") in ids for e in edges),
        "%d edges" % len(edges))

    plan = {}
    if os.path.exists(a.plan):
        try:
            plan = load(a.plan)
        except Exception:  # noqa: BLE001
            plan = {}
    for key in ("title", "purpose", "audience"):
        add("plan_%s" % key, bool((plan.get(key) or "").strip()), str(plan.get(key))[:60])

    joined = json.dumps(result, ensure_ascii=False).lower()
    hits = [p for p in PLACEHOLDERS if p.lower() in joined]
    add("no_placeholders", not hits, ",".join(hits))

    write_checks(a.out, checks, errors)
    passed = sum(1 for c in checks if c["passed"])
    print(json.dumps({"passed": passed, "total": len(checks), "errors": errors}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


def write_checks(out, checks, errors):
    os.makedirs(out, exist_ok=True)
    payload = {"passed": sum(1 for c in checks if c["passed"]), "total": len(checks),
               "errors": errors, "checks": checks}
    with open(os.path.join(out, "checks.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
