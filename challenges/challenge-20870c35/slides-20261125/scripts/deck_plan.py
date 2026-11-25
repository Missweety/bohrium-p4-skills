#!/usr/bin/env python3
"""deck_plan.py - build and audit an audience/time-constrained academic talk plan.

Subcommands:
  plan       normalise a deck spec, render deck.md + speaker_notes.md + timing table,
             write work/draft.json for kernel emit, try an optional pptx export.
  check      audit a spec only; exit 1 on hard errors.
  finalize   merge skill-specific fields into the result.json written by kernel emit.
  selfcheck  verify a work/output directory (artifact presence, page/notes/timing counts).

Hard rules (the competition topic asks for all four):
  * outline declares audience, duration and the mainline (problem/approach/results/conclusion);
  * every slide has a title plus <=6 bullets, each bullet <=14 non-space characters;
  * every slide has 30-60 seconds of speaking script (notes.say), not a copy of the bullets;
  * the sum of per-slide seconds stays within 10% of duration_min * 60.

Usage:
  python scripts/kernel.py init --case /input/case.json --out work
  python scripts/deck_plan.py plan --spec work/deck_spec.json --out work --corpus work/corpus.txt
Exit code 0 = no hard error, 1 = fix the plan before delivering.
"""
import argparse
import json
import math
import os
import re
import sys

import spec_io

KINDS = spec_io.KINDS
NUM = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
FIG = re.compile(r"(?:fig(?:ure)?s?\.?\s*S?\d+[a-z]?|tables?\s*S?\d+)", re.I)
LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "\u00ad": "", "’": "'"}


def norm(value):
    value = str(value or "")
    for src, dst in LIGATURES.items():
        value = value.replace(src, dst)
    return re.sub(r"\s+", "", value).lower()


def audit(spec, corpus="", min_sec=30, max_sec=60, max_bullets=6,
          max_bullet_chars=14, title_max=24, strict_numbers=False):
    errors, warnings = [], []
    slides = spec.get("slides", [])
    if not slides:
        errors.append("spec 没有 slides，无法组织汇报")
    if not spec.get("audience"):
        errors.append("缺少受众 audience：决定背景铺垫与术语深度")
    for key in ("problem", "approach", "results", "conclusion"):
        if not spec.get("mainline", {}).get(key):
            errors.append("主线缺少 %s（problem/approach/results/conclusion 必需）" % key)
    if not spec.get("mainline", {}).get("limitations"):
        warnings.append("主线未写 limitations：预判追问时容易失分")
    if not spec.get("duration_min"):
        warnings.append("未声明 duration_min，只能按逐页秒数反推总时长")

    body = norm(corpus)
    total = spec_io.total_seconds(spec)
    duration_sec = float(spec.get("duration_min") or 0) * 60
    for slide in slides:
        sid = "第 %d 页" % slide["index"]
        title = slide.get("title", "")
        if not title:
            errors.append("%s 缺标题" % sid)
        elif spec_io.char_len(title) > title_max:
            warnings.append("%s 标题 %d 字 > %d" % (sid, spec_io.char_len(title), title_max))
        if slide.get("kind") not in KINDS:
            errors.append("%s 页型非法：%s" % (sid, slide.get("kind")))
        bullets = slide.get("bullets") or []
        if not bullets:
            warnings.append("%s 没有要点（标题页可忽略）" % sid)
        if len(bullets) > max_bullets:
            errors.append("%s 要点 %d 条 > %d 条" % (sid, len(bullets), max_bullets))
        for bullet in bullets:
            if spec_io.char_len(bullet) > max_bullet_chars:
                errors.append("%s 单行 %d 字 > %d：%s" % (
                    sid, spec_io.char_len(bullet), max_bullet_chars, bullet))
        seconds = int(slide.get("seconds") or 0)
        if not min_sec <= seconds <= max_sec:
            errors.append("%s 讲稿 %d 秒，超出 %d–%d 秒区间" % (sid, seconds, min_sec, max_sec))
        say = (slide.get("notes") or {}).get("say", "")
        if spec_io.char_len(say) < 20:
            errors.append("%s 缺有效口播（notes.say 至少 20 字）" % sid)
        else:
            nsay = norm(say)
            for bullet in bullets:
                nb = norm(bullet)
                if len(nb) >= 8 and nsay.startswith(nb):
                    warnings.append("%s 口播以要点原文开头，疑似复述页面" % sid)
                    break
        visual = slide.get("visual") or {}
        if visual.get("type") in ("figure", "table"):
            if not visual.get("ref"):
                errors.append("%s 图表页缺 visual.ref（论文原编号）" % sid)
            elif body and norm(visual["ref"]) not in body:
                errors.append("%s 图表编号在原文找不到：%s" % (sid, visual["ref"]))
        if visual.get("type") == "schematic" and "示意" not in (visual.get("caption") or ""):
            warnings.append("%s 示意图图注未写“示意”" % sid)
        for ev in slide.get("evidence") or []:
            quote = ev.get("quote", "")
            if not quote:
                continue
            if len(norm(quote)) < 12:
                warnings.append("%s 证据引文过短，无法核验" % sid)
            elif body and norm(quote) not in body:
                errors.append("%s 证据引文非原文逐字：%s" % (sid, quote[:36]))
            if not ev.get("ref"):
                warnings.append("%s 证据缺 ref（Fig./Table/章节）" % sid)
        if body and slide.get("kind") not in ("title", "backup"):
            visible = " ".join([title, slide.get("takeaway", "")] + bullets)
            for token in dict.fromkeys(NUM.findall(FIG.sub(" ", visible))):
                token = token.strip()
                if len(token) >= 2 and norm(token) not in body:
                    (errors if strict_numbers else warnings).append(
                        "%s 数字 %s 在原文找不到" % (sid, token))

    if duration_sec:
        tolerance = max(30.0, duration_sec * 0.10)
        if abs(total - duration_sec) > tolerance:
            errors.append("总时长 %s 与目标 %s 差 %d 秒，超出 ±%d 秒（页数或每页秒数不匹配）" % (
                spec_io.mmss(total), spec_io.mmss(duration_sec), abs(total - duration_sec),
                int(tolerance)))
        pages = len(spec_io.content_slides(spec))
        low, high = int(math.ceil(duration_sec / max_sec)), int(math.floor(duration_sec / min_sec))
        if pages < low:
            warnings.append("主讲页 %d 少于 %d：按 %d 秒/页上限会讲不满 %s" % (
                pages, low, max_sec, spec_io.mmss(duration_sec)))
        if pages > high:
            errors.append("主讲页 %d 多于 %d：按 %d 秒/页下限会超时" % (
                pages, high, min_sec))
    if spec.get("max_slides") and len(spec_io.content_slides(spec)) > spec["max_slides"]:
        errors.append("主讲页 %d 超过题面上限 %d" % (
            len(spec_io.content_slides(spec)), spec["max_slides"]))
    if slides and slides[0].get("kind") != "title":
        warnings.append("首页不是 title 页")
    if slides and slides[-1].get("kind") != "conclusion":
        warnings.append("末页不是 conclusion 页")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "slide_count": len(spec_io.content_slides(spec)),
            "total_slides": len(slides), "total_seconds": total,
            "duration_seconds": int(duration_sec) or None}


def write_check(report, out):
    spec_io.dump(report, os.path.join(out, "deck_check.json"))
    lines = ["# 汇报内容组织校验", "",
             "- 主讲页：%d（总页 %d）" % (report["slide_count"], report["total_slides"]),
             "- 计划总时长：%s" % spec_io.mmss(report["total_seconds"]),
             "- 目标时长：%s" % (spec_io.mmss(report["duration_seconds"])
                                if report["duration_seconds"] else "未声明"),
             "- 硬错误：%d｜警告：%d" % (len(report["errors"]), len(report["warnings"])), "",
             "## 硬错误"] + (["- %s" % e for e in report["errors"]] or ["- 无"])
    lines += ["", "## 警告"] + (["- %s" % w for w in report["warnings"]] or ["- 无"])
    with open(os.path.join(out, "deck_check.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def cmd_plan(a):
    raw = spec_io.load_json(a.spec)
    if raw is None:
        print("blocked: spec not found:", a.spec)
        return 1
    case = spec_io.load_json(a.case) if a.case else None
    spec = spec_io.normalize_spec(raw, case)
    corpus = ""
    if a.corpus and os.path.exists(a.corpus):
        corpus = open(a.corpus, encoding="utf-8", errors="replace").read()
    os.makedirs(a.out, exist_ok=True)
    report = audit(spec, corpus, a.min_seconds, a.max_seconds, a.max_bullets,
                   a.max_bullet_chars, a.title_max, a.strict_numbers)

    spec_io.dump(spec, os.path.join(a.out, "deck_spec.json"))
    with open(os.path.join(a.out, "deck.md"), "w", encoding="utf-8") as fh:
        fh.write(spec_io.render_marp(spec))
    with open(os.path.join(a.out, "speaker_notes.md"), "w", encoding="utf-8") as fh:
        fh.write(spec_io.render_notes(spec))
    with open(os.path.join(a.out, "timing.md"), "w", encoding="utf-8") as fh:
        fh.write(spec_io.render_timing_md(spec))
    with open(os.path.join(a.out, "timing.csv"), "w", encoding="utf-8") as fh:
        fh.write(spec_io.timing_csv(spec))
    write_check(report, a.out)

    exports, uncertainty, limits = [], [], []
    pptx_path = a.pptx_out or os.path.join(a.out, "deck.pptx")
    if a.pptx:
        built = spec_io.try_pptx(spec, pptx_path, a.template)
        if built["built"]:
            if built.get("missing_visuals"):
                limits.append("以下页图表未能插入，请检查原始文件并修复：%s" % built["missing_visuals"])
            exports.append({"path": os.path.basename(pptx_path), "format": "pptx"})
            pdf = spec_io.try_pdf(pptx_path, a.out)
            if pdf["built"]:
                exports.append({"path": os.path.basename(pdf["path"]), "format": "pdf"})
            else:
                limits.append("未生成 PDF 预览：%s" % pdf["reason"])
        else:
            uncertainty.append("未生成 pptx：%s" % built["reason"])
            limits.append("本环境未产出 pptx；已交付幻灯片规格 JSON、Marp 源与逐页讲稿")
    else:
        limits.append("按 --no-pptx 跳过 pptx，交付规格 JSON + Marp 源 + 讲稿")
    if not exports:
        limits.append("无 PDF/PNG 预览；如需放映件请在有 python-pptx/LibreOffice 的环境复跑")

    evidence_map = []
    for slide in spec["slides"]:
        for ev in slide.get("evidence") or []:
            evidence_map.append({"slide": slide["index"], "ref": ev.get("ref"),
                                 "quote": ev.get("quote"), "locator": ev.get("locator")})
    fields = {
        "artifact_path": exports[0]["path"] if exports else "deck.md",
        "artifact_format": "pptx" if exports else "marp-md",
        "slide_count": report["slide_count"],
        "duration_min": spec["duration_min"] or None,
        "outline": {"audience": spec["audience"], "mainline": spec["mainline"]},
        "deck_outline": spec["slides"],
        "timing_table": spec_io.timing_rows(spec),
        "speaker_notes_path": "speaker_notes.md",
        "evidence_map": evidence_map,
        "render_log": {
            "source": "deck_spec.json",
            "exports": exports,
            "tool": "python-pptx" if exports else "none",
            "template": a.template or None,
        },
        "self_check": {k: report[k] for k in ("ok", "errors", "warnings", "slide_count",
                                              "total_seconds")},
    }
    draft = {"case_id": spec["case_id"],
             "status": "ok" if (report["ok"] and exports and not limits) else "partial",
             "fields": fields, "uncertainty": uncertainty, "changes": [],
             "limits": "；".join(limits), "sources": []}
    spec_io.dump(draft, os.path.join(a.out, "draft.json"))

    print("plan: slides=%d total=%s errors=%d warnings=%d pptx=%s" % (
        report["total_slides"], spec_io.mmss(report["total_seconds"]),
        len(report["errors"]), len(report["warnings"]), "yes" if exports else "no"))
    for err in report["errors"][:12]:
        print("  !", err)
    return 0 if report["ok"] else 1


def cmd_check(a):
    raw = spec_io.load_json(a.spec)
    if raw is None:
        print("blocked: spec not found:", a.spec)
        return 1
    case = spec_io.load_json(a.case) if a.case else None
    spec = spec_io.normalize_spec(raw, case)
    corpus = ""
    if a.corpus and os.path.exists(a.corpus):
        corpus = open(a.corpus, encoding="utf-8", errors="replace").read()
    report = audit(spec, corpus, a.min_seconds, a.max_seconds, a.max_bullets,
                   a.max_bullet_chars, a.title_max, a.strict_numbers)
    os.makedirs(a.out, exist_ok=True)
    write_check(report, a.out)
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
    if result.get("status") not in ("partial", "blocked", "refused", "failed") and draft.get("status"):
        result["status"] = draft["status"]
    for key in ("uncertainty", "changes", "sources"):
        if not result.get(key) and draft.get(key):
            result[key] = draft[key]
    if not result.get("limits") and draft.get("limits"):
        result["limits"] = draft["limits"]
    contract = spec_io.load_json(os.path.join(a.work, "contract.json")) or {}
    from kernel import contract_field_names, contract_type_errors
    invalid = contract_type_errors(result, contract.get("contract"))
    missing = [key for key in contract_field_names(contract.get("contract")) if result.get(key) is None]
    if missing or invalid:
        result["status"] = "partial"
        note = "契约字段缺失或类型错误：%s" % "、".join(missing + invalid)
        result["uncertainty"] = list(result.get("uncertainty") or []) + [note]
        result["limits"] = "；".join(x for x in (result.get("limits"), note) if x)
    spec_io.dump(result, os.path.join(a.out, "result.json"))
    print("finalize: %d fields merged" % len(draft.get("fields") or {}))
    return 2 if missing or invalid else 0


def cmd_selfcheck(a):
    problems = []
    spec = spec_io.load_json(os.path.join(a.work, "deck_spec.json"))
    if not spec:
        problems.append("deck_spec.json missing")
        spec = {"slides": []}
    deck = os.path.join(a.work, "deck.md")
    notes = os.path.join(a.work, "speaker_notes.md")
    if not os.path.exists(deck) or os.path.getsize(deck) == 0:
        problems.append("deck.md missing or empty")
    else:
        body = open(deck, encoding="utf-8").read()
        if body.count("\n---") < len(spec["slides"]):
            problems.append("deck.md has fewer slides than deck_spec")
    if not os.path.exists(notes):
        problems.append("speaker_notes.md missing")
    else:
        count = open(notes, encoding="utf-8").read().count("## 第 ")
        if count != len(spec["slides"]):
            problems.append("speaker_notes sections %d != slides %d" % (count, len(spec["slides"])))
    expected = spec_io.total_seconds(spec)
    rows = spec_io.timing_rows(spec)
    if sum(r["seconds"] for r in rows) != expected:
        problems.append("timing rows do not sum to total seconds")
    result = spec_io.load_json(os.path.join(a.work, "result.json"))
    if result is not None:
        for key in ("case_id", "status"):
            if not result.get(key):
                problems.append("result.json missing %s" % key)
    print("SELFCHECK PASS" if not problems else "SELFCHECK FAIL")
    for item in problems:
        print(" -", item)
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    common = dict(min_seconds=30, max_seconds=60, max_bullets=6,
                  max_bullet_chars=14, title_max=24)

    p = sub.add_parser("plan")
    p.add_argument("--spec", required=True)
    p.add_argument("--case", default="")
    p.add_argument("--corpus", default="")
    p.add_argument("--out", default="work")
    p.add_argument("--template", default="")
    p.add_argument("--pptx-out", default="")
    p.add_argument("--no-pptx", dest="pptx", action="store_false")
    p.add_argument("--strict-numbers", action="store_true")
    p.add_argument("--min-seconds", type=int, default=common["min_seconds"])
    p.add_argument("--max-seconds", type=int, default=common["max_seconds"])
    p.add_argument("--max-bullets", type=int, default=common["max_bullets"])
    p.add_argument("--max-bullet-chars", type=int, default=common["max_bullet_chars"])
    p.add_argument("--title-max", type=int, default=common["title_max"])
    p.set_defaults(fn=cmd_plan, pptx=True)

    c = sub.add_parser("check")
    c.add_argument("--spec", required=True)
    c.add_argument("--case", default="")
    c.add_argument("--corpus", default="")
    c.add_argument("--out", default="work")
    c.add_argument("--strict-numbers", action="store_true")
    c.add_argument("--min-seconds", type=int, default=common["min_seconds"])
    c.add_argument("--max-seconds", type=int, default=common["max_seconds"])
    c.add_argument("--max-bullets", type=int, default=common["max_bullets"])
    c.add_argument("--max-bullet-chars", type=int, default=common["max_bullet_chars"])
    c.add_argument("--title-max", type=int, default=common["title_max"])
    c.set_defaults(fn=cmd_check)

    s = sub.add_parser("selfcheck")
    s.add_argument("--work", default="work")
    s.set_defaults(fn=cmd_selfcheck)

    f = sub.add_parser("finalize")
    f.add_argument("--work", default="work")
    f.add_argument("--out", default="/app/output")
    f.set_defaults(fn=cmd_finalize)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
