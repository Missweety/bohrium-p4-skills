#!/usr/bin/env python3
"""structure_probe.py - manuscript structure probe (stdlib only).

Outputs work/structure.json with section tree/weights, paragraph ids + line ranges,
claim candidates, citation/number/figure density and rule flags.

Degradations that keep the run alive:
  * no blank-line paragraph breaks -> re-chunk lines into pseudo-paragraphs;
  * no headings / chaotic numbering -> inferred sections §A..§F, inferred_sections=true;
  * numeric-leading body lines are not mistaken for headings.

Every paragraph/section is a candidate to be re-read; flags never assert a defect by themselves.
Usage: python structure_probe.py --corpus work/corpus.txt --out work [--file NAME]
"""
import argparse
import json
import math
import os
import re
import sys

FILE_RE = re.compile(r"^===== FILE: (.+?) =====\s*$", re.M)
HEAD_NUM = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+(\S.{0,90})$")
HEAD_KW = re.compile(r"(?i)^(abstract|keywords?|introduction|related work|background|materials? and methods?|"
                     r"methods?|results?|discussion|conclusions?|references|acknowledg\w*|appendix|supplementary|"
                     r"摘要|关键词|引言|前言|背景|方法|材料与方法|结果|讨论|结论|参考文献|致谢|附录)\b")
SENT_RE = re.compile(r"(?<=[。！？!?])|(?<=[.])\s+")
CITE_RE = re.compile(r"(\[[0-9,\s\-–]+\]|\\cite\{[^}]+\}|\([A-Z][A-Za-z\-]+(?: et al\.)?,? (?:19|20)\d{2}\))")
CLAIM_RE = re.compile(r"(?i)\b(?:show|shows|showed|indicate|indicates|suggest|suggests|demonstrate|demonstrates|found|"
                      r"find|increase[sd]?|decrease[sd]?|improve[sd]?|reveal[sd]?)\b|表明|说明|显示|证明")
NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
RESULT_RE = re.compile(r"(?i)\b(?:yield|degrad\w*|removal|rate|increas\w*|decreas\w*|reached|declined?)\b|"
                       r"降解率|去除率|产率|转化率|达到|增至|降至|提高|下降|优于|低于|高于")
# Section roles seen in real Chinese and English manuscripts. Substring tests used to be
# English-only, so every Chinese "1 引言 / 3 结果" manuscript reported "未检出引言类章节".
ROLE_KEYS = {
    "引言": ("introduction", "background", "引言", "前言", "背景", "概述"),
    "方法": ("method", "materials", "experimental", "方法", "材料", "实验", "表征"),
    "结果": ("result", "结果", "发现"),
    "讨论": ("discussion", "讨论", "分析"),
    "结论": ("conclusion", "结论", "总结", "结语"),
}


def role_present(sections, role):
    low = [(s or "").lower() for s in sections]
    return any(k in name for name in low for k in ROLE_KEYS[role])


ABS_RE = re.compile(r"(?i)\b(?:prove[sd]?|clearly|undoubtedly|first time|always|never|completely)\b|首次|完全|所有|毫无疑问|必然|普遍")
NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?[%‰])?")
REF_RE = re.compile(r"(?i)\b(fig(?:ure)?\.?|table|scheme)\s*\d+|[图表]\s*\d+")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']+")


def split_files(corpus):
    marks = list(FILE_RE.finditer(corpus))
    return [(m.group(1), corpus[m.end():(marks[i + 1].start() if i + 1 < len(marks) else len(corpus))].lstrip("\n"))
            for i, m in enumerate(marks)]


def heading(line):
    s = line.strip()
    if not s or len(s) > 100:
        return None
    if s.startswith("#"):
        return s.lstrip("#").strip() or None
    if HEAD_KW.match(s) and len(s) < 60:
        return s
    m = HEAD_NUM.match(s)
    if not m:
        return None
    rest = m.group(2).strip()
    if len(rest) > 60 or rest[:1].islower():
        return None
    if any(ch in rest for ch in "，。；！？"):
        return None
    if ". " in rest or rest.endswith((".", ",", ";", "。", "，", "；", ":")):
        return None
    return rest


def top_of(name):
    m = re.match(r"^(\d+)", name or "")
    return m.group(1) if m else (name or "").lower()


def _para(pid, section, start, buf):
    body = " ".join(buf)
    return {"paragraph_id": pid, "section": section, "start_line": start,
            "end_line": start + len(buf) - 1, "chars": len(body), "text": body,
            "citations": len(CITE_RE.findall(body)), "numbers": len(NUM_RE.findall(body)),
            "refs": len(REF_RE.findall(body)),
            "claims": len([s for s in SENT_RE.split(body) if CLAIM_RE.search(s)])}


def analyze(text):
    paras, heads, cur, buf, start = [], [], "Preamble", [], [None]

    def flush():
        if not buf:
            return
        paras.append(_para("P%03d" % (len(paras) + 1), cur, start[0], buf))
        buf[:] = []
        start[0] = None

    for i, line in enumerate(text.splitlines(), 1):
        h = heading(line)
        if h:
            flush()
            cur = h
            heads.append({"name": h, "top": top_of(h), "start_line": i})
        elif line.strip():
            start[0] = start[0] or i
            buf.append(line.strip())
        else:
            flush()
    flush()

    notes = ["段落/章节均为规则识别候选，必须回原文核对后写入诊断",
             "section_not_detected 只表示未检出，不表示缺失"]
    inferred = False
    if len(paras) <= 1 and len([ln for ln in text.splitlines() if ln.strip()]) >= 8:
        # No blank-line paragraph structure: re-chunk non-empty lines into pseudo-paragraphs.
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        chunk = 4 if len(lines) >= 16 else 3
        paras = []
        for k in range(0, len(lines), chunk):
            paras.append(_para("P%03d" % (len(paras) + 1), "Preamble", k + 1, lines[k:k + chunk]))
        notes.append("未检测到空行分段，已按每 %d 行聚合成候选段落" % chunk)

    if not heads:
        n = max(1, min(6, math.ceil(len(paras) / 3.0)))
        size = max(1, math.ceil(len(paras) / float(n)))
        for idx, p in enumerate(paras):
            p["section"] = "§" + chr(ord("A") + min(n - 1, idx // size))
        inferred = True
        notes.append("未检出标题，已按段落顺序生成临时章节 §A..，inferred_sections=true")

    body = " ".join(p["text"] for p in paras)
    roots = {}
    for h in heads:
        roots.setdefault(h["top"], h["name"])
    if inferred:
        roots = {}
        for p in paras:
            roots.setdefault(p["section"], p["section"])
    weights = []
    for root, name in roots.items():
        mine = [p for p in paras if top_of(p["section"]) == root]
        chars = sum(p["chars"] for p in mine)
        weights.append({"section": name, "top": root, "paragraphs": len(mine),
                        "chars": chars, "share": round(chars / max(len(body), 1), 3)})
    if not weights:
        weights = [{"section": "Preamble", "top": "preamble", "paragraphs": len(paras),
                    "chars": len(body), "share": 1.0}]

    claims = []
    for p in paras:
        for k, s in enumerate(SENT_RE.split(p["text"]), 1):
            min_len = 8 if re.search(r"[\u4e00-\u9fff]", s) else 40
            if len(s) >= min_len and CLAIM_RE.search(s):
                claims.append({"paragraph_id": p["paragraph_id"], "section": p["section"], "sentence_index": k,
                               "sentence": s[:320], "has_number": bool(NUM_RE.search(s)),
                               "has_citation": bool(CITE_RE.search(s))})
    # Quantitative result sentences are the core claims of a results/discussion chapter but
    # carry no "shows/表明" verb, so the argument map used to list only absolute sentences.
    seen = {(c["paragraph_id"], c["sentence_index"]) for c in claims}
    for p in paras:
        sec = (p.get("section") or "").lower()
        if not any(k in sec for k in ("结果", "讨论", "结论", "result", "discussion", "conclusion")):
            continue
        for k, s in enumerate(SENT_RE.split(p["text"]), 1):
            if (p["paragraph_id"], k) in seen or len(s) < 8:
                continue
            if NUM_RE.search(s) and RESULT_RE.search(s):
                claims.append({"paragraph_id": p["paragraph_id"], "section": p["section"],
                               "sentence_index": k, "sentence": s[:320], "has_number": True,
                               "has_citation": bool(CITE_RE.search(s))})
    claims = claims[:300]

    flags = []

    def flag(code, severity, message, **kw):
        flags.append(dict(code=code, severity=severity, message=message, **kw))

    for w in weights:
        low = (w["section"] or "").lower()
        if "reference" in low or "acknowledg" in low or "参考文献" in low or "致谢" in low:
            continue
        if w["share"] > 0.45 and len(weights) > 1:
            flag("weight_imbalance", "high", "单节占正文 %.0f%%，需核对是否挤压其他章节" % (w["share"] * 100),
                 section=w["section"])
    for key, label in (("引言", "引言"), ("方法", "方法"), ("结果", "结果"),
                       ("讨论", "讨论"), ("结论", "结论")):
        if inferred:
            break
        if not role_present([w["section"] for w in weights], key):
            flag("section_not_detected", "review", "未检出%s类章节（命名可能不同，需人工确认，不得直接判缺失）" % label,
                 section=label)
    if inferred:
        flag("section_inferred", "review", "未检出标题，章节为按段落顺序聚类推断，仅作段落级定位参考")
    for p in paras:
        ab = ABS_RE.findall(p["text"])
        if ab and not p["citations"]:
            flag("absolute_claim_no_citation", "medium", "断言含绝对化措辞 %s 且该段无引用标记" % ",".join(ab[:3]),
                 paragraph_id=p["paragraph_id"], section=p["section"])
        if p["chars"] >= 900 and p["claims"] >= 2:
            flag("long_multiclaim_paragraph", "low", "该段较长且含多个论断，需核对是否一段多主题",
                 paragraph_id=p["paragraph_id"], section=p["section"])
    return {"sections": heads, "weights": weights, "paragraphs": paras,
            "repetition_pairs": [], "claim_candidates": claims, "flags": flags,
            "inferred_sections": inferred, "notes": notes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", default="work")
    ap.add_argument("--file", default="", help="稿件文件名/路径子串；缺省取最大可读块")
    a = ap.parse_args()
    blocks = split_files(open(a.corpus, encoding="utf-8").read())
    if not blocks:
        report = {"file": None, "chars": 0, "sections": [], "weights": [], "paragraphs": [],
                  "repetition_pairs": [], "claim_candidates": [], "flags": [],
                  "inferred_sections": False, "notes": ["corpus 中没有任何 '===== FILE:' 文本块"]}
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "structure.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print("FAIL: corpus has no '===== FILE:' blocks; wrote empty structure.json")
        return 1
    readable = [b for b in blocks if not b[1].lstrip().startswith("[")]
    pool = readable or blocks
    if a.file:
        chosen = [b for b in pool if a.file in b[0]] or pool
        path, text = max(chosen, key=lambda b: len(b[1]))
    else:
        path, text = max(pool, key=lambda b: len(b[1]))
    report = analyze(text)
    report["file"] = path if path.startswith("case:") else os.path.basename(path)
    report["file_path"] = path
    report["chars"] = len(text)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "structure.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("file=%s sections=%d paragraphs=%d chars=%d flags=%d claims=%d inferred=%s"
          % (path, len(report["sections"]), len(report["paragraphs"]), len(text),
             len(report["flags"]), len(report["claim_candidates"]), report["inferred_sections"]))
    for f in report["flags"][:10]:
        print("  ~", f["code"], "|", f.get("section", ""), "|", f["message"][:70])
    return 0


if __name__ == "__main__":
    sys.exit(main())
