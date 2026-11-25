#!/usr/bin/env python3
"""run_case.py - 一条命令完成方案比较：契约 → 材料索引 → 统一字段 → 硬门控 → 评分/选择 → 复算。

  python scripts/run_case.py --case /input/case.json --materials /input \
      --work /app/work --out /app/output

只用标准库。材料为空/不可读时写 status=blocked 并说明缺什么。退出码恒为 0（除非目录不可写）。
"""
import argparse
import hashlib
import json
import os
import shutil
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
    p = subprocess.run([sys.executable, os.path.join(HERE, script)] + [str(x) for x in args],
                       capture_output=True, text=True, cwd=HERE, timeout=600)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def write_blocked(a, contract, case_id, summary, limits):
    """blocked 也要回填契约字段并给出原因，而不是只丢一份最小 JSON。"""
    fields = {"recommendation": {"choice": "blocked", "plan_id": None, "rationale": summary,
                                 "rejected": [], "sensitivity": []},
              "comparison_matrix": [], "plans": [], "criteria": [], "scoring": {}, "cost_model": {},
              "risks": [], "exceptions": [{"case": "输入不可用", "action": limits}],
              "confirmations": [], "evidence_map": [], "assumptions": [],
              "variables": [], "controls": [], "procedure": [], "parameters": [],
              "resources": [], "readout": [],
              "validation": {"checks": [{"check": "输入可用性", "result": "FAIL", "detail": limits}],
                             "arithmetic_recomputed": False, "rerun": "材料补齐后重跑"},
              "uncertainty": [summary], "limits": limits, "changes": []}
    draft = {"status": "blocked", "fields": fields, "limits": limits, "uncertainty": [summary],
             "input_mode": "unavailable",
             "input_versions": {"case.json": contract.get("case_sha1"),
                                "contract_source": contract.get("contract_source")},
             "sources": [], "self_check": {"plans": 0, "survivors": 0, "selected": None},
             "determinism": {"runs": 0, "consistent": None,
                             "note": "blocked before comparison; rerun after inputs are available"},
             "artifacts": {
                 "comparison_report.md": "# 实验方案比较与选择\n\n状态：blocked\n\n- %s\n" % limits,
                 "comparison_matrix.csv": ("plan,source,objective,variables,controls,procedure,"
                                           "parameters,resources,readout,cost_known,currency,"
                                           "time_days,feasible,weighted\n")}}
    dump(draft, os.path.join(a.work, "draft.json"))
    run("kernel.py", "emit", "--draft", os.path.join(a.work, "draft.json"),
        "--contract-dir", a.work, "--out", a.out)
    run("kernel.py", "check", "--out", a.out, "--contract-dir", a.work)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--materials", default="/input")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--budget", type=float, default=None)
    ap.add_argument("--window", type=float, default=None)
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
        write_blocked(a, contract, case_id, "case.json 缺失或不可读", "case.json 缺失或不可读")
        print("blocked: case.json")
        return 0

    rc, log = run("kernel.py", "index", "--materials", a.materials, "--out", a.work)
    logs.append(log)
    ev = load(os.path.join(a.work, "evidence.json"), {})

    def runtime_file(p):
        ap = os.path.abspath(p)
        return ap.startswith(a.work + os.sep) or ap.startswith(a.out + os.sep)

    docs = [f for f in ev.get("files", [])
            if not runtime_file(f.get("path", ""))
            and os.path.basename(f.get("path", "")).lower() not in ("case.json", "case.raw.json", "task.md")]
    usable = [f for f in docs if f.get("readable") and f.get("chars", 0) > 20
              and os.path.basename(f.get("path", "")).lower().endswith(
                  (".md", ".txt", ".docx", ".pdf", ".csv", ".tsv", ".xlsx", ".json", ".yaml", ".yml"))]
    structured = int(contract.get("structured_candidates") or 0)
    if rc != 0 or (not usable and structured < 1):
        # 结构化候选本身就是真实输入（平台 case.json 常把 3 个候选放在 candidate_plans）
        write_blocked(a, contract, case_id,
                      "材料目录为空或不可读，且 case.json 未提供结构化候选",
                      "材料目录为空或不可读，且 case.json 未提供结构化候选")
        print("blocked: materials")
        return 0

    args = ["--work", a.work]
    if a.budget is not None:
        args += ["--budget", a.budget]
    if a.window is not None:
        args += ["--window", a.window]
    rc, log = run("plan_compare.py", *args)
    logs.append(log)
    draft_path = os.path.join(a.work, "draft.json")
    if rc != 0 or not os.path.exists(draft_path):
        write_blocked(a, contract, case_id, "比较脚本未能产出 draft", "plan_compare.py 失败，未见草稿")
        print("blocked: compare")
        return 0

    # 重跑一致性：同一输入与参数跑两次，比较草稿与矩阵哈希（不改变最终交付，只留证据）
    def sha(path):
        with open(path, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()

    h1 = sha(draft_path)
    csv1 = sha(os.path.join(a.work, "comparison_matrix.csv")) \
        if os.path.exists(os.path.join(a.work, "comparison_matrix.csv")) else None
    rc2, log2 = run("plan_compare.py", *args)
    logs.append(log2)
    h2 = sha(draft_path) if os.path.exists(draft_path) else None
    csv2 = sha(os.path.join(a.work, "comparison_matrix.csv")) \
        if os.path.exists(os.path.join(a.work, "comparison_matrix.csv")) else None
    combined = hashlib.sha1()
    combined.update(str(contract.get("case_sha1") or "").encode())
    for f in ev.get("files", []):
        combined.update(str(f.get("sha1") or "").encode())
    determinism = {"input_sha1": combined.hexdigest(),
                   "run1_draft_sha1": h1, "run2_draft_sha1": h2,
                   "run1_matrix_sha1": csv1, "run2_matrix_sha1": csv2,
                   "consistent": bool(h1 and h1 == h2 and csv1 == csv2),
                   "runs": 2, "params": {"budget": a.budget, "window": a.window}}
    dump(determinism, os.path.join(a.work, "determinism.json"))

    if os.path.exists(os.path.join(a.work, "comparison_matrix.csv")):
        shutil.copy(os.path.join(a.work, "comparison_matrix.csv"),
                    os.path.join(a.out, "comparison_matrix.csv"))
    run("kernel.py", "emit", "--draft", draft_path,
        "--contract-dir", a.work, "--out", a.out)
    rc3, log3 = run("kernel.py", "check", "--out", a.out, "--contract-dir", a.work)
    logs.append(log3)
    with open(os.path.join(a.work, "run_log.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(logs))
    print("PASS" if rc3 == 0 else "CHECK_FAIL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
