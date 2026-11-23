#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_run_case.py - 文献问答赛道的一键入口（打包时落为 scripts/run_case.py）。

一次调用完成：读 /input → 生成候选 → 写 /app/output/result.json → 独立复核。

Agent 的请求预算有限，分步命令容易把预算耗在探索上，所以入口脚本要能
一次跑完「机器该做的部分」：候选生成是机器的活，答案文本是模型的活。

流程：
    1. lane_qa.py    —— 候选生成 + 骨架 result.json（每个问题一项，不省略）
    2. 若 result.json 里已有答案（模型已写回），跑 qa_review.py 独立复核
    3. 若还没有答案，只输出复核提示，不报错退出

任何异常都 exit 0，把失败原因写进 result.json 的 uncertainty。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def _run(args):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description="文献问答一键入口")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--output", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    args = ap.parse_args(argv)

    out_dir, work_dir = args.output, args.work
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    result_path = os.path.join(out_dir, "result.json")

    rc, log = _run([sys.executable, os.path.join(HERE, "lane_qa.py"),
                    "--input", args.input, "--output", out_dir, "--work", work_dir])
    sys.stderr.write(log)

    if not os.path.isfile(result_path):
        # lane_qa 没能写出结果：如实记录，不伪造
        fail = {
            "case_id": "",
            "paper_id": "",
            "material_version": "",
            "status": "failed",
            "answers": [],
            "coverage": {"read_sections": [], "unread_sections": [],
                         "reasons": ["候选生成阶段未能写出 result.json"]},
            "sources": [],
            "uncertainty": {"level": "high",
                            "notes": ["候选生成阶段失败，请检查输入目录结构"],
                            "unresolved": []},
            "change_log": ["run_case.py 调用 lane_qa.py 失败（exit=%d）" % rc],
        }
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump(fail, fh, ensure_ascii=False, indent=2)
        return 0

    # 已有答案 → 跑独立复核；没有 → 只提示
    try:
        with open(result_path, "r", encoding="utf-8") as fh:
            result = json.load(fh)
    except Exception:
        result = {}
    answers = result.get("answers") or []
    answered = any(isinstance(a, dict) and (a.get("answer") or "").strip()
                   for a in answers)

    if answered:
        rc2, log2 = _run([sys.executable, os.path.join(HERE, "qa_review.py"),
                          "--result", result_path,
                          "--context", os.path.join(work_dir, "qa_context.json"),
                          "--out", os.path.join(work_dir, "qa_review.json")])
        sys.stderr.write(log2)
        try:
            with open(result_path, "r", encoding="utf-8") as fh:
                result = json.load(fh)
            clog = result.get("change_log")
            if isinstance(clog, list):
                clog.append("运行 qa_review.py 独立复核（exit=%d）" % rc2)
            with open(result_path, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass
    else:
        sys.stderr.write(
            "[run_case] 骨架已生成，尚未写入答案；"
            "请逐题复核候选并填入 answer/conditions/claims，"
            "然后再跑 scripts/qa_review.py 独立复核。\n")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.stderr.write("[run_case] fatal:\n%s\n" % traceback.format_exc())
        sys.exit(0)
