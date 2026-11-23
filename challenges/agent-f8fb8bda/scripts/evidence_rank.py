#!/usr/bin/env python3
"""evidence_rank.py - 按来源层级/直接性/研究设计/时效给证据分级，并检查子问题覆盖与冲突。

  python scripts/evidence_rank.py --table work/evidence_table.json --out work/evidence_rank.json
      [--as-of 2026] [--window 5]

输入 evidence_table.json:
  {"subquestions":[{"id":"Q1","text":"..."}],
   "evidence":[{"id":"E01","subq":"Q1","claim":"...","source_path":"lit/a.md","locator":"L12-15",
                "quote":"...","source_type":"peer_reviewed|conference|review|preprint|thesis|report|dataset|web",
                "directness":"direct|indirect|background","design":"experimental|rct|meta_analysis|cohort|modeling|none",
                "stance":"support|refute|mixed","year":2021}]}

缺 quote（<12 字符）或 locator 的证据判 X 不可采信；单一来源覆盖的子问题单独标出。
分级只是可复核的排序规则，不等于对研究质量的最终评价。
"""
import argparse
import json
import sys

BASE = {"peer_reviewed": 3.0, "conference": 2.5, "review": 2.0, "preprint": 2.0,
        "thesis": 1.5, "report": 1.5, "dataset": 1.5, "web": 0.5, "unknown": 0.0}
DIRECT = {"direct": 2.0, "indirect": 1.0, "background": 0.0}
DESIGN = {"experimental": 1.0, "rct": 1.0, "meta_analysis": 1.0, "cohort": 0.5, "modeling": 0.5}


def grade(score):
    if score >= 5.0:
        return "A"
    if score >= 3.5:
        return "B"
    if score >= 2.0:
        return "C"
    return "D"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--as-of", type=int, default=0)
    ap.add_argument("--window", type=int, default=5)
    a = ap.parse_args()

    data = json.load(open(a.table, encoding="utf-8"))
    subs = data.get("subquestions", []) or []
    items = data.get("evidence", []) or []
    as_of = a.as_of or max([e.get("year") or 0 for e in items] + [0])

    ranked, errors = [], []
    for e in items:
        quote = (e.get("quote") or "").strip()
        locator = (e.get("locator") or "").strip()
        score = BASE.get(str(e.get("source_type", "unknown")).lower(), 0.0)
        score += DIRECT.get(str(e.get("directness", "background")).lower(), 0.0)
        score += DESIGN.get(str(e.get("design", "none")).lower(), 0.0)
        year = e.get("year") or 0
        fresh = bool(year and as_of and 0 <= as_of - year <= a.window)
        score += 0.5 if fresh else 0.0
        ok = len(quote) >= 12 and bool(locator)
        g = grade(score) if ok else "X"
        if not ok:
            errors.append({"id": e.get("id"), "reason": "quote<12 或 locator 缺失，不可采信"})
        ranked.append({"id": e.get("id"), "subq": e.get("subq"), "claim": e.get("claim"),
                       "source_path": e.get("source_path"), "locator": locator, "quote": quote,
                       "source_type": e.get("source_type", "unknown"),
                       "directness": e.get("directness"), "design": e.get("design"),
                       "stance": e.get("stance", "support"), "year": year,
                       "score": round(score, 2), "fresh": fresh, "grade": g,
                       "admissible": ok})
    order = {"A": 0, "B": 1, "C": 2, "D": 3, "X": 4}
    ranked.sort(key=lambda r: (str(r["subq"]), order[r["grade"]]))

    coverage = []
    for s in subs:
        rows = [r for r in ranked if r["subq"] == s["id"] and r["admissible"]]
        best = min([r["grade"] for r in rows], key="ABCD".index) if rows else None
        verdict = "not_covered" if not rows else ("covered" if best in ("A", "B") else "weak")
        sources = sorted({r["source_path"] for r in rows})
        stances = {r["stance"] for r in rows if "ABCD".index(r["grade"]) <= 1}
        # mixed 表示同一材料内部结论不一致，也应作为冲突暴露；
        # 只认 support+refute 会漏掉「一项支持、一项 mixed」这类真实分歧。
        conflict = "mixed" in stances or {"support", "refute"} <= stances
        coverage.append({"subq": s["id"], "text": s.get("text"), "evidence_count": len(rows),
                         "best_grade": best, "verdict": verdict,
                         "distinct_sources": len(sources),
                         "single_source": len(sources) == 1,
                         "conflict": conflict})
    conflicts = [{"subq": c["subq"], "sources": sorted({r["source_path"] for r in ranked
                                                        if r["subq"] == c["subq"]})}
                 for c in coverage if c["conflict"]]
    report = {"as_of": as_of, "window": a.window, "evidence_total": len(ranked),
              "inadmissible": errors, "grade_counts": {g: sum(1 for r in ranked if r["grade"] == g)
                                                      for g in "ABCXD"},
              "coverage": coverage, "conflicts": conflicts,
              "gaps": [c["subq"] for c in coverage if c["verdict"] == "not_covered"],
              "single_source_subqs": [c["subq"] for c in coverage if c["single_source"]],
              "ranked": ranked, "verdict": "pass" if not errors else "review"}
    json.dump(report, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("verdict=%s evidence=%d grades=%s covered=%d/%d gaps=%d conflicts=%d inadmissible=%d"
          % (report["verdict"], len(ranked), report["grade_counts"],
             sum(1 for c in coverage if c["verdict"] == "covered"), len(coverage),
             len(report["gaps"]), len(conflicts), len(errors)))
    for e in errors:
        print("  !", e["id"], e["reason"])
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
