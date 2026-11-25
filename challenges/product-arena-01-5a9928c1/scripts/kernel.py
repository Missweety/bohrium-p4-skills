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
}

TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".tex", ".bib", ".yaml", ".yml", ".rst", ".html", ".xml"}
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
    """Return (text, reason). Empty text means there is no usable text layer."""
    notes = []
    try:
        import subprocess
        r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", "replace"), ""
        notes.append("pdftotext_empty" if r.returncode == 0 else "pdftotext_rc%d" % r.returncode)
    except FileNotFoundError:
        notes.append("pdftotext_missing")
    except Exception as exc:  # noqa: BLE001
        notes.append("pdftotext_error:%s" % exc)
    try:
        from pypdf import PdfReader  # type: ignore
        text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
        if text.strip():
            return text, ""
        notes.append("pypdf_empty")
    except Exception as exc:  # noqa: BLE001
        notes.append("pypdf_error:%s" % exc)
    return "", "no_text_layer(%s)" % ",".join(notes)


def read_text(path):
    """Decode with a fallback chain; GBK material used to come out as U+FFFD noise."""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8/replace"


def extract(path):
    """Return (text, ok, reason, encoding). Never passes a placeholder off as real text."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        try:
            text = read_docx(path)
        except Exception as exc:  # noqa: BLE001
            return "", False, "docx_unreadable: %s" % exc, ""
        return (text, True, "", "utf-8") if text.strip() else ("", False, "docx_no_text", "")
    if ext in {".xlsx", ".xlsm"}:
        text = read_xlsx(path)
        return (text, True, "", "utf-8") if text.strip() else ("", False, "xlsx_no_text", "")
    if ext == ".pdf":
        text, reason = read_pdf(path)
        return text, bool(text.strip()), reason, "utf-8"
    if ext in TEXT_EXT:
        text, enc = read_text(path)
        reason = "garbled_replacement_chars" if "\ufffd" in text else ""
        return text, bool(text.strip()), reason, enc
    if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".svg"}:
        return "", False, "image_asset_not_indexed", ""
    return "", False, "unsupported_type:%s" % (ext or "none"), ""


def num_tokens(text):
    """Set of numeric tokens, compared as whole tokens instead of substrings.

    Substring matching let a fabricated '2000 xg' pass because '2000' occurs inside
    the sourced '12000 xg'. Token membership keeps that mismatch visible. Comma
    separated cells ("10,4.2,0.31" in a stats CSV) are also exposed part by part,
    because NUM_RE treats commas as thousands separators.
    """
    toks = set()
    for m in NUM_RE.finditer(text):
        raw = m.group(0).strip().replace(" ", "")
        toks.add(raw)
        toks.update(p for p in raw.split(",") if p and p not in {"-", "+"})
    return toks


def strip_step_markers(text):
    """Drop leading step numbering ("1)", "(2)", "3、") so it is not audited as data."""
    return re.sub(r"(?m)^\s*(?:\d+[.)、]|\(\d+\)|[（(]\d+[)）])\s*", "", text)


def locate(snippet, corpus, source):
    """Return a human-checkable locator: line number(s) + char offset."""
    idx = corpus.find(snippet[:80])
    if idx < 0:
        return None
    line = corpus.count("\n", 0, idx) + 1
    return {"source": source, "line": line, "offset": idx}


def sha1_of(path):
    return __import__("hashlib").sha1(open(path, "rb").read()).hexdigest()


def resolve_material(p, a):
    """Resolve a material path that may be relative to the case file (harness writes /input/case.json)."""
    cands = [p]
    if not os.path.isabs(p):
        if getattr(a, "case", None):
            cands.append(os.path.join(os.path.dirname(os.path.abspath(a.case)), p))
        cp = os.path.join(a.out, "contract.json")
        if os.path.exists(cp):
            try:
                base = os.path.dirname(load_json(cp).get("case_path") or "")
                if base:
                    cands.append(os.path.join(base, p))
            except Exception:  # noqa: BLE001
                pass
        cands.append(os.path.join("/input", p))
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


# ---------------------------------------------------------------- commands
def cmd_init(a):
    case_path = find_case_file(a.case)
    if not case_path:
        dump({"status": "blocked", "missing": "case.json not found"}, os.path.join(a.out, "contract.json"))
        print("blocked: case.json not found")
        return 1
    try:
        case = load_json(case_path)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        dump({"status": "blocked", "error": "case.json is not valid JSON: %s" % exc,
              "case_path": os.path.abspath(case_path)}, os.path.join(a.out, "contract.json"))
        print("blocked: case.json is not valid JSON: %s" % exc)
        return 1
    if not isinstance(case, dict):
        dump({"status": "blocked", "error": "case.json top level must be an object, got %s" % type(case).__name__,
              "case_path": os.path.abspath(case_path)}, os.path.join(a.out, "contract.json"))
        print("blocked: case.json top level must be an object, got %s" % type(case).__name__)
        return 1
    norm = {k: pick(case, k) for k in ALIASES}
    contract = norm.get("output_contract") or {}
    if isinstance(contract, list):
        contract = {"fields": contract}
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
    missing = [p for p in a.materials if not resolve_material(p, a)]
    items, corpus = [], []
    for raw in a.materials:
        root = resolve_material(raw, a)
        if not root:
            # Do not let a typo'd or cwd-relative material path look like a successful empty index.
            print("MISSING %s" % raw)
            continue
        walk = [(root, [], [os.path.basename(root)])] if os.path.isfile(root) else os.walk(root)
        for dirpath, dirnames, names in walk:
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for n in sorted(names):
                if n.startswith("."):
                    continue
                p = root if (dirpath == root and n == os.path.basename(root)) else os.path.join(dirpath, n)
                if not os.path.isfile(p):
                    continue
                text, ok, reason, enc = extract(p)
                if ok and "\ufffd" in text:
                    reason = "garbled_replacement_chars"
                items.append({"path": p, "bytes": os.path.getsize(p), "chars": len(text),
                              "readable": ok, "reason": reason, "encoding": enc, "sha1": sha1_of(p)})
                corpus.append("===== FILE: %s =====\n%s" % (p, text if ok else "[unreadable: %s]" % reason))
    dump({"files": items, "total_chars": sum(i["chars"] for i in items),
          "unreadable": [i["path"] for i in items if not i["readable"]],
          "readable_files": sum(1 for i in items if i["readable"]),
          "missing_inputs": missing},
         os.path.join(a.out, "evidence.json"))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "corpus.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(corpus))
    for i in items:
        print("%-8s %8d  %s%s" % ("ok" if i["readable"] else "UNREAD", i["chars"], i["path"],
                                  "" if i["readable"] else "  <- " + i["reason"]))
    if not items:
        print("BLOCKED: no material indexed (missing=%d); do not translate from memory" % len(missing))
        return 1
    if not any(i["readable"] for i in items):
        print("WARN: every material is unreadable; downstream must report partial/blocked")
        return 1
    if missing:
        print("WARN: %d material(s) missing; record them in limits" % len(missing))
    return 0


def cmd_verify(a):
    corpus_path = os.path.join(a.evidence_dir, "corpus.txt")
    if not os.path.exists(corpus_path):
        print("FAIL: evidence index missing (%s); run `index` first" % corpus_path)
        return 1
    if not os.path.exists(a.text):
        print("FAIL: draft not found: %s" % a.text)
        return 1
    corpus = open(corpus_path, encoding="utf-8").read()
    ev_path = os.path.join(a.evidence_dir, "evidence.json")
    ev = {}
    if os.path.exists(ev_path):
        try:
            ev = load_json(ev_path)
        except json.JSONDecodeError:
            print("WARN: evidence.json is corrupt; continuing with corpus only")
    draft = open(a.text, encoding="utf-8").read()
    numbers = []
    for m in NUM_RE.finditer(strip_step_markers(draft)):
        tok = m.group(0).strip()
        if len(tok) < 2 and not tok.isdigit():
            continue
        numbers.append(tok)
    corpus_tokens = num_tokens(corpus)
    unsupported = [n for n in dict.fromkeys(numbers)
                   if n.replace(" ", "") not in corpus_tokens]
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
    return 0 if report["verdict"] == "pass" else 1


def contract_field_names(contract):
    """Required field names from contract.json, tolerating both contract shapes.

    Dict contract: keys are field names. List contract (init wraps it as
    {"fields": [...]}): the list items are field names. The list case used to be
    treated as one field literally named "fields", so result.json lost every
    contract field while every check still reported success.
    """
    c = contract.get("contract") or {}
    if isinstance(c, list):
        return [str(x) for x in c]
    if isinstance(c, dict):
        if set(c.keys()) == {"fields"} and isinstance(c["fields"], list):
            return [str(x) for x in c["fields"]]
        return list(c.keys())
    return []


def field_missing(name, value, status):
    """Required-field check. Empty lists/dicts are valid answers ("uncertainty: []"),
    and `limits` is only mandatory for status=partial."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return not (name == "limits" and status != "partial")
    return False


def cmd_emit(a):
    contract = load_json(os.path.join(a.contract_dir, "contract.json")) if os.path.isdir(a.contract_dir) \
        else load_json(a.contract_dir)
    draft = load_json(a.draft)
    names = contract_field_names(contract)
    result = {"case_id": contract.get("case_id") or draft.get("case_id"),
              "status": draft.get("status", "partial")}
    given = draft.get("fields", {}) or {}
    for name in names:
        value = given.get(name, draft.get(name))
        # Do not overwrite a value already backfilled from the contract (case_id).
        if value is not None or result.get(name) is None:
            result[name] = value
    result.setdefault("uncertainty", draft.get("uncertainty", []))
    result.setdefault("sources", draft.get("sources", []))
    result.setdefault("changes", draft.get("changes", []))
    result["limits"] = draft.get("limits", "")
    os.makedirs(a.out, exist_ok=True)
    dump(result, os.path.join(a.out, "result.json"))
    for name, body in (draft.get("artifacts") or {}).items():
        p = os.path.join(a.out, name)
        os.makedirs(os.path.dirname(p) or a.out, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, indent=1))
    missing = [k for k in names if field_missing(k, result.get(k), result["status"])]
    print("result.json written; missing_contract_fields=%s" % (missing or "none"))
    return 0 if not missing else 1


def cmd_check(a):
    problems = []
    rp = os.path.join(a.out, "result.json")
    res = {}
    if not os.path.exists(rp):
        problems.append("result.json missing")
    else:
        try:
            res = load_json(rp)
        except json.JSONDecodeError as exc:
            res = {}
            problems.append("result.json is not valid JSON: %s" % exc)
        for k in ("case_id", "status"):
            if not res.get(k):
                problems.append("result.json missing %s" % k)
        if res.get("status") not in {"ok", "success", "partial", "blocked", "refused"}:
            problems.append("status must be one of ok/success/partial/blocked/refused")
        if res.get("status") == "partial" and not str(res.get("limits") or "").strip():
            problems.append("status=partial requires non-empty limits")
        cp = os.path.join(a.contract_dir, "contract.json") if a.contract_dir else ""
        if cp and os.path.exists(cp):
            try:
                for name in contract_field_names(load_json(cp)):
                    if field_missing(name, res.get(name), res.get("status")):
                        problems.append("result.json missing contract field: %s" % name)
            except json.JSONDecodeError as exc:
                problems.append("contract.json is not valid JSON: %s" % exc)
    print("PASS" if not problems else "FAIL")
    for p in problems:
        print(" -", p)
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("--case"); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("index"); p.add_argument("--materials", nargs="+", required=True)
    p.add_argument("--case", help="case.json path used to resolve relative material paths")
    p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("verify"); p.add_argument("--text", required=True); p.add_argument("--evidence-dir", default="work"); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("emit"); p.add_argument("--draft", required=True); p.add_argument("--contract-dir", default="work"); p.add_argument("--out", default="/app/output"); p.set_defaults(fn=cmd_emit)
    p = sub.add_parser("check"); p.add_argument("--out", default="/app/output"); p.add_argument("--contract-dir", default="work"); p.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
