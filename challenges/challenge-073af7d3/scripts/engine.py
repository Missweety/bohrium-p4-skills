#!/usr/bin/env python3
"""engine.py - evidence-grounded literature synthesis and trend analysis.

Subcommands (each reads/writes JSON under --work):
  index     scan case materials -> records.json (records + extraction failures)
  screen    apply inclusion/exclusion criteria -> screening.json
  matrix    extract comparable fields + verbatim quotes -> matrix.json
  themes    emergent theme clustering + contradictions + gaps -> themes.json
  trends    year distribution, stage split, representative works -> trends.json
  synthesize  build review or trend report + result.json
  verify    machine checks -> checks.json

Design constraints:
  * every substantive claim is extractive or a counted statistic, with source_ids;
  * quotes are verbatim substrings of the source text and carry page/paragraph anchors;
  * missing metadata/year/full text is reported, never guessed;
  * nothing from outside the provided corpus is cited.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import zipfile
from collections import Counter, defaultdict
from datetime import datetime

STOP_EN = set("""a an the and or of for to in on with without by from as at is are was were be been
this that these those we our it its their they them using used use based study studies result results
method methods approach approaches paper article review we our than then into between among more less
can could may might also however therefore thus significant significantly showed shown show found
find findings data group groups compared comparison high low higher lower new novel different
""".split())
STOP_CN = set("的 了 与 和 及 或 在 对 中 是 为 了 我们 本文 研究 结果 方法 通过 以及 一个 这些 那些 进行 "
              "表明 显示 具有 可以 能够 不同 显著 分析 基于 使用 采用 影响 作用 相关 关系 问题 文献 综述".split())
RESULT_CUES = ("we found", "our results", "results show", "results indicate", "significant", "observed",
               "increased", "decreased", "improved", "reduced", "correlat", "表明", "显示", "显著",
               "提高", "降低", "增加", "减少", "优于", "相关")
LIMIT_CUES = ("limitation", "limited by", "future work", "further research", "remains unclear",
              "not clear", "small sample", "局限", "不足", "有待", "尚不清楚", "未来研究", "样本量")
GAP_CUES = ("remains unclear", "remains unknown", "further research", "future work", "not been studied",
            "little is known", "尚不清楚", "有待", "尚未", "未来研究", "缺乏", "空白")
POS = ("increase", "improve", "effective", "superior", "benefit", "positive", "提高", "改善", "有效", "优于", "正相关")
NEG = ("no effect", "no difference", "not significant", "ineffective", "negative", "decrease", "无效",
       "无差异", "不显著", "负相关", "降低")
YEAR_RE = re.compile(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)")
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
CITE_RE = re.compile(r"\[(S\d{2,4}(?:,\s*S\d{2,4})*)\]")


def load(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        return json.load(fh)


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def text_of(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            try:
                r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, timeout=90)
                if r.returncode == 0:
                    return r.stdout.decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            try:
                from pypdf import PdfReader  # type: ignore
                return "\n\f\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
            except Exception:  # noqa: BLE001
                return ""
        if ext == ".docx":
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            return re.sub(r"<[^>]+>", "", xml)
        return open(path, encoding="utf-8", errors="replace").read()
    except Exception:  # noqa: BLE001
        return ""


def split_pages(text):
    if "\f" in text:
        return text.split("\f")
    return [text]


def paragraphs(text):
    out = []
    for page_no, page in enumerate(split_pages(text), 1):
        local = 0
        for para in re.split(r"\n\s*\n", page):
            p = re.sub(r"\s+", " ", para).strip()
            if p:
                local += 1
                out.append({"page": page_no, "paragraph": local, "text": p})
    return out


def header_fields(text):
    """Parse YAML-ish front matter or key: value lines in the first 40 lines."""
    fields = {}
    head = "\n".join(text.splitlines()[:40])
    for key, names in {"title": ["title"], "authors": ["authors", "author"], "year": ["year", "date"],
                       "venue": ["journal", "venue", "booktitle"], "doi": ["doi"]}.items():
        for n in names:
            m = re.search(r"(?im)^\s*%s\s*:\s*(.+)$" % n, head)
            if m:
                fields[key] = m.group(1).strip().strip('"').strip("'")
                break
    m = DOI_RE.search(head)
    if m and "doi" not in fields:
        fields["doi"] = m.group(0)
    if "year" not in fields:
        m = YEAR_RE.search(head)
        if m:
            fields["year"] = m.group(1)
    return fields


def abstract_of(text):
    m = re.search(r"(?is)(?:^|\n)\s*(?:abstract|摘要)\s*[:：]?\s*(.+?)(?:\n\s*(?:#+\s*)?(?:keywords?|关键词|1\.?\s*introduction|"
                  r"introduction|引言|背景|methods?|方法|results?|结果)\b)", text)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:4000]
    m = re.search(r"(?im)^\s*(?:abstract|摘要)\s*[:：]?\s*$", text)
    if m:
        tail = text[m.end():]
        paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", tail) if p.strip()]
        if paras:
            return paras[0][:4000]
    paras = [p["text"] for p in paragraphs(text)]
    for p in paras[:3]:
        m2 = re.match(r"(?i)^\s*(?:abstract|摘要)\s*[:：]?\s*(.+)$", p)
        if m2 and len(m2.group(1)) > 40:
            return m2.group(1)[:4000]
    for p in paras[1:6]:
        if len(p) > 200:
            return p[:4000]
    return ""


def parse_bib(text):
    entries = []
    for chunk in re.split(r"\n(?=@)", text):
        if not chunk.strip().startswith("@"):
            continue
        rec = {}
        m = re.search(r"@(\w+)\s*\{\s*([^,]+),", chunk)
        if not m:
            continue
        rec["type"] = m.group(1).lower()
        rec["key"] = m.group(2).strip()
        for field in ("title", "author", "year", "journal", "booktitle", "doi", "abstract"):
            fm = re.search(r"(?is)\b%s\s*=\s*[{\"](.+?)[}\"]\s*,?\s*$" % field, chunk, re.M)
            if not fm:
                fm = re.search(r"(?is)\b%s\s*=\s*[{\"](.+?)[}\"]" % field, chunk)
            if fm:
                rec[field] = re.sub(r"\s+", " ", fm.group(1)).strip()
        entries.append(rec)
    return entries


def normalize_title(t):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (t or "").lower())


def tokens(text):
    text = (text or "").lower()
    en = [w for w in re.findall(r"[a-z][a-z\-]{2,}", text) if w not in STOP_EN]
    cn = [w for w in re.findall(r"[\u4e00-\u9fff]{2,}", text) if w not in STOP_CN]
    bigrams = []
    for seg in cn:
        if len(seg) <= 4:
            bigrams.append(seg)
        else:
            bigrams.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return en + [b for b in bigrams if b not in STOP_CN]


def case_roots(case):
    raw = None
    for key in ("materials", "files", "documents", "literature", "corpus", "inputs", "papers", "resources"):
        for k in case:
            if k.lower().replace("-", "_") == key and case[k]:
                raw = case[k]
                break
        if raw:
            break
    out = []
    if isinstance(raw, str):
        out = [raw]
    elif isinstance(raw, list):
        out = [x if isinstance(x, str) else x.get("path") for x in raw if isinstance(x, (str, dict))]
    if not out:
        out = [p for p in ("/input/materials", "/input/papers", "/input/files", "/app/input/materials")
               if os.path.exists(p)]
    return [os.path.abspath(p) for p in out if p and os.path.exists(p)]


def first_value(case, names):
    for n in names:
        for k in case:
            if k.lower().replace("-", "_") == n and case[k] not in (None, "", [], {}):
                return case[k]
    return None


def cmd_index(a):
    case = load(a.case)
    roots = case_roots(case)
    records, failures = [], []
    seen_files = set()
    for root in roots:
        paths = []
        if os.path.isfile(root):
            paths = [root]
        else:
            for dirpath, _, names in os.walk(root):
                for n in sorted(names):
                    if not n.startswith(".") and n.lower() not in {"case.json", "task.md"}:
                        paths.append(os.path.join(dirpath, n))
        for path in paths:
            if path in seen_files:
                continue
            seen_files.add(path)
            ext = os.path.splitext(path)[1].lower()
            if ext in {".csv", ".json", ".jsonl"}:
                try:
                    if ext == ".csv":
                        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
                    elif ext == ".jsonl":
                        rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
                    else:
                        data = load(path)
                        rows = data if isinstance(data, list) else data.get("records") or data.get("items") or [data]
                    for i, row in enumerate(rows):
                        if not any(str(v).strip() for v in row.values() if v is not None):
                            continue  # blank row carries no evidence and must not borrow file text
                        body = " ".join(str(row.get(k) or "") for k in
                                         ("fulltext", "full_text", "body", "content", "text") if row.get(k))
                        rec = {"file": path, "row": i + 1, "origin": "table",
                               "title": str(row.get("title") or row.get("标题") or row.get("题名") or "").strip() or None,
                               "authors": str(row.get("authors") or row.get("author") or row.get("作者") or "").strip() or None,
                               "year": row.get("year") or row.get("年份") or row.get("publication_year")
                                       or row.get("year_published") or row.get("发表年份"),
                               "venue": row.get("journal") or row.get("venue") or row.get("期刊"),
                               "doi": row.get("doi") or row.get("DOI"),
                               "abstract": row.get("abstract") or row.get("摘要") or row.get("summary"),
                               "row_text": " ".join(str(v) for v in row.values() if v),
                               "_fulltext_body": body}
                        records.append(rec)
                except Exception as exc:  # noqa: BLE001
                    failures.append({"file": path, "reason": "table_parse_failed:%s" % str(exc)[:80]})
                continue
            if ext == ".bib":
                try:
                    for e in parse_bib(open(path, encoding="utf-8", errors="replace").read()):
                        records.append({"file": path, "origin": "bib", "title": e.get("title"),
                                        "authors": e.get("author"), "year": e.get("year"),
                                        "venue": e.get("journal") or e.get("booktitle"),
                                        "doi": e.get("doi"), "abstract": e.get("abstract"),
                                        "row_text": " ".join(x for x in (e.get("title"), e.get("abstract")) if x)})
                except Exception as exc:  # noqa: BLE001
                    failures.append({"file": path, "reason": "bib_parse_failed:%s" % str(exc)[:80]})
                continue
            if ext not in {".pdf", ".docx", ".md", ".markdown", ".txt", ".rst", ".html", ".htm", ".tex"}:
                failures.append({"file": path, "reason": "unsupported_type"})
                continue
            try:
                text = text_of(path)
                if not text.strip():
                    failures.append({"file": path, "reason": "no_text_layer_or_empty"})
                    continue
                h = header_fields(text)
                records.append({"file": path, "origin": "file", "title": h.get("title") or next(
                    (ln.strip("# ").strip() for ln in text.splitlines() if 10 <= len(ln.strip()) <= 200), None),
                                "authors": h.get("authors"), "year": h.get("year"),
                                "venue": h.get("venue"), "doi": h.get("doi") or (DOI_RE.search(text).group(0)
                                                                                  if DOI_RE.search(text) else None),
                                "abstract": abstract_of(text), "text": text})
            except Exception as exc:  # noqa: BLE001
                failures.append({"file": path, "reason": "read_failed:%s" % str(exc)[:80]})

    hash_cache = {}
    for i, rec in enumerate(records, 1):
        rec["source_id"] = "S%02d" % i
        key = rec["file"]
        if key not in hash_cache:
            hash_cache[key] = sha256(key) if os.path.isfile(key) else None
        rec["sha256"] = hash_cache[key]
        y = rec.get("year")
        m = YEAR_RE.search(str(y)) if y is not None else None
        rec["year"] = int(m.group(1)) if m else None
        rec["doi"] = (rec.get("doi") or "").strip().lower() or None
        if rec.get("origin") == "table":
            # A table row is metadata unless the row carries an explicit body/fulltext field.
            rec["has_fulltext"] = len(rec.get("_fulltext_body") or "") > 400
        elif rec.get("origin") == "file":
            rec["has_fulltext"] = True  # a readable document file is itself the full text
        else:
            rec["has_fulltext"] = False
        rec.pop("_fulltext_body", None)
        rec["dup_key"] = rec["doi"] or (normalize_title(rec.get("title")) + "|" + str(rec.get("year") or ""))
        rec.pop("text", None)  # keep memory small; text re-read by other steps
    dump({"records": records, "failures": failures, "roots": roots, "counts": {
        "files_scanned": len(seen_files), "records": len(records), "failures": len(failures)}},
        a.out)
    print("records=%d files=%d failures=%d roots=%d" %
          (len(records), len(seen_files), len(failures), len(roots)))
    return 0 if records else 2


def record_text(rec):
    text = rec.get("_text")
    if text is None:
        if rec.get("origin") in {"table", "bib"}:
            # Per-record sources must never borrow text from neighbouring rows of the same file.
            text = rec.get("row_text") or ""
        else:
            path = rec.get("file")
            text = text_of(path) if path and os.path.isfile(path) else ""
        rec["_text"] = text
    return text


def cmd_screen(a):
    case = load(a.case)
    idx = load(a.index)
    records = idx.get("records", [])
    q = first_value(case, ["research_question", "question", "topic", "question_text", "goal"])
    inc = first_value(case, ["inclusion_criteria", "include_criteria", "include", "纳入标准"])
    exc = first_value(case, ["exclusion_criteria", "exclude_criteria", "exclude", "排除标准"])
    yfrom = first_value(case, ["year_from", "start_year", "from_year"])
    yto = first_value(case, ["year_to", "end_year", "to_year"])
    need_full = bool(first_value(case, ["require_fulltext", "fulltext_required", "must_fulltext"]))

    def terms(x):
        if not x:
            return []
        if isinstance(x, str):
            return [t.strip().lower() for t in re.split(r"[\n;；,，、]", x) if t.strip()]
        if isinstance(x, list):
            out = []
            for it in x:
                if isinstance(it, str):
                    out.append(it.lower())
                elif isinstance(it, dict):
                    out.extend(str(v).lower() for v in it.values() if isinstance(v, str))
            return out
        return []

    inc_t, exc_t = terms(inc), terms(exc)
    yfrom = int(re.search(r"\d{4}", str(yfrom)).group(0)) if yfrom and re.search(r"\d{4}", str(yfrom)) else None
    yto = int(re.search(r"\d{4}", str(yto)).group(0)) if yto and re.search(r"\d{4}", str(yto)) else None
    seen, included, excluded, duplicates, weak = {}, [], [], [], []
    for rec in records:
        rec["_text"] = None
        blob = " ".join(str(rec.get(k) or "") for k in ("title", "abstract", "venue", "authors")).lower()
        reasons, warnings = [], []
        key = rec.get("dup_key")
        if key and key in seen:
            duplicates.append({"source_id": rec["source_id"], "duplicate_of": seen[key], "key": key})
            reasons.append("duplicate")
        else:
            if key:
                seen[key] = rec["source_id"]
            if yfrom and rec.get("year") is not None and rec["year"] < yfrom:
                reasons.append("year_out_of_range")
            if rec.get("year") is None:
                # Missing year is reported, not silently dropped: it stays in the corpus
                # but is excluded from the year table and stage split downstream.
                warnings.append("year_missing")
            if yto and rec.get("year") and rec["year"] > yto:
                reasons.append("year_out_of_range")
            if need_full and not rec.get("has_fulltext"):
                reasons.append("fulltext_required_missing")
            hit = [t for t in exc_t if t and t in blob]
            if hit:
                reasons.append("exclusion_term:%s" % "|".join(hit[:3]))
            if inc_t and not any(t and t in blob for t in inc_t):
                reasons.append("no_inclusion_term_match")
            if not inc_t and q and not any(tok in blob for tok in tokens(str(q))[:8]):
                weak.append({"source_id": rec["source_id"], "note": "question_terms_not_matched_in_title_or_abstract"})
        if reasons:
            excluded.append({"source_id": rec["source_id"], "title": rec.get("title"),
                             "year": rec.get("year"), "reasons": reasons})
        else:
            if warnings:
                rec["screening_warnings"] = warnings
            included.append(rec)
    reasons_count = Counter(r.split(":")[0] for x in excluded for r in x["reasons"])
    dump({"question": q, "criteria": {"include_terms": inc_t, "exclude_terms": exc_t,
                                      "year_from": yfrom, "year_to": yto,
                                      "require_fulltext": need_full,
                                      "source": "case fields" if (inc_t or exc_t or yfrom or yto) else "default_include_all"},
          "included": included, "excluded": excluded, "duplicates": duplicates,
          "weak_topic_match": weak,
          "counts": {"found": len(records), "included": len(included), "excluded": len(excluded),
                     "duplicates": len(duplicates), "weak_topic_match": len(weak),
                     "missing_year": sum(1 for r in included if r.get("year") is None),
                     "reasons": dict(reasons_count)}},
         a.out)
    print("found=%d included=%d excluded=%d duplicates=%d" %
          (len(records), len(included), len(excluded), len(duplicates)))
    return 0


def sentences(text):
    text = re.sub(r"(?m)^\s*#+\s*", "", text or "")
    text = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+", text) if len(s.strip()) > 30]


def cmd_matrix(a):
    scr = load(a.screen)
    rows, failures = [], []
    for rec in scr.get("included", []):
        text = record_text(rec)
        if not text and rec.get("abstract"):
            text = rec["abstract"]
        if not text:
            failures.append({"source_id": rec["source_id"], "reason": "no_text_available"})
            text = ""
        sents = sentences(text)
        result_sents = [s for s in sents if any(c in s.lower() for c in RESULT_CUES)]
        limit_sents = [s for s in sents if any(c in s.lower() for c in LIMIT_CUES)]
        sampled = [s for s in result_sents if re.search(r"\d", s)]
        strength = "low"
        if rec.get("has_fulltext") and sampled and re.search(r"(p\s*[<=]|95%\s*ci|n\s*=\s*\d+)", " ".join(sampled), re.I):
            strength = "high"
        elif rec.get("has_fulltext") and (result_sents or sampled):
            strength = "medium"
        page_para = []
        paras = paragraphs(text)
        for s in (result_sents[:2] + limit_sents[:1]):
            for p in paras:
                if s[:60] in p["text"]:
                    page_para.append({"quote": s, "page": p["page"], "paragraph": p["paragraph"]})
                    break
        themes = [t for t, _ in Counter(tokens((rec.get("title") or "") + " " + (rec.get("abstract") or ""))).most_common(6)]
        rows.append({
            "source_id": rec["source_id"], "file": rec.get("file"),
            "origin": rec.get("origin"),
            "text_source": "row" if rec.get("row_text") else "file",
            "title": rec.get("title"), "authors": rec.get("authors"),
            "year": rec.get("year"), "venue": rec.get("venue"), "doi": rec.get("doi"),
            "design": next((w for w in ("randomized", "cohort", "case-control", "cross-sectional", "in vitro",
                                        "in vivo", "meta-analysis", "review", "survey", "队列", "随机", "横断面",
                                        "荟萃", "综述", "问卷") if w in (text or "").lower()), "not_reported"),
            "key_findings": result_sents[:2], "limitations": limit_sents[:2],
            "evidence_strength": strength, "quotes": page_para,
            "themes_hint": themes, "has_fulltext": rec.get("has_fulltext"),
            "has_abstract": bool(rec.get("abstract")), "has_year": rec.get("year") is not None,
        })
    dump({"matrix": rows, "failures": failures,
          "counts": {"included": len(scr.get("included", [])), "matrix_rows": len(rows),
                     "with_quotes": sum(1 for r in rows if r["quotes"]),
                     "no_text": len(failures)}}, a.out)
    print("matrix rows=%d with_quotes=%d no_text=%d" %
          (len(rows), sum(1 for r in rows if r["quotes"]), len(failures)))
    return 0


def cmd_themes(a):
    mx = load(a.matrix)
    rows = mx.get("matrix", [])
    df = Counter()
    rec_terms = {}
    for r in rows:
        terms = set(tokens((r.get("title") or "") + " " + " ".join(r.get("key_findings") or []) +
                           " " + " ".join(r.get("themes_hint") or [])))
        rec_terms[r["source_id"]] = terms
        for t in terms:
            df[t] += 1
    vocab = [t for t, c in df.most_common(40) if c >= 2 and len(t) >= 2]
    # connected components by shared terms, threshold 2 shared terms
    parent = {r["source_id"]: r["source_id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a1, a2 = rows[i]["source_id"], rows[j]["source_id"]
            if len(rec_terms[a1] & rec_terms[a2]) >= 2:
                parent[find(a1)] = find(a2)
    comps = defaultdict(list)
    for r in rows:
        comps[find(r["source_id"])].append(r)
    themes = []
    for k, members in comps.items():
        tc = Counter()
        for r in members:
            for t in rec_terms[r["source_id"]]:
                if t in vocab:
                    tc[t] += 1
        label_terms = [t for t, _ in tc.most_common(3)] or ["未命名主题"]
        years = [r["year"] for r in members if r.get("year")]
        themes.append({"theme_id": "T%d" % (len(themes) + 1),
                       "label": " / ".join(label_terms),
                       "terms": label_terms,
                       "support": [r["source_id"] for r in members],
                       "count": len(members),
                       "year_span": [min(years), max(years)] if years else None,
                       "boundary": "覆盖 %d 篇；年份 %s" % (len(members), "%s-%s" % (min(years), max(years)) if years else "未报告")})
    themes.sort(key=lambda t: -t["count"])

    # contradictions: same shared theme, opposite polarity signals
    contradictions = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            r1, r2 = rows[i], rows[j]
            shared = rec_terms[r1["source_id"]] & rec_terms[r2["source_id"]]
            if len(shared) < 2:
                continue
            b1 = " ".join(r1.get("key_findings") or []).lower()
            b2 = " ".join(r2.get("key_findings") or []).lower()
            p1 = any(w in b1 for w in POS); n1 = any(w in b1 for w in NEG)
            p2 = any(w in b2 for w in POS); n2 = any(w in b2 for w in NEG)
            if (p1 and n2) or (n1 and p2):
                contradictions.append({"theme_terms": sorted(shared)[:3],
                                       "a": {"source_id": r1["source_id"], "year": r1.get("year"),
                                             "quote": (r1.get("key_findings") or [""])[0][:220]},
                                       "b": {"source_id": r2["source_id"], "year": r2.get("year"),
                                             "quote": (r2.get("key_findings") or [""])[0][:220]},
                                       "note": "自动识别为相反/不一致表述，需人工确认是否同一结局与口径"})

    gaps = []
    for t in themes:
        if t["count"] == 1:
            gaps.append({"type": "thin_evidence", "theme": t["label"], "support": t["support"],
                         "statement": "主题仅 1 篇文献支撑，不足以形成稳定结论"})
    for r in rows:
        for q in (r.get("limitations") or []):
            if any(c in q.lower() for c in GAP_CUES):
                gaps.append({"type": "author_stated", "support": [r["source_id"]], "year": r.get("year"),
                             "statement": q[:300]})
    missing_year = [r["source_id"] for r in rows if not r.get("year")]
    missing_abs = [r["source_id"] for r in rows if not r.get("has_abstract")]
    dump({"themes": themes, "contradictions": contradictions, "gaps": gaps,
          "missing": {"year": missing_year, "abstract": missing_abs,
                      "fulltext": [r["source_id"] for r in rows if not r.get("has_fulltext")]},
          "counts": {"themes": len(themes), "contradictions": len(contradictions), "gaps": len(gaps)}}, a.out)
    print("themes=%d contradictions=%d gaps=%d" % (len(themes), len(contradictions), len(gaps)))
    return 0


def cmd_trends(a):
    mx = load(a.matrix)
    th = load(a.themes)
    rows = mx.get("matrix", [])
    years = defaultdict(list)
    missing_years = []
    for r in rows:
        if r.get("year"):
            years[r["year"]].append(r)
        else:
            missing_years.append(r["source_id"])
    dist = [{"year": y, "count": len(years[y]), "sources": [x["source_id"] for x in years[y]]}
            for y in sorted(years)]
    # stages: split into up to 3 contiguous windows by equal record counts, never empty
    ordered = sorted(years)
    stages = []
    if ordered:
        total = sum(len(years[y]) for y in ordered)
        target = max(1, total / 3.0)
        acc, cur = 0, []
        for y in ordered:
            cur.append(y)
            acc += len(years[y])
            if acc >= target and len(stages) < 2:
                stages.append(cur)
                cur, acc = [], 0
        if cur:
            stages.append(cur)
    stage_rows = []
    for i, ys in enumerate(stages, 1):
        members = [r for y in ys for r in years[y]]
        themes = Counter(t for r in members for t in (r.get("themes_hint") or [])[:4])
        reps = sorted(members, key=lambda r: (-int(bool(r.get("has_fulltext"))), r.get("year") or 0,
                                              -len(r.get("key_findings") or [])))[:2]
        stage_rows.append({"stage": "阶段%d" % i, "years": [min(ys), max(ys)], "count": len(members),
                           "top_terms": [t for t, _ in themes.most_common(4)],
                           "representative": [{"source_id": r["source_id"], "title": r.get("title"),
                                               "year": r.get("year"),
                                               "basis": "full_text>earlier>finding_rich(非被引排序)"}
                                              for r in reps]})
    # term first/last appearance
    first, last, cnt = {}, {}, Counter()
    for r in rows:
        if not r.get("year"):
            continue
        for t in set((r.get("themes_hint") or [])[:5]):
            first[t] = min(first.get(t, 9999), r["year"])
            last[t] = max(last.get(t, 0), r["year"])
            cnt[t] += 1
    latest_year = max(years) if years else None
    # A short window or a tiny corpus makes "emerging" trivially true; suppress it instead of over-claiming.
    emerging_suppressed = len(rows) < 5 or len(dist) < 3
    emerging = [] if emerging_suppressed else [
        {"term": t, "first_year": first[t], "last_year": last[t], "count": cnt[t]}
        for t in cnt if cnt[t] >= 2 and last[t] - first[t] <= 2
        and (latest_year is None or last[t] >= latest_year - 1)]
    emerging.sort(key=lambda x: (-x["last_year"], -x["count"]))
    dump({"distribution": dist, "stages": stage_rows,
          "emerging_terms": emerging[:8], "emerging_suppressed": emerging_suppressed,
          "missing_year": missing_years,
          "counts": {"records": len(rows), "with_year": len(rows) - len(missing_years),
                     "years_covered": len(dist), "stages": len(stage_rows)}}, a.out)
    print("years=%d stages=%d emerging=%d missing_year=%d" %
          (len(dist), len(stage_rows), len(emerging), len(missing_years)))
    return 0


def cmd_synthesize(a):
    scr = load(a.screen)
    mx = load(a.matrix)
    th = load(a.themes)
    tr = load(a.trends) if os.path.exists(a.trends) else {}
    rows = mx.get("matrix", [])
    question = scr.get("question") or "未提供研究问题（按材料可回答问题写）"
    inc = scr.get("criteria", {}).get("include_terms") or []
    mode = a.mode
    lines = []
    lines.append("# %s" % ("文献综述（证据约束草稿）" if mode == "review" else "研究前沿与趋势分析（证据约束报告）"))
    lines.append("")
    lines.append("> 本报告由脚本从所给文献集中抽取与统计生成；每条实质论断标注来源编号，引用可在 `matrix.json` 回链到原文段落。")
    lines.append("")
    lines.append("## 1. 研究问题与证据范围")
    lines.append("- 研究问题：%s" % question)
    lines.append("- 纳入文献：%d 篇；排除：%d 条（含重复 %d 条）；年份范围：%s" %
                 (scr.get("counts", {}).get("included", 0),
                  scr.get("counts", {}).get("excluded", 0),
                  scr.get("counts", {}).get("duplicates", 0),
                  "%s-%s" % (min([r["year"] for r in rows if r.get("year")] or ["NA"]),
                             max([r["year"] for r in rows if r.get("year")] or ["NA"]))))
    reasons = (scr.get("counts", {}).get("reasons") or {})
    if reasons:
        lines.append("- 排除原因：%s。" % "、".join("%s=%d" % (k, v) for k, v in sorted(reasons.items())))
    if inc:
        lines.append("- 纳入关键词：%s" % "、".join(inc[:8]))
    lines.append("- 数据口径：仅使用所给材料；不使用外部检索结果，不补造文献。")
    lines.append("")

    if mode == "review":
        lines.append("## 2. 主题结构与证据")
        for t in th.get("themes", []):
            cites = ",".join(t["support"][:6])
            lines.append("### %s（%d 篇，%s）" % (t["label"], t["count"],
                                                "%s-%s" % tuple(t["year_span"]) if t.get("year_span") else "年份未报告"))
            ev = [r for r in rows if r["source_id"] in t["support"]]
            for r in ev[:3]:
                finding = (r.get("key_findings") or ["（原文未抽取到结果句，见证据表）"])[0]
                lines.append("- %s 报告：%s `[%s]`（证据强度：%s）" %
                             ((r.get("title") or r["source_id"])[:80], finding[:260], r["source_id"],
                              r.get("evidence_strength")))
            if t["count"] > 3:
                lines.append("- 其余 %d 篇见证据矩阵（`[%s]`）。" % (t["count"] - 3, cites))
            lines.append("")
        lines.append("## 3. 冲突证据与反例")
        if th.get("contradictions"):
            for c in th["contradictions"][:5]:
                lines.append("- 主题词 %s：`[%s]` 与 `[%s]` 的表述方向不一致（%s vs %s），需核对结局与统计口径。" %
                             ("/".join(c["theme_terms"]), c["a"]["source_id"], c["b"]["source_id"],
                              c["a"]["year"], c["b"]["year"]))
        else:
            lines.append("- 未在抽取到的结果句中识别到明确相反表述；这不等于不存在冲突，可能源于原文未报告方向性结果。")
        lines.append("")
        lines.append("## 4. 研究空白")
        gaps = th.get("gaps", [])
        if gaps:
            for g in gaps[:8]:
                lines.append("- [%s] %s（支撑：`[%s]`）" % (g["type"], g["statement"], ",".join(g["support"][:4])))
        else:
            lines.append("- 未在材料中发现明确的“未解决/未来研究”陈述，也未出现单篇支撑的主题；当前不能据此宣称存在空白。")
        lines.append("")
        lines.append("## 5. 方法与可复现")
        lines.append("- 流程：`index → screen → matrix → themes → synthesize → verify`；筛选标准、排除原因、逐条原文与页段锚点均在 `screening.csv`/`matrix.csv`。")
        lines.append("- 主题由文献共词连通分量生成（共享≥2 个词项），标签取组内高频词，非预设“背景/方法/挑战”框架。")
        lines.append("")
    else:
        lines.append("## 2. 年度产出与阶段")
        lines.append("| 年份 | 篇数 | 来源 |")
        lines.append("|-|-|-|")
        for d in tr.get("distribution", []):
            lines.append("| %s | %d | %s |" % (d["year"], d["count"], ",".join(d["sources"])))
        lines.append("")
        lines.append("## 3. 主题演化")
        for s in tr.get("stages", []):
            lines.append("- %s（%s-%s，%d 篇）：主题词 %s；代表作 %s。" %
                         (s["stage"], s["years"][0], s["years"][1], s["count"],
                          "、".join(s["top_terms"]) or "未提取",
                          "、".join("`[%s]` %s" % (r["source_id"], (r["title"] or "")[:50]) for r in s["representative"])))
        if tr.get("emerging_terms"):
            lines.append("- 近期出现的候选主题词：%s（首次/最近年份见 `trends.json`）。" %
                         "、".join("%s(%d)" % (e["term"], e["count"]) for e in tr["emerging_terms"][:6]))
        elif tr.get("emerging_suppressed"):
            lines.append("- 纳入文献量或年份跨度不足，本轮不做“新兴/衰退主题”判断，避免把短窗口噪声当成趋势。")
        else:
            lines.append("- 未发现满足“≥2 篇且跨度≤2 年”的候选新兴主题词。")
        lines.append("")
        lines.append("## 4. 研究空白")
        gaps = th.get("gaps", [])
        if gaps:
            for g in gaps[:8]:
                lines.append("- [%s] %s（支撑：`[%s]`）" % (g["type"], g["statement"], ",".join(g["support"][:4])))
        else:
            lines.append("- 材料未给出可核的空白陈述；检索遗漏与真实空白无法区分，需扩大检索后再判断。")
        lines.append("")
        lines.append("## 5. 代表性工作口径")
        lines.append("- 代表作按“有全文 > 年份更早 > 结果句更多”选取，覆盖每个阶段，不按总被引排序（材料未提供被引数据）。")
        lines.append("")
    lines.append("## 6. 不确定性与限制")
    miss = th.get("missing", {})
    lines.append("- 缺年份：%s；缺摘要：%s；缺全文：%s。" %
                 (",".join(miss.get("year") or []) or "无", ",".join(miss.get("abstract") or []) or "无",
                  ",".join(miss.get("fulltext") or []) or "无"))
    lines.append("- 自动抽取的结果句可能遗漏正文表格/图注中的证据；引用强度按原文表述保留，不升级为因果。")
    lines.append("- 本报告不包含外部检索，不能据此断言“领域内不存在”某类研究。")
    lines.append("")
    report = "\n".join(lines)

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(report)
    with open(os.path.join(a.work, "matrix.csv"), "w", encoding="utf-8", newline="") as fh:
        cols = ["source_id", "title", "authors", "year", "venue", "doi", "design", "evidence_strength"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(a.work, "screening.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["source_id", "title", "year", "reasons"], extrasaction="ignore")
        w.writeheader()
        w.writerows(scr.get("excluded", []))
    dump({"report_markdown": report, "question": question,
          "counts": {"included": len(rows), "themes": th.get("counts", {}).get("themes", 0),
                     "contradictions": th.get("counts", {}).get("contradictions", 0),
                     "gaps": th.get("counts", {}).get("gaps", 0)}}, os.path.join(a.work, "report.json"))
    print("report chars=%d mode=%s" % (len(report), mode))
    return 0


def cmd_verify(a):
    scr = load(a.screen)
    mx = load(a.matrix)
    th = load(a.themes)
    rep = load(os.path.join(a.work, "report.json"))
    rows = mx.get("matrix", [])
    included_ids = {r["source_id"] for r in scr.get("included", [])}
    matrix_ids = {r["source_id"] for r in rows}
    items = []

    def add(name, ok, detail):
        items.append({"name": name, "ok": bool(ok), "detail": detail})

    c = scr.get("counts", {})
    add("screening_closure", c.get("found", 0) == c.get("included", 0) + c.get("excluded", 0),
        "found=%s included=%s excluded=%s" % (c.get("found"), c.get("included"), c.get("excluded")))
    add("matrix_covers_included", included_ids <= matrix_ids,
        "missing=%s" % (sorted(included_ids - matrix_ids)[:6] or "none"))
    add("matrix_not_outside_corpus", matrix_ids <= included_ids,
        "extra=%s" % (sorted(matrix_ids - included_ids)[:6] or "none"))
    add("row_scoped_text", all((r.get("origin") not in {"table", "bib"}) or r.get("text_source") == "row"
                               for r in rows),
        "borrowed=%s" % ([r["source_id"] for r in rows
                          if r.get("origin") in {"table", "bib"} and r.get("text_source") != "row"][:6] or "none"))

    bad_quotes = []
    quote_count = 0
    scoped = {r["source_id"]: r.get("row_text") for r in
              load(os.path.join(a.work, "records.json")).get("records", []) if r.get("row_text")}
    for r in rows:
        text = scoped.get(r.get("source_id")) or (text_of(r.get("file") or "") if r.get("file") else "")
        norm = re.sub(r"\s+", "", text)
        for q in r.get("quotes") or []:
            quote_count += 1
            if re.sub(r"\s+", "", q.get("quote") or "") not in norm:
                bad_quotes.append("%s:p%s" % (r["source_id"], q.get("page")))
    add("quotes_verbatim", not bad_quotes, "quotes=%d bad=%s" % (quote_count, bad_quotes[:5] or "none"))

    cites = set()
    for m in CITE_RE.finditer(rep.get("report_markdown", "")):
        cites.update(x.strip() for x in m.group(1).split(","))
    add("citations_resolve", cites <= included_ids, "cites=%d unresolved=%s" %
        (len(cites), sorted(cites - included_ids)[:6] or "none"))
    add("report_has_evidence", bool(cites), "cited_sources=%d" % len(cites))
    add("themes_have_support", all(t.get("support") for t in th.get("themes", [])),
        "themes=%d" % len(th.get("themes", [])))
    years = [d["year"] for d in load(a.trends).get("distribution", [])] if os.path.exists(a.trends) else []
    all_missing_year = bool(rows) and all(not r.get("year") for r in rows)
    add("year_stats_present", True if a.mode == "review" else (bool(years) or all_missing_year),
        "years=%s%s" % (years or ("review_mode" if a.mode == "review" else "none"),
                        " all_missing_year_reported" if all_missing_year else ""))
    if a.mode == "trends" and years:
        stated = {d["year"]: d["count"] for d in load(a.trends).get("distribution", [])}
        recomputed = Counter(r["year"] for r in rows if r.get("year"))
        add("year_counts_recomputable", dict(recomputed) == stated,
            "recomputed=%s stated=%s" % (dict(sorted(recomputed.items())), dict(sorted(stated.items()))))
    add("uncertainty_reported", "## 6. 不确定性与限制" in rep.get("report_markdown", ""),
        "section_present")
    add("no_external_references", all(r["source_id"] in included_ids for r in rows),
        "external_source_ids=%s" % (sorted(matrix_ids - included_ids)[:5] or "none"))
    metrics = {i["name"]: i["ok"] for i in items}
    dump({"items": items, "metrics": metrics,
          "summary": {"all_ok": all(metrics.values()),
                      "failed": [k for k, v in metrics.items() if not v],
                      "counts": {"included": len(rows), "quotes": quote_count, "cited": len(cites)}}},
         os.path.join(a.work, "checks.json"))
    print("checks %d/%d pass" % (sum(1 for v in metrics.values() if v), len(metrics)))
    for i in items:
        if not i["ok"]:
            print("  FAIL", i["name"], "-", i["detail"])
    return 0


def cmd_emit(a):
    contract = load(os.path.join(a.work, "contract.json"))
    scr = load(a.screen)
    mx = load(a.matrix)
    th = load(a.themes)
    tr = load(a.trends) if os.path.exists(a.trends) else {}
    rep = load(os.path.join(a.work, "report.json"))
    checks = load(os.path.join(a.work, "checks.json"))
    metrics = checks.get("metrics") or {}
    missing = th.get("missing", {})
    limits = []
    degradation = []
    included_n = len(mx.get("matrix", []))
    years_n = len(tr.get("distribution", [])) if a.mode == "trends" else None
    if not checks:
        degradation.append("未执行 verify")
    elif not all(metrics.values()):
        degradation.append("机器检查未全通过")
    if included_n == 0:
        degradation.append("纳入 0 篇，不推导趋势或空白")
    elif included_n < 5:
        degradation.append("纳入 %d 篇(<5)，不做新兴/衰退判断" % included_n)
    if a.mode == "trends" and years_n is not None and years_n < 3:
        degradation.append("年份跨度 %d 年(<3)，未强行三阶段" % years_n)
    status = "ok" if not degradation else "partial"
    if missing.get("year"):
        limits.append("%d 篇缺年份，年度统计未纳入" % len(missing["year"]))
    if missing.get("abstract"):
        limits.append("%d 篇缺摘要" % len(missing["abstract"]))
    if missing.get("fulltext"):
        limits.append("%d 篇仅有摘要，主题与证据强度受限" % len(missing["fulltext"]))
    limits.extend(degradation)
    failures = mx.get("failures", []) + load(a.index).get("failures", [])
    result = {
        "case_id": contract.get("case_id"),
        "status": status,
        "mode": a.mode,
        "research_product": {"question": rep.get("question"), "report_markdown": rep.get("report_markdown"),
                             "themes": th.get("themes", []), "trends": tr if a.mode == "trends" else None},
        "answer": rep.get("report_markdown"),
        "evidence_matrix": mx.get("matrix", []),
        "screening": scr,
        "uncertainty": {
            "missing_year": missing.get("year", []), "missing_abstract": missing.get("abstract", []),
            "missing_fulltext": missing.get("fulltext", []),
            "contradictions": th.get("contradictions", []),
            "note": "抽取式结果；冲突为表述方向自动比对，需人工核对结局与统计口径",
        },
        "checks": checks,
        "failures": failures,
        "sources": [{"path": p, "kind": "materials_root"} for p in load(a.index).get("roots", [])],
        "limits": "；".join(limits) if limits else "无已知限制",
        "counts": {"included": len(mx.get("matrix", [])),
                   "themes": len(th.get("themes", [])), "gaps": len(th.get("gaps", [])),
                   "years": len(tr.get("distribution", [])) if tr else 0},
    }
    fields = contract.get("contract") or {}
    names = []
    if isinstance(fields, dict):
        names = list(fields)
    elif isinstance(fields, list):
        for it in fields:
            if isinstance(it, str):
                names.append(it)
            elif isinstance(it, dict):
                nm = it.get("name") or it.get("field") or it.get("key")
                if nm:
                    names.append(str(nm))
    alias = {
        "research_product": "research_product", "report": "answer", "review": "answer",
        "draft": "answer", "evidence_matrix": "evidence_matrix", "matrix": "evidence_matrix",
        "uncertainty": "uncertainty", "screening": "screening", "references": "evidence_matrix",
        "sources": "sources", "checks": "checks", "failures": "failures", "status": "status",
        "limits": "limits", "trends": "research_product", "themes": "research_product",
    }
    unmapped = []
    if names:
        for name in names:
            key = name.lower().replace("-", "_")
            if key in result and result[key] is not None:
                continue
            target = alias.get(key)
            if target and result.get(target) is not None:
                result[name] = result[target]
            elif key not in result:
                result[name] = None
                unmapped.append(name)
    if unmapped:
        note = "契约字段 %s 无法从结果映射，已置 null" % ",".join(unmapped)
        result["limits"] = note if result["limits"] == "无已知限制" else result["limits"] + "；" + note
    os.makedirs(a.out, exist_ok=True)
    dump(result, os.path.join(a.out, "result.json"))
    for name in ("report.md", "matrix.csv", "screening.csv"):
        src = os.path.join(a.out if name == "report.md" else a.work, name)
        if os.path.exists(src) and name != "report.md":
            with open(src, encoding="utf-8") as fh:
                body = fh.read()
            with open(os.path.join(a.out, name), "w", encoding="utf-8") as fh:
                fh.write(body)
    print("result.json status=%s included=%d" % (status, len(mx.get("matrix", []))))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index"); p.add_argument("--case", default="work/case.raw.json")
    p.add_argument("--out", default="work/records.json"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("screen"); p.add_argument("--case", default="work/case.raw.json")
    p.add_argument("--index", default="work/records.json")
    p.add_argument("--out", default="work/screening.json"); p.set_defaults(fn=cmd_screen)
    p = sub.add_parser("matrix"); p.add_argument("--screen", default="work/screening.json")
    p.add_argument("--out", default="work/matrix.json"); p.set_defaults(fn=cmd_matrix)
    p = sub.add_parser("themes"); p.add_argument("--matrix", default="work/matrix.json")
    p.add_argument("--out", default="work/themes.json"); p.set_defaults(fn=cmd_themes)
    p = sub.add_parser("trends"); p.add_argument("--matrix", default="work/matrix.json")
    p.add_argument("--themes", default="work/themes.json")
    p.add_argument("--out", default="work/trends.json"); p.set_defaults(fn=cmd_trends)
    p = sub.add_parser("synthesize"); p.add_argument("--mode", choices=["review", "trends"], default="review")
    p.add_argument("--screen", default="work/screening.json"); p.add_argument("--matrix", default="work/matrix.json")
    p.add_argument("--themes", default="work/themes.json"); p.add_argument("--trends", default="work/trends.json")
    p.add_argument("--work", default="work"); p.add_argument("--out", default="/app/output")
    p.set_defaults(fn=cmd_synthesize)
    p = sub.add_parser("verify"); p.add_argument("--mode", default="review")
    p.add_argument("--screen", default="work/screening.json"); p.add_argument("--matrix", default="work/matrix.json")
    p.add_argument("--themes", default="work/themes.json"); p.add_argument("--trends", default="work/trends.json")
    p.add_argument("--work", default="work"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("emit"); p.add_argument("--mode", default="review")
    p.add_argument("--index", default="work/records.json"); p.add_argument("--screen", default="work/screening.json")
    p.add_argument("--matrix", default="work/matrix.json"); p.add_argument("--themes", default="work/themes.json")
    p.add_argument("--trends", default="work/trends.json"); p.add_argument("--work", default="work")
    p.add_argument("--out", default="/app/output"); p.set_defaults(fn=cmd_emit)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
