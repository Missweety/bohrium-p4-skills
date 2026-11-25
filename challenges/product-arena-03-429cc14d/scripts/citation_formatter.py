#!/usr/bin/env python3
"""citation_formatter.py - audit / renumber citations against a reference list (stdlib only).
  audit     citation points, 正文—列表一致性, duplicate candidates, field gaps, style issues
  renumber  sequential coding by first appearance; rewrite manuscript + reference list
"""
import argparse
import csv
import json
import os
import re
import unicodedata
BIB = re.compile(r"@(\w+)\s*\{\s*([^,]+),([\s\S]*?)\n\}", re.M)
FIELD = re.compile(r"(\w+)\s*=\s*[{\"]([^\n]*?)[}\"]\s*,?\s*\n")
DOI = re.compile(r"10\.\d{4,9}/[^\s,;\]}]+")
BRACKET = re.compile(r"[\[［【]\s*(\d[\d,，、\s\-–—]*)\s*[\]］】]")
CITE_CMD = re.compile(r"\\cite[pt]?\{([^}]+)\}")
NUM_LINE = re.compile(r"^\s*[\[［【]?(\d+)[\]］】\.、]\s*(.+?)\s*$")
AUTHOR_YEAR = re.compile(r"\(([A-Z][A-Za-z\-']+(?:\s+et al\.)?(?:\s+and\s+[A-Z][A-Za-z\-']+)?,\s*(?:19|20)\d{2}[a-z]?)\)")
REF_HEAD = re.compile(r"^#{1,6}\s*(参考文献|references|bibliography|引用文献|works cited)\s*$", re.M | re.I)

def norm(s):  # normalized comparison key (case/punctuation insensitive)
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s)
def split_refs(text):
    m = REF_HEAD.search(text)
    return (text[:m.start()], text[m.end():]) if m else (text, "")
COLMAP = {"title": ["title", "题名", "篇名", "文献题名", "article title"],
          "year": ["year", "年", "出版年", "年份", "date"],
          "doi": ["doi", "do"], "journal": ["journal", "期刊", "刊名", "来源", "source"],
          "volume": ["volume", "卷"], "issue": ["issue", "期"],
          "pages": ["pages", "页码", "页"], "author": ["author", "作者", "authors"],
          "type": ["type", "类型", "文献类型"], "key": ["key", "id", "编号", "序号"]}


NAME_PART = re.compile(r"^(?:[A-Z][A-Za-z\-']+(?:\s[A-Z][A-Za-z\-']+)*|[\u4e00-\u9fff]{2,4})$")


def _author_like(seg):
    """Numbered-list entries start with the author string; it must not be read as the title."""
    s = (seg or "").strip()
    if not s or re.search(r"(?:19|20)\d{2}", s):
        return False
    if re.search(r"et\s+al\.?|等", s):
        return True
    parts = [p.strip() for p in re.split(r"[,，、]|\s+and\s+|\s*&\s*", s) if p.strip()]
    if not all(NAME_PART.match(p) for p in parts):
        return False
    if len(parts) >= 2:
        return True
    return len(s.split()) <= 3 and not re.search(r"\b[a-z]{4,}\b", s)


def _pick_title(parts, raw):
    for p in parts:
        if len(p) >= 12 and not _author_like(p):
            return p
    return next((p for p in parts if len(p) >= 12), raw)


def _ref(key, fields, raw, i=0):
    raw = str(raw or "").strip()
    dm = DOI.search(raw)
    ym = re.search(r"(?:19|20)\d{2}", raw)
    title = fields.get("title", "") or _pick_title(re.split(r"[.。]\s+", raw), raw)
    return {"key": str(key or i), "raw": raw, "fields": fields,
            "doi": (fields.get("doi", "") or (dm.group(0).rstrip(".") if dm else "")),
            "title": title, "year": fields.get("year", "") or (ym.group(0) if ym else "")}


def parse_ris(text):
    recs, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])\s{1,2}-\s?(.*)$", line.strip())
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            if cur:
                recs.append(cur)
            cur = {}
        elif tag == "ER":
            if cur:
                recs.append(cur)
            cur = None
        elif cur is not None:
            cur.setdefault(tag, []).append(val)
    if cur:
        recs.append(cur)
    out = []
    for i, r in enumerate(recs, 1):
        f = {"title": (r.get("TI") or r.get("T1") or [""])[0],
             "year": (r.get("PY") or r.get("Y1") or [""])[0],
             "doi": (r.get("DO") or [""])[0],
             "journal": (r.get("JO") or r.get("JF") or r.get("T2") or [""])[0],
             "volume": (r.get("VL") or [""])[0], "issue": (r.get("IS") or [""])[0],
             "pages": (r.get("SP") or [""])[0] + (("-" + r["EP"][0]) if r.get("EP") else ""),
             "type": (r.get("TY") or [""])[0]}
        raw = " | ".join(v for k in ("AU", "TI", "JO", "PY", "DO", "VL", "IS", "SP") for v in r.get(k, []))
        out.append(_ref((r.get("ID") or [str(i)])[0], f, raw, i))
    return out


def parse_table_refs(path):
    rows = []
    if path.lower().endswith((".xlsx", ".xlsm")):
        try:
            import kernel  # same directory: reuse the stdlib xlsx reader
            rows = [r.split("\t") for r in kernel.read_xlsx(path).splitlines() if r.strip()]
        except Exception:  # noqa: BLE001
            return []
    else:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
            rows = [r for r in csv.reader(fh, delimiter="\t" if path.lower().endswith(".tsv") else ",")
                    if any(x.strip() for x in r)]
    if len(rows) < 2:
        return []
    head = [h.strip().lower() for h in rows[0]]
    idx = {}
    for k, names in COLMAP.items():
        for n in names:
            if n in head:
                idx[k] = head.index(n)
                break
    if "title" not in idx:
        return []
    out = []
    for i, row in enumerate(rows[1:], 1):
        get = lambda k: row[idx[k]].strip() if k in idx and idx[k] < len(row) else ""  # noqa: E731
        f = {k: get(k) for k in COLMAP if k in idx}
        raw = " ".join(get(k) for k in ("author", "title", "journal", "year", "doi"))
        out.append(_ref(get("key") or i, f, raw, i))
    return out


def parse_xml_refs(text):
    out = []
    for i, rec in enumerate(re.findall(r"<record>([\s\S]*?)</record>", text, re.I), 1):
        def tag(name):
            m = re.search(r"<%s[^>]*>([\s\S]*?)</%s>" % (name, name), rec, re.I)
            return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""
        f = {"title": tag("title"), "year": tag("year"), "doi": tag("doi"),
             "journal": tag("secondary-title"), "volume": tag("volume"),
             "issue": tag("number"), "pages": tag("pages")}
        out.append(_ref(tag("rec-number") or i, f, " ".join(f.values()), i))
    return out


def parse_refs(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".ris":
        return parse_ris(open(path, encoding="utf-8", errors="replace").read())
    if ext in {".csv", ".tsv", ".xlsx", ".xlsm"}:
        return parse_table_refs(path)
    text = open(path, encoding="utf-8", errors="replace").read()
    if ext == ".xml":
        refs = parse_xml_refs(text)
        if refs:
            return refs
    body = split_refs(text)[1] or text
    out = []
    for m in BIB.finditer(body):
        f = {k.lower(): v.strip() for k, v in FIELD.findall(m.group(3))}
        out.append(_ref(m.group(2).strip(), f, m.group(0)))
    if out:
        return out
    for line in body.splitlines():
        m = NUM_LINE.match(line)
        if not m:
            continue
        raw = m.group(2).strip()
        parts = [p.strip() for p in re.split(r"[.。]\s+", raw) if p.strip()]
        out.append(_ref(m.group(1), {"text": raw}, raw))
        if len(out[-1]["title"]) < 12:
            out[-1]["title"] = next((p for p in parts if len(p) >= 12), raw)
    return out


def expand(spec):  # [1,3-5] -> [1,3,4,5]
    out = []
    for p in [x.strip() for x in re.split(r"[,，、]", spec) if x.strip()]:
        if re.match(r"^\d+\s*[-–—]\s*\d+$", p):
            a, b = [int(x) for x in re.split(r"[-–—]", p)]
            out += list(range(min(a, b), max(a, b) + 1))
        elif p.replace(" ", "").isdigit():
            out.append(int(p.replace(" ", "")))
    return out


def scan(text):
    hits = [{"token": "[%d]" % n, "n": n, "pos": m.start()}
            for m in BRACKET.finditer(text) for n in expand(m.group(1))]
    hits += [{"token": "\\cite{%s}" % k.strip(), "key": k.strip(), "pos": m.start()}
             for m in CITE_CMD.finditer(text) for k in m.group(1).split(",")]
    hits += [{"token": m.group(0), "ay": m.group(1), "pos": m.start()} for m in AUTHOR_YEAR.finditer(text)]
    return sorted(hits, key=lambda h: h["pos"])
def audit(a):
    for path, label in ((a.manuscript, "manuscript"), (a.refs, "reference library")):
        if not os.path.exists(path):
            print("missing %s: %s" % (label, path))
            return 2
    body = split_refs(open(a.manuscript, encoding="utf-8", errors="replace").read())[0]
    refs = parse_refs(a.refs)
    nums = [int(r["key"]) for r in refs if str(r["key"]).isdigit()]
    keys = {r["key"] for r in refs}
    hits = scan(body)
    cited = sorted({h["n"] for h in hits if "n" in h})
    cited_keys = sorted({h["key"] for h in hits if h.get("key")})
    order = list(dict.fromkeys(h["n"] for h in hits if "n" in h))
    dup, seen, pairs = [], {}, set()
    for i, r in enumerate(refs):
        sigs = []
        if r["doi"]:
            sigs.append(("doi:" + norm(r["doi"]), "doi_exact"))
        if len(norm(r["title"])) >= 12:
            # B-level per references/dedup-verify.md: identical title AND identical year
            sigs.append(("title:" + norm(r["title"]) + "@" + str(r["year"] or "?"), "title_exact"))
        for sig, crit in sigs:
            if sig not in seen:
                seen[sig] = i
            elif (refs[seen[sig]]["key"], r["key"]) not in pairs:
                pairs.add((refs[seen[sig]]["key"], r["key"]))
                dup.append({"a": refs[seen[sig]]["key"], "b": r["key"], "criterion": crit})
    # containment-level candidates: one normalized title contains the other, ratio >= 0.9
    for i in range(len(refs)):
        ti = norm(refs[i]["title"])
        if len(ti) < 12:
            continue
        for j in range(i + 1, len(refs)):
            tj = norm(refs[j]["title"])
            if len(tj) < 12 or (refs[i]["key"], refs[j]["key"]) in pairs:
                continue
            lo, hi = sorted((ti, tj), key=len)
            if lo in hi and len(lo) / len(hi) >= 0.9:
                pairs.add((refs[i]["key"], refs[j]["key"]))
                dup.append({"a": refs[i]["key"], "b": refs[j]["key"], "criterion": "title_containment"})
    gaps = [{"key": r["key"], "missing": [f for f in ("title", "year") if not str(r.get(f) or "").strip()]
             + ([] if r["doi"] else ["doi"])} for r in refs]
    issues = []
    if not refs:
        issues.append("no reference entries parsed: check library format (bib/ris/csv/xlsx/numbered list)")
    if CITE_CMD.search(body) and BRACKET.search(body):
        issues.append("mixed citation syntax: numeric bracket + \\cite")
    if AUTHOR_YEAR.search(body) and BRACKET.search(body):
        issues.append("mixed style: author-year and numeric citations coexist")
    bad = [n for n in order if n not in nums]
    if bad:
        issues.append("citation numbers without reference entry: %s" % bad)
    bad_keys = [k for k in cited_keys if k not in keys]
    if bad_keys:
        issues.append("citation keys without reference entry: %s" % bad_keys)
    if nums and sorted(nums) != list(range(1, max(nums) + 1)):
        issues.append("reference numbering not contiguous from 1")
    if order != sorted(order):
        issues.append("numeric citations not in ascending first-appearance order")
    listed_not_cited = sorted(n for n in nums if n not in cited) \
        + sorted(k for k in keys if not str(k).isdigit() and k not in cited_keys)
    report = {"style": a.style, "refs": len(refs), "in_text_hits": len(hits), "cited_unique": len(cited),
              "cited_not_listed": sorted(set(bad) | set(bad_keys)),
              "listed_not_cited": listed_not_cited,
              "first_appearance": order,
              "first_appearance_keys": list(dict.fromkeys(h["key"] for h in hits if h.get("key"))),
              "duplicate_candidates": dup,
              "field_gaps": [g for g in gaps if g["missing"]], "style_issues": issues,
              "verdict": "pass" if not (bad or bad_keys or dup or issues or listed_not_cited) else "review"}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "citation_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "citation_points.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["token", "offset", "in_reference_list"])
        for h in hits:
            w.writerow([h["token"], h["pos"], (h.get("n") in nums) if "n" in h else (h.get("key") in keys)])
    print("verdict=%s refs=%d hits=%d cited_not_listed=%d dup=%d"
          % (report["verdict"], len(refs), len(hits), len(bad), len(dup)))
    for i in issues:
        print("  !", i)
    return 0

def _ident(ref):
    k = str(ref["key"])
    return ("n", int(k)) if k.isdigit() else ("k", k)


def _split_authors(raw):
    out = []
    for p in [x.strip() for x in re.split(r"\s+and\s+|;", raw or "") if x.strip()]:
        if re.search(r"[\u4e00-\u9fff]", p):
            out.append(("cjk", p, ""))
        elif "," in p:
            fam, giv = [x.strip() for x in p.split(",", 1)]
            out.append(("west", fam, giv))
        else:
            bits = p.split()
            out.append(("west", bits[-1], " ".join(bits[:-1])) if len(bits) > 1 else ("west", p, ""))
    return out


def _render_authors(raw, style):
    people = _split_authors(raw)
    if not people:
        return ""
    cjk = any(p[0] == "cjk" for p in people)
    etal = "等" if cjk else "et al."
    limit = 3 if style in ("gb7714", "") else (6 if style == "vancouver" else 20)
    shown = people[:limit]

    def one(p):
        _, fam, giv = p
        if p[0] == "cjk" or not giv:
            return fam
        initials = [w[0].upper() for w in re.split(r"[\s\-.]+", giv) if w]
        if style == "gb7714" or style == "":
            return fam.upper() + " " + " ".join(initials)
        if style == "vancouver":
            return fam + " " + "".join(initials)
        return "%s, %s" % (fam, ". ".join(initials) + ".")

    names = [one(p) for p in shown]
    if len(people) > limit:
        return ", ".join(names) + (", " + etal if not cjk else ", " + etal)
    if style == "apa" and len(names) > 1:
        return ", ".join(names[:-1]) + ", & " + names[-1]
    return ", ".join(names)


def format_entry(ref, style):
    """Render parsed fields into one reference line; fall back to the original record.

    Only fields present in the library are used - missing values are omitted, never invented.
    """
    f = ref.get("fields") or {}
    unesc = lambda s: re.sub(r"\\([&%$#_])", r"\1", s or "")  # noqa: E731  BibTeX escapes
    title = unesc(f.get("title") or ref.get("title") or "").strip().rstrip(".")
    year = str(f.get("year") or ref.get("year") or "").strip()
    journal = unesc(f.get("journal") or "").strip().rstrip(".")
    vol = str(f.get("volume") or "").strip()
    issue = str(f.get("issue") or "").strip()
    pages = re.sub(r"-{2,}", "-", str(f.get("pages") or "").strip())
    doi = (ref.get("doi") or f.get("doi") or "").strip().rstrip(".")
    authors = _render_authors(unesc(f.get("author", "")), style)
    if not title or not year or not (journal or authors):
        return ref["raw"].strip()  # not enough fields to render; keep the record verbatim
    kind = {"JOUR": "J", "CONF": "C", "BOOK": "M", "THES": "D"}.get(
        str(f.get("type", "")).upper(), "J" if journal else "")
    vol_part = vol + ("(%s)" % issue if issue else "")
    if style == "apa":
        line = "%s (%s). %s." % (authors, year, title)
        if journal:
            line += " %s" % journal
        tail = ", ".join(x for x in (vol_part, pages) if x)
        if tail:
            line += ("," if journal else "") + " " + tail
        line = line.rstrip() + "."
        if doi:
            line += " https://doi.org/%s" % doi
    elif style == "vancouver":
        line = "%s. %s." % (authors, title)
        if journal:
            line += " %s." % journal
        line += " %s" % year
        if vol_part and pages:
            line += ";%s:%s." % (vol_part, pages)
        elif vol_part:
            line += ";%s." % vol_part
        else:
            line += "."
        if doi:
            line += " doi:%s." % doi
    else:  # gb7714
        line = "%s. %s%s. %s, %s" % (authors, title, "[%s]" % kind if kind else "", journal, year)
        if pages:
            line += ", %s: %s." % (vol_part, pages) if vol_part else ": %s." % pages
        elif vol_part:
            line += ", %s." % vol_part
        else:
            line += "."
        if doi:
            line += " DOI:%s." % doi
    return re.sub(r"\s{2,}", " ", re.sub(r"\.{2,}", ".", line)).strip()


def renumber(a):
    for path, label in ((a.manuscript, "manuscript"), (a.refs, "reference library")):
        if not os.path.exists(path):
            print("missing %s: %s" % (label, path))
            return 2
    raw = open(a.manuscript, encoding="utf-8", errors="replace").read()
    body = split_refs(raw)[0]
    refs_list = parse_refs(a.refs)
    if not refs_list:
        print("no reference entries parsed from %s; check the library format" % a.refs)
    by_ident = {_ident(r): r for r in refs_list}
    ordered, seen = [], set()
    for h in scan(body):
        ident = ("n", h["n"]) if "n" in h else (("k", h["key"]) if h.get("key") else None)
        if ident and ident in by_ident and ident not in seen:
            seen.add(ident)
            ordered.append(ident)
    for ident in by_ident:  # uncited entries keep a stable slot after the cited ones
        if ident not in seen:
            seen.add(ident)
            ordered.append(ident)
    new_of = {ident: i + 1 for i, ident in enumerate(ordered)}

    unmapped = set()

    def _bracket(m):
        nums = []
        for x in expand(m.group(1)):
            if ("n", x) in new_of:
                nums.append(new_of[("n", x)])
            else:
                nums.append(x)
                unmapped.add(x)
        return "[%s]" % ",".join(str(n) for n in sorted(set(nums)))

    def _cite(m):
        keys = [k.strip() for k in m.group(1).split(",") if k.strip()]
        nums = sorted({new_of[("k", k)] for k in keys if ("k", k) in new_of})
        return "[%s]" % ",".join(str(n) for n in nums) if nums else m.group(0)

    out_body = CITE_CMD.sub(_cite, BRACKET.sub(_bracket, body)).rstrip()
    table = "\n".join("[%d] %s" % (new_of[_ident(r)], format_entry(r, a.style))
                      for r in refs_list if _ident(r) in new_of)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "manuscript_renumbered.md"), "w", encoding="utf-8") as fh:
        fh.write(out_body + "\n\n# 参考文献\n\n" + table + "\n")
    with open(os.path.join(a.out, "refs_renumbered.md"), "w", encoding="utf-8") as fh:
        fh.write("# 参考文献\n\n" + table + "\n")
    with open(os.path.join(a.out, "renumber_map.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["old", "new", "kind"])
        for ident in ordered:
            w.writerow([ident[1], new_of[ident], "number" if ident[0] == "n" else "key"])
        for n in sorted(unmapped):
            w.writerow([n, "", "unmapped: cited but absent from the library"])
    print("renumbered %d citations; refs=%d" % (len(new_of), len(refs_list)))
    if unmapped:
        print("unmapped citations kept verbatim: %s (report as cited_not_listed, do not invent entries)"
              % sorted(unmapped))
    return 0

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("audit", audit), ("renumber", renumber)):
        p = sub.add_parser(name)
        p.add_argument("--manuscript", required=True); p.add_argument("--refs", required=True)
        p.add_argument("--style", default="gb7714", choices=["gb7714", "apa", "vancouver"])
        p.add_argument("--out", default="work")
        p.set_defaults(fn=fn)
    args = ap.parse_args()
    return args.fn(args)

if __name__ == "__main__":
    raise SystemExit(main())
