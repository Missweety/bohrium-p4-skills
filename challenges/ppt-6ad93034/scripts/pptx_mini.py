#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pptx_mini.py - 纯标准库生成可编辑 .pptx（OOXML 直写）。

为什么需要它：
    题面要求交付「可编辑演示文件」，但评测镜像是否预装 python-pptx 不确定
    （平台只承诺 office-renderer / scientific-python 等工具）。
    若 pptx 缺失就降级为纯 Markdown，等于丢掉该赛道的核心交付物。
    所以这里用 zipfile + 手写 OOXML 直出 pptx：无第三方依赖，任何环境可用。

产出：
    一个最小但合法的 pptx：1 个空白母版 + 1 个空白版式 + N 张幻灯片，
    每张页含标题文本框、正文文本框、讲稿文本框，文字均可直接编辑。

降级：
    若标准库 zipfile 不可用，调用方应捕获异常并如实标注 degraded。
"""
from __future__ import annotations

import os
import zipfile
from xml.sax.saxutils import escape

EMU_PER_INCH = 914400
SLIDE_W = 12192000   # 13.333 in（16:9）
SLIDE_H = 6858000    # 7.5 in

CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
%s
</Types>"""

RELS_ROOT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""

THEME = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="SlideDefault">
<a:themeElements>
<a:clrScheme name="Office">
<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>
<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
<a:dk2><a:srgbClr val="44546A"/></a:dk2>
<a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>
<a:accent1><a:srgbClr val="4472C4"/></a:accent1>
<a:accent2><a:srgbClr val="ED7D31"/></a:accent2>
<a:accent3><a:srgbClr val="A5A5A5"/></a:accent3>
<a:accent4><a:srgbClr val="FFC000"/></a:accent4>
<a:accent5><a:srgbClr val="5B9BD5"/></a:accent5>
<a:accent6><a:srgbClr val="70AD47"/></a:accent6>
<a:hlink><a:srgbClr val="0563C1"/></a:hlink>
<a:folHlink><a:srgbClr val="954F72"/></a:folHlink>
</a:clrScheme>
<a:fontScheme name="Office">
<a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface="PingFang SC"/><a:cs typeface=""/></a:majorFont>
<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface="PingFang SC"/><a:cs typeface=""/></a:minorFont>
</a:fontScheme>
<a:fmtScheme name="Office">
<a:fillStyleLst>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
</a:fillStyleLst>
<a:lnStyleLst>
<a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
<a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
<a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
</a:lnStyleLst>
<a:effectStyleLst>
<a:effectStyle><a:effectLst/></a:effectStyle>
<a:effectStyle><a:effectLst/></a:effectStyle>
<a:effectStyle><a:effectLst/></a:effectStyle>
</a:effectStyleLst>
<a:bgFillStyleLst>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
</a:bgFillStyleLst>
</a:fmtScheme>
</a:themeElements>
</a:theme>"""

MASTER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:cSld>
<p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
</p:spTree>
</p:cSld>
<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
</p:sldMaster>"""

MASTER_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""

LAYOUT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">
<p:cSld name="Blank">
<p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
</p:spTree>
</p:cSld>
<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>"""

LAYOUT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""

SLIDE_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>"""

SLIDE_RELS_WITH_NOTES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide1.xml"/>
</Relationships>"""


def _slide_rels_with_notes(page_no):
    """第 page_no 页的 slide rels（挂上对应的 notesSlide）。"""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/notesSlide" Target="../notesSlides/notesSlide%d.xml"/>'
        '</Relationships>' % page_no)


def _notes_rels(page_no):
    """第 page_no 页备注页的 rels（指向 notesMaster 与所属 slide）。"""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/notesMaster" Target="../notesMasters/notesMaster1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/slide" Target="../slides/slide%d.xml"/>'
        '</Relationships>' % page_no)

NOTES_MASTER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:notesMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:cSld>
<p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
</p:spTree>
</p:cSld>
<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
</p:notesMaster>"""

NOTES_MASTER_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""


def _shape(shape_id, name, x, y, cx, cy, paragraphs):
    """一个矩形文本框。paragraphs 为 [(text, size_pt, bold, bullet)] 列表。"""
    body = []
    for text, size, bold, bullet in paragraphs:
        prefix = "• " if bullet else ""
        run = ""
        if text:
            run = ('<a:r><a:rPr lang="zh-CN" altLang="en-US" sz="%d" b="%d" dirty="0"/>'
                   '<a:t>%s</a:t></a:r>' % (int(size * 100), 1 if bold else 0,
                                           escape(prefix + text)))
        body.append(
            '<a:p><a:pPr marL="%d" indent="%d"><a:buNone/></a:pPr>%s</a:p>' % (
                285750 if bullet else 0, -285750 if bullet else 0, run))
    return (
        '<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/><p:cNvSpPr txBox="1"/>'
        '<p:nvPr/></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
        '<p:txBody><a:bodyPr wrap="square" lIns="91440" tIns="45720" rIns="91440" '
        'bIns="45720" anchor="t"><a:normAutofit/></a:bodyPr><a:lstStyle/>%s</p:txBody>'
        '</p:sp>' % (shape_id, escape(name), x, y, cx, cy, "".join(body)))


def _slide_xml(page):
    """按页内容生成 slide XML。

    page 字段（与 lane_slides 的 pages 结构对齐，缺字段按空处理）：
        title / claim / bullets / notes{transition,emphasis,backup}
    """
    shapes = []
    sid = 2
    title = (page.get("title") or "").strip()
    if title:
        shapes.append(_shape(sid, "Title", 685800, 457200, 10820400, 1143000,
                             [(title, 28, True, False)]))
        sid += 1

    lines = []
    claim = (page.get("claim") or "").strip()
    if claim:
        lines.append((claim, 18, True, False))
    for b in (page.get("bullets") or []):
        t = (b or "").strip()
        if t:
            lines.append((t, 16, False, True))

    if lines:
        shapes.append(_shape(sid, "Body", 685800, 1828800, 10820400, 3657600, lines))
        sid += 1

    notes = page.get("notes") or {}
    nlines = []
    for key, label in (("transition", "过渡"), ("emphasis", "强调"),
                       ("backup", "被问到时")):
        v = (notes.get(key) or "").strip()
        if v:
            nlines.append(("%s：%s" % (label, v), 12, False, False))

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        '%s</p:spTree></p:cSld>'
        '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
        % "".join(shapes)), nlines


def _notes_xml(nlines):
    """真正的 PowerPoint 备注页（notesSlide），而不是页内文本框。

    备注页含占位符：sldImg（幻灯片缩略图）、body（讲稿正文）。
    """
    paras = []
    for text, size, bold, _bullet in nlines:
        paras.append(
            '<a:p><a:r><a:rPr lang="zh-CN" altLang="en-US" sz="%d" b="%d" dirty="0"/>'
            '<a:t>%s</a:t></a:r></a:p>' % (int(size * 100), 1 if bold else 0,
                                           escape(text)))
    body = "".join(paras) or '<a:p><a:endParaRPr/></a:p>'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<p:notes xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/>'
        '<p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
        '<p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="685800" y="457200"/>'
        '<a:ext cx="5486400" cy="4114800"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
        '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr/></a:p></p:txBody></p:sp>'
        '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/>'
        '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
        '<p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="685800" y="5029200"/>'
        '<a:ext cx="5486400" cy="4114800"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
        '<p:txBody><a:bodyPr/><a:lstStyle/>%s</p:txBody></p:sp>'
        '</p:spTree></p:cSld>'
        '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>' % body)



def write_pptx(pages, out_path, title="Deck"):
    """写出可编辑 pptx，返回 {"ok": bool, "slides": n, "bytes": n}。"""
    pages = list(pages or [])
    slides_xml = []
    notes_xml = []
    for page in pages:
        s_xml, n_lines = _slide_xml(page)
        slides_xml.append(s_xml)
        notes_xml.append(n_lines)

    has_notes = [bool(n) for n in notes_xml]
    overrides = "\n".join(
        '<Override PartName="/ppt/slides/slide%d.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.presentationml.slide+xml"/>' % (i + 1)
        for i in range(len(pages)))
    if any(has_notes):
        overrides += "\n" + "\n".join(
            '<Override PartName="/ppt/notesSlides/notesSlide%d.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.presentationml.notesSlide+xml"/>' % (i + 1)
            for i in range(len(pages)) if has_notes[i])
        overrides += ('\n<Override PartName="/ppt/notesMasters/notesMaster1.xml" '
                      'ContentType="application/vnd.openxmlformats-officedocument.'
                      'presentationml.notesMaster+xml"/>')

    sld_ids = "".join(
        '<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, i + 2)
        for i in range(len(pages)))
    pres_rels = [
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>']
    for i in range(len(pages)):
        pres_rels.append(
            '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/slide" Target="slides/slide%d.xml"/>'
            % (i + 2, i + 1))
    notes_master_id = ""
    if any(has_notes):
        notes_master_id = ('<p:notesMasterIdLst><p:notesMasterId r:id="rIdNM1"/>'
                           '</p:notesMasterIdLst>')
        pres_rels.append(
            '<Relationship Id="rIdNM1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/notesMaster" '
            'Target="notesMasters/notesMaster1.xml"/>')
    presentation = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'saveSubsetFonts="1">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        '%s<p:sldIdLst>%s</p:sldIdLst>'
        '<p:sldSz cx="%d" cy="%d"/><p:notesSz cx="6858000" cy="9144000"/>'
        '</p:presentation>' % (notes_master_id, sld_ids, SLIDE_W, SLIDE_H))

    tmp = out_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CT % overrides)
        zf.writestr("_rels/.rels", RELS_ROOT)
        zf.writestr("ppt/presentation.xml", presentation)
        zf.writestr("ppt/_rels/presentation.xml.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                    '2006/relationships">%s</Relationships>' % "".join(pres_rels))
        zf.writestr("ppt/slideMasters/slideMaster1.xml", MASTER)
        zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", MASTER_RELS)
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", LAYOUT)
        zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", LAYOUT_RELS)
        zf.writestr("ppt/theme/theme1.xml", THEME)
        if any(has_notes):
            zf.writestr("ppt/notesMasters/notesMaster1.xml", NOTES_MASTER)
            zf.writestr("ppt/notesMasters/_rels/notesMaster1.xml.rels", NOTES_MASTER_RELS)
        for i, page in enumerate(pages):
            zf.writestr("ppt/slides/slide%d.xml" % (i + 1), slides_xml[i])
            if has_notes[i]:
                zf.writestr("ppt/notesSlides/notesSlide%d.xml" % (i + 1),
                            _notes_xml(notes_xml[i]))
                zf.writestr("ppt/notesSlides/_rels/notesSlide%d.xml.rels" % (i + 1),
                            _notes_rels(i + 1))
                zf.writestr("ppt/slides/_rels/slide%d.xml.rels" % (i + 1),
                            _slide_rels_with_notes(i + 1))
            else:
                zf.writestr("ppt/slides/_rels/slide%d.xml.rels" % (i + 1), SLIDE_RELS)
    if os.path.exists(out_path):
        os.remove(out_path)
    os.rename(tmp, out_path)
    return {"ok": True, "slides": len(pages),
            "notes": sum(1 for h in has_notes if h),
            "bytes": os.path.getsize(out_path)}


if __name__ == "__main__":  # pragma: no cover - 自检入口
    demo = [{"title": "标题页", "claim": "核心主张",
             "bullets": ["要点一", "要点二"],
             "notes": {"transition": "开场", "emphasis": "重点", "backup": "备用"}}]
    print(write_pptx(demo, "/tmp/pptx_mini_selftest.pptx"))
