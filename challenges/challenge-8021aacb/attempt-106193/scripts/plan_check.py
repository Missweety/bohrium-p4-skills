#!/usr/bin/env python3
"""plan_check.py - gate (and optionally repair) the structure-edit plan before delivery.

Two modes:
  strict (default)  exit 1 on any violation. Use for authoring/CI.
  --sanitize        drop unverifiable findings instead of aborting the whole delivery,
                    fill mandatory bookkeeping (paragraph_map/coverage/source_map) from the
                    actual manuscript, and write a deliverable draft to --out-draft.
                    Exit 0 when a genuine plan remains, 1 when nothing verifiable remains.

Checks:
  * six coverage dimensions checked with integer findings;
  * diagnosis ids unique, enums valid, anchor_quote verbatim in the corpus;
  * issue <-> edit two-way linkage, action enum, executable fields;
  * paragraph_map covers every paragraph from structure_probe (no silent omission);
  * outline order unique, paragraph refs resolve;
  * fact_guard clean; source_map carries a locator.

Usage:
  python plan_check.py --draft work/draft.json --corpus work/corpus.txt \
      --structure work/structure.json --out work
  python plan_check.py ... --sanitize --out-draft work/draft.sanitized.json
"""
import argparse
import json
import os
import re
import sys

DIMS = ["rq_alignment", "section_structure", "argument_chain", "paragraph_relation",
        "repetition", "conclusion_boundary"]
DIMS_SET = set(DIMS)
ACTIONS = {"MOVE", "MERGE", "SPLIT", "REORDER", "ADD_EVIDENCE", "NARROW",
           "DELETE_REDUNDANCY", "REWRITE_TRANSITION", "FLAG_GAP"}
LEVELS = {"high", "medium", "low"}
PSTATUS = {"kept", "moved", "merged", "split", "removed", "added_placeholder"}
WS = re.compile(r"\s+")


def norm(s):
    return WS.sub(" ", str(s or "")).strip().lower()


def load(path, default):
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return default
    return default


def merged_plan(draft):
    plan = dict(draft.get("fields") or {})
    for k, v in draft.items():
        if k != "fields":
            plan.setdefault(k, v)
    return plan


def known_paragraphs(structure):
    return {p.get("paragraph_id"): p for p in structure.get("paragraphs", []) if p.get("paragraph_id")}


def evaluate(plan, corpus, paras, inferred_ok=False):
    E, W = [], []
    cov = plan.get("coverage") or {}
    for d in DIMS:
        c = cov.get(d) or {}
        if not c.get("checked"):
            E.append("coverage.%s not checked" % d)
        if not isinstance(c.get("findings"), int):
            E.append("coverage.%s findings must be an integer" % d)
    for sec in ("read_sections", "unread_sections"):
        if sec not in cov:
            W.append("coverage.%s missing (needed to state what was read)" % sec)
    if cov.get("unread_sections"):
        W.append("unread sections declared: %s" % cov.get("unread_sections"))

    diags = plan.get("diagnosis") or []
    ids, dim_findings = set(), {d: 0 for d in DIMS}
    for x in diags:
        iid = x.get("issue_id")
        if not iid:
            E.append("diagnosis entry without issue_id")
            continue
        if iid in ids:
            E.append("duplicate issue_id %s" % iid)
        ids.add(iid)
        dim = x.get("dimension")
        if dim not in DIMS_SET:
            E.append("issue %s invalid dimension: %s" % (iid, dim))
        else:
            dim_findings[dim] += 1
        for key, allow in (("severity", LEVELS), ("confidence", LEVELS)):
            if x.get(key) not in allow:
                E.append("issue %s invalid %s: %s" % (iid, key, x.get(key)))
        for key in ("problem", "why"):
            if not str(x.get(key, "")).strip():
                E.append("issue %s missing %s" % (iid, key))
        loc = x.get("location") or {}
        pid = loc.get("paragraph_id")
        if pid and paras and pid not in paras:
            E.append("issue %s location paragraph %s not in structure.json" % (iid, pid))
        q = loc.get("anchor_quote") or x.get("anchor_quote")
        if q:
            probe = norm(q)[:40]
            if corpus and probe not in corpus:
                E.append("issue %s anchor_quote not verbatim in source" % iid)
            elif not corpus:
                E.append("issue %s anchor_quote unverifiable: corpus empty" % iid)
        elif not pid:
            E.append("issue %s has neither paragraph_id nor anchor_quote (not locatable)" % iid)
    for d, n in dim_findings.items():
        claimed = (cov.get(d) or {}).get("findings")
        if isinstance(claimed, int) and claimed != n:
            W.append("coverage.%s findings=%d but diagnosis has %d" % (d, claimed, n))
    if not diags and not cov.get("no_issues_found"):
        E.append("diagnosis empty and no_issues_found not declared")

    edits = plan.get("edit_plan") or []
    if not edits and not cov.get("no_issues_found"):
        E.append("edit_plan empty: no executable action")
    per_issue, eids = {}, set()
    for x in edits:
        eid, iid = x.get("edit_id"), x.get("issue_id")
        if not eid:
            E.append("edit entry without edit_id")
        elif eid in eids:
            E.append("duplicate edit_id %s" % eid)
        eids.add(eid)
        if iid not in ids:
            E.append("edit %s links to unknown issue %s" % (eid, iid))
        else:
            per_issue[iid] = per_issue.get(iid, 0) + 1
        if x.get("action") not in ACTIONS:
            E.append("edit %s invalid action: %s" % (eid, x.get("action")))
        pid = (x.get("target") or {}).get("paragraph_id")
        if pid and paras and pid not in paras:
            E.append("edit %s target paragraph %s not in structure.json" % (eid, pid))
        for key in ("instruction", "preserves", "expected_effect"):
            if not str(x.get(key, "")).strip():
                E.append("edit %s missing %s" % (eid, key))
    for iid in ids:
        if not per_issue.get(iid):
            E.append("issue %s has no edit action" % iid)

    pmap = plan.get("paragraph_map") or []
    if not pmap and paras:
        E.append("paragraph_map empty: paragraph destinations are not traceable")
    seen = set()
    for p in pmap:
        pid = p.get("paragraph_id")
        if not pid:
            E.append("paragraph_map entry without paragraph_id")
            continue
        if pid in seen:
            E.append("paragraph_map duplicates %s" % pid)
        seen.add(pid)
        if paras and pid not in paras:
            E.append("paragraph_map %s not in structure.json" % pid)
        if p.get("status") not in PSTATUS:
            E.append("paragraph %s invalid status: %s" % (pid, p.get("status")))
        if p.get("status") == "merged" and not p.get("into"):
            E.append("paragraph %s merged without 'into'" % pid)
        if p.get("status") == "split" and not p.get("split_into"):
            E.append("paragraph %s split without 'split_into'" % pid)
    missing = sorted(set(paras) - seen)
    if paras and missing:
        E.append("paragraph_map omits %d paragraph(s): %s" % (len(missing), ",".join(missing[:8])))

    outline = plan.get("outline") or []
    if not outline:
        E.append("outline empty: revised structure not delivered")
    orders = [o.get("order") for o in outline]
    if orders and len(set(map(str, orders))) != len(orders):
        E.append("outline order values are not unique")
    for o in outline:
        if not str(o.get("role", "")).strip():
            E.append("outline section %s missing role" % o.get("section"))
        for pid in o.get("paragraphs_from") or []:
            if paras and pid not in paras:
                E.append("outline section %s references unknown paragraph %s" % (o.get("section"), pid))

    fg = plan.get("fact_guard") or {}
    for key in ("numbers_unbound", "citations_not_in_sources"):
        val = fg.get(key)
        if val not in (None, [], 0):
            E.append("fact_guard.%s not clean: %s" % (key, val))
    if not str(fg.get("verdict", "")).strip():
        W.append("fact_guard.verdict missing")

    smap = plan.get("source_map") or []
    if not smap and diags:
        E.append("source_map empty: diagnosis has no evidence locator")
    for i, s in enumerate(smap):
        if not str(s.get("locator", "")).strip():
            E.append("source_map[%d] missing locator" % i)
    return E, W, dim_findings


def sanitize(plan, corpus, structure, paras):
    """Drop what cannot be verified, keep what can. Returns (clean_plan, dropped[])."""
    dropped = []
    clean = {k: v for k, v in plan.items()}
    cov = dict(plan.get("coverage") or {})

    kept_diags = []
    for x in plan.get("diagnosis") or []:
        iid = x.get("issue_id") or "?"
        loc = x.get("location") or {}
        pid = loc.get("paragraph_id")
        q = loc.get("anchor_quote") or x.get("anchor_quote") or ""
        reason = None
        if x.get("dimension") not in DIMS_SET:
            reason = "维度不在六维枚举内"
        elif x.get("severity") not in LEVELS or x.get("confidence") not in LEVELS:
            reason = "severity/confidence 不在枚举内"
        elif not str(x.get("problem", "")).strip() or not str(x.get("why", "")).strip():
            reason = "缺少 problem 或 why"
        elif pid and paras and pid not in paras:
            reason = "定位段落 %s 不存在于本次稿件" % pid
        elif q:
            if not corpus:
                reason = "无可读原文，引文无法核验"
            elif norm(q)[:40] not in corpus:
                reason = "anchor_quote 在原文中找不到逐字匹配"
        elif not pid:
            reason = "既无段落编号也无引文，无法定位"
        if reason:
            dropped.append({"kind": "diagnosis", "id": iid, "reason": reason,
                            "anchor_quote": q[:120]})
            continue
        kept_diags.append(x)
    kept_ids = {x.get("issue_id") for x in kept_diags}
    clean["diagnosis"] = kept_diags

    kept_edits = []
    for e in plan.get("edit_plan") or []:
        eid = e.get("edit_id") or "?"
        reason = None
        if e.get("issue_id") not in kept_ids:
            reason = "对应诊断已被移除或不存在"
        elif e.get("action") not in ACTIONS:
            reason = "action 不在词表内"
        elif any(not str(e.get(k, "")).strip() for k in ("instruction", "preserves", "expected_effect")):
            reason = "缺少 instruction/preserves/expected_effect"
        if reason:
            dropped.append({"kind": "edit", "id": eid, "reason": reason})
            continue
        e = dict(e)
        pid = (e.get("target") or {}).get("paragraph_id")
        if pid and paras and pid not in paras:
            e["target"] = dict(e.get("target") or {})
            e["target"]["paragraph_id"] = None
        kept_edits.append(e)
    clean["edit_plan"] = kept_edits

    # coverage: keep model's checked flags where valid, but findings must match kept diagnosis
    for d in DIMS:
        c = dict(cov.get(d) or {})
        if not isinstance(c.get("checked"), bool):
            c["checked"] = bool(paras)
        c["findings"] = len([x for x in kept_diags if x.get("dimension") == d])
        cov[d] = c
    cov["read_sections"] = cov.get("read_sections") or [w.get("section") for w in structure.get("weights") or []] \
        or ["Preamble"]
    cov["unread_sections"] = cov.get("unread_sections") or []
    if not kept_diags:
        cov["no_issues_found"] = bool(cov.get("no_issues_found"))
    clean["coverage"] = cov

    # paragraph_map: normalize, then fill every known paragraph
    pmap, seen = [], set()
    for p in plan.get("paragraph_map") or []:
        pid = p.get("paragraph_id")
        if not pid or pid in seen or (paras and pid not in paras):
            continue
        if p.get("status") not in PSTATUS:
            continue
        if p.get("status") == "merged" and not p.get("into"):
            p = dict(p, status="kept", reason="合并目标缺失，降级为保留")
        if p.get("status") == "split" and not p.get("split_into"):
            p = dict(p, status="kept", reason="拆分点缺失，降级为保留")
        pmap.append(p)
        seen.add(pid)
    for pid, p in paras.items():
        if pid not in seen:
            pmap.append({"paragraph_id": pid, "status": "kept",
                         "reason": "门禁补全：原方案未涉及该段，默认保留原位"})
    clean["paragraph_map"] = pmap

    # outline: drop unresolvable refs, fill if empty
    outline = []
    for o in plan.get("outline") or []:
        refs = [pid for pid in (o.get("paragraphs_from") or []) if not paras or pid in paras]
        o = dict(o, paragraphs_from=refs, role=o.get("role") or "功能待作者确认")
        outline.append(o)
    if not outline and paras:
        order, seen_sec = [], {}
        for pid, p in paras.items():
            sec = p.get("section") or "正文"
            if sec not in seen_sec:
                seen_sec[sec] = {"section": sec, "role": "功能待作者确认",
                                 "order": len(order) + 1, "paragraphs_from": [],
                                 "merge_of": [], "split_into": [], "note": "门禁补全的大纲"}
                order.append(seen_sec[sec])
            seen_sec[sec]["paragraphs_from"].append(pid)
        outline = order
    clean["outline"] = outline

    # source_map: drop locator-less entries, fill from kept diagnosis
    smap = [s for s in (plan.get("source_map") or []) if str(s.get("locator", "")).strip()]
    if not smap:
        smap = []
        for x in kept_diags:
            p = paras.get((x.get("location") or {}).get("paragraph_id")) or {}
            smap.append({"claim": x.get("problem", "")[:120],
                         "value": (x.get("location") or {}).get("anchor_quote", ""),
                         "source_path": structure.get("file") or "manuscript",
                         "locator": "%s L%s-L%s" % ((x.get("location") or {}).get("paragraph_id", "?"),
                                                    p.get("start_line", "?"), p.get("end_line", "?"))})
    clean["source_map"] = smap

    fg = dict(plan.get("fact_guard") or {})
    for key in ("numbers_unbound", "citations_not_in_sources"):
        if fg.get(key) not in (None, [], 0):
            dropped.append({"kind": "fact_guard", "id": key, "reason": "门禁不通过，已移动待人工复核",
                            "values": fg.get(key)})
            fg[key] = []
    clean["fact_guard"] = fg

    if not kept_diags:
        clean["no_issues_found"] = bool(cov.get("no_issues_found"))
    return clean, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--structure", default="work/structure.json")
    ap.add_argument("--out", default="work")
    ap.add_argument("--sanitize", action="store_true")
    ap.add_argument("--out-draft", default="")
    a = ap.parse_args()
    draft = load(a.draft, {})
    plan = merged_plan(draft)
    corpus = norm(open(a.corpus, encoding="utf-8").read()) if os.path.exists(a.corpus) else ""
    structure = load(a.structure, {})
    paras = known_paragraphs(structure)
    dropped = []

    if a.sanitize:
        plan, dropped = sanitize(plan, corpus, structure, paras)
        # a sanitized clean manuscript must prove work through argument_map or paragraph coverage
        cov = plan.get("coverage") or {}
        if not plan.get("diagnosis") and not (cov.get("no_issues_found") and plan.get("argument_map")):
            cov["no_issues_found"] = False
            plan["coverage"] = cov
        out_draft = a.out_draft or os.path.join(a.out, "draft.sanitized.json")
        os.makedirs(os.path.dirname(os.path.abspath(out_draft)) or ".", exist_ok=True)
        with open(out_draft, "w", encoding="utf-8") as fh:
            json.dump({"fields": plan, "status": plan.get("status") or draft.get("status", "partial")},
                      fh, ensure_ascii=False, indent=1)

    E, W, dim_findings = evaluate(plan, corpus, paras)
    if dropped:
        W.append("sanitizer dropped %d unverifiable item(s)" % len(dropped))
    report = {"ok": not E, "mode": "sanitize" if a.sanitize else "strict",
              "errors": E, "warnings": W, "dropped": dropped,
              "counts": {"diagnosis": len(plan.get("diagnosis") or []),
                         "edits": len(plan.get("edit_plan") or []),
                         "paragraphs_known": len(paras),
                         "paragraphs_mapped": len(plan.get("paragraph_map") or []),
                         "outline_sections": len(plan.get("outline") or [])},
              "dimension_findings": dim_findings}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "plan_check.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    md = ["# 结构修改方案门禁", "",
          "结论：%s；模式：%s；issue %d / edit %d；段落覆盖 %d/%d"
          % ("PASS" if not E else "FAIL", report["mode"], len(plan.get("diagnosis") or []),
             len(plan.get("edit_plan") or []), len(plan.get("paragraph_map") or []), len(paras)),
          "", "## 错误"] + (["- %s" % e for e in E] or ["- 无"])
    md += ["", "## 警告"] + (["- %s" % w for w in W] or ["- 无"])
    if dropped:
        md += ["", "## 被拦截/移除的条目"] + ["- %s %s：%s" % (d["kind"], d["id"], d["reason"]) for d in dropped]
    with open(os.path.join(a.out, "plan_check.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("verdict=%s mode=%s errors=%d warnings=%d issues=%d edits=%d coverage=%d/%d dropped=%d"
          % ("pass" if not E else "fail", report["mode"], len(E), len(W),
             len(plan.get("diagnosis") or []), len(plan.get("edit_plan") or []),
             len(plan.get("paragraph_map") or []), len(paras), len(dropped)))
    for e in E[:12]:
        print("  !", e)
    for w in W[:6]:
        print("  ~", w)
    for d in dropped[:6]:
        print("  -", d["kind"], d["id"], "|", d["reason"])
    return 0 if not E else 1


if __name__ == "__main__":
    sys.exit(main())
