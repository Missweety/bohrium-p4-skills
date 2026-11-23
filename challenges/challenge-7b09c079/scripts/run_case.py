#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_case.py -- 学术写作客户端：一条命令完成"读稿 -> 按指令改 -> 留修订 -> 同步引用 -> 导出版本"。

用法：
    python3 /skills/weekly-skill/scripts/run_case.py \
        --input /input --work /app/work --out /app/output

产物：
    revision.docx     含 Word 修订标记（w:ins/w:del，可逐条接受/拒绝）
    clean.docx        全部接受后的干净稿（可直接投稿/继续编辑）
    revision.md       干净稿 Markdown 版
    revision.diff     原稿与干净稿的逐行差异
    original.docx     原稿只读副本（v0，回退目标）
    revisions.json    逐条修订：位置/锚点/前后/依据/状态
    versions.json     版本谱系（sha256、父版本、回退说明）
    citation_map 含于 result.json：正文与参考文献表的 old->new 编号映射
    preview.pdf|html  真实渲染预览
    result.json       契约字段 + 来源 + 不确定性 + 变更记录 + 自检
    work/doc.json|revisions.json|self_check.json

退出码 0：已写出结构完整且诚实的交付物（success/partial/failed 都写全 + 原因）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys

import citations
import docx_io
import lineage
import locate
import preview
import track_changes

AUTHOR = track_changes.DEFAULT_AUTHOR
DATE = track_changes.DEFAULT_DATE
TEXT_KEYS = ("manuscript", "materials", "files", "inputs", "documents", "chapters", "artifacts")
SKIP_NAMES = {"task.md", "case.json", "organizer-edit-workorder.json", "README.md"}

FIELD_ALIASES = {
    "manuscript": ["artifact", "outputs"],
    "draft": ["artifact", "outputs"],
    "document": ["artifact", "outputs"],
    "revision": ["artifact", "outputs"],
    "revised_document": ["artifact", "outputs"],
    "artifact": ["artifact", "outputs"],
    "output": ["outputs", "artifact"],
    "revisions": ["revisions"],
    "changes": ["revisions"],
    "edit_log": ["revisions"],
    "track_changes": ["revisions"],
    "citation_map": ["citation_map"],
    "versions": ["version_history"],
    "version_history": ["version_history"],
    "evidence": ["evidence"],
}


# --------------------------------------------------------------------------- #
def read_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh), None
    except FileNotFoundError:
        return None, "文件不存在"
    except Exception as exc:
        return None, "JSON 解析失败: %s" % exc


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return fh.read()
    except Exception:
        return ""


def find_file(input_dir, name):
    cand = os.path.join(input_dir, name)
    if os.path.exists(cand):
        return cand
    hits = glob.glob(os.path.join(input_dir, "**", name), recursive=True)
    return hits[0] if hits else None


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def discover_materials(input_dir, case):
    items = []
    if isinstance(case, dict):
        for key in TEXT_KEYS:
            val = case.get(key)
            if not val:
                continue
            if isinstance(val, dict):
                val = val.get("items") or val.get("paths") or []
            val = [val] if isinstance(val, str) else val
            for it in val:
                path = it.get("path") if isinstance(it, dict) else it
                if isinstance(path, str):
                    items.append(path)
    resolved, missing = [], []
    for raw in items:
        hit = next((c for c in (raw, os.path.join(input_dir, raw),
                                os.path.join(input_dir, "materials", raw))
                    if c and os.path.isfile(c)), None)
        (resolved if hit else missing).append(os.path.abspath(hit) if hit else raw)
    if not resolved:
        for dirpath, _dirs, files in os.walk(input_dir):
            for f in files:
                if (os.path.splitext(f)[1].lower() in (".docx", ".md", ".txt", ".pdf")
                        and f not in SKIP_NAMES):
                    resolved.append(os.path.abspath(os.path.join(dirpath, f)))
    seen, unique = set(), []
    for p in sorted(resolved, key=natural_key):
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique, missing


def parse_contract(case):
    if not isinstance(case, dict):
        return []
    oc = case.get("output_contract")
    if isinstance(oc, dict):
        for k in ("required", "fields", "keys", "items"):
            if isinstance(oc.get(k), list):
                return [str(x) for x in oc[k]]
        return [str(k) for k, v in oc.items() if v]
    return [str(x) for x in oc] if isinstance(oc, list) else []


def _first(d, keys):
    for k in keys:
        if isinstance(d.get(k), str) and d[k]:
            return d[k]
    return None


def extract_pairs(s):
    pairs = []
    for m in re.finditer(r"[“\"「]([^”\"」]{1,80})[”\"」]\s*(?:统一为|改为|替换为|→|->)\s*"
                         r"[“\"「]([^”\"」]{1,80})[”\"」]", s):
        pairs.append((m.group(1), m.group(2)))
    return pairs


def parse_workorder(data):
    out = {"replace": [], "delete": [], "insert": [], "unparsed": [],
           "citation_sync": True, "raw_keys": []}
    if not isinstance(data, dict):
        return out
    for k, v in data.items():
        kl = str(k).lower()
        out["raw_keys"].append(str(k))
        if "citation" in kl:
            out["citation_sync"] = bool(v)
        if re.search(r"^(edits?|replacements?|changes?|修改|改动)$", kl) and isinstance(v, list):
            for it in v:
                if isinstance(it, dict):
                    q = _first(it, ["target_quote", "quote", "find", "old", "before", "target"])
                    r = _first(it, ["replacement", "replace", "new", "after", "text"])
                    if q and isinstance(r, str):
                        out["replace"].append({"quote": q, "new": r,
                                               "basis": it.get("basis") or it.get("reason") or ""})
                    else:
                        out["unparsed"].append(json.dumps(it, ensure_ascii=False))
                elif isinstance(it, str):
                    out["unparsed"].append(it)
        if re.search(r"delete|删除|删除句", kl) and isinstance(v, list):
            for it in v:
                q = it.get("quote") or it.get("text") if isinstance(it, dict) else it
                b = it.get("basis", "") if isinstance(it, dict) else ""
                if isinstance(q, str) and q:
                    out["delete"].append({"quote": q, "basis": b})
        if re.search(r"insert|插入|新增", kl) and isinstance(v, list):
            for it in v:
                if isinstance(it, dict):
                    a = _first(it, ["anchor", "after", "target_quote", "quote"])
                    t = _first(it, ["text", "insert", "new"])
                    if a and t:
                        out["insert"].append({"anchor": a, "text": t,
                                              "basis": it.get("basis", "")})
        if re.search(r"instruction|指令", kl) and isinstance(v, list):
            for it in v:
                s = it if isinstance(it, str) else (it.get("instruction") or it.get("text") or "")
                pairs = extract_pairs(s)
                if pairs:
                    for q, r in pairs:
                        out["replace"].append({"quote": q, "new": r, "basis": "工单指令"})
                elif s.strip():
                    out["unparsed"].append(s)
    return out


# --------------------------------------------------------------------------- #
def pdf_text(path, work_dir):
    import shutil
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    out = os.path.join(work_dir, "from_text", os.path.splitext(os.path.basename(path))[0] + ".txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        subprocess.run([exe, "-layout", path, out], check=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=120)
        txt = read_text(out)
        return txt if txt.strip() else None
    except Exception:
        return None


def load_material(path, work_dir, tag):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".docx":
            return docx_io.load_docx(path, source_path=os.path.basename(path)), None
        if ext in (".md", ".txt", ".pdf"):
            txt = read_text(path) if ext != ".pdf" else pdf_text(path, work_dir)
            if txt is None or not txt.strip():
                return None, "PDF 无可提取文本层（需要 OCR / pdf-text-tool）"
            tmp = os.path.join(work_dir, "from_text", "%s.docx" % tag)
            docx_io.build_docx(docx_io.text_to_blocks(txt), tmp)
            return docx_io.load_docx(tmp, source_path=os.path.basename(path)), None
        return None, "不支持的类型: %s（旧版 .doc/.rtf 请先转 docx）" % ext
    except docx_io.DocxError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, "抽取异常: %s" % exc


def merge_blocks(docs):
    blocks = []
    for d in docs:
        done = set()
        for p in d["paragraphs"]:
            if p.get("in_table"):
                ti = p.get("table_index")
                if ti in done:
                    continue
                done.add(ti)
                t = next((x for x in d["tables"] if x["index"] == ti), None)
                if t and t["rows"]:
                    blocks.append({"kind": "table", "rows": t["rows"]})
                continue
            lvl = locate.style_level(p)
            if lvl:
                blocks.append({"kind": "heading", "level": lvl, "text": p["text"]})
            elif locate.caption_info(p):
                blocks.append({"kind": "caption", "text": p["text"]})
            else:
                blocks.append({"kind": "para", "text": p["text"]})
    return blocks


def render_md(doc):
    out = []
    for p in doc["paragraphs"]:
        if p.get("in_table"):
            continue
        text = p["text"].strip()
        if not text:
            continue
        lvl = p.get("heading_level") or 0
        out.append(("#" * min(6, lvl) + " " + text) if lvl else text)
        out.append("")
    for t in doc.get("tables", []):
        if not t["rows"]:
            continue
        out.append("| " + " | ".join(str(c).replace("\n", " ") for c in t["rows"][0]) + " |")
        out.append("|" + "---|" * len(t["rows"][0]))
        for row in t["rows"][1:]:
            cells = [str(c).replace("\n", " ") for c in row]
            cells += [""] * (len(t["rows"][0]) - len(cells))
            out.append("| " + " | ".join(cells) + " |")
        out.append("")
    return "\n".join(out).strip() + "\n"


def contract_payload(payload, required):
    out, gaps = {}, []
    for name in required:
        key = name.strip()
        if key in payload:
            out[key] = payload[key]
            continue
        hit = next((a for a in FIELD_ALIASES.get(key.lower(), []) if a in payload), None)
        out[key] = payload[hit] if hit else None
        if hit is None:
            gaps.append(key)
    for k, v in payload.items():
        out.setdefault(k, v)
    return out, gaps


# --------------------------------------------------------------------------- #
def run(args):
    input_dir = os.path.abspath(args.input)
    work_dir = os.path.abspath(args.work)
    out_dir = os.path.abspath(args.out)
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    case_path = args.case or os.path.join(input_dir, "case.json")
    case, _ = read_json(case_path)
    case = case if isinstance(case, dict) else {}
    case_id = str(case.get("case_id") or case.get("id") or "unknown-case")
    required = parse_contract(case)
    task_text = read_text(os.path.join(input_dir, "task.md"))
    wo_path = args.workorder or find_file(input_dir, "organizer-edit-workorder.json")
    wo_raw, wo_err = (read_json(wo_path) if wo_path else (None, "未提供"))
    workorder = parse_workorder(wo_raw if isinstance(wo_raw, dict) else {})

    materials, missing = discover_materials(input_dir, case)
    sources, docs, errors = [], [], []
    for i, path in enumerate(materials):
        doc, err = load_material(path, work_dir, "m%d" % (i + 1))
        kind = os.path.splitext(path)[1].lstrip(".").lower()
        if doc is None:
            sources.append({"path": os.path.basename(path), "kind": kind,
                            "status": "unreadable", "paragraphs": 0, "error": err})
            errors.append({"path": os.path.basename(path), "error": err})
        else:
            sources.append({"path": os.path.basename(path), "kind": kind,
                            "status": "parsed", "paragraphs": len(doc["paragraphs"]),
                            "error": None})
            docs.append(doc)

    change_log = [{"action": "input_scan", "detail": {
        "case_json": case_path if os.path.exists(case_path) else None,
        "task_md": bool(task_text), "workorder": wo_path, "workorder_error": wo_err,
        "workorder_keys": workorder["raw_keys"],
        "materials": [os.path.basename(m) for m in materials]}}]
    uncertainty = [{"item": m, "reason": "case.json 声明的材料在 /input 中找不到",
                    "where": "input"} for m in missing]
    uncertainty += [{"item": e["path"], "reason": e["error"], "where": "extraction"}
                    for e in errors]
    uncertainty += [{"item": s, "where": "workorder", "status": "pending",
                     "reason": "语义型修改指令无法机械落地，需模型/人工按清单改写；未自动改写。"}
                    for s in workorder["unparsed"]]

    if not docs:
        payload = {
            "case_id": case_id, "status": "failed", "artifact": None,
            "artifact_format": None, "outputs": {}, "revisions": [],
            "revision_summary": {"applied": 0, "skipped": 0, "pending": len(workorder["unparsed"])},
            "citation_map": [], "citation_sync": {"checked": False}, "version_history": {},
            "evidence": [], "coverage": {}, "sources": sources,
            "uncertainty": uncertainty or [{"item": "materials", "reason": "无可读材料",
                                            "where": "input"}],
            "change_log": change_log, "contract_gaps": [],
            "limits": "没有可读取的稿件，未产出修订稿；已列出每个失败文件的原因。",
            "self_check": {"ok": False, "checks": {}, "errors": ["无可读材料"]},
        }
        for k in required:
            payload.setdefault(k, None)
        with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        with open(os.path.join(work_dir, "self_check.json"), "w", encoding="utf-8") as fh:
            json.dump(payload["self_check"], fh, ensure_ascii=False, indent=1)
        print(json.dumps({"case_id": case_id, "status": "failed",
                          "reason": "no readable material"}, ensure_ascii=False))
        return 0

    rebuild = len(docs) > 1
    if rebuild:
        base_path = os.path.join(work_dir, "merged_base.docx")
        docx_io.build_docx(merge_blocks(docs), base_path)
        base = docx_io.load_docx(base_path, source_path="merged_base")
        uncertainty.append({"item": "格式", "where": "output",
                            "reason": "多份来源已合并重建为单一 docx：标题层级、正文与表格顺序保留，"
                                      "原始分页/页眉页脚/复杂域不保留。"})
    else:
        base = docs[0]

    sections = locate.assign_sections(base["paragraphs"])
    base_texts = [p["text"] for p in base["paragraphs"]]
    by_id = {p["id"]: p for p in base["paragraphs"]}
    ids = track_changes.IdGen(base["root"])
    revisions, skipped, pending = [], [], []

    def add_rev(rtype, pid, anchor, before, after, basis, result):
        p = by_id.get(pid)
        base_text = base_texts[int(pid[1:]) - 1] if pid and pid.startswith("P") else ""
        off = base_text.find(anchor) if anchor else -1
        rec = {"revision_id": "R%03d" % (len(revisions) + 1), "type": rtype,
               "paragraph_id": pid, "section": p.get("section") if p else None,
               "anchor": anchor, "before": before, "after": after,
               "char_start": off, "char_end": off + len(anchor) if off >= 0 else None,
               "basis": basis, "author": AUTHOR, "date": DATE,
               "status": "applied"}
        revisions.append(rec)
        return rec

    def find_paragraph(quote, used):
        for p in base["paragraphs"]:
            if p.get("in_table"):
                continue
            if p["id"] in used and used[p["id"]] >= p["text"].count(quote):
                continue
            if quote in p["text"]:
                used[p["id"]] = used.get(p["id"], 0) + 1
                return p
        return None

    used = {}
    for ed in workorder["replace"]:
        p = find_paragraph(ed["quote"], used)
        res = track_changes.replace_quote(p, ed["quote"], ed["new"], ids, AUTHOR, DATE) if p else None
        if res:
            add_rev("replace", p["id"], ed["quote"], ed["quote"], ed["new"],
                    ed["basis"], res)
        else:
            skipped.append({"type": "replace", "anchor": ed["quote"],
                            "reason": "原文未逐字命中该引文"})
    for ed in workorder["delete"]:
        p = find_paragraph(ed["quote"], used)
        res = track_changes.replace_quote(p, ed["quote"], "", ids, AUTHOR, DATE) if p else None
        if res:
            add_rev("delete", p["id"], ed["quote"], ed["quote"], "",
                    ed["basis"] or "工单要求删除", res)
        else:
            skipped.append({"type": "delete", "anchor": ed["quote"],
                            "reason": "原文未逐字命中该引文"})
    for ed in workorder["insert"]:
        p = find_paragraph(ed["anchor"], used)
        res = track_changes.insert_after(p, ed["anchor"], ed["text"], ids, AUTHOR, DATE) if p else None
        if res:
            add_rev("insert", p["id"], ed["anchor"], ed["anchor"],
                    ed["anchor"] + ed["text"], ed["basis"] or "工单要求在锚点后插入", res)
        else:
            skipped.append({"type": "insert", "anchor": ed["anchor"],
                            "reason": "原文未逐字命中锚点"})
    for s in workorder["unparsed"]:
        pending.append({"type": "semantic", "anchor": None, "instruction": s,
                        "reason": "语义型指令需要模型判断改写幅度，未机械落地"})

    collected = citations.collect(base["paragraphs"])
    citation_map, cit = [], None
    if workorder["citation_sync"] and collected["in_text"]:
        mapping, changes = citations.build_map(collected)
        cit = citations.apply(base, collected, mapping, ids, AUTHOR, DATE)
        for rec in cit["applied"]:
            add_rev(rec["type"], rec["paragraph_id"],
                    rec.get("anchor") or rec.get("before") or "",
                    rec.get("before"), rec.get("after"),
                    "按正文首次出现顺序重排引用编号并同步参考文献表", rec)
        for rec in cit["skipped"]:
            skipped.append({"type": rec["type"], "anchor": rec.get("anchor"),
                            "reason": "编号改写未命中原文（可能已被修订覆盖）"})
        citation_map = changes

    rev_path = os.path.join(out_dir, "revision.docx")
    docx_io.save_docx(base, rev_path)
    clean_path = os.path.join(out_dir, "clean.docx")
    track_changes.accept_all(base, clean_path)

    original_path = os.path.join(out_dir, "original.docx")
    import shutil
    shutil.copyfile(base["path"], original_path)

    clean_doc = docx_io.load_docx(clean_path, source_path="clean")
    locate.assign_sections(clean_doc["paragraphs"])
    clean_texts = [p["text"] for p in clean_doc["paragraphs"]]
    with open(os.path.join(out_dir, "revision.md"), "w", encoding="utf-8") as fh:
        fh.write(render_md(clean_doc))
    with open(os.path.join(out_dir, "revision.diff"), "w", encoding="utf-8") as fh:
        fh.write(lineage.diff(base_texts, clean_texts,
                              os.path.splitext(sources[0]["path"])[0]))

    versions = lineage.build(case_id, original_path, rev_path, len(revisions),
                             note="v1 含 Word 修订标记；v2(clean) 为全部接受后的干净稿")
    versions["versions"].append({
        "version": "v1-clean", "role": "accepted", "parent": "v1",
        "file": "clean.docx", "sha256": lineage.sha256(clean_path),
        "bytes": os.path.getsize(clean_path), "note": "全部接受修订后的可编辑稿"})
    versions["line_diff"] = lineage.changed_lines(base_texts, clean_texts)

    prev = preview.render_pdf(clean_path, os.path.join(out_dir, "preview.pdf"))
    preview.render_html([p["text"] for p in clean_doc["paragraphs"]],
                        os.path.join(out_dir, "preview.html"), title=case_id)

    with open(os.path.join(out_dir, "revisions.json"), "w", encoding="utf-8") as fh:
        json.dump({"case_id": case_id, "revisions": revisions,
                   "skipped": skipped, "pending": pending}, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "versions.json"), "w", encoding="utf-8") as fh:
        json.dump(versions, fh, ensure_ascii=False, indent=1)

    # ---- 独立复核：修订稿 vs 干净稿 vs 原稿 ----
    checks = {}
    rev_texts, rev_ok, rev_err = docx_io.docx_text(rev_path)
    checks["revision_openable"] = bool(rev_ok and docx_io.docx_info(rev_path)["ok"])
    checks["clean_openable"] = bool(docx_io.docx_info(clean_path)["ok"])
    checks["revision_marks_present"] = (rev_ok and any(
        i.get("insertions") or i.get("deletions")
        for i in [track_changes.count_tracked(p["xml"]) for p in base["paragraphs"]]))
    checks["revision_equals_clean"] = (rev_ok and rev_texts == clean_texts)
    clean_full = "\n".join(clean_texts)
    rev_full = "\n".join(rev_texts)

    unverified = []
    for r in revisions:
        if r["type"] in ("replace", "insert"):
            if r["after"] and r["after"] not in clean_full:
                unverified.append(r["revision_id"])
        elif r["type"] == "delete":
            if r["before"] and r["before"] in clean_full:
                unverified.append(r["revision_id"])
        elif r["type"] == "citation_renumber":
            if r["after"] and r["after"] not in clean_full:
                unverified.append(r["revision_id"])
    checks["edits_visible_in_clean"] = not unverified
    bad_anchor = [r["revision_id"] for r in revisions
                  if r.get("anchor") and r.get("paragraph_id")
                  and r["anchor"] not in base_texts[int(r["paragraph_id"][1:]) - 1]]
    checks["anchors_verbatim"] = not bad_anchor
    checks["versions_linked"] = bool(versions["versions"][0]["sha256"]
                                     and versions["versions"][1]["parent"] == "v0")
    checks["preview"] = prev["status"]
    checks["contract_fields_present"] = all(True for _ in required)

    errors_sc = []
    if not checks["revision_openable"] or not checks["clean_openable"]:
        errors_sc.append("docx 不可解析: %s" % rev_err)
    if not checks["revision_equals_clean"]:
        errors_sc.append("接受修订后的文本与干净稿不一致")
    if unverified:
        errors_sc.append("修订内容未出现在干净稿: %s" % unverified[:5])
    if bad_anchor:
        errors_sc.append("锚点无法逐字复核: %s" % bad_anchor[:5])

    status = "success" if (not skipped and not pending and checks["revision_marks_present"]
                           and prev["status"] == "rendered" and not errors_sc) else "partial"
    limits = []
    if rebuild:
        limits.append("多源合并重建稿件，原始分页/页眉页脚/复杂域未保留。")
    if skipped:
        limits.append("%d 条指令未命中原文，未做改动（见 revisions.json.skipped）。" % len(skipped))
    if pending:
        limits.append("%d 条语义型指令未机械落地，已列入 uncertainty。"
                      % len(pending))
    if not checks["revision_marks_present"]:
        limits.append("本稿没有产生任何修订标记（可能无改动或结构不支持）。")
    if prev["status"] != "rendered":
        limits.append("PDF 预览不可用：%s；已提供 preview.html。" % prev["reason"])
    limits_s = " ".join(limits) or "无。"

    applied_types = {}
    for r in revisions:
        applied_types[r["type"]] = applied_types.get(r["type"], 0) + 1
    evidence = [{"revision_id": r["revision_id"], "paragraph_id": r["paragraph_id"],
                 "section": r["section"], "anchor": r["anchor"],
                 "status": r["status"]} for r in revisions]
    payload = {
        "case_id": case_id, "status": status,
        "artifact": "revision.docx", "artifact_format": "docx",
        "outputs": {"tracked": "revision.docx", "clean": "clean.docx",
                    "original": "original.docx", "markdown": "revision.md",
                    "diff": "revision.diff", "revisions": "revisions.json",
                    "versions": "versions.json",
                    "preview_pdf": "preview.pdf" if prev["status"] == "rendered" else None,
                    "preview_html": "preview.html", "report": "revision_report.md"},
        "revisions": revisions,
        "revision_summary": {"applied": len(revisions), "skipped": len(skipped),
                             "pending": len(pending), "by_type": applied_types,
                             "paragraphs_before": len(base_texts),
                             "paragraphs_after": len(clean_texts)},
        "skipped_revisions": skipped, "pending_instructions": pending,
        "citation_map": citation_map,
        "citation_sync": {"checked": cit is not None,
                          "applied": len(cit["applied"]) if cit else 0,
                          "reordered": (cit or {}).get("reordered"),
                          "in_text_citations": len(collected["in_text"]),
                          "reference_entries": len(collected["entries"])},
        "version_history": versions, "evidence": evidence,
        "coverage": {"checked": True,
                     "instructions_total": (len(workorder["replace"]) + len(workorder["delete"])
                                            + len(workorder["insert"]) + len(pending)),
                     "applied": len(revisions), "skipped": len(skipped),
                     "semantic_pending": len(pending),
                     "citation_renumber": (len(cit["applied"]) if cit else 0)},
        "sources": sources, "uncertainty": uncertainty,
        "change_log": change_log + [{"action": "tracked_revision", "detail": {
            "applied": len(revisions), "skipped": len(skipped),
            "pending": len(pending), "by_type": applied_types}},
            {"action": "version_snapshot", "detail": {
                "v0": versions["versions"][0]["sha256"][:12],
                "v1": versions["versions"][1]["sha256"][:12],
                "clean": versions["versions"][2]["sha256"][:12]}}],
        "limits": limits_s, "preview": prev,
    }
    final, gaps = contract_payload(payload, required)
    final["contract_gaps"] = gaps
    if gaps:
        uncertainty.append({"item": "output_contract", "where": "contract",
                            "reason": "契约字段语义未知，保留 null：%s" % gaps})
        final["uncertainty"] = uncertainty
        checks["contract_fields_present"] = False
        errors_sc.append("契约字段缺口: %s" % gaps)

    self_check = {"ok": not errors_sc, "checks": checks, "errors": errors_sc}
    final["self_check"] = self_check

    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(final, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "revision_report.md"), "w", encoding="utf-8") as fh:
        fh.write(render_report(case_id, status, revisions, skipped, pending,
                               citation_map, versions, sources, limits_s))
    with open(os.path.join(work_dir, "doc.json"), "w", encoding="utf-8") as fh:
        json.dump({"case_id": case_id, "sections": sections,
                   "paragraphs": [{"id": p["id"], "section": p["section"],
                                   "heading_level": p["heading_level"],
                                   "in_table": p.get("in_table"),
                                   "source_path": p.get("source_path"),
                                   "text": p["text"]} for p in base["paragraphs"]],
                   "clean_texts": clean_texts}, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(work_dir, "revisions.json"), "w", encoding="utf-8") as fh:
        json.dump({"revisions": revisions, "skipped": skipped, "pending": pending},
                  fh, ensure_ascii=False, indent=1)
    with open(os.path.join(work_dir, "self_check.json"), "w", encoding="utf-8") as fh:
        json.dump(self_check, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"case_id": case_id, "status": status,
                      "revisions": len(revisions), "skipped": len(skipped),
                      "pending": len(pending), "self_check_ok": self_check["ok"],
                      "preview": prev["status"]}, ensure_ascii=False))
    return 0


def render_report(case_id, status, revisions, skipped, pending, citation_map,
                  versions, sources, limits):
    lines = ["# 修订报告", "", "- case_id：`%s`" % case_id,
             "- 状态：**%s**" % status,
             "- 已应用修订：%d 条；未命中：%d 条；语义待办：%d 条"
             % (len(revisions), len(skipped), len(pending)), ""]
    if limits:
        lines += ["> 限制：%s" % limits, ""]
    lines += ["## 逐条修订（可在 Word 审阅中接受/拒绝）", ""]
    if not revisions:
        lines.append("本次没有产生修订。")
    for r in revisions:
        lines.append("- `%s` [%s] %s §%s：`%s` → `%s`（依据：%s）"
                     % (r["revision_id"], r["type"], r["paragraph_id"],
                        r.get("section"), r["before"], r["after"], r.get("basis") or "-"))
    if citation_map:
        lines += ["", "## 引用编号映射（old → new）", ""]
        for c in citation_map:
            lines.append("- [%s] → [%s]（首现 %s）%s"
                         % (c["old"], c["new"], c.get("first_paragraph") or "-",
                            "（变更）" if c["changed"] else "（不变）"))
    if skipped:
        lines += ["", "## 未命中（未改动原文）", ""]
        for s in skipped:
            lines.append("- [%s] `%s`：%s" % (s.get("type"), s.get("anchor"), s.get("reason")))
    if pending:
        lines += ["", "## 语义待办（需人工/模型处理）", ""]
        for s in pending:
            lines.append("- %s：%s" % (s.get("instruction"), s.get("reason")))
    lines += ["", "## 版本谱系", ""]
    for v in versions.get("versions", []):
        lines.append("- `%s` %s sha256=`%s…` 父版本=%s"
                     % (v["version"], v["file"], v["sha256"][:12], v.get("parent")))
    lines += ["", versions.get("rollback", ""), "", "## 输入来源", ""]
    for s in sources:
        lines.append("- `%s`（%s）：%s，段落 %s" % (s["path"], s["kind"],
                                                s["status"], s.get("paragraphs")))
    return "\n".join(lines) + "\n"


def check(outputs):
    result, err = read_json(os.path.join(outputs, "result.json"))
    problems = []
    if result is None:
        print("FAIL - result.json 不可读: %s" % err)
        return 1
    for k in ("case_id", "status", "revisions", "sources", "uncertainty", "change_log"):
        if k not in result:
            problems.append("缺少字段 %s" % k)
    need = ["revision.docx", "clean.docx", "original.docx", "revision.md",
            "revision.diff", "revisions.json", "versions.json", "revision_report.md"]
    for name in need:
        if not os.path.exists(os.path.join(outputs, name)):
            problems.append("缺少产物 %s" % name)
    for name in ("revision.docx", "clean.docx", "original.docx"):
        p = os.path.join(outputs, name)
        if os.path.exists(p) and not docx_io.docx_info(p)["ok"]:
            problems.append("%s 不可解析" % name)
    if not result.get("self_check", {}).get("ok"):
        problems.append("self_check 未通过: %s" % (result.get("self_check", {}).get("errors")))
    if problems:
        print("FAIL")
        for p in problems:
            print(" -", p)
        return 1
    print("PASS")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="学术写作客户端：按指令修订并留痕")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--case", default=None)
    ap.add_argument("--workorder", default=None)
    ap.add_argument("--check", default=None)
    a = ap.parse_args(argv)
    return check(os.path.abspath(a.check)) if a.check else run(a)


if __name__ == "__main__":
    sys.exit(main())
