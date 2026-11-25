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


def decode_text(path):
    """Decode a text file; returns (text, encoding).

    Chinese manuscripts are often GBK/GB18030 while the platform only promises nothing:
    reading them as utf-8 with errors='replace' silently turned every character into U+FFFD,
    so downstream checks reported "0 numbers, nothing to verify" on a perfectly good draft.
    """
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8/replace"


def extract(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return read_docx(path)
    if ext in {".xlsx", ".xlsm"}:
        return read_xlsx(path)
    if ext == ".pdf":
        return read_pdf(path)
    if ext in TEXT_EXT:
        return decode_text(path)[0]
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
                ext = os.path.splitext(p)[1].lower()
                encoding = "binary"
                if ext in TEXT_EXT:
                    text, encoding = decode_text(p)
                else:
                    text = extract(p)
                unread = text.startswith(("[pdf text layer unavailable", "[xlsx unreadable",
                                          "[unsupported type", "[image asset"))
                items.append({
                    "path": p,
                    "bytes": os.path.getsize(p),
                    "chars": len(text),
                    "readable": not unread,
                    "encoding": encoding,
                    "sha1": __import__("hashlib").sha1(open(p, "rb").read()).hexdigest(),
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
        print("MISSING  %s (material path does not exist; not silently skipped)" % p)
    for i in items:
        print("%-8s %8d  %-10s %s" % ("ok" if i["readable"] else "UNREAD", i["chars"], i["encoding"], i["path"]))
    return 0


def _num_forms(tok):
    """Plausible spellings of one numeric token so 3,000 / 3000 / 3 000 compare equal."""
    base = tok.strip().replace(" ", "").replace(",", "")
    forms = {tok.strip(), base}
    m = re.match(r"^([-+]?\d+(?:\.\d+)?)\s?([%‰])?$", base)
    if m:
        num, unit = m.group(1), m.group(2) or ""
        if num.endswith(".0"):
            num = num[:-2]
        forms.add(num + unit)
        forms.add(num)
        if unit:
            forms.add(num + " " + unit)
    return forms


def _corpus_forms(corpus):
    forms = set()
    for m in NUM_RE.finditer(corpus):
        forms |= _num_forms(m.group(0))
    return forms


def _expand_cite(tok):
    """[3,5] / [3-5] -> 3,5 ; ranges expanded so each number is checked on its own."""
    out = []
    for p in re.split(r"[,\s]+", tok.strip("[]")):
        if not p:
            continue
        m = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", p)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            out += list(range(min(lo, hi), max(lo, hi) + 1))
        elif p.isdigit():
            out.append(int(p))
    return out


def cmd_verify(a):
    corpus_path = os.path.join(a.evidence_dir, "corpus.txt")
    ev_path = os.path.join(a.evidence_dir, "evidence.json")
    absent = [p for p in (corpus_path, ev_path) if not os.path.exists(p)]
    if absent:
        dump({"verdict": "blocked", "error": "evidence index missing; run kernel.py index first",
              "missing": absent}, os.path.join(a.out, "claims.json"))
        print("blocked: evidence index missing (run kernel.py index first)")
        return 1
    corpus = open(corpus_path, encoding="utf-8").read()
    ev = load_json(ev_path)
    text, enc = decode_text(a.text)
    # Headings ("## 3.2") and citation markers ("[37]", "\cite{x}") are structure, not
    # numeric claims: scanning them reported every section number as unsupported.
    body = "\n".join(l for l in text.splitlines() if not re.match(r"^\s*#{1,6}\s", l))
    numbers = []
    for m in NUM_RE.finditer(CITE_RE.sub(" ", body)):
        tok = m.group(0).strip()
        if len(tok) < 2 and not tok.isdigit():
            continue
        numbers.append(tok)
    corpus_forms = _corpus_forms(corpus)
    unsupported = [n for n in dict.fromkeys(numbers) if not (_num_forms(n) & corpus_forms)]
    cites = []
    for m in CITE_RE.finditer(body):
        tok = m.group(0)
        if re.match(r"^\[[0-9,\s\-–]+\]$", tok):
            cites += ["[%d]" % n for n in _expand_cite(tok)]
        elif tok.startswith("\\cite"):
            cites += [k for k in re.split(r"[,\s]+", tok[6:-1].strip()) if k]
        else:
            cites.append(tok)
    missing_cites = [c for c in dict.fromkeys(cites) if c not in corpus]
    report = {
        "draft": os.path.abspath(a.text),
        "draft_encoding": enc,
        "numbers_total": len(numbers),
        "numbers_unique": len(set(numbers)),
        "unsupported_numbers": unsupported[:200],
        "citations_unique": len(set(cites)),
        "citations_not_in_sources": missing_cites[:200],
        "unreadable_sources": ev.get("unreadable", []),
        "missing_materials": ev.get("missing_materials", []),
        "verdict": "pass" if not unsupported and not missing_cites else "review",
    }
    dump(report, os.path.join(a.out, "claims.json"))
    print("verdict=%s unsupported_numbers=%d citations_not_in_sources=%d"
          % (report["verdict"], len(unsupported), len(missing_cites)))
    for n in unsupported[:20]:
        print("  ? number not in sources:", n)
    for c in missing_cites[:20]:
        print("  ? citation not in sources:", c)
    return 0


def cmd_emit(a):
    try:
        contract = load_json(os.path.join(a.contract_dir, "contract.json")) if os.path.isdir(a.contract_dir) \
            else load_json(a.contract_dir)
    except (OSError, json.JSONDecodeError) as exc:
        contract = {}
        print("warn: contract unreadable (%s); emitting with draft fields only" % exc)
    try:
        draft = load_json(a.draft)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        print("FAIL: draft unreadable: %s" % exc)
        return 2
    if not isinstance(contract, dict):
        contract = {}
    if not isinstance(draft, dict):
        print("FAIL: draft top level is %s, expected object" % type(draft).__name__)
        return 2
    fields = normalize_contract(contract.get("contract")) if contract.get("contract") is not None else {}
    draft_fields = draft.get("fields") if isinstance(draft.get("fields"), dict) else {}
    result = {"case_id": contract.get("case_id") or draft.get("case_id"),
              "status": draft.get("status", "partial")}
    # Contract fields must not overwrite the identity keys: a contract that lists case_id
    # used to blank result.json.case_id to None and fail the gate.
    for name in fields:
        if name in ("case_id", "status"):
            continue
        val = draft_fields.get(name, draft.get(name))
        if val is None and name in ("uncertainty", "sources", "changes", "limits"):
            val = draft.get(name, [] if name != "limits" else "")
        result[name] = val
    if not fields:
        # No contract fields (case.json without output_contract): keep every draft field
        # instead of silently dropping artifact_path/source_map.
        for name, val in draft_fields.items():
            result.setdefault(name, val)
    result.setdefault("uncertainty", draft.get("uncertainty", []))
    result.setdefault("sources", draft.get("sources", []))
    result.setdefault("changes", draft.get("changes", []))
    if _blank(result.get("limits")):
        result["limits"] = draft.get("limits") or ""
    os.makedirs(a.out, exist_ok=True)
    dump(result, os.path.join(a.out, "result.json"))
    for name, body in (draft.get("artifacts") or {}).items():
        p = os.path.join(a.out, name)
        os.makedirs(os.path.dirname(p) or a.out, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
    missing = [k for k in fields if result.get(k) is None]
    print("result.json written; missing_contract_fields=%s" % (missing or "none"))
    return 0


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
    """Gate the deliverable: contract fields, evidence structures, tables, honest status."""
    problems, notes = [], []
    rp = os.path.join(a.out, "result.json")
    contract_path = a.contract or getattr(a, "contract_dir", None) or "work/contract.json"
    if contract_path and os.path.isdir(contract_path):
        contract_path = os.path.join(contract_path, "contract.json")
    contract = {}
    if contract_path and os.path.exists(contract_path):
        try:
            contract = load_json(contract_path)
        except (OSError, json.JSONDecodeError) as exc:
            notes.append("contract unreadable (%s); gate falls back to structural checks" % exc)
    elif contract_path:
        notes.append("contract not found at %s; gate falls back to structural checks" % contract_path)
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
    fields = normalize_contract(contract.get("contract")) if contract.get("contract") is not None else {}
    # These fields legitimately have nothing to report on a clean run; demanding non-empty
    # content pushed writers to invent change logs and uncertainties that never happened.
    allowed_empty = {"changes", "uncertainty", "limits", "notes", "self_check", "sources"}
    for name in fields:
        if _blank(res.get(name)) and name not in allowed_empty:
            problems.append("contract field empty/missing: %s" % name)
    if isinstance(res.get("fields"), dict) and any(name in res["fields"] for name in fields):
        problems.append("contract fields nested under result['fields']; flatten them to top level")
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
    for name in ("intro", "claim_map", "gap_table", "contribution_map", "arrow"):
        val = res.get(name)
        if val and not os.path.exists(os.path.join(a.out, str(val))):
            problems.append("%s does not exist under output: %s" % (name, val))
    if status in {"partial", "blocked"} and _blank(res.get("limits")):
        problems.append("status=%s requires non-empty limits" % status)
    if not problems:
        notes.append("status=%s gap_table=%s" % (status, res.get("gap_table")))
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
    p = sub.add_parser("index"); p.add_argument("--materials", nargs="+", required=True); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("verify"); p.add_argument("--text", required=True); p.add_argument("--evidence-dir", default="work"); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("emit"); p.add_argument("--draft", required=True); p.add_argument("--contract-dir", default="work"); p.add_argument("--out", default="/app/output"); p.set_defaults(fn=cmd_emit)
    p = sub.add_parser("check"); p.add_argument("--out", default="/app/output")
    p.add_argument("--contract", default=None)
    p.add_argument("--contract-dir", dest="contract_dir", default=None)
    p.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
