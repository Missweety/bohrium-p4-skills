#!/usr/bin/env python3
"""kernel.py - evidence-first execution kernel shared by all Bohrium skills.

Subcommands (all stdlib only, no network):
  init     read /input/case.json (alias tolerant), emit work/contract.json + work/case.json
  index    walk material dir, extract text with locators, emit work/evidence.json
  build    render work/manuscript.md from a draft JSON (sections/figures/refs)
  verify   check a draft against the evidence index (numbers, units, citations)
  emit     merge draft fields + contract into result.json, write md artifacts, run selfcheck
  check    validate an existing output dir against its contract

Design rule: never fabricate. Missing data is reported as missing, never filled in.
"""
import argparse
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
NUM_RE = re.compile(r"(?<![A-Za-z0-9_.])(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s?[%‰])?")
CITE_RE = re.compile(r"(\[[0-9,\s\-–]+\]|\\cite\{[^}]+\}|\([A-Z][A-Za-z\-]+(?:\s(?:et al\.|and\s[A-Z][A-Za-z\-]+))?,?\s?(?:19|20)\d{2}[a-z]?\))")
UNREADABLE_PREFIX = "[unreadable:"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".svg"}
REF_HEADINGS = {"references", "reference", "bibliography", "works cited", "参考文献"}
CONTRACT_META_KEYS = {"fields", "required", "type", "description", "schema", "properties", "title"}
MANUSCRIPT_ALIASES = {"manuscript", "paper", "article", "draft", "document", "text", "content",
                      "manuscript_md", "full_text", "paper_text", "report", "essay",
                      "summary", "writeup", "output_text"}
MAP_ALIASES = {"source_map", "sources_map", "evidence_map", "fact_map", "facts"}
AUDIT_ALIASES = {"audit", "audit_report", "self_check"}
STATUSES = {"ok", "success", "partial", "blocked", "refused"}


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


def contract_field_names(contract):
    """Accept list form, {fields:[...]}, {required:[...]}, {properties:{...}} or dict-of-fields."""
    if isinstance(contract, list):
        return [str(x) for x in contract]
    if isinstance(contract, dict):
        for key in ("fields", "required"):
            if isinstance(contract.get(key), list):
                return [str(x) for x in contract[key]]
        if isinstance(contract.get("properties"), dict):
            return [str(x) for x in contract["properties"]]
        return [str(k) for k in contract if k not in CONTRACT_META_KEYS]
    return []


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
        return "%s xlsx unreadable: %s]" % (UNREADABLE_PREFIX, exc)


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
        return "%s pdf text layer unavailable: install pdftotext or pypdf; do not guess page content]" \
            % UNREADABLE_PREFIX


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
    if ext in IMAGE_EXT:
        return "[image asset: inspect visually; record size/content in evidence notes]"
    return "[unsupported type %s]" % ext


def is_readable_text(text):
    return not text.startswith(UNREADABLE_PREFIX) and not text.startswith("[unsupported type")


# ---------------------------------------------------------------- commands
def cmd_init(a):
    case_path = find_case_file(a.case)
    if not case_path:
        dump({"status": "blocked", "missing": "case.json not found"}, os.path.join(a.out, "contract.json"))
        print("blocked: case.json not found")
        return 1
    try:
        case = load_json(case_path)
    except (OSError, ValueError) as exc:
        dump({"status": "blocked", "missing": "case.json is not valid JSON: %s" % exc},
             os.path.join(a.out, "contract.json"))
        print("blocked: case.json is not valid JSON: %s" % exc)
        return 1
    if not isinstance(case, dict):
        dump({"status": "blocked", "missing": "case.json must be a JSON object"},
             os.path.join(a.out, "contract.json"))
        print("blocked: case.json must be a JSON object")
        return 1
    norm = {k: pick(case, k) for k in ALIASES}
    contract = norm.get("output_contract") or {}
    field_names = contract_field_names(contract)
    base_dir = os.path.dirname(os.path.abspath(case_path))
    task_md = os.path.join(base_dir, "task.md")
    result = {
        "case_path": os.path.abspath(case_path),
        "case_dir": base_dir,
        "case_id": norm.get("case_id") or os.path.splitext(os.path.basename(case_path))[0],
        "task": norm.get("task"),
        "task_md_path": task_md if os.path.exists(task_md) else None,
        "task_md_text": open(task_md, encoding="utf-8", errors="replace").read()
        if os.path.exists(task_md) else None,
        "language": norm.get("language"),
        "genre": norm.get("genre"),
        "audience": norm.get("audience"),
        "materials": norm.get("materials"),
        "raw_keys": sorted(case.keys()),
        "contract_source": "case.output_contract" if norm.get("output_contract") else "skill_default",
        "contract": contract,
        "contract_fields": field_names,
    }
    dump(result, os.path.join(a.out, "contract.json"))
    dump(case, os.path.join(a.out, "case.raw.json"))
    if not field_names:
        print("warn: case.json has no output_contract fields; using skill default contract")
    print("case_id=%s fields=%d keys=%s"
          % (result["case_id"], len(field_names), ",".join(result["raw_keys"])))
    return 0


def _candidate_materials(contract):
    """Collect explicit material paths, inline materials and conventional dirs."""
    case_dir = contract.get("case_dir") or os.getcwd()
    raw = contract.get("materials") or []
    paths, inline = [], []
    if isinstance(raw, str):
        raw = [raw]
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            p = item if os.path.isabs(item) else os.path.join(case_dir, item)
            paths.append(p)
        elif isinstance(item, dict):
            p = item.get("path") or item.get("file") or item.get("name")
            content = item.get("content") or item.get("text")
            if content:
                inline.append((str(p or "inline_material.txt"), str(content)))
            elif p:
                paths.append(p if os.path.isabs(str(p)) else os.path.join(case_dir, str(p)))
    if not paths:
        for name in ("materials", "input", "data", "resources"):
            cand = os.path.join(case_dir, name)
            if os.path.isdir(cand):
                paths.append(cand)
    if not paths:
        paths.append(case_dir)
    return paths, inline


def cmd_index(a):
    contract = load_json(os.path.join(a.out, "contract.json")) \
        if os.path.exists(os.path.join(a.out, "contract.json")) else {}
    if contract.get("status") == "blocked":
        dump({"status": "blocked", "missing": contract.get("missing")},
             os.path.join(a.out, "evidence.json"))
        print("blocked: %s" % contract.get("missing"))
        return 1
    roots = [p for p in (a.materials or []) if os.path.exists(p)]
    inline = []
    if not roots:
        roots, inline = _candidate_materials(contract)
        roots = [p for p in roots if os.path.exists(p)]
    contract_materials = contract.get("materials") or []
    if isinstance(contract_materials, list):
        for item in contract_materials:
            if isinstance(item, dict) and (item.get("content") or item.get("text")):
                inline.append((str(item.get("path") or item.get("name") or "inline_material.txt"),
                               str(item.get("content") or item.get("text"))))
    if not roots and not inline:
        dump({"status": "blocked", "missing": "no material files found"},
             os.path.join(a.out, "evidence.json"))
        print("blocked: no material files found")
        return 1
    os.makedirs(a.out, exist_ok=True)
    inline_dir = os.path.join(a.out, "inline")
    for name, body in inline:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(name)) or "inline_material.txt"
        p = os.path.join(inline_dir, safe)
        os.makedirs(inline_dir, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        roots.append(p)

    items, corpus, seen = [], [], set()
    explicit = bool(a.materials)
    reserved = {"case.json", "task.md", "draft.json", "result.json", "manuscript.md",
                "contract.json", "evidence.json", "audit.json", "claims.json",
                "source_map.json", "todo.md", "case.raw.json"}
    for root in roots:
        root = os.path.abspath(root)
        walk = [(os.path.dirname(root), [], [os.path.basename(root)])] if os.path.isfile(root) \
            else os.walk(root)
        for dirpath, dirnames, names in walk:
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "work", "output")]
            for n in sorted(names):
                if os.path.isfile(root):
                    p = root
                else:
                    p = os.path.join(dirpath, n)
                if not os.path.isfile(p) or n.startswith("."):
                    continue
                if not explicit and not os.path.isfile(root) and n in reserved:
                    continue
                real = os.path.realpath(p)
                if real in seen:
                    continue
                seen.add(real)
                text = extract(p)
                items.append({
                    "path": p,
                    "bytes": os.path.getsize(p),
                    "chars": len(text),
                    "readable": is_readable_text(text),
                    "sha1": __import__("hashlib").sha1(open(p, "rb").read()).hexdigest(),
                })
                corpus.append("===== FILE: %s =====\n%s" % (p, text))
    dump({"files": items, "total_chars": sum(i["chars"] for i in items),
          "unreadable": [i["path"] for i in items if not i["readable"]]},
         os.path.join(a.out, "evidence.json"))
    with open(os.path.join(a.out, "corpus.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(corpus))
    for i in items:
        print("%-8s %8d  %s" % ("ok" if i["readable"] else "UNREAD", i["chars"], i["path"]))
    return 0


def _render_reference(entry, index):
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        return str(entry)
    if "raw" in entry and entry["raw"]:
        return str(entry["raw"])
    parts = []
    authors = entry.get("authors")
    if isinstance(authors, list):
        authors = ", ".join(str(x) for x in authors)
    if authors:
        parts.append(str(authors).rstrip(".") + ".")
    if entry.get("title"):
        parts.append(str(entry["title"]).rstrip(".") + ".")
    tail = []
    if entry.get("journal"):
        tail.append(str(entry["journal"]))
    if entry.get("year"):
        tail.append(str(entry["year"]))
    if tail:
        parts.append(", ".join(tail) + ".")
    if entry.get("doi"):
        parts.append("doi:%s" % entry["doi"])
    body = " ".join(parts).strip()
    return "[%d] %s" % (index, body) if entry.get("numbered", True) else body


def render_manuscript(plan):
    """Render an editable manuscript from a draft JSON (sections/figures/tables/refs)."""
    lines = []
    if plan.get("title"):
        lines += ["# %s" % plan["title"], ""]
    figures = plan.get("figures") or []
    tables = plan.get("tables") or []
    placed_figs, placed_tabs = set(), set()
    for section in plan.get("sections") or []:
        heading = section.get("heading") or section.get("name") or ""
        level = int(section.get("level") or 2)
        if heading:
            lines += ["%s %s" % ("#" * max(1, min(6, level)), heading), ""]
        for para in section.get("paragraphs") or []:
            text = para if isinstance(para, str) else str(para.get("text") or "")
            if not text.strip():
                continue
            lines += [text.strip(), ""]
        for i, fig in enumerate(figures):
            if i in placed_figs:
                continue
            label = str(fig.get("label") or "Figure %d" % (i + 1))
            if str(fig.get("section") or "").lower() == heading.lower():
                lines += ["%s. %s" % (label, str(fig.get("caption") or "").strip()), ""]
                placed_figs.add(i)
        for i, tab in enumerate(tables):
            if i in placed_tabs:
                continue
            label = str(tab.get("label") or "Table %d" % (i + 1))
            if str(tab.get("section") or "").lower() == heading.lower():
                lines += ["%s. %s" % (label, str(tab.get("caption") or "").strip()), ""]
                placed_tabs.add(i)
    for tag, remaining, kind in (("Figures", figures, "fig"), ("Tables", tables, "tab")):
        pending = [x for i, x in enumerate(remaining)
                   if i not in (placed_figs if kind == "fig" else placed_tabs)]
        if pending:
            lines += ["## %s" % tag, ""]
            for i, obj in enumerate(remaining):
                if i in (placed_figs if kind == "fig" else placed_tabs):
                    continue
                label = str(obj.get("label") or ("Figure %d" if kind == "fig" else "Table %d")
                            % (i + 1))
                lines += ["%s. %s" % (label, str(obj.get("caption") or "").strip()), ""]
    headings = [str(s.get("heading") or s.get("name") or "").lower()
                for s in plan.get("sections") or []]
    refs = plan.get("references") or []
    if refs and not any(h in REF_HEADINGS for h in headings):
        lines += ["## References", ""]
        for i, r in enumerate(refs, start=1):
            lines += [_render_reference(r, i), ""]
    decl = plan.get("declarations") or {}
    titles = {"data_availability": "Data availability", "funding": "Funding",
              "conflict_of_interest": "Conflict of interest", "ethics": "Ethics statement"}
    for key, title in titles.items():
        val = str(decl.get(key) or "").strip()
        if val and title.lower() not in headings:
            lines += ["## %s" % title, "", val, ""]
    return "\n".join(lines).rstrip() + "\n"


def cmd_build(a):
    plan = load_json(a.draft)
    text = render_manuscript(plan)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "manuscript.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    source_map = plan.get("source_map") or []
    dump({"source_map": source_map, "entries": len(source_map)},
         os.path.join(a.out, "source_map.json"))
    print("rendered manuscript.md chars=%d sections=%d source_map=%d"
          % (len(text), len(plan.get("sections") or []), len(source_map)))
    return 0


def _numbers(text):
    out = []
    for m in NUM_RE.finditer(text):
        tok = m.group(0).strip()
        if len(tok) < 2 and not tok.isdigit():
            continue
        out.append(tok)
    return out


def _num_value(token):
    t = str(token).strip().replace(",", "").replace("，", "")
    t = re.sub(r"\s?[%‰]$", "", t)
    t = re.sub(r"^[^\d.+-]+|[^\d.]+$", "", t)
    try:
        return float(t)
    except (TypeError, ValueError):
        return None


def _number_values(text):
    vals = set()
    for tok in _numbers(text):
        v = _num_value(tok)
        if v is not None:
            vals.add(round(v, 10))
    return vals


def _citation_tokens(text):
    tokens = []
    for m in CITE_RE.finditer(text):
        tok = m.group(1).strip()
        if tok not in tokens:
            tokens.append(tok)
    return tokens


STRUCT_LABEL_RE = re.compile(r"(?i)\b(?:figure|fig\.?|table)\s*\d+[A-Za-z]?|[图表]\s*\d+[A-Za-z]?")
HEADING_NUM_RE = re.compile(r"(?m)^(\s*(?:#{1,6}\s*)?)"
                            r"(?:\d+(?:\.\d+)*[\.、]?|[一二三四五六七八九十百]+[、.]|第[一二三四五六七八九十百]+[章节])\s*")


def _audit_text(text):
    """Drop citations, heading numbers, caption labels and reference entries.

    Those numbers are structural, not factual claims, so they must not be
    reported as unsupported values.
    """
    text = CITE_RE.sub(" ", text)
    kept, in_refs = [], False
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            in_refs = m.group(2).strip().lower() in REF_HEADINGS
            line = HEADING_NUM_RE.sub(r"\1", line)
        if in_refs:
            continue
        kept.append(STRUCT_LABEL_RE.sub(" ", line))
    return "\n".join(kept)


def _reference_registry(corpus):
    numbers = {int(n) for n in re.findall(r"(?m)^\s*\[(\d+)\]", corpus)}
    bib_keys = set(re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", corpus))
    return numbers, bib_keys


def _check_citations(tokens, corpus, numbers, bib_keys):
    unresolved = []
    for tok in tokens:
        if tok.startswith("\\cite{"):
            key = tok[len("\\cite{"):-1].split(",")[0].strip()
            if key and key not in corpus and key not in bib_keys:
                unresolved.append({"citation": tok, "reason": "bib key not in sources"})
            continue
        if tok.startswith("["):
            idxs = []
            for part in tok.strip("[]").split(","):
                part = part.strip()
                if re.match(r"^\d+$", part):
                    idxs.append(int(part))
                elif re.match(r"^\d+\s*[-–]\s*\d+$", part):
                    a, b = re.split(r"[-–]", part)
                    idxs.extend(range(int(a), int(b) + 1))
            if not idxs:
                continue
            missing = [i for i in idxs
                       if (numbers and i not in numbers) or (not numbers and not bib_keys)]
            if not numbers and not bib_keys:
                unresolved.append({"citation": tok,
                                   "reason": "no reference list or bib file in sources"})
            elif missing:
                unresolved.append({"citation": tok, "reason": "index not in reference list %s"
                                   % missing})
            continue
        body = tok.strip("()")
        m = re.search(r"([A-Z][A-Za-z\-]+).*?((?:19|20)\d{2})", body)
        if m:
            author, year = m.group(1), m.group(2)
            if not re.search(re.escape(author) + r"[^\n]{0,200}" + year, corpus):
                unresolved.append({"citation": tok,
                                   "reason": "author/year pair not found in sources"})
    return unresolved


def cmd_verify(a):
    corpus = open(os.path.join(a.evidence_dir, "corpus.txt"), encoding="utf-8").read()
    ev = load_json(os.path.join(a.evidence_dir, "evidence.json"))
    draft = open(a.text, encoding="utf-8").read()
    corpus_values = _number_values(corpus)
    numbers = _numbers(_audit_text(draft))
    unsupported = []
    for tok in dict.fromkeys(numbers):
        v = _num_value(tok)
        if v is None:
            continue
        if round(v, 10) not in corpus_values:
            unsupported.append(tok)
    cites = _citation_tokens(draft)
    registry, bib_keys = _reference_registry(corpus)
    unresolved = _check_citations(cites, corpus, registry, bib_keys)
    report = {
        "draft": os.path.abspath(a.text),
        "numbers_total": len(numbers),
        "numbers_unique": len(set(numbers)),
        "unsupported_numbers": unsupported[:200],
        "citations_unique": len(cites),
        "citations_not_in_sources": [c["citation"] for c in unresolved][:200],
        "citations_unresolved": unresolved[:200],
        "unreadable_sources": ev.get("unreadable", []),
        "verdict": "pass" if not unsupported and not unresolved else "review",
    }
    dump(report, os.path.join(a.out, "claims.json"))
    print("verdict=%s unsupported_numbers=%d citations_not_in_sources=%d"
          % (report["verdict"], len(unsupported), len(unresolved)))
    for n in unsupported[:20]:
        print("  ? number not in sources:", n)
    for c in unresolved[:10]:
        print("  ? citation not in sources:", c["citation"], "-", c["reason"])
    return 0


def _artifact_text(draft, work_dir):
    artifacts = draft.get("artifacts") if isinstance(draft.get("artifacts"), dict) else {}
    if isinstance(artifacts.get("manuscript.md"), str):
        return artifacts["manuscript.md"], artifacts
    path = os.path.join(work_dir, "manuscript.md")
    if os.path.exists(path):
        return open(path, encoding="utf-8", errors="replace").read(), artifacts
    if draft.get("sections"):
        return render_manuscript(draft), artifacts
    return None, artifacts


def cmd_emit(a):
    contract_path = os.path.join(a.contract_dir, "contract.json") \
        if os.path.isdir(a.contract_dir) else a.contract_dir
    contract = load_json(contract_path) if os.path.exists(contract_path) else {}
    try:
        draft = load_json(a.draft)
    except (OSError, ValueError) as exc:
        names = contract_field_names(contract.get("contract", contract))
        result = {"case_id": contract.get("case_id"), "status": "blocked",
                  "limits": "draft.json is not readable: %s" % exc,
                  "uncertainty": [], "conflicts": [], "changes": [], "sources": [],
                  "source_map": [], "self_check": {"audit_verdict": "not_run",
                                                   "error": str(exc)}}
        for name in names:
            result.setdefault(name, None)
        os.makedirs(a.out, exist_ok=True)
        dump(result, os.path.join(a.out, "result.json"))
        print("blocked: draft.json is not readable: %s" % exc)
        return 1
    names = contract_field_names(contract.get("contract", contract))

    text, artifacts = _artifact_text(draft, a.work_dir)
    result = {"case_id": draft.get("case_id") or contract.get("case_id"),
              "status": draft.get("status", "partial")}
    for key in ("uncertainty", "conflicts", "changes", "sources", "limits", "title",
                "references", "figures", "tables"):
        if key in draft:
            result[key] = draft[key]
    for key, value in (draft.get("fields") or {}).items():
        if value is not None:
            result[key] = value
    for key, value in draft.items():
        if key in ("fields", "artifacts", "sections", "status", "case_id"):
            continue
        if value is not None:
            result[key] = value
    if not result.get("source_map"):
        sm = os.path.join(a.work_dir, "source_map.json")
        if os.path.exists(sm):
            result["source_map"] = load_json(sm).get("source_map", [])
    audit_path = os.path.join(a.work_dir, "audit.json")
    audit = load_json(audit_path) if os.path.exists(audit_path) else None
    if audit:
        result["audit"] = audit
        result["self_check"] = {
            "audit_verdict": audit.get("verdict"),
            "problems": audit.get("problems", []),
            "warnings": audit.get("warnings", [])[:20],
            "numbers_unbound": audit.get("numbers_unbound", []),
            "citations_unresolved": audit.get("citations_unresolved", []),
            "sections_missing": audit.get("sections_missing", []),
            "sections_out_of_order": audit.get("sections_out_of_order", []),
            "conflicts": audit.get("conflicts", []),
            "placeholders_unregistered": audit.get("placeholders_unregistered", []),
            "declarations_missing": audit.get("declarations_missing", []),
            "figure_problems": audit.get("figure_problems", []),
        }
        if audit.get("verdict") == "fail":
            result["status"] = "partial"
            result["limits"] = (str(result.get("limits") or "").strip() +
                                " | audit failed: " + "; ".join(audit.get("problems", [])[:3])
                                ).strip(" |")
    else:
        result["self_check"] = {"audit_verdict": "not_run"}
    if not result.get("sources"):
        ev_path = os.path.join(a.work_dir, "evidence.json")
        if os.path.exists(ev_path):
            result["sources"] = [i["path"] for i in load_json(ev_path).get("files", [])
                                 if i.get("readable")]
    result.setdefault("uncertainty", [])
    result.setdefault("conflicts", [])
    result.setdefault("changes", [])
    result.setdefault("source_map", [])
    result.setdefault("sources", [])
    if result.get("status") in ("partial", "blocked") and not str(result.get("limits") or "").strip():
        result["limits"] = ("未完成全部要求或存在未核实项；详见 self_check 与 uncertainty。"
                            if result["status"] == "partial" else "材料不足，未生成所需产物。")

    # contract fields: explicit values, then manuscript/map/audit aliases, then null
    for name in names:
        if result.get(name) is not None:
            continue
        low = name.lower()
        if low in MANUSCRIPT_ALIASES and text:
            result[name] = text
        elif low in MAP_ALIASES:
            result[name] = result.get("source_map") or []
        elif low in AUDIT_ALIASES and audit:
            result[name] = audit
        else:
            result[name] = None
    missing = [k for k in names if result.get(k) is None]
    if missing and result.get("status") in ("ok", "success"):
        result["status"] = "partial"
        result["limits"] = (str(result.get("limits") or "").strip() +
                            " | contract fields not producible: " + ", ".join(missing)).strip(" |")
    artifact_name = "manuscript.md"
    artifacts = dict(artifacts or {})
    if text:
        artifacts[artifact_name] = text
    result.setdefault("artifact_path", artifact_name)
    result.setdefault("artifact_format", "md")

    os.makedirs(a.out, exist_ok=True)
    dump(result, os.path.join(a.out, "result.json"))
    for name, body in artifacts.items():
        p = os.path.join(a.out, name)
        os.makedirs(os.path.dirname(p) or a.out, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
    for name in ("source_map.json", "source_map.csv", "audit.json", "claims.json", "todo.md"):
        src = os.path.join(a.work_dir, name)
        if os.path.exists(src):
            dst = os.path.join(a.out, name)
            with open(src, "rb") as fh:
                data = fh.read()
            with open(dst, "wb") as fh:
                fh.write(data)
    print("result.json written; contract_fields=%d missing_contract_fields=%s"
          % (len(names), missing or "none"))
    return 0 if not missing else 1


def cmd_check(a):
    problems, warns = [], []
    rp = os.path.join(a.out, "result.json")
    if not os.path.exists(rp):
        print("FAIL\n - result.json missing")
        return 1
    res = load_json(rp)
    for k in ("case_id", "status"):
        if not res.get(k):
            problems.append("result.json missing %s" % k)
    if res.get("status") not in STATUSES:
        problems.append("status must be one of %s" % "/".join(sorted(STATUSES)))
    if res.get("status") in ("partial", "blocked") and not str(res.get("limits") or "").strip():
        problems.append("status=%s but limits is empty" % res["status"])
    for key in ("source_map", "uncertainty"):
        if not isinstance(res.get(key), list):
            problems.append("%s must be a list" % key)
    for i, entry in enumerate(res.get("source_map") or []):
        if not isinstance(entry, dict):
            problems.append("source_map[%d] is not an object" % i)
            continue
        for k in ("claim", "value", "source_path", "locator"):
            if not str(entry.get(k, "")).strip():
                problems.append("source_map[%d] missing %s" % (i, k))
        sp = str(entry.get("source_path") or "")
        if sp and os.path.isabs(sp) and not os.path.exists(sp):
            warns.append("source_map[%d] source_path not found now: %s" % (i, sp))
    artifact = str(res.get("artifact_path") or "")
    ap = os.path.join(a.out, artifact) if artifact else ""
    if not artifact:
        problems.append("artifact_path empty")
    elif not os.path.exists(ap):
        problems.append("artifact missing: %s" % artifact)
    elif os.path.getsize(ap) < 32:
        problems.append("artifact is empty/truncated: %s" % artifact)
    if not os.path.exists(os.path.join(a.out, "manuscript.md")):
        problems.append("manuscript.md missing (the editable deliverable)")
    audit_path = os.path.join(a.out, "audit.json")
    if os.path.exists(audit_path):
        verdict = load_json(audit_path).get("verdict")
        if verdict == "fail" and res.get("status") in ("ok", "success"):
            problems.append("audit verdict=fail but status=%s" % res.get("status"))
    else:
        warns.append("audit.json not found in output; audit evidence is not re-checkable")
    if not isinstance(res.get("self_check"), dict) or not res["self_check"].get("audit_verdict"):
        problems.append("self_check.audit_verdict missing")
    cp = os.path.join(a.contract_dir, "contract.json") if a.contract_dir else ""
    if cp and os.path.exists(cp):
        names = contract_field_names(load_json(cp).get("contract", {}))
        for name in names:
            if name not in res or res.get(name) is None:
                problems.append("result.json missing contract field %s" % name)
            elif name != "limits" and isinstance(res.get(name), str) and not res[name].strip():
                problems.append("result.json empty contract field %s" % name)
    elif a.contract_dir:
        warns.append("contract.json not found; skipped contract-field check")
    print("PASS" if not problems else "FAIL")
    for p in problems:
        print(" -", p)
    for w in warns:
        print(" ~", w)
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("--case"); p.add_argument("--out", default="work")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("index"); p.add_argument("--materials", nargs="*")
    p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("build"); p.add_argument("--draft", required=True)
    p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_build)
    p = sub.add_parser("verify"); p.add_argument("--text", required=True)
    p.add_argument("--evidence-dir", default="work"); p.add_argument("--out", default="work")
    p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("emit"); p.add_argument("--draft", required=True)
    p.add_argument("--contract-dir", default="work"); p.add_argument("--work-dir", default="work")
    p.add_argument("--audit", default=""); p.add_argument("--source-map", default="")
    p.add_argument("--out", default="/app/output"); p.set_defaults(fn=cmd_emit)
    p = sub.add_parser("check"); p.add_argument("--out", default="/app/output")
    p.add_argument("--contract-dir", default="work"); p.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
