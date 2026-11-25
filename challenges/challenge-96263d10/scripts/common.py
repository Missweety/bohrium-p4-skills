#!/usr/bin/env python3
"""Shared stdlib helpers for the academic format/template adaptation skill.

No third-party imports, no network access. Works with DOCX as a zip of XML
parts, and with plain UTF-8 Markdown/TXT manuscripts and JSON/YAML/MD specs.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "v": "urn:schemas-microsoft-com:vml",
    "o": "urn:schemas-microsoft-com:office:office",
    "w10": "urn:schemas-microsoft-com:office:word",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "wp14": "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "w15": "http://schemas.microsoft.com/office/word/2012/wordml",
    "w16": "http://schemas.microsoft.com/office/word/2018/wordml",
}
for _p, _u in NS.items():
    try:
        ET.register_namespace(_p, _u)
    except Exception:
        pass

W_NS = NS["w"]
R_NS = NS["r"]
M_NS = NS["m"]


def qn(prefix, tag):
    return "{%s}%s" % (NS[prefix], tag)


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def locate(base, *parts):
    return os.path.join(base, *parts)


def ensure_dir(path):
    if path:
        os.makedirs(path, exist_ok=True)
    return path


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    ensure_dir(os.path.dirname(os.path.abspath(path)))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return path


def read_text(path, errors="replace"):
    try:
        with open(path, "r", encoding="utf-8", errors=errors) as fh:
            return fh.read()
    except OSError:
        return ""


def sha256_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- units
def cm_to_twips(cm):
    return int(round(float(cm) * 1440.0 / 2.54))


def twips_to_cm(twips):
    try:
        return round(float(twips) * 2.54 / 1440.0, 3)
    except (TypeError, ValueError):
        return None


def pt_to_half(pt):
    return int(round(float(pt) * 2))


def half_to_pt(half):
    try:
        return round(float(half) / 2.0, 2)
    except (TypeError, ValueError):
        return None


def sanitize_text(text):
    """Drop control characters that are illegal in XML 1.0 text nodes."""
    if text is None:
        return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(text))


HEADING_NUMBER_PATTERNS = (
    r"^\s*\d+(?:\.\d+)*[\.、]?\s+",
    r"^\s*第[一二三四五六七八九十百零〇]+[章节篇]\s*",
    r"^\s*[一二三四五六七八九十百零〇]+[、.．]\s*",
    r"^\s*[（(][一二三四五六七八九十百零〇]+[）)]\s*",
)


def strip_heading_number(text):
    """Remove a literal section number that would duplicate numbering.xml."""
    if not text:
        return text
    if re.match(r"^\s*(?:19|20)\d{2}\s", text):
        return text
    out = text
    for pattern in HEADING_NUMBER_PATTERNS:
        out = re.sub(pattern, "", out, count=1)
    return out


def xml_escape(text, attr=False):
    if text is None:
        return ""
    text = sanitize_text(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if attr:
        text = text.replace('"', "&quot;")
    return text


# ---------------------------------------------------------------- docx io
class Docx(object):
    """Read-only view over a .docx package."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.zip = zipfile.ZipFile(self.path)
        self.names = set(self.zip.namelist())

    def has(self, name):
        return name in self.names

    def read(self, name):
        if name not in self.names:
            return None
        return self.zip.read(name)

    def xml(self, name):
        data = self.read(name)
        if not data:
            return None
        return ET.fromstring(data)

    def text_xml(self, name):
        data = self.read(name)
        return data.decode("utf-8", "replace") if data else ""

    def media(self, name):
        return self.read(name)

    def close(self):
        try:
            self.zip.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def docx_valid(path):
    """Return (ok, reason). Verifies zip integrity plus the core XML parts."""
    if not path or not os.path.exists(path):
        return False, "file missing"
    if os.path.getsize(path) < 512:
        return False, "file too small to be a docx"
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                return False, "zip member damaged: %s" % bad
            names = set(zf.namelist())
            for req in ("[Content_Types].xml", "word/document.xml"):
                if req not in names:
                    return False, "missing part %s" % req
            ET.fromstring(zf.read("word/document.xml"))
    except Exception as exc:  # noqa: BLE001 - report, never traceback
        return False, "%s: %s" % (type(exc).__name__, exc)
    return True, "valid OOXML package"


def style_map(styles_root):
    """styleId -> parsed style dict; also name -> styleId for convenience."""
    out = {}
    by_name = {}
    if styles_root is None:
        return out, by_name
    for st in styles_root.findall(qn("w", "style")):
        sid = st.get(qn("w", "styleId")) or ""
        name_el = st.find(qn("w", "name"))
        name = (name_el.get(qn("w", "val")) if name_el is not None else sid) or sid
        info = parse_style(st)
        info["styleId"] = sid
        info["name"] = name
        out[sid] = info
        by_name[name.strip().lower()] = sid
    return out, by_name


def _rpr_info(rpr):
    info = {"font_latin": None, "font_east_asia": None, "size_pt": None,
            "bold": None, "italic": None}
    if rpr is None:
        return info
    fonts = rpr.find(qn("w", "rFonts"))
    if fonts is not None:
        info["font_latin"] = fonts.get(qn("w", "ascii")) or fonts.get(qn("w", "hAnsi"))
        info["font_east_asia"] = fonts.get(qn("w", "eastAsia"))
    sz = rpr.find(qn("w", "sz"))
    if sz is not None:
        info["size_pt"] = half_to_pt(sz.get(qn("w", "val")))
    b = rpr.find(qn("w", "b"))
    if b is not None:
        info["bold"] = b.get(qn("w", "val")) not in ("0", "false", "off")
    i = rpr.find(qn("w", "i"))
    if i is not None:
        info["italic"] = i.get(qn("w", "val")) not in ("0", "false", "off")
    return info


def _ppr_info(ppr):
    info = {"spacing_line": None, "line_rule": None, "before_pt": None,
            "after_pt": None, "first_line_twips": None, "hanging_twips": None,
            "align": None, "outline_level": None, "num_id": None, "num_ilvl": None,
            "page_break_before": None}
    if ppr is None:
        return info
    sp = ppr.find(qn("w", "spacing"))
    if sp is not None:
        line = sp.get(qn("w", "line"))
        if line is not None:
            try:
                info["spacing_line"] = int(line)
            except ValueError:
                pass
        info["line_rule"] = sp.get(qn("w", "lineRule"))
        for key, tag in (("before_pt", "before"), ("after_pt", "after")):
            val = sp.get(qn("w", tag))
            if val is not None:
                try:
                    info[key] = round(int(val) / 20.0, 2)
                except ValueError:
                    pass
    ind = ppr.find(qn("w", "ind"))
    if ind is not None:
        for attr, key in (("firstLine", "first_line_twips"),
                          ("hanging", "hanging_twips")):
            val = ind.get(qn("w", attr))
            if val is not None:
                try:
                    info[key] = int(val)
                except ValueError:
                    pass
    jc = ppr.find(qn("w", "jc"))
    if jc is not None:
        info["align"] = jc.get(qn("w", "val"))
    outline = ppr.find(qn("w", "outlineLvl"))
    if outline is not None:
        val = outline.get(qn("w", "val"))
        if val is not None:
            try:
                info["outline_level"] = int(val)
            except ValueError:
                pass
    num = ppr.find(qn("w", "numPr"))
    if num is not None:
        nid = num.find(qn("w", "numId"))
        ilvl = num.find(qn("w", "ilvl"))
        if nid is not None:
            info["num_id"] = nid.get(qn("w", "val"))
        if ilvl is not None:
            info["num_ilvl"] = ilvl.get(qn("w", "val"))
    pbb = ppr.find(qn("w", "pageBreakBefore"))
    if pbb is not None:
        info["page_break_before"] = pbb.get(qn("w", "val")) not in ("0", "false", "off")
    return info


def parse_style(style_el):
    based = style_el.find(qn("w", "basedOn"))
    ppr = style_el.find(qn("w", "pPr"))
    rpr = style_el.find(qn("w", "rPr"))
    info = {
        "based_on": based.get(qn("w", "val")) if based is not None else None,
        "type": style_el.get(qn("w", "type")),
        "default": style_el.get(qn("w", "default")) in ("1", "true", "on"),
    }
    info.update(_rpr_info(rpr))
    info.update(_ppr_info(ppr))
    return info


def doc_defaults(styles_root):
    info = {"font_latin": None, "font_east_asia": None, "size_pt": None,
            "spacing_line": None, "line_rule": None, "first_line_twips": None,
            "align": None, "before_pt": None, "after_pt": None}
    if styles_root is None:
        return info
    dd = styles_root.find(qn("w", "docDefaults"))
    if dd is None:
        return info
    info.update(_rpr_info(dd.find(qn("w", "rPrDefault") + "/" + qn("w", "rPr"))))
    info.update(_ppr_info(dd.find(qn("w", "pPrDefault") + "/" + qn("w", "pPr"))))
    return info


def sect_properties(root):
    """Return section properties of the last w:sectPr in document.xml."""
    if root is None:
        return {}
    sect = None
    for el in root.iter(qn("w", "sectPr")):
        sect = el
    if sect is None:
        return {}
    out = {"page_width_twips": None, "page_height_twips": None,
           "orientation": None, "margins_twips": {}, "columns": None,
           "page_number_fmt": None, "page_number_start": None,
           "footer_ref": None, "header_ref": None}
    pg = sect.find(qn("w", "pgSz"))
    if pg is not None:
        for attr, key in (("w", "page_width_twips"), ("h", "page_height_twips")):
            val = pg.get(qn("w", attr))
            if val is not None:
                try:
                    out[key] = int(val)
                except ValueError:
                    pass
        out["orientation"] = pg.get(qn("w", "orient"))
    mar = sect.find(qn("w", "pgMar"))
    if mar is not None:
        for side in ("top", "bottom", "left", "right", "header", "footer", "gutter"):
            val = mar.get(qn("w", side))
            if val is not None:
                try:
                    out["margins_twips"][side] = int(val)
                except ValueError:
                    pass
    cols = sect.find(qn("w", "cols"))
    out["columns"] = int(cols.get(qn("w", "num")) or 1) if cols is not None else 1
    num = sect.find(qn("w", "pgNumType"))
    if num is not None:
        out["page_number_fmt"] = num.get(qn("w", "fmt"))
        start = num.get(qn("w", "start"))
        if start is not None:
            try:
                out["page_number_start"] = int(start)
            except ValueError:
                pass
    for kind, key in (("footer", "footer_ref"), ("header", "header_ref")):
        ref = None
        for el in sect.findall(qn("w", kind + "Reference")):
            ref = el.get(qn("r", "id"))
        out[key] = ref
    return out


def numbering_map(root):
    """numId -> {'abstract': id}; abstract -> {ilvl: level dict}."""
    nums, abstracts = {}, {}
    if root is None:
        return nums, abstracts
    for ab in root.findall(qn("w", "abstractNum")):
        aid = ab.get(qn("w", "abstractNumId"))
        levels = {}
        for lvl in ab.findall(qn("w", "lvl")):
            ilvl = lvl.get(qn("w", "ilvl"))
            fmt = lvl.find(qn("w", "numFmt"))
            txt = lvl.find(qn("w", "lvlText"))
            start = lvl.find(qn("w", "start"))
            levels[int(ilvl or 0)] = {
                "ilvl": int(ilvl or 0),
                "numFmt": fmt.get(qn("w", "val")) if fmt is not None else None,
                "lvlText": (txt.get(qn("w", "val")) if txt is not None else None) or "",
                "start": int(start.get(qn("w", "val")) or 1) if start is not None else 1,
            }
        abstracts[aid] = levels
    for num in root.findall(qn("w", "num")):
        nid = num.get(qn("w", "numId"))
        ab = num.find(qn("w", "abstractNumId"))
        if ab is not None:
            nums[nid] = {"abstract": ab.get(qn("w", "val"))}
    return nums, abstracts


def paragraph_text(p):
    """Concatenate w:t text inside a paragraph, honouring tabs/breaks."""
    parts = []
    for el in p.iter():
        name = local(el.tag)
        if name == "t":
            parts.append(el.text or "")
        elif name == "tab":
            parts.append("\t")
        elif name in ("br", "cr"):
            parts.append("\n")
        elif name == "noBreakHyphen":
            parts.append("-")
    return "".join(parts)


def body_children(root):
    if root is None:
        return []
    body = root.find(qn("w", "body"))
    if body is None:
        return []
    return list(body)


def heading_level_from_style(style_id, style_name):
    """Map English/Chinese Word heading style names to a 1-based level."""
    for raw in (style_id or "", style_name or ""):
        text = raw.strip().lower().replace("_", " ")
        m = re.match(r"^heading\s*([1-9])$", text)
        if m:
            return int(m.group(1))
        m = re.match(r"^标题\s*([1-9])$", text)
        if m:
            return int(m.group(1))
        m = re.match(r"^title\s*([1-9])$", text)
        if m:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------- case/contract
CONTRACT_KEYS = [
    "output_contract", "output_contracts", "required_output_fields",
    "expected_output", "expected_outputs", "outputs", "contract",
    "output_fields", "result_contract", "deliverable_fields",
    "required_fields", "result_fields",
]
DEFAULT_CONTRACT = [
    "case_id", "status", "sources", "uncertainty", "change_log", "issues",
    "deliverables", "contract_fields", "format_report", "docx", "pdf",
    "template_spec", "metrics", "limits", "verification",
]


def _names_from_contract(value):
    names = []
    if isinstance(value, str):
        names = [x for x in re.split(r"[,;\s]+", value) if x]
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                for key in ("name", "key", "field", "id"):
                    if isinstance(item.get(key), str):
                        names.append(item[key])
                        break
    elif isinstance(value, dict):
        for key in ("required", "fields", "properties", "keys", "items"):
            if isinstance(value.get(key), (list, dict)):
                return _names_from_contract(value[key])
        names = list(value.keys())
    return [n.strip() for n in names if isinstance(n, str) and n.strip()]


def contract_fields(case):
    """Extract the output_contract field names, preserving source order."""
    raw_type = "default"
    found = None
    if isinstance(case, dict):
        for key in CONTRACT_KEYS:
            if key in case and case[key] not in (None, "", [], {}):
                found = case[key]
                raw_type = type(case[key]).__name__
                break
    names = _names_from_contract(found) if found is not None else []
    if not names:
        names = list(DEFAULT_CONTRACT)
        raw_type = "default"
    seen, ordered = set(), []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered, raw_type


def detect_case_id(case, case_path):
    if isinstance(case, dict):
        for key in ("case_id", "caseId", "id", "task_id", "taskId"):
            val = case.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip(), "case.%s" % key
    digest = sha256_file(case_path) if case_path and os.path.exists(case_path) else "0" * 64
    return "case-" + (digest or ("0" * 64))[:12], "sha256(case.json)[:12]"


# ---------------------------------------------------------------- process utils
def which(name):
    return shutil.which(name)


def run(cmd, timeout=120, cwd=None):
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, cwd=cwd)
        return proc.returncode, proc.stdout.decode("utf-8", "replace"), \
            proc.stderr.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", "%s: %s" % (type(exc).__name__, exc)


def pdf_page_count(path):
    """Heuristic page count from a PDF without third-party libraries."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None, "pdf unreadable"
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    counts = [int(x) for x in re.findall(rb"/Count\s+(\d+)", data)]
    if pages:
        return pages, "count of /Type /Page objects"
    if counts:
        return max(counts), "max /Count in page tree"
    return None, "no page markers found"


def pdf_fonts(path):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return {"base_fonts": [], "embedding_markers": 0}
    names = set()
    for raw in re.findall(rb"/BaseFont\s*/([A-Za-z0-9+\-_,#]+)", data):
        name = raw.decode("latin-1")
        name = re.sub(r"#([0-9A-Fa-f]{2})",
                      lambda m: chr(int(m.group(1), 16)), name)
        names.add(name)
    return {"base_fonts": sorted(names),
            "embedding_markers": len(re.findall(rb"/FontFile[23]?", data))}


def font_available(family):
    """Return (available, matched_family, detail)."""
    if not family:
        return False, None, "no font requested"
    fc = which("fc-match")
    if not fc:
        return None, None, "fc-match not installed; availability not checked"
    rc, out, err = run([fc, "-f", "%{family}", family], timeout=20)
    if rc != 0:
        return None, None, (err or "fc-match failed").strip()[:160]
    matched = (out or "").strip().split(",")[0]
    ok = matched.lower().replace(" ", "") == family.lower().replace(" ", "")
    return ok, matched, "fc-match %r -> %r" % (family, matched)


def has_cjk(text):
    return bool(re.search(r"[\u3400-\u9fff\uf900-\ufaff]", text or ""))
