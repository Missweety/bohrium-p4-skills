#!/usr/bin/env python3
"""deck_plan.py - plan, audit and render a paper-to-deck deliverable.

Subcommands:
  plan       normalise work/deck_spec.json, audit it, render deck.md (Marp), speaker_notes.md,
             timing.md/csv and selfcheck.json, optionally build deck.pptx + deck.pdf.
  check      audit a spec only; exit 1 on hard errors.
  finalize   merge skill fields into the result.json written by kernel emit.
  selfcheck  re-audit a delivered directory and write selfcheck.json (PASS/FAIL).

Hard rules (competition rubric):
  * 10-14 content pages (or the case max_slides when smaller), one claim per page;
  * title <=24 chars, <=6 bullets per page, each bullet <=14 non-space chars,
    page text <=180 non-space chars;
  * 30-60 seconds of script per page, sum within 10% of duration_min * 60;
  * every figure/table ref exists in the paper; every number traces back to the corpus;
  * headings are one H1 per slide (no H2/H3 inside a slide);
  * body/background contrast >=4.5, accent/background >=3.0.

Usage:
  python scripts/deck_plan.py plan --spec work/deck_spec.json --paper work/paper.json \
      --corpus work/corpus.txt --out work
Exit code 0 = no hard error, 1 = fix the spec before delivering.
"""
import argparse
import json
import math
import os
import re
import sys

import spec_io
from kernel import contract_field_names, contract_validation

KINDS = spec_io.KINDS
NUM = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
FIG = re.compile(r"(?:fig(?:ure)?s?\.?\s*S?\d+[a-z]?|tables?\s*S?\d+|图\s*\d+[a-z]?|表\s*\d+[a-z]?)", re.I)
HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
PAGE_REF = re.compile(r"(?:pp?\.?\s*|p\s|页\s*)?(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?")
LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "\u00ad": "", "’": "'"}


def norm(value):
    value = str(value or "")
    for src, dst in LIGATURES.items():
        value = value.replace(src, dst)
    return re.sub(r"\s+", "", value).lower()


def _rgb(color):
    m = HEX.match(str(color or "").strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _lum(color):
    rgb = _rgb(color)
    if rgb is None:
        return None
    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg):
    lf, lb = _lum(fg), _lum(bg)
    if lf is None or lb is None:
        return None
    hi, lo = max(lf, lb), min(lf, lb)
    return (hi + 0.05) / (lo + 0.05)


def audit(spec, corpus="", paper=None, deck_md="", notes_md="",
          min_slides=10, max_slides=14, max_bullets=6, max_bullet_chars=14,
          title_max=24, max_page_chars=180, min_sec=30, max_sec=60,
          strict_numbers=True):
    checks = []

    def add(cid, ok, level, detail):
        checks.append({"id": cid, "level": level, "ok": bool(ok), "detail": detail})

    slides = spec.get("slides", [])
    content = spec_io.content_slides(spec)
    body = norm(corpus)
    total = spec_io.total_seconds(spec)
    duration_sec = float(spec.get("duration_min") or 0) * 60

    # ---- paper parse status
    paper = paper if isinstance(paper, dict) else {}
    if paper:
        missing = paper.get("missing") or []
        add("paper.title", paper.get("title", {}).get("status") != "missing", "error",
            "论文标题已解析" if paper.get("title", {}).get("status") != "missing"
            else "论文标题未解析：封面标题需人工确认，不得编造")
        add("paper.abstract", paper.get("abstract", {}).get("status") != "missing", "warning",
            "摘要已解析" if paper.get("abstract", {}).get("status") != "missing"
            else "摘要未解析：方法/结论页需逐句回到原文")
        add("paper.conclusion", paper.get("conclusion", {}).get("status") != "missing", "warning",
            "结论已解析" if paper.get("conclusion", {}).get("status") != "missing"
            else "结论段未解析：结论页需人工对照原文并写入 uncertainty")
        add("paper.missing", not missing, "warning",
            "无缺失字段" if not missing else "缺失字段：%s（已显式标注，不补造）" % "、".join(missing))
    else:
        add("paper.source", False, "warning", "未提供 paper.json：图表编号只能按 corpus 文本核对")

    # ---- narrative
    mainline = spec.get("mainline") or {}
    for key in ("problem", "approach", "conclusion"):
        val = (mainline.get(key) or {}).get("text", "")
        add("mainline.%s" % key, bool(val.strip()), "error",
            "主线 %s 已写" % key if val.strip() else "主线缺 %s：页序将退化为按段落切块" % key)
    results = mainline.get("results") or []
    add("mainline.results", 3 <= len(results) <= 5, "warning",
        "关键结果 %d 条（建议 3–5）" % len(results))
    add("mainline.limitations", bool((mainline.get("limitations") or {}).get("text", "").strip()),
        "warning", "局限已写" if (mainline.get("limitations") or {}).get("text", "").strip()
        else "主线未写局限：追问时容易失分")

    # ---- page window
    eff_max = min(max_slides, spec["max_slides"]) if spec.get("max_slides") else max_slides
    eff_min = int(spec.get("min_slides") or min_slides)
    in_window = eff_min <= len(content) <= eff_max
    add("slides.window", in_window, "error",
        "主讲页 %d，窗口 %d–%d（含备份页共 %d）" % (len(content), eff_min, eff_max, len(slides)))
    if not slides:
        add("slides.present", False, "error", "spec 没有 slides")

    if duration_sec:
        low = int(math.ceil(duration_sec / max_sec))
        high = int(math.floor(duration_sec / min_sec))
        add("slides.feasible", low <= len(content) <= high, "warning",
            "%d 页 / %s：按 %d–%d 秒/页 %s" % (
                len(content), spec_io.mmss(duration_sec), min_sec, max_sec,
                "可行" if low <= len(content) <= high else "时间与页数不匹配（%d–%d 页更合适）" % (low, high)))
        tolerance = max(30.0, duration_sec * 0.10)
        ok = bool(total) and abs(total - duration_sec) <= tolerance
        add("timing.total", ok, "error",
            "逐页合计 %s，目标 %s，偏差 %d 秒（容差 %d 秒）" % (
                spec_io.mmss(total), spec_io.mmss(duration_sec), abs(total - duration_sec),
                int(tolerance)))
    else:
        add("timing.total", True, "warning", "未声明 duration_min：只能按逐页秒数反推总时长")
    if spec.get("duration_min") and not spec.get("audience"):
        add("audience", False, "warning", "未声明受众：背景比例与术语深度无法判定")

    titles = []
    figure_refs, ref_pages = [], []
    for slide in slides:
        sid = "第 %d 页" % slide["index"]
        title = slide.get("title", "")
        titles.append(title)
        add("slide%d.title" % slide["index"], bool(title.strip()), "error",
            "%s 标题：%s" % (sid, title or "缺失"))
        if title and spec_io.char_len(title) > title_max:
            add("slide%d.title_len" % slide["index"], False, "warning",
                "%s 标题 %d 字 > %d" % (sid, spec_io.char_len(title), title_max))
        add("slide%d.kind" % slide["index"], slide.get("kind") in KINDS, "error",
            "%s 页型：%s" % (sid, slide.get("kind")))

        bullets = slide.get("bullets") or []
        add("slide%d.bullets" % slide["index"], len(bullets) <= max_bullets, "error",
            "%s 要点 %d 条（上限 %d）" % (sid, len(bullets), max_bullets))
        long_bullets = [b for b in bullets if spec_io.char_len(b) > max_bullet_chars]
        add("slide%d.bullet_len" % slide["index"], not long_bullets, "error",
            "%s 要点长度%s" % (sid, "均 ≤%d 字" % max_bullet_chars if not long_bullets
                              else "超限：%s" % "；".join(long_bullets[:3])))
        page_text = "".join(bullets) + title + slide.get("takeaway", "")
        add("slide%d.page_chars" % slide["index"],
            spec_io.char_len(page_text) <= max_page_chars, "error",
            "%s 页面文字 %d 字（上限 %d）" % (sid, spec_io.char_len(page_text), max_page_chars))

        seconds = int(slide.get("seconds") or 0)
        add("slide%d.seconds" % slide["index"], min_sec <= seconds <= max_sec, "error",
            "%s 讲稿 %d 秒（%d–%d）" % (sid, seconds, min_sec, max_sec))
        say = (slide.get("notes") or {}).get("say", "")
        add("slide%d.notes" % slide["index"], spec_io.char_len(say) >= 60, "error",
            "%s 口播 %d 字%s" % (sid, spec_io.char_len(say),
                                "" if spec_io.char_len(say) >= 60 else "（<60 字，讲不满 30 秒）"))
        if say and spec_io.char_len(say) < seconds * 2:
            add("slide%d.notes_short" % slide["index"], False, "warning",
                "%s 口播 %d 字，按 %d 秒偏短（约 %d 字更合适）" % (
                    sid, spec_io.char_len(say), seconds, seconds * 3))
        nsay = norm(say)
        restated = [b for b in bullets if len(norm(b)) >= 8 and nsay.find(norm(b)[:max(8, int(len(norm(b)) * 0.8))]) >= 0]
        if restated:
            add("slide%d.notes_restate" % slide["index"], False, "warning",
                "%s 口播含要点原文，疑似复述页面" % sid)

        visual = slide.get("visual") or {}
        vtype, ref = visual.get("type") or "none", visual.get("ref", "")
        add("slide%d.visual_type" % slide["index"], vtype in ("figure", "table", "schematic", "photo", "none"),
            "error", "%s 图表类型：%s" % (sid, vtype))
        if vtype in ("figure", "table"):
            number_ok = bool(FIG.search(ref))
            add("slide%d.ref_number" % slide["index"], number_ok, "error",
                "%s 图表编号%s" % (sid, ref if number_ok else "缺失或非论文编号：%r" % ref))
            trace = bool(ref) and (not body or norm(ref) in body)
            add("slide%d.ref_trace" % slide["index"], trace, "error",
                "%s 图号 %s %s" % (sid, ref, "可在原文命中" if trace else "在原文找不到"))
            caption = (visual.get("caption") or "").strip()
            add("slide%d.caption" % slide["index"], bool(caption), "error",
                "%s 图注%s" % (sid, caption or "缺失（需含条件/n/误差线含义）"))
            figure_refs.append(ref)
        if vtype == "schematic" and "示意" not in (visual.get("caption") or ""):
            add("slide%d.schematic" % slide["index"], False, "warning",
                "%s 示意图图注未写“示意”" % sid)

        if slide.get("kind") not in ("title", "backup"):
            src = (slide.get("source_pages") or "").strip()
            add("slide%d.source" % slide["index"], bool(src), "error",
                "%s 来源页码%s" % (sid, src or "缺失（必须能回到论文页/行）"))
            if src:
                ref_pages.append(src)
            ev = slide.get("evidence") or []
            add("slide%d.evidence" % slide["index"], bool(ev), "error",
                "%s 证据映射 %d 条" % (sid, len(ev)))
            for j, item in enumerate(ev):
                quote = str(item.get("quote") or "")
                ok = len(norm(quote)) >= 12 and (not body or norm(quote) in body)
                add("slide%d.evidence%d" % (slide["index"], j + 1), ok, "error",
                    "%s 引文%s" % (sid, "逐字命中" if ok else "过短或非原文逐字：%s" % quote[:36]))
                add("slide%d.evidence%d_ref" % (slide["index"], j + 1), bool(item.get("ref")),
                    "error", "%s 证据 ref：%s" % (sid, item.get("ref") or "缺失"))

            visible = " ".join([title, slide.get("takeaway", "")] + bullets)
            for token in dict.fromkeys(NUM.findall(FIG.sub(" ", visible))):
                token = token.strip()
                if len(token) < 2:
                    continue
                if body and norm(token) not in body:
                    add("slide%d.number_%s" % (slide["index"], token),
                        not strict_numbers, "error" if strict_numbers else "warning",
                        "%s 数字 %s 在原文找不到" % (sid, token))

    # ---- paper figure list cross-check
    if paper:
        listed = [norm(x.get("ref")) for x in (paper.get("figures") or []) + (paper.get("tables") or [])]
        if listed:
            unknown = [r for r in figure_refs
                       if not any(norm(r).startswith(l) or l.startswith(norm(r)) for l in listed)]
            add("figures.listed", not unknown, "warning",
                "图表编号均在解析清单中" if not unknown
                else "编号不在解析清单（以原文文本为准再核）：%s" % "、".join(unknown))
        else:
            add("figures.listed", False, "warning",
                "论文图表清单未解析：编号仅按原文文本核对，需人工复核")
        page_count = paper.get("page_count")
        if page_count:
            beyond = []
            for src in ref_pages:
                nums = re.findall(r"(?:pp?\.\s*|第\s*|页\s*)(\d{1,3})", src)
                if not nums and re.fullmatch(r"\s*\d{1,3}\s*", src):
                    nums = [src.strip()]
                beyond += ["%s>%s" % (n, page_count) for n in nums if int(n) > int(page_count)]
            add("source.pages", not beyond, "warning",
                "来源页码都在论文范围" if not beyond
                else "来源页码超出论文页数：%s" % "、".join(beyond))

    # ---- heading hierarchy
    if deck_md:
        h1 = len(re.findall(r"^#\s+", deck_md, re.M))
        h2 = len(re.findall(r"^##\s+", deck_md, re.M))
        h3 = len(re.findall(r"^###\s+", deck_md, re.M))
        add("headings.deck", h1 == len(slides) and h2 == 0 and h3 == 0, "error",
            "deck.md 标题层级：H1 %d（页数 %d）/ H2 %d / H3 %d" % (h1, len(slides), h2, h3))
    if notes_md:
        h1 = len(re.findall(r"^#\s+", notes_md, re.M))
        sections = notes_md.count("\n## 第 ")
        add("headings.notes", h1 == 1 and sections == len(slides), "error",
            "speaker_notes.md：H1 %d / 页小节 %d（页数 %d）" % (h1, sections, len(slides)))

    # ---- contrast
    theme = spec.get("theme") or spec_io.DEFAULT_THEME
    body_ratio = contrast(theme.get("fg"), theme.get("bg"))
    accent_ratio = contrast(theme.get("accent"), theme.get("bg"))
    add("contrast.body", body_ratio is not None and body_ratio >= 4.5, "error",
        "正文/背景对比度 %s（阈值 4.5）" % ("%.2f" % body_ratio if body_ratio else "无法解析"))
    add("contrast.accent", accent_ratio is not None and accent_ratio >= 3.0, "warning",
        "强调/背景对比度 %s（阈值 3.0）" % ("%.2f" % accent_ratio if accent_ratio else "无法解析"))

    # ---- order + duplicates
    if slides and slides[0].get("kind") != "title":
        add("order.first", False, "warning", "首页不是 title 页")
    if slides and slides[-1].get("kind") != "conclusion":
        add("order.last", False, "warning", "末页不是 conclusion 页")
    dups = sorted({t for t in titles if t and titles.count(t) > 1})
    if dups:
        add("titles.unique", False, "warning", "标题重复：%s" % "、".join(dups[:5]))

    errors = [c["detail"] for c in checks if not c["ok"] and c["level"] == "error"]
    warnings = [c["detail"] for c in checks if not c["ok"] and c["level"] == "warning"]
    return {"ok": not errors, "checks": checks, "errors": errors, "warnings": warnings,
            "slide_count": len(content), "total_slides": len(slides),
            "total_seconds": total, "duration_seconds": int(duration_sec) or None,
            "page_window": [eff_min, eff_max]}


def write_check(report, out):
    spec_io.dump(report, os.path.join(out, "deck_check.json"))
    lines = ["# 演示大纲校验", "",
             "- 主讲页：%d（总页 %d，窗口 %d–%d）" % (
                 report["slide_count"], report["total_slides"],
                 report["page_window"][0], report["page_window"][1]),
             "- 逐页合计：%s｜目标：%s" % (
                 spec_io.mmss(report["total_seconds"]),
                 spec_io.mmss(report["duration_seconds"]) if report["duration_seconds"] else "未声明"),
             "- 硬错误：%d｜警告：%d" % (len(report["errors"]), len(report["warnings"])), "",
             "## 硬错误"] + (["- %s" % e for e in report["errors"]] or ["- 无"])
    lines += ["", "## 警告"] + (["- %s" % w for w in report["warnings"]] or ["- 无"])
    with open(os.path.join(out, "deck_check.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def write_selfcheck(report, spec, out, exports=None, extra=None):
    artifact_checks = []
    def add(cid, ok, level, detail):
        artifact_checks.append({"id": cid, "level": level, "ok": bool(ok), "detail": detail})

    deck = os.path.join(out, "deck.md")
    notes = os.path.join(out, "speaker_notes.md")
    timing = os.path.join(out, "timing.csv")
    add("artifact.deck_md", os.path.exists(deck) and os.path.getsize(deck) > 0, "error",
        "deck.md 存在且非空" if os.path.exists(deck) and os.path.getsize(deck) > 0 else "deck.md 缺失")
    add("artifact.notes", os.path.exists(notes) and os.path.getsize(notes) > 0, "error",
        "speaker_notes.md 存在且非空" if os.path.exists(notes) and os.path.getsize(notes) > 0
        else "speaker_notes.md 缺失")
    add("artifact.timing", os.path.exists(timing) and os.path.getsize(timing) > 0, "error",
        "timing.csv 存在" if os.path.exists(timing) and os.path.getsize(timing) > 0 else "timing.csv 缺失")
    if os.path.exists(deck):
        text = open(deck, encoding="utf-8").read()
        add("artifact.deck_pages", len(re.findall(r"^#\s+", text, re.M)) == len(spec["slides"]), "error",
            "deck.md 页标题数 = 页数（%d）" % len(spec["slides"]))
    if os.path.exists(notes):
        text = open(notes, encoding="utf-8").read()
        add("artifact.notes_pages", text.count("\n## 第 ") == len(spec["slides"]), "error",
            "讲稿小节数 = 页数（%d）" % len(spec["slides"]))
    rows = spec_io.timing_rows(spec)
    add("artifact.timing_sum", sum(r["seconds"] for r in rows) == spec_io.total_seconds(spec), "error",
        "时间表逐页合计 = 总时长（%d 秒）" % spec_io.total_seconds(spec))
    if exports is not None:
        add("artifact.exports", True, "warning",
            "导出件：%s" % (", ".join(e["path"] for e in exports) if exports else "无（降级交付）"))

    checks = report["checks"] + artifact_checks
    errors = [c["detail"] for c in checks if not c["ok"] and c["level"] == "error"]
    warnings = [c["detail"] for c in checks if not c["ok"] and c["level"] == "warning"]
    payload = {
        "verdict": "PASS" if not errors else "FAIL",
        "pass": not errors,
        "summary": {"pages": len(spec["slides"]), "content_pages": report["slide_count"],
                    "total_seconds": report["total_seconds"],
                    "duration_seconds": report["duration_seconds"],
                    "errors": len(errors), "warnings": len(warnings)},
        "checks": checks, "errors": errors, "warnings": warnings,
    }
    if extra:
        payload.update(extra)
    spec_io.dump(payload, os.path.join(out, "selfcheck.json"))
    return payload


def render_outputs(spec, out, template="", want_pptx=True, pptx_out="", materials_dir=""):
    os.makedirs(out, exist_ok=True)
    spec_io.dump(spec, os.path.join(out, "deck_spec.json"))
    deck_md = spec_io.render_marp(spec)
    notes_md = spec_io.render_notes(spec)
    with open(os.path.join(out, "deck.md"), "w", encoding="utf-8") as fh:
        fh.write(deck_md)
    with open(os.path.join(out, "speaker_notes.md"), "w", encoding="utf-8") as fh:
        fh.write(notes_md)
    with open(os.path.join(out, "timing.md"), "w", encoding="utf-8") as fh:
        fh.write(spec_io.render_timing_md(spec))
    with open(os.path.join(out, "timing.csv"), "w", encoding="utf-8") as fh:
        fh.write(spec_io.timing_csv(spec))

    exports, uncertainty, limits = [], [], []
    if want_pptx:
        path = pptx_out or os.path.join(out, "deck.pptx")
        built = spec_io.try_pptx(spec, path, template, materials_dir)
        uncertainty.extend(built.get("uncertainty") or [])
        if built["built"]:
            exports.append({"path": os.path.basename(path), "format": "pptx"})
            pdf = spec_io.try_pdf(path, out)
            if pdf["built"]:
                exports.append({"path": os.path.basename(pdf["path"]), "format": "pdf"})
            else:
                limits.append("未生成 PDF 预览：%s" % pdf["reason"])
        else:
            uncertainty.append("未生成 pptx：%s" % built["reason"])
            limits.append("PPTX 生成失败：%s；已交付 deck_spec.json、Marp 源与逐页讲稿" % built.get("reason", "unknown"))
    else:
        limits.append("按 --no-pptx 跳过 pptx")
    if not exports:
        limits.append("无放映/预览导出件；需在有 python-pptx/LibreOffice 的环境复跑")
    return deck_md, notes_md, exports, uncertainty, limits


def build_draft(spec, report, exports, uncertainty, limits):
    evidence_map = []
    for slide in spec["slides"]:
        for ev in slide.get("evidence") or []:
            evidence_map.append({"slide": slide["index"], "ref": ev.get("ref"),
                                 "quote": ev.get("quote"), "locator": ev.get("locator")})
    fields = {
        "artifact_path": exports[0]["path"] if exports else "deck.md",
        "artifact_format": "pptx" if any(e["format"] == "pptx" for e in exports) else "md",
        "slide_count": report["slide_count"],
        "duration_min": spec["duration_min"] or None,
        "mainline": spec["mainline"],
        "narrative": spec["mainline"],
        "deck_outline": spec["slides"],
        "timing_table": spec_io.timing_rows(spec),
        "notes_path": "speaker_notes.md",
        "evidence_map": evidence_map,
        "render_log": {"source": "deck_spec.json", "exports": exports,
                       "tool": "python-pptx" if exports else "none",
                       "preview": "deck.pdf" if any(e["format"] == "pdf" for e in exports) else None},
        "self_check": {"verdict": "PASS" if report["ok"] else "FAIL",
                       "errors": len(report["errors"]), "warnings": len(report["warnings"]),
                       "slide_count": report["slide_count"],
                       "total_seconds": report["total_seconds"]},
        "theme": spec["theme"],
    }
    return {"case_id": spec["case_id"],
            "status": "ok" if (report["ok"] and any(e["format"] == "pptx" for e in exports) and any(e["format"] == "pdf" for e in exports) and not uncertainty and not limits)
            else "partial",
            "fields": fields, "uncertainty": uncertainty, "changes": [],
            "limits": "；".join(limits), "sources": []}


def load_corpus(path):
    if path and os.path.exists(path):
        return open(path, encoding="utf-8", errors="replace").read()
    return ""


def read_spec(path, case=""):
    raw = spec_io.load_json(path)
    if raw is None:
        return None
    case_data = spec_io.load_json(case) if case else None
    return spec_io.normalize_spec(raw, case_data)


def _args_bounds(a):
    return dict(min_slides=a.min_slides, max_slides=a.max_slides,
                max_bullets=a.max_bullets, max_bullet_chars=a.max_bullet_chars,
                title_max=a.title_max, max_page_chars=a.max_page_chars,
                min_sec=a.min_seconds, max_sec=a.max_seconds,
                strict_numbers=a.strict_numbers)


def cmd_plan(a):
    spec = read_spec(a.spec, a.case)
    if spec is None:
        print("blocked: spec not found:", a.spec)
        return 1
    paper = spec_io.load_json(a.paper) if a.paper else None
    corpus = load_corpus(a.corpus)
    materials_dir = (os.path.join(os.path.dirname(os.path.abspath(a.case)), "materials")
                     if a.case else "")
    deck_md, notes_md, exports, uncertainty, limits = render_outputs(
        spec, a.out, a.template, a.pptx, a.pptx_out, materials_dir)
    report = audit(spec, corpus, paper, deck_md, notes_md, **_args_bounds(a))
    write_check(report, a.out)
    payload = write_selfcheck(report, spec, a.out, exports)
    draft = build_draft(spec, report, exports, uncertainty, limits)
    spec_io.dump(draft, os.path.join(a.out, "draft.json"))

    print("plan: slides=%d total=%s errors=%d warnings=%d pptx=%s selfcheck=%s" % (
        report["total_slides"], spec_io.mmss(report["total_seconds"]),
        len(report["errors"]), len(report["warnings"]),
        "yes" if any(e["format"] == "pptx" for e in exports) else "no", payload["verdict"]))
    for err in report["errors"][:12]:
        print("  !", err)
    for warn in report["warnings"][:8]:
        print("  ~", warn)
    return 0 if report["ok"] else 1


def cmd_check(a):
    spec = read_spec(a.spec, a.case)
    if spec is None:
        print("blocked: spec not found:", a.spec)
        return 1
    paper = spec_io.load_json(a.paper) if a.paper else None
    deck_md = spec_io.render_marp(spec)
    notes_md = spec_io.render_notes(spec)
    report = audit(spec, load_corpus(a.corpus), paper, deck_md, notes_md, **_args_bounds(a))
    os.makedirs(a.out, exist_ok=True)
    write_check(report, a.out)
    write_selfcheck(report, spec, a.out, None)
    print("check: errors=%d warnings=%d" % (len(report["errors"]), len(report["warnings"])))
    for err in report["errors"][:12]:
        print("  !", err)
    return 0 if report["ok"] else 1


def cmd_finalize(a):
    """Merge the skill's extra fields into the result.json written by kernel emit."""
    draft = spec_io.load_json(os.path.join(a.work, "draft.json"))
    result = spec_io.load_json(os.path.join(a.out, "result.json"))
    if draft is None or result is None:
        print("FAIL: draft.json or result.json missing")
        return 1
    for key, value in (draft.get("fields") or {}).items():
        if result.get(key) in (None, "", [], {}):
            result[key] = value
    if draft.get("case_id"):
        result["case_id"] = draft["case_id"]
    if draft.get("status") and result.get("status") not in ("partial", "blocked", "refused"):
        result["status"] = draft["status"]
    for key in ("uncertainty", "changes", "sources"):
        if not result.get(key) and draft.get(key):
            result[key] = draft[key]
    if not result.get("limits") and draft.get("limits"):
        result["limits"] = draft["limits"]
    contract = spec_io.load_json(os.path.join(a.work, "contract.json")) or {}
    if isinstance(contract, dict):
        raw_contract = contract.get("contract")
        if raw_contract is None:
            raw_contract = contract.get("output_contract", contract)
    else:
        raw_contract = contract
    expected = contract_field_names(raw_contract)
    missing = [key for key in expected if result.get(key) is None]
    result["contract_fields"] = len(expected)
    result["contract_missing"] = missing
    invalid = contract_validation(result, raw_contract)
    if missing or invalid:
        note = "契约字段缺失或类型错误：%s" % "、".join(missing + invalid)
        result["uncertainty"] = list(result.get("uncertainty") or []) + [note]
        result["limits"] = "；".join(x for x in (result.get("limits"), note) if x)
        result["status"] = "partial"
    spec_io.dump(result, os.path.join(a.out, "result.json"))
    print("finalize: %d fields merged" % len(draft.get("fields") or {}))
    return 2 if missing or invalid else 0


def cmd_selfcheck(a):
    spec = spec_io.load_json(os.path.join(a.work, "deck_spec.json"))
    if not spec:
        print("SELFCHECK FAIL - deck_spec.json missing")
        return 1
    spec = spec_io.normalize_spec(spec)
    paper = spec_io.load_json(a.paper) if a.paper else spec_io.load_json(
        os.path.join(a.work, "paper.json"))
    deck = os.path.join(a.work, "deck.md")
    notes = os.path.join(a.work, "speaker_notes.md")
    deck_md = open(deck, encoding="utf-8").read() if os.path.exists(deck) else ""
    notes_md = open(notes, encoding="utf-8").read() if os.path.exists(notes) else ""
    corpus = load_corpus(a.corpus or os.path.join(a.work, "corpus.txt"))
    report = audit(spec, corpus, paper, deck_md, notes_md, **_args_bounds(a))
    payload = write_selfcheck(report, spec, a.work)
    result = spec_io.load_json(os.path.join(a.work, "result.json"))
    if result is not None and not (result.get("case_id") and result.get("status")):
        payload["verdict"] = "FAIL"
        payload["errors"] = list(payload["errors"]) + ["result.json 缺 case_id/status"]
        spec_io.dump(payload, os.path.join(a.work, "selfcheck.json"))
    print("%s verdict=%s errors=%d warnings=%d" % (
        "SELFCHECK PASS" if payload["verdict"] == "PASS" else "SELFCHECK FAIL",
        payload["verdict"], len(payload["errors"]), len(payload["warnings"])))
    for item in payload["errors"][:12]:
        print(" -", item)
    return 0 if payload["verdict"] == "PASS" else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def rule_args(parser):
        parser.add_argument("--min-slides", type=int, default=10)
        parser.add_argument("--max-slides", type=int, default=14)
        parser.add_argument("--max-bullets", type=int, default=6)
        parser.add_argument("--max-bullet-chars", type=int, default=14)
        parser.add_argument("--title-max", type=int, default=24)
        parser.add_argument("--max-page-chars", type=int, default=180)
        parser.add_argument("--min-seconds", type=int, default=30)
        parser.add_argument("--max-seconds", type=int, default=60)
        parser.add_argument("--lenient-numbers", dest="strict_numbers", action="store_false")

    p = sub.add_parser("plan")
    p.add_argument("--spec", required=True)
    p.add_argument("--case", default="")
    p.add_argument("--paper", default="")
    p.add_argument("--corpus", default="")
    p.add_argument("--out", default="work")
    p.add_argument("--template", default="")
    p.add_argument("--pptx-out", default="")
    p.add_argument("--no-pptx", dest="pptx", action="store_false")
    rule_args(p)
    p.set_defaults(fn=cmd_plan, pptx=True, strict_numbers=True)

    c = sub.add_parser("check")
    c.add_argument("--spec", required=True)
    c.add_argument("--case", default="")
    c.add_argument("--paper", default="")
    c.add_argument("--corpus", default="")
    c.add_argument("--out", default="work")
    rule_args(c)
    c.set_defaults(fn=cmd_check, strict_numbers=True)

    f = sub.add_parser("finalize")
    f.add_argument("--work", default="work")
    f.add_argument("--out", default="/app/output")
    f.set_defaults(fn=cmd_finalize)

    s = sub.add_parser("selfcheck")
    s.add_argument("--work", default="work")
    s.add_argument("--paper", default="")
    s.add_argument("--corpus", default="")
    rule_args(s)
    s.set_defaults(fn=cmd_selfcheck, strict_numbers=True)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
