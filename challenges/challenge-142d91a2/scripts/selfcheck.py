#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selfcheck.py - independent quality gate for the generated proposal bundle.

This is not a second renderer.  It re-opens the artefacts that were actually
written and checks the promises made in SKILL.md:

  contract   every output_contract field is present in result.json
  docx       proposal.docx is a real OOXML package with text and tables
  elements   the seven required Sections exist in proposal.md and result.json
  evidence   every `reported` claim has an anchor + verbatim quote that can be
             found in sources.json or case.json
  numbers    no unresolved number silently presented as fact
  plan       question count 1-3, alignment rows complete, milestone month sum
             matches the declared period, four risk categories present
  honesty    status/uncertainty are consistent with what is missing

Usage:
  python3 scripts/selfcheck.py --case /input/case.json \
      --sources /app/work/sources.json --out /app/output [--json]

Exit 0 only when every hard check passes ("PASS" is printed).  Exit 1 prints
"FAIL" plus the individual problems.  Warnings do not fail the run but are
listed so an editor can see what still needs human confirmation.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import common  # noqa: E402
import docx_mini  # noqa: E402

ELEMENT_HEADINGS = [
    ("research_background", "研究背景"),
    ("problem_definition", "问题定义"),
    ("objectives", "研究目标"),
    ("technical_route", "技术路线"),
    ("schedule", "阶段计划"),
    ("risks", "风险"),
    ("expected_outcomes", "预期成果"),
]
RISK_CATEGORIES = {"data", "method", "schedule", "ethics"}
DOCX_MUST = ["研究背景", "问题定义", "技术路线", "阶段计划", "风险", "预期成果"]


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        return {"__error__": "%s: %s" % (type(exc).__name__, str(exc)[:200])}


def _case_value(case, path):
    node = case
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _quote_ok(claim, para_index, case):
    quote = common.norm_ws(claim.get("quote", ""))
    anchor = claim.get("anchor", "")
    if not quote or not anchor:
        return False
    if anchor.startswith("case.json:"):
        value = _case_value(case, anchor.split(":", 1)[1])
        if value is None:
            return False
        text = common.safe_text(value)
        return common.quote_in(quote, text) or common.quote_in(text, quote)
    para = para_index.get(anchor)
    if not para:
        return False
    return common.quote_in(quote, para)


def build_para_index(sources):
    index = {}
    for src in (sources or {}).get("sources", []):
        for para in src.get("paragraphs", []):
            if para.get("anchor"):
                index[para["anchor"]] = para.get("text", "")
    return index


def resolve_sources(explicit, out_dir, case_path, result):
    """Locate sources.json instead of silently assuming /app/work.

    root cause of a previous false FAIL: selfcheck defaulted to
    <out>/../work/sources.json, which does not exist when the caller uses
    /tmp/p_out2 and /tmp/p_out2_work.  The authoritative location is recorded
    in result.json as build.sources_path by build_proposal.py.
    """
    candidates = []
    if explicit:
        candidates.append(explicit)
    recorded = ((result or {}).get("build") or {}).get("sources_path")
    if recorded:
        candidates.append(recorded)
    out_abs = os.path.abspath(out_dir)
    candidates.append(os.path.join(out_abs, "sources.json"))
    candidates.append(os.path.join(os.path.dirname(out_abs), "work", "sources.json"))
    candidates.append(out_abs.rstrip(os.sep) + "_work" + os.sep + "sources.json")
    if case_path:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(case_path)),
                                       "work", "sources.json"))
    candidates.append(os.path.join(os.getcwd(), "work", "sources.json"))
    for path in candidates:
        if path and os.path.isfile(path):
            return os.path.abspath(path)
    return None


def check(out_dir, case_path, sources_path):
    problems, warnings, info = [], [], {}
    result_path = os.path.join(out_dir, "result.json")
    md_path = os.path.join(out_dir, "proposal.md")
    docx_path = os.path.join(out_dir, "proposal.docx")

    if not os.path.isfile(result_path):
        return ["result.json missing"], [], {}
    result = _load_json(result_path)
    if "__error__" in result:
        return ["result.json unreadable: %s" % result["__error__"]], [], {}
    case = _load_json(case_path) if case_path and os.path.isfile(case_path) else {}
    sources_file = resolve_sources(sources_path, out_dir, case_path, result)
    sources = _load_json(sources_file) if sources_file else {}
    if "__error__" in sources:
        problems.append("sources.json unreadable: %s" % sources["__error__"])
        sources = {}
    if not sources_file:
        problems.append("sources.json not found; cannot verify claim anchors "
                        "(pass --sources or keep result.build.sources_path)")
    info["sources_path"] = sources_file or ""
    para_index = build_para_index(sources)

    # ---- contract -----------------------------------------------------
    fields, _raw = common.contract_declaration(case)
    missing_fields = [name for name in fields
                      if name not in result and common.contract_declaration(case)[0]]
    # case_id is mandatory even if the contract omits it.
    case_id = common.case_id_of(case, os.path.dirname(case_path) if case_path else None)
    if not result.get("case_id"):
        problems.append("result.case_id missing")
    elif case and str(result["case_id"]) != str(common.case_id_of(case, None)):
        problems.append("result.case_id %r != case.json case_id %r"
                        % (result.get("case_id"), common.case_id_of(case, None)))
    for name in missing_fields:
        problems.append("output_contract field missing: %s" % name)
    info["contract_fields"] = len(fields)
    info["contract_missing"] = missing_fields

    # ---- status -------------------------------------------------------
    status = result.get("status")
    if status not in ("success", "partial", "failed"):
        problems.append("result.status must be success|partial|failed, got %r" % status)
    if status == "success":
        if result.get("uncertainty", {}).get("unresolved"):
            problems.append("status=success but uncertainty.unresolved is non-empty")
        if (result.get("numeric_audit") or {}).get("unresolved"):
            problems.append("status=success but numeric_audit has unresolved numbers")
    if status == "failed" and (os.path.isfile(md_path) and os.path.getsize(md_path) > 0):
        warnings.append("status=failed but proposal.md exists; confirm this is intended")

    # ---- markdown -----------------------------------------------------
    markdown = ""
    if not os.path.isfile(md_path) or os.path.getsize(md_path) == 0:
        problems.append("proposal.md missing or empty")
    else:
        markdown = common.read_text(md_path)
        info["markdown_chars"] = len(markdown)
        for _key, label in ELEMENT_HEADINGS:
            if label not in markdown:
                problems.append("proposal.md lacks section about %s" % label)
    for label in ["研究背景", "问题定义", "研究目标", "技术路线", "阶段计划",
                  "风险", "预期成果"]:
        if label not in markdown:
            warnings.append("proposal.md does not mention %s" % label)
    if "伦理" not in markdown:
        problems.append("proposal.md must contain an ethics/compliance section")
    if "参考文献" in markdown and "材料未提供" not in markdown:
        warnings.append("proposal.md mentions references; verify none were fabricated")

    # ---- docx ---------------------------------------------------------
    docx_check = docx_mini.verify_docx(docx_path) if os.path.isfile(docx_path) else {
        "ok": False, "error": "proposal.docx missing"}
    info["docx"] = docx_check
    if not docx_check.get("ok"):
        problems.append("proposal.docx is not a valid reopenable DOCX: %s"
                        % docx_check.get("error"))
    else:
        with zipfile.ZipFile(docx_path) as zf:
            text = zf.read("word/document.xml").decode("utf-8", "replace")
        for label in DOCX_MUST:
            if label not in text:
                problems.append("proposal.docx text lacks %s" % label)
        if "伦理" not in text:
            problems.append("proposal.docx text lacks the ethics/compliance section")
        if docx_check.get("tables", 0) < 4:
            warnings.append("proposal.docx has only %s tables; tables may be flattened"
                            % docx_check.get("tables"))

    # ---- evidence -----------------------------------------------------
    claims = result.get("evidence") or []
    if not claims:
        problems.append("result.evidence is empty")
    reported = [c for c in claims if c.get("status") == "reported"]
    for claim in reported:
        if not claim.get("verified"):
            problems.append("reported claim %s is not verified" % claim.get("claim_id"))
        anchor = claim.get("anchor", "")
        if anchor.startswith("case.json:"):
            if not _quote_ok(claim, para_index, case):
                problems.append("claim %s quote not found at anchor %s"
                                % (claim.get("claim_id"), anchor))
        elif para_index:
            if not _quote_ok(claim, para_index, case):
                problems.append("claim %s quote not found at anchor %s"
                                % (claim.get("claim_id"), anchor))
        # When sources.json is missing, a single clear problem was already added;
        # do not emit one misleading quote error per claim.
    info["claims"] = len(claims)
    info["claims_reported"] = len(reported)

    # ---- numbers ------------------------------------------------------
    numeric = result.get("numeric_audit") or {}
    if numeric.get("unresolved"):
        if status == "success":
            problems.append("unresolved numbers under status=success")
        else:
            warnings.append("%d numbers are not traceable; they must stay marked as drafts"
                            % len(numeric["unresolved"]))

    # ---- plan consistency --------------------------------------------
    questions = result.get("questions") or []
    if not (1 <= len(questions) <= 3):
        problems.append("research question count is %d; must be 1-3" % len(questions))
    alignment = result.get("alignment") or {}
    if alignment.get("status") != "pass":
        problems.append("alignment gaps: %s" % "；".join(alignment.get("gaps", [])))
    schedule = result.get("schedule") or {}
    milestones = schedule.get("milestones") or []
    period = (result.get("constraints") or {}).get("period_months") or {}
    if period.get("status") == "reported" and milestones:
        if int(milestones[-1].get("end_month") or 0) != int(round(float(period.get("value") or 0))):
            problems.append("last milestone end_month %s != period %s"
                            % (milestones[-1].get("end_month"), period.get("value")))
    if period.get("status") == "reported" and not milestones:
        problems.append("period reported but no milestones generated")
    risks = result.get("risks") or []
    categories = set(r.get("category") for r in risks)
    if categories != RISK_CATEGORIES:
        problems.append("risk categories %s != %s"
                        % (sorted(categories), sorted(RISK_CATEGORIES)))
    for risk in risks:
        for key in ("trigger", "impact", "fallback", "decision_point"):
            if not risk.get(key):
                problems.append("risk %s lacks %s" % (risk.get("id"), key))
    outcomes = result.get("outcomes") if isinstance(result.get("outcomes"), list) else \
        (result.get("elements", {}).get("expected_outcomes", {}).get("items") or [])
    if not outcomes:
        problems.append("expected outcomes missing")

    # ---- element statuses --------------------------------------------
    elements = result.get("elements") or {}
    for key, label in ELEMENT_HEADINGS:
        item = elements.get(key)
        if not isinstance(item, dict):
            problems.append("elements.%s missing" % key)
            continue
        if item.get("status") in (None, "not_reported") and status == "success":
            problems.append("elements.%s is %s under status=success"
                            % (key, item.get("status")))
    status_map = result.get("element_status") or {}
    info["element_status"] = status_map

    # ---- honest partial -------------------------------------------------
    if status == "partial":
        if not result.get("uncertainty", {}).get("notes"):
            problems.append("status=partial but uncertainty.notes is empty")
        if not result.get("uncertainty", {}).get("unresolved"):
            warnings.append("status=partial but no unresolved item is listed")
    if result.get("preview", {}).get("status") != "ok":
        warnings.append("no rendered PDF/PNG preview (%s); HTML preview is present"
                        % result.get("preview", {}).get("reason", "unknown"))
    return problems, warnings, info


def main(argv=None):
    ap = argparse.ArgumentParser(description="Independent self-check of the proposal bundle")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--sources", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    problems, warnings, info = check(args.out, args.case, args.sources)
    report = {"ok": not problems, "problems": problems, "warnings": warnings, "info": info}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for item in problems:
            print(" - %s" % item)
        for item in warnings:
            print(" WARN %s" % item)
        print("stats:", json.dumps({k: v for k, v in info.items()
                                    if k not in ("docx",)}, ensure_ascii=False))
    try:
        common.write_json(os.path.join(args.out, "selfcheck.json"), report)
    except Exception:  # noqa: BLE001
        pass
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
