#!/usr/bin/env python3
"""run_case.py - 一条命令完成候选筛选：契约 → 材料索引 → 相关性打分/去重/排序 → 交付与自检。

  python scripts/run_case.py --case /input/case.json --materials /input \
      --work /app/work --out /app/output

只用标准库；候选集为空时写 status=blocked，不补造文献。退出码恒为 0。
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def run(script, *args):
    cmd = [sys.executable, os.path.join(HERE, script)] + [str(x) for x in args]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE, timeout=600)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def blocked(case_id, summary, limits):
    return {"case_id": case_id, "status": "blocked", "summary": summary,
            "retrieval_scope": {}, "query_terms": {}, "relevance_rubric": {},
            "dedup_summary": {}, "ranked_candidates": [], "screening_decisions": [],
            "conflict_resolution": [], "recall_check": {}, "stability_check": {},
            "exclusions": [], "evidence_map": [], "assumptions": [],
            "validation": {"checks": []}, "uncertainty": [summary],
            "limits": limits, "changes": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--materials", default="/input")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    a = ap.parse_args()
    a.case, a.materials = os.path.abspath(a.case), os.path.abspath(a.materials)
    a.work, a.out = os.path.abspath(a.work), os.path.abspath(a.out)
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    logs = []

    rc, log = run("kernel.py", "init", "--case", a.case, "--out", a.work)
    logs.append(log)
    contract = load(os.path.join(a.work, "contract.json"), {})
    case_id = contract.get("case_id") or os.path.splitext(os.path.basename(a.case))[0]
    if rc != 0:
        dump(blocked(case_id, "case.json 缺失或不可读", "case.json 缺失或不可读"),
             os.path.join(a.out, "result.json"))
        print("blocked: case.json")
        return 0

    rc, log = run("kernel.py", "index", "--materials", a.materials, "--out", a.work)
    logs.append(log)

    rc, log = run("rank.py", "--case", a.case, "--materials", a.materials, "--work", a.work)
    logs.append(log)
    if rc != 0 or not os.path.exists(os.path.join(a.work, "draft.json")):
        dump(blocked(case_id, "筛选脚本未能产出 draft", "rank.py 失败，未见草稿"),
             os.path.join(a.out, "result.json"))
        print("blocked: rank")
        return 0

    rc, log = run("kernel.py", "emit", "--draft", os.path.join(a.work, "draft.json"),
                  "--contract-dir", a.work, "--out", a.out)
    logs.append(log)
    rc2, log2 = run("kernel.py", "check", "--out", a.out, "--contract-dir", a.work)
    logs.append(log2)
    with open(os.path.join(a.work, "run_log.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(logs))
    print("PASS" if rc2 == 0 else "CHECK_FAIL")
    print("result=%s" % os.path.join(a.out, "result.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
