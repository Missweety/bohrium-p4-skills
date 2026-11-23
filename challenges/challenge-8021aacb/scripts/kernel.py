#!/usr/bin/env python3
"""kernel.py - evidence-first execution kernel for the structure-edit skill.

Subcommands (stdlib only, no network):
  init     read case.json (alias tolerant), emit work/contract.json + work/case.raw.json
  index    extract readable text + locators from materials/inline case text -> work/evidence.json
  verify   check a narrative against the evidence corpus (numbers, citations)
  emit     merge draft + contract -> result.json AND always render the four required artifacts
  check    validate an output dir against contract, artifacts, arrays and status rules

Design rule: never abort without a written result. Missing or unreadable input is reported
as missing in result.json / limits, never silently skipped and never filled in.
"""
import argparse
import csv
import hashlib
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
ARTIFACTS = ("structure_plan.md", "diagnosis.csv", "edit_plan.csv", "outline.md")
CN_NUM = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}


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


def norm_num(tok):
    return str(tok).replace(" ", "").replace(",", "").replace("，", "")


def cn_num(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "n"
    return CN_NUM.get(n, "n")


def normalize_contract(raw):
    """Accept dict / list[str] / list[{name|field|field_name|key|id}] / nested contract."""
    if isinstance(raw, dict):
        for key in ("fields", "output_fields", "outputs", "contract"):
            if key in raw and isinstance(raw[key], (dict, list)) and raw[key] is not raw:
                inner = normalize_contract(raw[key])
                if inner:
                    return inner
        return raw
    if isinstance(raw, list):
        out = {}
        for item in raw:
            if isinstance(item, str):
                out[item] = None
            elif isinstance(item, dict):
                name = item.get("name") or item.get("field") or item.get("field_name") \
                    or item.get("key") or item.get("id")
                if name:
                    out[str(name)] = item.get("type") or item.get("description")
        return out
    return {}


def find_case_file(explicit=None):
    cands = [explicit] if explicit else []
    cands += ["/input/case.json", "case.json", "/app/input/case.json", "./input/case.json"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def case_texts(case):
    """Inline manuscript text carried directly by case.json (no external material file)."""
    out = []
    for key in ALIASES["source_text"]:
        val = case.get(key)
        if isinstance(val, str) and len(val.strip()) >= 80:
            out.append((key, val))
    for key in ("materials", "files", "attachments", "inputs", "documents"):
        for item in case.get(key) or []:
            if isinstance(item, dict):
                for v in item.values():
                    if isinstance(v, str) and len(v) >= 400:
                        out.append((key, v))
    return out


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
        if r.returncode == 0 and len(r.stdout.strip()) >= 200:
            return r.stdout.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        pass
    try:
        from pypdf import PdfReader  # type: ignore
        text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
        if len(text.strip()) >= 200:
            return text
        return "[pdf text layer unavailable or too short: %d chars; do not guess page content]" % len(text.strip())
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
        return "[image asset: inspect visually; record size/content in evidence notes]"
    return "[unsupported type %s]" % ext


def locate(snippet, corpus, source):
    idx = corpus.find(snippet[:80])
    if idx < 0:
        return None
    line = corpus.count("\n", 0, idx) + 1
    return {"source": source, "line": line, "offset": idx}


# ---------------------------------------------------------------- commands
def cmd_init(a):
    case_path = find_case_file(a.case)
    case = {}
    if case_path:
        try:
            case = load_json(case_path)
        except Exception as exc:  # noqa: BLE001
            print("warn: case.json unparsable (%s); continuing with empty case" % exc)
    else:
        print("warn: case.json not found; using skill defaults (case_id=case)")
    if not isinstance(case, dict):
        case = {"content": case}
    norm = {k: pick(case, k) for k in ALIASES}
    contract = normalize_contract(norm.get("output_contract"))
    result = {
        "case_path": os.path.abspath(case_path) if case_path else None,
        "case_id": norm.get("case_id") or "case",
        "task": norm.get("task"),
        "language": norm.get("language"),
        "genre": norm.get("genre"),
        "audience": norm.get("audience"),
        "raw_keys": sorted(case.keys()) if isinstance(case, dict) else [],
        "contract_source": "case.output_contract" if norm.get("output_contract") else "skill_default",
        "contract": contract,
        "inline_text_keys": [k for k, _ in case_texts(case)],
    }
    dump(result, os.path.join(a.out, "contract.json"))
    dump(case, os.path.join(a.out, "case.raw.json"))
    if not contract:
        print("warn: case.json has no usable output_contract; skill default contract applies")
    print("case_id=%s contract_fields=%s keys=%s"
          % (result["case_id"], ",".join(contract) or "default", ",".join(result["raw_keys"][:12])))
    return 0


def _material_files(root):
    """Yield real files under a file/dir root without following symlinks or dotfiles."""
    if os.path.isfile(root):
        yield root
        return
    for dirpath, dirnames, names in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for n in sorted(names):
            if n.startswith("."):
                continue
            p = os.path.join(dirpath, n)
            if os.path.isfile(p) and not os.path.islink(p):
                yield p


def cmd_index(a):
    roots = list(a.materials or [])
    missing = [p for p in roots if not os.path.exists(p)]
    roots = [p for p in roots if os.path.exists(p)]
    items, corpus = [], []
    seen = set()
    for root in roots:
        for p in _material_files(root):
            if p in seen:
                continue
            seen.add(p)
            try:
                text = extract(p)
            except Exception as exc:  # noqa: BLE001
                text = "[unreadable: %s]" % exc
            items.append({
                "path": p,
                "bytes": os.path.getsize(p),
                "chars": len(text),
                "readable": bool(text.strip()) and not text.lstrip().startswith("["),
                "sha1": hashlib.sha1(open(p, "rb").read()).hexdigest(),
            })
            corpus.append("===== FILE: %s =====\n%s" % (p, text))
    if getattr(a, "case", None):
        try:
            case = load_json(a.case)
            texts = case_texts(case if isinstance(case, dict) else {})
        except Exception:  # noqa: BLE001
            texts = []
        for key, body in texts:
            label = "case:%s" % key
            if label in seen:
                continue
            seen.add(label)
            items.append({"path": label, "bytes": len(body.encode("utf-8")), "chars": len(body),
                          "readable": True, "sha1": hashlib.sha1(body.encode("utf-8")).hexdigest()})
            corpus.append("===== FILE: %s =====\n%s" % (label, body))
    report = {"files": items, "total_chars": sum(i["chars"] for i in items),
              "unreadable": [i["path"] for i in items if not i["readable"]],
              "missing_paths": missing}
    dump(report, os.path.join(a.out, "evidence.json"))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "corpus.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(corpus))
    for i in items:
        print("%-8s %8d  %s" % ("ok" if i["readable"] else "UNREAD", i["chars"], i["path"]))
    if missing:
        print("warn: material path(s) not found: %s" % ", ".join(missing))
    if not items:
        print("warn: no material file and no inline text; corpus is empty")
    return 0


def cmd_verify(a):
    corpus = open(os.path.join(a.evidence_dir, "corpus.txt"), encoding="utf-8").read()
    ev = load_json(os.path.join(a.evidence_dir, "evidence.json"))
    draft = open(a.text, encoding="utf-8").read()
    numbers = [m.group(0).strip() for m in NUM_RE.finditer(draft)]
    known_nums = {norm_num(m.group(0)) for m in NUM_RE.finditer(corpus)}
    unsupported = [n for n in dict.fromkeys(numbers) if norm_num(n) not in known_nums]
    flat_corpus = re.sub(r"\s+", "", corpus).lower()
    cites = list(dict.fromkeys(CITE_RE.findall(draft)))
    missing_cites = [c for c in cites
                     if re.sub(r"\s+", "", c).lower() not in flat_corpus
                     and c.strip("[]") not in corpus]
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


# ------------------------------------------------------------ artifacts
def _loc_text(x):
    loc = x.get("location") or x.get("target") or {}
    parts = []
    if loc.get("section"):
        parts.append("§%s" % loc["section"])
    if loc.get("paragraph_id"):
        parts.append(str(loc["paragraph_id"]))
    if loc.get("sentence_index"):
        parts.append("第%s句" % cn_num(loc["sentence_index"]))
    return " ".join(parts) or "（未定位）"


def _md_escape(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def render_structure_plan(res):
    lines = ["# 论文结构与逻辑修改方案", ""]
    lines.append("- case_id：`%s`" % res.get("case_id"))
    lines.append("- 状态：`%s`" % res.get("status"))
    lines.append("- 主产物：`%s`" % res.get("artifact_path", "structure_plan.md"))
    cov = res.get("coverage") or {}
    checked = [d for d, v in cov.items() if isinstance(v, dict) and v.get("checked")]
    lines.append("- 已检查维度：%s" % ("、".join(checked) or "无"))
    lines.append("- 诊断条数：%d；动作条数：%d" % (len(res.get("diagnosis") or []), len(res.get("edit_plan") or [])))
    lines.append("")
    lines.append("> 所有判断均来自本次读取的稿件原文；原文片段逐字引用。规则自动产出的条目标为候选，"
                 "需作者按稿件实际语境确认；本文件不重写全文、不改数值与引用。")
    lines.append("")

    lines += ["## 一、结构问题诊断", ""]
    diags = res.get("diagnosis") or []
    if not diags:
        lines.append("本次规则检查未发现可定位的结构问题（六维检查状态见 coverage）。")
        lines.append("")
    for x in diags:
        lines.append("### %s｜%s｜%s" % (x.get("issue_id"), x.get("dimension"), x.get("severity")))
        lines.append("")
        lines.append("- 位置：%s" % _loc_text(x))
        loc = x.get("location") or {}
        if loc.get("anchor_quote"):
            lines.append("- 原文片段：\"%s\"" % loc["anchor_quote"].replace("\n", " "))
        lines.append("- 问题类型：`%s`" % x.get("problem_type", ""))
        lines.append("- 问题：%s" % x.get("problem", ""))
        lines.append("- 依据：%s" % x.get("why", ""))
        refs = x.get("evidence_refs") or []
        if refs:
            lines.append("- 关联证据：%s" % "、".join(str(r) for r in refs))
        lines.append("- 置信度：%s" % x.get("confidence", ""))
        lines.append("")

    lines += ["## 二、可执行修改动作", ""]
    edits = res.get("edit_plan") or []
    if not edits:
        lines.append("无（未发现需要执行的结构动作）。")
        lines.append("")
    for e in edits:
        lines.append("### %s → issue %s｜`%s`" % (e.get("edit_id"), e.get("issue_id"), e.get("action")))
        lines.append("")
        lines.append("- 目标：%s%s" % (_loc_text(e),
                                     (" → " + str(e["destination"])) if e.get("destination") else ""))
        lines.append("- 操作：%s" % e.get("instruction", ""))
        lines.append("- 保持不变：%s" % e.get("preserves", ""))
        lines.append("- 预期效果：%s" % e.get("expected_effect", ""))
        if e.get("risk"):
            lines.append("- 风险/需确认：%s" % e["risk"])
        lines.append("")

    lines += ["## 三、修改后大纲", ""]
    outline = res.get("outline") or []
    if outline:
        lines.append("| 顺序 | 章节 | 功能 | 承接原段落 | 说明 |")
        lines.append("|-|-|-|-|-|")
        for o in outline:
            lines.append("| %s | %s | %s | %s | %s |" % (
                o.get("order", ""), _md_escape(o.get("section")), _md_escape(o.get("role")),
                _md_escape("、".join(o.get("paragraphs_from") or []) or "—"),
                _md_escape(o.get("note", ""))))
    else:
        lines.append("未生成（未识别出章节结构，见 limitations）。")
    lines.append("")

    lines += ["## 四、原段落去向（不静默丢弃）", ""]
    pmap = res.get("paragraph_map") or []
    if pmap:
        lines.append("| 段落 | 去向 | 目标/关联 | 理由 |")
        lines.append("|-|-|-|-|")
        for p in pmap:
            dest = p.get("to") or p.get("into") or "、".join(p.get("split_into") or []) or "—"
            lines.append("| %s | %s | %s | %s |" % (
                p.get("paragraph_id"), p.get("status"), _md_escape(dest), _md_escape(p.get("reason", ""))))
    else:
        lines.append("未生成（稿件未能切分为段落，见 limitations）。")
    lines.append("")

    lines += ["## 五、论点—论据映射", ""]
    amap = res.get("argument_map") or []
    if amap:
        lines.append("| 论断 | 位置 | 证据 | 强度 | 断点 |")
        lines.append("|-|-|-|-|-|")
        for c in amap:
            refs = "、".join(str(e.get("ref")) for e in c.get("evidence") or []) or "未检出"
            lines.append("| %s | %s | %s | %s | %s |" % (
                _md_escape(c.get("claim")), _loc_text({"target": {"paragraph_id": c.get("paragraph_id"),
                                                                 "section": c.get("section")}}),
                _md_escape(refs), c.get("strength", ""), _md_escape(c.get("breakpoint", "") or "—")))
    else:
        lines.append("未抽取到可定位的论断候选。")
    lines.append("")

    fg = res.get("fact_guard") or {}
    lines += ["## 六、事实守卫", "",
              "- 悬空数字：%s" % (fg.get("numbers_unbound") or "无"),
              "- 来源外引用：%s" % (fg.get("citations_not_in_sources") or "无"),
              "- 引文逐字核验：%s" % (fg.get("quotes_checked", "未运行")),
              "- 判定：`%s`" % fg.get("verdict", "未判定"), ""]

    lines += ["## 七、不确定性与限制", ""]
    unc = res.get("uncertainty") or []
    for u in unc:
        lines.append("- %s" % u if isinstance(u, str) else "- `%s`：%s" % (u.get("item", ""), u.get("reason", "")))
    if not unc:
        lines.append("- 无显式不确定性条目。")
    if res.get("limits"):
        lines.append("- 限制：%s" % res["limits"])
    lines.append("")

    lines += ["## 八、方法与来源", "",
              "- 方法：章节/段落切分 → 六维规则定位 → 论点—论据抽取 → 动作化 → 大纲与段落去向 → 事实守卫。",
              "- 来源定位：`source_map[]` 中逐条记录段落、行号与材料路径。",
              "- 规则产出的问题均为候选，作者复核后可采纳、部分采纳或驳回；本方案不修改原稿文件。", ""]
    return "\n".join(lines) + "\n"


def render_outline(res):
    lines = ["# 修改后大纲", ""]
    outline = res.get("outline") or []
    if not outline:
        lines.append("未识别出章节结构（可能无标题或编号混乱），见 limitations。")
        return "\n".join(lines) + "\n"
    lines.append("| 顺序 | 章节 | 功能 | 承接原段落 | 合并/拆分 | 说明 |")
    lines.append("|-|-|-|-|-|-|")
    for o in outline:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            o.get("order", ""), _md_escape(o.get("section")), _md_escape(o.get("role")),
            _md_escape("、".join(o.get("paragraphs_from") or []) or "—"),
            _md_escape("、".join(o.get("merge_of") or []) or "—"),
            _md_escape(o.get("note", ""))))
    return "\n".join(lines) + "\n"


def _write_csv(path, header, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])


def cmd_emit(a):
    contract_path = os.path.join(a.contract_dir, "contract.json")
    contract = load_json(contract_path) if os.path.isdir(a.contract_dir) else load_json(a.contract_dir)
    draft = load_json(a.draft)
    fields = contract.get("contract") or {}
    body = draft.get("fields") or {}
    result = {"case_id": contract.get("case_id") or draft.get("case_id") or "case",
              "status": draft.get("status", "partial")}
    gaps = []
    if isinstance(fields, dict):
        for name in fields:
            val = body.get(name, draft.get(name))
            if val is None:
                gaps.append(name)
            result[name] = val
        for name, value in body.items():
            result.setdefault(name, value)
        for name, value in draft.items():
            if name not in ("fields", "artifacts"):
                result.setdefault(name, value)
    else:
        result.update(body)
    defaults = {
        "artifact_path": "structure_plan.md", "artifact_format": "md",
        "diagnosis": [], "edit_plan": [], "outline": [], "paragraph_map": [],
        "argument_map": [], "source_map": [], "changes": [], "uncertainty": [],
        "coverage": {}, "fact_guard": {}, "self_check": {},
    }
    for key, val in defaults.items():
        if result.get(key) is None:
            result[key] = val
    if result.get("uncertainty") is None:
        result["uncertainty"] = []
    if gaps:
        result["contract_gaps"] = gaps
        note = "未提供语义的契约字段（按 null 保留，不臆造内容）：%s" % ",".join(gaps)
        limits = result.get("limits") or ""
        result["limits"] = (limits + "；" + note) if limits else note
    os.makedirs(a.out, exist_ok=True)
    dump(result, os.path.join(a.out, "result.json"))
    # Always render the four required human-checkable artifacts, whether or not the draft supplied them.
    artifacts = {name: body_ for name, body_ in (draft.get("artifacts") or {}).items()}
    artifacts.setdefault("structure_plan.md", render_structure_plan(result))
    artifacts.setdefault("outline.md", render_outline(result))
    diags = result.get("diagnosis") or []
    artifacts.setdefault("diagnosis.csv", None)
    if artifacts["diagnosis.csv"] is None:
        rows = [[x.get("issue_id"), x.get("dimension"), x.get("severity"), x.get("confidence"),
                 (x.get("location") or {}).get("section"), (x.get("location") or {}).get("paragraph_id"),
                 (x.get("location") or {}).get("sentence_index"), x.get("problem_type"), x.get("problem"),
                 x.get("why"), (x.get("location") or {}).get("anchor_quote")] for x in diags]
        _write_csv(os.path.join(a.out, "diagnosis.csv"),
                   ["issue_id", "dimension", "severity", "confidence", "section", "paragraph_id",
                    "sentence_index", "problem_type", "problem", "why", "anchor_quote"], rows)
        artifacts.pop("diagnosis.csv")
    edits = result.get("edit_plan") or []
    artifacts.setdefault("edit_plan.csv", None)
    if artifacts["edit_plan.csv"] is None:
        rows = [[e.get("edit_id"), e.get("issue_id"), e.get("action"),
                 (e.get("target") or {}).get("section"), (e.get("target") or {}).get("paragraph_id"),
                 (e.get("target") or {}).get("sentence_index"), e.get("destination"),
                 e.get("instruction"), e.get("preserves"), e.get("expected_effect"), e.get("risk")] for e in edits]
        _write_csv(os.path.join(a.out, "edit_plan.csv"),
                   ["edit_id", "issue_id", "action", "section", "paragraph_id", "sentence_index",
                    "destination", "instruction", "preserves", "expected_effect", "risk"], rows)
        artifacts.pop("edit_plan.csv")
    for name, content in artifacts.items():
        if content is None:
            continue
        p = os.path.join(a.out, name)
        os.makedirs(os.path.dirname(p) or a.out, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
    print("result.json written; contract_gaps=%s; artifacts=%s"
          % (gaps or "none", ",".join(sorted(os.listdir(a.out)))))
    return 0


def cmd_check(a):
    problems, warns = [], []
    rp = os.path.join(a.out, "result.json")
    res = {}
    if not os.path.exists(rp):
        problems.append("result.json missing")
    else:
        try:
            res = load_json(rp)
        except Exception as exc:  # noqa: BLE001
            problems.append("result.json unparsable: %s" % exc)
    if res:
        for k in ("case_id", "status"):
            if not res.get(k):
                problems.append("result.json missing %s" % k)
        if res.get("status") not in {"ok", "success", "partial", "blocked", "refused"}:
            problems.append("status must be one of ok/success/partial/blocked/refused")
        if res.get("status") == "partial" and not str(res.get("limits", "")).strip():
            problems.append("status=partial but limits is empty")
        gaps = set(res.get("contract_gaps") or [])
        cp = os.path.join(a.contract_dir, "contract.json")
        if os.path.exists(cp):
            fields = load_json(cp).get("contract") or {}
            for name in (fields if isinstance(fields, dict) else []):
                if name in ("uncertainty", "limits", "changes", "notes"):
                    if name not in res:
                        problems.append("result.json missing contract field %s" % name)
                    continue
                val = res.get(name, "__MISSING__")
                if val == "__MISSING__" or val is None:
                    msg = "result.json missing contract field %s" % name
                    (warns if name in gaps else problems).append(msg)
                elif isinstance(val, (list, dict, str)) and not val:
                    warns.append("result.json contract field %s is empty" % name)
        else:
            warns.append("contract.json not found; skipped contract-field check")
        for name in ARTIFACTS:
            p = os.path.join(a.out, name)
            if not os.path.exists(p):
                problems.append("artifact %s missing" % name)
            elif os.path.getsize(p) < 8:
                problems.append("artifact %s is empty/truncated" % name)
        if not res.get("self_check"):
            warns.append("self_check summary absent in result.json")
        for key in ("diagnosis", "edit_plan", "outline", "paragraph_map", "argument_map",
                    "source_map", "uncertainty", "changes"):
            if not isinstance(res.get(key), (list, type(None))):
                problems.append("result.%s must be an array" % key)
        if res.get("status") in ("ok", "partial") and not res.get("diagnosis") \
                and not (res.get("coverage") or {}).get("no_issues_found"):
            warns.append("diagnosis empty and no_issues_found not declared")
    report = {"ok": not problems, "problems": problems, "warnings": warns}
    if a.report:
        dump(report, a.report)
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
    p = sub.add_parser("index"); p.add_argument("--materials", nargs="*", default=[]); p.add_argument("--case")
    p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("verify"); p.add_argument("--text", required=True); p.add_argument("--evidence-dir", default="work")
    p.add_argument("--out", default="work"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("emit"); p.add_argument("--draft", required=True); p.add_argument("--contract-dir", default="work")
    p.add_argument("--out", default="/app/output"); p.set_defaults(fn=cmd_emit)
    p = sub.add_parser("check"); p.add_argument("--out", default="/app/output"); p.add_argument("--contract-dir", default="work")
    p.add_argument("--report", default=""); p.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    try:
        return a.fn(a)
    except Exception as exc:  # noqa: BLE001 - never die without a diagnostic line
        print("ERROR: %s: %s" % (type(exc).__name__, exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
