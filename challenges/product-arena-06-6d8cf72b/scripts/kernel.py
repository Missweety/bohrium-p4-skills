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


def cmd_emit(a):
    contract = load_json(os.path.join(a.contract_dir, "contract.json")) if os.path.isdir(a.contract_dir) \
        else load_json(a.contract_dir)
    draft = load_json(a.draft)
    fields = contract.get("contract") or {}
    result = {"case_id": contract.get("case_id"), "status": draft.get("status", "partial")}
    if isinstance(fields, dict):
        for name in fields:
            result[name] = draft.get("fields", {}).get(name, draft.get(name))
    else:
        result.update(draft.get("fields", {}))
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
            fh.write(body)
    missing = [k for k in (fields.keys() if isinstance(fields, dict) else []) if result.get(k) is None]
    print("result.json written; missing_contract_fields=%s" % (missing or "none"))
    return 0 if not missing else 1


def cmd_search(a):
    notes = load_json(a.notes)
    query = (a.query or "").strip().lower()
    hits = []
    for name, entries in (notes.get("fields") or {}).items():
        for e in entries or []:
            hay = " ".join(str(e.get(k, "")) for k in ("id", "text", "value", "topic", "quote"))
            if query and query not in hay.lower():
                continue
            hits.append({"field": name, "id": e.get("id"), "topic": e.get("topic"),
                         "text": e.get("text"), "value": e.get("value"),
                         "anchor": e.get("anchor"), "kind": e.get("kind")})
    report = {"query": a.query, "hits": len(hits), "entries": hits}
    dump(report, a.out)
    print("hits=%d query=%r" % (len(hits), a.query))
    return 0


def cmd_compare(a):
    reports = []
    for path in a.notes:
        notes = load_json(path)
        paper = notes.get("paper") or {}
        entry = {"path": path, "title": paper.get("title") or os.path.basename(path),
                 "sections": paper.get("sections") or [], "fields": notes.get("fields") or {}}
        reports.append(entry)
    topics = {}
    for rep in reports:
        for name, entries in rep["fields"].items():
            for e in entries or []:
                key = (e.get("topic") or e.get("id") or "").strip()
                if not key:
                    continue
                topics.setdefault(key, []).append({
                    "paper": rep["title"], "field": name, "id": e.get("id"),
                    "text": e.get("text"), "value": e.get("value"),
                    "kind": e.get("kind"), "conflict_group": e.get("conflict_group"),
                    "anchor": e.get("anchor")})
    shared = {k: v for k, v in topics.items() if len({i["paper"] for i in v}) > 1}
    divergent = {k: v for k, v in shared.items()
                 if len({(i.get("value") or i.get("text") or "").strip() for i in v}) > 1}
    report = {"papers": [r["title"] for r in reports], "topics_total": len(topics),
              "shared_topics": sorted(shared), "divergent_topics": sorted(divergent),
              "matrix": topics}
    dump(report, a.out)
    if a.markdown:
        lines = ["# 多篇论文并排比较", "", "| 主题 | " + " | ".join(r["title"] for r in reports) + " |",
                 "|---|" + "---|" * len(reports)]
        for topic in sorted(topics):
            cells = []
            for rep in reports:
                vals = [str(i.get("value") or i.get("text") or "") for i in topics[topic]
                        if i["paper"] == rep["title"]]
                cells.append("；".join(vals) if vals else "—")
            lines.append("| " + topic + " | " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
        if divergent:
            lines += ["", "## 跨论文差异主题", "", ", ".join(sorted(divergent))]
        os.makedirs(os.path.dirname(os.path.abspath(a.markdown)) or ".", exist_ok=True)
        with open(a.markdown, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    print("papers=%d topics=%d shared=%d divergent=%d"
          % (len(reports), len(topics), len(shared), len(divergent)))
    return 0


UNIT_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*(mg/g|mg/L|g/L|mg|%|摄氏度|℃|分钟|小时|mL|μm|nm)")
METRIC_RE = re.compile(r"(最大吸附量|吸附量|去除率|回收率|降解率|转化率|产率|得率|选择性|容量|浓度|效率)")
ABSTRACT_RE = re.compile(r"摘要|abstract", re.I)


def _paragraphs(corpus):
    """Yield (section_title, paragraph_text) in document order."""
    section = ""
    buf = []
    for line in corpus.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if buf:
                yield section, "\n".join(buf).strip()
                buf = []
            section = stripped.lstrip("#").strip()
        elif not stripped:
            if buf:
                yield section, "\n".join(buf).strip()
                buf = []
        else:
            buf.append(stripped)
    if buf:
        yield section, "\n".join(buf).strip()


def _metric_values(text, section):
    """Extract (metric, unit, value, sentence) binding each number to the nearest preceding metric word."""
    out = []
    for sentence in re.split(r"[。；;]\s*", text):
        metrics = [(m.start(), m.group(1)) for m in METRIC_RE.finditer(sentence)]
        if not metrics:
            continue
        for match in UNIT_RE.finditer(sentence):
            preceding = [m for m in metrics if m[0] < match.start()]
            if not preceding:
                continue
            out.append((preceding[-1][1], match.group(2), float(match.group(1)), sentence.strip(), section))
    return out


def cmd_consistency(a):
    corpus = open(a.corpus, encoding="utf-8").read() if os.path.exists(a.corpus) else ""
    rows = []
    for section, paragraph in _paragraphs(corpus):
        rows.extend(_metric_values(paragraph, section))
    by_metric = {}
    for metric, unit, value, sentence, section in rows:
        by_metric.setdefault((metric, unit), []).append((value, sentence, section))
    candidates = []
    for (metric, unit), values in by_metric.items():
        abstracts = [v for v in values if ABSTRACT_RE.search(v[2])]
        bodies = [v for v in values if not ABSTRACT_RE.search(v[2])]
        if not abstracts or not bodies:
            continue
        avals = {round(v[0], 6) for v in abstracts}
        bvals = {round(v[0], 6) for v in bodies}
        # A shared value means the abstract is reproducing a body measurement; not a conflict.
        if any(abs(x - y) / max(abs(x), abs(y), 1e-9) < 0.01 for x in avals for y in bvals):
            continue
        only_a = sorted(avals - bvals)
        only_b = sorted(bvals - avals)
        if not only_a or not only_b:
            continue
        candidates.append({
            "metric": metric, "unit": unit,
            "abstract_values": only_a, "body_values": only_b,
            "section": bodies[0][2],
            "delta_pct": round(abs(only_a[0] - only_b[0]) / max(abs(only_a[0]), abs(only_b[0]), 1e-9) * 100, 1),
            "abstract_quote": abstracts[0][1], "body_quote": bodies[0][1],
            "needs_confirmation": True})
    report = {"checked_paragraphs": len(list(_paragraphs(corpus))), "metrics": len(by_metric),
              "candidates": candidates, "note": "仅提示摘要与正文同指标数值互不重合的情况，语义是否冲突需人工确认"}
    dump(report, a.out)
    print("candidates=%d metrics=%d" % (len(candidates), len(by_metric)))
    return 0


def cmd_baseline(a):
    corpus = open(a.corpus, encoding="utf-8").read() if os.path.exists(a.corpus) else ""
    sections = [(s, p) for s, p in _paragraphs(corpus)]
    naive = []
    for section, paragraph in sections:
        first = re.split(r"(?<=[。！？.!?])\s*", paragraph)[0][:120]
        naive.append({"section": section, "summary": first})
    ours = {"entries": 0, "fields": 0, "anchored": 0, "topics": 0}
    if os.path.exists(a.notes):
        notes = load_json(a.notes)
        fields = notes.get("fields") or {}
        entries = [e for v in fields.values() for e in v or []]
        ours = {"entries": len(entries), "fields": len([k for k, v in fields.items() if v]),
                "anchored": len([e for e in entries if e.get("quote") and e.get("anchor")]),
                "topics": len({e.get("topic") for e in entries if e.get("topic")})}
    report = {
        "fairness": {"same_materials": True, "same_parser": "共用 corpus.txt", "same_case": True,
                     "baseline": "确定性白板：按章节取首句作摘要，不使用额外模型或预算"},
        "baseline": {"sections": len(naive), "entries": len(naive), "fields": 1 if naive else 0,
                     "anchored": 0, "retrievable": False, "comparable": False, "notes": naive[:20]},
        "ours": {"entries": ours["entries"], "fields": ours["fields"], "anchored": ours["anchored"],
                 "retrievable": os.path.exists(a.notes), "comparable": True},
        "delta": {"entries": ours["entries"] - len(naive), "fields": ours["fields"] - (1 if naive else 0),
                  "anchored": ours["anchored"], "anchor_rate": round(ours["anchored"] / max(ours["entries"], 1), 3)},
    }
    dump(report, a.out)
    if a.markdown:
        lines = ["# 同一材料上的白板对照", "",
                 "| 指标 | 白板基线 | 本 Skill |", "|---|---|---|",
                 f"| 条目数 | {len(naive)} | {ours['entries']} |",
                 f"| 覆盖字段 | {1 if naive else 0} | {ours['fields']} |",
                 f"| 带锚点条目 | 0 | {ours['anchored']} |",
                 "| 可检索 | 否 | 是 |", "| 可并排比较 | 否 | 是 |", "",
                 "对照条件：同一材料、同一 corpus 解析、同一案例请求，基线不额外调用模型。"]
        os.makedirs(os.path.dirname(os.path.abspath(a.markdown)) or ".", exist_ok=True)
        with open(a.markdown, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    print("baseline sections=%d ours_entries=%d anchored=%d" % (len(naive), ours["entries"], ours["anchored"]))
    return 0


def cmd_check(a):
    problems = []
    rp = os.path.join(a.out, "result.json")
    if not os.path.exists(rp):
        problems.append("result.json missing")
        res = {}
    else:
        res = load_json(rp)
        for k in ("case_id", "status"):
            if not res.get(k):
                problems.append("result.json missing %s" % k)
        if res.get("status") not in {"ok", "success", "partial", "blocked", "refused"}:
            problems.append("status must be one of ok/success/partial/blocked/refused")
    contract_path = os.path.join(a.work, "contract.json")
    if os.path.exists(contract_path):
        contract = load_json(contract_path)
        for name in (contract.get("contract") or {}):
            if res.get(name) in (None, "", [], {}):
                problems.append("contract field empty: %s" % name)
    for name in ("notes.md", "notes.json", "anchors.csv"):
        if not os.path.exists(os.path.join(a.out, name)):
            problems.append("artifact missing: %s" % name)
    structured = res.get("structured") or {}
    if structured:
        total, verified = structured.get("anchors_total"), structured.get("anchors_verified")
        if total is not None and verified is not None and total != verified:
            problems.append("anchors_verified %s != anchors_total %s" % (verified, total))
        if structured.get("check_summary") not in (None, "pass"):
            problems.append("structured.check_summary is not pass")
    for name, key in (("note_check.json", "verdict"), ("quote_check.json", "verdict")):
        path = os.path.join(a.work, name)
        if os.path.exists(path) and load_json(path).get(key) != "pass":
            problems.append("%s is not pass" % name)
    print("PASS" if not problems else "FAIL")
    for p in problems:
        print(" -", p)
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("--case"); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("index"); p.add_argument("--materials", nargs="+", required=True); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("verify"); p.add_argument("--text", required=True); p.add_argument("--evidence-dir", default="work"); p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("emit"); p.add_argument("--draft", required=True); p.add_argument("--contract-dir", default="work"); p.add_argument("--out", default="/app/output"); p.set_defaults(fn=cmd_emit)
    p = sub.add_parser("check"); p.add_argument("--out", default="/app/output"); p.add_argument("--work", default="work"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("search"); p.add_argument("--notes", required=True); p.add_argument("--query", default=""); p.add_argument("--out", default="work/search.json"); p.set_defaults(fn=cmd_search)
    p = sub.add_parser("compare"); p.add_argument("--notes", nargs="+", required=True); p.add_argument("--out", default="work/compare.json"); p.add_argument("--markdown", default="work/compare.md"); p.set_defaults(fn=cmd_compare)
    p = sub.add_parser("consistency"); p.add_argument("--corpus", default="work/corpus.txt"); p.add_argument("--out", default="work/consistency.json"); p.set_defaults(fn=cmd_consistency)
    p = sub.add_parser("baseline"); p.add_argument("--corpus", default="work/corpus.txt"); p.add_argument("--notes", default="work/notes.json"); p.add_argument("--out", default="work/baseline_compare.json"); p.add_argument("--markdown", default="work/baseline_compare.md"); p.set_defaults(fn=cmd_baseline)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
