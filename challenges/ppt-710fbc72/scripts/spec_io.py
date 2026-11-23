#!/usr/bin/env python3
"""spec_io.py - slide-spec normalisation, Marp/Markdown rendering and optional pptx export.

Standard library covers every required deliverable. python-pptx is optional: when it is
missing, broken, or the template has no usable placeholder, the helper returns
{"built": false, "reason": ...} instead of raising, so callers can degrade honestly.

Spec shape (all keys alias-tolerant on input, canonical on output):
  {case_id, audience, duration_min, max_slides, language,
   mainline: {problem, approach, results, conclusion, ...},
   slides: [{index, kind, title, takeaway, bullets[], visual{}, evidence[],
             notes:{say, why, qa[]}, seconds}]}
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

ALIASES = {
    "case_id": ("case_id", "caseId", "id", "task_id"),
    "audience": ("audience", "readers", "target_audience", "listeners", "听众"),
    "duration_min": ("duration_min", "minutes", "duration", "talk_minutes", "time_limit_min", "时长"),
    "max_slides": ("max_slides", "slide_limit", "max_pages", "page_limit", "slide_count_limit"),
    "language": ("language", "lang", "target_language"),
    "slides": ("slides", "pages", "deck_outline", "deck", "slides_spec"),
    "mainline": ("mainline", "narrative", "story", "outline_mainline", "主线"),
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


def char_len(value):
    """Character budget used by the rules: non-whitespace characters."""
    return len(re.sub(r"\s+", "", text(value)))


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


def _mainline(raw):
    if isinstance(raw, str):
        return {"problem": raw}
    raw = raw if isinstance(raw, dict) else {}
    results = pick_any(raw, "results", "key_results", "findings")
    if isinstance(results, (list, tuple)):
        results = "；".join(text(r) for r in results if text(r))
    return {
        "problem": text(pick_any(raw, "problem", "motivation", "question")),
        "gap": text(pick_any(raw, "gap", "novelty")),
        "approach": text(pick_any(raw, "approach", "method", "solution")),
        "results": text(results),
        "conclusion": text(pick_any(raw, "conclusion", "significance", "takeaway")),
        "limitations": text(pick_any(raw, "limitations", "limitation", "boundary")),
    }


def normalize_spec(data, case=None):
    data = dict(data or {})
    if case:
        for key in ("case_id", "audience", "duration_min", "max_slides", "language"):
            if not data.get(key):
                val = pick(case, key)
                if val not in (None, ""):
                    data[key] = val

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
        try:
            seconds = int(float(raw.get("seconds") or raw.get("duration_sec") or 0))
        except (TypeError, ValueError):
            seconds = 0
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
                "path": text(visual.get("path") or visual.get("file") or visual.get("image")),
                "table": visual.get("table") if isinstance(visual.get("table"), (dict, list)) else None,
            },
            "evidence": [{
                "ref": text(e.get("ref") or e.get("locator")),
                "quote": text(e.get("quote") or e.get("snippet")),
                "locator": text(e.get("locator")),
            } for e in evidence],
            "notes": {
                "say": text(notes.get("say") or notes.get("script") or notes.get("讲稿")),
                "why": text(notes.get("why") or notes.get("transition")),
                "qa": [qa for qa in (notes.get("qa") or []) if isinstance(qa, dict)],
            },
            "seconds": seconds,
        })

    try:
        duration = float(pick(data, "duration_min") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    try:
        max_slides = int(float(pick(data, "max_slides") or 0))
    except (TypeError, ValueError):
        max_slides = 0

    return {
        "case_id": text(pick(data, "case_id")) or "unknown",
        "audience": text(pick(data, "audience")),
        "duration_min": duration,
        "max_slides": max_slides,
        "language": text(pick(data, "language")) or "zh",
        "footer": text(data.get("footer") or data.get("footer_text") or ""),
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
    """Marp-compatible Markdown: one slide per `---`, speaker notes as HTML comments."""
    lines = ["---", "marp: true", "theme: default", "paginate: true", "size: 16:9", "---"]
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
            label = "表" if visual.get("type") == "table" else "图"
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
        lines.append("| %s | %s（%d 秒） | %s |" % (item["segment"], mmss(item["seconds"]), item["seconds"], span))
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
    lines += ["| 合计 | | | %d s | %s | |" % (total_seconds(spec), mmss(total_seconds(spec))), ""]
    lines.append("## 分段汇总")
    lines.append("")
    lines.append("| 段落 | 时长 | 占比 |")
    lines.append("|-|-|-|")
    total = max(total_seconds(spec), 1)
    for item in segment_totals(spec):
        lines.append("| %s | %s | %.0f%% |" % (item["segment"], mmss(item["seconds"]),
                                                100.0 * item["seconds"] / total))
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


def _find_layout_by_name(prs, name):
    if not name:
        return None
    target = str(name).strip().lower()
    for layout in prs.slide_layouts:
        if (getattr(layout, "name", "") or "").strip().lower() == target:
            return layout
    return None


def _placeholder(slide, idxs=(), types=(), name_has=()):
    for shape in slide.placeholders:
        try:
            pf = shape.placeholder_format
        except Exception:  # noqa: BLE001
            continue
        name = (getattr(shape, "name", "") or "").lower()
        tname = str(getattr(pf.type, "name", "") or "").lower()
        if idxs and pf.idx in idxs:
            return shape
        if types and tname in types:
            return shape
        if name_has and any(key in name for key in name_has):
            return shape
    return None


def _body_shape(slide):
    shape = _placeholder(slide, idxs=(1,))
    if shape is not None:
        return shape
    shape = _placeholder(slide, types=("body", "object", "subtitle"))
    if shape is not None:
        return shape
    for candidate in slide.placeholders:
        try:
            idx = candidate.placeholder_format.idx
        except Exception:  # noqa: BLE001
            continue
        if idx in (0, 10, 11, 12):
            continue
        if getattr(candidate, "has_text_frame", False):
            return candidate
    return None


def _write_bullets(frame, bullets, takeaway=""):
    frame.clear()
    first = True
    if takeaway:
        para = frame.paragraphs[0]
        para.text = takeaway
        first = False
    for item in bullets:
        para = frame.paragraphs[0] if first else frame.add_paragraph()
        para.text = item
        first = False


def _image_size(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                import struct
                width, height = struct.unpack(">II", head[16:24])
                return int(width), int(height)
            if head[:2] == b"\xff\xd8":
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


def _figure_key(value):
    """First figure key in a ref/filename: number plus optional panel letter (2b)."""
    match = re.search(r"(\d+)\s*([a-z])?", str(value).lower())
    return (match.group(1) + (match.group(2) or "")) if match else ""


def _locate_image(visual, materials_dir=""):
    # Explicit paths take precedence; ambiguous inferred figures are never selected.
    for key in ("path", "file", "image"):
        value = visual.get(key)
        if value:
            path = value if os.path.isabs(value) else os.path.join(materials_dir or "", value)
            if os.path.isfile(path): return path
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


def _insert_visual(slide, item, prs, materials_dir, uncertainty):
    """Insert a figure or native table; return (kind, caption_text)."""
    visual = item.get("visual") or {}
    vtype = visual.get("type")
    width, height = prs.slide_width, prs.slide_height
    box_left, box_top = int(width * 0.55), int(height * 0.28)
    box_w, box_h = int(width * 0.4), int(height * 0.52)
    if vtype in ("figure", "schematic", "photo"):
        image = _locate_image(visual, materials_dir)
        if not image:
            uncertainty.append("第 %d 页图表未找到图像文件（%s），仅保留图注"
                               % (item["index"], visual.get("ref") or "无编号"))
            return "missing-image", visual.get("caption") or ""
        size = _image_size(image)
        if not size:
            uncertainty.append("第 %d 页图像尺寸不可读：%s" % (item["index"], os.path.basename(image)))
            return "unreadable-image", visual.get("caption") or ""
        left, top, draw_w, draw_h = _fit_rect(size[0], size[1], box_left, box_top, box_w, box_h)
        slide.shapes.add_picture(image, left, top, draw_w, draw_h)
        return "picture", visual.get("caption") or ""
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
            uncertainty.append("第 %d 页表格缺少 table 数据，仅保留图注" % item["index"])
            return "missing-table", visual.get("caption") or ""
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
        table_obj = shape.table
        for col in range(n_cols):
            value = header[col] if col < len(header) else ""
            table_obj.cell(0, col).text = str(value)
        for row_idx, cells in enumerate(norm_rows, start=1):
            for col in range(n_cols):
                value = cells[col] if col < len(cells) else ""
                table_obj.cell(row_idx, col).text = str(value)
        return "table", visual.get("caption") or ""
    return "none", ""


def _set_caption(slide, text_value, prs):
    if not text_value:
        return False
    shape = _placeholder(slide, name_has=("caption", "图注", "表注"))
    if shape is not None:
        shape.text_frame.text = text_value
        return True
    box = slide.shapes.add_textbox(int(prs.slide_width * 0.07),
                                   int(prs.slide_height * 0.86),
                                   int(prs.slide_width * 0.86),
                                   int(prs.slide_height * 0.06))
    box.text_frame.text = text_value
    return True


def _strip_slide_content(slide):
    """Drop old slide-level content when reusing a base page.

    Text boxes with old text and old pictures/tables/charts are removed; empty decorative
    shapes and placeholders stay, and master/layout design is untouched.
    """
    for shape in list(slide.shapes):
        if getattr(shape, "is_placeholder", False):
            if getattr(shape, "has_text_frame", False):
                shape.text_frame.clear()
            continue
        has_text = (getattr(shape, "has_text_frame", False)
                    and bool(shape.text_frame.text.strip()))
        is_media = getattr(shape, "shape_type", None) in (3, 13, 19)  # chart, picture, table
        if not has_text and not is_media:
            continue
        element = shape._element
        element.getparent().remove(element)


def _drop_slides(prs, keep):
    try:
        from pptx.oxml.ns import qn
        sld_ids = prs.slides._sldIdLst
        for sld_id in list(sld_ids)[keep:]:
            r_id = sld_id.get(qn("r:id"))
            prs.part.drop_rel(r_id)
            sld_ids.remove(sld_id)
    except Exception:  # noqa: BLE001
        pass


def try_pptx(spec, out_path, template=None, base_deck=None, materials_dir=""):
    """Best-effort pptx export from the template/starting deck.

    Returns {"built", "reason", "path", "tool", "pages"} and never raises. When python-pptx
    is missing, falls back to the stdlib builder in pptx_min.py (text-only, honest limits).
    """
    uncertainty = []
    from pathlib import Path
    target = Path(out_path).absolute()
    for item in (target, *target.parents):
        if item.is_symlink():
            return {"built": False, "reason": "symlink output refused", "path": None, "pages": []}
    for src in (template, base_deck):
        if src and Path(src).exists() and target.resolve() == Path(src).resolve():
            return {"built": False, "reason": "output would overwrite source deck/template", "path": None, "pages": []}
    if base_deck and template and os.path.exists(base_deck) and os.path.exists(template) and Path(base_deck).resolve() != Path(template).resolve():
        return {"built": False, "reason": "cannot faithfully apply a different template to an existing deck; generate from target template and migrate content explicitly", "path": None, "pages": [], "uncertainty": ["different base deck and template require explicit content migration"]}
    try:
        from pptx import Presentation
    except Exception as exc:  # noqa: BLE001
        return _try_pptx_stdlib(spec, out_path, exc)
    try:
        prs, source = None, None
        for candidate in (base_deck, template):
            if not candidate or not os.path.exists(candidate):
                continue
            try:
                prs = Presentation(candidate)
                source = candidate
                break
            except Exception as exc:  # noqa: BLE001
                uncertainty.append("无法打开 %s（%s），改用其余来源"
                                   % (os.path.basename(candidate), exc))
        if prs is None:
            from pptx.util import Inches
            prs = Presentation()
            prs.slide_width = Inches(13.333)
            prs.slide_height = Inches(7.5)
            uncertainty.append("模板/起始稿不可读，已用默认 16:9 画布构建")
        base_count = len(prs.slides) if base_deck and source == base_deck else 0
        _drop_slides(prs, base_count)
        pages = []
        for index, item in enumerate(spec.get("slides", []), start=1):
            layout = _find_layout_by_name(prs, item.get("layout"))
            if layout is None:
                layout = _find_layout(prs, item.get("kind"))
            if base_count and index <= base_count:
                slide = prs.slides[index - 1]
                _strip_slide_content(slide)
            else:
                slide = prs.slides.add_slide(layout)
            title = slide.shapes.title
            if title is not None:
                title.text = item.get("title") or ""
            else:
                box = slide.shapes.add_textbox(int(prs.slide_width * 0.07),
                                               int(prs.slide_height * 0.05),
                                               int(prs.slide_width * 0.86),
                                               int(prs.slide_height * 0.15))
                box.text_frame.text = item.get("title") or ""
            body = _body_shape(slide)
            if body is None:
                body = slide.shapes.add_textbox(int(prs.slide_width * 0.07),
                                                int(prs.slide_height * 0.22),
                                                int(prs.slide_width * 0.86),
                                                int(prs.slide_height * 0.65))
            if getattr(body, "has_text_frame", False):
                bullets = list(item.get("bullets") or [])
                _write_bullets(body.text_frame, bullets, item.get("takeaway") or "")
            if (item.get("visual") or {}).get("type") in ("figure", "table", "schematic", "photo"):
                try:
                    body.width = int(prs.slide_width * 0.46)
                    body.height = int(prs.slide_height * 0.54)
                except Exception:  # noqa: BLE001
                    pass
            try:
                visual_kind, caption = _insert_visual(slide, item, prs, materials_dir, uncertainty)
            except Exception as exc:  # noqa: BLE001
                visual_kind = "failed"
                caption = (item.get("visual") or {}).get("caption") or ""
                uncertainty.append("第 %d 页图表插入失败：%s" % (index, exc))
            caption = caption or (item.get("visual") or {}).get("caption") or ""
            visual = item.get("visual") or {}
            if visual.get("type") in ("figure", "table", "schematic", "photo") and not caption:
                caption = "%s（来源见页级证据）" % (visual.get("ref") or "图表")
                uncertainty.append("第 %d 页图表缺图注，已用编号占位，需核对原图注" % index)
            _set_caption(slide, caption, prs)
            footer = _placeholder(slide, idxs=(11,), types=("footer",))
            footer_text = spec.get("footer") or ""
            if footer is not None and getattr(footer, "has_text_frame", False):
                if not footer.text_frame.text:
                    footer.text_frame.text = footer_text
            elif footer_text:
                box = slide.shapes.add_textbox(int(prs.slide_width * 0.05),
                                               int(prs.slide_height * 0.93),
                                               int(prs.slide_width * 0.5),
                                               int(prs.slide_height * 0.04))
                box.text_frame.text = footer_text
            number = _placeholder(slide, idxs=(12,), types=("slide_number",))
            if number is not None and getattr(number, "has_text_frame", False):
                number.text_frame.text = str(index)
            else:
                box = slide.shapes.add_textbox(int(prs.slide_width * 0.9),
                                               int(prs.slide_height * 0.93),
                                               int(prs.slide_width * 0.05),
                                               int(prs.slide_height * 0.04))
                box.text_frame.text = str(index)
            notes = _note_lines(item)
            for ev in item.get("evidence") or []:
                ref = ev.get("ref") or ev.get("locator") or ""
                quote = ev.get("quote") or ""
                if ref or quote:
                    notes.append("证据：%s｜%s" % (ref, quote))
            if notes:
                try:
                    slide.notes_slide.notes_text_frame.text = "\n".join(notes)
                except Exception:  # noqa: BLE001
                    pass
            pages.append({"slide": index, "layout": getattr(slide.slide_layout, "name", ""),
                          "visual": visual_kind, "caption": bool(caption),
                          "evidence": len(item.get("evidence") or []),
                          "title": bool(item.get("title")), "body": bool(item.get("bullets"))})
        wanted = len(spec.get("slides", []))
        if wanted:
            _drop_slides(prs, wanted)
        prs.save(out_path)
        if any(p["visual"] == "missing-image" for p in pages):
            uncertainty.append("存在未插入图像的图表页，需把图像文件放入 materials 或改用表格")
        return {"built": True, "reason": "", "path": out_path, "tool": "python-pptx",
                "pages": pages, "uncertainty": uncertainty}
    except Exception as exc:  # noqa: BLE001
        return {"built": False, "reason": "pptx build failed: %s" % exc, "path": None,
                "tool": "python-pptx", "pages": [], "uncertainty": uncertainty}


def _try_pptx_stdlib(spec, out_path, exc):
    try:
        import pptx_min
        result = pptx_min.build(spec, out_path)
        result["uncertainty"] = ["python-pptx 不可用（%s），已用标准库兜底生成文本版 pptx；"
                                 "未继承模板母版，需在有 python-pptx 的环境复跑" % exc]
        return result
    except Exception as fallback_exc:  # noqa: BLE001
        return {"built": False,
                "reason": "python-pptx unavailable (%s); stdlib fallback failed: %s"
                          % (exc, fallback_exc),
                "path": None, "tool": "none", "pages": [], "uncertainty": []}


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


def file_sha1(path):
    import hashlib
    with open(path, "rb") as fh:
        return hashlib.sha1(fh.read()).hexdigest()
