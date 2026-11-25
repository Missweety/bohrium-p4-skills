#!/usr/bin/env python3
"""paper_parse.py - pull title/authors/abstract/figures/tables/conclusion out of a paper.

Sources: PDF (text layer via pdftotext or pypdf), DOCX (OOXML), Markdown/plain text/LaTeX.
Every field is either extracted or marked `missing` with a reason; nothing is invented.
Page numbers come from PDF form-feed boundaries; other formats report a line locator and
`page: null` so the caller never pretends to know a page it cannot see.

Usage:
  python3 scripts/paper_parse.py --paper /input/materials/paper.pdf --out work
  python3 scripts/paper_parse.py --materials /input/materials --out work --name paper.json
Exit 0 = some text was read (partial extraction allowed); 1 = source unreadable.
"""
import argparse
import json
import os
import re
import sys

try:
    import kernel  # reuse alias-tolerant text extraction, stdlib only
except Exception:  # noqa: BLE001
    kernel = None

PAPER_EXT = (".pdf", ".docx", ".md", ".markdown", ".txt")
SECTION_NAMES = {
    "abstract", "摘要", "introduction", "引言", "background", "背景",
    "related work", "related works", "相关工作", "methods", "method",
    "materials and methods", "methodology", "方法", "实验", "results",
    "result", "结果", "discussion", "讨论", "conclusion", "conclusions",
    "结论", "总结", "limitations", "limitation", "局限", "references",
    "参考文献", "acknowledgements", "致谢", "supplementary",
}
MD_HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.{1,90})$")
NUM_HEAD = re.compile(r"^\s*(\d{1,2})\.?\s+([A-Z][A-Za-z][A-Za-z \-]{2,60})\s*$")
CN_HEAD = re.compile(r"^\s*(摘要|引言|方法|结果|讨论|结论|总结|局限|参考文献|致谢)\s*[:：]?\s*$")
CN_NUM_HEAD = re.compile(r"^\s*\d{1,2}[.、\s]\s*(摘要|引言|方法|结果|讨论|结论|总结|局限|参考文献|致谢)\s*$")
FIG_RE = re.compile(r"(?:Fig(?:ure)?\.?\s*S?\d+[a-z]?|图\s*\d+[a-z]?)")
TAB_RE = re.compile(r"(?:Table\s*S?\d+[a-z]?|表\s*\d+[a-z]?)")
AUTHOR_HINT = re.compile(r"(作者|authors?\s*[:：])", re.I)
NAME_LINE = re.compile(r"^[A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+){1,3}"
                       r"(?:\s*[\d*†‡,，、;；].*)?$")


def _dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def _norm_ref(ref):
    return re.sub(r"\s+", "", str(ref or "")).lower().replace("figure", "fig").replace("图", "fig")


def _locate(text, idx):
    page = text.count("\f", 0, idx) + 1 if "\f" in text else None
    line = text.count("\n", 0, idx) + 1
    return {"page": page, "line": line}


def _clean(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00ad", "")


def _key(name):
    return re.sub(r"^\s*\d{1,2}[.、\s]*", "", str(name or "")).strip(" :：#").lower()


def _sections(text):
    """Return [{name, key, start, body_start, end}] for md/LaTeX/numbered/Chinese heads."""
    heads = []
    offset = 0
    for raw in text.split("\n"):
        line = raw.strip()
        name = None
        m = MD_HEAD.match(raw)
        if m and m.group(1) in ("#", "##"):
            name = m.group(2).strip()
        elif NUM_HEAD.match(raw):
            name = NUM_HEAD.match(raw).group(2).strip()
        elif CN_NUM_HEAD.match(raw):
            name = CN_NUM_HEAD.match(raw).group(1)
        elif CN_HEAD.match(raw):
            name = CN_HEAD.match(raw).group(1)
        elif line.lower() in SECTION_NAMES and len(line) <= 40:
            name = line
        if name and _key(name) in SECTION_NAMES:
            heads.append({"name": name.strip(" :："), "key": _key(name),
                          "start": offset, "body_start": offset + len(raw) + 1})
        offset += len(raw) + 1
    for i, head in enumerate(heads):
        head["end"] = heads[i + 1]["start"] if i + 1 < len(heads) else len(text)
    return heads


def _section_body(text, heads, names):
    for head in heads:
        if head["key"] in names:
            body = text[head["body_start"]:head["end"]].strip()
            body = re.sub(r"\n{2,}", "\n", body)
            return body[:1600], head
    return "", None


def _field(value, locator=None, note=""):
    if value in (None, "", [], {}):
        return {"status": "missing", "value": None, "reason": note or "原文未识别到该字段"}
    return {"status": "ok", "value": value, "locator": locator or ""}


def _caption_after(text, end):
    """Caption only when the ref starts a line followed by prose; inline citations get ''."""
    rest = text[end:end + 240]
    if rest[:1] in "）)，,、；;:：]】":
        return ""
    line = rest.split("\n")[0].strip().lstrip("）)，,、；;:：]】")
    if len(line) < 10:
        nxt = [x.strip() for x in rest.split("\n")[1:3] if x.strip()]
        line = (nxt[0] if nxt else "").lstrip("）)，,、；;:：]】")
    if len(line) < 6 or FIG_RE.match(line) or TAB_RE.match(line):
        return ""
    return re.split(r"。|\.\s", line, maxsplit=1)[0].strip()[:120]


def parse(text, source):
    text = _clean(text)
    heads = _sections(text)
    offsets, acc = [], 0
    for raw in text.split("\n"):
        offsets.append(acc)
        acc += len(raw) + 1

    # ---- title: first markdown H1 or first plausible non-heading line
    title, title_loc = None, None
    for i, line in enumerate(text.split("\n")):
        stripped = line.strip()
        if not stripped:
            continue
        m = MD_HEAD.match(line)
        if m and m.group(1) == "#" and m.group(2).strip().lower() not in SECTION_NAMES:
            title = m.group(2).strip()
            title_loc = _locate(text, offsets[i])
            break
        if 6 <= len(stripped) <= 200 and not stripped.startswith("#"):
            low = stripped.lower().strip(":：")
            if low in SECTION_NAMES or NUM_HEAD.match(line) or CN_HEAD.match(line) \
                    or CN_NUM_HEAD.match(line):
                continue
            title = stripped
            title_loc = _locate(text, offsets[i])
            break
    title_field = _field(title, title_loc, "未找到可作为标题的行")

    # ---- authors: explicit hint, or the line right after the title, or a name-like line
    authors, author_loc = None, None
    if title:
        start = text.find(title) + len(title)
        offset = start
        for raw_line in text[start:start + 400].splitlines(keepends=True):
            stripped = raw_line.strip()
            if not stripped:
                offset += len(raw_line)
                continue
            if AUTHOR_HINT.search(stripped):
                authors = AUTHOR_HINT.sub("", stripped, count=1).strip(" :：")
            elif ("," in stripped or "，" in stripped or "、" in stripped) and len(stripped) <= 240 \
                    and not stripped.endswith(("。", ".", "；", ";")):
                authors = stripped
            elif NAME_LINE.match(stripped) and len(stripped) <= 120:
                authors = stripped
            if authors:
                author_loc = _locate(text, offset + raw_line.find(stripped))
                break
            offset += len(raw_line)
    authors_field = _field(authors, author_loc, "作者行未识别（可能为扫描版或无作者信息）")

    # ---- abstract
    abstract, head = _section_body(text, heads, {"abstract", "摘要"})
    if not abstract:
        m = re.search(r"(?:Abstract|摘要)\s*[:：]\s*(.{40,1600}?)(?:\n\n|\Z)", text, re.S)
        if m:
            abstract = re.sub(r"\s+", " ", m.group(1)).strip()
            head = {"start": m.start()}
    abstract_field = _field(abstract[:1600], _locate(text, head["start"]) if head else None,
                            "未识别到摘要段（Abstract/摘要）")

    # ---- figures and tables with caption and locator
    figures, tables = {}, {}
    for regex, bucket in ((FIG_RE, figures), (TAB_RE, tables)):
        for m in regex.finditer(text):
            ref = re.sub(r"\s+", " ", m.group(0)).strip()
            key = _norm_ref(ref)
            caption = _caption_after(text, m.end())
            loc = _locate(text, m.start())
            prev = bucket.get(key)
            if prev is None or len(caption) > len(prev["caption"]):
                bucket[key] = {"ref": ref, "caption": caption, "locator": loc}

    # ---- conclusion / limitations
    conclusion, head = _section_body(text, heads, {"conclusion", "conclusions", "结论", "总结"})
    if not conclusion:
        m = re.search(r"(?:In conclusion|综上|总之)[，,、\s]*(.{40,1200})", text, re.S)
        if m:
            conclusion = m.group(1).strip()
            head = {"start": m.start()}
    conclusion_field = _field(conclusion[:1200],
                              _locate(text, head["start"]) if head else None,
                              "未识别到结论段（Conclusion/结论）")

    limitations, head = _section_body(text, heads, {"limitations", "limitation", "局限"})
    if not limitations:
        for m in re.finditer(r"(局限性|不足|未来工作|future work|a limitation)", text, re.I):
            limitations = text[m.start():m.start() + 400].strip()
            head = {"start": m.start()}
            break
    limitations_field = _field(limitations[:800],
                               _locate(text, head["start"]) if head else None,
                               "作者未单列局限；需在 uncertainty 说明外推边界")

    sections = [{"name": h["name"], "locator": _locate(text, h["start"])}
                for h in heads]
    pages = text.count("\f") + 1 if "\f" in text else None
    missing = [name for name, field in (
        ("title", title_field), ("authors", authors_field), ("abstract", abstract_field),
        ("figures", {"status": "ok" if figures else "missing"}),
        ("tables", {"status": "ok" if tables else "missing"}),
        ("conclusion", conclusion_field), ("limitations", limitations_field),
    ) if field.get("status") == "missing"]

    return {
        "source": source,
        "format": os.path.splitext(source)[1].lower().lstrip("."),
        "page_count": pages,
        "chars": len(text),
        "title": title_field,
        "authors": authors_field,
        "abstract": abstract_field,
        "sections": sections,
        "figures": list(figures.values()),
        "tables": list(tables.values()),
        "conclusion": conclusion_field,
        "limitations": limitations_field,
        "missing": missing,
    }


def pick_paper(materials):
    best = []
    for root in materials:
        if os.path.isfile(root):
            best.append(root)
            continue
        for dirpath, _, names in os.walk(root):
            for name in names:
                if name.startswith("."):
                    continue
                if os.path.splitext(name)[1].lower() in PAPER_EXT:
                    best.append(os.path.join(dirpath, name))
    best.sort(key=lambda p: (PAPER_EXT.index(os.path.splitext(p)[1].lower()),
                             -os.path.getsize(p)))
    return best[0] if best else None


def read_source(path):
    if kernel is not None:
        return kernel.extract(path)
    ext = os.path.splitext(path)[1].lower()
    if ext in {".md", ".markdown", ".txt"}:
        return open(path, encoding="utf-8", errors="replace").read()
    return "[unreadable: kernel.py not importable]"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--paper", default="")
    ap.add_argument("--materials", nargs="*", default=[])
    ap.add_argument("--out", default="work")
    ap.add_argument("--name", default="paper.json")
    a = ap.parse_args()

    source = a.paper or pick_paper(a.materials)
    if not source or not os.path.exists(source):
        print("blocked: no paper source found (looked for %s)" % ", ".join(PAPER_EXT))
        _dump({"status": "blocked", "reason": "no paper source",
               "missing": ["title", "authors", "abstract", "figures", "tables", "conclusion"]},
              os.path.join(a.out, a.name))
        return 1
    text = read_source(source)
    if not text.strip() or text.startswith("[") and "unavailable" in text:
        print("blocked: paper text layer unavailable:", source)
        _dump({"status": "blocked", "source": source, "reason": text[:400],
               "missing": ["title", "authors", "abstract", "figures", "tables", "conclusion"]},
              os.path.join(a.out, a.name))
        return 1

    report = parse(text, source)
    report["status"] = "partial" if report["missing"] else "ok"
    _dump(report, os.path.join(a.out, a.name))
    print("paper: title=%s authors=%s abstract=%s figures=%d tables=%d conclusion=%s pages=%s"
          % (report["title"]["status"], report["authors"]["status"], report["abstract"]["status"],
             len(report["figures"]), len(report["tables"]), report["conclusion"]["status"],
             report["page_count"] or "-"))
    if report["missing"]:
        print("  missing:", ", ".join(report["missing"]), "- 页面不得补造这些内容")
    return 0


if __name__ == "__main__":
    sys.exit(main())
