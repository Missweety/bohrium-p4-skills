#!/usr/bin/env python3
"""spec_io.py - deck-spec normalisation plus Marp/Markdown, notes and timing rendering.

Standard library only. python-pptx and LibreOffice are optional: when either is missing,
`try_pptx` / `try_pdf` return {"built": false, "reason": ...} instead of raising, so the
caller can degrade honestly and still deliver a spec, a Marp source and a speaker script.

Canonical spec (input keys are alias-tolerant):
  {case_id, audience, language, duration_min, max_slides, min_slides,
   theme: {bg, fg, accent},
   mainline: {problem|gap|approach|results|conclusion|limitations: {text, locator}},
   slides: [{index, kind, title, takeaway, bullets[], visual{type,ref,caption},
             evidence[{ref,quote,locator}], source_pages, seconds,
             notes{say, why, qa[{q,a}]}}]}
"""
import json
import os
import re

KINDS = ("title", "problem", "gap", "method", "result", "limitation", "conclusion", "backup")
SEGMENTS = (
    ("开场", ("title",)),
    ("问题与动机", ("problem", "gap")),
    ("方法与设计", ("method",)),
    ("结果与证据", ("result",)),
    ("局限与结论", ("limitation", "conclusion")),
    ("备用页", ("backup",)),
)
DEFAULT_THEME = {"bg": "#FFFFFF", "fg": "#1A1A1A", "accent": "#0B5FFF"}

ALIASES = {
    "case_id": ("case_id", "caseId", "id", "task_id", "case"),
    "audience": ("audience", "readers", "target_audience", "listeners", "听众"),
    "language": ("language", "lang", "target_language"),
    "duration_min": ("duration_min", "minutes", "duration", "talk_minutes",
                     "time_limit_min", "时长"),
    "max_slides": ("max_slides", "slide_limit", "max_pages", "page_limit", "slide_count_limit"),
    "min_slides": ("min_slides", "min_pages", "slide_min"),
    "slides": ("slides", "pages", "deck_outline", "deck", "slides_spec"),
    "mainline": ("mainline", "narrative", "story", "outline_mainline", "主线"),
    "theme": ("theme", "colors", "palette", "配色"),
}


def load_json(path, default=None):
    if not path or not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def text(value):
    return "" if value is None else str(value).strip()


def char_len(value):
    """Character budget used by the rules: non-whitespace characters."""
    return len(re.sub(r"\s+", "", text(value)))


def pick(data, key):
    if not isinstance(data, dict):
        return None
    for name in ALIASES.get(key, (key,)):
        val = data.get(name)
        if val not in (None, "", [], {}):
            return val
    return None


def pick_any(data, *names):
    if not isinstance(data, dict):
        return None
    for name in names:
        val = data.get(name)
        if val not in (None, "", [], {}):
            return val
    return None


def bullet_list(value):
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    elif isinstance(value, str):
        parts = re.split(r"\n|[；;]\s*", value)
    else:
        parts = []
    out = []
    for part in parts:
        part = re.sub(r"^\s*[-*•·]+\s*", "", str(part)).strip()
        part = re.sub(r"^\d+[.)、]\s*", "", part).strip()
        if part:
            out.append(part)
    return out


def _slot(raw):
    """Narrative slot: accepts str or {text, locator}; always returns {text, locator}."""
    if isinstance(raw, dict):
        return {"text": text(pick_any(raw, "text", "value", "claim", "summary")),
                "locator": text(pick_any(raw, "locator", "source", "ref", "pages"))}
    return {"text": text(raw), "locator": ""}


def _mainline(raw):
    if isinstance(raw, str):
        return {"problem": {"text": raw, "locator": ""}}
    raw = raw if isinstance(raw, dict) else {}
    results = pick_any(raw, "results", "key_results", "findings") or []
    if not isinstance(results, (list, tuple)):
        results = [results]
    return {
        "problem": _slot(pick_any(raw, "problem", "motivation", "question")),
        "gap": _slot(pick_any(raw, "gap", "novelty")),
        "approach": _slot(pick_any(raw, "approach", "method", "solution")),
        "results": [_slot(r) for r in results],
        "conclusion": _slot(pick_any(raw, "conclusion", "significance", "takeaway")),
        "limitations": _slot(pick_any(raw, "limitations", "limitation", "boundary")),
    }


def _theme(raw):
    raw = raw if isinstance(raw, dict) else {}
    theme = {}
    for key, aliases in (("bg", ("bg", "background", "base")),
                         ("fg", ("fg", "foreground", "text")),
                         ("accent", ("accent", "accent1", "primary", "强调"))):
        theme[key] = text(pick_any(raw, *aliases)) or DEFAULT_THEME[key]
    return theme


def _num(value, cast=float):
    try:
        return cast(float(value))
    except (TypeError, ValueError):
        return cast(0)


def normalize_spec(data, case=None):
    data = dict(data or {})
    if case:
        for key in ("case_id", "audience", "duration_min", "max_slides", "min_slides", "language"):
            if not data.get(key):
                val = pick(case, key)
                if val not in (None, ""):
                    data[key] = val
        # The case is the authority on its own limits: a spec may tighten them
        # (fewer than max_slides) but must never relax the case's page cap/floor.
        case_max, case_min = pick(case, "max_slides"), pick(case, "min_slides")
        if case_max not in (None, ""):
            data["max_slides"] = (min(_num(data.get("max_slides"), int), _num(case_max, int))
                                  if data.get("max_slides") else _num(case_max, int))
        if case_min not in (None, ""):
            data["min_slides"] = (max(_num(data.get("min_slides"), int), _num(case_min, int))
                                  if data.get("min_slides") else _num(case_min, int))

    slides_in = data.get("slides") or pick(data, "slides") or []
    if isinstance(slides_in, dict):
        slides_in = slides_in.get("slides", [])

    slides = []
    for i, raw in enumerate(slides_in):
        raw = raw if isinstance(raw, dict) else {}
        visual = raw.get("visual") if isinstance(raw.get("visual"), dict) else {}
        if not visual and raw.get("figure"):
            visual = {"type": "figure", "ref": text(raw.get("figure"))}
        notes = raw.get("notes")
        if isinstance(notes, str):
            notes = {"say": notes}
        notes = notes if isinstance(notes, dict) else {}
        evidence = raw.get("evidence")
        if isinstance(evidence, dict):
            evidence = [{"ref": k, "quote": v} for k, v in evidence.items()]
        evidence = [e for e in (evidence or []) if isinstance(e, dict)]
        slides.append({
            "index": i + 1,
            "kind": text(raw.get("kind")) or ("title" if i == 0 else "method"),
            "title": text(raw.get("title")),
            "takeaway": text(raw.get("takeaway")),
            "bullets": bullet_list(raw.get("bullets") or raw.get("points") or raw.get("body")),
            "visual": {
                "type": text(visual.get("type")) or "none",
                "ref": text(visual.get("ref")),
                "caption": text(visual.get("caption")),
                "path": text(pick_any(visual, "path", "file", "image")),
                "table": (visual.get("table")
                          if isinstance(visual.get("table"), (dict, list)) else None),
            },
            "evidence": [{
                "ref": text(e.get("ref") or e.get("locator")),
                "quote": text(e.get("quote") or e.get("snippet")),
                "locator": text(e.get("locator")),
            } for e in evidence],
            "source_pages": text(pick_any(raw, "source_pages", "source_page", "pages", "page")),
            "seconds": _num(raw.get("seconds") or raw.get("duration_sec"), int),
            "notes": {
                "say": text(notes.get("say") or notes.get("script") or notes.get("讲稿")),
                "why": text(notes.get("why") or notes.get("transition")),
                "qa": [qa for qa in (notes.get("qa") or []) if isinstance(qa, dict)],
            },
        })

    return {
        "case_id": text(pick(data, "case_id")) or "unknown",
        "audience": text(pick(data, "audience")),
        "language": text(pick(data, "language")) or "zh",
        "duration_min": _num(pick(data, "duration_min"), float),
        "max_slides": _num(pick(data, "max_slides"), int),
        "min_slides": _num(pick(data, "min_slides"), int),
        "theme": _theme(pick(data, "theme")),
        "mainline": _mainline(pick(data, "mainline") or {}),
        "slides": slides,
    }


def segment_of(kind):
    for name, kinds in SEGMENTS:
        if kind in kinds:
            return name
    return "方法与设计"


def mmss(seconds):
    seconds = int(round(seconds))
    return "%02d:%02d" % (seconds // 60, seconds % 60)


def content_slides(spec):
    return [s for s in spec.get("slides", []) if s.get("kind") != "backup"]


def total_seconds(spec):
    return sum(int(s.get("seconds") or 0) for s in spec.get("slides", []))


def timing_rows(spec):
    rows, acc = [], 0
    for slide in spec.get("slides", []):
        sec = int(slide.get("seconds") or 0)
        acc += sec
        rows.append({
            "index": slide["index"],
            "kind": slide["kind"],
            "segment": segment_of(slide["kind"]),
            "title": slide.get("title", ""),
            "seconds": sec,
            "cumulative": acc,
            "cumulative_mmss": mmss(acc),
        })
    return rows


def segment_totals(spec):
    out = []
    for name, _ in SEGMENTS:
        secs = sum(int(s.get("seconds") or 0) for s in spec.get("slides", [])
                   if segment_of(s.get("kind")) == name)
        if secs:
            out.append({"segment": name, "seconds": secs, "minutes": round(secs / 60.0, 1)})
    return out


def _note_lines(slide):
    notes = slide.get("notes") or {}
    lines = []
    if notes.get("say"):
        lines.append("讲稿：" + notes["say"])
    if notes.get("why"):
        lines.append("过渡：" + notes["why"])
    for qa in notes.get("qa") or []:
        lines.append("问答：%s → %s" % (text(qa.get("q")), text(qa.get("a"))))
    return lines


def render_marp(spec):
    """Marp-compatible Markdown: one slide per `---`, speaker notes in HTML comments."""
    theme = spec.get("theme") or DEFAULT_THEME
    lines = ["---", "marp: true", "theme: default", "paginate: true", "size: 16:9",
             "style: |",
             "  section { background: %s; color: %s; }" % (theme["bg"], theme["fg"]),
             "  h1 { color: %s; }" % theme["accent"],
             "---"]
    for slide in spec.get("slides", []):
        lines.append("")
        if slide.get("kind") == "title":
            lines.append("<!-- _class: lead -->")
        lines.append("# " + (slide.get("title") or "（待定标题）"))
        if slide.get("takeaway"):
            lines.append("")
            lines.append("**" + slide["takeaway"] + "**")
        if slide.get("bullets"):
            lines.append("")
            lines.extend("- " + b for b in slide["bullets"])
        visual = slide.get("visual") or {}
        if visual.get("type") in ("figure", "table", "schematic", "photo"):
            label = {"table": "表", "schematic": "示意图"}.get(visual.get("type"), "图")
            ref = " " + visual["ref"] if visual.get("ref") else ""
            lines.append("")
            lines.append("> %s%s：%s" % (label, ref, visual.get("caption") or "（图注待补）"))
        notes = _note_lines(slide)
        if notes:
            lines.append("")
            lines.append("<!--")
            lines.extend(notes)
            lines.append("-->")
        lines.append("")
        lines.append("---")
    if lines and lines[-1] == "---":
        lines.pop()
    return "\n".join(lines) + "\n"


def render_notes(spec):
    rows = timing_rows(spec)
    total = total_seconds(spec)
    lines = ["# 逐页讲稿与时间分配", "",
             "- 案例：%s" % spec.get("case_id", "unknown"),
             "- 受众：%s" % (spec.get("audience") or "未声明"),
             "- 页数：%d（主讲页 %d）" % (len(spec.get("slides", [])), len(content_slides(spec))),
             "- 总时长：%s（%d 秒）" % (mmss(total), total), ""]
    for slide, row in zip(spec.get("slides", []), rows):
        lines.append("## 第 %d 页｜%s（%d 秒，累计 %s）" % (
            slide["index"], slide.get("title") or "（待定）", row["seconds"], row["cumulative_mmss"]))
        lines.append("")
        lines.append("- 页型：%s｜段落：%s" % (slide.get("kind"), row["segment"]))
        if slide.get("takeaway"):
            lines.append("- 本页主张：%s" % slide["takeaway"])
        if slide.get("source_pages"):
            lines.append("- 来源：%s" % slide["source_pages"])
        visual = slide.get("visual") or {}
        if visual.get("ref"):
            lines.append("- 图表：%s（%s）" % (visual["ref"], visual.get("caption") or "图注待补"))
        notes = slide.get("notes") or {}
        lines.append("- 口播（%d 秒）：%s" % (row["seconds"], notes.get("say") or "（缺讲稿，需补齐）"))
        if notes.get("why"):
            lines.append("- 过渡：%s" % notes["why"])
        for qa in notes.get("qa") or []:
            lines.append("- 预设问答：%s → %s" % (text(qa.get("q")), text(qa.get("a"))))
        lines.append("")
    lines.append("## 时间分配表")
    lines.append("")
    lines.append("| 段落 | 时长 | 页数 |")
    lines.append("|-|-|-|")
    for item in segment_totals(spec):
        pages = [r["index"] for r in rows if r["segment"] == item["segment"]]
        span = ("%d-%d" % (min(pages), max(pages))) if pages else "-"
        lines.append("| %s | %s（%d 秒） | %s |" % (item["segment"], mmss(item["seconds"]),
                                                    item["seconds"], span))
    lines.append("| 合计 | %s | %d 页 |" % (mmss(total), len(spec.get("slides", []))))
    return "\n".join(lines) + "\n"


def render_timing_md(spec):
    lines = ["# 时间分配表", "",
             "| 页 | 页型 | 标题 | 本页 | 累计 | 段落 |",
             "|-|-|-|-|-|-|"]
    for row in timing_rows(spec):
        lines.append("| %d | %s | %s | %d s | %s | %s |" % (
            row["index"], row["kind"], row["title"].replace("|", "/"),
            row["seconds"], row["cumulative_mmss"], row["segment"]))
    total = total_seconds(spec)
    lines += ["| 合计 | | | %d s | %s | |" % (total, mmss(total)), ""]
    lines.append("## 分段汇总")
    lines.append("")
    lines.append("| 段落 | 时长 | 占比 |")
    lines.append("|-|-|-|")
    for item in segment_totals(spec):
        lines.append("| %s | %s | %.0f%% |" % (item["segment"], mmss(item["seconds"]),
                                                100.0 * item["seconds"] / max(total, 1)))
    return "\n".join(lines) + "\n"


def timing_csv(spec):
    lines = ["index,kind,segment,title,seconds,cumulative_seconds,cumulative_mmss"]
    for row in timing_rows(spec):
        title = '"%s"' % row["title"].replace('"', "'")
        lines.append("%d,%s,%s,%s,%d,%d,%s" % (
            row["index"], row["kind"], row["segment"], title,
            row["seconds"], row["cumulative"], row["cumulative_mmss"]))
    return "\n".join(lines) + "\n"


def _find_layout(prs, kind):
    layouts = list(prs.slide_layouts)
    for layout in layouts:
        name = (getattr(layout, "name", "") or "").lower()
        if kind == "title" and ("title slide" in name or "标题幻灯片" in name):
            return layout
    for layout in layouts:
        name = (getattr(layout, "name", "") or "").lower()
        if kind != "title" and ("title and content" in name or "标题和内容" in name):
            return layout
    if len(layouts) > 1:
        return layouts[0] if kind == "title" else layouts[1]
    return layouts[0]


def _set_body(slide, bullets, width, height):
    body = None
    for shape in slide.placeholders:
        if shape.placeholder_format.idx != 0 and getattr(shape, "has_text_frame", False):
            body = shape
            break
    if body is None:
        body = slide.shapes.add_textbox(int(width * 0.07), int(height * 0.22),
                                        int(width * 0.86), int(height * 0.65))
    frame = body.text_frame
    frame.clear()
    for i, item in enumerate(bullets):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.text = item
    return body


def _figure_key(value):
    """First figure key in a ref/filename: number plus optional panel letter (2b)."""
    match = re.search(r"(\d+)\s*([a-z])?", str(value).lower())
    return (match.group(1) + (match.group(2) or "")) if match else ""


def _locate_image(visual, materials_dir=""):
    # Explicit paths take precedence; ambiguous inferred figures are never selected.
    for key in ("path", "file", "image"):
        value = visual.get(key)
        if value:
            if os.path.isabs(value):
                candidates = [value]
            else:
                # Spec paths are read relative to the materials dir; tolerate specs
                # that keep the case's "materials/xxx.png" prefix.
                candidates = [os.path.join(materials_dir or "", value)]
                if materials_dir:
                    candidates.append(os.path.join(materials_dir, os.path.basename(value)))
            for path in candidates:
                if os.path.isfile(path):
                    return path
            return ""
    ref_key = _figure_key(visual.get("ref") or "")
    if not ref_key or not materials_dir or not os.path.isdir(materials_dir): return ""
    ref_num = re.sub(r"[a-z]$", "", ref_key)
    exact, whole = [], []
    for name in sorted(os.listdir(materials_dir)):
        if os.path.splitext(name.lower())[1] not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"): continue
        key = _figure_key(name)
        if key == ref_key: exact.append(os.path.join(materials_dir, name))
        elif ref_num != ref_key and key == ref_num: whole.append(os.path.join(materials_dir, name))
    options = exact or whole
    return options[0] if len(options) == 1 else ""



def _fit_rect(px_w, px_h, left, top, width, height):
    scale = min(float(width) / max(px_w, 1), float(height) / max(px_h, 1))
    draw_w, draw_h = int(px_w * scale), int(px_h * scale)
    return (int(left + (width - draw_w) / 2), int(top + (height - draw_h) / 2),
            draw_w, draw_h)


def _image_size(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            import struct
            width, height = struct.unpack(">II", head[16:24])
            return int(width), int(height)
        if head[:2] == b"\xff\xd8":
            with open(path, "rb") as fh:
                fh.seek(2)
                while True:
                    byte = fh.read(1)
                    while byte and byte != b"\xff":
                        byte = fh.read(1)
                    marker = fh.read(1)
                    while marker == b"\xff":
                        marker = fh.read(1)
                    if not marker:
                        return None
                    length = int.from_bytes(fh.read(2), "big")
                    if marker[0] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6,
                                     0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        data = fh.read(5)
                        return (int.from_bytes(data[3:5], "big"),
                                int.from_bytes(data[1:3], "big"))
                    fh.seek(length - 2, 1)
    except Exception:  # noqa: BLE001
        return None
    return None


def _insert_visual(slide, item, prs, materials_dir, uncertainty):
    """Insert a real figure/table when the material exists; never invent one."""
    visual = item.get("visual") or {}
    vtype = visual.get("type")
    width, height = prs.slide_width, prs.slide_height
    box_left, box_top = int(width * 0.55), int(height * 0.26)
    box_w, box_h = int(width * 0.4), int(height * 0.5)
    if vtype in ("figure", "schematic", "photo"):
        image = _locate_image(visual, materials_dir)
        if not image:
            uncertainty.append("第 %d 页图表未找到图像文件（%s），保留全宽正文与图注"
                               % (item.get("index", 0), visual.get("ref") or "无编号"))
            return "missing-image"
        size = _image_size(image)
        if not size:
            uncertainty.append("第 %d 页图像尺寸不可读：%s"
                               % (item.get("index", 0), os.path.basename(image)))
            return "unreadable-image"
        left, top, draw_w, draw_h = _fit_rect(size[0], size[1], box_left, box_top, box_w, box_h)
        slide.shapes.add_picture(image, left, top, draw_w, draw_h)
        return "picture"
    if vtype == "table":
        table = visual.get("table")
        if isinstance(table, dict):
            raw_header = table.get("header") or table.get("columns") or []
            rows = table.get("rows") or []
        elif isinstance(table, list):
            raw_header, rows = (table[0] if table else []), table[1:]
        else:
            raw_header, rows = [], []
        if isinstance(raw_header, dict):
            header_keys = list(raw_header.keys())
            header = [raw_header[k] for k in header_keys]
        else:
            header_keys, header = [], list(raw_header or [])
        if not header and not rows:
            uncertainty.append("第 %d 页表格缺少 table 数据，保留全宽正文与图注"
                               % item.get("index", 0))
            return "missing-table"
        norm_rows = []
        for row in rows:
            if isinstance(row, dict):
                cells = ([row.get(k, "") for k in header_keys] if header_keys
                         else [row.get(k, "") for k in row])
            elif isinstance(row, (list, tuple)):
                cells = list(row)
            else:
                cells = [row]
            norm_rows.append(cells)
        n_cols = max([len(header)] + [len(cells) for cells in norm_rows] + [1])
        shape = slide.shapes.add_table(1 + len(norm_rows), n_cols,
                                       box_left, box_top, box_w, box_h)
        for col in range(n_cols):
            value = header[col] if col < len(header) else ""
            shape.table.cell(0, col).text = str(value)
        for row_idx, cells in enumerate(norm_rows, start=1):
            for col in range(n_cols):
                value = cells[col] if col < len(cells) else ""
                shape.table.cell(row_idx, col).text = str(value)
        return "table"
    return "none"


def _set_caption(slide, text_value, prs):
    if not text_value:
        return
    width, height = prs.slide_width, prs.slide_height
    shape = slide.shapes.add_textbox(int(width * 0.07), int(height * 0.86),
                                     int(width * 0.86), int(height * 0.06))
    shape.text_frame.text = text_value
    try:
        shape.text_frame.paragraphs[0].font.size = int(height * 0.022)
    except Exception:  # noqa: BLE001
        pass


def try_pptx(spec, out_path, template=None, materials_dir=""):
    """Best-effort pptx export. Never raises: returns {"built": bool, ...}.

    Inserts a real figure/table only when the material exists; missing visuals
    are reported in `uncertainty` and never replaced by a fabricated image.
    """
    uncertainty = []
    try:
        from pptx import Presentation  # optional dependency
        from pptx.util import Inches
    except Exception as exc:  # noqa: BLE001
        return {"built": False, "reason": "python-pptx unavailable: %s" % exc, "path": None}
    try:
        if template and os.path.realpath(out_path) == os.path.realpath(template):
            raise ValueError("output must not overwrite template")
        if template and not os.path.isfile(template):
            raise ValueError("指定模板不存在或不可读")
        prs = Presentation(template) if template else Presentation()
        # The template contributes its master and layouts, not its example slides.
        if template:
            while len(prs.slides):
                slide_id = prs.slides._sldIdLst[0]
                prs.part.drop_rel(slide_id.rId)
                prs.slides._sldIdLst.remove(slide_id)
        if not template:
            prs.slide_width = Inches(13.333)
            prs.slide_height = Inches(7.5)
        width, height = prs.slide_width, prs.slide_height
        for item in spec.get("slides", []):
            layout = _find_layout(prs, item.get("kind"))
            slide = prs.slides.add_slide(layout)
            title = slide.shapes.title
            if title is not None:
                title.text = item.get("title") or ""
            else:
                box = slide.shapes.add_textbox(int(width * 0.07), int(height * 0.05),
                                               int(width * 0.86), int(height * 0.15))
                box.text_frame.text = item.get("title") or ""
            body = None
            if item.get("bullets"):
                body = _set_body(slide, item["bullets"], width, height)
            visual = item.get("visual") or {}
            vtype = visual.get("type")
            insertable = False
            if vtype in ("figure", "schematic", "photo"):
                insertable = bool(_locate_image(visual, materials_dir))
            elif vtype == "table":
                table = visual.get("table")
                if isinstance(table, dict):
                    insertable = bool(table.get("header") or table.get("columns")
                                      or table.get("rows"))
                elif isinstance(table, list):
                    insertable = bool(table)
            if insertable and body is not None:
                try:
                    body.width = int(width * 0.48)
                    body.height = int(height * 0.55)
                except Exception:  # noqa: BLE001
                    pass
            try:
                kind = _insert_visual(slide, item, prs, materials_dir, uncertainty)
            except Exception as exc:  # noqa: BLE001
                kind = "failed"
                uncertainty.append("第 %d 页图表插入失败：%s" % (item.get("index", 0), exc))
            caption = visual.get("caption") or ""
            if caption:
                try:
                    _set_caption(slide, caption, prs)
                except Exception as exc:  # noqa: BLE001
                    uncertainty.append("第 %d 页图注写入失败：%s" % (item.get("index", 0), exc))
            elif kind in ("picture", "table"):
                uncertainty.append("第 %d 页图表缺图注，未臆造" % item.get("index", 0))
            notes = _note_lines(item)
            if notes:
                try:
                    slide.notes_slide.notes_text_frame.text = "\n".join(notes)
                except Exception:  # noqa: BLE001
                    pass
        prs.save(out_path)
        return {"built": True, "reason": "", "path": out_path, "uncertainty": uncertainty}
    except Exception as exc:  # noqa: BLE001
        return {"built": False, "reason": "pptx build failed: %s" % exc, "path": None}


def try_pdf(pptx_path, out_dir):
    """Convert in an isolated directory, verifying this invocation's PDF."""
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    if not pptx_path or not os.path.isfile(pptx_path):
        return {"built": False, "reason": "pptx not found", "path": None}
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe: return {"built": False, "reason": "LibreOffice not available", "path": None}
    out = Path(out_dir).absolute()
    if any(p.is_symlink() for p in [out, *out.parents]):
        return {"built": False, "reason": "symlink output directory refused", "path": None}
    target = out / (Path(pptx_path).stem + ".pdf")
    if target.is_symlink() or target.resolve() == Path(pptx_path).resolve():
        return {"built": False, "reason": "unsafe PDF target", "path": None}
    try:
        out.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp); profile = (work / "profile").as_uri()
            run = subprocess.run([exe, "--headless", "-env:UserInstallation=" + profile,
                    "--convert-to", "pdf", "--outdir", str(work), pptx_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=False)
            pdf = work / (Path(pptx_path).stem + ".pdf")
            if run.returncode != 0 or not pdf.is_file():
                return {"built": False, "reason": "PDF converter failed or produced no file", "path": None}
            raw = pdf.read_bytes()
            if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-2048:]:
                return {"built": False, "reason": "invalid PDF output", "path": None}
            tmpout = out / ("." + target.name + ".tmp-" + str(os.getpid()))
            if tmpout.exists() or tmpout.is_symlink(): raise ValueError("temporary output exists")
            try:
                with tmpout.open("xb") as f: f.write(raw)
                os.replace(tmpout, target)
            finally:
                if tmpout.exists(): tmpout.unlink()
            return {"built": True, "reason": "", "path": str(target)}
    except Exception as exc:
        return {"built": False, "reason": "pdf convert failed: %s" % exc, "path": None}
