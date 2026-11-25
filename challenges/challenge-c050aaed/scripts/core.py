#!/usr/bin/env python3
"""core.py - 阅读批注与知识沉淀：清单、抽取、锚定、结构化、关联、检索。

标准库实现，不联网。所有页码/坐标/引文只来自输入文件或导出记录；
找不到的引文不猜测位置，标记为待复核。
"""
import csv
import hashlib
import html as htmllib
import io
import json
import os
import re
import zipfile
import zlib
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

VERSION = "anchornotes/1.0.0"
SUPPORTED_DOC_EXT = {".pdf", ".docx", ".docm", ".html", ".htm", ".md", ".markdown", ".txt"}
EXPORT_EXT = {".json", ".jsonl", ".csv", ".tsv", ".xfdf"}
TEXT_OUT_EXT = {".md", ".txt", ".py", ".sh", ".json", ".yaml", ".yml", ".csv", ".tsv"}

TYPE_ALIASES = ["type", "annotationtype", "annot_type", "annottype", "subtype", "kind", "marktype"]
PAGE_ALIASES = ["page", "pagenumber", "page_number", "pageindex", "page_index", "pagelabel",
                "page_label", "pageno"]
QUOTE_ALIASES = ["quote", "highlight", "selectedtext", "selected_text", "annotationtext",
                 "annotation_text", "text", "excerpt", "snippet"]
COMMENT_ALIASES = ["comment", "note", "annotationcomment", "annotation_comment", "body",
                   "memo", "remark", "content"]
COLOR_ALIASES = ["color", "colour", "strokecolor", "stroke_color", "annotationcolor",
                 "annotation_color", "colorhex", "color_hex", "fill"]
LABEL_ALIASES = ["label", "tags", "tag", "category", "topic", "keyword", "keywords"]
AUTHOR_ALIASES = ["author", "creator", "user", "owner", "annotator"]
CREATED_ALIASES = ["created", "date", "modified", "createdat", "created_at", "dateadded",
                   "date_added", "timestamp"]
BBOX_ALIASES = ["rect", "rects", "position", "bbox", "bounds", "quadpoints", "coords",
                "coordinates", "location"]
SOURCE_ALIASES = ["source", "file", "document", "attachment", "attachmenttitle",
                  "attachment_title", "doc", "filename", "file_name", "ref", "parentitem"]
ID_ALIASES = ["id", "key", "annotationid", "annotation_id", "uuid", "itemkey"]

TYPE_MAP = {
    "highlight": "highlight", "underline": "underline", "strikeout": "strikethrough",
    "strikethrough": "strikethrough", "squiggly": "wavy_underline",
    "wavyunderline": "wavy_underline", "text": "note", "note": "marginal_note",
    "freetext": "free_text", "textbox": "free_text", "ink": "handwriting",
    "handwriting": "handwriting", "comment": "comment", "postit": "marginal_note",
    "popup": "marginal_note", "clip": "web_clip", "webclip": "web_clip", "mark": "highlight",
}
NOTE_TYPE_BY_LABEL = {
    "question": "question", "问题": "question", "疑问": "question",
    "method": "method", "方法": "method",
    "conclusion": "conclusion", "结论": "conclusion", "发现": "conclusion",
    "reuse": "reusable", "reusable": "reusable", "可复用": "reusable", "要点": "reusable",
    "todo": "todo", "待验证": "todo", "疑点": "todo", "unverified": "todo",
}

STOP = set("""a an the and or of to in on for with by from as at is are was were be been
this that these those it its we our they their their you your not no yes than then
""".split())

CANON = {
    "caseid": "case_id", "status": "status", "runstatus": "status",
    "summary": "summary", "conclusion": "summary", "abstract": "summary",
    "inputinventory": "input_inventory", "inventory": "input_inventory",
    "manifest": "input_inventory", "filelist": "input_inventory",
    "documents": "documents", "files": "documents", "docs": "documents",
    "metadatasummary": "metadata_summary", "metadata": "metadata_summary",
    "versionrelations": "version_relations", "versions": "version_relations",
    "dedup": "version_relations",
    "annotations": "annotations", "highlights": "annotations", "marks": "annotations",
    "anchorquality": "anchor_quality", "anchoring": "anchor_quality",
    "locatorquality": "anchor_quality",
    "notes": "notes", "knowledge": "notes", "structurednotes": "notes",
    "links": "links", "relations": "links", "associations": "links",
    "searchindexmeta": "search_index_meta", "searchindex": "search_index_meta",
    "index": "search_index_meta", "retrieval": "search_index_meta",
    "searchresults": "search_results", "queries": "search_results",
    "retrievalresults": "search_results",
    "operationslog": "operations_log", "ops": "operations_log", "changeslog": "operations_log",
    "conflicts": "conflicts", "issues": "conflicts",
    "failuresrecovery": "failures_recovery", "skipped": "failures_recovery",
    "recovery": "failures_recovery",
    "uncertainty": "uncertainty", "limits": "limits", "validation": "validation",
    "checks": "validation", "changes": "changes", "assumptions": "assumptions",
}

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
WORD_RE = re.compile(r"[a-z0-9][a-z0-9_+\-]*")


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normkey(s):
    return re.sub(r"[\s_\-]+", "", str(s)).lower()


def read_json(path):
    try:
        return json.loads(read_text(path))
    except Exception:
        return None


def read_text(path):
    """UTF-8 → GB18030 → UTF-16(BOM) 依次尝试，避免中文材料乱码。"""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def as_text(v):
    if v is None:
        return None
    if isinstance(v, list):
        parts = [as_text(x) for x in v]
        parts = [p for p in parts if p]
        return "; ".join(parts) if parts else None
    if isinstance(v, dict):
        for k in ("tag", "name", "value", "text", "label"):
            if k in v:
                return as_text(v[k])
        return None
    s = str(v).strip()
    return s or None


def pick(raw, aliases):
    """大小写/下划线/连字符不敏感的字段取值，同时看 Zotero 风格的一层 data。"""
    scopes = [raw]
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        scopes.append(raw["data"])
    keys = {}
    for sc in scopes:
        for k, v in sc.items():
            keys.setdefault(normkey(k), v)
    for alias in aliases:
        if normkey(alias) in keys:
            return keys[normkey(alias)]
    for k, v in keys.items():
        for alias in aliases:
            if k.startswith(normkey(alias)):
                return v
    return None


def to_int(v):
    m = re.search(r"\d+", str(v or ""))
    return int(m.group(0)) if m else None


def norm_color(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        nums = []
        for x in v:
            try:
                nums.append(float(x))
            except Exception:
                pass
        if len(nums) >= 3:
            nums = nums[:3]
            if max(nums) <= 1.0:
                nums = [x * 255 for x in nums]
            return "#%02x%02x%02x" % tuple(int(round(x)) for x in nums)
        return None
    s = str(v).strip().lower()
    named = {"yellow": "#ffff00", "red": "#ff0000", "green": "#00a000", "blue": "#0000ff",
             "purple": "#800080", "magenta": "#ff00ff", "orange": "#ffa500",
             "gray": "#808080", "grey": "#808080"}
    if s in named:
        return named[s]
    m = re.search(r"#?([0-9a-f]{6})", s)
    return "#" + m.group(1) if m else None


def parse_bbox(v):
    if v is None:
        return None
    if isinstance(v, dict):
        for k in ("rect", "bbox", "bounds"):
            if k in v:
                return parse_bbox(v[k])
        nums = [v.get(k) for k in ("x", "y", "x1", "y1", "width", "height") if v.get(k) is not None]
        return parse_bbox(nums)
    if isinstance(v, str):
        v = re.findall(r"-?\d+(?:\.\d+)?", v)
    nums = []
    try:
        for x in v:
            nums.append(float(x))
    except Exception:
        return None
    if len(nums) >= 8:
        xs, ys = nums[0::2], nums[1::2]
        return [min(xs), min(ys), max(xs), max(ys)]
    if len(nums) >= 4:
        return [min(nums[0], nums[2]), min(nums[1], nums[3]),
                max(nums[0], nums[2]), max(nums[1], nums[3])]
    return None


def iou(a, b):
    if not a or not b:
        return 0.0
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    area_a = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1e-9, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / (area_a + area_b - inter)


# ---------------------------------------------------------------- 契约与清单

def extract_contract_fields(raw):
    oc = None
    for k in ("output_contract", "outputContract", "outputs", "output_schema"):
        if isinstance(raw, dict) and k in raw:
            oc = raw[k]
            break
    names = []
    meta_keys = ("note", "description", "required", "optional", "properties",
                 "fields", "$schema", "type", "version")
    if isinstance(oc, dict):
        if isinstance(oc.get("fields"), list):
            for f in oc["fields"]:
                if isinstance(f, str):
                    names.append(f)
                elif isinstance(f, dict):
                    nm = f.get("name") or f.get("field") or f.get("key")
                    if nm:
                        names.append(nm)
        elif isinstance(oc.get("required"), (list, dict)):
            req = oc["required"]
            names.extend([k for k in (req if isinstance(req, list) else req.keys())
                          if isinstance(k, str)])
            names.extend(oc["required"].keys() if isinstance(oc["required"], dict)
                         and not isinstance(oc["required"], list) else [])
        elif isinstance(oc.get("properties"), dict):
            names.extend(oc["properties"].keys())
        else:
            names = [k for k in oc.keys() if k not in meta_keys]
    elif isinstance(oc, list):
        for f in oc:
            if isinstance(f, str):
                names.append(f)
            elif isinstance(f, dict):
                nm = f.get("name") or f.get("field") or f.get("key")
                if nm:
                    names.append(nm)
    seen, uniq = set(), []
    for nm in names:
        if isinstance(nm, str) and nm not in seen:
            seen.add(nm)
            uniq.append(nm)
    return uniq


def load_case(case_path):
    raw = read_json(case_path) or {}
    case_id = pick(raw, ["case_id", "caseId", "id", "task_id", "taskId"])
    if not case_id:
        case_id = os.path.splitext(os.path.basename(case_path))[0]
    legend = {}
    for k in ("color_legend", "colorLegend", "color_meanings", "colorMeanings"):
        if isinstance(raw.get(k), dict):
            legend = {norm_color(kk) or str(kk).lower(): str(vv) for kk, vv in raw[k].items()}
            break
    questions = []
    for k in ("search_questions", "queries", "search_tasks", "questions"):
        v = raw.get(k)
        if isinstance(v, list):
            questions = v
            break
    return {"case_id": str(case_id), "raw": raw, "contract_fields": extract_contract_fields(raw),
            "color_legend": legend, "search_questions": questions}


def index_materials(materials):
    entries = []
    for dirpath, dirnames, filenames in os.walk(materials):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, materials).replace(os.sep, "/")
            ext = os.path.splitext(name)[1].lower()
            is_link = os.path.islink(p)
            readable = os.access(p, os.R_OK) and not is_link
            entry = {"path": rel, "abs": p, "ext": ext,
                     "bytes": None, "is_symlink": is_link,
                     "readable": readable, "sha256": None}
            if is_link:
                entry["diagnostics"] = ["symlink_not_followed"]
            elif readable:
                try:
                    entry["bytes"] = os.path.getsize(p)
                    entry["sha256"] = sha256_file(p)
                except Exception as exc:  # noqa: BLE001
                    entry["readable"] = False
                    entry["diagnostics"] = ["stat_or_read_failed: %s" % exc]
            if os.path.basename(name) in ("case.json", "task.md"):
                entry["role"] = "case_input"
            elif ext in EXPORT_EXT:
                entry["role"] = "annotation_export"
            elif ext in SUPPORTED_DOC_EXT:
                entry["role"] = "document"
            else:
                entry["role"] = "unsupported"
            entries.append(entry)
    return entries


# ---------------------------------------------------------------- PDF

PDF_STR = rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>"


def _pdf_string(raw):
    if raw is None:
        return None
    if raw.startswith(b"<"):
        h = re.sub(rb"\s", b"", raw[1:-1])
        if len(h) % 2:
            h += b"0"
        try:
            b = bytes.fromhex(h.decode("ascii"))
        except Exception:
            return None
        if b[:2] == b"\xfe\xff":
            return b[2:].decode("utf-16-be", "replace")
        return b.decode("latin-1", "replace")
    s = raw[1:-1].decode("latin-1", "replace")
    return re.sub(r"\\([nrtbf()\\])",
                  lambda m: {"n": "\n", "r": "\r", "t": "\t", "b": "", "f": "",
                             "(": "(", ")": ")", "\\": "\\"}[m.group(1)], s)


def _pdf_objects(data):
    for m in re.finditer(rb"(\d+)\s+\d+\s+obj\b(.*?)endobj", data, re.S):
        yield int(m.group(1)), m.group(2)


def _dec_stream(body):
    m = re.search(rb"stream\r?\n(.*?)\r?\n?endstream", body, re.S)
    if not m:
        return None
    raw = m.group(1)
    if b"/FlateDecode" in body:
        for fn in (zlib.decompress, lambda x: zlib.decompressobj().decompress(x)):
            try:
                return fn(raw)
            except Exception:
                continue
        return None
    return raw


def _pdf_text(content):
    if not content:
        return ""
    s = content.decode("latin-1", "replace")
    out = []
    pat = r"\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f\s]+>|(?:Td|TD|T\*|'|\")"
    for m in re.finditer(pat, s):
        tok = m.group(0)
        if tok.startswith("("):
            t = _pdf_string(tok.encode("latin-1", "replace")) or ""
            out.append(t)
        elif tok.startswith("<"):
            t = _pdf_string(tok.encode("latin-1", "replace")) or ""
            out.append(t)
        else:
            out.append("\n")
    text = "".join(out)
    return re.sub(r"[ \t]+", " ", text).strip()


def _fidelity(text):
    if not text:
        return 0.0
    good = sum(1 for ch in text if ch.isprintable() or ch.isspace())
    bad = text.count("\ufffd")
    return round(max(0.0, good / len(text) - bad / len(text)), 3)


def _page_order(objs, pages):
    by_num = {n: b for n, b in objs}
    ordered = []
    for n, b in objs:
        if re.search(rb"/Type\s*/Pages\b", b):
            m = re.search(rb"/Kids\s*\[(.*?)\]", b, re.S)
            if m:
                for r in re.findall(rb"(\d+)\s+\d+\s+R", m.group(1)):
                    rn = int(r)
                    if rn in by_num and re.search(rb"/Type\s*/Page\b", by_num[rn]) \
                            and not re.search(rb"/Type\s*/Pages\b", by_num[rn]):
                        ordered.append(rn)
            if ordered:
                break
    for n, _ in pages:
        if n not in ordered:
            ordered.append(n)
    return ordered


def _refs_from(body, key):
    m = re.search(rb"/" + key + rb"\s*(\[(.*?)\]|(\d+)\s+\d+\s+R)", body, re.S)
    if not m:
        return []
    if m.group(2) is not None:
        return [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", m.group(2))]
    return [int(m.group(3))]


def _page_text(by_num, body):
    parts = []
    for n in _refs_from(body, b"Contents"):
        d = _dec_stream(by_num.get(n, b""))
        if d:
            parts.append(d)
    return _pdf_text(b"\n".join(parts))


def _pdf_nums(body, key):
    m = re.search(rb"/" + key + rb"\s*\[([^\]]*)\]", body)
    if not m:
        return None
    return [float(x) for x in re.findall(rb"-?\d+(?:\.\d+)?", m.group(1))]


def _parse_pdf_annot(body, page, ref, by_num):
    m = re.search(rb"/Subtype\s*/([A-Za-z0-9]+)", body)
    subtype = m.group(1).decode("ascii", "replace") if m else ""
    if not subtype:
        return None
    quad = _pdf_nums(body, b"QuadPoints")
    rect = _pdf_nums(body, b"Rect")
    bbox = parse_bbox(quad) if quad and len(quad) >= 8 else (parse_bbox(rect) if rect else None)
    cm = re.search(rb"/C\s*\[([^\]]*)\]", body)
    color = None
    if cm:
        vals = [float(x) for x in re.findall(rb"-?\d+(?:\.\d+)?", cm.group(1))]
        color = norm_color(vals)
    t = re.search(rb"/T\s*(" + PDF_STR + rb")", body)
    contents = re.search(rb"/Contents\s*(" + PDF_STR + rb")", body)
    created = re.search(rb"/M\s*(" + PDF_STR + rb")", body)
    subject = re.search(rb"/Subj\s*(" + PDF_STR + rb")", body)
    nm = re.search(rb"/NM\s*(" + PDF_STR + rb")", body)
    raw_type = subtype
    atype = TYPE_MAP.get(normkey(subtype), "unknown")
    return {
        "annotation_id": None, "page": page, "raw_type": raw_type, "type": atype,
        "quote": None, "comment": _pdf_string(contents.group(1)) if contents else None,
        "author": _pdf_string(t.group(1)) if t else None,
        "created": _pdf_string(created.group(1)) if created else None,
        "label": _pdf_string(subject.group(1)) if subject else None,
        "color": color, "bbox": bbox,
        "quads": [quad[i:i + 2] for i in range(0, len(quad) - 1, 2)] if quad else None,
        "origin": "pdf_object", "source_ref": "obj:%d" % ref,
        "native_id": _pdf_string(nm.group(1)) if nm else None,
    }


def parse_pdf(path, rel, sha):
    doc = {"doc_id": None, "source_file": rel, "sha256": sha, "media_type": "application/pdf",
           "title": None, "pages": None, "permission": "readable", "metadata": {},
           "kind": "pdf", "diagnostics": []}
    anns = []
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except Exception as exc:
        doc["permission"] = "unreadable"
        doc["diagnostics"].append("pdf_unreadable: %s" % exc)
        return doc, anns
    tm = re.search(rb"/Title\s*(" + PDF_STR + rb")", data)
    if tm:
        doc["title"] = _pdf_string(tm.group(1))
    doc["metadata"]["file_bytes"] = len(data)
    mver = re.search(rb"%PDF-(\d\.\d)", data[:16])
    doc["metadata"]["pdf_version"] = mver.group(1).decode("ascii", "replace") if mver else None
    if not mver:
        doc["permission"] = "unreadable"
        doc["diagnostics"].append("pdf_invalid_header: 文件头不是 %PDF-，不是可解析 PDF")
        return doc, anns
    if b"/Encrypt" in data:
        doc["permission"] = "encrypted"
        doc["diagnostics"].append("pdf_encrypted: 仅登记元数据，未解析文本层与批注")
        return doc, anns
    objs = list(_pdf_objects(data))
    by_num = {n: b for n, b in objs}
    pages = [(n, b) for n, b in objs
             if re.search(rb"/Type\s*/Page\b", b) and not re.search(rb"/Type\s*/Pages\b", b)]
    order = _page_order(objs, pages)
    doc["pages"] = len(order)
    doc["_page_texts"] = {}
    doc["_page_fidelity"] = {}
    if not order:
        doc["diagnostics"].append("pdf_pages_unreadable: 页面对象位于压缩对象流中，未取得文本层")
    for idx, num in enumerate(order, 1):
        body = by_num[num]
        txt = _page_text(by_num, body)
        doc["_page_texts"][idx] = txt
        doc["_page_fidelity"][idx] = _fidelity(txt)
        for ref in _refs_from(body, b"Annots"):
            ab = by_num.get(ref)
            if not ab:
                doc["diagnostics"].append("pdf_annot_ref_missing: obj:%d" % ref)
                continue
            a = _parse_pdf_annot(ab, idx, ref, by_num)
            if a:
                a["_obj"] = ref
                anns.append(a)
    total = sum(len(v or "") for v in doc["_page_texts"].values())
    doc["metadata"]["text_layer_chars"] = total
    doc["text_layer"] = "available" if total else "unavailable"
    doc["metadata"]["text_layer_fidelity"] = round(
        sum(doc["_page_fidelity"].values()) / max(1, len(doc["_page_fidelity"])), 3)
    if anns:
        doc["diagnostics"].append("pdf_native_annotations: %d" % len(anns))
    return doc, anns


# ---------------------------------------------------------------- DOCX / HTML / 文本

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def parse_docx(path, rel, sha):
    doc = {"doc_id": None, "source_file": rel, "sha256": sha,
           "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
           "title": None, "pages": None, "permission": "readable", "metadata": {},
           "kind": "docx", "diagnostics": [], "_text": "", "_page_texts": {1: ""}}
    anns = []
    try:
        z = zipfile.ZipFile(path)
    except Exception as exc:
        doc["permission"] = "unreadable"
        doc["diagnostics"].append("docx_unreadable: %s" % exc)
        return doc, anns
    names = set(z.namelist())
    if "docProps/core.xml" in names:
        try:
            core = ET.fromstring(z.read("docProps/core.xml"))
            for el in core.iter():
                tag = el.tag.split("}")[-1]
                if not (el.text or "").strip():
                    continue
                if tag == "title":
                    doc["title"] = el.text.strip()
                elif tag in ("creator", "lastModifiedBy", "modified", "created"):
                    doc["metadata"][tag] = el.text.strip()
        except Exception as exc:
            doc["diagnostics"].append("docx_core_meta_unreadable: %s" % exc)
    if "word/document.xml" not in names:
        doc["permission"] = "partial"
        doc["diagnostics"].append("docx_document_xml_missing")
        return doc, anns
    try:
        root = ET.fromstring(z.read("word/document.xml"))
    except Exception as exc:
        doc["permission"] = "unreadable"
        doc["diagnostics"].append("docx_document_xml_broken: %s" % exc)
        return doc, anns
    paras = []
    for p in root.iter(W + "p"):
        paras.append("".join(t.text or "" for t in p.iter(W + "t")))
    doc["_text"] = "\n".join(paras)
    doc["_page_texts"] = {1: doc["_text"]}
    doc["metadata"]["paragraphs"] = len(paras)
    for p in root.iter(W + "p"):
        para_text = "".join(t.text or "" for t in p.iter(W + "t"))
        for r in p.iter(W + "r"):
            hl = r.find(W + "rPr/" + W + "highlight")
            if hl is None:
                continue
            q = "".join(t.text or "" for t in r.iter(W + "t")).strip()
            if not q:
                continue
            anns.append({"page": None, "raw_type": "highlight", "type": "highlight",
                         "quote": q, "comment": None, "author": None, "created": None,
                         "label": "highlight:" + (hl.get(W + "val") or ""),
                         "color": norm_color(hl.get(W + "val")), "bbox": None, "quads": None,
                         "origin": "docx_highlight", "source_ref": "highlight_run",
                         "_para": para_text})
    quotes = {}
    active = {}
    for el in root.iter():
        if el.tag == W + "commentRangeStart":
            active[el.get(W + "id")] = []
        elif el.tag == W + "t":
            for lst in active.values():
                lst.append(el.text or "")
        elif el.tag == W + "commentRangeEnd":
            cid = el.get(W + "id")
            quotes[cid] = "".join(active.pop(cid, [])).strip()
    comments = {}
    if "word/comments.xml" in names:
        try:
            croot = ET.fromstring(z.read("word/comments.xml"))
            for c in croot.iter(W + "comment"):
                comments[c.get(W + "id")] = {
                    "comment": "".join(t.text or "" for t in c.iter(W + "t")).strip(),
                    "author": c.get(W + "author"), "created": c.get(W + "date")}
        except Exception as exc:
            doc["diagnostics"].append("docx_comments_unreadable: %s" % exc)
    for cid, q in quotes.items():
        c = comments.get(cid, {})
        anns.append({"page": None, "raw_type": "comment", "type": "comment",
                     "quote": q or None, "comment": c.get("comment"),
                     "author": c.get("author"), "created": c.get("created"),
                     "label": None, "color": None, "bbox": None, "quads": None,
                     "origin": "docx_comment", "source_ref": "comment:%s" % cid})
    return doc, anns


def parse_html(path, rel, sha):
    doc = {"doc_id": None, "source_file": rel, "sha256": sha, "media_type": "text/html",
           "title": None, "pages": None, "permission": "readable", "metadata": {},
           "kind": "html", "diagnostics": [], "_page_texts": {}}
    anns = []
    try:
        raw = read_text(path)
    except Exception as exc:
        doc["permission"] = "unreadable"
        doc["diagnostics"].append("html_unreadable: %s" % exc)
        return doc, anns
    tm = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if tm:
        doc["title"] = htmllib.unescape(re.sub(r"\s+", " ", tm.group(1))).strip()
    s = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", raw)
    marks = []
    for m in re.finditer(r"(?is)<(mark|span|div|a|p)\b([^>]*)>(.*?)</\1>", s):
        tag, attrs, inner = m.group(1).lower(), m.group(2), m.group(3)
        if tag != "mark" and not re.search(r"(highlight|annotation|note|clip)", attrs, re.I):
            continue
        q = htmllib.unescape(re.sub(r"(?s)<[^>]+>", " ", inner))
        q = re.sub(r"\s+", " ", q).strip()
        if q and len(q) <= 800:
            marks.append({"quote": q, "label": (re.search(r'class\s*=\s*"([^"]*)"', attrs) or
                                                ["", None])[1]})
    text = htmllib.unescape(re.sub(r"(?s)<[^>]+>", " ", s))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    doc["_page_texts"] = {1: text}
    doc["metadata"]["chars"] = len(text)
    for i, mk in enumerate(marks, 1):
        anns.append({"page": None, "raw_type": "webkit_highlight", "type": "web_clip",
                     "quote": mk["quote"], "comment": None, "author": None, "created": None,
                     "label": mk["label"], "color": None, "bbox": None, "quads": None,
                     "origin": "html_mark", "source_ref": "mark:%d" % i})
    return doc, anns


def parse_plain(path, rel, sha):
    doc = {"doc_id": None, "source_file": rel, "sha256": sha,
           "media_type": "text/markdown" if rel.lower().endswith((".md", ".markdown")) else "text/plain",
           "title": None, "pages": None, "permission": "readable", "metadata": {},
           "kind": "text", "diagnostics": [], "_page_texts": {}}
    anns = []
    try:
        raw = read_text(path)
    except Exception as exc:
        doc["permission"] = "unreadable"
        doc["diagnostics"].append("text_unreadable: %s" % exc)
        return doc, anns
    hm = re.search(r"(?m)^#\s+(.+)$", raw)
    doc["title"] = hm.group(1).strip() if hm else None
    doc["_page_texts"] = {1: raw}
    doc["metadata"]["chars"] = len(raw)
    for i, m in enumerate(re.finditer(r"==([^=\n]{2,300})==", raw), 1):
        anns.append({"page": None, "raw_type": "md_highlight", "type": "highlight",
                     "quote": m.group(1).strip(), "comment": None, "author": None,
                     "created": None, "label": None, "color": None, "bbox": None,
                     "quads": None, "origin": "markdown_highlight",
                     "source_ref": "span:%d" % i})
    return doc, anns


# ---------------------------------------------------------------- 导出批注

def parse_xfdf(raw, rel):
    out = []
    for m in re.finditer(r"(?is)<(highlight|underline|strikeout|squiggly|ink|freetext|text)\b([^>]*)>"
                         r"(.*?)</\1>", raw):
        tag, attrs, inner = m.group(1).lower(), m.group(2), m.group(3)
        def attr(name):
            mm = re.search(r'%s\s*=\s*"([^"]*)"' % name, attrs, re.I)
            return mm.group(1) if mm else None
        txt = re.findall(r"(?is)<(?:contents|text)[^>]*>(.*?)</(?:contents|text)>", inner)
        quote = None
        cm = re.search(r'<contents[^>]*>(.*?)</contents>', inner, re.I | re.S)
        if tag in ("highlight", "underline", "strikeout", "squiggly"):
            quote = None
        if cm:
            quote = htmllib.unescape(re.sub(r"<[^>]+>", "", cm.group(1))).strip() or None
        row = {"type": tag, "page": to_int(attr("page")), "quote": quote,
               "comment": None, "color": attr("color"), "label": attr("subject"),
               "author": attr("title"), "created": attr("date"),
               "rect": attr("rect")}
        if quote and tag in ("text", "freetext"):
            row["comment"], row["quote"] = quote, None
        out.append(row)
    return out


def load_export(path, rel):
    ext = os.path.splitext(path)[1].lower()
    rows, diag = [], []
    try:
        if ext == ".json":
            data = read_json(path)
            if isinstance(data, dict):
                for k in ("annotations", "items", "highlights", "records", "data", "notes"):
                    if isinstance(data.get(k), list):
                        rows = data[k]
                        break
                else:
                    rows = [data]
            elif isinstance(data, list):
                rows = data
        elif ext == ".jsonl":
            for line in read_text(path).splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        elif ext in (".csv", ".tsv"):
            delim = "\t" if ext == ".tsv" else ","
            rd = csv.DictReader(io.StringIO(read_text(path)), delimiter=delim)
            rows = [dict(r) for r in rd]
        elif ext == ".xfdf":
            rows = parse_xfdf(read_text(path), rel)
    except Exception as exc:
        diag.append("export_unreadable: %s (%s)" % (rel, exc))
    return rows, diag


def normalize_export_row(row, rel, idx):
    raw_type = as_text(pick(row, TYPE_ALIASES)) or ""
    atype = TYPE_MAP.get(normkey(raw_type), "unknown")
    page = to_int(pick(row, PAGE_ALIASES))
    quote = as_text(pick(row, QUOTE_ALIASES))
    comment = as_text(pick(row, COMMENT_ALIASES))
    if quote and comment and normkey(quote) == normkey(comment):
        comment = None
    label = as_text(pick(row, LABEL_ALIASES))
    src = as_text(pick(row, SOURCE_ALIASES))
    return {
        "annotation_id": None, "page": page, "raw_type": raw_type or None, "type": atype,
        "quote": quote, "comment": comment, "author": as_text(pick(row, AUTHOR_ALIASES)),
        "created": as_text(pick(row, CREATED_ALIASES)), "label": label,
        "color": norm_color(pick(row, COLOR_ALIASES)), "bbox": parse_bbox(pick(row, BBOX_ALIASES)),
        "quads": None, "origin": "export", "source_ref": "%s:row%d" % (rel, idx),
        "declared_source": src, "external_id": as_text(pick(row, ID_ALIASES)),
    }


def load_exports(entries):
    anns, diags = [], []
    for e in entries:
        if e["role"] != "annotation_export" or not e["readable"]:
            continue
        rows, d = load_export(e["abs"], e["path"])
        diags.extend(d)
        for i, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            a = normalize_export_row(row, e["path"], i)
            if not any([a.get("quote"), a.get("comment"), a.get("bbox")]):
                continue
            a["_export_sha"] = e["sha256"]
            anns.append(a)
    return anns, diags


# ---------------------------------------------------------------- 锚定

def norm_with_map(text):
    chars, pos = [], []
    for i, ch in enumerate(text or ""):
        if ch.isspace() or ch in "，。；：、（）【】「」『』“”‘’《》.,;:!?()[]{}<>-—–_/\\|'\"·•…":
            continue
        chars.append(ch.lower())
        pos.append(i)
    return "".join(chars), pos


def locate(quote, text):
    if not quote or not text:
        return None
    qi = text.find(quote)
    if qi >= 0:
        return {"start": qi, "end": qi + len(quote), "method": "exact",
                "occurrences": text.count(quote)}
    ntext, pos = norm_with_map(text)
    nquote, _ = norm_with_map(quote)
    if nquote and nquote in ntext:
        i = ntext.find(nquote)
        return {"start": pos[i], "end": pos[i + len(nquote) - 1] + 1, "method": "normalized",
                "occurrences": ntext.count(nquote)}
    return None


def anchor(a, page_texts, fidelity):
    a["anchor"] = {"status": None, "start": None, "end": None, "verified": False,
                   "ambiguous": False}
    q = (a.get("quote") or "").strip()
    page = a.get("page")
    an = a["anchor"]
    if not q:
        an["status"] = "coordinate_only" if (a.get("bbox") or a.get("quads")) \
            and a.get("type") == "handwriting" else "quote_missing"
        a["needs_review"] = a["type"] == "unknown"
        return a
    if page is None:
        if not page_texts:
            an["status"] = "export_only"
            a["needs_review"] = False
            return a
        page = 1
        an["page_basis"] = "single_text_stream"
    text = (page_texts or {}).get(page)
    if not text:
        an["status"] = "text_layer_unavailable"
        a["needs_review"] = True
        return a
    span = locate(q, text)
    if span:
        an.update({"status": "exact" if span["method"] == "exact" else "normalized",
                   "start": span["start"], "end": span["end"], "verified": True,
                   "ambiguous": span["occurrences"] > 1})
        a["needs_review"] = an["ambiguous"]
        return a
    fid = (fidelity or {}).get(page, 0.0) if isinstance(fidelity, dict) else (fidelity or 0.0)
    if fid and fid < 0.55:
        an["status"] = "low_fidelity_text"
    else:
        an["status"] = "quote_not_found"
    a["needs_review"] = True
    return a


# ---------------------------------------------------------------- 版本与文档

def norm_title(t):
    t = os.path.splitext(os.path.basename(t or ""))[0].lower()
    t = re.sub(r"(?:[\s_\-]*\((\d+)\)|[\s_\-]+(?:copy|副本)|[\s_\-]*v\d+(?:\.\d+)*)$", "", t)
    t = re.sub(r"[\s_\-]+", " ", t).strip()
    return t


def short_hash(s, n=10):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]


def register_documents(docs):
    by_sha = {}
    for d in docs:
        by_sha.setdefault(d["sha256"], []).append(d)
    duplicates = []
    for sha, group in by_sha.items():
        if len(group) > 1:
            primary = group[0]["doc_id"]
            for d in group[1:]:
                d["duplicates_of"] = primary
                duplicates.append({"sha256": sha, "duplicate_of": primary,
                                   "files": [g["source_file"] for g in group]})
    families = {}
    for d in docs:
        key = norm_title(d.get("title") or d.get("source_file"))
        d["title_normalized"] = key
        d["family_id"] = "fam_" + short_hash(key, 8)
        families.setdefault(d["family_id"], []).append(d)
    relations = []
    for fid, group in families.items():
        if len(group) < 2:
            continue
        relations.append({
            "family_id": fid, "title_normalized": group[0]["title_normalized"],
            "members": [{"doc_id": d["doc_id"], "file": d["source_file"],
                         "sha256": d["sha256"], "pages": d.get("pages")} for d in group],
            "basis": "normalized_title", "kind": "version_family",
            "note": "同标题不同哈希，按版本族登记；不自动合并批注引文"})
        for d in group:
            d["version_family"] = fid
    return {"duplicates": duplicates, "version_families": relations}


def page_drift(anns):
    by_family = {}
    for a in anns:
        fam = a.get("_family")
        if not fam or not a.get("quote") or a.get("page") is None:
            continue
        key = (fam, normkey(a["quote"])[:120])
        by_family.setdefault(key, []).append(a)
    conflicts = []
    for (fam, _), group in by_family.items():
        pages = sorted({g["page"] for g in group if g.get("page") is not None})
        docs = {g.get("doc_id") for g in group}
        if len(pages) > 1 and len(docs) > 1:
            conflicts.append({
                "type": "page_drift_between_versions", "family_id": fam,
                "quote": group[0]["quote"][:160], "pages": pages,
                "annotation_ids": [g["annotation_id"] for g in group],
                "handling": "保留各自页码，不做平均、不改写；关联中标注同族不同版本"})
    return conflicts


# ---------------------------------------------------------------- 笔记 / 关联 / 索引

def note_type_for(label):
    if not label:
        return "excerpt"
    for k in NOTE_TYPE_BY_LABEL:
        if k in str(label).lower():
            return NOTE_TYPE_BY_LABEL[k]
    return "excerpt"


def _text_block(a):
    """文本流没有页码时，用空行分段序号做笔记分组，避免所有高亮塌成一条笔记。"""
    texts = a.get("_page_texts") or {}
    page = a.get("page")
    body = texts.get(page) if page is not None else None
    if body is None:
        body = next((v for v in texts.values() if v), "")
    start = (a.get("anchor") or {}).get("start") or 0
    prefix = (body or "")[:start]
    blocks = [b for b in re.split(r"\n\s*\n", prefix) if b.strip()]
    return ("text_block", len(blocks))


def build_notes(anns):
    groups = {}
    for a in anns:
        fam = a.get("_family") or a.get("doc_id") or "unknown"
        label = (a.get("label") or "").strip()
        if label:
            key = ("label", fam, normkey(label))
        else:
            page = a.get("page")
            if page is None:
                page = _text_block(a)
            key = ("page", fam, page)
        groups.setdefault(key, []).append(a)
    notes = []
    for i, (key, group) in enumerate(sorted(groups.items(), key=lambda kv: str(kv[0])), 1):
        group.sort(key=lambda x: (x.get("page") or 0, (x.get("anchor") or {}).get("start") or 0))
        first = group[0]
        label = first.get("label")
        verified_anns = [a for a in group if (a.get("anchor") or {}).get("verified")]
        claim_ann = None
        for a in (verified_anns or group):
            if a.get("comment"):
                claim_ann = a
                break
        if claim_ann is None:
            claim_ann = (verified_anns or group)[0]
        claim = (claim_ann.get("comment") or claim_ann.get("quote"))
        supports = [{"annotation_id": a["annotation_id"], "quote": a.get("quote"),
                     "page": a.get("page"), "anchor_status": (a.get("anchor") or {}).get("status"),
                     "verified": bool((a.get("anchor") or {}).get("verified"))}
                    for a in group if a.get("quote") or a.get("comment")]
        verified = bool((claim_ann.get("anchor") or {}).get("verified"))
        page_out = first.get("page")
        if page_out is None and isinstance(key[2], tuple):
            page_out = None
        notes.append({
            "note_id": "note_%04d" % i,
            "note_type": note_type_for(label),
            "title": (str(label) if label else (claim or "")[:40]),
            "claim": claim,
            "doc_ids": sorted({a["doc_id"] for a in group if a.get("doc_id")}),
            "source_files": sorted({a.get("_file") for a in group if a.get("_file")}),
            "page": page_out,
            "annotation_ids": [a["annotation_id"] for a in group],
            "support": supports,
            "support_status": "verified" if verified else "unverified",
            "tags": sorted({str(label)} if label else set()),
            "needs_review": (not verified) or any(a.get("needs_review") for a in group),
        })
    return notes


def tokens_for(text):
    text = (text or "").lower()
    toks = set(w for w in WORD_RE.findall(text) if len(w) >= 2 and w not in STOP)
    cjk = "".join(CJK_RE.findall(text))
    toks.update(cjk[i:i + 2] for i in range(len(cjk) - 1))
    if 2 <= len(cjk) <= 6:
        toks.add(cjk)
    return toks


def build_links(notes, anns, entities):
    by_id = {a["annotation_id"]: a for a in anns}
    links, rejected = [], []
    lid = 0
    accepted_per_note = {}
    for i, n in enumerate(notes):
        for m in notes[i + 1:]:
            bases = []
            fams_a = {by_id[a].get("_family") for a in n["annotation_ids"] if a in by_id}
            fams_b = {by_id[a].get("_family") for a in m["annotation_ids"] if a in by_id}
            shared_fams = {f for f in (fams_a & fams_b) if f}
            if shared_fams and not (set(n["doc_ids"]) & set(m["doc_ids"])):
                bases.append(("same_version_family", sorted(shared_fams), 0.9))
            shared_labels = set(n["tags"]) & set(m["tags"])
            if shared_labels:
                bases.append(("shared_label", sorted(shared_labels), 0.8))
            shared_ents = (tokens_for(n["title"] + " " + (n["claim"] or "")) &
                           tokens_for(m["title"] + " " + (m["claim"] or "")) &
                           set(e.lower() for e in entities))
            if shared_ents:
                bases.append(("shared_entity", sorted(shared_ents), 0.6))
            same_page = n["page"] is not None and n["page"] == m["page"] and \
                bool(set(n["doc_ids"]) & set(m["doc_ids"]))
            if same_page:
                gaps = []
                for a in n["annotation_ids"]:
                    for b in m["annotation_ids"]:
                        aa, bb = by_id.get(a), by_id.get(b)
                        if not aa or not bb:
                            continue
                        ga = (aa.get("anchor") or {}).get("start")
                        gb = (bb.get("anchor") or {}).get("start")
                        if ga is not None and gb is not None:
                            gaps.append(abs(ga - gb))
                if gaps and min(gaps) <= 80:
                    bases.append(("same_page_adjacent", ["gap=%d" % min(gaps)], 0.5))
            if not bases:
                ta = tokens_for(n["title"] + " " + (n["claim"] or ""))
                tb = tokens_for(m["title"] + " " + (m["claim"] or ""))
                shared = ta & tb
                jac = len(shared) / max(1.0, len(ta | tb))
                if len(shared) >= 2 and jac >= 0.5:
                    lid += 1
                    rejected.append({"link_id": "link_%04d" % lid, "from_note": n["note_id"],
                                     "to_note": m["note_id"], "basis": "keyword_overlap",
                                     "shared": sorted(shared)[:8], "confidence": round(jac, 3),
                                     "accepted": False,
                                     "reason": "仅词面重合，默认不连边（控制过度连接）"})
                continue
            bases.sort(key=lambda x: -x[2])
            basis, shared, conf = bases[0]
            lid += 1
            keep = accepted_per_note.get(n["note_id"], 0) < 3 and \
                accepted_per_note.get(m["note_id"], 0) < 3
            links.append({"link_id": "link_%04d" % lid, "from_note": n["note_id"],
                          "to_note": m["note_id"], "basis": basis, "shared": shared,
                          "confidence": conf, "accepted": keep,
                          "reason": "依据成立" if keep else "超过每笔记接受关联上限 3，降级为拒绝"})
            if keep:
                accepted_per_note[n["note_id"]] = accepted_per_note.get(n["note_id"], 0) + 1
                accepted_per_note[m["note_id"]] = accepted_per_note.get(m["note_id"], 0) + 1
    return links, rejected


def build_index(notes):
    postings = {}
    summary = []
    for n in notes:
        text = " ".join([n.get("title") or "", n.get("claim") or "",
                         " ".join(n.get("tags") or []),
                         " ".join((s.get("quote") or "") for s in n.get("support") or [])])
        for t in tokens_for(text):
            postings.setdefault(t, []).append(n["note_id"])
        summary.append({"note_id": n["note_id"], "title": n.get("title"),
                        "note_type": n.get("note_type"), "doc_ids": n.get("doc_ids"),
                        "page": n.get("page"), "tags": n.get("tags"),
                        "support_status": n.get("support_status")})
    index = {"version": VERSION, "note_count": len(notes), "vocabulary": len(postings),
             "postings": {k: sorted(set(v)) for k, v in postings.items()},
             "notes": summary,
             "filters": ["tag", "doc_id", "since", "note_type"]}
    return index


def run_queries(index, notes, questions):
    by_id = {n["note_id"]: n for n in notes}
    results, log = [], []
    for i, q in enumerate(questions, 1):
        if isinstance(q, dict):
            query = as_text(pick(q, ["query", "question", "text", "q"])) or ""
            filters = {k: q[k] for k in ("tag", "doc_id", "since", "note_type") if k in q}
        else:
            query, filters = str(q), {}
        qid = "q%02d" % i
        hits = search_index(index, query, filters)
        log.append({"question_id": qid, "query": query, "filters": filters,
                    "hits": len(hits["hits"]), "recall_note": hits["recall_note"]})
        for rank, h in enumerate(hits["hits"][:5], 1):
            n = by_id.get(h["note_id"], {})
            anchor_status = None
            for s in n.get("support") or []:
                if s.get("verified"):
                    anchor_status = s.get("anchor_status")
                    break
            results.append({"question_id": qid, "query": query, "filters": filters,
                            "rank": rank, "note_id": h["note_id"], "score": h["score"],
                            "title": n.get("title"), "doc_ids": n.get("doc_ids"),
                            "page": n.get("page"),
                            "anchor_status": anchor_status or (n.get("support") or [{}])[0].get("anchor_status")})
    return results, log


def search_index(index, query, filters=None):
    filters = filters or {}
    q = tokens_for(query)
    candidates = {}
    for t in q:
        for nid in (index.get("postings") or {}).get(t, []):
            candidates[nid] = candidates.get(nid, 0) + 1
    meta = {m["note_id"]: m for m in index.get("notes") or []}
    hits = []
    for nid, score in candidates.items():
        m = meta.get(nid, {})
        if filters.get("tag") and filters["tag"] not in (m.get("tags") or []):
            continue
        if filters.get("doc_id") and filters["doc_id"] not in (m.get("doc_ids") or []):
            continue
        if filters.get("note_type") and filters["note_type"] != m.get("note_type"):
            continue
        if filters.get("since") and m.get("note_id") is None:
            continue
        hits.append({"note_id": nid, "score": score})
    hits.sort(key=lambda h: (-h["score"], h["note_id"]))
    recall = "normal"
    if not hits:
        recall = ("零命中：已记录查询；建议去掉 tag/doc_id 过滤、改用同义词或单字术语，"
                  "不得解读为资料不存在")
    elif len(hits) == 1 and len(q) > 1:
        recall = "单条命中，召回可能偏窄；建议放宽为 OR 或减少限定词"
    return {"query": query, "filters": filters, "hits": hits, "recall_note": recall}


# ---------------------------------------------------------------- 结果组装

def finalize_contract(result, fields):
    for f in fields:
        key = CANON.get(normkey(f))
        if key and key not in result:
            result[f] = result.get(key)
        elif key and f != key:
            result[f] = result.get(key)
        if f not in result:
            result[f] = {"note": "输入契约未定义该字段的取值口径；保留字段名与空值说明，不补造内容。"}
    return result


def validate(result):
    anns, notes = result["annotations"], result["notes"]
    links = result["links"]
    checks = []

    def add(check, ok, detail=""):
        checks.append({"check": check, "pass": bool(ok), "detail": detail})

    inv = [e for e in result["input_inventory"] if e.get("readable")]
    add("input_manifest_complete", all(e.get("sha256") for e in inv) if inv else True,
        "%d 个可读文件" % len(inv))
    add("every_annotation_has_locator",
        all(a.get("source", {}).get("file") and a.get("source", {}).get("ref") for a in anns),
        "%d 条批注" % len(anns))
    add("no_guessed_anchor",
        all((not a["anchor"]["verified"]) or
            (a["anchor"]["start"] is not None and a["anchor"]["end"] is not None) for a in anns),
        "已验证锚点均有字符区间")
    supported = [n for n in notes if n.get("annotation_ids") and n.get("claim")]
    add("every_note_has_support", len(supported) == len(notes),
        "%d/%d 条笔记有支撑" % (len(supported), len(notes)))
    accepted = [l for l in links if l.get("accepted")]
    add("no_link_without_basis", all(l.get("basis") and l.get("shared") for l in accepted),
        "%d 条接受关联" % len(accepted))
    add("duplicates_and_versions_registered",
        bool(result["version_relations"]["duplicates"] or
             result["version_relations"]["version_families"]) or
        len(result["documents"]) <= 1,
        "重复 %d 组，版本族 %d 组" % (len(result["version_relations"]["duplicates"]),
                                     len(result["version_relations"]["version_families"])))
    add("contract_fields_present",
        all(f in result for f in result["_contract_fields"]),
        "%d 个契约字段" % len(result["_contract_fields"]))
    unread = [e for e in result["input_inventory"] if not e.get("readable")]
    skipped_paths = {s.get("path") or s.get("file")
                     for s in result["failures_recovery"].get("skipped", [])}
    diag_text = " | ".join(str(d.get("detail") if isinstance(d, dict) else d)
                            for d in result["failures_recovery"]["diagnostics"])
    add("no_silent_drop",
        all(e["path"] in skipped_paths or e["path"] in diag_text for e in unread)
        if unread else True,
        "%d 个不可读/符号链接文件已登记" % len(unread))
    return checks
