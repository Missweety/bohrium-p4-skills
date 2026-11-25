#!/usr/bin/env python3
"""pptx_min.py - dependency-free .pptx writer used only when python-pptx is missing.

It emits a real, editable Office Open XML presentation (16:9) with one slide master,
one "Title and Content" layout and text shapes for title / takeaway+bullets / caption /
footer / page number. It does not embed images or speaker notes; template inheritance is
not possible without python-pptx, so callers must report that limit honestly.

Public: build(spec, out_path) -> {"built": bool, "path": str|None, "tool": str,
                                 "pages": [...], "reason": str}
"""
import os
import re
import zipfile

EMU = 914400
SLIDE_W, SLIDE_H = 12192000, 6858000  # 13.333 x 7.5 in
NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
%s</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""

THEME = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office">
<a:themeElements>
<a:clrScheme name="Office">
<a:dk1><a:srgbClr val="1A1A1A"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
<a:dk2><a:srgbClr val="44546A"/></a:dk2><a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>
<a:accent1><a:srgbClr val="0B5FFF"/></a:accent1><a:accent2><a:srgbClr val="ED7D31"/></a:accent2>
<a:accent3><a:srgbClr val="A5A5A5"/></a:accent3><a:accent4><a:srgbClr val="FFC000"/></a:accent4>
<a:accent5><a:srgbClr val="5B9BD5"/></a:accent5><a:accent6><a:srgbClr val="70AD47"/></a:accent6>
<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink>
</a:clrScheme>
<a:fontScheme name="Office">
<a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>
<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>
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

EMPTY_TREE = """<p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
</p:spTree>"""

MASTER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster %s>
<p:cSld>%s</p:cSld>
<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
</p:sldMaster>""" % (NS, EMPTY_TREE)

LAYOUT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout %s type="obj" preserve="1">
<p:cSld name="Title and Content">%s</p:cSld>
<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>""" % (NS, EMPTY_TREE)


def _esc(value):
    return (str(value or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _run(value, size, bold=False, italic=False):
    return ('<a:r><a:rPr lang="zh-CN" sz="%d"%s%s dirty="0"><a:solidFill>'
            '<a:schemeClr val="tx1"/></a:solidFill></a:rPr><a:t>%s</a:t></a:r>'
            % (int(size), ' b="1"' if bold else "", ' i="1"' if italic else "", _esc(value)))


def _para(value, size, bold=False, bullet=False, italic=False):
    props = ('<a:pPr marL="285750" indent="-285750"><a:buFont typeface="Arial"/>'
             '<a:buChar char="\u2022"/></a:pPr>' if bullet else "<a:pPr/>")
    return "<a:p>%s%s<a:endParaRPr lang=\"zh-CN\" sz=\"%d\"/></a:p>" % (
        props, _run(value, size, bold, italic), int(size))


def _shape(shape_id, name, left, top, width, height, paragraphs):
    return ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/><p:cNvSpPr txBox="1"/>'
            '<p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/>'
            '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            '<p:txBody><a:bodyPr wrap="square" lIns="91440" tIns="45720" rIns="91440" bIns="45720">'
            '</a:bodyPr><a:lstStyle/>%s</p:txBody></p:sp>'
            % (shape_id, _esc(name), int(left), int(top), int(width), int(height),
               "".join(paragraphs)))


def _slide_xml(item, index):
    shapes, shape_id = [], 2
    visual = item.get("visual") or {}
    has_visual = visual.get("type") in ("figure", "table", "schematic", "photo")
    body_width = int(SLIDE_W * 0.86) if not has_visual else int(SLIDE_W * 0.5)
    shapes.append(_shape(shape_id, "Title %d" % index, int(SLIDE_W * 0.06), int(SLIDE_H * 0.06),
                         int(SLIDE_W * 0.88), int(SLIDE_H * 0.15),
                         [_para(item.get("title") or "（待定标题）", 3200, bold=True)]))
    shape_id += 1
    body_paras = []
    if item.get("takeaway"):
        body_paras.append(_para(item["takeaway"], 2200, bold=True))
    for bullet in item.get("bullets") or []:
        body_paras.append(_para(bullet, 2000, bullet=True))
    if not body_paras:
        body_paras.append(_para("（本页要点待补）", 1800, italic=True))
    if has_visual:
        label = "%s %s" % ("表" if visual.get("type") == "table" else "图",
                           visual.get("ref") or "")
        body_paras.append(_para("%s：%s" % (label.strip(), visual.get("caption") or "见原图"),
                                1400, italic=True))
    shapes.append(_shape(shape_id, "Body %d" % index, int(SLIDE_W * 0.06), int(SLIDE_H * 0.26),
                         body_width, int(SLIDE_H * 0.56), body_paras))
    shape_id += 1
    caption = visual.get("caption") or ""
    if caption:
        shapes.append(_shape(shape_id, "Caption %d" % index, int(SLIDE_W * 0.06),
                             int(SLIDE_H * 0.845), int(SLIDE_W * 0.74), int(SLIDE_H * 0.06),
                             [_para(caption, 1200, italic=True)]))
        shape_id += 1
    footer_text = item.get("footer") or ""
    if footer_text:
        shapes.append(_shape(shape_id, "Footer %d" % index, int(SLIDE_W * 0.06),
                             int(SLIDE_H * 0.93), int(SLIDE_W * 0.6), int(SLIDE_H * 0.045),
                             [_para(footer_text, 900)]))
        shape_id += 1
    shapes.append(_shape(shape_id, "Slide Number %d" % index, int(SLIDE_W * 0.88),
                         int(SLIDE_H * 0.93), int(SLIDE_W * 0.06), int(SLIDE_H * 0.045),
                         [_para(str(index), 900)]))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<p:sld %s><p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            '%s</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
            % (NS, "".join(shapes)))


def build(spec, out_path):
    slides = spec.get("slides") or []
    if not slides:
        return {"built": False, "reason": "spec has no slides", "path": None,
                "tool": "stdlib-pptx", "pages": []}
    overrides = "\n".join(
        '<Override PartName="/ppt/slides/slide%d.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        % (i + 1) for i in range(len(slides)))
    pres_rels = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>']
    sld_ids = []
    for i in range(len(slides)):
        pres_rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/'
                         'officeDocument/2006/relationships/slide" Target="slides/slide%d.xml"/>'
                         % (i + 2, i + 1))
        sld_ids.append('<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, i + 2))
    presentation = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                    '<p:presentation %s saveSubsetFonts="1">'
                    '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                    '<p:sldIdLst>%s</p:sldIdLst>'
                    '<p:sldSz cx="%d" cy="%d"/><p:notesSz cx="6858000" cy="9144000"/>'
                    '</p:presentation>' % (NS, "".join(sld_ids), SLIDE_W, SLIDE_H))
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '%s</Relationships>' % "".join(pres_rels))
    master_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
                   '</Relationships>')
    layout_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
                   '</Relationships>')
    slide_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                  '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                  '</Relationships>')
    try:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", CONTENT_TYPES % overrides)
            zf.writestr("_rels/.rels", ROOT_RELS)
            zf.writestr("ppt/presentation.xml", presentation)
            zf.writestr("ppt/_rels/presentation.xml.rels", rels)
            zf.writestr("ppt/slideMasters/slideMaster1.xml", MASTER)
            zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", master_rels)
            zf.writestr("ppt/slideLayouts/slideLayout1.xml", LAYOUT)
            zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", layout_rels)
            zf.writestr("ppt/theme/theme1.xml", THEME)
            pages = []
            for i, item in enumerate(slides, start=1):
                zf.writestr("ppt/slides/slide%d.xml" % i, _slide_xml(item, i))
                zf.writestr("ppt/slides/_rels/slide%d.xml.rels" % i, slide_rels)
                pages.append({"slide": i, "layout": "Title and Content",
                              "visual": (item.get("visual") or {}).get("type") or "none",
                              "caption": bool((item.get("visual") or {}).get("caption")),
                              "evidence": len(item.get("evidence") or []),
                              "title": bool(item.get("title")),
                              "body": bool(item.get("bullets"))})
        return {"built": True, "reason": "", "path": out_path, "tool": "stdlib-pptx",
                "pages": pages}
    except Exception as exc:  # noqa: BLE001
        return {"built": False, "reason": "stdlib pptx failed: %s" % exc, "path": None,
                "tool": "stdlib-pptx", "pages": []}
