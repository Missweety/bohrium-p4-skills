#!/usr/bin/env python3
"""kernel.py - case contract reader and output checker for research synthesis skills."""
import argparse
import json
import os
import sys

ALIASES = {
    "case_id": ["case_id", "id", "caseId", "task_id"],
    "task": ["task", "instruction", "question", "prompt", "goal", "research_question"],
    "materials": ["materials", "files", "documents", "literature", "corpus", "inputs", "papers"],
    "research_question": ["research_question", "question", "topic", "question_text", "goal"],
    "output_contract": ["output_contract", "outputContract", "expected_output", "schema"],
}


def load(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return json.load(fh)


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def pick(case, key):
    for name in ALIASES.get(key, [key]):
        for k in case:
            if k.lower().replace("-", "_") == name.lower().replace("-", "_") and case[k] not in (None, "", [], {}):
                return case[k]
    return None


def find_case(explicit=None):
    for c in ([explicit] if explicit else []) + ["/input/case.json", "case.json", "/app/input/case.json"]:
        if c and os.path.exists(c):
            return c
    return None


def init(a):
    path = find_case(a.case)
    if not path:
        dump({"status": "blocked", "missing": "case.json not found"}, os.path.join(a.out, "contract.json"))
        return 1
    case = load(path)
    contract = pick(case, "output_contract") or {}
    dump({"case_path": os.path.abspath(path),
          "case_id": pick(case, "case_id") or os.path.splitext(os.path.basename(path))[0],
          "question": pick(case, "research_question"),
          "contract": contract if isinstance(contract, (dict, list)) else {"value": contract}}, os.path.join(a.out, "contract.json"))
    dump(case, os.path.join(a.out, "case.raw.json"))
    print("case=%s contract_fields=%s" % (os.path.basename(path),
                                          ",".join(contract) if isinstance(contract, dict) else "list"))
    return 0


def check(a):
    problems = []
    rp = os.path.join(a.out, "result.json")
    if not os.path.exists(rp):
        problems.append("result.json missing")
    else:
        res = load(rp)
        zero_evidence = (res.get("counts") or {}).get("included") == 0 \
            and res.get("status") in {"partial", "blocked"}
        for k in ("case_id", "status", "research_product"):
            if k not in res:
                problems.append("missing field %s" % k)
        if not res.get("evidence_matrix") and not zero_evidence:
            problems.append("empty evidence_matrix")
        if res.get("status") not in {"ok", "success", "partial", "blocked"}:
            problems.append("bad status")
        metrics = (res.get("checks") or {}).get("metrics") or {}
        if metrics and not all(metrics.values()) and not zero_evidence:
            problems.append("failed checks: %s" % [k for k, v in metrics.items() if not v])
    for f in ("report.md", "matrix.csv"):
        if not os.path.exists(os.path.join(a.out, f)):
            problems.append("missing %s" % f)
    print("PASS" if not problems else "FAIL")
    for p in problems:
        print(" -", p)
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--case"); p.add_argument("--out", default="work"); p.set_defaults(fn=init)
    p = sub.add_parser("check"); p.add_argument("--out", default="/app/output"); p.set_defaults(fn=check)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
