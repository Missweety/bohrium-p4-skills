#!/usr/bin/env python3
"""core.py - 科研选题与创新性评估：来源、纳排、证据矩阵、创新判定、可行性。

标准库实现，不联网。字段抽取为线索句摘录；缺失一律 not_reported/unknown，
不生成来源没有的结论，不给全局新颖性断言。
"""
import csv
import hashlib
import html as htmllib
import json
import os
import re
import zipfile
import zlib
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

VERSION = "proposal-auditor/1.1.0"

TITLE_A = ["title", "标题", "name", "itemtitle"]
AUTHOR_A = ["authors", "author", "作者", "creators"]
YEAR_A = ["year", "年份", "publicationyear", "date", "issued"]
VENUE_A = ["venue", "journal", "期刊", "container", "publisher", "会议"]
ABSTRACT_A = ["abstract", "摘要", "summary"]
DOI_A = ["doi"]
URL_A = ["url", "link", "链接"]
KEYWORD_A = ["keywords", "keyword", "关键词", "tags"]
TYPE_A = ["type", "publicationtype", "类型", "doctype", "itemtype"]
LANG_A = ["language", "语种", "lang"]

PROPOSAL_A = ["proposal", "researchidea", "idea", "motivation", "description", "abstract", "summary"]
RQ_A = ["researchquestion", "question", "topic", "研究问题"]
OBJECT_A = ["object", "研究对象", "researchobject"]
VARIABLE_A = ["variables", "keyvariables", "关键变量", "变量"]
BASELINE_A = ["baseline", "comparisonbaseline", "比较基线", "baselinecondition"]
EXPECTED_A = ["expectedconclusion", "expectedresult", "预期结论", "hypothesis"]
FALSIFIER_A = ["falsifier", "falsificationcondition", "可证伪条件", "falsify"]
NOVELTY_A = ["noveltyclaims", "innovations", "contributions", "创新点", "创新陈述"]
PREREQ_A = ["prerequisites", "prerequisite", "constraints", "resources", "前提", "资源", "约束"]
ASSUME_A = ["assumptions", "assumption", "假设"]

CONCEPT_STOP = set("""research study method methods approach paper using based analysis model models
data result results new novel task problem propose proposed system framework experiment
""".split()) | set("研究 方法 分析 影响 基于 问题 本文 工作 结果 数据 模型 论文 提出".split())

POS_CUES = ["improve", "outperform", "effective", "significant gain", "提升", "有效", "优于", "改善", "增强"]
NEG_CUES = ["no improvement", "ineffective", "not effective", "fail", "decrease", "no significant",
            "无效", "下降", "不及", "没有提升", "未改善", "失败"]

FIELD_CUES = {
    "task": ["we study", "we investigate", "we address", "this paper studies", "本文研究",
             "针对", "旨在", "task of", "problem of"],
    "method": ["we propose", "we present", "we introduce", "our method", "our approach",
               "本文提出", "方法", "framework", "模型", "算法"],
    "data": ["dataset", "datasets", "corpus", "benchmark", "数据", "样本", "语料", "标注"],
    "evaluation": ["evaluate", "experiment", "experiments", "results", "metric", "评测",
                   "实验", "指标", "对比实验"],
    "conclusion": ["results show", "results indicate", "we find", "we conclude", "our results",
                   "show that", "show no", "indicate that", "表明", "发现", "结论", "验证了", "显示"],
}
FIELD_GENERIC = {"task", "method", "data", "evaluation", "conclusion", "not_reported"}

CANON = {
    "caseid": "case_id", "status": "status", "runstatus": "status",
    "summary": "summary", "conclusion": "summary", "abstract": "summary",
    "problemstatement": "problem_statement", "problem": "problem_statement",
    "researchquestion": "problem_statement", "questiondefinition": "problem_statement",
    "scope": "scope", "searchscope": "scope", "boundary": "scope",
    "sources": "sources", "records": "sources", "literature": "sources",
    "screening": "screening", "eligibility": "screening", "decisions": "screening",
    "reasoncodes": "reason_codes", "codebook": "reason_codes",
    "evidencematrix": "evidence_matrix", "comparisonmatrix": "evidence_matrix",
    "matrix": "evidence_matrix",
    "novelty": "novelty", "innovation": "novelty", "noveltyassessment": "novelty",
    "feasibility": "feasibility", "conditions": "feasibility", "risk": "feasibility",
    "conflicts": "conflicts", "contradictoryevidence": "conflicts",
    "gaps": "gaps", "researchgaps": "gaps", "opportunities": "gaps",
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
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def short_hash(s, n=10):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]


def as_text(v):
    if v is None:
        return None
    if isinstance(v, list):
        parts = [as_text(x) for x in v]
        parts = [p for p in parts if p]
        return "; ".join(parts) if parts else None
    if isinstance(v, dict):
        for k in ("tag", "name", "value", "text", "label", "title"):
            if k in v:
                return as_text(v[k])
        return None
    s = str(v).strip()
    return s or None


def pick(raw, aliases):
    if not isinstance(raw, dict):
        return None
    scopes = [raw]
    if isinstance(raw.get("data"), dict):
        scopes.append(raw["data"])
    keys = {}
    for sc in scopes:
        for k, v in sc.items():
            keys.setdefault(normkey(k), v)
    for alias in aliases:
        if normkey(alias) in keys:
            return keys[normkey(alias)]
    return None


def as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        out = []
        for x in v:
            t = as_text(x)
            if t:
                out.append(t)
        return out
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[,;，；]", v) if x.strip()]
    t = as_text(v)
    return [t] if t else []


def to_int(v):
    m = re.search(r"\d{4}", str(v or ""))
    return int(m.group(0)) if m else None


def tokens_for(text):
    text = (text or "").lower()
    toks = set(w for w in WORD_RE.findall(text) if len(w) >= 3 and w not in CONCEPT_STOP)
    cjk = "".join(CJK_RE.findall(text))
    toks.update(cjk[i:i + 2] for i in range(len(cjk) - 1))
    return toks


def content_terms(text):
    text = (text or "").lower()
    out = set(w for w in WORD_RE.findall(text) if len(w) >= 4 and w not in CONCEPT_STOP)
    cjk = "".join(CJK_RE.findall(text))
    out.update(cjk[i:i + 2] for i in range(len(cjk) - 1))
    return out - FIELD_GENERIC


def sentences(text):
    if not text:
        return []
    # 中文句号/问号/叹号后通常没有空格，不能像英文那样要求空白才切句；
    # 但 ASCII 的 ?/! 可能是 URL 的一部分（如 a?b=1），只在后面是空白/行尾时才切。
    parts = re.split(r"(?<=[。！？])\s*|(?<=[!?])(?=\s|$)|\s*(?<=\.)\s+(?=[A-Z\u4e00-\u9fff])|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def find_sentence(text, terms):
    best, best_hit = None, 0
    for s in sentences(text):
        hit = len(content_terms(s) & set(terms))
        if hit > best_hit:
            best, best_hit = s, hit
    return best, best_hit


def cue_sentence(text, cues):
    for s in sentences(text):
        low = s.lower()
        if any(c.lower() in low for c in cues):
            return s
    return None


def norm_title(t):
    """标题归一：只统一大小写与空白/下划线/连字符，不按路径截断。

    旧实现用 os.path.basename，标题含 '/'（如 COVID-19/SARS-CoV-2）会被截断，
    与另一条记录得到同一去重键而被误合并。
    """
    t = str(t or "").strip().lower()
    return re.sub(r"[\s_\-]+", " ", t).strip()


def file_stem(path):
    """文件型来源缺标题时用文件名兜底；只有这里才需要 basename。"""
    return norm_title(os.path.splitext(os.path.basename(path or ""))[0])


# ---------------------------------------------------------------- PDF / 文档

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


def _obj_text(body):
    content = b""
    m = re.search(rb"stream\r?\n(.*?)\r?\n?endstream", body, re.S)
    if m:
        content = m.group(1)
        if b"/FlateDecode" in body:
            try:
                content = zlib.decompress(content)
            except Exception:
                try:
                    content = zlib.decompressobj().decompress(content)
                except Exception:
                    content = b""
    s = content.decode("latin-1", "replace")
    out = []
    for mm in re.finditer(r"\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f\s]+>|(?:Td|TD|T\*|'|\")", s):
        tok = mm.group(0)
        if tok.startswith(("(", "<")):
            out.append(_pdf_string(tok.encode("latin-1", "replace")) or "")
        else:
            out.append("\n")
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def parse_pdf_pages(path):
    with open(path, "rb") as fh:
        data = fh.read()
    title = None
    tm = re.search(rb"/Title\s*(" + PDF_STR + rb")", data)
    if tm:
        title = _pdf_string(tm.group(1))
    if b"/Encrypt" in data:
        return {"title": title, "pages": [], "encrypted": True}
    objs = list(re.finditer(rb"(\d+)\s+\d+\s+obj\b(.*?)endobj", data, re.S))
    by_num = {int(m.group(1)): m.group(2) for m in objs}
    pages = []
    for n, b in by_num.items():
        if re.search(rb"/Type\s*/Page\b", b) and not re.search(rb"/Type\s*/Pages\b", b):
            pages.append((n, b))
    texts = []
    for n, b in pages:
        cm = re.search(rb"/Contents\s*(\[(.*?)\]|(\d+)\s+\d+\s+R)", b, re.S)
        parts = []
        if cm:
            refs = ([int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", cm.group(2))]
                    if cm.group(2) is not None else [int(cm.group(3))])
            for r in refs:
                if r in by_num:
                    parts.append(_obj_text(by_num[r]))
        texts.append("\n".join(p for p in parts if p))
    return {"title": title, "pages": texts, "encrypted": False}


def parse_docx_text(path):
    try:
        z = zipfile.ZipFile(path)
    except Exception:
        return {"title": None, "text": ""}
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    title = None
    if "docProps/core.xml" in z.namelist():
        try:
            core = ET.fromstring(z.read("docProps/core.xml"))
            for el in core.iter():
                if el.tag.split("}")[-1] == "title" and (el.text or "").strip():
                    title = el.text.strip()
        except Exception:
            pass
    text = ""
    if "word/document.xml" in z.namelist():
        try:
            root = ET.fromstring(z.read("word/document.xml"))
            text = "\n".join("".join(t.text or "" for t in p.iter(W + "t"))
                             for p in root.iter(W + "p"))
        except Exception:
            pass
    return {"title": title, "text": text}


def parse_html_text(path):
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return {"title": None, "text": ""}
    tm = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    title = htmllib.unescape(re.sub(r"\s+", " ", tm.group(1))).strip() if tm else None
    s = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", raw)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = htmllib.unescape(re.sub(r"[ \t]+", " ", s))
    return {"title": title, "text": re.sub(r"\n\s*\n+", "\n", s).strip()}


# ---------------------------------------------------------------- 清单与来源

def index_files(materials):
    entries = []
    for dirpath, dirnames, filenames in os.walk(materials):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, materials).replace(os.sep, "/")
            ext = os.path.splitext(name)[1].lower()
            readable = os.access(p, os.R_OK) and not os.path.islink(p)
            e = {"path": rel, "abs": p, "ext": ext, "readable": readable,
                 "bytes": os.path.getsize(p) if readable else None, "sha256": None}
            if readable:
                try:
                    e["sha256"] = sha256_file(p)
                except Exception:
                    e["readable"] = False
            if name in ("case.json", "task.md") or ext == ".yaml":
                e["role"] = "case_input"
            elif ext in (".json", ".jsonl", ".csv", ".tsv"):
                e["role"] = "biblio"
            elif ext in (".pdf", ".docx", ".docm", ".html", ".htm", ".md", ".markdown", ".txt"):
                e["role"] = "document"
            else:
                e["role"] = "unsupported"
            entries.append(e)
    return entries


def record_to_source(row, file, locator):
    title = as_text(pick(row, TITLE_A))
    if not title:
        return None
    abstract = as_text(pick(row, ABSTRACT_A))
    s = {
        "source_id": None, "file": file, "locator": locator, "sha256": None,
        "title": title, "authors": as_list(pick(row, AUTHOR_A)),
        "year": to_int(pick(row, YEAR_A)), "venue": as_text(pick(row, VENUE_A)),
        "doi": as_text(pick(row, DOI_A)), "url": as_text(pick(row, URL_A)),
        "keywords": as_list(pick(row, KEYWORD_A)),
        "type": as_text(pick(row, TYPE_A)), "language": as_text(pick(row, LANG_A)),
        "abstract": abstract, "text": abstract or "", "pages": None,
        "permission": "readable", "provenance": [{"file": file, "locator": locator}],
        "diagnostics": [],
    }
    s["source_id"] = "src_" + short_hash((s["doi"] or s["title"] + str(s["year"] or "")))
    return s


def load_biblio(path, rel):
    ext = os.path.splitext(path)[1].lower()
    rows = []
    try:
        if ext == ".json":
            data = read_json(path)
            if isinstance(data, dict):
                for k in ("records", "items", "sources", "data", "literature", "results"):
                    if isinstance(data.get(k), list):
                        rows = data[k]
                        break
                else:
                    rows = [data]
            elif isinstance(data, list):
                rows = data
        elif ext == ".jsonl":
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except Exception:
                            continue
        else:
            with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
                rd = csv.DictReader(fh, delimiter="\t" if ext == ".tsv" else ",")
                rows = [dict(r) for r in rd]
    except Exception:
        return []
    out = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        s = record_to_source(row, rel, {"kind": "row", "row": i})
        if s:
            out.append(s)
    return out


def build_sources(entries):
    sources, skipped = [], []
    for e in entries:
        if e["role"] == "unsupported":
            skipped.append({"file": e["path"], "reason": "unsupported_type: %s" % (e["ext"] or "none")})
            continue
        if e["role"] not in ("document", "biblio"):
            continue
        if not e["readable"]:
            skipped.append({"file": e["path"], "reason": "unreadable_or_symlink"})
            continue
        if e["role"] == "biblio":
            recs = load_biblio(e["abs"], e["path"])
            if not recs:
                skipped.append({"file": e["path"], "reason": "biblio_empty_or_unreadable"})
            for s in recs:
                s["sha256"] = e["sha256"]
            sources.extend(recs)
            continue
        if e["ext"] == ".pdf":
            info = parse_pdf_pages(e["abs"])
            text = "\n".join(info["pages"])
            sources.append({
                "source_id": None, "file": e["path"],
                "locator": {"kind": "page", "page": 1}, "sha256": e["sha256"],
                "title": info.get("title") or file_stem(e["path"]),
                "authors": [], "year": None, "venue": None, "doi": None, "url": None,
                "keywords": [], "type": "pdf",
                "language": "zh" if CJK_RE.search(text) else "en",
                "abstract": text[:1500], "text": text, "pages": len(info["pages"]),
                "permission": "encrypted" if info.get("encrypted") else "readable",
                "provenance": [{"file": e["path"], "locator": {"kind": "page", "page": 1}}],
                "diagnostics": [] if text else ["pdf_text_layer_unavailable"],
            })
        elif e["ext"] in (".docx", ".docm"):
            info = parse_docx_text(e["abs"])
            text = info["text"]
            sources.append({
                "source_id": None, "file": e["path"], "locator": {"kind": "docx", "page": None},
                "sha256": e["sha256"], "title": info.get("title") or file_stem(e["path"]),
                "authors": [], "year": None, "venue": None, "doi": None, "url": None,
                "keywords": [], "type": "docx", "language": "zh" if CJK_RE.search(text) else "en",
                "abstract": text[:1500], "text": text, "pages": None, "permission": "readable",
                "provenance": [{"file": e["path"], "locator": {"kind": "docx"}}],
                "diagnostics": [] if text else ["docx_text_unavailable"],
            })
        else:
            if e["ext"] in (".html", ".htm"):
                info = parse_html_text(e["abs"])
            else:
                raw = open(e["abs"], encoding="utf-8", errors="replace").read()
                hm = re.search(r"(?m)^#\s+(.+)$", raw)
                info = {"title": hm.group(1).strip() if hm else None, "text": raw}
            text = info["text"]
            sources.append({
                "source_id": None, "file": e["path"], "locator": {"kind": "section", "page": 1},
                "sha256": e["sha256"], "title": info.get("title") or file_stem(e["path"]),
                "authors": [], "year": None, "venue": None, "doi": None, "url": None,
                "keywords": [], "type": e["ext"].lstrip("."), "language": "zh" if CJK_RE.search(text) else "en",
                "abstract": text[:1500], "text": text, "pages": None, "permission": "readable",
                "provenance": [{"file": e["path"], "locator": {"kind": "section"}}],
                "diagnostics": [] if text else ["text_unreadable"],
            })
    for s in sources:
        if not s.get("source_id"):
            s["source_id"] = "src_" + short_hash(
                (s.get("doi") or s.get("title") or "") + str(s.get("year") or ""))
    return dedupe_sources(sources), skipped


def dedupe_sources(sources):
    merged = {}
    order = []
    for s in sources:
        key = ("doi:" + s["doi"].lower()) if s.get("doi") else \
            ("title:" + norm_title(s.get("title")) + "|" + str(s.get("year") or ""))
        if key in merged:
            prev = merged[key]
            for f in ("abstract", "text", "year", "venue", "doi", "url", "type", "language"):
                if not prev.get(f) and s.get(f):
                    prev[f] = s[f]
            prev["provenance"].extend(s.get("provenance") or [])
            if len(s.get("text") or "") > len(prev.get("text") or ""):
                prev["text"] = s["text"]
            continue
        s["provenance"] = s.get("provenance") or [{"file": s["file"], "locator": s["locator"]}]
        merged[key] = s
        order.append(key)
    return [merged[k] for k in order]


# ---------------------------------------------------------------- 问题拆解

def load_case(case_path, materials):
    raw = read_json(case_path) or {}
    case_id = as_text(pick(raw, ["case_id", "caseId", "id", "task_id"])) or \
        os.path.basename(os.path.abspath(materials)) or "case"
    proposal = as_text(pick(raw, PROPOSAL_A)) or ""
    rq = as_text(pick(raw, RQ_A)) or ""
    explicit = {}
    for key, aliases in (("object", OBJECT_A), ("variables", VARIABLE_A),
                         ("baseline", BASELINE_A), ("expected_conclusion", EXPECTED_A),
                         ("falsifier", FALSIFIER_A)):
        v = pick(raw, aliases)
        explicit[key] = as_text(v) if not isinstance(v, list) else as_list(v)
    claims = pick(raw, NOVELTY_A)
    prereq = pick(raw, PREREQ_A)
    assumptions = as_list(pick(raw, ASSUME_A))
    contract = []
    oc = raw.get("output_contract") or raw.get("outputContract") or raw.get("outputs")
    if isinstance(oc, dict):
        if isinstance(oc.get("fields"), list):
            contract = [f if isinstance(f, str) else (f.get("name") or f.get("field"))
                        for f in oc["fields"]]
        else:
            contract = list(oc.keys())
    elif isinstance(oc, list):
        contract = [f if isinstance(f, str) else (f.get("name") or f.get("field")) for f in oc]
    contract = [c for c in contract if c]
    return {"case_id": case_id, "raw": raw, "proposal": proposal, "rq": rq,
            "explicit": explicit, "claims": claims, "prereq": prereq,
            "assumptions": assumptions, "contract_fields": contract}


def decompose(case):
    raw = case["raw"]
    text = " ".join(x for x in (case["rq"], case["proposal"]) if x)
    out = {}
    patterns = {
        "object": [r"(?:研究对象|object)\s*[:：]\s*([^。；;\n]{2,80})",
                   r"(?:针对|面向)\s*([^。；;\n]{2,60})"],
        "variables": [r"(?:关键变量|variables?)\s*[:：]\s*([^。；;\n]{2,100})"],
        "baseline": [r"(?:比较基线|baseline)\s*[:：]\s*([^。；;\n]{2,100})",
                     r"(?:相比|compared (?:with|to))\s*([^。；;\n]{2,60})"],
        "expected_conclusion": [r"(?:预期结论|expected (?:conclusion|result))\s*[:：]\s*([^。；;\n]{2,120})"],
        "falsifier": [r"(?:可证伪条件|falsifier|falsification)\s*[:：]\s*([^。；;\n]{2,120})",
                      r"(?:若|如果)\s*([^。；;\n]{2,80})(?:则|就)"],
    }
    for key, pats in patterns.items():
        val = case["explicit"].get(key)
        if val:
            out[key] = {"value": val, "source": "case_field"}
            continue
        hit = None
        for pat in pats:
            m = re.search(pat, text, re.I)
            if m:
                hit = m.group(1).strip()
                break
        out[key] = ({"value": hit, "source": "extracted"} if hit
                    else {"value": None, "source": "undefined", "note": "输入未给出"})
    missing = [k for k in ("object", "variables", "baseline", "expected_conclusion", "falsifier")
               if not out[k].get("value")]
    out["falsifiable"] = not missing
    out["missing"] = missing
    out["needs_input"] = bool(missing)
    out["template"] = {
        "object": "在<对象/场景>中，比较<方法A>与<基线B>对<可观测指标>的影响。",
        "note": "以上为补全模板，不是用户结论；填充后才可判定可证伪性。"}
    return out


# ---------------------------------------------------------------- 纳排

def criteria_from_case(case):
    raw = case["raw"]
    return {
        "year_from": to_int(pick(raw, ["yearfrom", "startyear", "fromyear", "year_from"])),
        "year_to": to_int(pick(raw, ["yearto", "endyear", "toyear", "year_to"])),
        "languages": [x.lower() for x in as_list(pick(raw, ["languages", "language", "语种"]))],
        "types": [x.lower() for x in as_list(pick(raw, ["types", "publicationtypes",
                                                        "doctypes", "文献类型"]))],
        "exclude_terms": [x.lower() for x in as_list(pick(
            raw, ["excludeterms", "exclusions", "exclusionterms", "排除词"]))],
        "criteria_version": as_text(pick(raw, ["criteriaversion"])) or "v1",
    }


def concept_terms(case):
    terms = set()
    for k in ("keywords", "concepts", "conceptterms", "terms", "关键词"):
        v = pick(case["raw"], [k])
        if v:
            terms.update(x.lower() for x in as_list(v) if len(x) >= 2)
    for k in ("keywordsen", "conceptsen", "englishkeywords", "termsen"):
        v = pick(case["raw"], [k])
        if v:
            terms.update(x.lower() for x in as_list(v) if len(x) >= 2)
    tr = pick(case["raw"], ["translations", "conceptglossary", "glossary"])
    if isinstance(tr, dict):
        for k, v in tr.items():
            terms.add(str(k).lower())
            for x in as_list(v):
                terms.add(x.lower())
    q = (case["rq"] or "") + " " + (case["proposal"] or "")[:600]
    terms.update(content_terms(q))
    return terms


REASON_CODES = {
    "IN_TOPIC_MATCH": "标题/摘要覆盖≥2 个问题概念词，纳入证据矩阵",
    "EX_YEAR_OUT_OF_WINDOW": "年份在给定检索窗口之外",
    "EX_EXCLUDE_TERM": "标题/摘要命中排除词",
    "EX_TYPE_MISMATCH": "文献类型不在给定范围内",
    "EX_LANGUAGE_MISMATCH": "语种不在给定范围内",
    "REV_YEAR_MISSING": "年份缺失，未默认在窗内，转人工确认",
    "REV_WEAK_TOPIC_MATCH": "仅覆盖 1 个概念词，转人工确认",
    "REV_NO_TOPIC_MATCH": "未命中问题概念词，不直接排除，转人工确认",
    "REV_METADATA_INCOMPLETE": "关键元数据缺失，转人工确认",
}


def screen_sources(sources, crit, concepts):
    decisions = []
    for s in sources:
        text = ((s.get("title") or "") + " " + (s.get("abstract") or "")).lower()
        year = s.get("year")
        overlap = sorted(concepts & content_terms(text))
        quote, _ = find_sentence(s.get("abstract") or s.get("title") or "", overlap)
        ev = {"file": s["file"], "locator": s["locator"], "quote": (quote or s.get("title") or "")[:240]}
        d = {"source_id": s["source_id"], "title": s.get("title"), "year": year,
             "decision": None, "reason_code": None, "reason": None,
             "evidence": ev, "overlap_terms": overlap[:10],
             "criteria_version": crit["criteria_version"], "needs_human": False}
        if crit["year_from"] and year and year < crit["year_from"]:
            d.update({"decision": "exclude", "reason_code": "EX_YEAR_OUT_OF_WINDOW",
                      "reason": "年份 %s < 起始年 %s" % (year, crit["year_from"])})
        elif crit["year_to"] and year and year > crit["year_to"]:
            d.update({"decision": "exclude", "reason_code": "EX_YEAR_OUT_OF_WINDOW",
                      "reason": "年份 %s > 截止年 %s" % (year, crit["year_to"])})
        elif (crit["year_from"] or crit["year_to"]) and year is None:
            d.update({"decision": "maybe", "reason_code": "REV_YEAR_MISSING",
                      "reason": "年份缺失，未默认在窗内", "needs_human": True})
        elif any(t and t in text for t in crit["exclude_terms"]):
            hit = next(t for t in crit["exclude_terms"] if t and t in text)
            d.update({"decision": "exclude", "reason_code": "EX_EXCLUDE_TERM",
                      "reason": "命中排除词 `%s`" % hit})
        elif crit["types"] and s.get("type") and s["type"].lower() not in crit["types"]:
            d.update({"decision": "exclude", "reason_code": "EX_TYPE_MISMATCH",
                      "reason": "类型 %s 不在 %s" % (s["type"], crit["types"])})
        elif crit["languages"] and s.get("language") and \
                s["language"].lower() not in crit["languages"]:
            d.update({"decision": "exclude", "reason_code": "EX_LANGUAGE_MISMATCH",
                      "reason": "语种 %s 不在 %s" % (s["language"], crit["languages"])})
        elif len(overlap) >= 2:
            d.update({"decision": "include", "reason_code": "IN_TOPIC_MATCH",
                      "reason": "覆盖概念词 %s" % ", ".join(overlap[:4])})
        elif len(overlap) == 1:
            d.update({"decision": "maybe", "reason_code": "REV_WEAK_TOPIC_MATCH",
                      "reason": "仅覆盖概念词 %s" % overlap[0], "needs_human": True})
        else:
            d.update({"decision": "maybe", "reason_code": "REV_NO_TOPIC_MATCH",
                      "reason": "未命中问题概念词，不直接排除", "needs_human": True})
        decisions.append(d)
    return decisions


# ---------------------------------------------------------------- 证据矩阵

def extract_matrix(sources, decisions, concepts):
    included = {d["source_id"]: d for d in decisions if d["decision"] in ("include", "maybe")}
    rows = []
    for s in sources:
        if s["source_id"] not in included:
            continue
        text = (s.get("abstract") or s.get("text") or "")[:4000]
        row = {"source_id": s["source_id"], "title": s.get("title"),
               "year": s.get("year"), "venue": s.get("venue"), "doi": s.get("doi"),
               "file": s["file"], "locator": s["locator"], "not_reported": []}
        for field, cues in FIELD_CUES.items():
            sent = cue_sentence(text, cues)
            if sent:
                row[field] = sent[:300]
                row[field + "_quote"] = sent[:240]
            else:
                row[field] = "not_reported"
                row["not_reported"].append(field)
        task_hit = len(concepts & content_terms(row.get("task") or ""))
        reported = [f for f in ("task", "data", "evaluation") if row[f] != "not_reported"]
        if row["task"] == "not_reported":
            row["comparability"] = "not_directly_comparable"
            row["comparability_reason"] = "缺少任务描述，无法判断是否同一问题"
        elif task_hit >= 2 and len(reported) >= 2:
            row["comparability"] = "comparable"
            row["comparability_reason"] = "任务与问题概念对齐，且有数据/评价信息"
        elif len(reported) >= 1:
            row["comparability"] = "partially_comparable"
            row["comparability_reason"] = "任务相近，但数据或评价字段不全"
        else:
            row["comparability"] = "not_directly_comparable"
            row["comparability_reason"] = "仅有任务句，缺数据与评价细节"
        row["extraction"] = "abstract_cue" if s.get("abstract") else \
            ("fulltext_cue" if s.get("text") else "none")
        rows.append(row)
    return rows


# ---------------------------------------------------------------- 创新判定

def classify_type(claim):
    low = claim.lower()
    if any(k in low for k in ["数据", "dataset", "corpus", "样本", "标注", "benchmark"]):
        return "data"
    if any(k in low for k in ["场景", "迁移", "transfer", "domain", "应用", "跨域"]):
        return "scenario_transfer"
    if any(k in low for k in ["结论", "修正", "correct", "contradict", "重新", "反驳"]):
        return "conclusion_revision"
    if any(k in low for k in ["方法", "框架", "模型", "策略", "机制", "协议", "算法",
                              "algorithm", "method", "approach", "pipeline", "protocol",
                              "融合"]):
        return "method"
    return "unclassified"


def collect_claims(case):
    claims = []
    v = case["claims"]
    if isinstance(v, list):
        for i, c in enumerate(v, 1):
            if isinstance(c, dict):
                text = as_text(pick(c, ["claim", "text", "statement", "description"]))
                typ = as_text(pick(c, ["type", "category"]))
            else:
                text, typ = as_text(c), None
            if text:
                claims.append({"claim_id": "cl%02d" % i, "claim": text,
                               "type_hint": typ, "origin": "case_field"})
    elif isinstance(v, str) and v.strip():
        # 字符串型创新陈述不能整段丢弃，也不能当成一条把多个主张糊在一起：
        # 先按分号/换行切，再按句切，逐条判定。
        parts = [x.strip() for x in re.split(r"[;；\n]+", v) if x.strip()]
        expanded = []
        for part in parts:
            expanded.extend(sentences(part) or [part])
        parts = expanded or [v.strip()]
        for i, text in enumerate(parts, 1):
            claims.append({"claim_id": "cl%02d" % i, "claim": text[:300],
                           "type_hint": None, "origin": "case_field"})
    else:
        for s in sentences(case["proposal"]):
            if re.search(r"创新|首次|尚未|novel|first|contribution|不同于|区别于", s, re.I):
                claims.append({"claim_id": "cl%02d" % (len(claims) + 1), "claim": s[:300],
                               "type_hint": None, "origin": "extracted"})
    for i, c in enumerate(claims, 1):
        c["claim_id"] = "cl%02d" % i
        c["type"] = (c["type_hint"] if c.get("type_hint") in
                     ("method", "data", "scenario_transfer", "conclusion_revision")
                     else classify_type(c["claim"]))
    return claims


def novelty_assess(case, claims, sources, decisions, matrix):
    included_ids = {d["source_id"] for d in decisions if d["decision"] in ("include", "maybe")}
    pool = [s for s in sources if s["source_id"] in included_ids]
    by_src = {m["source_id"]: m for m in matrix}
    rows = []
    for c in claims:
        ct = content_terms(c["claim"])
        nearest = []
        for s in pool:
            text = (s.get("title") or "") + " " + (s.get("abstract") or "")[:2000]
            shared = ct & content_terms(text)
            if len(shared) >= 2:
                q, _ = find_sentence(s.get("abstract") or text, shared)
                nearest.append({"source_id": s["source_id"], "title": s.get("title"),
                                "file": s["file"], "locator": s["locator"],
                                "quote": (q or s.get("title") or "")[:240],
                                "shared_terms": sorted(shared)[:8],
                                "score": len(shared)})
        nearest.sort(key=lambda x: -x["score"])
        nearest = nearest[:2]
        covered_terms = set()
        for n in nearest:
            covered_terms.update(ct & set(n["shared_terms"]))
        ratio = round(len(covered_terms) / max(1, len(ct)), 3)
        n_included = len(pool)
        if c["type"] == "scenario_transfer":
            dm = re.search(r"(?:在|于|面向|for)\s*([\u4e00-\u9fffA-Za-z\-]{2,24}?)(?:中|上|里|场景|任务|领域)",
                           c["claim"], re.I)
            pool_text = " ".join(((s.get("title") or "") + " " + (s.get("abstract") or ""))
                                 for s in pool).lower()
            if dm:
                domain = dm.group(1)
                probes = {domain, domain[:2], domain[:3]}
                if not any(p and p in pool_text for p in probes):
                    rows.append({
                        "claim_id": c["claim_id"], "claim": c["claim"], "type": c["type"],
                        "origin": c["origin"], "nearest": [], "coverage_ratio": 0.0,
                        "verdict": "unknown",
                        "verdict_reason": ("场景领域 `%s` 未在本次来源中出现，检索覆盖不足，"
                                           "不能判定是否已被覆盖" % domain),
                        "scope": "仅限本次纳入的 %d 篇来源；未做全局检索，不构成'首次'结论" % n_included,
                        "global_claim": False, "needs_human": True, "evidence": [],
                        "matrix_refs": [],
                    })
                    continue
        if n_included < 3:
            verdict, why = "unknown", "纳入来源少于 3 篇，不能下覆盖/未覆盖结论"
        elif not nearest:
            verdict, why = "unknown", "未找到可对齐的最近工作，需扩展检索"
        elif ratio >= 0.6:
            verdict, why = "covered", "最近工作已覆盖该陈述的主要概念（重合度 %.2f）" % ratio
        elif ratio >= 0.35:
            verdict, why = "partially_covered", "最近工作覆盖部分概念（重合度 %.2f），边界需逐项澄清" % ratio
        else:
            verdict, why = "uncovered_within_scope", "本次来源内未发现覆盖（重合度 %.2f），需扩大检索再确认" % ratio
        rows.append({
            "claim_id": c["claim_id"], "claim": c["claim"], "type": c["type"],
            "origin": c["origin"], "nearest": nearest, "coverage_ratio": ratio,
            "verdict": verdict, "verdict_reason": why,
            "scope": "仅限本次纳入的 %d 篇来源；未做全局检索，不构成'首次'结论" % n_included,
            "global_claim": False,
            "needs_human": verdict in ("unknown", "uncovered_within_scope"),
            "evidence": [{"source_id": n["source_id"], "file": n["file"],
                          "locator": n["locator"], "quote": n["quote"]} for n in nearest],
            "matrix_refs": [m for m in by_src if m in {n["source_id"] for n in nearest}],
        })
    return rows


# ---------------------------------------------------------------- 可行性

CATEGORY_CUES = {
    "data": ["数据", "样本", "dataset", "corpus", "标注", "语料"],
    "compute": ["算力", "gpu", "显存", "compute", "集群", "训练资源"],
    "experiment": ["实验", "设备", "平台", "experiment", "实验条件", "benchmark"],
    "time": ["时间", "周期", "月", "deadline", "时间窗", "进度"],
    "personnel": ["人员", "团队", "人力", "标注员", "作者", "student"],
    "ethics": ["伦理", "合规", "隐私", "irb", "授权", "许可"],
}


def classify_premise(p):
    low = p.lower()
    for cat, cues in CATEGORY_CUES.items():
        if any(c in low for c in cues):
            return cat
    return "other"


def feasibility_assess(case, sources, decisions):
    premises = []
    v = case["prereq"]
    if isinstance(v, str) and v.strip():
        # 字符串型前提同样不能整段丢弃：按分号/换行切成多条。
        v = [x.strip() for x in re.split(r"[;；\n]+", v) if x.strip()]
    if isinstance(v, list):
        for i, x in enumerate(v, 1):
            if isinstance(x, dict):
                text = as_text(pick(x, ["premise", "text", "constraint", "name", "description"]))
                hint = as_text(pick(x, ["status"]))
                src = as_text(pick(x, ["source"]))
            else:
                text, hint, src = as_text(x), None, None
            if text:
                premises.append({"premise": text, "status_hint": hint, "source_hint": src,
                                 "origin": "case_field"})
    else:
        for s in sentences(case["proposal"]):
            if any(c in s.lower() for cat in CATEGORY_CUES.values() for c in cat):
                premises.append({"premise": s[:240], "status_hint": None,
                                 "source_hint": None, "origin": "extracted"})
    for a in case["assumptions"]:
        premises.append({"premise": a, "status_hint": "assumed", "source_hint": "case:assumptions",
                         "origin": "assumption"})
    seen, rows = set(), []
    for i, p in enumerate(premises, 1):
        key = normkey(p["premise"])[:80]
        if key in seen:
            continue
        seen.add(key)
        ptoks = content_terms(p["premise"])
        pdigits = set(re.findall(r"\d+", p["premise"]))
        best, best_quote, best_file, best_loc = None, None, None, None
        for s in sources:
            text = (s.get("abstract") or "") + " " + (s.get("text") or "")[:3000]
            shared = ptoks & content_terms(text)
            if len(shared) >= 2 and any(
                    any(c in text.lower() for c in cues) for cues in CATEGORY_CUES.values()):
                q, _ = find_sentence(text, shared)
                if pdigits and q and not (pdigits & set(re.findall(r"\d+", q))):
                    continue
                if q and len(shared) > (best[0] if best else 0):
                    best = (len(shared), s["source_id"])
                    best_quote, best_file, best_loc = q[:240], s["file"], s["locator"]
        hint = (p.get("status_hint") or "").lower()
        downgraded = False
        if hint == "supported" and not (best and best_quote):
            # 案例声明 supported 但没有可引用片段：不能输出"有来源支持"的空证据。
            status, downgraded = "unknown", True
        elif hint in ("supported", "assumed", "unsupported", "unknown"):
            status = hint
        elif p["origin"] == "assumption":
            status = "assumed"
        elif best:
            status = "supported"
        else:
            status = "unknown"
        rows.append({
            "premise_id": "pr%02d" % i, "premise": p["premise"],
            "category": classify_premise(p["premise"]), "status": status,
            "source": ({"file": best_file, "locator": best_loc, "quote": best_quote}
                       if status == "supported" else
                       ({"assumption": True} if status == "assumed" else None)),
            "source_hint": p.get("source_hint"), "origin": p["origin"],
            "status_note": ("案例声明 supported 但未找到可引用来源片段，已降级 unknown"
                            if downgraded else None),
            "impact": ("该前提不成立将直接改写研究设计或结论" if status in ("unknown", "unsupported")
                       else "前提成立时可继续按当前设计推进"),
            "mitigation": ("补充数据/资源核查并记录来源；无法确认时缩小研究范围"
                           if status in ("unknown", "unsupported") else "保存来源以备复核"),
            "needs_check": status in ("unknown", "unsupported"),
        })
    if not rows:
        conclusion, why = "unknown", "案例未提供任何数据/算力/时间/人员前提"
    elif all(r["status"] == "supported" for r in rows):
        conclusion, why = "feasible_within_scope", "全部前提有来源支持（范围内）"
    elif any(r["status"] == "unsupported" for r in rows):
        conclusion, why = "not_supported", "存在与前提相反的证据"
    else:
        conclusion, why = "conditionally_feasible", "存在未知或假设前提，需先核实"
    risks = [{"premise_id": r["premise_id"], "risk": "前提未确认：%s" % r["premise"][:80],
              "mitigation": r["mitigation"]} for r in rows if r["status"] in ("unknown", "unsupported")]
    return {"conclusion": conclusion, "reason": why,
            "conditions": [r["premise"] for r in rows if r["status"] != "supported"],
            "premises": rows, "risks": risks}


# ---------------------------------------------------------------- 冲突与空白

def detect_conflicts(sources, decisions, matrix):
    included = {d["source_id"] for d in decisions if d["decision"] in ("include", "maybe")}
    by_id = {s["source_id"]: s for s in sources}
    rows = [m for m in matrix if m["source_id"] in included]
    conflicts = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            ta = content_terms(by_id[a["source_id"]].get("abstract") or "")
            tb = content_terms(by_id[b["source_id"]].get("abstract") or "")
            if len(ta & tb) < 2:
                continue
            ca = (a.get("conclusion") or "").lower()
            cb = (b.get("conclusion") or "").lower()
            if ca == "not_reported" or cb == "not_reported":
                continue
            a_pos = any(c in ca for c in POS_CUES)
            a_neg = any(c in ca for c in NEG_CUES)
            b_pos = any(c in cb for c in POS_CUES)
            b_neg = any(c in cb for c in NEG_CUES)
            if (a_pos and b_neg) or (a_neg and b_pos):
                same_data = a.get("data") == b.get("data") and a.get("data") != "not_reported"
                same_method = a.get("method") == b.get("method") and a.get("method") != "not_reported"
                if not (same_data or same_method):
                    adjudication, unresolved = "scope_difference", False
                    note = "数据/方法不同，结论差异可用范围差异解释"
                else:
                    adjudication, unresolved = "unresolved", True
                    note = "数据与方法相近但结论相反，需人工复核原文"
                conflicts.append({
                    "type": "conclusion_conflict", "sources": [a["source_id"], b["source_id"]],
                    "quotes": [{"source_id": a["source_id"], "quote": a.get("conclusion_quote") or ca[:200]},
                               {"source_id": b["source_id"], "quote": b.get("conclusion_quote") or cb[:200]}],
                    "adjudication": adjudication, "unresolved": unresolved, "note": note})
    return conflicts


def research_gaps(novelty_rows, matrix, feas):
    gaps = []
    for n in novelty_rows:
        if n["verdict"] in ("uncovered_within_scope", "unknown"):
            gaps.append({"type": "novelty_gap", "claim_id": n["claim_id"],
                         "basis": n["verdict_reason"], "bounded": True,
                         "next_step": "限定任务/数据边界后补检索或设计对照实验"})
    if matrix and all(m.get("data") in (None, "not_reported") for m in matrix):
        gaps.append({"type": "evidence_gap", "dimension": "data",
                     "basis": "纳入来源均未报告数据字段", "bounded": True,
                     "next_step": "补充数据描述或直接复现实验"})
    for r in feas.get("premises") or []:
        if r["status"] in ("unknown", "unsupported"):
            gaps.append({"type": "feasibility_gap", "premise_id": r["premise_id"],
                         "basis": r["premise"][:120], "bounded": True,
                         "next_step": "核实资源或缩小范围"})
    return gaps


# ---------------------------------------------------------------- 自检

def validate(result):
    checks = []

    def add(check, ok, detail=""):
        checks.append({"check": check, "pass": bool(ok), "detail": detail})

    src_ids = {s["source_id"] for s in result["sources"]}
    dec = result["screening"]
    add("every_source_screened",
        all(s["source_id"] in {d["source_id"] for d in dec} for s in result["sources"]),
        "%d 来源 / %d 决定" % (len(result["sources"]), len(dec)))
    add("every_decision_has_reason_code",
        all(d.get("reason_code") in REASON_CODES for d in dec),
        "理由码均在字典内")
    add("every_matrix_row_has_locator",
        all(m.get("file") and m.get("locator") for m in result["evidence_matrix"]),
        "%d 行矩阵" % len(result["evidence_matrix"]))
    add("novelty_has_scope",
        all(n.get("scope") and not n.get("global_claim") for n in result["novelty"]) and
        all(n["verdict"] != "uncovered" for n in result["novelty"]),
        "%d 条创新判定均有 scope" % len(result["novelty"]))
    add("feasibility_premises_stated",
        all(r.get("status") in ("supported", "assumed", "unsupported", "unknown")
            for r in result["feasibility"].get("premises") or []) and
        result["feasibility"].get("conclusion") in
        ("feasible_within_scope", "conditionally_feasible", "not_supported", "unknown"),
        "结论=%s" % result["feasibility"].get("conclusion"))
    add("supported_premises_cite_source",
        all((r.get("source") or {}).get("file") and (r.get("source") or {}).get("quote")
            for r in result["feasibility"].get("premises") or []
            if r.get("status") == "supported"),
        "supported 前提必须带文件与逐字片段")
    add("conflicts_registered",
        isinstance(result["conflicts"], list), "%d 条冲突" % len(result["conflicts"]))
    add("sources_traceable",
        all(s.get("sha256") and s.get("file") and s.get("locator") for s in result["sources"]),
        "%d 个来源" % len(result["sources"]))
    add("contract_fields_present",
        all(f in result for f in result["_contract_fields"]),
        "%d 个契约字段" % len(result["_contract_fields"]))
    return checks


def finalize_contract(result, fields):
    for f in fields:
        key = CANON.get(normkey(f))
        if key and key in result:
            result[f] = result.get(key)
        if f not in result:
            result[f] = {"note": "输入契约未定义该字段的取值口径；保留字段名与空值说明，不补造内容。"}
    return result


def markdown_report(result):
    lines = ["# 选题与创新性评估报告 - %s（%s）" % (result["case_id"], VERSION), ""]
    lines.append("状态：`%s`；%s" % (result["status"], result["summary"]))
    ps = result["problem_statement"]
    lines += ["", "## 1. 问题拆解", "", "| 要素 | 值 | 来源 |", "|-|-|-|"]
    for k, label in (("object", "研究对象"), ("variables", "关键变量"),
                     ("baseline", "比较基线"), ("expected_conclusion", "预期结论"),
                     ("falsifier", "可证伪条件")):
        v = ps.get(k) or {}
        lines.append("| %s | %s | %s |" % (label, v.get("value") or "undefined",
                                           v.get("source")))
    lines.append("")
    lines.append("- 可证伪：%s；缺失项：%s" % (ps.get("falsifiable"),
                                              ", ".join(ps.get("missing") or []) or "无"))
    lines += ["", "## 2. 来源与纳排", "",
              "| 来源 | 年份 | 决定 | 理由码 | 证据 |", "|-|-|-|-|-|"]
    for d in result["screening"]:
        lines.append("| %s | %s | %s | `%s` | %s |" % (
            (d["title"] or "")[:60], d.get("year"), d["decision"], d["reason_code"],
            (d["evidence"].get("quote") or "")[:60]))
    lines += ["", "## 3. 证据矩阵", "",
              "| 来源 | 任务 | 方法 | 数据 | 评价 | 可比较性 |", "|-|-|-|-|-|-|"]
    for m in result["evidence_matrix"]:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            (m["title"] or "")[:40], (m.get("task") or "")[:40],
            (m.get("method") or "")[:40], (m.get("data") or "")[:30],
            (m.get("evaluation") or "")[:30], m["comparability"]))
    lines += ["", "## 4. 创新逐条判定", ""]
    if not result["novelty"]:
        lines.append("- 未提供可判定的创新陈述（novelty=[]）。")
    for n in result["novelty"]:
        lines.append("- `%s` [%s] %s → **%s**（%s）" % (
            n["claim_id"], n["type"], n["claim"][:80], n["verdict"], n["verdict_reason"]))
        for e in n["evidence"][:2]:
            lines.append("  - 证据 %s：%s" % (e["file"], e["quote"][:80]))
        lines.append("  - 范围：%s" % n["scope"])
    lines += ["", "## 5. 可行性", "",
              "- 结论：**%s**（%s）" % (result["feasibility"]["conclusion"],
                                       result["feasibility"]["reason"])]
    lines += ["", "| 前提 | 类别 | 状态 | 来源 |", "|-|-|-|-|"]
    for r in result["feasibility"].get("premises") or []:
        src = r.get("source") or {}
        lines.append("| %s | %s | %s | %s |" % (
            r["premise"][:60], r["category"], r["status"],
            (src.get("file") or ("case:assumption" if src.get("assumption") else "无"))))
    if result["feasibility"].get("risks"):
        lines += ["", "### 失败风险", ""]
        for r in result["feasibility"]["risks"]:
            lines.append("- %s → %s" % (r["risk"], r["mitigation"]))
    lines += ["", "## 6. 冲突与空白", ""]
    if not result["conflicts"]:
        lines.append("- 未登记结论冲突。")
    for c in result["conflicts"]:
        lines.append("- `%s` %s：%s（%s）" % (
            c["type"], ", ".join(c["sources"]), c["note"], c["adjudication"]))
    for g in result["gaps"]:
        lines.append("- 空白 `%s`：%s（bounded=%s）" % (g["type"], g["basis"], g["bounded"]))
    lines += ["", "## 7. 不确定性与边界", ""]
    for u in result["uncertainty"] or ["无"]:
        lines.append("- %s" % u)
    for l in result["limits"]:
        lines.append("- 限制：%s" % l)
    lines += ["", "## 8. 自查", "", "| 检查 | 结果 | 说明 |", "|-|-|-|"]
    for c in result["validation"]["checks"]:
        lines.append("| %s | %s | %s |" % (c["check"], "pass" if c["pass"] else "FAIL",
                                           c["detail"]))
    lines += ["", "## 复跑", "", "```bash",
              "python scripts/run_case.py --case /input/case.json --materials /input \\",
              "  --work /app/work --out /app/output", "```", ""]
    return "\n".join(lines)
