#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_case.py -- 学位论文长文档一致性：一条命令完成"读稿 -> 巡检 -> 修订 -> 自检"。

用法：
    python3 /skills/weekly-skill/scripts/run_case.py \
        --input /input --work /app/work --out /app/output

产物：
    /app/output/result.json            契约字段 + 领域字段 + 状态 + 来源 + 变更记录 + 自检
    /app/output/revision.docx          修订稿（单 docx 时原位只改命中 run）
    /app/output/revision.md            同一稿的 Markdown 版
    /app/output/revision.diff          逐行差异
    /app/output/inconsistencies.csv    可逐条复核的不一致清单
    /app/output/consistency_report.md  人读版巡检报告
    /app/output/preview.pdf|.html      真实渲染预览（无渲染器则如实记录原因）
    /app/work/doc.json|findings.json|self_check.json

退出码 0：已写出结构完整且诚实的交付物（success / partial / failed 都写全 + 原因）。
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys

import consistency
import docx_io
import locate
import preview
import revise

TEXT_KEYS = ("materials", "files", "inputs", "documents", "chapters", "artifacts")
SKIP_NAMES = {"task.md", "case.json", "organizer-edit-workorder.json", "README.md"}

FIELD_ALIASES = {
    "parsed": ["parsed", "document", "doc_model"],
    "fields": ["fields", "term_table"],
    "evidence": ["evidence", "inconsistencies"],
    "thesis": ["artifact", "outputs"],
    "manuscript": ["artifact", "outputs"],
    "draft": ["artifact", "outputs"],
    "artifact": ["artifact", "outputs"],
    "output": ["outputs", "artifact"],
    "document": ["artifact", "outputs"],
    "revised_document": ["artifact", "outputs"],
    "revision": ["artifact", "outputs"],
}


# --------------------------------------------------------------------------- #
# 输入
# --------------------------------------------------------------------------- #
def read_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh), None
    except FileNotFoundError:
        return None, "文件不存在"
    except Exception as exc:
        return None, "JSON 解析失败: %s" % exc


TEXT_ENCODINGS = ("utf-8-sig", "gb18030", "utf-16")


def read_text_meta(path):
    """按 UTF-8 → GB18030 → UTF-16 顺序严格解码，返回 (text, meta)。

    meta: {"encoding": 实际编码, "fallback": 是否非 UTF-8, "lossy": 是否含替换字符,
           "error": 读取失败原因或 None}
    非 UTF-8 材料不再静默返回空串（旧版会把 GBK 材料误报成"PDF 无文本层"）。
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return "", {"encoding": None, "fallback": False, "lossy": False,
                    "error": "%s: %s" % (type(exc).__name__, exc)}
    if not raw.strip():
        return "", {"encoding": None, "fallback": False, "lossy": False, "error": None}
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        candidates = ("utf-16",)
    else:
        candidates = TEXT_ENCODINGS
    for enc in candidates:
        try:
            return raw.decode(enc), {"encoding": enc, "fallback": enc != "utf-8-sig",
                                     "lossy": False, "error": None}
        except UnicodeDecodeError:
            continue
    text = raw.decode("utf-8", "replace")
    return text, {"encoding": "utf-8(replace)", "fallback": True, "lossy": True,
                  "error": None}


def read_text(path):
    return read_text_meta(path)[0]


def find_file(input_dir, name):
    cand = os.path.join(input_dir, name)
    if os.path.exists(cand):
        return cand
    hits = glob.glob(os.path.join(input_dir, "**", name), recursive=True)
    return hits[0] if hits else None


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def discover_materials(input_dir, case, case_dir):
    items = []
    if isinstance(case, dict):
        for key in TEXT_KEYS:
            val = case.get(key)
            if not val:
                continue
            val = [val] if isinstance(val, str) else (val.get("items") or val.get("paths") or [] if isinstance(val, dict) else val)
            for it in val:
                path = it.get("path") if isinstance(it, dict) else it
                if isinstance(path, str):
                    items.append(path)
    resolved, missing = [], []
    for raw in items:
        hit = next((c for c in (raw, os.path.join(input_dir, raw),
                                os.path.join(case_dir, raw),
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


def material_labels(paths, input_dir):
    """来源显示名：默认 basename；不同目录下重名时退回相对路径，避免来源混淆。"""
    counts = {}
    for p in paths:
        counts[os.path.basename(p)] = counts.get(os.path.basename(p), 0) + 1
    labels = {}
    for p in paths:
        base = os.path.basename(p)
        if counts[base] > 1:
            try:
                labels[p] = os.path.relpath(p, input_dir)
            except ValueError:
                labels[p] = p
        else:
            labels[p] = base
    return labels


_ABS_PATH_RE = re.compile(r"(?<![\w.\-])(?:/[\w.\-+@%]+){2,}/?")


def scrub_paths(text):
    """产物里不写运行环境的绝对路径：错误信息只保留文件名/相对路径。"""
    if not text:
        return text
    out = _ABS_PATH_RE.sub("", str(text))
    out = re.sub(r"[:：]\s*$", "", out).strip()
    return out or "(路径已省略)"


FIND_KEYS = ("find", "old", "before", "from", "source_text", "orig", "original",
             "原词", "原句", "原文")
REPLACE_KEYS = ("replace", "new", "after", "to", "target_text", "replacement",
                "改为", "新词", "新句")
SCOPE_KEYS = ("paragraph_id", "para_id", "paragraph", "section", "chapter",
              "file", "path", "where")
REASON_KEYS = ("reason", "why", "note", "rationale", "basis", "说明", "依据")


def _pick(node, keys):
    for key in keys:
        for k, v in node.items():
            if str(k).lower() == key and isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _as_target(node):
    """识别 {"find": "...", "replace": "..."} 形式的工单显式改稿目标。"""
    if not isinstance(node, dict):
        return None
    find = _pick(node, FIND_KEYS)
    repl = _pick(node, REPLACE_KEYS)
    if not find or not repl or find == repl:
        return None
    scope = {k: v for k, v in node.items()
             if str(k).lower() in SCOPE_KEYS and isinstance(v, (str, int))}
    return {"find": find, "replace": repl,
            "reason": _pick(node, REASON_KEYS) or "",
            "scope": {str(k).lower(): str(v) for k, v in scope.items()}}


def parse_workorder(data):
    """宽松解析 organizer-edit-workorder.json。

    两类输入分开处理，互不混淆：
      * 结构化改稿目标（find/old + replace/new [+ section/paragraph_id]）-> targets，
        逐条机械落地并回报 applied / not_found / ambiguous；
      * 自然语言指令 -> instructions，能被"“A”改为“B”"解析的转为术语替换，
        其余登记为语义型指令（unparsed_instructions），不臆造语义。
    """
    out = {"canonical_terms": {}, "instructions": [], "chapter_order": [],
           "focus_terms": [], "raw_keys": [], "unparsed_instructions": [],
           "targets": []}
    if not isinstance(data, dict):
        return out

    def walk(node, top=False):
        target = _as_target(node)
        if target:
            out["targets"].append(target)
            return
        if isinstance(node, dict):
            for k, v in node.items():
                kl = str(k).lower()
                if top:
                    out["raw_keys"].append(str(k))
                if re.search(r"canonical|term_?map|术语统一|replacements", kl) and isinstance(v, dict):
                    for a, b in v.items():
                        if isinstance(a, str) and isinstance(b, str):
                            out["canonical_terms"][a] = b
                if re.search(r"chapter|order|章节顺序|sequence", kl) and isinstance(v, list):
                    for it in v:
                        if isinstance(it, str):
                            out["chapter_order"].append(it)
                        elif isinstance(it, dict):
                            for kk in ("path", "file", "name"):
                                if isinstance(it.get(kk), str):
                                    out["chapter_order"].append(it[kk])
                                    break
                if re.search(r"focus|关注术语|terms_of_interest", kl) and isinstance(v, list):
                    out["focus_terms"] += [x for x in v if isinstance(x, str)]
                if re.search(r"instruction|指令|edit|target|检查|check", kl) and isinstance(v, list):
                    for it in v:
                        if isinstance(it, str):
                            out["instructions"].append(it)
                        elif isinstance(it, dict):
                            if _as_target(it):
                                continue
                            for kk in ("instruction", "text", "detail", "description",
                                       "find", "old", "before"):
                                if isinstance(it.get(kk), str):
                                    out["instructions"].append(it[kk])
                                    break
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data, top=True)
    pairs = {}
    for s in out["instructions"]:
        hit = False
        for m in re.finditer(r"[“\"「]([^”\"」]{1,40})[”\"」]\s*(?:统一为|改为|替换为|→|->)\s*[“\"「]([^”\"」]{1,40})[”\"」]", s):
            pairs[m.group(1)] = m.group(2)
            hit = True
        for m in re.finditer(r"replace[:\s]+([^\s→]+)\s*(?:->|→|with)\s*(\S+)", s, re.I):
            pairs[m.group(1).strip("\"'")] = m.group(2).strip("\"'")
            hit = True
        if not hit:
            out["unparsed_instructions"].append(s)
    out["canonical_terms"].update({k: v for k, v in pairs.items() if k != v})
    out["canonical_terms"] = {k: v for k, v in out["canonical_terms"].items() if k and v}
    # 去重：同一对 find/replace 只执行一次，避免重复工单条目互相覆盖
    seen, unique = set(), []
    for t in out["targets"]:
        key = (t["find"], t["replace"], tuple(sorted(t["scope"].items())))
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    out["targets"] = unique
    return out


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


# --------------------------------------------------------------------------- #
# 抽取
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


def load_material(path, work_dir):
    """返回 (doc, error, meta)。meta 记录实际编码与是否发生解码回退。"""
    ext = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)
    meta = {"encoding": None, "fallback": False, "lossy": False}
    try:
        if ext == ".docx":
            return docx_io.load_docx(path, source_path=name), None, meta
        if ext == ".pdf":
            txt = pdf_text(path, work_dir)
            if txt is None:
                return None, "PDF 无可提取文本层（需要 OCR / pdf-text-tool）", meta
        elif ext in (".md", ".txt"):
            txt, meta = read_text_meta(path)
            if meta.get("error"):
                return None, "文本读取失败：%s" % meta["error"], meta
            if not txt.strip():
                return None, "文本为空（0 个可见字符）", meta
        else:
            return None, "不支持的类型: %s（旧版 .doc/.rtf 请先转 docx）" % ext, meta
        tmp = os.path.join(work_dir, "from_text", os.path.splitext(name)[0] + ".docx")
        docx_io.build_docx(docx_io.text_to_blocks(txt), tmp)
        return docx_io.load_docx(tmp, source_path=name), None, meta
    except docx_io.DocxError as exc:
        return None, str(exc), meta
    except Exception as exc:
        return None, "抽取异常: %s" % exc, meta


def merge_to_blocks(docs):
    """按原始顺序合并为 blocks，表格保持原位置，并给每个 block 记来源文件。"""
    blocks = []
    for d in docs:
        src = d.get("source_path") or os.path.basename(d.get("path") or "merged")
        done = set()
        for p in d["paragraphs"]:
            if p.get("in_table"):
                ti = p.get("table_index")
                if ti in done:
                    continue
                done.add(ti)
                t = next((x for x in d["tables"] if x["index"] == ti), None)
                if t and t["rows"]:
                    blocks.append({"kind": "table", "rows": t["rows"], "source": src})
                continue
            lvl = locate.style_level(p)
            if not lvl:
                hl, _ = locate.heading_number(p["text"])
                if hl and len(p["text"]) <= 80:
                    lvl = hl
            if lvl:
                blocks.append({"kind": "heading", "level": lvl, "text": p["text"],
                               "source": src})
            elif locate.caption_info(p):
                blocks.append({"kind": "caption", "text": p["text"], "source": src})
            else:
                blocks.append({"kind": "para", "text": p["text"], "source": src})
    return blocks


def assign_provenance(blocks, paragraphs):
    """把合并前的来源文件回填到重建后的段落（build_docx 每个 block 生成 1 段，
    表格 block 每单元格生成 1 段），使每条 finding 能指回原始章节文件。"""
    idx = 0
    for b in blocks:
        count = sum(len(r) for r in b.get("rows") or []) if b["kind"] == "table" else 1
        for _ in range(count):
            if idx < len(paragraphs):
                paragraphs[idx]["source_path"] = b.get("source") or "merged"
            idx += 1


def rebuild_base(blocks, work_dir):
    out = os.path.join(work_dir, "merged_base.docx")
    docx_io.build_docx(blocks, out)
    return docx_io.load_docx(out, source_path="merged_base")


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
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


def write_csv(path, findings):
    cols = ["id", "rule", "kind", "severity", "confidence", "section", "paragraph_id",
            "sentence_index", "anchor_quote", "summary", "suggested_fix",
            "auto_fixable", "needs_manual_confirmation"]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for f in findings:
            loc = f.get("location") or {}
            w.writerow([f.get("id"), f.get("rule"), f.get("kind"), f.get("severity"),
                        f.get("confidence"), loc.get("section"), loc.get("paragraph_id"),
                        loc.get("sentence_index"), loc.get("anchor_quote"), f.get("summary"),
                        f.get("suggested_fix"), f.get("auto_fixable"),
                        f.get("needs_manual_confirmation")])


KIND_CN = {"terminology": "术语与缩写", "symbol": "符号", "definition": "重复定义",
           "numbering": "编号", "reference": "图表/公式引用", "citation": "参考文献",
           "conclusion": "跨章节结论"}


def render_report(case_id, analysis, edits, sources, status, limits,
                  workorder_report=None, impact=None):
    f = analysis["findings"]
    lines = ["# 长文档一致性巡检报告", "",
             "- case_id：`%s`" % case_id, "- 状态：**%s**" % status,
             "- 检出：%d 条（high %d / medium %d / low %d）"
             % (len(f), sum(1 for x in f if x["severity"] == "high"),
                sum(1 for x in f if x["severity"] == "medium"),
                sum(1 for x in f if x["severity"] == "low")), ""]
    if limits:
        lines += ["> 限制：%s" % limits, ""]
    lines += ["## 覆盖", "", "| 检查族 | 已检查 | 发现 | 关键统计 |", "|-|-|-|-|"]
    for k, v in analysis["coverage"].items():
        stats = ", ".join("%s=%s" % (kk, vv) for kk, vv in v.items()
                          if kk not in ("checked", "findings") and not isinstance(vv, (list, dict)))
        lines.append("| %s | %s | %s | %s |" % (KIND_CN.get(k, k),
                                                "是" if v.get("checked") else "否",
                                                v.get("findings", 0), stats))
    lines += ["", "## 不一致清单（可逐条核到 段落号+句号+逐字引文）", ""]
    if not f:
        lines.append("本次规则集未检出不一致；这不等于全文无问题，语义判断仍需人工复核。")
    for x in f:
        loc = x.get("location") or {}
        lines += ["### %s [%s] %s" % (x["id"], x["severity"], x["summary"]),
                  "- 规则：`%s`" % x["rule"],
                  "- 位置：%s §%s / %s / 第 %s 句" % (loc.get("source_path") or "-",
                                                    loc.get("section"), loc.get("paragraph_id"),
                                                    loc.get("sentence_index")),
                  "- 原句：> %s" % (loc.get("sentence_quote") or loc.get("anchor_quote") or ""),
                  "- 原因：%s" % x.get("why", ""),
                  "- 处理：%s" % (x.get("suggested_fix") or "需人工确认"), ""]
        for ev in x.get("evidence") or []:
            if ev.get("quote"):
                lines.append("  - 证据 `%s`：%s" % (ev.get("paragraph_id") or ev.get("table"), ev["quote"]))
        if x.get("evidence"):
            lines.append("")
    lines += ["", "## 工单改稿目标执行情况", ""]
    if not workorder_report:
        lines.append("本次 workorder 未提供 find/replace 形式的显式改稿目标。")
    else:
        lines += ["| 目标 | 查找 | 替换 | 状态 | 命中段落 |", "|-|-|-|-|-|"]
        for r in workorder_report:
            hit = ", ".join("%s(§%s, %d 处)" % (x["paragraph_id"], x.get("section"),
                                               x["occurrences"])
                            for x in (r.get("paragraphs") or [])) or "-"
            lines.append("| %s | `%s` | `%s` | %s | %s |"
                         % (r["target_id"], r["find"], r["replace"], r["status"], hit))
    lines += ["", "## 改动影响面（同一旧写法仍出现的段落）", ""]
    if not impact:
        lines.append("未发现同一旧写法残留在其他段落。")
    for im in impact or []:
        lines.append("- `%s` 影响 %s（§%s）：%s" % (im["edit_id"], im["paragraph_id"],
                                                   im.get("section"), im["excerpt"]))
    lines += ["", "## 已自动修订", ""]
    if not edits:
        lines.append("本次没有满足自动修订边界（排版级/任务显式指定）的条目；所有问题转为人工处理。")
    for e in edits:
        lines.append("- `%s` %s §%s %s：`%s` → `%s`（依据：%s）"
                     % (e["edit_id"], e["paragraph_id"], e.get("section"),
                        e["rule"], e["before"], e["after"], e["basis"]))
    lines += ["", "## 输入来源", ""]
    for s in sources:
        lines.append("- `%s`（%s）：%s，段落 %s" % (s["path"], s["kind"], s["status"], s.get("paragraphs")))
    return "\n".join(lines) + "\n"


def self_check(payload, analysis, before_texts, verify_result, preview_info, required):
    errors, checks = [], {}
    checks["contract_declared"] = bool(required)
    checks["contract_fields_present"] = all(payload.get(k) is not None for k in required)
    missing = [k for k in required if payload.get(k) is None]
    if missing:
        errors.append("契约字段为空: %s" % missing)
    ids = [f["id"] for f in analysis["findings"]]
    checks["finding_ids_unique"] = len(ids) == len(set(ids))
    if not checks["finding_ids_unique"]:
        errors.append("finding id 重复")
    bad = []
    for f in analysis["findings"]:
        loc = f.get("location") or {}
        pid, q = loc.get("paragraph_id"), loc.get("anchor_quote")
        idx = int(pid[1:]) - 1 if pid and pid.startswith("P") else -1
        if idx < 0 or idx >= len(before_texts) or not q or q not in before_texts[idx]:
            bad.append(f["id"])
    checks["anchors_verbatim"] = not bad
    if bad:
        errors.append("锚点无法逐字复核: %s" % bad[:5])
    checks["revision_verified"] = bool(verify_result.get("ok"))
    if not verify_result.get("ok"):
        errors.extend(verify_result.get("errors") or [])
    checks["preview"] = preview_info.get("status")
    checks["severity_counts"] = analysis.get("severity_counts", {})
    return {"ok": not errors, "checks": checks, "errors": errors}


# --------------------------------------------------------------------------- #
def run(args):
    input_dir, work_dir, out_dir = (os.path.abspath(args.input),
                                    os.path.abspath(args.work),
                                    os.path.abspath(args.out))
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

    materials, missing = discover_materials(input_dir, case, os.path.dirname(case_path))
    labels = material_labels(materials, input_dir)
    if workorder["chapter_order"]:
        order = {os.path.basename(x): i for i, x in enumerate(workorder["chapter_order"])}
        materials.sort(key=lambda p: (order.get(os.path.basename(p), 999), natural_key(p)))

    sources, docs, errors, uncertainty = [], [], [], []
    for path in materials:
        label = labels.get(path) or os.path.basename(path)
        doc, err, meta = load_material(path, work_dir)
        if doc is not None:
            doc["source_path"] = label
        kind = os.path.splitext(path)[1].lstrip(".").lower()
        if doc is None:
            sources.append({"path": label, "kind": kind, "status": "unreadable",
                            "paragraphs": 0, "error": scrub_paths(err)})
            errors.append({"path": label, "error": scrub_paths(err)})
        else:
            entry = {"path": label, "kind": kind, "status": "parsed",
                     "paragraphs": len(doc["paragraphs"]), "error": None}
            if meta.get("encoding"):
                entry["encoding"] = meta["encoding"]
            sources.append(entry)
            docs.append(doc)
            if meta.get("fallback"):
                uncertainty.append({
                    "item": label, "where": "extraction",
                    "reason": "文件不是 UTF-8，已按 %s 解码；若正文出现乱码请转存为 UTF-8。"
                              % meta.get("encoding")})

    change_log = [{"action": "input_scan", "detail": {
        "case_json": os.path.basename(case_path) if os.path.exists(case_path) else None,
        "task_md": bool(task_text),
        "workorder": {"path": os.path.basename(wo_path) if wo_path else None,
                      "keys": workorder["raw_keys"],
                      "canonical_terms": workorder["canonical_terms"],
                      "instructions": len(workorder["instructions"]),
                      "targets": len(workorder["targets"]), "error": wo_err},
        "materials": [labels.get(m) or os.path.basename(m) for m in materials]}}]
    uncertainty.extend({"item": m, "reason": "case.json 声明的材料在 /input 中找不到",
                        "where": "input"} for m in missing)
    uncertainty.extend({"item": e["path"], "reason": e["error"], "where": "extraction"}
                       for e in errors)
    uncertainty.extend({"item": s, "where": "workorder",
                        "reason": "语义型指令无法机械落地；需模型/人工按清单改写，未自动改写。"}
                       for s in workorder["unparsed_instructions"])
    contract_note = None
    if not required:
        contract_note = ("case.json 未声明 output_contract.required；已按内置字段集输出，"
                         "无法核对组织方要求的字段清单。")
        uncertainty.append({"item": "output_contract", "where": "contract", "reason": contract_note})

    if not docs:
        payload = {
            "case_id": case_id, "status": "failed", "artifact": None, "artifact_format": None,
            "inconsistencies": [], "term_table": [], "symbol_table": [], "numbering_report": {},
            "coverage": {}, "revision_edits": [], "evidence": [], "sources": sources,
            "uncertainty": uncertainty or [{"item": "materials", "reason": "无可读材料", "where": "input"}],
            "change_log": change_log, "contract_gaps": [],
            "limits": "没有可读取的稿件材料，未产出修订稿；已列出每个失败文件的原因。",
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

    if len(docs) == 1:
        base, rebuild = docs[0], False
    else:
        blocks = merge_to_blocks(docs)
        base, rebuild = rebuild_base(blocks, work_dir), True
        assign_provenance(blocks, base["paragraphs"])
        uncertainty.append({"item": "格式", "where": "output",
                            "reason": "多份来源已合并重建为单一 docx：标题层级、正文与表格顺序保留，"
                                      "原始分页/页眉页脚/复杂域不保留。"})
    # 巡检、修订、自检统一以最终交付的 docx 模型为准，保证段落号与产物一致
    ps, tbls = base["paragraphs"], base["tables"]
    sections = locate.assign_sections(ps)
    analysis = consistency.Analyzer(
        ps, tbls, sections,
        options={"canonical_terms": workorder["canonical_terms"],
                 "focus_terms": workorder["focus_terms"]}).run()

    before_texts = [p["text"] for p in ps]
    # 工单显式目标优先执行（任务要求），其后才跑排版级术语归一，避免同段互相覆盖
    target_rev = revise.apply_target_edits(base, workorder["targets"])
    rev = revise.apply_edits(base, analysis["findings"])
    for i, e in enumerate(target_rev["edits"] + rev["edits"], start=1):
        e["edit_id"] = "E%03d" % i
    edits = target_rev["edits"] + rev["edits"]
    skipped = target_rev["skipped"] + rev["skipped"]
    rev_path = os.path.join(out_dir, "revision.docx")
    docx_io.save_docx(base, rev_path)
    verify_result = revise.verify(before_texts, rev_path, edits)
    impact = revise.edit_impact(base, edits)

    with open(os.path.join(out_dir, "revision.md"), "w", encoding="utf-8") as fh:
        fh.write(revise.render_markdown_from_doc(base))
    with open(os.path.join(out_dir, "revision.diff"), "w", encoding="utf-8") as fh:
        fh.write(revise.unified_diff(before_texts, [p["text"] for p in ps],
                                     os.path.splitext(sources[0]["path"])[0]))

    prev = preview.render_pdf(rev_path, os.path.join(out_dir, "preview.pdf"))
    preview.render_html(docx_io.docx_text(rev_path)[0],
                        os.path.join(out_dir, "preview.html"), title=case_id)
    write_csv(os.path.join(out_dir, "inconsistencies.csv"), analysis["findings"])

    status = "partial" if (errors or rebuild or skipped or
                           prev["status"] != "rendered") else "success"
    limits = []
    if errors:
        limits.append("%d 个材料不可读，未纳入巡检（见 uncertainty）。" % len(errors))
    if rebuild:
        limits.append("多源合并重建稿件，原始分页/页眉页脚/复杂域未保留。")
    if skipped:
        limits.append("%d 条自动修订被跳过（定位不到原文或超出自动修改边界）。" % len(skipped))
    if prev["status"] != "rendered":
        limits.append("PDF 预览不可用：%s；已提供 preview.html。" % prev["reason"])
    if workorder["unparsed_instructions"]:
        limits.append("%d 条运行工单指令为语义型，未自动改写，已列入 uncertainty。"
                      % len(workorder["unparsed_instructions"]))
    if contract_note:
        limits.append(contract_note)
    limits_s = " ".join(limits)

    numbering_report = {
        "headings": [{"paragraph_id": p["id"], "section": p["section"],
                      "level": p["heading_level"], "text": p["text"].strip()[:80]}
                     for p in ps if p.get("is_heading")],
        "captions": analysis["caption_table"], "equations": analysis["equation_list"],
        "findings": [f["id"] for f in analysis["findings"] if f["kind"] == "numbering"]}
    evidence = [{"finding_id": f["id"], "rule": f["rule"],
                 "paragraph_id": (f.get("location") or {}).get("paragraph_id"),
                 "section": (f.get("location") or {}).get("section"),
                 "quote": (f.get("location") or {}).get("anchor_quote"),
                 "source_path": (f.get("location") or {}).get("source_path")}
                for f in analysis["findings"]]
    payload = {
        "case_id": case_id, "status": status,
        "artifact": "revision.docx", "artifact_format": "docx",
        "outputs": {"docx": "revision.docx", "markdown": "revision.md",
                    "csv": "inconsistencies.csv", "report": "consistency_report.md",
                    "preview_pdf": "preview.pdf" if prev["status"] == "rendered" else None,
                    "preview_html": "preview.html", "diff": "revision.diff"},
        "parsed": {"materials": sources, "paragraphs": len(ps), "sections": sections,
                   "tables": len(tbls), "chars": sum(len(p["text"]) for p in ps),
                   "task_excerpt": task_text.strip()[:400]},
        "inconsistencies": analysis["findings"],
        "fields": {"term_table": analysis["term_table"], "symbol_table": analysis["symbol_table"]},
        "term_table": analysis["term_table"], "symbol_table": analysis["symbol_table"],
        "numbering_report": numbering_report, "coverage": analysis["coverage"],
        "severity_counts": analysis["severity_counts"],
        "revision_edits": edits, "skipped_edits": skipped,
        "deduped_edits": rev["deduped"],
        "workorder_execution": target_rev["report"],
        "edit_impact": impact,
        "evidence": evidence, "sources": sources, "uncertainty": uncertainty,
        "change_log": change_log + [{"action": "auto_revision", "detail": {
            "workorder_targets_applied": sum(1 for r in target_rev["report"]
                                             if r["status"] == "applied"),
            "workorder_targets_not_found": sum(1 for r in target_rev["report"]
                                               if r["status"] == "not_found"),
            "applied": len(edits), "paragraphs_touched": rev["paragraphs_touched"],
            "skipped": len(skipped), "deduped": len(rev["deduped"])}}],
        "limits": limits_s or "无。",
        "preview": {"status": prev["status"], "reason": prev.get("reason"),
                    "pdf": "preview.pdf" if prev["status"] == "rendered" else None,
                    "html": "preview.html"},
        "workorder": {"path": os.path.basename(wo_path) if wo_path else None,
                      "canonical_terms": workorder["canonical_terms"],
                      "instructions": workorder["instructions"],
                      "raw_keys": workorder["raw_keys"]},
    }
    final, gaps = contract_payload(payload, required)
    final["contract_gaps"] = gaps
    if gaps:
        uncertainty.append({"item": "output_contract", "where": "contract",
                            "reason": "契约字段语义未知，保留 null：%s" % gaps})
    final["uncertainty"] = uncertainty
    sc = self_check(final, analysis, before_texts, verify_result, prev, required)
    final["self_check"] = sc

    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(final, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "consistency_report.md"), "w", encoding="utf-8") as fh:
        fh.write(render_report(case_id, analysis, edits, sources, status, limits_s,
                               target_rev["report"], impact))
    with open(os.path.join(work_dir, "doc.json"), "w", encoding="utf-8") as fh:
        json.dump({"case_id": case_id, "sections": sections,
                   "paragraphs": [{"id": p["id"], "section": p["section"],
                                   "heading_level": p["heading_level"],
                                   "in_table": p.get("in_table"),
                                   "source_path": p.get("source_path"),
                                   "text": p["text"]} for p in ps],
                   "tables": tbls}, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(work_dir, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(analysis, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(work_dir, "self_check.json"), "w", encoding="utf-8") as fh:
        json.dump(sc, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"case_id": case_id, "status": status,
                      "findings": len(analysis["findings"]), "edits": len(edits),
                      "self_check_ok": sc["ok"], "preview": prev["status"]},
                     ensure_ascii=False))
    return 0


def check(outputs):
    result, err = read_json(os.path.join(outputs, "result.json"))
    problems = []
    if result is None:
        print("FAIL - result.json 不可读: %s" % err)
        return 1
    for k in ("case_id", "status", "inconsistencies", "sources", "uncertainty", "change_log"):
        if k not in result:
            problems.append("缺少字段 %s" % k)
    for name in ("revision.docx", "revision.md", "inconsistencies.csv", "consistency_report.md"):
        if not os.path.exists(os.path.join(outputs, name)):
            problems.append("缺少产物 %s" % name)
    docx_path = os.path.join(outputs, "revision.docx")
    if os.path.exists(docx_path):
        if not docx_io.docx_info(docx_path)["ok"]:
            problems.append("revision.docx 不可解析")
        texts, ok, _ = docx_io.docx_text(docx_path)
        if not ok or not any(t.strip() for t in texts):
            problems.append("revision.docx 无正文")
    if problems:
        print("FAIL")
        for p in problems:
            print(" -", p)
        return 1
    print("PASS")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="学位论文长文档一致性巡检与修订")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--case", default=None)
    ap.add_argument("--workorder", default=None)
    ap.add_argument("--check", default=None, help="只检查已有输出目录")
    a = ap.parse_args(argv)
    return check(os.path.abspath(a.check)) if a.check else run(a)


if __name__ == "__main__":
    sys.exit(main())
