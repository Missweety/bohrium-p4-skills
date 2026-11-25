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


def _num_forms(tok):
    """Whitespace/percent/thousand-separator variants of one numeric token."""
    forms = {tok, tok.replace(" ", ""), re.sub(r"[%‰]$", "", tok).strip(),
             re.sub(r"(?<=\d),(?=\d{3}\b)", "", tok)}
    return [f for f in forms if f]


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


def normalize_contract(raw):
    """Flatten every observed output_contract shape into {field_name: spec}.

    Accepted: {"case_id": "string", ...} | {"fields": {...}} | {"fields": ["a", "b"]}
    | ["a", "b"]. Anything else yields {} so the caller falls back to the skill default.
    """
    if isinstance(raw, list):
        return {str(n): None for n in raw if str(n).strip()}
    if isinstance(raw, dict):
        inner = raw.get("fields")
        if isinstance(inner, dict):
            return dict(inner)
        if isinstance(inner, list):
            return {str(n): None for n in inner if str(n).strip()}
        return dict(raw)
    return {}


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
    try:
        case = load_json(case_path)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        msg = "case.json unreadable: %s" % exc
        dump({"status": "blocked", "case_path": os.path.abspath(case_path), "error": msg},
             os.path.join(a.out, "contract.json"))
        print("blocked: " + msg)
        return 1
    if not isinstance(case, dict):
        dump({"status": "blocked", "case_path": os.path.abspath(case_path),
              "error": "case.json top level is %s, expected object" % type(case).__name__},
             os.path.join(a.out, "contract.json"))
        print("blocked: case.json top level is not an object")
        return 1
    norm = {k: pick(case, k) for k in ALIASES}
    raw_contract = norm.get("output_contract") or {}
    contract = normalize_contract(raw_contract)
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
        "contract_raw": raw_contract,
    }
    dump(result, os.path.join(a.out, "contract.json"))
    dump(case, os.path.join(a.out, "case.raw.json"))
    if not contract:
        print("warn: case.json has no usable output_contract; using skill default contract")
    print("case_id=%s contract_fields=%d keys=%s"
          % (result["case_id"], len(contract), ",".join(result["raw_keys"])))
    return 0


def cmd_index(a):
    missing = [p for p in a.materials if not os.path.exists(p)]
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
                raw_bytes = open(p, "rb").read()
                try:
                    raw_bytes.decode("utf-8")
                    encoding = "utf-8"
                except UnicodeDecodeError:
                    encoding = "non-utf8 (decoded with replacement; verify numbers/names by hand)"
                items.append({
                    "path": p,
                    "bytes": os.path.getsize(p),
                    "chars": len(text),
                    "encoding": encoding,
                    "readable": not text.startswith("["),
                    "sha1": __import__("hashlib").sha1(raw_bytes).hexdigest(),
                })
                corpus.append("===== FILE: %s =====\n%s" % (p, text))
    dump({"files": items, "total_chars": sum(i["chars"] for i in items),
          "missing_materials": missing,
          "unreadable": [i["path"] for i in items if not i["readable"]]},
         os.path.join(a.out, "evidence.json"))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "corpus.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(corpus))
    for p in missing:
        print("missing material:", p)
    if not items:
        print("warn: no readable material found; do not fill reference data from memory")
    for i in items:
        print("%-8s %8d  %s%s" % ("ok" if i["readable"] else "UNREAD", i["chars"], i["path"],
                                  "" if i["encoding"] == "utf-8" else "  [%s]" % i["encoding"]))
    return 0


def cmd_verify(a):
    for p, label in ((a.text, "draft text"), (os.path.join(a.evidence_dir, "corpus.txt"), "corpus"),
                     (os.path.join(a.evidence_dir, "evidence.json"), "evidence index")):
        if not os.path.exists(p):
            print("missing %s: %s (run index/emit first)" % (label, p))
            return 1
    corpus = open(os.path.join(a.evidence_dir, "corpus.txt"), encoding="utf-8").read()
    ev = load_json(os.path.join(a.evidence_dir, "evidence.json"))
    draft = open(a.text, encoding="utf-8").read()
    # Markdown heading numbers ("## 3.2") and citation markers ("[37]") are not measured
    # values; scanning them produced false unsupported_numbers that cannot be cleared honestly.
    scan_text = CITE_RE.sub(" ", re.sub(r"^#{1,6}\s.*$", "", draft, flags=re.M))
    numbers = []
    for m in NUM_RE.finditer(scan_text):
        tok = m.group(0).strip()
        if len(tok) < 2 and not tok.isdigit():
            continue
        numbers.append(tok)
    unsupported = [n for n in dict.fromkeys(numbers)
                   if not any(form in corpus for form in _num_forms(n))]
    # Merged tokens such as "[3,5]" are a single valid citation, not a source string;
    # expand them and require each number to exist as its own "[n]" marker in the corpus.
    cites = list(dict.fromkeys(CITE_RE.findall(draft)))
    missing_cites = []
    for c in cites:
        if c.startswith("["):
            nums = [int(x) for x in re.findall(r"\d+", c)]
            if nums and all(("[%d]" % n) in corpus for n in nums):
                continue
        elif c.startswith("\\cite"):
            keys = [k.strip() for k in c[c.find("{") + 1:c.rfind("}")].split(",") if k.strip()]
            if keys and all(k in corpus for k in keys):
                continue
        missing_cites.append(c)
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
    cp = os.path.join(a.contract_dir, "contract.json") if os.path.isdir(a.contract_dir) else a.contract_dir
    try:
        contract = load_json(cp)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        print("warn: contract unreadable (%s); emitting from draft fields only" % exc)
        contract = {}
    try:
        draft = load_json(a.draft)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        print("error: draft unreadable (%s): %s" % (a.draft, exc))
        return 2
    names = normalize_contract(contract.get("contract") or {}).keys()
    draft_fields = draft.get("fields") if isinstance(draft.get("fields"), dict) else {}
    result = {"case_id": contract.get("case_id"), "status": draft.get("status", "partial")}
    if names:
        for name in names:
            if name in ("case_id", "status"):
                continue  # identity/status come from the case file and the draft, never from fields
            result[name] = draft_fields.get(name, draft.get(name))
    else:
        result.update({k: v for k, v in draft_fields.items() if k not in ("case_id", "status")})
    result.setdefault("uncertainty", draft.get("uncertainty", []))
    result.setdefault("sources", draft.get("sources", []))
    result.setdefault("changes", draft.get("changes", []))
    result.setdefault("self_check", draft.get("self_check", {}))
    result["limits"] = draft.get("limits", "")
    if not result.get("case_id"):
        result["case_id"] = draft.get("case_id") or contract.get("case_id")
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


def cmd_extract(a):
    """Dump one material to a deterministic text file (docx/pdf/xlsx -> markdown-safe text)."""
    if not os.path.exists(a.path):
        print("missing:", a.path)
        return 1
    text = extract(a.path)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("%d chars -> %s" % (len(text), a.out))
    return 0 if not text.startswith("[") else 1


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
        cp = os.path.join(a.contract_dir, "contract.json")
        if os.path.exists(cp):
            names = list(normalize_contract(load_json(cp).get("contract") or {}))
            nested = res.get("fields")
            if isinstance(nested, dict) and any(n in nested for n in names):
                problems.append("contract fields are nested under result.json['fields']; "
                                "they must be top-level keys")
            for name in names:
                # Empty uncertainty/limits are legitimate: uncertainty may be [], limits may be "".
                if name in ("uncertainty", "limits", "changes", "notes"):
                    if name not in res:
                        problems.append("result.json missing contract field %s" % name)
                    elif res.get("status") == "partial" and not str(res.get("limits", "")).strip():
                        problems.append("status=partial but limits is empty")
                elif res.get(name) in (None, "", [], {}):
                    problems.append("result.json missing contract field %s" % name)
        else:
            warns.append("contract.json not found; skipped contract-field check")
        for name in ("manuscript_renumbered.md", "refs_renumbered.md",
                     "citation_report.json", "renumber_map.csv"):
            p = os.path.join(a.out, name)
            if not os.path.exists(p):
                problems.append("artifact %s missing" % name)
            elif os.path.getsize(p) < 8:
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
    p = sub.add_parser("extract"); p.add_argument("--path", required=True); p.add_argument("--out", required=True); p.set_defaults(fn=cmd_extract)
    p = sub.add_parser("check"); p.add_argument("--out", default="/app/output"); p.add_argument("--contract-dir", default="work"); p.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
