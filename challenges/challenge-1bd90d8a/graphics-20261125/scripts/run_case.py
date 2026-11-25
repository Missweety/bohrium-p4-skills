#!/usr/bin/env python3
"""run_case.py - one command from /input to /app/output.

Reads the evaluator case, finds the data (or SVG) in the materials, profiles it, plans
the chart, builds the spec, applies requested edits, renders SVG/PNG/PDF, writes the
caption and the element->source-row map, self-checks, and emits result.json with every
contract field. A failure never produces an empty or fabricated answer: the reason,
the files already produced and the uncertainty are recorded instead.

Usage:
  python3 scripts/run_case.py --case /input/case.json --materials /input \
      --work /app/work --out /app/output

Optional overrides (only needed when the case text is ambiguous):
  --x COL --y COL --group COL --intent auto|bar|grouped_bar|line|scatter|hist|box|heatmap|panel
  --error sd|sem|ci95|none   --title "..."   --contract "a,b,c"   --no-raster

Exit code is 0 whenever result.json was written (including an honest blocked/partial),
except a fatal empty-panel result, which exits 1 while still writing result.json; 2 means
not even result.json could be written.
"""
import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import kernel  # noqa: E402
import tableio  # noqa: E402

DATA_EXT = (".csv", ".tsv", ".txt", ".tab", ".xlsx", ".xlsm")
SVG_EXT = (".svg",)
SKIP_DIRS = {"__pycache__", ".git", ".svn", ".ipynb_checkpoints", ".trae", ".vscode",
             "node_modules", ".cache", "work", "output"}
MAX_SCAN_FILES = 400
VALID_TYPES = ("auto", "bar", "grouped_bar", "line", "scatter", "hist", "box",
               "heatmap", "panel")
TYPE_MAP = {
    "bar": "bar", "bar chart": "bar", "column": "bar", "柱": "bar", "柱状": "bar",
    "柱状图": "bar", "柱形图": "bar", "条形图": "bar",
    "grouped bar": "grouped_bar", "grouped_bar": "grouped_bar", "groupedbar": "grouped_bar",
    "分组柱状图": "grouped_bar", "分组柱形图": "grouped_bar", "分组柱": "grouped_bar",
    "line": "line", "line chart": "line", "折线": "line", "折线图": "line", "曲线图": "line",
    "scatter": "scatter", "scatter plot": "scatter", "散点": "scatter", "散点图": "scatter",
    "hist": "hist", "histogram": "hist", "直方图": "hist", "分布图": "hist",
    "box": "box", "boxplot": "box", "box plot": "box", "箱线图": "box", "箱图": "box",
    "heatmap": "heatmap", "heat map": "heatmap", "热图": "heatmap", "热力图": "heatmap",
    "panel": "panel", "multi-panel": "panel", "多面板": "panel", "组合图": "panel",
}
TYPE_RE = "|".join(sorted(TYPE_MAP, key=len, reverse=True))
EDIT_VERBS = re.compile(r"(修改|编辑|改为|改成|换成|调整|重画|重绘|添加标注|高亮|"
                        r"\bedit\b|\bchange\b|\bretitle\b|\bmodify\b|\bupdate\b)",
                        re.I)


# ------------------------------------------------------------------ small helpers
def sha256_file(path):
    try:
        return tableio.sha256_file(path)
    except OSError:
        return ""


def panel_marks(p):
    ct = p.get("chart_type")
    if ct in ("bar", "grouped_bar"):
        return sum(len(s.get("values") or []) for s in p.get("series", []))
    if ct in ("line", "scatter"):
        return len(p.get("points") or [])
    if ct == "hist":
        return sum(1 for b in p.get("bins", []) if (b.get("count") or 0) > 0)
    if ct == "box":
        return len(p.get("boxes") or [])
    if ct == "heatmap":
        return len(p.get("cells") or [])
    return 0


def empty_panels(spec):
    return [(p.get("id") or "?") for p in spec.get("panels") or []
            if panel_marks(p) == 0]


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def write_json(path, payload):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)


def copy_file(src, dst):
    if not src or not os.path.exists(src):
        return False
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    shutil.copyfile(src, dst)
    return True


def norm_key(text):
    return re.sub(r"[^0-9a-z]", "", str(text).lower())


def norm_type(value):
    key = str(value or "").strip().lower().replace("_", " ")
    if key in TYPE_MAP:
        return TYPE_MAP[key]
    return TYPE_MAP.get(key.replace(" ", ""), "")


def norm_error(value):
    key = re.sub(r"[^0-9a-z]", "", str(value or "").lower())
    if key in ("sd", "std", "stddev", "标准差"):
        return "sd"
    if key in ("sem", "se", "stderr", "标准误"):
        return "sem"
    if key in ("ci95", "ci", "95ci", "置信区间"):
        return "ci95"
    if key in ("none", "no", "off", "无", "无误差线"):
        return "none"
    return ""


def discover_files(root):
    found = []
    if not root or not os.path.isdir(root):
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirnames[:] = sorted(d for d in dirnames
                             if d not in SKIP_DIRS and not d.startswith("."))
        if depth >= 3:
            dirnames[:] = []
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            found.append(os.path.join(dirpath, name))
            if len(found) >= MAX_SCAN_FILES:
                return found
    return found


def unique(paths):
    seen, out = set(), []
    for p in paths:
        ap = os.path.abspath(p)
        if ap not in seen:
            seen.add(ap)
            out.append(p)
    return out


# ------------------------------------------------------------------ case parsing
def material_paths(case_doc, case_raw, materials_root):
    paths = []
    for item in case_doc.get("materials") or []:
        p = item.get("path") if isinstance(item, dict) else item
        if not p:
            continue
        if not os.path.isabs(p):
            p = os.path.join(materials_root, p)
        paths.append(p)
    for key in ("data", "data_files", "files", "inputs", "source_svg", "svg_path",
                "figure_svg", "input"):
        v = case_raw.get(key)
        vals = v if isinstance(v, list) else [v]
        for x in vals:
            if isinstance(x, dict):
                x = x.get("path") or x.get("file") or x.get("name")
            if isinstance(x, str) and x.strip():
                p = x if os.path.isabs(x) else os.path.join(materials_root, x)
                paths.append(p)
    return paths


def pick_data(candidates, task_text):
    """Return (path, table, audit_rows, reason). Only readable tables are eligible."""
    scored = []
    for path in candidates:
        ext = os.path.splitext(path)[1].lower()
        if ext not in DATA_EXT:
            continue
        try:
            table = tableio.read_any(path)
        except Exception as exc:  # noqa: BLE001
            scored.append((path, None, "unreadable: %s" % exc, -1))
            continue
        numeric = sum(1 for r in table["rows"] for c in r
                      if tableio.to_number(c) is not None)
        if numeric == 0:
            scored.append((path, None, "no numeric cells", -1))
            continue
        score = numeric + table["rows_total"] * max(table["columns"], 1)
        scored.append((path, table, "%d rows x %d cols, %d numeric cells"
                       % (table["rows_total"], table["columns"], numeric), score))
    usable = [s for s in scored if s[1] is not None]
    if not usable:
        audit = [{"file": os.path.basename(p), "reason": why} for p, _, why, _ in scored]
        return "", None, audit, "no readable numeric table"
    low = (task_text or "").lower()
    named = [s for s in usable if os.path.basename(s[0]).lower() in low]
    pool = named or usable
    pool.sort(key=lambda s: (-s[3], len(os.path.basename(s[0])), os.path.basename(s[0])))
    chosen = pool[0]
    audit = [{"file": os.path.basename(p), "reason": why, "score": score}
             for p, _, why, score in scored]
    reason = "task names it" if named else "highest numeric coverage"
    return chosen[0], chosen[1], audit, reason


def case_options(case_raw, case_doc):
    hints = case_doc.get("hints") or {}
    merged = dict(case_raw)
    merged.update({k: v for k, v in hints.items() if v not in (None, "")})

    def first(*keys):
        for key in keys:
            for src in (merged, case_raw):
                v = src.get(key) if isinstance(src, dict) else None
                if isinstance(v, str) and v.strip():
                    return v.strip()
        return ""

    return {
        "x": first("x", "x_column", "x_field", "xcol"),
        "y": first("y", "y_column", "y_field", "value", "metric", "ycol"),
        "group": first("group", "group_by", "series", "hue", "color", "facet"),
        "intent": norm_type(first("chart_type", "figure_type", "intent", "figure")),
        "error": norm_error(first("error", "error_type", "error_bars", "errorbar")),
        "title": first("title", "figure_title", "caption_title"),
        "task_text": case_doc.get("task_text") or "",
    }


def edit_context(case_raw, task_text):
    explicit = False
    for key in ("edit_instructions", "edits", "edit_ops", "edit"):
        if isinstance(case_raw, dict) and case_raw.get(key):
            explicit = True
    text = task_text or ""
    return explicit or bool(EDIT_VERBS.search(text))


def _flatten_ops(value, ops):
    if value is None:
        return
    if isinstance(value, dict):
        for key, v in value.items():
            k = norm_key(key)
            if k in ("title", "figuretitle"):
                ops["title"] = str(v)
            elif k in ("charttype", "figuretype", "type"):
                t = norm_type(v)
                if t:
                    ops["chart_type"] = t
            elif k in ("ymin", "axismin", "yaxismin", "min"):
                ops["y_min"] = float(v)
            elif k in ("ymax", "axismax", "yaxismax", "max"):
                ops["y_max"] = float(v)
            elif k in ("annotation", "annotations", "note", "notes"):
                vals = v if isinstance(v, list) else [v]
                ops["annotations"] += [str(x) for x in vals if str(x).strip()]
            elif k in ("highlight", "highlights"):
                vals = v if isinstance(v, list) else [v]
                ops["highlights"] += [str(x) for x in vals if str(x).strip()]
            elif k in ("settext", "replace", "rename"):
                if isinstance(v, dict):
                    ops["set_text"] += ["%s=%s" % (a, b) for a, b in v.items()]
                elif isinstance(v, list):
                    ops["set_text"] += [str(x) for x in v if "=" in str(x)]
                elif isinstance(v, str) and "=" in v:
                    ops["set_text"].append(v)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                parse_natural_language(item, ops)
            else:
                _flatten_ops(item, ops)
    elif isinstance(value, str):
        parse_natural_language(value, ops)


def parse_natural_language(text, ops):
    if not text:
        return
    m = re.search(r"(?:标题|图题|title)\s*(?:改为|改成|设为|设置为|为|:|：|to|is)\s*"
                  r"[\"“'‘]?(.+?)[\"”'’]?\s*(?:[，,。；;\n]|$)", text, re.I)
    if m:
        candidate = m.group(1).strip()
        if candidate and not re.fullmatch(TYPE_RE, candidate.lower()) and not ops.get("title"):
            ops["title"] = candidate
    m = re.search(r"(?:改为|改成|换成|转成|画成|绘制为|chart\s*type\s*[:：]?\s*|"
                  r"type\s*[:：]\s*)(%s)" % TYPE_RE, text, re.I)
    if m:
        t = norm_type(m.group(1))
        if t and not ops.get("chart_type"):
            ops["chart_type"] = t
    m = re.search(r"(?:y\s*轴|纵轴|y-axis|y\s*axis)\D{0,14}"
                  r"(-?\d+(?:\.\d+)?)\s*(?:到|至|~|-|to)\s*(-?\d+(?:\.\d+)?)", text, re.I)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if hi > lo and ops.get("y_min") is None and ops.get("y_max") is None:
            ops["y_min"], ops["y_max"] = lo, hi
    m = re.search(r"(?:添加|增加|加)?\s*(?:标注|注释|annotation|annotate)\s*[:：]\s*"
                  r"[\"“]?(.+?)[\"”]?\s*(?:[，,。；;\n]|$)", text, re.I)
    if m:
        ops["annotations"].append(m.group(1).strip())
    for m in re.finditer(r"(?:高亮|突出显示|highlight)\s*(?:标出)?\s*[:：]?\s*"
                         r"[\"“]?([^\"”，,。；;\s]+)", text, re.I):
        label = m.group(1).strip()
        if label:
            ops["highlights"].append(label)
    m = re.search(r"(?:把|将)\s*[\"“]?([^\"”]{1,30}?)[\"”]?\s*"
                  r"(?:改为|改成|替换为|替换成)\s*[\"“]?([^\"”\n。；;，,]{1,60})[\"”]?", text)
    if m:
        old, new = m.group(1).strip(), m.group(2).strip()
        if (old and new and not re.fullmatch(TYPE_RE, old.lower())
                and not re.search(r"标题|图题|轴|范围|类型|颜色", old)):
            ops["set_text"].append("%s=%s" % (old, new))


def edit_ops(case_raw):
    ops = {"title": "", "chart_type": "", "y_min": None, "y_max": None,
           "annotations": [], "highlights": [], "set_text": []}
    for key in ("edit_instructions", "edits", "edit_ops", "edit"):
        if isinstance(case_raw, dict) and case_raw.get(key):
            _flatten_ops(case_raw[key], ops)
    text = (case_raw.get("task") or case_raw.get("task_text")
            or case_raw.get("instruction") or "")
    if isinstance(text, list):
        text = "\n".join(str(x) for x in text)
    if text and edit_context(case_raw, text):
        parse_natural_language(text, ops)
    ops["annotations"] = list(dict.fromkeys(a for a in ops["annotations"] if a))
    ops["highlights"] = list(dict.fromkeys(h for h in ops["highlights"] if h))
    ops["set_text"] = list(dict.fromkeys(s for s in ops["set_text"] if "=" in s))
    return ops


def has_ops(ops):
    return bool(ops.get("title") or ops.get("chart_type") or ops.get("y_min") is not None
                or ops.get("y_max") is not None or ops.get("annotations")
                or ops.get("highlights") or ops.get("set_text"))


# ------------------------------------------------------------------ process steps
class Runner:
    def __init__(self, work):
        self.work = work
        self.log = []

    def call(self, script, args, timeout=300):
        cmd = [sys.executable, os.path.join(HERE, script)] + [str(x) for x in args]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            rc, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired:
            rc, out, err = 124, "", "timeout after %ss" % timeout
        except Exception as exc:  # noqa: BLE001
            rc, out, err = 125, "", "spawn failed: %s" % exc
        self.log.append({"step": script, "args": [os.path.basename(str(x)) for x in args],
                         "exit": rc, "stdout": out.strip()[-2000:],
                         "stderr": err.strip()[-2000:]})
        return rc, (out + err).strip()

    def flush(self):
        write_json(os.path.join(self.work, "run_log.json"), self.log)
        with open(os.path.join(self.work, "run_log.txt"), "w", encoding="utf-8") as fh:
            for item in self.log:
                fh.write("$ %s %s\n[exit %d]\n%s\n%s\n\n"
                         % (item["step"], " ".join(item["args"]), item["exit"],
                            item["stdout"], item["stderr"]))


# ------------------------------------------------------------------ draft builders
def base_draft(case_doc, case_raw, case_id):
    fields = case_doc.get("contract_fields") or list(kernel.DEFAULT_CONTRACT)
    return {
        "case_id": case_id, "status": "partial",
        "contract_fields": fields,
        "sources": [], "limits": [], "uncertainty": [],
        "change_log": "", "change_details": {},
        "metrics": {}, "input_files": [], "code_path": "scripts/run_case.py",
    }


def summarize_element_map(payload):
    els = (payload or {}).get("elements") or []
    return {
        "file": "element_map.json",
        "counts": (payload or {}).get("counts", {}),
        "sha256": (payload or {}).get("sha256", ""),
        "sample": els[:8],
    }


def svg_elements(text):
    els = []
    for i, m in enumerate(re.finditer(r"<text\b([^>]*)>(.*?)</text>", text, re.S), start=1):
        attrs = m.group(1)
        tid = re.search(r'\bid="([^"]+)"', attrs)
        label = re.sub(r"<[^>]+>", "", m.group(2))
        label = html.unescape(label).strip()
        if not label:
            continue
        els.append({"element": "svg:%s" % (tid.group(1) if tid else "text:%d" % i),
                    "kind": "text", "panel": "", "text": label,
                    "source": "figure.svg#%s" % (tid.group(1) if tid else "text:%d" % i),
                    "source_rows": []})
    return els


# ------------------------------------------------------------------ SVG edit flow
def svg_edit_flow(runner, svg_path, ops, out, work, draft, task_text):
    copy_file(svg_path, os.path.join(out, "source_figure.svg"))
    args = ["--svg", svg_path, "--out", out]
    if ops.get("title"):
        args += ["--title", ops["title"]]
    for a in ops.get("annotations") or []:
        args += ["--annotate", a]
    for h_ in ops.get("highlights") or []:
        args += ["--highlight", h_]
    for s in ops.get("set_text") or []:
        args += ["--set-text", s]
    rc, msg = runner.call("edit_figure.py", ["svg"] + args)
    log = read_json(os.path.join(out, "edit_log.json"), {}) or {}
    if not (log.get("changes") or log.get("warnings")):
        log.setdefault("warnings", []).append(
            "no edit instruction matched the SVG; file copied with hashes recorded")
        write_json(os.path.join(out, "edit_log.json"), log)
    unsupported = [k for k in ("chart_type", "y_min", "y_max") if ops.get(k)]
    if unsupported:
        draft["limits"].append(
            "SVG edit mode cannot re-map %s: only title, annotation, highlight and "
            "text replacement are structure-preserving; rerun with a data table to "
            "change chart type or axis range" % ", ".join(unsupported))
        log.setdefault("warnings", []).append("unsupported in svg mode: %s"
                                              % ", ".join(unsupported))
        write_json(os.path.join(out, "edit_log.json"), log)

    text = ""
    try:
        text = open(os.path.join(out, "figure.svg"), encoding="utf-8", errors="replace").read()
    except OSError:
        pass
    els = svg_elements(text)
    payload = {"chart": "svg-edit", "title": ops.get("title") or os.path.basename(svg_path),
               "source": os.path.basename(svg_path), "source_sha256": sha256_file(svg_path),
               "elements": els,
               "counts": {"total": len(els), "data": 0}}
    payload["sha256"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    write_json(os.path.join(out, "element_map.json"), payload)

    changes = log.get("changes") or []
    caption = ("# %s\n\n"
               "图型：在已有 SVG（`%s`）上做结构保留编辑，未重新绘制。\n\n"
               "编辑内容：%s。共 %d 处修改，SVG 结构可逆性校验=%s；前后 sha256 已记录在 "
               "`edit_log.json`。\n\n"
               "来源与可核验性：源文件 sha256 %s…，输出 sha256 %s…；文本节点由源 SVG "
               "保留，图元—文本对照见 `element_map.json`（%d 个文本图元）。\n\n"
               "限制：SVG 编辑模式不读取原始数据表，因此不提供逐行数据映射、误差线口径、"
               "样本量统计或 PNG/PDF 重新导出；这些需要数据表才能复算。\n"
               % (ops.get("title") or "Edited figure", os.path.basename(svg_path),
                  "；".join("%s→%s" % (c.get("before") if c.get("before") is not None else "（新增）",
                                       c.get("after"))
                           for c in changes[:6]) or "无（未匹配到编辑目标）",
                  len(changes), log.get("structure_preserved"),
                  (payload["source_sha256"] or "")[:12],
                  (log.get("output_sha256") or "")[:12], len(els)))
    with open(os.path.join(out, "caption.md"), "w", encoding="utf-8") as fh:
        fh.write(caption)

    rc, msg = runner.call("check_figure.py", ["--svg-only", "--work", work, "--out", out])
    selfcheck = read_json(os.path.join(out, "selfcheck.json"), {}) or {}
    draft.update({
        "status": "partial" if selfcheck.get("verdict") != "PASS" else "partial",
        "title": ops.get("title") or os.path.basename(svg_path),
        "chart_type": "svg-edit", "panel_count": 1,
        "caption": caption,
        "element_map": summarize_element_map(payload),
        "selfcheck": {k: selfcheck.get(k) for k in ("verdict", "errors", "warnings")},
        "change_log": "SVG edit on %s: %d change(s), structure_preserved=%s"
                      % (os.path.basename(svg_path), len(changes),
                         log.get("structure_preserved")),
        "change_details": {"mode": "svg", "changes": changes,
                           "warnings": log.get("warnings") or []},
        "metrics": {"svg_text_elements": len(els), "edit_changes": len(changes),
                    "edit_warnings": len(log.get("warnings") or [])},
        "sources": [{"file": os.path.basename(svg_path), "sha256": payload["source_sha256"],
                     "bytes": os.path.getsize(svg_path), "role": "input_svg"}],
        "limits": draft["limits"] + ["no raster re-export in SVG edit mode"],
        "uncertainty": draft["uncertainty"] + ([] if selfcheck.get("verdict") == "PASS" else
                                               ["selfcheck: %s"
                                                % (selfcheck.get("errors") or [])]),
    })
    if not task_text:
        draft["uncertainty"].append("no task text in case.json; edits taken from structured "
                                    "fields only")
    return draft


# ------------------------------------------------------------------ main flow
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--materials", default="/input")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--title", default="")
    ap.add_argument("--x", default="")
    ap.add_argument("--y", default="")
    ap.add_argument("--group", default="")
    ap.add_argument("--intent", default="")
    ap.add_argument("--error", default="")
    ap.add_argument("--contract", default="")
    ap.add_argument("--no-raster", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    runner = Runner(a.work)

    # ---- case + contract
    ns = argparse.Namespace(case=a.case, materials=a.materials, work=a.work,
                            contract=a.contract)
    try:
        kernel.cmd_init(ns)
    except SystemExit:
        pass
    case_doc = read_json(os.path.join(a.work, "case.json"), {}) or {}
    info = kernel.read_case(a.case)
    case_raw = info.get("case") or {}
    case_id = case_doc.get("case_id") or "local-unknown"
    draft = base_draft(case_doc, case_raw, case_id)
    if case_doc.get("blocked"):
        draft["uncertainty"].append("case.json: %s" % case_doc["blocked"])
    task_text = case_doc.get("task_text") or ""
    if not task_text:
        for name in ("task.md", "TASK.md", "task.txt", "workorder.md"):
            p = os.path.join(a.materials, name)
            if os.path.exists(p):
                try:
                    task_text = open(p, encoding="utf-8", errors="replace").read()
                except OSError:
                    task_text = ""
                if task_text:
                    break
    if task_text:
        with open(os.path.join(a.work, "task.md"), "w", encoding="utf-8") as fh:
            fh.write(task_text)

    # ---- discover inputs
    files = unique(discover_files(a.materials) + material_paths(case_doc, case_raw,
                                                                a.materials))
    data_files = [p for p in files if os.path.splitext(p)[1].lower() in DATA_EXT
                  and os.path.exists(p)]
    svg_files = [p for p in files if os.path.splitext(p)[1].lower() in SVG_EXT
                 and os.path.exists(p)]
    draft["input_files"] = [{"file": os.path.basename(p), "bytes": os.path.getsize(p)}
                            for p in files if os.path.isfile(p)]
    ops = edit_ops(case_raw)
    editing = edit_context(case_raw, task_text) or has_ops(ops)
    mode_hint = str(case_raw.get("mode", "") if isinstance(case_raw, dict) else "").lower()

    def blocked(reason, extra_limits=(), fatal=False):
        draft["status"] = "blocked"
        if fatal:
            draft["fatal"] = True
            draft["fatal_error"] = reason
        draft["caption"] = ("# 无法生成图表\n\n原因：%s。\n\n已检查的输入：%s。\n"
                            "未伪造任何数据、统计量或图件；请提供可解析的 CSV/TSV/XLSX "
                            "数据表（或要编辑的 SVG）后重跑。\n"
                            % (reason, ", ".join(os.path.basename(p) for p in files) or "无"))
        draft["limits"] = draft["limits"] + list(extra_limits)
        draft["uncertainty"].append(reason)
        draft["change_log"] = "blocked: %s" % reason
        draft["metrics"] = {"input_files": len(files), "data_files": 0}
        return finish(runner, draft, a, case_doc)

    if not data_files and svg_files:
        if not editing:
            draft["limits"].append("materials contain an SVG but no data table; "
                                   "treated as an edit request")
        return finish(runner, draft, a, case_doc, flow="svg",
                      svg_path=svg_files[0], ops=ops, task_text=task_text)
    if not data_files:
        return blocked("materials contain no readable CSV/TSV/XLSX data table")
    if svg_files and "svg" in mode_hint and editing:
        return finish(runner, draft, a, case_doc, flow="svg",
                      svg_path=svg_files[0], ops=ops, task_text=task_text)

    # ---- choose table
    data_path, table, audit, why = pick_data(data_files, task_text)
    if not data_path:
        return blocked("no data file has parseable numeric cells (%s)"
                       % "; ".join("%s: %s" % (r["file"], r["reason"]) for r in audit))
    draft["input_files"].append({"file": os.path.basename(data_path),
                                 "role": "chosen_data", "reason": why,
                                 "candidates": audit})
    if len([x for x in audit if x.get("score", -1) >= 0]) > 1:
        draft["uncertainty"].append(
            "multiple data tables found; chose %s (%s). Others: %s"
            % (os.path.basename(data_path), why,
               ", ".join(x["file"] for x in audit if x.get("score", -1) >= 0
                         and x["file"] != os.path.basename(data_path))))
    normalized = os.path.join(a.work, "normalized.csv")
    tableio.write_normalized_csv(table, normalized)
    snapshot = {
        "source": os.path.basename(data_path), "source_sha256": table["sha256"],
        "source_bytes": table["bytes"], "encoding": table["encoding"],
        "delimiter": table["delimiter"], "sheet": table.get("sheet", ""),
        "rows": table["rows_total"], "columns": table["columns"],
        "header": table["header"], "normalized": "normalized.csv",
        "normalized_sha256": sha256_file(normalized),
        "header_row": 1, "note": "normalized snapshot keeps every source row; "
                                 "row number N in the map = data row N-1",
    }
    write_json(os.path.join(a.out, "data_snapshot.json"), snapshot)

    # ---- profile
    rc, msg = runner.call("profile_data.py", ["--input", data_path, "--out", a.work])
    copy_file(os.path.join(a.work, "data_profile.json"),
              os.path.join(a.out, "data_profile.json"))
    profile = read_json(os.path.join(a.out, "data_profile.json"), {}) or {}
    if profile.get("warnings"):
        draft["uncertainty"] += ["profile: %s" % w for w in profile["warnings"][:8]]

    # ---- plan
    opts = case_options(case_raw, case_doc)
    x = a.x or opts["x"]
    y = a.y or opts["y"]
    group = a.group or opts["group"]
    error = norm_error(a.error) or opts["error"] or "sd"
    intent = norm_type(a.intent) or opts["intent"] or "auto"
    if ops.get("chart_type"):
        intent = ops["chart_type"]
    intent = intent if intent in VALID_TYPES else "auto"
    base = ["--input", data_path, "--out", a.work, "--error", error]
    if task_text:
        base += ["--hint", os.path.join(a.work, "task.md")]
    plan_args = list(base)
    if x:
        plan_args += ["--x", x]
    if y:
        plan_args += ["--y", y]
    if group:
        plan_args += ["--group", group]
    if intent != "auto":
        plan_args += ["--intent", intent]
    rc, msg = runner.call("plan_figures.py", plan_args)
    if rc != 0:
        draft["uncertainty"].append("plan with explicit columns failed (%s); retried auto"
                                    % msg.splitlines()[-1][:160])
        plan_args = list(base) + (["--intent", intent] if intent != "auto" else [])
        rc, msg = runner.call("plan_figures.py", plan_args)
    if rc != 0:
        for fallback in ("hist", "bar"):
            draft["uncertainty"].append("auto plan failed; retried --intent %s" % fallback)
            rc, msg = runner.call("plan_figures.py", base + ["--intent", fallback])
            if rc == 0:
                break
    if rc != 0:
        return blocked("could not map the table to any chart shape: %s"
                       % msg.splitlines()[-1][:240] if msg else "plan failed")

    # ---- spec
    spec_args = ["--plan", os.path.join(a.work, "chart_plan.json"), "--out", a.work,
                 "--source-path", os.path.abspath(data_path), "--normalized",
                 "normalized.csv"]
    title = a.title or opts["title"] or ops.get("title") or ""
    if title:
        spec_args += ["--title", title]
    rc, msg = runner.call("build_spec.py", spec_args)
    if rc != 0:
        return blocked("chart spec build failed: %s" % msg.splitlines()[-1][:240])

    built = read_json(os.path.join(a.work, "chart_spec.json"), {}) or {}
    empty = empty_panels(built)
    if empty:
        fatal_msg = ("fatal: panel %s has zero data marks; the selected y column has no "
                     "usable numeric rows. Refusing to emit an empty figure as ok."
                     % ",".join(empty))
        write_json(os.path.join(a.out, "selfcheck.json"),
                   {"verdict": "FAIL", "checked": False, "checker": "run_case.py",
                    "errors": [fatal_msg], "warnings": [],
                    "checks": [{"id": "panels.content", "ok": False, "detail": fatal_msg}],
                    "stats": {"data_marks": {p.get("id"): panel_marks(p)
                                             for p in built.get("panels") or []}}})
        return blocked(fatal_msg, extra_limits=[fatal_msg], fatal=True)

    # ---- edits / copy spec to output
    spec_out = os.path.join(a.out, "chart_spec.json")
    edit_log = {}
    if has_ops(ops):
        edit_args = ["--spec", os.path.join(a.work, "chart_spec.json"), "--out", a.out]
        if ops.get("title"):
            edit_args += ["--title", ops["title"]]
        if ops.get("y_min") is not None:
            edit_args += ["--y-min", ops["y_min"]]
        if ops.get("y_max") is not None:
            edit_args += ["--y-max", ops["y_max"]]
        if ops.get("chart_type"):
            edit_args += ["--chart-type", ops["chart_type"]]
        for ann in ops.get("annotations") or []:
            edit_args += ["--annotate", ann]
        for hl in ops.get("highlights") or []:
            edit_args += ["--highlight", hl]
        for st in ops.get("set_text") or []:
            edit_args += ["--set-text", st]
        rc, msg = runner.call("edit_figure.py", ["spec"] + edit_args)
        edit_log = read_json(os.path.join(a.out, "edit_log.json"), {}) or {}
        if not (edit_log.get("changes") or edit_log.get("warnings")):
            edit_log.setdefault("warnings", []).append(
                "all requested edits were already satisfied by the initial build; "
                "no spec rewrite was needed")
            write_json(os.path.join(a.out, "edit_log.json"), edit_log)
        for w in edit_log.get("warnings") or []:
            draft["limits"].append("edit: %s" % w)
        if not os.path.exists(spec_out):
            copy_file(os.path.join(a.work, "chart_spec.json"), spec_out)
    else:
        copy_file(os.path.join(a.work, "chart_spec.json"), spec_out)

    # ---- element map + caption
    rc, msg = runner.call("map_elements.py", ["--spec", spec_out, "--out", a.out])
    emap = read_json(os.path.join(a.out, "element_map.json"), {}) or {}
    caption = ""
    try:
        caption = open(os.path.join(a.out, "caption.md"), encoding="utf-8").read()
    except OSError:
        pass

    # ---- render
    render_ok = False
    no_matplotlib = False
    rc, msg = runner.call("render_figure.py",
                          ["--spec", spec_out, "--out", a.out,
                           "--formats", "svg,png,pdf"])
    if rc == 0:
        render_ok = True
    else:
        no_matplotlib = "matplotlib" in msg.lower() or rc == 3
        draft["uncertainty"].append(
            "matplotlib render unavailable (%s); used the stdlib SVG renderer"
            % (msg.splitlines()[-1][:160] if msg else "exit %d" % rc))
        rc2, msg2 = runner.call("svg_render.py", ["--spec", spec_out, "--out", a.out])
        if rc2 != 0:
            return blocked("both renderers failed: %s" % msg2.splitlines()[-1][:240])
        draft["limits"].append("renderer=stdlib-svg: no raster/PDF pass, no antialiasing; "
                               "geometry and numbers are unchanged")
        if not a.no_raster:
            rasterize(a.out, runner, draft)

    # ---- selfcheck
    rc, msg = runner.call("check_figure.py",
                          ["--spec", spec_out, "--work", a.work, "--out", a.out])
    selfcheck = read_json(os.path.join(a.out, "selfcheck.json"), {}) or {}
    render_meta = read_json(os.path.join(a.out, "render_meta.json"), {}) or {}
    spec = read_json(spec_out, {}) or {}
    png = render_meta.get("png") or {}
    have_png = os.path.exists(os.path.join(a.out, "figure.png")) and png.get("bytes", 0) > 0
    have_pdf = os.path.exists(os.path.join(a.out, "figure.pdf"))
    verdict = selfcheck.get("verdict", "FAIL")
    status = "ok" if verdict == "PASS" and have_png and have_pdf else "partial"
    if status == "ok" and case_doc.get("blocked"):
        status = "partial"
    empty = empty_panels(spec)
    if empty:
        status = "partial"
        draft["fatal"] = True
        draft["fatal_error"] = ("fatal: panel %s has zero data marks; an empty figure is "
                                "never reported as ok" % ",".join(empty))
        draft["uncertainty"].append(draft["fatal_error"])
        draft["limits"].append(draft["fatal_error"])

    # ---- draft
    element_counts = emap.get("counts") or {}
    draft.update({
        "status": status,
        "title": spec.get("title", ""),
        "chart_type": spec.get("chart_type", ""),
        "panel_count": len(spec.get("panels") or []),
        "caption": caption,
        "element_map": summarize_element_map(emap),
        "selfcheck": {k: selfcheck.get(k) for k in
                      ("verdict", "errors", "warnings", "stats")},
        "metrics": {
            "rows": snapshot["rows"], "columns": snapshot["columns"],
            "chart_type": spec.get("chart_type"), "panels": len(spec.get("panels") or []),
            "elements": element_counts.get("total", 0),
            "data_elements": element_counts.get("data", 0),
            "recomputed_marks": (selfcheck.get("stats") or {}).get("recomputed_marks"),
            "png": png, "renderer": (render_meta.get("renderer") or ""),
            "selfcheck_checks": len(selfcheck.get("checks") or []),
            "selfcheck_errors": len(selfcheck.get("errors") or []),
            "edit_changes": len((edit_log or {}).get("changes") or []),
        },
        "sources": [{"file": os.path.basename(data_path), "sha256": table["sha256"],
                     "bytes": table["bytes"], "rows": table["rows_total"],
                     "columns": table["columns"], "role": "data"},
                    {"file": "normalized.csv", "sha256": snapshot["normalized_sha256"],
                     "rows": snapshot["rows"], "role": "normalized_snapshot"}],
        "data_profile": {"file": "data_profile.json", "rows": profile.get("rows"),
                         "columns": profile.get("columns"),
                         "sha256": profile.get("sha256"),
                         "warnings": (profile.get("warnings") or [])[:10]},
        "data_snapshot": snapshot,
        "sample_sizes": {p.get("id"): p.get("sample_sizes")
                         for p in spec.get("panels") or []},
        "error_semantics": spec.get("error_semantics"),
        "change_log": ("initial generation from %s (sha256 %s…); chart=%s; edits=%d"
                       % (os.path.basename(data_path), table["sha256"][:12],
                          spec.get("chart_type"),
                          len((edit_log or {}).get("changes") or []))),
        "change_details": {"mode": (edit_log or {}).get("mode", "none"),
                           "changes": (edit_log or {}).get("changes") or [],
                           "warnings": (edit_log or {}).get("warnings") or []},
    })
    if no_matplotlib:
        draft["limits"].append("no matplotlib: PNG/PDF only exist if an optional SVG "
                               "converter is installed locally")
    if selfcheck.get("verdict") != "PASS":
        draft["uncertainty"].append("selfcheck verdict %s: %s"
                                    % (selfcheck.get("verdict"),
                                       (selfcheck.get("errors") or [])[:6]))
    for w in (selfcheck.get("warnings") or [])[:8]:
        draft["limits"].append("selfcheck: %s" % w)
    if spec.get("style", {}).get("cjk") and not render_meta.get("cjk_font"):
        draft["limits"].append("no CJK font detected: Chinese text is kept as live <text> "
                               "in SVG/PDF but raster output may show boxes")
    if not have_png or not have_pdf:
        draft["limits"].append("deliverable formats incomplete: png=%s pdf=%s"
                               % (have_png, have_pdf))
    return finish(runner, draft, a, case_doc, flow="spec")


def rasterize(out, runner, draft):
    """Optional: convert the fallback SVG to PNG/PDF with any local converter."""
    svg = os.path.join(out, "figure.svg")
    png, pdf = os.path.join(out, "figure.png"), os.path.join(out, "figure.pdf")
    if importlib.util.find_spec("cairosvg"):
        code = ("import cairosvg,sys;"
                "cairosvg.svg2png(url=sys.argv[1],write_to=sys.argv[2],scale=2.0);"
                "cairosvg.svg2pdf(url=sys.argv[1],write_to=sys.argv[3])")
        rc, msg = runner.call_raw([sys.executable, "-c", code, svg, png, pdf])
        if rc == 0:
            return True
    tool = shutil.which("rsvg-convert")
    if tool:
        if subprocess.call([tool, "-z", "2", "-o", png, svg]) == 0:
            subprocess.call([tool, "-f", "pdf", "-o", pdf, svg])
            return True
    tool = shutil.which("inkscape")
    if tool:
        ok = subprocess.call([tool, svg, "--export-filename=%s" % png]) == 0
        ok = subprocess.call([tool, svg, "--export-filename=%s" % pdf]) == ok
        if ok:
            return True
    draft["limits"].append("no SVG->PNG/PDF converter (cairosvg/rsvg-convert/inkscape)")
    return False


def finish(runner, draft, a, case_doc, flow="spec", svg_path="", ops=None,
           task_text=""):
    if flow == "svg":
        try:
            draft = svg_edit_flow(runner, svg_path, ops or {}, a.out, a.work, draft,
                                  task_text)
        except Exception as exc:  # noqa: BLE001
            draft["uncertainty"].append("svg edit failed: %s" % exc)
            draft["status"] = "partial"
            draft.setdefault("caption", "# SVG edit failed\n\n%s\n" % exc)
    return _emit(runner, draft, a, flow)


def _emit(runner, draft, a, flow="spec"):
    out = a.out
    write_json(os.path.join(a.work, "draft.json"), draft)
    kernel.cmd_emit(argparse.Namespace(draft=os.path.join(a.work, "draft.json"),
                                       out=out, work=a.work, case_id=draft.get("case_id")))
    rc = kernel.cmd_check(argparse.Namespace(result=os.path.join(out, "result.json"),
                                             work=a.work))
    if rc != 0:
        result = read_json(os.path.join(out, "result.json"), {}) or {}
        if result.get("status") == "ok":
            result["status"] = "partial"
            result["success"] = False
            result.setdefault("uncertainty", [])
            if isinstance(result["uncertainty"], list):
                result["uncertainty"].append(
                    "kernel check failed after emit; status downgraded to partial")
            write_json(os.path.join(out, "result.json"), result)
            rc = kernel.cmd_check(argparse.Namespace(result=os.path.join(out, "result.json"),
                                                     work=a.work))
    runner.flush()
    report = {"case_id": draft.get("case_id"), "status": draft.get("status"),
              "flow": flow, "result": os.path.join(out, "result.json"),
              "contract_fields": len(draft.get("contract_fields") or []),
              "kernel_check": "PASS" if rc == 0 else "FAIL",
              "steps": len(runner.log),
              "limits": draft.get("limits"), "uncertainty": draft.get("uncertainty")}
    write_json(os.path.join(a.work, "run_report.json"), report)
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print("run_case: status=%s flow=%s contract=%d kernel_check=%s"
              % (report["status"], flow, report["contract_fields"],
                 report["kernel_check"]))
    return 1 if draft.get("fatal") else 0


def _call_raw(self, cmd, timeout=180):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        self.log.append({"step": "subprocess", "args": [os.path.basename(str(x)) for x in cmd],
                         "exit": proc.returncode, "stdout": (proc.stdout or "")[-1000:],
                         "stderr": (proc.stderr or "")[-1000:]})
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 125, str(exc)


Runner.call_raw = _call_raw


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print("FATAL: %s" % exc)
        sys.exit(2)
