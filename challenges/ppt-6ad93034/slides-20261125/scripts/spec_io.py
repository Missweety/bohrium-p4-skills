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
                "path": text(visual.get("path")),
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


def try_pptx(spec, out_path, template=None):
    """Best-effort pptx export. Never raises: returns {"built": bool, ...}."""
    try:
        from pptx import Presentation  # optional dependency
        from pptx.util import Inches
    except Exception as exc:  # noqa: BLE001
        return {"built": False, "reason": "python-pptx unavailable: %s" % exc, "path": None}
    try:
        if template and os.path.realpath(template) == os.path.realpath(out_path):
            return {"built": False, "reason": "output would overwrite input template", "path": None}
        if template and not os.path.isfile(template):
            return {"built": False, "reason": "requested template not found: %s" % template, "path": None}
        prs = Presentation(template) if template else Presentation()
        if not template:
            prs.slide_width = Inches(13.333)
            prs.slide_height = Inches(7.5)
        width, height = prs.slide_width, prs.slide_height
        # Template slides are examples, not source slides for a new deck.
        while len(prs.slides):
            rel = prs.slides._sldIdLst[0].rId
            prs.part.drop_rel(rel)
            prs.slides._sldIdLst.remove(prs.slides._sldIdLst[0])
        warnings = []
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
            if item.get("bullets"):
                body = _set_body(slide, item["bullets"], width, height)
            else:
                body = None
            visual = item.get("visual") or {}
            if visual.get("type") in ("figure", "photo", "schematic"):
                image = visual.get("path")
                if image and os.path.isfile(image):
                    try:
                        if body is not None:
                            body.left = int(width * .06)
                            body.width = int(width * .39)
                        from PIL import Image
                        with Image.open(image) as im:
                            iw, ih = im.size
                        boxw, boxh = width * .46, height * .53
                        scale = min(boxw / iw, boxh / ih)
                        slide.shapes.add_picture(image, int(width * .50 + (boxw - iw * scale)/2),
                                                 int(height * .22 + (boxh - ih * scale)/2),
                                                 width=int(iw * scale), height=int(ih * scale))
                        if visual.get("caption"):
                            caption = slide.shapes.add_textbox(int(width * .5), int(height * .78), int(width * .46), int(height * .1))
                            caption.text_frame.text = visual["caption"]
                    except Exception as exc:
                        warnings.append("slide %d: image not inserted: %s" % (len(prs.slides), exc))
                else:
                    warnings.append("slide %d: figure source missing: %s" % (len(prs.slides), image or "unspecified"))
            elif visual.get("type") == "table":
                warnings.append("slide %d: table data not inserted; requires manual editable table" % len(prs.slides))
            notes = _note_lines(item)
            if notes:
                try:
                    slide.notes_slide.notes_text_frame.text = "\n".join(notes)
                except Exception:  # noqa: BLE001
                    pass
        prs.save(out_path)
        return {"built": True, "reason": "", "path": out_path, "warnings": warnings}
    except Exception as exc:  # noqa: BLE001
        return {"built": False, "reason": "pptx build failed: %s" % exc, "path": None}


def try_pdf(pptx_path, out_dir):
    """Best-effort PDF preview via LibreOffice. Never raises: absence is reported as data."""
    import shutil
    import subprocess
    if not pptx_path or not os.path.exists(pptx_path):
        return {"built": False, "reason": "pptx not found", "path": None}
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return {"built": False, "reason": "LibreOffice not available", "path": None}
    import tempfile
    profile_dir = os.path.join(tempfile.gettempdir(), "lo-profile-%d" % os.getpid())
    try:
        subprocess.run([exe, "--headless",
                        "-env:UserInstallation=file://" + profile_dir,
                        "--convert-to", "pdf", "--outdir", out_dir, pptx_path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=False)
    except Exception as exc:  # noqa: BLE001
        return {"built": False, "reason": "pdf convert failed: %s" % exc, "path": None}
    pdf = os.path.join(out_dir, os.path.splitext(os.path.basename(pptx_path))[0] + ".pdf")
    if os.path.exists(pdf) and os.path.getsize(pdf) > 0:
        return {"built": True, "reason": "", "path": pdf}
    return {"built": False, "reason": "pdf not produced", "path": None}


def file_sha1(path):
    import hashlib
    with open(path, "rb") as fh:
        return hashlib.sha1(fh.read()).hexdigest()
