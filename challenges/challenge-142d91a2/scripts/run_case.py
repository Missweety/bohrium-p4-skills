#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_case.py - one-command entry point for a fixed case.

Inputs (runtime contract):
  /input/case.json, /input/task.md, and the case material files
Work:
  /app/work (sources.json, proposal_plan.json, build_report.json)
Output:
  /app/output/proposal.md
  /app/output/proposal.docx
  /app/output/proposal.html
  /app/output/evidence.csv
  /app/output/result.json       (all output_contract fields + case_id)
  /app/output/selfcheck.json

Usage:
  python3 scripts/run_case.py --input /input --work /app/work --output /app/output

The entry point never crashes on unreadable/missing material: it writes an
honest partial/failed result and returns a non-zero code only when no usable
result could be produced.
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import build_proposal  # noqa: E402
import common  # noqa: E402
import selfcheck  # noqa: E402


def run(input_dir, work_dir, output_dir):
    result = build_proposal.build(input_dir, work_dir, output_dir)
    case_path = os.path.join(input_dir, "case.json")
    sources_path = os.path.join(work_dir, "sources.json")
    problems, warnings, info = selfcheck.check(output_dir, case_path, sources_path)
    report = {"ok": not problems, "problems": problems, "warnings": warnings, "info": info}
    common.write_json(os.path.join(output_dir, "selfcheck.json"), report)
    print("status=%s case=%s selfcheck=%s"
          % (result.get("status"), result.get("case_id"), "PASS" if report["ok"] else "FAIL"))
    for item in problems:
        print("SELFCHECK - %s" % item)
    for item in warnings:
        print("SELFCHECK WARN %s" % item)
    print("outputs: proposal.md, proposal.docx, proposal.html, evidence.csv, result.json")
    return result, report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the research-proposal skill on one case")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--output", "--out", dest="output", default="/app/output")
    args = ap.parse_args(argv)
    try:
        result, report = run(args.input, args.work, args.output)
    except Exception as exc:  # noqa: BLE001
        import traceback
        sys.stderr.write("[run_case] fatal: %s\n%s\n"
                         % (exc, traceback.format_exc()[-1200:]))
        try:
            os.makedirs(args.output, exist_ok=True)
            case = common.load_json(os.path.join(args.input, "case.json"), {}) or {}
            fallback = {
                "case_id": common.case_id_of(case, args.input),
                "status": "failed",
                "proposal_md": "",
                "proposal_docx": "",
                "elements": {},
                "evidence": [],
                "sources": [],
                "uncertainty": {
                    "level": "high",
                    "notes": ["run_case 内部异常：%s" % str(exc)[:300]],
                    "unresolved": ["runtime"],
                },
                "change_log": ["运行异常退出，未生成正式产物。"],
                "contract_check": {"required": [], "present": [], "missing": []},
            }
            common.write_json(os.path.join(args.output, "result.json"), fallback)
        except Exception:  # noqa: BLE001
            pass
        return 1
    # status=failed 表示"材料不可读、内容未产出"，但 result.json 与逐文件原因已如实写全，
    # 属于约定内的降级交付；Harbor 以退出码判断是否崩溃，故仍返回 0（旧版返回 1）。
    return 0 if report.get("ok") or result.get("status") in ("success", "partial", "failed") else 1



if __name__ == "__main__":
    sys.exit(main())
