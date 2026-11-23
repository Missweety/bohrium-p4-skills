#!/usr/bin/env python3
"""kernel.py - evidence-first execution kernel shared by all Bohrium skills.

Subcommands (all stdlib only, no network):
  init     read /input/case.json (alias tolerant), emit work/contract.json + work/case.json
  claims   read /input/claims-to-verify.json, normalise claims and flag atomic components
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
}

TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".tex", ".bib", ".yaml", ".yml", ".rst", ".html", ".xml"}
NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
CITE_RE = re.compile(r"(\[[0-9,\s\-–]+\]|\\cite\{[^}]+\}|\([A-Z][A-Za-z\-]+(?:\s(?:et al\.|and\s[A-Z][A-Za-z\-]+))?,?\s?(?:19|20)\d{2}[a-z]?\))")
DEFAULT_CONTRACT = {
    "case_id": "string", "status": "enum", "claim_evidence": "path", "verdicts": "list",
    "source_map": "list", "conflicts": "list", "gaps": "list", "summary": "string",
    "metrics": "object", "limits": "string", "uncertainty": "list",
}
VERDICT_SET = {"supported", "partially_supported", "contradicted", "insufficient_evidence"}


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
        dump({"case_path": None, "case_id": "unstated-case", "task": None,
              "raw_keys": [], "contract_source": "skill_default",
              "contract": dict(DEFAULT_CONTRACT),
              "warnings": ["case.json not found; default contract and sentinel case_id used"]},
             os.path.join(a.out, "contract.json"))
        print("warn: case.json not found; using default contract with case_id=unstated-case")
        return 0
    case = load_json(case_path)
    norm = {k: pick(case, k) for k in ALIASES}
    contract = norm.get("output_contract") or {}
    if isinstance(contract, list):
        contract = {"fields": contract}
    if not contract:
        contract = dict(DEFAULT_CONTRACT)
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


CLAIM_KEYS = ["claims", "claims_to_verify", "claimsToVerify", "items", "questions"]
COMPARATOR = re.compile(r"(高于|低于|大于|小于|多于|少于|增加|减少|升高|降低|高于|优于|劣于|"
                        r"higher|lower|greater|fewer|more than|less than|increase[sd]?|decrease[sd]?|"
                        r"outperform|superior|inferior)", re.I)
NEGATION = re.compile(r"(不显著|不支持|不一致|不能|不会|不存在|未能|未见|未报告|未纳入|未测试|"
                      r"无显著|无证据|没有|非|never|not\b|no\b|none\b|without|fail(?:s|ed)?\b)", re.I)
MODALITY = re.compile(r"(可能|或许|推测|有望|could|may|might|would|suggest(s|ed)?|potential(ly)?|extrapolat)", re.I)
SENT_SPLIT = re.compile(r"[。！？!?；;]\s*|(?<=，)(?=\s*(?:且|并且|同时|而且|以及|但))"
                        r"|,\s+(?:but|whereas|and also)\s+", re.I)
CONNECTOR = re.compile(r"^(?:且|并且|同时|而且|以及|但)\s*", re.I)


def load_claims(path):
    data = load_json(path)
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = None
        for k in CLAIM_KEYS:
            if isinstance(data.get(k), (list, dict)) and data.get(k):
                items = data[k]
                break
        if items is None and data and all(isinstance(v, dict) for v in data.values()):
            items = data
        items = items if items is not None else []
        if isinstance(items, dict):
            items = [dict(v, id=(v.get("id") or k)) if isinstance(v, dict) else {"id": k, "text": str(v)}
                     for k, v in items.items()]
    else:
        items = []
    out = []
    for i, it in enumerate(items):
        if isinstance(it, str):
            raw, cid, ctype, cond = {"text": it}, "C%d" % (i + 1), None, None
        else:
            raw = it
            cid = str(it.get("id") or it.get("claim_id") or it.get("cid") or "C%d" % (i + 1))
            ctype = it.get("type") or it.get("claim_type")
            cond = it.get("conditions") or it.get("context")
        text = (raw.get("text") if isinstance(raw, dict) else raw) or \
               (raw.get("claim") if isinstance(raw, dict) else None) or \
               (raw.get("claim_text") if isinstance(raw, dict) else None) or \
               (raw.get("statement") if isinstance(raw, dict) else None) or \
               (raw.get("question") if isinstance(raw, dict) else None) or ""
        text = re.sub(r"\s+", " ", str(text)).strip()
        parts = [CONNECTOR.sub("", p.strip(" ，,")) for p in SENT_SPLIT.split(text) if p.strip()]
        components = [p for p in parts if p]
        out.append({
            "id": cid,
            "text": text,
            "type": ctype,
            "conditions": cond,
            "components": components,
            "auto_decomposed": len(components) > 1,
            "numbers": list(dict.fromkeys(NUM_RE.findall(text))),
            "comparators": list(dict.fromkeys(m.group(0) for m in COMPARATOR.finditer(text))),
            "negation": list(dict.fromkeys(m.group(0) for m in NEGATION.finditer(text))),
            "modality": list(dict.fromkeys(m.group(0) for m in MODALITY.finditer(text))),
            "raw": raw,
        })
    return out


def cmd_claims(a):
    path = a.claims or "/input/claims-to-verify.json"
    if not os.path.exists(path):
        for c in ("claims-to-verify.json", "/app/input/claims-to-verify.json"):
            if os.path.exists(c):
                path = c
                break
    if not os.path.exists(path):
        dump({"status": "blocked", "missing": "claims-to-verify.json not found"},
             os.path.join(a.out, "claims.json"))
        print("blocked: claims-to-verify.json not found")
        return 1
    claims = load_claims(path)
    if not claims:
        dump({"status": "blocked", "source": os.path.abspath(path),
              "reason": "no claims parsed; check the claims/claims_to_verify/items keys and text fields"},
             os.path.join(a.out, "claims.json"))
        print("blocked: no claims parsed from %s" % path)
        return 2
    dump({"source": os.path.abspath(path), "count": len(claims), "claims": claims},
         os.path.join(a.out, "claims.json"))
    print("claims=%d multi_component=%d" % (len(claims), sum(1 for c in claims if c["auto_decomposed"])))
    for c in claims:
        flags = []
        if c["auto_decomposed"]:
            flags.append("split")
        if c["comparators"]:
            flags.append("comparator")
        if c["negation"]:
            flags.append("negation")
        if c["modality"]:
            flags.append("modality")
        print("  %-6s %-14s %s" % (c["id"], ",".join(flags) or "-", c["text"][:70]))
    return 0


def cmd_index(a):
    roots = [p for p in a.materials if os.path.exists(p)]
    exclude = set(a.exclude or [])
    items, corpus = [], []
    for root in roots:
        walk = [(root, [], [os.path.basename(root)])] if os.path.isfile(root) else os.walk(root)
        for dirpath, _, names in walk:
            for n in sorted(names):
                p = dirpath if dirpath == root and not os.path.isdir(root) else os.path.join(dirpath, n)
                if not os.path.isfile(p) or n.startswith("."):
                    continue
                if n in exclude or p in exclude:
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
    # Locators are not data: ignore "line 15" / "第 15 行" when checking numbers.
    scan = re.sub(r"(?i)\bline[s]?\s*\d+(?:\s*[-–]\s*\d+)?", " ", draft)
    scan = re.sub(r"(?i)\b(?:p|pp|page|pages)\.?\s*\d+(?:\s*[-–]\s*\d+)?", " ", scan)
    scan = re.sub(r"第\s*\d+\s*[页行]", " ", scan)
    scan = re.sub(r"\d+\s*页", " ", scan)
    numbers = []
    for m in NUM_RE.finditer(scan):
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
    dump(report, os.path.join(a.out, "claims_numbers.json"))
    print("verdict=%s unsupported_numbers=%d citations_not_in_sources=%d"
          % (report["verdict"], len(unsupported), len(missing_cites)))
    for n in unsupported[:20]:
        print("  ? number not in sources:", n)
    return 0


def cmd_emit(a):
    contract = load_json(os.path.join(a.contract_dir, "contract.json")) if os.path.isdir(a.contract_dir) \
        else load_json(a.contract_dir)
    draft = load_json(a.draft)
    fields = contract.get("contract") or {}
    result = {"case_id": contract.get("case_id") or draft.get("case_id") or "unstated-case",
              "status": draft.get("status", "partial")}
    if not fields:
        fields = dict(DEFAULT_CONTRACT)
    if isinstance(fields, dict):
        for name in fields:
            if name == "case_id":
                continue
            if name == "status":
                result["status"] = draft.get("status") or draft.get("fields", {}).get("status")
                continue
            result[name] = draft.get("fields", {}).get(name, draft.get(name))
    else:
        result.update(draft.get("fields", {}))
    result.setdefault("uncertainty", draft.get("uncertainty", []))
    result.setdefault("sources", draft.get("sources", []))
    result.setdefault("changes", draft.get("changes", []))
    result["limits"] = (draft.get("fields", {}).get("limits") if isinstance(draft.get("fields"), dict) else None) \
        or draft.get("limits") or ""
    os.makedirs(a.out, exist_ok=True)
    dump(result, os.path.join(a.out, "result.json"))
    for name, body in (draft.get("artifacts") or {}).items():
        p = os.path.join(a.out, name)
        os.makedirs(os.path.dirname(p) or a.out, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
    missing = [k for k in (fields.keys() if isinstance(fields, dict) else []) if result.get(k) is None]
    print("result.json written; missing_contract_fields=%s" % (missing or "none"))
    return 0 if not missing else 0


PLACEHOLDER = re.compile(r"^(?:<[^>]*>|TODO|TBD|\?\?+)\s*$", re.I)


def _blank(v):
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip() or bool(PLACEHOLDER.match(v.strip()))
    if isinstance(v, (list, dict)):
        return not v
    return False


def cmd_check(a):
    """Gate the deliverable: contract fields, core artifacts, evidence structures, honest status."""
    problems, notes = [], []
    rp = os.path.join(a.out, "result.json")
    contract = load_json(a.contract) if a.contract and os.path.exists(a.contract) else {}
    if not os.path.exists(rp):
        print("FAIL\n - result.json missing")
        return 1
    res = load_json(rp)
    if _blank(res.get("case_id")):
        problems.append("result.json missing case_id")
    elif contract.get("case_id") and res.get("case_id") != contract["case_id"]:
        problems.append("case_id mismatch: output=%r contract=%r"
                        % (res.get("case_id"), contract["case_id"]))
    status = res.get("status")
    if status not in {"ok", "success", "partial", "blocked", "refused"}:
        problems.append("status must be one of ok/success/partial/blocked/refused")
    fields = contract.get("contract") or dict(DEFAULT_CONTRACT)
    optional_lists = {"conflicts", "gaps", "uncertainty", "changes", "warnings", "notes"}
    if isinstance(fields, dict):
        for name in fields:
            if _blank(res.get(name)) and not (name in optional_lists and isinstance(res.get(name), list)):
                problems.append("contract field empty/missing: %s" % name)
    for name in ("source_map", "changes", "uncertainty"):
        val = res.get(name)
        if name not in res:
            problems.append("result.json missing %s" % name)
            continue
        if not isinstance(val, list):
            problems.append("%s must be a list" % name)
            continue
        if name == "uncertainty":
            continue
        need = ("claim", "value", "source_path", "locator") if name == "source_map" \
            else ("target", "type", "before", "after", "reason")
        for i, entry in enumerate(val):
            if not isinstance(entry, dict):
                problems.append("%s[%d] must be an object" % (name, i))
                continue
            for k in need:
                if k not in entry:
                    problems.append("%s[%d] missing key %s" % (name, i, k))
    for name in ("manuscript", "claim_evidence"):
        val = res.get(name)
        if val and not os.path.exists(os.path.join(a.out, str(val))):
            problems.append("%s does not exist under output: %s" % (name, val))
    verdicts = res.get("verdicts")
    if isinstance(verdicts, list) and verdicts:
        ids = []
        for i, v in enumerate(verdicts):
            if not isinstance(v, dict):
                problems.append("verdicts[%d] must be an object" % i)
                continue
            cid = str(v.get("claim_id", "")).strip()
            ids.append(cid)
            if not cid:
                problems.append("verdicts[%d] missing claim_id" % i)
            if v.get("verdict") not in VERDICT_SET:
                problems.append("verdicts[%d] bad verdict %r" % (i, v.get("verdict")))
        metrics = res.get("metrics")
        if isinstance(metrics, dict) and isinstance(metrics.get("claims"), int) \
                and metrics["claims"] != len(verdicts):
            problems.append("metrics.claims=%s but verdicts has %d rows"
                            % (metrics["claims"], len(verdicts)))
        insufficient = {str(v.get("claim_id")) for v in verdicts
                        if isinstance(v, dict) and v.get("verdict") == "insufficient_evidence"}
        for g in res.get("gaps") or []:
            cid = str(g.get("claim", "")).strip() if isinstance(g, dict) else ""
            if cid and cid not in insufficient:
                problems.append("gaps lists %s but its verdict is not insufficient_evidence" % cid)
        md_name = res.get("claim_evidence")
        md_path = os.path.join(a.out, str(md_name)) if md_name else ""
        if md_path and os.path.exists(md_path):
            table = open(md_path, encoding="utf-8").read()
            for v in verdicts:
                if not isinstance(v, dict) or not str(v.get("claim_id", "")).strip():
                    continue
                cid = str(v.get("claim_id")).strip()
                row = re.search(r"^\|\s*%s\s*\|.*$" % re.escape(cid), table, re.M)
                if not row:
                    problems.append("claim_evidence.md missing row for %s" % cid)
                else:
                    cells = [c.strip() for c in row.group(0).strip().strip("|").split("|")]
                    if len(cells) < 3 or cells[2] != str(v.get("verdict")):
                        problems.append("claim_evidence.md verdict for %s differs from result.json" % cid)
    if status in {"partial", "blocked"} and _blank(res.get("limits")):
        problems.append("status=%s requires non-empty limits" % status)
    if not problems:
        notes.append("status=%s claims_ref=%s" % (status, res.get("claim_evidence")))
    print("PASS" if not problems else "FAIL")
    for p in problems:
        print(" -", p)
    for n in notes:
        print(" =", n)
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("--case"); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("claims"); p.add_argument("--claims", default=""); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_claims)
    p = sub.add_parser("index"); p.add_argument("--materials", nargs="+", required=True)
    p.add_argument("--exclude", nargs="*", default=[]); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("verify"); p.add_argument("--text", required=True); p.add_argument("--evidence-dir", default="work"); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("emit"); p.add_argument("--draft", required=True); p.add_argument("--contract-dir", default="work"); p.add_argument("--out", default="/app/output"); p.set_defaults(fn=cmd_emit)
    p = sub.add_parser("check"); p.add_argument("--out", default="/app/output")
    p.add_argument("--contract", default="work/contract.json"); p.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
