#!/usr/bin/env python3
"""verify_format.py - compare the produced DOCX against the normalized spec.

Every requirement is reported with expected value, observed value, status and a
location inside the OOXML package:
  applied / partial / unsupported / not_applicable / failed

Writes format_report.json under --output. Honest rule: a requirement is only
"applied" when the value was read back from the generated file; rendering-only
properties that cannot be inspected (e.g. column balance) stay "partial".
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

PLACEHOLDERS = [r"\{\{", r"\}\}", r"\bTODO\b", r"\bTBD\b", r"\bXXX\b",
                r"lorem ipsum", r"\[\[missing image", r"待补充", r"待定",
                r"\?\?\?"]


def fmt_num(value, digits=2):
    if isinstance(value, float):
        return ("%." + str(digits) + "f") % value
    return str(value)


class Report(object):
    def __init__(self):
        self.requirements = []
        self.notes = []

    def add(self, req_id, requirement, expected, actual, status, location,
            note=None):
        item = {"id": req_id, "requirement": requirement,
                "expected": expected, "actual": actual, "status": status,
                "location": location}
        if note:
            item["note"] = note
        self.requirements.append(item)
        return item

    def summary(self):
        out = {"applied": 0, "partial": 0, "unsupported": 0,
               "not_applicable": 0, "failed": 0}
        for item in self.requirements:
            out[item["status"]] = out.get(item["status"], 0) + 1
        out["total"] = len(self.requirements)
        return out


def sub_el(el, *path):
    node = el
    for tag in path:
        if node is None:
            return None
        node = node.find(C.qn("w", tag))
    return node


def attr(el, name):
    return el.get(C.qn("w", name)) if el is not None else None


def first_caption_label(blocks, kind):
    for block in blocks:
        if block.get("type") == "caption" and block.get("kind") == kind:
            return block.get("label")
    return None


def first_caption_sep(blocks, kind):
    for block in blocks:
        if block.get("type") == "caption" and block.get("kind") == kind:
            return block.get("separator")
    return None


def body_items(root):
    items = []
    body = root.find(C.qn("w", "body"))
    if body is None:
        return items
    for child in body:
        name = C.local(child.tag)
        if name == "p":
            ppr = child.find(C.qn("w", "pPr"))
            pstyle = attr(sub_el(ppr, "pStyle"), "val")
            numpr = ppr.find(C.qn("w", "numPr")) if ppr is not None else None
            ilvl = attr(sub_el(numpr, "ilvl"), "val") if numpr is not None else None
            numid = attr(sub_el(numpr, "numId"), "val") if numpr is not None else None
            has_drawing = any(C.local(el.tag) == "drawing" for el in child.iter())
            items.append({"kind": "p", "text": C.paragraph_text(child).strip(),
                          "style": pstyle, "ilvl": ilvl, "numId": numid,
                          "drawing": has_drawing, "keepNext":
                          ppr is not None and ppr.find(C.qn("w", "keepNext")) is not None})
        elif name == "tbl":
            items.append({"kind": "tbl", "text": ""})
    return items


def rel_targets(docx, part):
    root = docx.xml(part)
    out = {}
    if root is None:
        return out
    for rel in root:
        out[rel.get("Id")] = rel.get("Target")
    return out


def footer_parts(docx, sect):
    parts = {}
    targets = rel_targets(docx, "word/_rels/document.xml.rels")
    for rid in (sect.get("footer_ref"),):
        target = targets.get(rid)
        if target:
            name = "word/" + target.lstrip("/").replace("word/", "")
            parts[name] = docx.text_xml(name)
    for name in docx.names:
        if re.match(r"^word/footer\d+\.xml$", name):
            parts.setdefault(name, docx.text_xml(name))
    return parts


def header_parts(docx, sect):
    parts = {}
    targets = rel_targets(docx, "word/_rels/document.xml.rels")
    target = targets.get(sect.get("header_ref"))
    if target:
        name = "word/" + target.lstrip("/").replace("word/", "")
        parts[name] = docx.text_xml(name)
    for name in docx.names:
        if re.match(r"^word/header\d+\.xml$", name):
            parts.setdefault(name, docx.text_xml(name))
    return parts


def table_borders(tbl):
    tblpr = tbl.find(C.qn("w", "tblPr"))
    borders = tblpr.find(C.qn("w", "tblBorders")) if tblpr is not None else None
    out = {}
    if borders is not None:
        for el in borders:
            out[C.local(el.tag)] = {"val": attr(el, "val"), "sz": attr(el, "sz")}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify DOCX against the format spec")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--output", default="/app/output")
    ap.add_argument("--docx", help="docx path override")
    ap.add_argument("--spec", help="spec.json override")
    ap.add_argument("--inputs", help="inputs.json override")
    args = ap.parse_args(argv)

    inputs = C.read_json(args.inputs or os.path.join(args.work, "inputs.json"), {}) or {}
    spec = C.read_json(args.spec or os.path.join(args.work, "spec.json"), {}) or {}
    build_meta = C.read_json(os.path.join(args.output, "build_meta.json"), {}) or {}
    docx_path = args.docx or build_meta.get("docx") or os.path.join(
        args.output, "manuscript_formatted.docx")
    rep = Report()
    report = {"schema": "format-report/v1",
              "case_id": (inputs.get("case") or {}).get("case_id"),
              "docx": os.path.abspath(docx_path) if docx_path else None,
              "spec_sources": (spec.get("meta") or {}).get("spec_sources"),
              "conflicts": spec.get("conflicts") or [],
              "requirements": rep.requirements,
              "verification": {}, "issues": [], "notes": []}
    blocks = (inputs.get("manuscript") or {}).get("blocks") or []
    page = spec.get("page") or {}
    body = spec.get("body") or {}
    headings = spec.get("headings") or {}
    captions = spec.get("captions") or {}
    refs = spec.get("references") or {}
    pn = spec.get("page_numbers") or {}
    header = spec.get("header") or {}
    num_spec = spec.get("heading_numbering") or {}
    tables_spec = spec.get("tables") or {}
    prov = spec.get("provenance") or {}

    def is_default(path):
        return ((prov.get(path) or {}).get("source") or "").startswith("builtin-default")

    ok, reason = C.docx_valid(docx_path)
    rep.add("docx.readable", "DOCX 可打开（zip + document.xml 解析）",
            "valid OOXML package", reason, "applied" if ok else "failed",
            "word/document.xml")
    if not ok:
        out = os.path.join(args.output, "format_report.json")
        report["summary"] = rep.summary()
        report["verification"] = {"docx_reopens": False, "reason": reason}
        C.write_json(out, report)
        print(json.dumps({"verdict": "FAIL", "reason": reason}, ensure_ascii=False))
        return 1

    docx = C.Docx(docx_path)
    try:
        root = docx.xml("word/document.xml")
        styles_root = docx.xml("word/styles.xml")
        numbering_root = docx.xml("word/numbering.xml") if docx.has(
            "word/numbering.xml") else None
        smap, by_name = C.style_map(styles_root)
        dd = C.doc_defaults(styles_root)
        sect = C.sect_properties(root)
        items = body_items(root)
        paragraph_items = [x for x in items if x["kind"] == "p"]
        tables = list(root.iter(C.qn("w", "tbl")))
        numbering, abstracts = C.numbering_map(numbering_root)
        texts = [x["text"] for x in paragraph_items]
        all_text = "\n".join(texts)
        fonts_in_body = []

        def resolved_style(sid):
            info = smap.get(sid) or {}
            return info

        # ---------------------------------------------------- page / section
        width_cm = C.twips_to_cm(sect.get("page_width_twips"))
        height_cm = C.twips_to_cm(sect.get("page_height_twips"))
        exp_w = float(page.get("width_cm") or 21.0)
        exp_h = float(page.get("height_cm") or 29.7)
        match = (width_cm is not None and abs(width_cm - exp_w) <= 0.06 and
                 abs((height_cm or 0) - exp_h) <= 0.06)
        rep.add("page.size",
                "纸张尺寸 %s" % (page.get("size_name") or "custom"),
                "%.2f x %.2f cm" % (exp_w, exp_h),
                "%.2f x %.2f cm" % (width_cm or 0, height_cm or 0),
                "applied" if match else "failed",
                "word/document.xml#sectPr/pgSz w=%s h=%s"
                % (sect.get("page_width_twips"), sect.get("page_height_twips")))

        margins = page.get("margins_cm") or {}
        obs_margins = {side: C.twips_to_cm((sect.get("margins_twips") or {}).get(side))
                       for side in ("top", "bottom", "left", "right")}
        margin_ok = all(obs_margins.get(side) is not None and
                        abs(obs_margins[side] - float(margins.get(side) or 0)) <= 0.06
                        for side in ("top", "bottom", "left", "right"))
        rep.add("page.margins", "页边距（上/下/左/右）",
                " / ".join("%s=%scm" % (s, margins.get(s)) for s in
                           ("top", "bottom", "left", "right")),
                " / ".join("%s=%scm" % (s, obs_margins.get(s)) for s in
                           ("top", "bottom", "left", "right")),
                "applied" if margin_ok else "failed",
                "word/document.xml#sectPr/pgMar %s"
                % (sect.get("margins_twips") or {}))

        orientation = page.get("orientation") or "portrait"
        obs_orient = sect.get("orientation") or (
            "landscape" if (width_cm or 0) > (height_cm or 0) else "portrait")
        rep.add("page.orientation", "页面方向",
                orientation, obs_orient,
                "applied" if obs_orient == orientation else "failed",
                "word/document.xml#sectPr/pgSz@orient")

        columns = int(page.get("columns") or 1)
        obs_cols = int(sect.get("columns") or 1)
        if columns == 1:
            rep.add("page.columns", "单栏排版", 1, obs_cols,
                    "applied" if obs_cols == 1 else "failed",
                    "word/document.xml#sectPr/w:cols@num")
        else:
            rep.add("page.columns", "%d 栏排版" % columns, columns, obs_cols,
                    "partial" if obs_cols == columns else "failed",
                    "word/document.xml#sectPr/w:cols@num",
                    "栏属性已写入 OOXML；分栏平衡需要渲染/人工目检，本报告不宣称已目检")

        # ---------------------------------------------------- body text
        normal = resolved_style("Normal")
        latin = normal.get("font_latin") or dd.get("font_latin")
        east = normal.get("font_east_asia") or dd.get("font_east_asia")
        exp_latin = body.get("font_latin")
        exp_east = body.get("font_east_asia") or exp_latin
        font_ok = (latin or "").lower() == (exp_latin or "").lower()
        rep.add("body.font", "正文字体",
                "%s (eastAsia=%s)" % (exp_latin, exp_east),
                "%s (eastAsia=%s)" % (latin, east),
                "applied" if font_ok else "failed",
                "word/styles.xml#style[Normal]/w:rPr/w:rFonts")

        exp_size = float(body.get("size_pt") or 12)
        obs_size = normal.get("size_pt") or dd.get("size_pt")
        rep.add("body.size", "正文字号",
                "%spt" % fmt_num(exp_size), "%spt" % fmt_num(obs_size or 0),
                "applied" if obs_size and abs(obs_size - exp_size) <= 0.1 else "failed",
                "word/styles.xml#style[Normal]/w:sz")

        line = body.get("line_spacing") or {"type": "multiple", "value": 1.5}
        obs_line = normal.get("spacing_line")
        obs_rule = (normal.get("line_rule") or "auto")
        if line.get("type") == "exact":
            exp_line = round(float(line.get("value_pt") or 12) * 20)
            actual_desc = "%spt (exact)" % fmt_num((obs_line or 0) / 20.0)
        else:
            exp_line = int(round(240 * float(line.get("value") or 1)))
            actual_desc = "%s lines" % fmt_num((obs_line or 0) / 240.0, 2)
        line_ok = obs_line is not None and abs(obs_line - exp_line) <= 12 and (
            (line.get("type") == "exact") == (obs_rule == "exact"))
        rep.add("body.line_spacing", "正文行距",
                ("%spt 固定值" % line.get("value_pt")
                 if line.get("type") == "exact"
                 else "%s 倍行距" % line.get("value")),
                actual_desc, "applied" if line_ok else "failed",
                "word/styles.xml#style[Normal]/w:spacing")

        exp_indent = float(body.get("first_line_indent_cm") or 0)
        obs_indent = normal.get("first_line_twips") or 0
        indent_cm = C.twips_to_cm(obs_indent) or 0
        rep.add("body.first_line_indent", "正文首行缩进",
                "%scm" % fmt_num(exp_indent), "%scm" % fmt_num(indent_cm),
                "applied" if abs(indent_cm - exp_indent) <= 0.06 else "failed",
                "word/styles.xml#style[Normal]/w:ind@firstLine")

        exp_align = body.get("alignment") or "both"
        obs_align = normal.get("align") or dd.get("align") or "left"
        rep.add("body.alignment", "正文对齐",
                {"both": "两端对齐", "left": "左对齐", "center": "居中",
                 "right": "右对齐"}.get(exp_align, exp_align),
                obs_align,
                "applied" if obs_align == exp_align else "failed",
                "word/styles.xml#style[Normal]/w:jc")

        # ---------------------------------------------------- heading styles
        heading_paras = [x for x in paragraph_items
                         if x.get("style") and re.match(r"^Heading[1-4]$", x["style"])]
        max_lvl = max([int(k) for k in headings if str(k).isdigit()] + [1])
        heading_levels_ok = True
        for lvl in range(1, max_lvl + 1):
            cfg = headings.get(str(lvl)) or {}
            sid = "Heading%d" % lvl
            info = smap.get(sid)
            if not info:
                rep.add("heading.%d.style" % lvl, "%d 级标题样式已定义" % lvl,
                        sid, "missing", "failed", "word/styles.xml#style[%s]" % sid)
                heading_levels_ok = False
                continue
            problems = []
            if cfg.get("size_pt") and info.get("size_pt") is not None and \
                    abs(float(cfg["size_pt"]) - float(info["size_pt"])) > 0.1:
                problems.append("字号 %s != %s" % (info.get("size_pt"),
                                                  cfg.get("size_pt")))
            if cfg.get("bold") is not None and bool(info.get("bold")) != bool(
                    cfg.get("bold")):
                problems.append("加粗不符")
            if cfg.get("alignment") and (info.get("align") or "left") != cfg["alignment"]:
                problems.append("对齐 %s != %s" % (info.get("align"),
                                                  cfg.get("alignment")))
            if info.get("outline_level") != lvl - 1:
                problems.append("outlineLvl=%s != %d" % (info.get("outline_level"),
                                                         lvl - 1))
            used = sum(1 for x in heading_paras if x["style"] == sid)
            note = "使用 %d 段" % used
            rep.add("heading.%d.style" % lvl, "%d 级标题样式属性" % lvl,
                    "size=%spt bold=%s align=%s outlineLvl=%d" % (
                        cfg.get("size_pt"), cfg.get("bold"),
                        cfg.get("alignment") or "left", lvl - 1),
                    "size=%spt bold=%s align=%s outlineLvl=%s" % (
                        info.get("size_pt"), info.get("bold"),
                        info.get("align") or "left", info.get("outline_level")),
                    "applied" if not problems else "failed",
                    "word/styles.xml#style[%s]" % sid,
                    "; ".join(problems) + ("; " + note if note else ""))
            if problems:
                heading_levels_ok = False

        expected_levels = [b.get("level") for b in blocks
                           if b.get("type") == "heading" and not b.get("heading_role")]
        seq = [int(x["style"][-1]) for x in heading_paras
               if x.get("style") and re.match(r"^Heading[1-4]$", x["style"])]
        # drop the unnumbered reference heading from the sequence check
        numbered_heading_paras = [x for x in heading_paras
                                  if x.get("numId") or not (num_spec.get("enabled"))]
        seq_numbered = [int(x["style"][-1]) for x in numbered_heading_paras
                        if x.get("style") and re.match(r"^Heading[1-4]$", x["style"])]
        sequence_problems = []
        prev = 0
        for idx, lvl in enumerate(seq_numbered):
            if idx == 0 and lvl != 1:
                sequence_problems.append("首个小节级别为 %d" % lvl)
            if prev and lvl > prev + 1:
                sequence_problems.append("层级跳跃 %d -> %d" % (prev, lvl))
            prev = lvl
        rep.add("heading.sequence", "标题层级顺序（不跳级）",
                "从 1 级开始，每次最多下降一级",
                " -> ".join(str(x) for x in seq_numbered) or "无标题",
                "applied" if not sequence_problems else "failed",
                "word/document.xml#p/w:pPr/w:pStyle",
                "; ".join(sequence_problems))

        if num_spec.get("enabled"):
            levels = num_spec.get("levels") or []
            num_problems = []
            obs_levels = []
            for num_id, info in numbering.items():
                abstract = abstracts.get(info.get("abstract"), {})
                if abstract:
                    obs_levels.append((num_id, abstract.get(0, {})))
            heading_num_ids = {x.get("numId") for x in heading_paras if x.get("numId")}
            pattern_ok = False
            for num_id in heading_num_ids:
                abstract = abstracts.get((numbering.get(num_id) or {})
                                         .get("abstract"), {})
                if not abstract:
                    continue
                ok_patterns = True
                for idx, exp in enumerate(levels):
                    obs = abstract.get(idx) or {}
                    if (obs.get("lvlText") != exp.get("lvlText") or
                            obs.get("numFmt") != exp.get("numFmt")):
                        ok_patterns = False
                        num_problems.append(
                            "level %d: %s/%s != %s/%s" % (
                                idx, obs.get("lvlText"), obs.get("numFmt"),
                                exp.get("lvlText"), exp.get("numFmt")))
                pattern_ok = pattern_ok or ok_patterns
            unnumbered = [x for x in heading_paras if not x.get("numId")]
            exp_heading_count = len([b for b in blocks if b.get("type") == "heading"
                                     and not b.get("heading_role")])
            numbered_count = len([x for x in heading_paras if x.get("numId")])
            if not heading_num_ids:
                num_problems.append("标题段落没有 numPr")
            if unnumbered and len(unnumbered) > 1:
                num_problems.append("%d 个标题段落未编号" % len(unnumbered))
            status = "applied" if pattern_ok and not num_problems else "partial"
            note = "; ".join(num_problems) or (
                "参考章节标题按惯例不编号" if unnumbered else None)
            rep.add("heading.numbering", "标题自动编号（多级列表）",
                    "；".join("%d级=%s(%s)" % (i + 1, x.get("lvlText"),
                                              x.get("numFmt"))
                             for i, x in enumerate(levels)),
                    "numbered=%d/%d; 编号定义=%s" % (
                        numbered_count, exp_heading_count,
                        "已写入 numbering.xml" if heading_num_ids else "缺失"),
                    status, "word/numbering.xml#abstractNum/num[%s]"
                    % ",".join(sorted(heading_num_ids)) if heading_num_ids
                    else "word/numbering.xml", note)
        else:
            numbered = [x for x in heading_paras if x.get("numId")]
            rep.add("heading.numbering", "标题不自动编号",
                    "无 numPr", "%d 个标题带 numPr" % len(numbered),
                    "applied" if not numbered else "failed",
                    "word/document.xml#p/w:pPr/w:numPr")

        # ---------------------------------------------------- captions
        def cap_label_for(kind):
            if not is_default("captions.%s.label" % kind):
                return (captions.get(kind) or {}).get("label")
            return first_caption_label(blocks, kind) or (
                "Figure" if kind == "figure" else "Table")

        def cap_sep_for(kind):
            if not is_default("captions.%s.separator" % kind):
                return (captions.get(kind) or {}).get("separator") or ". "
            sep = (first_caption_sep(blocks, kind) or "").strip()
            return sep + " " if sep else ". "

        caption_paras = [x for x in paragraph_items if x.get("style") == "Caption"]
        figure_caps = [x for x in caption_paras
                       if re.match(r"^\s*(Figure|Fig\.?|图)\s*\d", x["text"])]
        table_caps = [x for x in caption_paras
                      if re.match(r"^\s*(Table|Tab\.?|表)\s*\d", x["text"])]
        exp_caps = {"figure": [b for b in blocks if b.get("type") == "caption"
                               and b.get("kind") == "figure"],
                    "table": [b for b in blocks if b.get("type") == "caption"
                              and b.get("kind") == "table"]}
        obs_caps = {"figure": figure_caps, "table": table_caps}
        for kind, cn in (("figure", "图"), ("table", "表")):
            expected = exp_caps[kind]
            observed = obs_caps[kind]
            if not expected and not observed:
                rep.add("caption.%s" % kind, "%s题注" % cn, "无题注", "无题注",
                        "not_applicable", "word/document.xml#p[w:pStyle=Caption]",
                        "稿件中未发现%s" % cn)
                continue
            label = cap_label_for(kind) or ""
            sep = cap_sep_for(kind) or ""
            numbers = []
            format_problems = []
            for x in observed:
                m = re.match(r"^\s*(?P<label>Figure|Fig\.?|图|Table|Tab\.?|表)\s*"
                             r"(?P<num>\d+)\s*(?P<rest>.*)$", x["text"])
                if not m:
                    format_problems.append("无法解析: %s" % x["text"][:40])
                    continue
                numbers.append(int(m.group("num")))
                if label and m.group("label").lower() != label.lower():
                    format_problems.append("标签 %s != %s" % (m.group("label"), label))
            sequential = numbers == list(range(1, len(numbers) + 1))
            if not sequential:
                format_problems.append("编号序列不是 1..N: %s" % numbers[:12])
            if len(observed) < len(expected):
                format_problems.append("稿件有 %d 条题注，输出 %d 条"
                                       % (len(expected), len(observed)))
            position = (captions.get(kind) or {}).get("position") or (
                "below" if kind == "figure" else "above")
            pos_problems = []
            for idx, item in enumerate(items):
                if item["kind"] == "tbl" and kind == "table":
                    prev = items[idx - 1] if idx > 0 else None
                    nxt = items[idx + 1] if idx + 1 < len(items) else None
                    cap_above = prev is not None and prev.get("style") == "Caption"
                    cap_below = nxt is not None and nxt.get("style") == "Caption"
                    if not (cap_above or cap_below):
                        pos_problems.append("表格 #%d 无相邻题注" % (idx + 1))
                    elif position == "above" and not cap_above:
                        pos_problems.append("表格 #%d 题注应在表格上方" % (idx + 1))
                    elif position == "below" and not cap_below:
                        pos_problems.append("表格 #%d 题注应在表格下方" % (idx + 1))
                if item["kind"] == "p" and item.get("drawing") and kind == "figure":
                    prev = items[idx - 1] if idx > 0 else None
                    nxt = items[idx + 1] if idx + 1 < len(items) else None
                    cap_above = prev is not None and prev.get("style") == "Caption"
                    cap_below = nxt is not None and nxt.get("style") == "Caption"
                    if not (cap_above or cap_below):
                        pos_problems.append("图 #%d 无相邻题注" % (idx + 1))
                    elif position == "below" and not cap_below:
                        pos_problems.append("图 #%d 题注应在图下方" % (idx + 1))
                    elif position == "above" and not cap_above:
                        pos_problems.append("图 #%d 题注应在图上方" % (idx + 1))
            status = "applied" if not format_problems and not pos_problems else "partial"
            rep.add("caption.%s.format" % kind, "%s题注标签/编号/位置" % cn,
                    "%s 1%s…（%s）" % (label, sep, "图下" if position == "below"
                                      else "图上"),
                    "%d 条，编号 %s" % (len(observed), numbers[:10]),
                    status, "word/document.xml#p[w:pStyle=Caption]",
                    "; ".join((format_problems + pos_problems)[:6]))
            cap_info = smap.get("Caption") or {}
            exp_cap_size = (captions.get(kind) or {}).get("size_pt")
            if exp_cap_size:
                rep.add("caption.%s.size" % kind, "%s题注字号" % cn,
                        "%spt" % fmt_num(exp_cap_size),
                        "%spt" % fmt_num(cap_info.get("size_pt") or 0),
                        "applied" if cap_info.get("size_pt") and
                        abs(cap_info["size_pt"] - float(exp_cap_size)) <= 0.1
                        else "failed",
                        "word/styles.xml#style[Caption]/w:sz")

        # ---------------------------------------------------- references
        exp_refs = [b for b in blocks if b.get("type") == "reference"]
        obs_refs = [x for x in paragraph_items if x.get("style") == "Bibliography"]
        ref_heading = None
        for x in paragraph_items:
            if x.get("style", "").startswith("Heading") and x["text"].strip().lower() \
                    .rstrip(":：") in ("references", "reference", "bibliography",
                                      "works cited", "参考文献"):
                ref_heading = x
                break
        if not exp_refs and not obs_refs:
            rep.add("references.entries", "参考文献条目", "无参考文献", "无参考文献",
                    "partial" if refs.get("heading") else "not_applicable",
                    "word/document.xml#p[w:pStyle=Bibliography]",
                    "稿件中未发现参考文献条目；未虚构条目")
        else:
            style = refs.get("style") or "numeric_bracket"
            numbers = []
            format_problems = []
            ref_num_ids = {x.get("numId") for x in obs_refs if x.get("numId")}
            ref_lvl_text = None
            for num_id in ref_num_ids:
                abstract = abstracts.get((numbering.get(num_id) or {})
                                         .get("abstract"), {})
                lvl0 = abstract.get(0) or {}
                if lvl0.get("lvlText"):
                    ref_lvl_text = lvl0["lvlText"]
                    break
            if style in ("numeric_bracket", "numeric_period"):
                expected_pat = "[%1]" if style == "numeric_bracket" else "%1."
                if not ref_num_ids:
                    format_problems.append("条目未使用自动编号")
                elif ref_lvl_text != expected_pat:
                    format_problems.append("编号定义 %s != %s"
                                           % (ref_lvl_text, expected_pat))
            elif style == "author_year" and ref_num_ids:
                format_problems.append("作者-出版年样式不应带编号列表")
            for x in obs_refs:
                m = re.match(r"^\s*(?:\[(\d+)\]|(\d+)[\.\、])\s*", x["text"])
                if m:
                    numbers.append(int(m.group(1) or m.group(2)))
            if len(obs_refs) < len(exp_refs):
                format_problems.append("稿件 %d 条，输出 %d 条"
                                       % (len(exp_refs), len(obs_refs)))
            rep.add("references.entries", "参考文献条目与顺序编码",
                    "%d 条，样式 %s" % (len(exp_refs), style),
                    "%d 条，编号定义=%s" % (len(obs_refs), ref_lvl_text or "无"),
                    "applied" if not format_problems else "partial",
                    "word/document.xml#p[w:pStyle=Bibliography]",
                    "; ".join(format_problems))
            bib = smap.get("Bibliography") or {}
            exp_hang = float(refs.get("hanging_indent_cm") or 0.74)
            hang_cm = C.twips_to_cm(bib.get("hanging_twips") or 0) or 0
            rep.add("references.hanging_indent", "参考文献悬挂缩进",
                    "%scm" % fmt_num(exp_hang), "%scm" % fmt_num(hang_cm),
                    "applied" if abs(hang_cm - exp_hang) <= 0.06 else "failed",
                    "word/styles.xml#style[Bibliography]/w:ind@hanging")
            if refs.get("size_pt"):
                rep.add("references.size", "参考文献字号",
                        "%spt" % fmt_num(refs["size_pt"]),
                        "%spt" % fmt_num(bib.get("size_pt") or 0),
                        "applied" if bib.get("size_pt") and
                        abs(bib["size_pt"] - float(refs["size_pt"])) <= 0.1
                        else "failed",
                        "word/styles.xml#style[Bibliography]/w:sz")
            if ref_heading is not None:
                rep.add("references.heading", "参考文献标题",
                        refs.get("heading") or "References",
                        ref_heading["text"], "applied",
                        "word/document.xml#p[w:pStyle=Heading1]")
            # citation cross references
            citations = []
            for x in paragraph_items:
                if x.get("style") == "Bibliography":
                    continue
                citations.extend(int(n) for n in re.findall(r"\[(\d+)\]", x["text"]))
            if citations:
                bad = sorted({n for n in citations if n > len(obs_refs)})
                rep.add("references.citations", "正文引用与文献表交叉一致",
                        "所有 [n] 均存在对应条目",
                        "引用 %s；条目 %d" % (sorted(set(citations))[:12], len(obs_refs)),
                        "applied" if not bad and obs_refs else "partial",
                        "word/document.xml#p/w:t",
                        ("越界引用 %s" % bad) if bad else
                        ("没有参考文献条目" if not obs_refs else None))

        # ---------------------------------------------------- page numbers / header
        footers = footer_parts(docx, sect)
        page_fields = {}
        for name, xml in footers.items():
            instr = re.findall(r"<w:instrText[^>]*>([^<]*)</w:instrText>", xml or "")
            page_fields[name] = any("PAGE" in text for text in instr)
        has_page_field = any(page_fields.values())
        if pn.get("enabled"):
            ref_ok = bool(sect.get("footer_ref"))
            status = "applied" if has_page_field and ref_ok else "failed"
            rep.add("page_numbers", "页脚页码（PAGE 域）",
                    "页脚 %s，格式 %s" % (pn.get("position") or "footer_center",
                                          pn.get("fmt") or "decimal"),
                    "footerReference=%s, PAGE域=%s" % (ref_ok, has_page_field),
                    status, "word/footer1.xml#w:instrText=PAGE",
                    None if status == "applied" else
                    "页码域未写入；无法声称页码可用")
        else:
            rep.add("page_numbers", "不显示页码", "无页脚页码",
                    "footerReference=%s" % bool(sect.get("footer_ref")),
                    "applied" if not sect.get("footer_ref") else "failed",
                    "word/document.xml#sectPr/w:footerReference")

        headers = header_parts(docx, sect)
        header_text = " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>",
                                          "".join(headers.values())))
        if header.get("enabled") or header.get("text"):
            exp_text = (header.get("text") or "")
            status = "applied" if headers and exp_text.strip() in header_text else "partial"
            rep.add("header", "页眉文本", exp_text,
                    header_text.strip() or "无", status,
                    "word/header1.xml#w:t")
        else:
            rep.add("header", "不启用页眉", "无 headerReference",
                    "headerReference=%s" % bool(sect.get("header_ref")),
                    "applied" if not sect.get("header_ref") else "failed",
                    "word/document.xml#sectPr/w:headerReference")

        # ---------------------------------------------------- tables
        table_style = (tables_spec.get("style") or "grid").lower()
        if not tables:
            rep.add("tables.style", "表格边框", table_style, "无表格",
                    "not_applicable", "word/document.xml#w:tbl")
        else:
            problems = []
            for idx, tbl in enumerate(tables):
                borders = table_borders(tbl)
                if table_style in ("three_line", "three-line", "三线表"):
                    if not borders or borders.get("top", {}).get("val") != "single" or \
                            borders.get("bottom", {}).get("val") != "single" or \
                            borders.get("insideH", {}).get("val") not in ("none", None):
                        problems.append("表格 #%d 非三线表边框" % (idx + 1))
                else:
                    if not borders or borders.get("insideH", {}).get("val") != "single":
                        problems.append("表格 #%d 缺少完整网格边框" % (idx + 1))
            rep.add("tables.style", "表格边框样式", table_style,
                    "%d 个表格" % len(tables),
                    "applied" if not problems else "partial",
                    "word/document.xml#w:tbl/w:tblPr/w:tblBorders",
                    "; ".join(problems[:5]))

        # ---------------------------------------------------- styles / content
        used = sorted({x.get("style") for x in paragraph_items if x.get("style")})
        missing_styles = [s for s in used if s not in smap]
        rep.add("styles.defined", "被引用样式均已定义",
                "所有 pStyle 均在 styles.xml 中",
                "使用 %d 个样式，缺失 %d 个" % (len(used), len(missing_styles)),
                "applied" if not missing_styles else "failed",
                "word/styles.xml#w:style",
                ("缺失: %s" % ", ".join(missing_styles)) if missing_styles else None)

        content = build_meta.get("content_check") or {}
        missing_blocks = content.get("missing_blocks")
        if missing_blocks is None:
            missing_blocks = len((build_meta.get("reopen") or {})
                                 .get("missing_blocks") or [])
        rep.add("content.preserved", "正文内容单元不丢失",
                "稿件文本块全部出现在输出中",
                "缺失 %s 个文本块；输出段落 %s" % (
                    missing_blocks, content.get("output_paragraphs")),
                "applied" if missing_blocks == 0 else "failed",
                "word/document.xml#w:body",
                None if missing_blocks == 0 else
                "有文本块未在输出中找到，详见 build_meta.json/reopen.missing_blocks")

        hits = []
        for pattern in PLACEHOLDERS:
            for match in re.finditer(pattern, all_text, re.I):
                hits.append({"pattern": pattern, "context": all_text[
                    max(0, match.start() - 30):match.end() + 30]})
        rep.add("placeholders", "占位符扫描",
                "无未完成占位符", "%d 处" % len(hits),
                "applied" if not hits else "failed",
                "word/document.xml#w:t",
                None if not hits else
                "发现占位符：%s" % "; ".join(h["context"][:60] for h in hits[:3]))

        font_check = build_meta.get("font_check") or {}
        if font_check.get("requested"):
            matched = font_check.get("matched")
            # The requested family is written into styles.xml; fc-match merely
            # reports whether this machine can render it natively.
            rep.add("font.availability", "目标字体在 DOCX 中显式指定",
                    font_check.get("requested"),
                    "%s（fc-match=%s）" % (
                        "已指定" if matched else "未确认", matched),
                    "applied" if matched else "partial",
                    "environment#fc-match",
                    None if matched else "fc-match 未返回可用字体；渲染可能缺字")

        # ---------------------------------------------------- export / preview
        formats = [str(x).lower() for x in (spec.get("export") or {}).get("formats")
                   or ["docx"]]
        pdf_path = build_meta.get("pdf")
        rendering = build_meta.get("rendering") or {}
        if "pdf" in formats:
            if pdf_path and os.path.exists(pdf_path) and rendering.get("produced"):
                pages = rendering.get("page_count")
                rep.add("export.pdf", "PDF 导出与真实页数",
                        "PDF 可生成", "已生成，%s 页（%s）" % (
                            pages, rendering.get("page_count_method")),
                        "applied" if pages else "partial",
                        "manuscript_formatted.pdf")
            else:
                rep.add("export.pdf", "PDF 导出", "PDF 可生成",
                        "未生成：%s" % (rendering.get("reason") or "无渲染器"),
                        "partial", "build_meta.json#rendering")
        elif rendering.get("produced"):
            rep.add("export.preview", "可选 PDF 预览",
                    "预览（非必需）", "已生成，%s 页" % rendering.get("page_count"),
                    "applied", "manuscript_formatted.pdf")

        if (spec.get("toc") or {}).get("enabled"):
            toc_found = "TOC" in (docx.text_xml("word/document.xml") or "")
            rep.add("toc", "目录域", "插入 TOC 域", "域存在" if toc_found else "缺失",
                    "partial" if toc_found else "failed",
                    "word/document.xml#w:instrText=TOC",
                    "目录页码需要 Word/LibreOffice 更新域后才能定稿，本报告不宣称已更新")

        for idx, item in enumerate(
                (spec.get("meta") or {}).get("unmatched_requirements") or [], 1):
            rep.add("requirement.unsupported.%d" % idx,
                    "任务要求：%s" % (item.get("text") or "")[:90],
                    "已应用", "未实现或无法在 DOCX 中核验", "unsupported",
                    item.get("source") or "task.md",
                    "当前生成器没有对应实现；未声称该要求已满足，"
                    "请人工补齐或改用受支持的写法")
    finally:
        docx.close()

    report["summary"] = rep.summary()
    report["verification"] = {
        "docx_reopens": True,
        "parts": sorted(docx.names),
        "paragraphs": len(paragraph_items),
        "tables": len(tables),
        "drawings": sum(1 for x in paragraph_items if x.get("drawing")),
        "styles_used": used,
        "defined_styles": sorted(smap.keys()),
        "page_count": (build_meta.get("rendering") or {}).get("page_count"),
        "page_count_method": (build_meta.get("rendering") or {})
        .get("page_count_method"),
        "pdf_fonts": (build_meta.get("rendering") or {}).get("fonts_detected"),
        "placeholder_hits": hits,
        "spec_conflicts": len(spec.get("conflicts") or []),
        "template_missing": (spec.get("meta") or {}).get("template_missing"),
    }
    report["requirements"] = rep.requirements
    report["issues"] = [
        {"id": item["id"], "status": item["status"],
         "detail": item.get("note") or "%s: %s" % (item["expected"], item["actual"])}
        for item in rep.requirements
        if item["status"] in ("failed", "partial", "unsupported")]
    out_path = os.path.join(args.output, "format_report.json")
    C.write_json(out_path, report)
    summary = report["summary"]
    print(json.dumps({
        "format_report": os.path.abspath(out_path),
        "summary": summary,
        "issues": len(report["issues"]),
        "docx_reopens": True,
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
