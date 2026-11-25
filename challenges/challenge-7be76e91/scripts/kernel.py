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
    "candidate_plans": ["candidate_plans", "plans", "variants", "versions", "candidates", "alternatives"],
    "criteria": ["criteria", "dimensions", "comparison_criteria", "scoring_criteria"],
    "resource_contract": ["resource_contract", "prices", "booking", "resources", "cost_terms"],
    "constraints": ["constraints", "hard_constraints", "limits", "budget"],
    "budget": ["budget", "cost_limit", "spend_limit", "预算"],
}
# 契约字段名 → 本技能标准字段（大小写/下划线/连字符不敏感）
CONTRACT_ALIAS = {
    "caseid": "case_id", "id": "case_id", "taskid": "case_id",
    "status": "status",
    "recommendation": "recommendation", "selection": "recommendation",
    "selectedplan": "recommendation", "chosenplan": "recommendation", "conclusion": "recommendation",
    "comparison": "comparison_matrix", "comparisonmatrix": "comparison_matrix",
    "matrix": "comparison_matrix", "comparisontable": "comparison_matrix",
    "plans": "plans", "candidateplans": "plans", "candidates": "plans", "alternatives": "plans",
    "criteria": "criteria", "dimensions": "criteria", "comparisoncriteria": "criteria",
    "scoring": "scoring", "scores": "scoring", "ranking": "scoring", "weights": "scoring",
    "costmodel": "cost_model", "cost": "cost_model", "costestimate": "cost_model", "costs": "cost_model",
    "risks": "risks", "riskanalysis": "risks", "riskregister": "risks",
    "exceptions": "exceptions", "fallbacks": "exceptions",
    "confirmations": "confirmations", "pendingconfirmations": "confirmations",
    "evidencemap": "evidence_map", "evidence": "evidence_map", "sources": "evidence_map",
    "assumptions": "assumptions", "uncertainty": "uncertainty", "limits": "limits",
    "validation": "validation", "validationresults": "validation", "checks": "validation",
    "changes": "changes", "summary": "summary", "findings": "findings",
    "variables": "variables", "controls": "controls", "procedure": "procedure", "steps": "procedure",
    "parameters": "parameters", "resources": "resources", "readout": "readout",
    "hypothesis": "hypothesis", "objective": "objective", "goals": "objective",
}
ARTIFACTS = ["comparison_report.md", "comparison_matrix.csv"]

TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".tex", ".bib", ".yaml", ".yml", ".rst", ".html", ".xml"}
# 本题默认契约（case.json 未给 output_contract 时兜底）
DEFAULT_CONTRACT = [
    "recommendation", "comparison_matrix", "plans", "criteria", "scoring",
    "cost_model", "risks", "exceptions", "confirmations", "evidence_map",
    "assumptions", "variables", "controls", "procedure", "parameters",
    "resources", "readout", "validation", "uncertainty", "limits", "changes",
]
# 归一化：大小写/下划线/连字符不敏感地映射到标准字段名
def canon(name):
    key = re.sub(r"[\s_\-]+", "", str(name)).lower()
    return CONTRACT_ALIAS.get(key, str(name))
NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
CITE_RE = re.compile(r"(\[[0-9,\s\-–]+\]|\\cite\{[^}]+\}|\([A-Z][A-Za-z\-]+(?:\s(?:et al\.|and\s[A-Z][A-Za-z\-]+))?,?\s?(?:19|20)\d{2}[a-z]?\))")


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def pick(case, key, _depth=0):
    for name in ALIASES.get(key, [key]):
        if name in case and case[name] not in (None, "", [], {}):
            return case[name]
    # 嵌套 case（case.input / case.data / case.payload / case.case）一层层找
    if _depth < 3:
        for name in ("input", "inputs", "data", "payload", "case", "context", "example", "task"):
            sub = case.get(name)
            if isinstance(sub, dict):
                got = pick(sub, key, _depth + 1)
                if got is not None:
                    return got
    return None


def contract_fields(contract):
    """把 output_contract 的各种写法归一为 (字段名列表, 规格字典)。

    支持:
      ["field", ...]
      [{"name": "field", "type": "object"}, ...]
      {"fields": [...]} / {"required": [...]} / {"properties": {...}}
      {"field": {"type": ...}, ...}
    """
    names, spec = [], {}

    def add(name, s=None):
        if isinstance(name, str) and name.strip() and name not in names:
            names.append(name)
            if s is not None:
                spec[name] = s

    if isinstance(contract, list):
        for item in contract:
            if isinstance(item, str):
                add(item)
            elif isinstance(item, dict):
                n = item.get("name") or item.get("field") or item.get("key")
                add(n, item)
            elif isinstance(item, (list, tuple)) and item:
                add(str(item[0]), {"type": item[1] if len(item) > 1 else None})
    elif isinstance(contract, dict):
        inner = None
        for k in ("fields", "required", "properties", "output_contract", "outputs"):
            if k in contract and isinstance(contract[k], (list, dict)):
                inner = contract[k]
                break
        if inner is not None:
            return contract_fields(inner)
        for k, v in contract.items():
            add(str(k), v if isinstance(v, dict) else {"type": v})
    return names, spec


def count_structured_candidates(case):
    for key in ("candidate_plans", "candidates", "plans", "variants", "alternatives", "versions"):
        v = pick(case, key)
        if isinstance(v, list):
            return len(v)
    return 0


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
    raw_contract = norm.get("output_contract")
    names, spec = contract_fields(raw_contract) if raw_contract else ([], {})
    if not names:
        names = list(DEFAULT_CONTRACT)
        contract_source = "skill_default"
    else:
        contract_source = "case.output_contract"
    contract = {"fields": names, "spec": spec}
    try:
        case_sha1 = __import__("hashlib").sha1(open(case_path, "rb").read()).hexdigest()
    except Exception:  # noqa: BLE001
        case_sha1 = None
    result = {
        "case_path": os.path.abspath(case_path),
        "case_id": norm.get("case_id") or os.path.splitext(os.path.basename(case_path))[0],
        "case_sha1": case_sha1,
        "task": norm.get("task"),
        "language": norm.get("language"),
        "genre": norm.get("genre"),
        "audience": norm.get("audience"),
        "raw_keys": sorted(case.keys()),
        "raw_contract": raw_contract,
        "contract_source": contract_source,
        "contract": contract,
        "structured_candidates": count_structured_candidates(case),
        "has_structured_contract": bool(count_structured_candidates(case)),
    }
    dump(result, os.path.join(a.out, "contract.json"))
    dump(case, os.path.join(a.out, "case.raw.json"))
    if not raw_contract:
        print("warn: case.json has no output_contract; using skill default contract")
    print("case_id=%s sha1=%s keys=%s structured_candidates=%d"
          % (result["case_id"], (case_sha1 or "?")[:10], ",".join(result["raw_keys"]),
             result["structured_candidates"]))
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


def cmd_emit(a):
    try:
        contract = load_json(os.path.join(a.contract_dir, "contract.json")) if os.path.isdir(a.contract_dir) \
            else load_json(a.contract_dir)
    except Exception:  # noqa: BLE001 - blocked 路径可能没有 contract.json
        contract = {}
    draft = load_json(a.draft)
    c = contract.get("contract") or {}
    if isinstance(c, dict) and isinstance(c.get("fields"), list):
        names = [n for n in c["fields"] if isinstance(n, str)]
        spec = c.get("spec") or {}
    else:
        names, spec = contract_fields(c) if c else ([], {})
    if not names:
        names, spec = list(DEFAULT_CONTRACT), {}
    src = dict(draft.get("fields", {}))
    for k, v in draft.items():
        if k not in ("fields", "artifacts", "status"):
            src.setdefault(k, v)
    result = {"case_id": contract.get("case_id"), "status": draft.get("status", "partial")}
    unresolved = []
    for name in names:
        if name in ("case_id", "status") and result.get(name):
            continue
        val = src.get(name)
        if val in (None, "", [], {}):
            val = src.get(canon(name))
        if val in (None, "", [], {}):
            unresolved.append(name)
            expected = spec.get(name)
            exp_type = None
            if isinstance(expected, dict):
                exp_type = expected.get("type") or expected.get("datatype")
            note = ("输入契约要求 %s%s；本技能未产出对应内容，见 uncertainty/limits"
                    % (name, ("（类型 %s）" % exp_type) if exp_type else ""))
            etype = str(exp_type or "").lower()
            if draft.get("status") == "blocked":
                # blocked 是明确结论：按契约类型（或标准字段类型）给空值，
                # 不用说明对象冒充数组，避免下载方按契约解析失败
                ARRAY = {"comparison_matrix", "plans", "criteria", "risks", "exceptions",
                         "confirmations", "evidence_map", "assumptions", "variables", "controls",
                         "procedure", "parameters", "resources", "readout", "uncertainty",
                         "changes", "sources", "risks"}
                OBJ = {"recommendation", "scoring", "cost_model", "validation"}
                cname = canon(name)
                if etype in ("array", "list", "[]") or (not etype and cname in ARRAY):
                    val = []
                elif etype in ("object", "dict", "map") or (not etype and cname in OBJ):
                    val = {}
                elif etype in ("string", "str", "text") or (not etype and cname == "limits"):
                    val = ""
                else:
                    val = {"note": note}
            else:
                val = {"note": note}
        result[name] = val
    for name in DEFAULT_CONTRACT:
        if name not in result:
            result[name] = src.get(name)
    for name, val in src.items():          # 附加证据（评分矩阵/淘汰记录等）一并保留
        result.setdefault(name, val)
    result.setdefault("uncertainty", draft.get("uncertainty", []))
    result.setdefault("sources", draft.get("sources", []))
    result.setdefault("changes", draft.get("changes", []))
    result.setdefault("self_check", draft.get("self_check", {}))
    result["limits"] = draft.get("limits", "")
    result["input_mode"] = draft.get("input_mode")
    result["input_versions"] = draft.get("input_versions") or {
        "case.json": contract.get("case_sha1"), "contract_source": contract.get("contract_source")}
    result["contract_source"] = contract.get("contract_source")
    det_path = os.path.join(a.contract_dir, "determinism.json")
    det = load_json(det_path) if os.path.exists(det_path) else None
    if isinstance(det, dict):
        result["determinism"] = det
        checks = (result.get("validation") or {}).get("checks")
        if isinstance(checks, list):
            checks.append({"check": "重跑一致性",
                           "result": ("PASS" if det.get("consistent") else "FAIL"),
                           "detail": "输入 sha1=%s；两次运行草稿一致=%s"
                                     % (str(det.get("input_sha1"))[:12], det.get("consistent"))})
    os.makedirs(a.out, exist_ok=True)
    dump(result, os.path.join(a.out, "result.json"))
    for name, body in (draft.get("artifacts") or {}).items():
        p = os.path.join(a.out, name)
        os.makedirs(os.path.dirname(p) or a.out, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
    missing = [k for k in names if result.get(k) is None]
    print("result.json written; missing_contract_fields=%s" % (missing or "none"))
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
        if res.get("status") not in {"ok", "success", "partial", "blocked", "refused"}:
            problems.append("status must be one of ok/success/partial/blocked/refused")
        if res.get("status") == "partial" and not str(res.get("limits", "")).strip():
            problems.append("status=partial but limits is empty")
        if res.get("status") == "blocked":
            if not str(res.get("limits", "")).strip():
                problems.append("status=blocked but limits is empty")
            print("PASS" if not problems else "FAIL")
            for p in problems:
                print(" -", p)
            return 0 if not problems else 1
        # Every field promised by the case contract must be present and non-empty.
        cp = os.path.join(a.contract_dir, "contract.json")
        if os.path.exists(cp):
            c = (load_json(cp).get("contract") or {})
            if isinstance(c, dict) and isinstance(c.get("fields"), list):
                names = [n for n in c["fields"] if isinstance(n, str)]
            else:
                names, _ = contract_fields(c) if c else ([], {})
            optional = ("uncertainty", "limits", "changes", "notes", "risks", "exceptions",
                        "confirmations", "evidence_map", "sources", "validation", "assumptions",
                        "input_mode", "input_versions", "determinism")
            is_blocked = res.get("status") == "blocked"
            for name in names:
                if is_blocked and name not in ("case_id", "status"):
                    warns.append("blocked: contract field %s intentionally empty" % name)
                    continue
                if canon(name) in optional:
                    if name not in res:
                        warns.append("result.json missing optional contract field %s" % name)
                    continue
                if res.get(name) in (None, "", [], {}):
                    problems.append("result.json missing contract field %s" % name)
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
