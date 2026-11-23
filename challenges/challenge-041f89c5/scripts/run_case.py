#!/usr/bin/env python3
"""run_case.py - 一条命令完成选题拆解→纳排→证据矩阵→创新判定→可行性→冲突与空白。

  python scripts/run_case.py --case /input/case.json --materials /input \
      --work /app/work --out /app/output

只用标准库，不联网。无来源时 status=blocked，不产出评估结论。退出码恒为 0。
"""
import argparse
import csv
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core  # noqa: E402


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def write_csv(path, header, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in header})


def build(case_path, materials):
    case = core.load_case(case_path, materials)
    entries = core.index_files(materials)
    sources, skipped = core.build_sources(entries)
    problem = core.decompose(case)
    crit = core.criteria_from_case(case)
    concepts = core.concept_terms(case)
    decisions = core.screen_sources(sources, crit, concepts)
    matrix = core.extract_matrix(sources, decisions, concepts)
    claims = core.collect_claims(case)
    novelty = core.novelty_assess(case, claims, sources, decisions, matrix)
    feas = core.feasibility_assess(case, sources, decisions)
    conflicts = core.detect_conflicts(sources, decisions, matrix)
    gaps = core.research_gaps(novelty, matrix, feas)

    included = [d for d in decisions if d["decision"] == "include"]
    maybe = [d for d in decisions if d["decision"] == "maybe"]
    excluded = [d for d in decisions if d["decision"] == "exclude"]
    bad_src = [s["source_id"] for s in sources if s.get("permission") != "readable" or
               any("unavailable" in d for d in s.get("diagnostics") or [])]
    unresolved = [c for c in conflicts if c.get("unresolved")]
    unknown_nov = [n for n in novelty if n["verdict"] == "unknown"]
    missing = problem.get("missing") or []
    if not sources:
        matrix, novelty, gaps = [], [], []
        feas = {"conclusion": "unknown", "reason": "没有可读来源，无法核查可行性前提",
                "conditions": [], "premises": feas.get("premises") or [], "risks": []}
        unknown_nov = []

    if not sources:
        status = "blocked"
    elif missing or unknown_nov or feas["conclusion"] == "unknown" or unresolved or \
            not novelty or bad_src:
        status = "partial"
    else:
        status = "ok"

    limits = ["新颖性只在给定来源范围内判断，不构成全局'首次'或'尚无人研究'结论。",
              "证据矩阵为线索句摘录，not_reported 不等于原文献没有做；同义改写可能漏检。",
              "可行性结论依赖案例前提；未提供的前提一律 unknown，不代填。"]
    if status == "blocked":
        limits.insert(0, "没有可读来源，无法产出评估结论。")
    elif status == "partial":
        limits.insert(0, "存在问题要素缺失、未知创新判定、未决冲突或不可读来源，已逐条列明，未按完成处理。")
    if not novelty:
        limits.append("案例未提供可判定的创新陈述（novelty=[]），未自行编造。")
    if not matrix:
        limits.append("没有任何来源进入证据矩阵，比较与创新判定失去证据基础。")

    uncertainty = []
    if missing:
        uncertainty.append("问题要素缺失：%s（已置 undefined/needs_input）" % ", ".join(missing))
    if not claims:
        uncertainty.append("未提供创新陈述，无法判定创新点")
    for n in unknown_nov:
        uncertainty.append("%s 创新判定为 unknown：%s" % (n["claim_id"], n["verdict_reason"]))
    for c in unresolved:
        uncertainty.append("结论冲突未决：%s" % c["note"])
    for s in sources:
        for d in s.get("diagnostics") or []:
            uncertainty.append("%s：%s" % (s["file"], d))
    for s in skipped:
        uncertainty.append("跳过 %s（%s）" % (s["file"], s["reason"]))
    for d in decisions:
        if d["reason_code"] in ("REV_YEAR_MISSING", "REV_METADATA_INCOMPLETE"):
            uncertainty.append("%s 元数据不全：%s" % (d["title"], d["reason"]))

    scope = {
        "sources_total": len(sources),
        "included": len(included), "maybe": len(maybe), "excluded": len(excluded),
        "criteria": crit,
        "concept_terms": sorted(concepts)[:40],
        "databases": sorted({(s.get("provenance") or [{}])[0].get("file") for s in sources}),
        "note": "只对本目录提供的来源负责；未联网检索，也未使用平台外数据库。",
    }

    src_out = []
    for s in sources:
        src_out.append({"source_id": s["source_id"], "file": s["file"],
                        "locator": s["locator"], "sha256": s["sha256"],
                        "title": s["title"], "authors": s["authors"], "year": s["year"],
                        "venue": s["venue"], "doi": s["doi"], "type": s["type"],
                        "language": s["language"],
                        "abstract": (s.get("abstract") or "")[:1200],
                        "text_chars": len(s.get("text") or ""),
                        "permission": s.get("permission"),
                        "provenance": s.get("provenance") or [],
                        "diagnostics": s.get("diagnostics") or []})

    result = {
        "case_id": case["case_id"],
        "status": status,
        "summary": ("来源 %d（纳入 %d / 待定 %d / 排除 %d）；创新陈述 %d 条；"
                    "可行性 %s；冲突 %d 条"
                    % (len(sources), len(included), len(maybe), len(excluded),
                       len(novelty), feas["conclusion"], len(conflicts))),
        "problem_statement": problem,
        "scope": scope,
        "sources": src_out,
        "screening": decisions,
        "reason_codes": core.REASON_CODES,
        "evidence_matrix": matrix,
        "novelty": novelty,
        "feasibility": feas,
        "conflicts": conflicts,
        "gaps": gaps,
        "uncertainty": uncertainty,
        "limits": limits,
        "assumptions": ["材料目录即本次证据范围", "字段抽取为摘录式线索句",
                        "未提供的前提按 unknown 处理", "颜色/领域标签不作为事实依据"],
        "validation": {"checks": []},
        "changes": [],
        "_contract_fields": case["contract_fields"],
    }
    result["validation"]["checks"] = core.validate(result)
    result = core.finalize_contract(result, case["contract_fields"])
    result["validation"]["checks"] = core.validate(result)
    result.pop("_contract_fields", None)
    return result


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
    try:
        result = build(a.case, a.materials)
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        blocked = {"case_id": os.path.basename(a.materials) or "case", "status": "blocked",
                   "summary": "运行异常，未产出评估结论",
                   "problem_statement": {}, "scope": {}, "sources": [], "screening": [],
                   "reason_codes": core.REASON_CODES, "evidence_matrix": [], "novelty": [],
                   "feasibility": {"conclusion": "unknown", "premises": [], "risks": []},
                   "conflicts": [], "gaps": [], "uncertainty": ["运行异常"],
                   "limits": ["运行异常，结果不完整"],
                   "assumptions": [], "validation": {"checks": []}, "changes": []}
        dump(blocked, os.path.join(a.out, "result.json"))
        print("BLOCKED")
        return 0

    dump(result, os.path.join(a.out, "result.json"))
    write_csv(os.path.join(a.out, "evidence_matrix.csv"),
              ["source_id", "title", "year", "comparability", "task", "method", "data",
               "evaluation", "conclusion", "file", "locator", "extraction",
               "comparability_reason"],
              [{"source_id": m["source_id"], "title": m.get("title"), "year": m.get("year"),
                "comparability": m.get("comparability"), "task": m.get("task"),
                "method": m.get("method"), "data": m.get("data"),
                "evaluation": m.get("evaluation"), "conclusion": m.get("conclusion"),
                "file": m.get("file"), "locator": json.dumps(m.get("locator"), ensure_ascii=False),
                "extraction": m.get("extraction"),
                "comparability_reason": m.get("comparability_reason")}
               for m in result["evidence_matrix"]])
    write_csv(os.path.join(a.out, "novelty.csv"),
              ["claim_id", "claim", "type", "verdict", "coverage_ratio", "nearest",
               "scope", "needs_human", "verdict_reason"],
              [{"claim_id": n["claim_id"], "claim": n["claim"], "type": n["type"],
                "verdict": n["verdict"], "coverage_ratio": n["coverage_ratio"],
                "nearest": ";".join(x["source_id"] for x in n["nearest"]),
                "scope": n["scope"], "needs_human": n["needs_human"],
                "verdict_reason": n["verdict_reason"]} for n in result["novelty"]])
    write_csv(os.path.join(a.out, "feasibility.csv"),
              ["premise_id", "premise", "category", "status", "source_file", "source_quote",
               "impact", "mitigation"],
              [{"premise_id": r["premise_id"], "premise": r["premise"],
                "category": r["category"], "status": r["status"],
                "source_file": ((r.get("source") or {}).get("file") or
                                ("case:assumption" if (r.get("source") or {}).get("assumption")
                                 else "")),
                "source_quote": (r.get("source") or {}).get("quote"),
                "impact": r["impact"], "mitigation": r["mitigation"]}
               for r in result["feasibility"].get("premises") or []])
    write_csv(os.path.join(a.out, "conflicts.csv"),
              ["type", "sources", "adjudication", "unresolved", "note", "quotes"],
              [{"type": c["type"], "sources": ";".join(c["sources"]),
                "adjudication": c["adjudication"], "unresolved": c["unresolved"],
                "note": c["note"],
                "quotes": json.dumps(c["quotes"], ensure_ascii=False)}
               for c in result["conflicts"]])
    with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(core.markdown_report(result))
    dump({"version": core.VERSION, "generated_at": core.now_iso(),
          "case_id": result["case_id"], "status": result["status"],
          "inputs": [{"path": e["path"], "sha256": e["sha256"]}
                     for e in core.index_files(a.materials)],
          "counts": {"sources": len(result["sources"]),
                     "included": sum(1 for d in result["screening"] if d["decision"] == "include"),
                     "novelty": len(result["novelty"]),
                     "conflicts": len(result["conflicts"])},
          "validation": result["validation"]},
         os.path.join(a.out, "run_manifest.json"))
    with open(os.path.join(a.work, "run_summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"status": result["status"], "screening": result["screening"],
                   "novelty": result["novelty"]}, fh, ensure_ascii=False, indent=1)
    ok = all(c["pass"] for c in result["validation"]["checks"])
    print("PASS" if ok and result["status"] != "blocked" else
          ("BLOCKED" if result["status"] == "blocked" else "CHECK_FAIL"))
    print("status=%s sources=%d matrix=%d novelty=%d feasibility=%s"
          % (result["status"], len(result["sources"]), len(result["evidence_matrix"]),
             len(result["novelty"]), result["feasibility"]["conclusion"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
