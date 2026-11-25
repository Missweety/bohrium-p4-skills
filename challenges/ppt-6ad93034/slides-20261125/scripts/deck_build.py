#!/usr/bin/env python3
"""deck_build.py - generate an academic deck from a spec, or edit existing pages by instruction.

Subcommands:
  generate   normalise a spec written from the paper/outline, audit it, render deck.md,
             speaker_notes.md and (optionally) deck.pptx, write work/draft.json.
  edit       apply declarative page edits to a base spec, produce the edited spec plus a
             per-page diff list (JSON + Markdown), then audit and render.
  check      audit a spec only; exit 1 on hard errors.
  finalize   merge skill fields into result.json written by kernel emit.
  selfcheck  verify work/output (spec, deck, notes, diff, result).

Edit operations (edits.json: {"edits":[...]} or a bare list):
  {"slide":3,"op":"set_title","value":"...","reason":"..."}
  {"page":2,"op":"set_bullets","value":["..."],"reason":"..."}
  {"slide":4,"op":"replace_text","find":"31 um","replace":"31 微米"}
  {"slide":5,"op":"set_notes_say","value":"...","reason":"..."}
  {"slide":5,"op":"delete","reason":"..."} / {"op":"insert_after","slide":5,"value":{...}}

Rules: every page keeps one claim; numbers/figure refs must trace to the corpus; bullets
<=6 and each <=40 characters by default (overridable); notes.say is required; every edit
must carry a reason so the diff list explains *why*, not only *what*.

Usage:
  python scripts/deck_build.py generate --spec work/deck_spec.json --out work --corpus work/corpus.txt
  python scripts/deck_build.py edit --base work/deck_spec.json --edits work/edits.json --out work_edit
Exit 0 = audit clean, 1 = fix before delivering.
"""
import argparse
import copy
import json
import math
import os
import re
import sys

import spec_io

KINDS = spec_io.KINDS
DENSITY_FIELDS = ("kind", "title", "takeaway", "bullets", "visual", "notes", "seconds")
NUM = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
FIG = re.compile(r"(?:fig(?:ure)?s?\.?\s*S?\d+[a-z]?|tables?\s*S?\d+)", re.I)
LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "\u00ad": "", "’": "'"}


def norm(value):
    value = str(value or "")
    for src, dst in LIGATURES.items():
        value = value.replace(src, dst)
    return re.sub(r"\s+", "", value).lower()


def audit(spec, corpus="", max_bullets=6, max_bullet_chars=40, title_max=24):
    errors, warnings = [], []
    body = norm(corpus)
    slides = spec.get("slides", [])
    if not slides:
        errors.append("spec 没有 slides")
    for slide in slides:
        sid = "第 %d 页" % slide["index"]
        if not slide.get("title"):
            errors.append("%s 缺标题" % sid)
        elif spec_io.char_len(slide["title"]) > title_max:
            warnings.append("%s 标题超过 %d 字" % (sid, title_max))
        if slide.get("kind") not in KINDS:
            errors.append("%s 页型非法：%s" % (sid, slide.get("kind")))
        bullets = slide.get("bullets") or []
        if len(bullets) > max_bullets:
            errors.append("%s 要点 %d 条 > %d" % (sid, len(bullets), max_bullets))
        for bullet in bullets:
            if spec_io.char_len(bullet) > max_bullet_chars:
                errors.append("%s 单行 %d 字 > %d" % (sid, spec_io.char_len(bullet), max_bullet_chars))
        say = (slide.get("notes") or {}).get("say", "")
        if spec_io.char_len(say) < 20:
            errors.append("%s 缺有效讲稿（notes.say ≥20 字）" % sid)
        visual = slide.get("visual") or {}
        if visual.get("type") in ("figure", "table"):
            if not visual.get("ref"):
                errors.append("%s 图表页缺 ref" % sid)
            elif body and norm(visual["ref"]) not in body:
                errors.append("%s 图表编号原文找不到：%s" % (sid, visual["ref"]))
        if visual.get("type") == "schematic" and "示意" not in (visual.get("caption") or ""):
            warnings.append("%s 示意图图注未写“示意”" % sid)
        for ev in slide.get("evidence") or []:
            quote = ev.get("quote", "")
            if quote and len(norm(quote)) < 12:
                warnings.append("%s 证据引文过短" % sid)
            elif quote and body and norm(quote) not in body:
                errors.append("%s 证据引文非逐字：%s" % (sid, quote[:36]))
        if body and slide.get("kind") not in ("title", "backup"):
            visible = " ".join([slide["title"], slide.get("takeaway", "")] + bullets)
            for token in dict.fromkeys(NUM.findall(FIG.sub(" ", visible))):
                token = token.strip()
                if len(token) >= 2 and norm(token) not in body:
                    errors.append("%s 数字 %s 在原文找不到" % (sid, token))
    if slides and slides[0].get("kind") != "title":
        warnings.append("首页不是 title 页")
    if slides and slides[-1].get("kind") != "conclusion":
        warnings.append("末页不是 conclusion 页")
    titles = [s.get("title") for s in slides if s.get("title")]
    duplicates = sorted({t for t in titles if titles.count(t) > 1})
    if duplicates:
        warnings.append("标题重复：%s" % "、".join(duplicates[:5]))
    total = spec_io.total_seconds(spec)
    if spec.get("duration_min"):
        target = spec["duration_min"] * 60
        if total and abs(total - target) > max(30, target * 0.15):
            warnings.append("逐页秒数合计 %s 与目标 %s 相差较大" % (
                spec_io.mmss(total), spec_io.mmss(target)))
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "slide_count": len(spec_io.content_slides(spec)), "total_slides": len(slides),
            "total_seconds": total}


def write_check(report, out):
    spec_io.dump(report, os.path.join(out, "deck_check.json"))
    lines = ["# 演示稿校验", "",
             "- 主讲页：%d（总页 %d）" % (report["slide_count"], report["total_slides"]),
             "- 逐页秒数合计：%s" % spec_io.mmss(report["total_seconds"]),
             "- 硬错误：%d｜警告：%d" % (len(report["errors"]), len(report["warnings"])), "",
             "## 硬错误"] + (["- %s" % e for e in report["errors"]] or ["- 无"])
    lines += ["", "## 警告"] + (["- %s" % w for w in report["warnings"]] or ["- 无"])
    with open(os.path.join(out, "deck_check.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def render_outputs(spec, out, template="", want_pptx=True, pptx_out=""):
    os.makedirs(out, exist_ok=True)
    spec_io.dump(spec, os.path.join(out, "deck_spec.json"))
    with open(os.path.join(out, "deck.md"), "w", encoding="utf-8") as fh:
        fh.write(spec_io.render_marp(spec))
    with open(os.path.join(out, "speaker_notes.md"), "w", encoding="utf-8") as fh:
        fh.write(spec_io.render_notes(spec))
    exports, uncertainty, limits = [], [], []
    if want_pptx:
        path = pptx_out or os.path.join(out, "deck.pptx")
        built = spec_io.try_pptx(spec, path, template)
        if built["built"]:
            uncertainty.extend(built.get("warnings", []))
            limits.extend(built.get("warnings", []))
            exports.append({"path": os.path.basename(path), "format": "pptx"})
            pdf = spec_io.try_pdf(path, out)
            if pdf["built"]:
                exports.append({"path": os.path.basename(pdf["path"]), "format": "pdf"})
            else:
                limits.append("未生成 PDF 预览：%s" % pdf["reason"])
        else:
            uncertainty.append("未生成 pptx：%s" % built["reason"])
            limits.append("未产出 pptx，已交付规格 JSON、Marp 源与讲稿")
    else:
        limits.append("按 --no-pptx 跳过 pptx")
    if not exports:
        limits.append("无 PDF/PNG 预览；需要放映件请在有 python-pptx/LibreOffice 的环境复跑")
    return exports, uncertainty, limits


def build_draft(spec, report, exports, uncertainty, limits, mode, changes):
    evidence_map = []
    for slide in spec["slides"]:
        for ev in slide.get("evidence") or []:
            evidence_map.append({"slide": slide["index"], "ref": ev.get("ref"),
                                 "quote": ev.get("quote"), "locator": ev.get("locator")})
    fields = {
        "mode": mode,
        "artifact_path": exports[0]["path"] if exports else "deck.md",
        "artifact_format": "pptx" if exports else "marp-md",
        "slide_count": report["slide_count"],
        "deck_outline": spec["slides"],
        "notes_path": "speaker_notes.md",
        "diff": changes,
        "changes": changes,
        "evidence_map": evidence_map,
        "render_log": {"source": "deck_spec.json", "exports": exports,
                       "tool": "python-pptx" if exports else "none"},
        "self_check": {k: report[k] for k in ("ok", "errors", "warnings",
                                              "slide_count", "total_seconds")},
    }
    return {"case_id": spec["case_id"],
            "status": "ok" if (report["ok"] and exports and not limits) else "partial",
            "fields": fields, "uncertainty": uncertainty, "changes": changes,
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


def cmd_generate(a):
    spec = read_spec(a.spec, a.case)
    if spec is None:
        print("blocked: spec not found:", a.spec)
        return 1
    report = audit(spec, load_corpus(a.corpus), a.max_bullets, a.max_bullet_chars, a.title_max)
    exports, uncertainty, limits = render_outputs(spec, a.out, a.template, a.pptx, a.pptx_out)
    write_check(report, a.out)
    render_diff([], [], len(spec["slides"]), len(spec["slides"]), a.out)
    draft = build_draft(spec, report, exports, uncertainty, limits, "generate", [])
    spec_io.dump(draft, os.path.join(a.out, "draft.json"))
    print("generate: slides=%d errors=%d warnings=%d pptx=%s" % (
        report["total_slides"], len(report["errors"]), len(report["warnings"]),
        "yes" if exports else "no"))
    for err in report["errors"][:12]:
        print("  !", err)
    return 0 if report["ok"] else 1


# ------------------------------------------------------------------ edit mode
def _slide_copy(spec):
    return copy.deepcopy(spec)


def _target_index(spec, raw):
    try:
        num = int(raw)
    except (TypeError, ValueError):
        return None
    if 1 <= num <= len(spec["slides"]):
        return num - 1
    return None


def _replace_in(value, find, replace):
    if isinstance(value, str):
        return value.replace(find, replace)
    if isinstance(value, list):
        return [_replace_in(v, find, replace) for v in value]
    return value


def apply_edits(spec, edits):
    new = _slide_copy(spec)
    changes, failures = [], []
    structural = False
    if isinstance(edits, dict):
        edits = edits.get("edits") or edits.get("instructions") or []
    for edit in edits:
        if not isinstance(edit, dict):
            failures.append({"edit": str(edit), "reason": "edit 不是对象"})
            continue
        op = str(edit.get("op") or edit.get("action") or "").strip()
        reason = str(edit.get("reason") or edit.get("why") or "").strip()
        raw_target = edit.get("slide", edit.get("page", edit.get("index")))
        value = edit.get("value", edit.get("after", edit.get("to")))
        before = edit.get("before", edit.get("from"))
        record = {"slide": raw_target, "op": op, "reason": reason}
        if not op:
            failures.append({"slide": raw_target, "op": "", "reason": "缺少 op；先把指令翻译成声明式操作"})
            continue
        if op == "insert_after":
            pos = _target_index(new, raw_target)
            if pos is None:
                failures.append({"slide": raw_target, "op": op, "reason": "目标页不存在"})
                continue
            slide = spec_io.normalize_spec({"slides": [value]}, None)["slides"][0]
            slide["index"] = pos + 2
            new["slides"].insert(pos + 1, slide)
            structural = True
            changes.append(dict(record, field="*", before=None, after=slide.get("title")))
            continue
        idx = _target_index(new, raw_target)
        if idx is None:
            failures.append({"slide": raw_target, "op": op, "reason": "目标页不存在"})
            continue
        slide = new["slides"][idx]
        if op == "delete":
            removed = slide.get("title")
            new["slides"].pop(idx)
            structural = True
            changes.append(dict(record, field="*", before=removed, after=None))
            continue
        if op == "move":
            try:
                dest = int(value)
            except (TypeError, ValueError):
                failures.append({"slide": raw_target, "op": op, "reason": "move 需要整数目标位置"})
                continue
            moved = new["slides"].pop(idx)
            new["slides"].insert(max(0, min(len(new["slides"]), dest - 1)), moved)
            structural = True
            changes.append(dict(record, field="index", before=raw_target, after=dest))
            continue
        if op == "set_title":
            changes.append(dict(record, field="title", before=slide["title"], after=str(value)))
            slide["title"] = str(value)
        elif op == "set_takeaway":
            changes.append(dict(record, field="takeaway", before=slide["takeaway"], after=str(value)))
            slide["takeaway"] = str(value)
        elif op == "set_bullets":
            bullets = spec_io.bullet_list(value)
            changes.append(dict(record, field="bullets", before=slide["bullets"], after=bullets))
            slide["bullets"] = bullets
        elif op == "set_seconds":
            try:
                seconds = int(value)
            except (TypeError, ValueError):
                failures.append({"slide": raw_target, "op": op, "reason": "seconds 需为整数"})
                continue
            changes.append(dict(record, field="seconds", before=slide["seconds"], after=seconds))
            slide["seconds"] = seconds
        elif op in ("set_notes_say", "set_notes_why"):
            key = "say" if op.endswith("say") else "why"
            changes.append(dict(record, field="notes." + key,
                                before=slide["notes"].get(key, ""), after=str(value)))
            slide["notes"][key] = str(value)
        elif op == "add_qa":
            qa = value if isinstance(value, dict) else {"q": "", "a": str(value)}
            slide["notes"].setdefault("qa", []).append(qa)
            changes.append(dict(record, field="notes.qa", before=None, after=qa))
        elif op == "set_visual":
            visual = value if isinstance(value, dict) else {"type": "figure", "ref": str(value)}
            slide["visual"] = {"type": str(visual.get("type", "none")),
                               "ref": str(visual.get("ref", "")),
                               "caption": str(visual.get("caption", ""))}
            changes.append(dict(record, field="visual", before=None, after=slide["visual"]))
        elif op == "replace_text":
            find = str(edit.get("find") or before or "")
            replace = str(edit.get("replace") if edit.get("replace") is not None else value or "")
            if not find:
                failures.append({"slide": raw_target, "op": op, "reason": "replace_text 缺 find"})
                continue
            field = str(edit.get("field") or "all")
            for key in ("title", "takeaway", "bullets"):
                if field in ("all", key):
                    old = slide.get(key)
                    new_value = _replace_in(old, find, replace)
                    if new_value != old:
                        changes.append(dict(record, field=key, before=old, after=new_value))
                        slide[key] = new_value
        else:
            failures.append({"slide": raw_target, "op": op, "reason": "未知 op"})
    for i, slide in enumerate(new["slides"]):
        slide["index"] = i + 1
    # drift check: only meaningful when page order did not change
    if not structural:
        for i in range(min(len(spec["slides"]), len(new["slides"]))):
            old, cur = spec["slides"][i], new["slides"][i]
            for field in DENSITY_FIELDS:
                if old.get(field) != cur.get(field):
                    declared = [c for c in changes if c.get("slide") in (i + 1, str(i + 1))
                                and (c.get("field") == field or c.get("field") in ("*", "index"))]
                    if not declared:
                        changes.append({"slide": i + 1, "op": "drift", "field": field,
                                        "before": old.get(field), "after": cur.get(field),
                                        "reason": "未在 edits 中声明"})
    return new, changes, failures


def _short(value, limit=60):
    if isinstance(value, (list, tuple)):
        value = "；".join(str(v) for v in value)
    elif isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False)
    value = "—" if value in (None, "") else str(value)
    return value if len(value) <= limit else value[:limit - 1] + "…"


def render_diff(changes, failures, base_count, new_count, out):
    report = {"base_slides": base_count, "new_slides": new_count,
              "change_count": len(changes), "changes": changes, "failures": failures}
    spec_io.dump(report, os.path.join(out, "diff.json"))
    lines = ["# 编辑 diff 清单", "",
             "- 原页数：%d｜新页数：%d" % (base_count, new_count),
             "- 改动：%d 处｜未应用：%d 处" % (len(changes), len(failures)), "",
             "| 页 | 操作 | 字段 | 之前 | 之后 | 原因 |", "|-|-|-|-|-|-|"]
    if changes:
        for ch in changes:
            lines.append("| %s | %s | %s | %s | %s | %s |" % (
                ch.get("slide"), ch.get("op"), ch.get("field"),
                _short(ch.get("before")), _short(ch.get("after")),
                _short(ch.get("reason"), 40) or "（未写原因）"))
    else:
        lines.append("| - | - | - | - | - | 无实际改动 |")
    if failures:
        lines += ["", "## 未应用", "", "| 页 | 操作 | 原因 |", "|-|-|-|"]
        for item in failures:
            lines.append("| %s | %s | %s |" % (item.get("slide"), item.get("op"), item.get("reason")))
    with open(os.path.join(out, "diff.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return report


def cmd_edit(a):
    spec = read_spec(a.base, a.case)
    if spec is None:
        print("blocked: base spec not found:", a.base)
        return 1
    edits = spec_io.load_json(a.edits)
    if edits is None:
        print("blocked: edits file not found:", a.edits)
        return 1
    new_spec, changes, failures = apply_edits(spec, edits)
    report = audit(new_spec, load_corpus(a.corpus), a.max_bullets, a.max_bullet_chars, a.title_max)
    exports, uncertainty, limits = render_outputs(new_spec, a.out, a.template, a.pptx, a.pptx_out)
    write_check(report, a.out)
    diff_report = render_diff(changes, failures, len(spec["slides"]), len(new_spec["slides"]), a.out)
    if failures:
        limits.append("%d 条编辑未应用，详见 diff.md" % len(failures))
        uncertainty.extend("%s 未应用：%s" % (f.get("op"), f.get("reason")) for f in failures)
    if not changes:
        limits.append("编辑未产生实际变化")
    draft = build_draft(new_spec, report, exports, uncertainty, limits, "edit", changes)
    if not changes:
        draft["status"] = "partial"
    spec_io.dump(draft, os.path.join(a.out, "draft.json"))
    print("edit: changes=%d failures=%d slides=%d errors=%d warnings=%d" % (
        len(changes), len(failures), len(new_spec["slides"]),
        len(report["errors"]), len(report["warnings"])))
    for item in failures[:8]:
        print("  ?", item.get("slide"), item.get("op"), item.get("reason"))
    return 0 if (report["ok"] and changes and not failures) else 1


def cmd_check(a):
    spec = read_spec(a.spec, a.case)
    if spec is None:
        print("blocked: spec not found:", a.spec)
        return 1
    report = audit(spec, load_corpus(a.corpus), a.max_bullets, a.max_bullet_chars, a.title_max)
    os.makedirs(a.out, exist_ok=True)
    write_check(report, a.out)
    print("check: errors=%d warnings=%d" % (len(report["errors"]), len(report["warnings"])))
    for err in report["errors"][:12]:
        print("  !", err)
    return 0 if report["ok"] else 1


def cmd_finalize(a):
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
    if draft.get("status"):
        result["status"] = draft["status"]
    for key in ("uncertainty", "changes", "sources"):
        if not result.get(key) and draft.get(key):
            result[key] = draft[key]
    if not result.get("limits") and draft.get("limits"):
        result["limits"] = draft["limits"]
    contract = spec_io.load_json(os.path.join(a.work, "contract.json")) or {}
    from kernel import contract_field_names
    expected = contract_field_names(contract.get("contract", {}))
    missing = [key for key in expected if result.get(key) is None]
    if missing:
        result["status"] = "partial"
        note = "契约字段未产出：%s" % "、".join(missing)
        result["uncertainty"] = list(result.get("uncertainty") or []) + [note]
        result["limits"] = "；".join(x for x in (result.get("limits"), note) if x)
    spec_io.dump(result, os.path.join(a.out, "result.json"))
    print("finalize: %d fields merged" % len(draft.get("fields") or {}))
    return 0


def cmd_selfcheck(a):
    problems = []
    spec = spec_io.load_json(os.path.join(a.work, "deck_spec.json"))
    if not spec:
        problems.append("deck_spec.json missing")
        spec = {"slides": []}
    deck = os.path.join(a.work, "deck.md")
    if not os.path.exists(deck) or os.path.getsize(deck) == 0:
        problems.append("deck.md missing or empty")
    else:
        body = open(deck, encoding="utf-8").read()
        if body.count("\n---") < len(spec["slides"]):
            problems.append("deck.md has fewer slides than deck_spec")
    notes = os.path.join(a.work, "speaker_notes.md")
    if not os.path.exists(notes):
        problems.append("speaker_notes.md missing")
    else:
        count = open(notes, encoding="utf-8").read().count("## 第 ")
        if count != len(spec["slides"]):
            problems.append("speaker_notes sections %d != slides %d" % (count, len(spec["slides"])))
    diff = os.path.join(a.work, "diff.json")
    if not os.path.exists(diff):
        problems.append("diff.json missing")
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

    def density_args(parser):
        parser.add_argument("--max-bullets", type=int, default=6)
        parser.add_argument("--max-bullet-chars", type=int, default=40)
        parser.add_argument("--title-max", type=int, default=24)

    g = sub.add_parser("generate")
    g.add_argument("--spec", required=True)
    g.add_argument("--case", default="")
    g.add_argument("--corpus", default="")
    g.add_argument("--out", default="work")
    g.add_argument("--template", default="")
    g.add_argument("--pptx-out", default="")
    g.add_argument("--no-pptx", dest="pptx", action="store_false")
    density_args(g)
    g.set_defaults(fn=cmd_generate, pptx=True)

    e = sub.add_parser("edit")
    e.add_argument("--base", required=True)
    e.add_argument("--edits", required=True)
    e.add_argument("--case", default="")
    e.add_argument("--corpus", default="")
    e.add_argument("--out", default="work_edit")
    e.add_argument("--template", default="")
    e.add_argument("--pptx-out", default="")
    e.add_argument("--no-pptx", dest="pptx", action="store_false")
    density_args(e)
    e.set_defaults(fn=cmd_edit, pptx=True)

    c = sub.add_parser("check")
    c.add_argument("--spec", required=True)
    c.add_argument("--case", default="")
    c.add_argument("--corpus", default="")
    c.add_argument("--out", default="work")
    density_args(c)
    c.set_defaults(fn=cmd_check)

    f = sub.add_parser("finalize")
    f.add_argument("--work", default="work")
    f.add_argument("--out", default="/app/output")
    f.set_defaults(fn=cmd_finalize)

    s = sub.add_parser("selfcheck")
    s.add_argument("--work", default="work")
    s.set_defaults(fn=cmd_selfcheck)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
