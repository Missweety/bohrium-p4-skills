#!/usr/bin/env python3
"""kernel.py - evidence-first execution kernel shared by all Bohrium skills.

Subcommands (all stdlib only, no network):
  init     read /input/case.json (alias tolerant), emit work/contract.json + work/case.json
  index    walk material dir, extract text with locators, emit work/evidence.json
  verify   check a draft against the evidence index (numbers, units, citations, claims)
  emit     merge draft fields + contract into result.json, write md artifacts, run selfcheck
  check    validate an existing output dir against its contract

Design rule: never fabricate. Missing data is reported as missing, never filled in.
"""
import argparse
import csv
import json
import os
import re
import sys
import zipfile

ALIASES = {
    "source_text": ["source_text", "text", "input_text", "manuscript", "content", "document", "paper_text"],
    "case_id": ["case_id", "id", "caseId", "task_id"],
    "task": ["task", "instruction", "question", "prompt", "request"],
    "materials": ["materials", "files", "attachments", "inputs", "resources", "documents"],
    "output_contract": ["output_contract", "outputContract", "expected_output", "schema"],
    "audience": ["audience", "readers", "target_audience"],
    "language": ["target_language", "language", "lang"],
    "genre": ["genre", "document_type", "doc_type", "style", "register"],
    "parameter_domains": ["parameter_domains", "domains", "bounds", "ranges", "parameter_ranges"],
    "candidate_plans": ["candidate_plans", "plans", "variants", "versions", "candidates"],
    "response_metrics": ["response_metrics", "objectives", "responses", "metrics", "indicators"],
    "resource_contract": ["resource_contract", "prices", "booking", "resources", "cost_terms"],
    "budget": ["budget", "cost_limit", "spend_limit", "预算"],
}
# 契约字段名 → 本技能标准字段（大小写/下划线/连字符不敏感）
CONTRACT_ALIAS = {
    "caseid": "case_id", "id": "case_id", "taskid": "case_id",
    "status": "status", "runstatus": "status",
    "recommendation": "recommendation", "recommended_plan": "recommendation",
    "recommended_parameters": "parameter_plan", "parameterplan": "parameter_plan",
    "parameters": "parameter_plan", "settings": "parameter_plan", "params": "parameter_plan",
    "feasibledomain": "feasible_domain", "domain": "feasible_domain", "constraints": "feasible_domain",
    "responsemetrics": "response_metrics", "metrics": "response_metrics", "objectives": "response_metrics",
    "searchplan": "search_plan", "searchstrategy": "search_plan", "strategy": "search_plan",
    "costmodel": "cost_model", "cost": "cost_model", "costestimate": "cost_model", "budget": "cost_model",
    "assumptions": "assumptions", "variables": "variables", "controls": "controls",
    "risks": "risks", "exceptions": "exceptions", "riskanalysis": "risks",
    "confirmations": "confirmations", "confirmationitems": "confirmations",
    "evidencemap": "evidence_map", "evidence": "evidence_map", "sources": "evidence_map",
    "uncertainty": "uncertainty", "limits": "limits", "changes": "changes",
    "validation": "validation", "validationresults": "validation", "checks": "validation",
    "summary": "summary", "conclusion": "summary", "findings": "findings",
    "researchquestion": "query_terms", "retrievalscope": "retrieval_scope",
    "queryterms": "query_terms", "concepts": "query_terms",
    "relevancerubric": "relevance_rubric", "scoringrubric": "relevance_rubric",
    "dedupsummary": "dedup_summary", "deduplication": "dedup_summary",
    "rankedcandidates": "ranked_candidates", "ranked": "ranked_candidates",
    "candidates": "ranked_candidates", "results": "ranked_candidates",
    "screeningdecisions": "screening_decisions", "decisions": "screening_decisions",
    "labels": "screening_decisions",
    "conflictresolution": "conflict_resolution", "conflicts": "conflict_resolution",
    "recallcheck": "recall_check", "coverage": "recall_check",
    "stabilitycheck": "stability_check", "stability": "stability_check",
    "exclusions": "exclusions", "missing": "exclusions",
}
ARTIFACTS = ["ranked_candidates.csv", "screening_report.md"]

TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".tex", ".bib", ".yaml", ".yml", ".rst", ".html", ".xml"}
# 本题默认契约（case.json 未给 output_contract 时兜底）
DEFAULT_CONTRACT = [
    "query_terms", "retrieval_scope", "relevance_rubric", "dedup_summary",
    "ranked_candidates", "screening_decisions", "conflict_resolution",
    "recall_check", "stability_check", "exclusions", "evidence_map",
    "assumptions", "uncertainty", "limits", "validation", "changes",
]
NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
CITE_RE = re.compile(r"(\[[0-9,\s\-–]+\]|\\cite\{[^}]+\}|\([A-Z][A-Za-z\-]+(?:\s(?:et al\.|and\s[A-Z][A-Za-z\-]+))?,?\s?(?:19|20)\d{2}[a-z]?\))")


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def pick(case, key):
    for name in ALIASES.get(key, [key]):
        if name in case and case[name] not in (None, "", [], {}):
            return case[name]
    return None


def find_case_file(explicit=None):
    cands = [explicit] if explicit else []
    cands += ["/input/case.json", "case.json", "/app/input/case.json", "./input/case.json"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


# ---------------------------------------------------------------- extraction
def strip_xml(raw):
    raw = re.sub(r"<w:p[ >]", "\n<w:p ", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    return re.sub(r"\n{3,}", "\n\n", raw)


def read_docx(path):
    out = []
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.startswith("word/") and n.endswith(".xml")]
        for n in sorted(names):
            if "document" in n:
                out.append(strip_xml(z.read(n).decode("utf-8", "replace")))
    return "\n".join(out)


def read_xlsx(path):
    try:
        with zipfile.ZipFile(path) as z:
            shared = []
            if "xl/sharedStrings.xml" in z.namelist():
                s = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
                shared = [re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<si>(.*?)</si>", s, re.S)]
            rows = []
            for n in sorted(x for x in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", x)):
                x = z.read(n).decode("utf-8", "replace")
                for r in re.findall(r"<row[^>]*>(.*?)</row>", x, re.S):
                    cells = []
                    for c in re.findall(r"<c([^>]*)>(.*?)</c>", r, re.S):
                        attrs, body = c
                        v = re.search(r"<v>(.*?)</v>", body, re.S)
                        t = re.search(r't="([^"]+)"', attrs)
                        if v is None:
                            cells.append("")
                        elif t and t.group(1) == "s":
                            idx = int(v.group(1))
                            cells.append(shared[idx] if idx < len(shared) else "")
                        else:
                            cells.append(v.group(1))
                    rows.append("\t".join(cells))
            return "\n".join(rows)
    except Exception as exc:  # noqa: BLE001
        return "[xlsx unreadable: %s]" % exc


def read_pdf(path):
    try:
        import subprocess
        r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        pass
    try:
        from pypdf import PdfReader  # type: ignore
        return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    except Exception:  # noqa: BLE001
        return "[pdf text layer unavailable: install pdftotext or pypdf; do not guess page content]"


def extract(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return read_docx(path)
    if ext in {".xlsx", ".xlsm"}:
        return read_xlsx(path)
    if ext == ".pdf":
        return read_pdf(path)
    if ext in TEXT_EXT:
        return open(path, encoding="utf-8", errors="replace").read()
    if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".svg"}:
        return "[image asset: inspect visually; record尺寸/内容 in evidence notes]"
    return "[unsupported type %s]" % ext


def locate(snippet, corpus, source):
    """Return a human-checkable locator: line number(s) + char offset."""
    idx = corpus.find(snippet[:80])
    if idx < 0:
        return None
    line = corpus.count("\n", 0, idx) + 1
    return {"source": source, "line": line, "offset": idx}


# ---------------------------------------------------------------- commands
def cmd_init(a):
    case_path = find_case_file(a.case)
    if not case_path:
        dump({"status": "blocked", "missing": "case.json not found"}, os.path.join(a.out, "contract.json"))
        print("blocked: case.json not found")
        return 1
    case = load_json(case_path)
    norm = {k: pick(case, k) for k in ALIASES}
    contract = norm.get("output_contract") or {}
    if isinstance(contract, list):
        contract = {"fields": contract}
    if not contract:
        contract = {"fields": list(DEFAULT_CONTRACT)}
    result = {
        "case_path": os.path.abspath(case_path),
        "case_id": norm.get("case_id") or os.path.splitext(os.path.basename(case_path))[0],
        "task": norm.get("task"),
        "language": norm.get("language"),
        "genre": norm.get("genre"),
        "audience": norm.get("audience"),
        "raw_keys": sorted(case.keys()),
        "contract_source": "case.output_contract" if norm.get("output_contract") else "skill_default",
        "contract": contract,
    }
    dump(result, os.path.join(a.out, "contract.json"))
    dump(case, os.path.join(a.out, "case.raw.json"))
    if not contract:
        print("warn: case.json has no output_contract; using skill default contract")
    print("case_id=%s keys=%s" % (result["case_id"], ",".join(result["raw_keys"])))
    return 0


def cmd_index(a):
    roots = [p for p in a.materials if os.path.exists(p)]
    items, corpus = [], []
    for root in roots:
        walk = [(root, [], [os.path.basename(root)])] if os.path.isfile(root) else os.walk(root)
        for dirpath, _, names in walk:
            for n in sorted(names):
                p = dirpath if dirpath == root and not os.path.isdir(root) else os.path.join(dirpath, n)
                if not os.path.isfile(p) or n.startswith("."):
                    continue
                text = extract(p)
                items.append({
                    "path": p,
                    "bytes": os.path.getsize(p),
                    "chars": len(text),
                    "readable": not text.startswith("["),
                    "sha1": __import__("hashlib").sha1(open(p, "rb").read()).hexdigest(),
                })
                corpus.append("===== FILE: %s =====\n%s" % (p, text))
    dump({"files": items, "total_chars": sum(i["chars"] for i in items),
          "unreadable": [i["path"] for i in items if not i["readable"]]},
         os.path.join(a.out, "evidence.json"))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "corpus.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(corpus))
    for i in items:
        print("%-8s %8d  %s" % ("ok" if i["readable"] else "UNREAD", i["chars"], i["path"]))
    return 0


def cmd_verify(a):
    corpus = open(os.path.join(a.evidence_dir, "corpus.txt"), encoding="utf-8").read()
    ev = load_json(os.path.join(a.evidence_dir, "evidence.json"))
    draft = open(a.text, encoding="utf-8").read()
    numbers = []
    for m in NUM_RE.finditer(draft):
        tok = m.group(0).strip()
        if len(tok) < 2 and not tok.isdigit():
            continue
        numbers.append(tok)
    unsupported = [n for n in dict.fromkeys(numbers) if n not in corpus]
    cites = list(dict.fromkeys(CITE_RE.findall(draft)))
    missing_cites = [c for c in cites if c.strip("[]") not in corpus and c.strip("\\cite{}") not in corpus]
    report = {
        "draft": os.path.abspath(a.text),
        "numbers_total": len(numbers),
        "numbers_unique": len(set(numbers)),
        "unsupported_numbers": unsupported[:200],
        "citations_unique": len(cites),
        "citations_not_in_sources": missing_cites[:200],
        "unreadable_sources": ev.get("unreadable", []),
        "verdict": "pass" if not unsupported and not missing_cites else "review",
    }
    dump(report, os.path.join(a.out, "claims.json"))
    print("verdict=%s unsupported_numbers=%d citations_not_in_sources=%d"
          % (report["verdict"], len(unsupported), len(missing_cites)))
    for n in unsupported[:20]:
        print("  ? number not in sources:", n)
    return 0


def canon(name):
    """契约字段名归一：小写、去掉 _ - 空格后查别名表。"""
    key = re.sub(r"[\s_\-]+", "", str(name)).lower()
    return CONTRACT_ALIAS.get(key, str(name))


def cmd_emit(a):
    contract = load_json(os.path.join(a.contract_dir, "contract.json")) if os.path.isdir(a.contract_dir) \
        else load_json(a.contract_dir)
    draft = load_json(a.draft)
    fields = contract.get("contract") or {}
    if isinstance(fields, dict) and isinstance(fields.get("fields"), list):
        fields = {name: None for name in fields["fields"] if isinstance(name, str)}
    if not fields:
        fields = {name: None for name in DEFAULT_CONTRACT}
    src = dict(draft.get("fields", {}))
    for k, v in draft.items():
        if k not in ("fields", "artifacts"):
            src.setdefault(k, v)
    result = {"case_id": contract.get("case_id"), "status": draft.get("status", "partial")}
    unresolved = []
    for name in (fields if isinstance(fields, dict) else DEFAULT_CONTRACT):
        # 空数组/空字符串是合法取值（如"无冲突"），只有键缺失或 None 才算未产出。
        if name in src and src[name] is not None:
            val = src[name]
        elif canon(name) in src and src[canon(name)] is not None:
            val = src[canon(name)]
        else:
            unresolved.append(name)
            val = {"note": "输入契约未定义该字段的取值口径；本技能未产出对应内容，见 uncertainty/limits"}
        result[name] = val
    result["status"] = draft.get("status", "partial")
    for name in DEFAULT_CONTRACT:
        if name not in result:
            result[name] = src.get(name)
    for name, val in src.items():          # 附加证据（候选核算/越界清单等）一并保留
        result.setdefault(name, val)
    result.setdefault("uncertainty", draft.get("uncertainty", []))
    result.setdefault("sources", draft.get("sources", []))
    result.setdefault("changes", draft.get("changes", []))
    result.setdefault("self_check", draft.get("self_check", {}))
    result["limits"] = draft.get("limits", "")
    os.makedirs(a.out, exist_ok=True)
    dump(result, os.path.join(a.out, "result.json"))
    for name, body in (draft.get("artifacts") or {}).items():
        p = os.path.join(a.out, name)
        os.makedirs(os.path.dirname(p) or a.out, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
    missing = [k for k in unresolved]
    print("result.json written; unresolved_contract_fields=%s" % (missing or "none"))
    return 0


def cmd_check(a):
    problems, warns = [], []
    rp = os.path.join(a.out, "result.json")
    if not os.path.exists(rp):
        problems.append("result.json missing")
    else:
        res = load_json(rp)
        for k in ("case_id", "status"):
            if not res.get(k):
                problems.append("result.json missing %s" % k)
        status = res.get("status")
        if not isinstance(status, str) or status not in {"ok", "success", "partial", "blocked", "refused"}:
            problems.append("status must be a string in ok/success/partial/blocked/refused")
        if status == "partial" and not str(res.get("limits", "")).strip():
            problems.append("status=partial but limits is empty")
        if status == "blocked":
            if not str(res.get("limits", "")).strip():
                problems.append("status=blocked but limits is empty")
            print("PASS" if not problems else "FAIL")
            for p in problems:
                print(" -", p)
            return 0 if not problems else 1
        # Every field promised by the case contract must be present and non-empty.
        cp = os.path.join(a.contract_dir, "contract.json")
        if os.path.exists(cp):
            fields = (load_json(cp).get("contract") or {})
            if isinstance(fields, dict) and isinstance(fields.get("fields"), list):
                fields = {n: None for n in fields["fields"] if isinstance(n, str)}
            optional = ("uncertainty", "limits", "changes", "notes", "risks", "exceptions",
                        "confirmations", "evidence_map", "sources", "validation")
            for name in (fields if isinstance(fields, dict) else []):
                cname = canon(name)
                if cname in optional:
                    if cname not in res and name not in res:
                        problems.append("result.json missing contract field %s" % name)
                    continue
                if name not in res:
                    problems.append("result.json missing contract field %s" % name)
                elif res[name] is None or (isinstance(res[name], str) and not res[name].strip()):
                    problems.append("result.json empty contract field %s" % name)
        else:
            warns.append("contract.json not found; skipped contract-field check")
        # Editable artifacts promised by this skill must exist and be non-trivial.
        for name in ARTIFACTS:
            p = os.path.join(a.out, name)
            if not os.path.exists(p):
                problems.append("artifact %s missing" % name)
            elif os.path.getsize(p) < 40:
                problems.append("artifact %s is empty/truncated" % name)
        if not res.get("self_check"):
            warns.append("self_check summary absent in result.json")
    print("PASS" if not problems else "FAIL")
    for p in problems:
        print(" -", p)
    for w in warns:
        print(" ~", w)
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("--case"); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("index"); p.add_argument("--materials", nargs="+", required=True); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("verify"); p.add_argument("--text", required=True); p.add_argument("--evidence-dir", default="work"); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("emit"); p.add_argument("--draft", required=True); p.add_argument("--contract-dir", default="work"); p.add_argument("--out", default="/app/output"); p.set_defaults(fn=cmd_emit)
    p = sub.add_parser("check"); p.add_argument("--out", default="/app/output"); p.add_argument("--contract-dir", default="work"); p.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
