#!/usr/bin/env python3
"""claim_citation_linker.py - sentence-level claim -> citation map for intro / related work.

Stdlib only, no network. Flags: assertion without citation, gap without citations,
decorative citation, stacked citations, citations absent from the reference list,
contributions without an evidence pointer.

  python scripts/claim_citation_linker.py audit --draft work/intro.md --refs materials/refs.md --out work
Outputs work/claim_map.json + work/claim_map.csv.
"""
import argparse
import csv
import json
import os
import re

HEAD = re.compile(r"^#{1,6}\s+(.+)$", re.M)
SENT = re.compile(r"[^。！？!?]+?(?:[。！？!?]+|\.(?=\s|$))|.+$", re.S)
# "Fig. 2" / "e.g." / "et al." end with a dot that is not a sentence boundary; splitting there
# turned one claim into two fragments ("…（Fig." + "2），并以…") and produced false findings.
ABBREV = re.compile(r"\b(Fig|Figs|Tab|Table|Eq|Eqs|Ref|Refs|No|vs|cf|al|e\.g|i\.e|approx)\.", re.I)
NUM_CITE = re.compile(r"\[(\d[\d,\s\-–]*)\]")
CMD_CITE = re.compile(r"\\cite\{([^}]+)\}")
AY_CITE = re.compile(r"\(([A-Z][A-Za-z\-']+(?:\s+et al\.)?,\s*(?:19|20)\d{2}[a-z]?)\)")
NUM = re.compile(r"\d+(?:[.,]\d+)?\s?%?")
REF_HEAD = re.compile(r"^#{1,6}\s*(参考文献|references|bibliography)\s*$", re.M | re.I)
SECTION_ROLES = (
    ("background", r"背景|background|motivation"),
    ("related", r"相关工作|相关研究|related\s+work|prior\s+work|literature"),
    ("gap", r"空白|局限|gap|limitation|challenge"),
    ("contribution", r"贡献|contribution|本文工作|this\s+work"),
)
HARD_STATUS = {"missing_ref", "gap_unsupported", "contribution_needs_evidence", "stacked", "decorative"}

CUES = {
    "gap": r"然而|但是|尚未|仍缺乏|鲜有|有待|仍未被|尚不清楚|尚未见|未见报道|仍未知|待回答|"
           r"remains?\s+(?:unclear|unknown|limited|unanswered)|few\s+studies|has\s+not\s+been|"
           r"not\s+yet|unaddressed",
    "boundary": r"限于|不外推|不适用于|仅适用|仅在|超出本文|不宣称|scope\s+is\s+limited|"
                r"not\s+generaliz|beyond\s+the\s+scope",
    "contribution": r"本文[^。；，]{0,12}?(?:提出|设计|构建|贡献|实现|给出)|"
                    r"本研究[^。；，]{0,12}?(?:提出|设计|构建|实现|给出)|"
                    r"我们(?:提出|设计|构建|实现)|^[（(]\d+[）)]|"
                    r"we\s+(?:propose|present|introduce|develop)|"
                    r"this\s+(?:paper|work)\s+(?:proposes?|presents?|introduces?)",
    "background": r"近年来|随着|in\s+recent\s+years|recently|has\s+attracted|受到(?:广泛)?关注",
    "result": r"结果表明|结果显示|we\s+(?:found|show)|results?\s+(?:show|indicate)",
}
COMPARE = r"与本文(?:相比|不同|区别)|compared\s+(?:with|to)\s+(?:this|our)\s+work|in\s+contrast\s+to\s+(?:this|our)"
CLAIM = r"表明|证明|显示|发现|导致|优于|显著|outperform|demonstrate|suggest|indicate|improve"
EVIDENCE = r"图\s?\d|表\s?\d|Fig(?:ure)?\.?\s?\d|Table\s?\d|Section\s?\d|第\s?\d+\s?节"
DECOR = r"^(?:已有|大量|不少)?(?:研究|文献|工作)(?:表明|发现|指出|关注|报道)?[，,]?\s*$|^(?:many|several|previous)\s+studies\s*$"
DISTINGUISH = (r"前者|后者|分别|相较|相比|但|却|而|while|whereas|in contrast|respectively|"
               r"路线|途径|方向|类别|综述|概括|总体|多个|若干|two|three|several|multiple|approaches?")

def sentence_spans(text):
    """(offset, sentence) pairs; abbreviation dots are protected before splitting.

    The offset points at the first non-space character: heading lines are blanked out with
    spaces, so a span used to start inside the previous section and mis-attribute the
    sentence that follows a heading.
    """
    guarded = ABBREV.sub(lambda m: m.group(1) + "\u0000", text)
    for m in SENT.finditer(guarded):
        piece = m.group(0)
        lead = len(piece) - len(piece.lstrip())
        sent = piece.strip().replace("\u0000", ".")
        if sent:
            yield m.start() + lead, sent


def split_sentences(text):
    return [s for _, s in sentence_spans(text)]


def expand(spec):
    out = []
    for p in [x.strip() for x in spec.split(",")]:
        if re.match(r"^\d+\s*[-–]\s*\d+$", p):
            a, b = [int(x) for x in re.split(r"[-–]", p)]
            out += list(range(min(a, b), max(a, b) + 1))
        elif p.isdigit():
            out.append(int(p))
    return out

def ref_keys(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    keys, nums = set(), set()
    for m in re.finditer(r"@\w+\s*\{\s*([^,\s]+),", text):
        keys.add(m.group(1))
    for m in re.finditer(r"^\s*\[?(\d+)[\]\.、]\s+", text, re.M):
        nums.add(int(m.group(1)))
    return keys, nums


def citation_tokens(sentence):
    toks = []
    for m in NUM_CITE.finditer(sentence):
        toks += ["[%d]" % n for n in expand(m.group(1))]
    toks += ["%s" % k.strip() for m in CMD_CITE.finditer(sentence) for k in m.group(1).split(",")]
    toks += [m.group(1) for m in AY_CITE.finditer(sentence)]
    return list(dict.fromkeys(toks))


def token_ok(tok, keys, nums):
    if tok.startswith("[") and tok.endswith("]"):
        return int(tok.strip("[]")) in nums
    if re.match(r"^[A-Z][A-Za-z\-']+", tok):
        year = re.search(r"(?:19|20)\d{2}", tok)
        return any(year and year.group(0) in k or tok.split(",")[0].lower() in k.lower() for k in keys) if keys else False
    return tok in keys


def role_of(s):
    if re.search(COMPARE, s, re.I):
        return "related"          # "与本文相比" is a contrast sentence, not a contribution
    for role in ("boundary", "gap", "contribution", "result", "background"):
        if re.search(CUES[role], s, re.I):
            return role
    return "related"


def classify(sentence, toks, keys, nums, numeric_unverifiable=False):
    body = NUM_CITE.sub("", CMD_CITE.sub("", AY_CITE.sub("", sentence))).strip()
    role = role_of(sentence)
    if toks:
        bad = [t for t in toks if not token_ok(t, keys, nums)]
        # A numeric citation cannot be resolved against a key-only .bib library; that is a
        # format mismatch to report, not proof that the reference does not exist.
        if bad and numeric_unverifiable and all(t.startswith("[") for t in bad):
            return "unverified_numeric", ("编号引用无法对齐 key 制文献库：改用 \\cite{key}，"
                                          "或提供 cite_map.csv（编号→key）后复跑")
        if bad:
            return "missing_ref", "补齐文献表条目，或改引库内已核验文献"
    if len(toks) >= 3 and not re.search(DISTINGUISH, sentence):
        return "stacked", "拆分各文献的独立贡献或改为概括性表述"
    if role == "boundary":
        return "ok", ""           # scope statement: no citation is owed
    if toks and (len(body) < 12 or re.match(DECOR, body)):
        return "decorative", "删引用或补上该文献的具体结论"
    if role == "gap" and len(toks) < 2:
        return "gap_unsupported", "为空白陈述补 >=2 条已引文献的局限依据，否则降级为作者判断"
    if role == "contribution":
        return ("ok", "") if re.search(EVIDENCE, sentence) else (
            "contribution_needs_evidence", "补图表/章节/结果的对应指针，或删去该条贡献")
    if role == "related" and re.search(COMPARE, sentence, re.I):
        return "ok", ""          # explicit "vs. this work" contrast needs no citation
    if not toks and (role in ("background", "related", "result")
                     or re.search(CLAIM, sentence, re.I) or NUM.search(body)):
        return "needs_citation", "挂到支撑该论断的句子，或标 missing_citation"
    return "ok", ""


def section_role(name):
    for role, pat in SECTION_ROLES:
        if re.search(pat, name, re.I):
            return role
    return None


def read_csv(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_cite_map(path):
    """Optional number -> bibkey mapping (CSV with old,key columns) for numeric drafts."""
    rows = read_csv(path)
    if not rows:
        return {}
    out = {}
    for row in rows:
        num = (row.get("number") or row.get("old") or "").strip()
        key = (row.get("key") or row.get("new") or "").strip()
        if num.isdigit() and key:
            out[int(num)] = key
    return out


def audit_tables(gap_table, contrib_map, body):
    """Cross-check the gap / contribution tables against the manuscript text."""
    problems, warnings = [], []
    gaps = read_csv(gap_table)
    if gaps is not None:
        if not gaps:
            problems.append("gap_table.csv is empty")
        cols = set(gaps[0].keys()) if gaps else set()
        for need in ("gap", "cited_limitations", "uncovered_condition", "how_this_work_answers"):
            if gaps and need not in cols:
                problems.append("gap_table.csv missing column: %s" % need)
        for i, row in enumerate(gaps, 2):
            cited = [c for c in re.split(r"[;；,，\s]+", row.get("cited_limitations", "")) if c]
            if len(cited) < 2:
                problems.append("gap_table row %d has %d cited limitation(s), need >=2" % (i, len(cited)))
            if not (row.get("uncovered_condition") or "").strip():
                problems.append("gap_table row %d missing uncovered_condition" % i)
    contribs = read_csv(contrib_map)
    if contribs is not None:
        if not contribs:
            problems.append("contribution_map.csv is empty")
        cols = set(contribs[0].keys()) if contribs else set()
        for need in ("contribution", "evidence_pointer", "boundary", "verified"):
            if contribs and need not in cols:
                problems.append("contribution_map.csv missing column: %s" % need)
        for i, row in enumerate(contribs, 2):
            ptr = (row.get("evidence_pointer") or "").strip()
            if not ptr:
                problems.append("contribution_map row %d has no evidence_pointer" % i)
            elif not re.search(r"图\s?\d|表\s?\d|Fig(?:ure)?\.?\s?\d|Table\s?\d|Section\s?\d|第\s?\d+\s?节",
                               ptr):
                warnings.append("contribution_map row %d pointer is not a locatable figure/table/section: %s"
                                % (i, ptr))
            elif ptr.split()[0] not in body and ptr not in body:
                warnings.append("contribution_map row %d pointer not found in draft text: %s" % (i, ptr))
            if str(row.get("verified", "")).strip().lower() not in {"true", "yes", "1", "verified"}:
                warnings.append("contribution_map row %d is not marked verified" % i)
    return problems, warnings


def main():
    ap = argparse.ArgumentParser()
    p = ap.add_subparsers(dest="cmd", required=True).add_parser("audit")
    p.add_argument("--draft", required=True); p.add_argument("--refs", required=True)
    p.add_argument("--out", default="work")
    p.add_argument("--gap-table", default="")
    p.add_argument("--contribution-map", default="")
    p.add_argument("--cite-map", default="",
                   help="CSV with number,key columns when the draft uses [1] and the library is key-based")
    p.add_argument("--strict", action="store_true",
                   help="exit 1 on hard issues or on wrong section order")
    a = ap.parse_args()

    raws = open(a.draft, encoding="utf-8", errors="replace").read() if os.path.exists(a.draft) else None
    if raws is None:
        print("missing draft: %s" % a.draft)
        return 2
    if not os.path.exists(a.refs):
        print("missing reference library: %s" % a.refs)
        return 2
    raw = raws
    cut = REF_HEAD.search(raw)
    body = raw[:cut.start()] if cut else raw
    keys, nums = ref_keys(a.refs)
    cmap = load_cite_map(a.cite_map)
    numeric_unverifiable = bool(keys) and not nums and not cmap

    sections = [(m.start(), m.group(1).strip()) for m in HEAD.finditer(body)]
    clean = HEAD.sub(lambda m: " " * len(m.group(0)), body)
    rows, counts = [], {}
    used_nums, used_keys = set(), set()
    for pos_i, sent in sentence_spans(clean):
        if len(sent) < 4 or sent.startswith("#"):
            continue
        section = next((name for pos, name in reversed(sections) if pos <= pos_i), "preamble")
        toks = citation_tokens(sent)
        if cmap:
            toks = [cmap.get(int(t.strip("[]")), t) if t.startswith("[") else t for t in toks]
        status, action = classify(sent, toks, keys, nums, numeric_unverifiable)
        counts[status] = counts.get(status, 0) + 1
        for t in toks:
            (used_nums.add(int(t.strip("[]"))) if t.startswith("[") else used_keys.add(t))
        rows.append({"sid": "S%03d" % (len(rows) + 1), "section": section,
                     "role": role_of(sent), "sentence": sent, "citations": toks,
                     "ref_ok": all(token_ok(t, keys, nums) for t in toks),
                     "status": status, "action": action})

    orphan = sorted(n for n in nums if n not in used_nums)
    # section order: background -> related -> gap -> contribution when those headings exist
    roles_found, order_problems = [], []
    for pos, name in sections:
        role = section_role(name)
        if role and role not in roles_found:
            roles_found.append(role)
    expected = [r for r, _ in SECTION_ROLES]
    ranks = [expected.index(r) for r in roles_found]
    if ranks != sorted(ranks):
        order_problems.append("section order is %s, expected background -> related -> gap -> contribution"
                              % " -> ".join(roles_found))
    if "related" in roles_found and "gap" not in roles_found:
        order_problems.append("related work present but no gap section: state the research gap explicitly")
    table_problems, table_warnings = audit_tables(a.gap_table, a.contribution_map, body)
    hard = {k: v for k, v in counts.items() if k in HARD_STATUS}
    verdict = "fail" if hard or order_problems or table_problems else \
        ("review" if counts.get("needs_citation") or counts.get("unverified_numeric")
         or table_warnings else "pass")
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "claim_map.json"), "w", encoding="utf-8") as fh:
        json.dump({"sentences": len(rows), "citations": sum(len(r["citations"]) for r in rows),
                   "status_counts": counts, "orphan_refs": orphan, "rows": rows,
                   "verdict": verdict, "section_order": roles_found,
                   "order_problems": order_problems, "table_problems": table_problems,
                   "table_warnings": table_warnings}, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "claim_map.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sid", "section", "role", "citations", "status", "action", "sentence"])
        for r in rows:
            w.writerow([r["sid"], r["section"], r["role"], ";".join(r["citations"]),
                        r["status"], r["action"], r["sentence"]])
    print("sentences=%d citations=%d orphan_refs=%d verdict=%s"
          % (len(rows), sum(len(r["citations"]) for r in rows), len(orphan), verdict))
    for status, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print("  %-28s %d" % (status, n))
    for msg in order_problems + table_problems:
        print("  !", msg)
    for msg in table_warnings[:8]:
        print("  ~", msg)
    if a.strict and verdict != "pass":
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
