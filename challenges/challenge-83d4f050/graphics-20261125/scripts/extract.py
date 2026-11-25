#!/usr/bin/env python3
"""extract.py - conservative entity / relation extraction with source spans.

Rules that keep the biology honest:
  * structured nodes/edges in case.json are authoritative;
  * free text only yields an edge when one sentence names two entities AND an explicit
    polarity cue; an isolated verb never creates a mechanism;
  * duplicate / alias names are merged; a name seen with two types/compartments becomes
    a recorded conflict, never a silent overwrite;
  * entities without a compartment get a heuristic compartment marked `inferred`;
  * every node and edge carries a real quote + locator, or is marked unverified.

Output: work/spec.json  (nodes, edges, compartments, evidence, conflicts, isolated,
unresolved). Never fabricates an endpoint to make a pretty picture.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graphlib as G  # noqa: E402
import kernel  # noqa: E402

# entity-looking latin token: EGFR, EGF, PI3K, PTEN, AKT, mTOR, p53, BAX,
# IL-6, NF-kB, HIF-1α, ERK1/2, CD4, TGF-β
LATIN_TOKEN = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9\u0370-\u03ff]*(?:[-/][A-Za-z0-9\u0370-\u03ff]+)*"
    r"|[a-z]{1,2}[A-Z][A-Za-z0-9\u0370-\u03ff]*(?:[-/][A-Za-z0-9\u0370-\u03ff]+)*"
    r"|[a-z]{1,4}\d{1,4}[a-z]?|p\d{2,3})\b")
CJK_SUFFIX = ("受体", "蛋白", "激酶", "磷酸酶", "因子", "细胞", "通路", "复合物", "复合体",
              "配体", "酶", "基因", "分子", "离子", "通道", "整合素", "抗体", "代谢物",
              "细胞器", "转录因子", "生长因子")
CJK_TOKEN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9α-ωΑ-Ω\-]{2,18}(?:%s)" % "|".join(CJK_SUFFIX))
STOP_LATIN = {
    "THE", "AND", "WITH", "FROM", "THIS", "THAT", "FIG", "FIGURE", "TABLE", "SUPP",
    "DATA", "WAS", "WERE", "ARE", "HAS", "HAVE", "NOT", "BUT", "FOR", "ALL", "CAN",
    "MAY", "OUR", "THEIR", "THESE", "THOSE", "RESULTS", "METHODS", "DISCUSSION",
    "INTRODUCTION", "A", "AN", "IN", "ON", "OF", "TO", "BY", "AS", "AT", "OR", "IS",
    "IT", "WE", "MRNA", "DNA", "RNA", "PCR", "SD", "SEM", "NS", "WT", "KO", "OE",
    # table headers / ordinary prose words that are capitalised but are not symbols
    "ENTITY", "ENTITIES", "TYPE", "COMPARTMENT", "ALIAS", "NAME", "LABEL", "ID",
    "SOURCE", "TARGET", "RELATION", "KIND", "STATUS", "NOTE", "VALUE", "GENE",
    "PROTEIN", "COMPOUND", "CELL", "MEMBRANE", "CYTOPLASM", "NUCLEUS",
    "EXTRACELLULAR", "ROW", "LINE", "PAGE", "LAB", "SAFETY", "MEMO", "WEAR",
    "AUTOCLAVE", "NO", "YES", "UNKNOWN",
}
KNOWN_TITLECASE = {"Akt", "Erk", "Bax", "Myc", "Ras", "Fos", "Jun", "Src",
                   "Pten", "Egfr", "Foxo3", "Mtor", "Pi3k", "Nfkb"}
CJK_PREFIX_BAD = ("位于", "在", "结合", "激活", "抑制", "促进", "诱导", "转位", "并",
                  "且", "后", "被", "与", "和", "的", "其", "该", "这", "那", "可",
                  "能", "会", "使", "将", "已", "未", "不", "中", "内", "外", "是",
                  # instruction/prose openers that used to leak in as entities
                  "标明", "标注", "绘制", "生成", "输出", "保留", "提供", "根据",
                  "完成", "展示", "使用", "包括", "说明", "要求", "如图", "图中")
CJK_STOP = {"细胞膜", "细胞质", "细胞核", "细胞外", "细胞", "胞质", "胞核", "胞外"}
CUE_RE = re.compile(
    r"(activ|inhib|suppress|block|repress|downregulat|upregulat|promot|induc|enhanc|"
    r"phosphorylat|ubiquitin|methylat|acetyl|glycosylat|bind|bound|recruit|interact|"
    r"transport|import|export|secret|releas|endocyt|exocyt|translocat|convert|catalyz|"
    r"produce|driv|stimulat|trigger|attenuat|reduc|prevent|cleav|modif|"
    r"激活|抑制|促进|诱导|上调|下调|增强|削弱|阻断|阻遏|结合|募集|互作|相互作用|"
    r"磷酸化|泛素化|甲基化|乙酰化|糖基化|修饰|切割|剪切|转运|运输|输入|输出|分泌|"
    r"释放|内吞|外排|转位|入核|出核|转化为|产生|催化|驱动|催化)", re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?。！？；;])\s+|\n+")


def span(file, locator, quote, verified=True):
    return {"file": file, "locator": locator, "quote": quote[:320].strip(),
            "verified": bool(verified)}


def ref(span_obj):
    if not span_obj:
        return ""
    return "%s#%s" % (span_obj["file"], span_obj["locator"])


class Corpus:
    """Sentence-level index with file + line/page locators."""

    def __init__(self):
        self.spans = []
        self.docs = []

    def add(self, path, text):
        name = os.path.basename(path)
        ext = os.path.splitext(path)[1].lower()
        self.docs.append({"file": name, "path": path, "ext": ext, "chars": len(text)})
        if not text or text.startswith("["):
            return
        if ext == ".pdf" and "[[page " in text:
            for page_block in re.split(r"(?=\[\[page \d+\]\])", text):
                m = re.match(r"\[\[page (\d+)\]\]", page_block)
                page = int(m.group(1)) if m else 0
                body = re.sub(r"\[\[page \d+\]\]", "", page_block)
                for i, sent in enumerate(self._sentences(body)):
                    if len(sent.strip()) >= 8:
                        self.spans.append(span(name, "page %d / sentence %d" % (page, i + 1), sent))
        else:
            for lineno, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                if len(line) > 400:
                    for i, sent in enumerate(self._sentences(line)):
                        if len(sent.strip()) >= 8:
                            self.spans.append(span(name, "line %d / part %d" % (lineno, i + 1), sent))
                elif len(line.strip()) >= 8:
                    loc = ("row %d" % lineno) if ext in (".csv", ".tsv", ".xlsx") else ("line %d" % lineno)
                    self.spans.append(span(name, loc, line.strip()))

    @staticmethod
    def _sentences(text):
        return [s for s in SENT_SPLIT.split(text) if s and s.strip()]

    def find(self, label, near=None):
        if not label or not str(label).strip():
            return None
        needle = str(label).strip()
        lo = needle.lower()
        candidates = []
        for sp in self.spans:
            q = sp["quote"]
            ql = q.lower()
            if lo in ql:
                if len(needle) >= 3 and re.match(r"^[A-Za-z0-9-]+$", needle):
                    if not re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(lo), ql):
                        continue
                score = 0 if CUE_RE.search(q) else 1
                if near and near.lower() in ql:
                    score -= 1
                candidates.append((score, len(q), sp))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][2]

    def pair(self, a, b):
        for sp in self.spans:
            q = sp["quote"].lower()
            if str(a).lower() in q and str(b).lower() in q:
                return sp
        return None


# ------------------------------------------------------------------ structured input
def dig(case, *keys):
    for k in keys:
        if isinstance(case, dict) and isinstance(case.get(k), (list, dict)):
            return case[k]
    for holder in ("mechanism_graph", "graph", "mechanism", "result", "data"):
        inner = case.get(holder) if isinstance(case, dict) else None
        if isinstance(inner, dict):
            for k in keys:
                if isinstance(inner.get(k), (list, dict)):
                    return inner[k]
    return None


def norm_entity(raw, idx):
    if isinstance(raw, str):
        return {"label": raw.strip(), "id": "", "type": "", "compartment": "",
                "aliases": [], "evidence": "", "note": ""}
    if not isinstance(raw, dict):
        return None
    label = for_first(raw, ("label", "name", "term", "symbol", "text", "id", "entity"))
    if not label:
        return None
    aliases = raw.get("aliases") or raw.get("synonyms") or raw.get("alias") or []
    if isinstance(aliases, str):
        aliases = [x.strip() for x in re.split(r"[,;/]", aliases) if x.strip()]
    return {
        "label": str(label).strip(),
        "id": str(raw.get("id") or raw.get("uid") or "").strip(),
        "type": raw.get("type") or raw.get("entity_type") or raw.get("category") or "",
        "compartment": (raw.get("compartment") or raw.get("localization")
                        or raw.get("location") or raw.get("compartment_id") or ""),
        "aliases": [str(a).strip() for a in aliases if str(a).strip()],
        "evidence": raw.get("evidence") or raw.get("source") or raw.get("quote") or "",
        "note": raw.get("note") or raw.get("description") or "",
    }


def for_first(d, keys):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return ""


def norm_edge(raw):
    if not isinstance(raw, dict):
        return None
    src = for_first(raw, ("source", "from", "src", "subject", "head", "cause", "start"))
    tgt = for_first(raw, ("target", "to", "dst", "object", "tail", "effect", "end"))
    kind = for_first(raw, ("kind", "polarity", "type", "relation", "interaction", "effect",
                           "sign", "mode", "label"))
    return {
        "source": str(src).strip() if src not in (None, "") else "",
        "target": str(tgt).strip() if tgt not in (None, "") else "",
        "kind_raw": kind,
        "evidence": raw.get("evidence") or raw.get("source_quote") or raw.get("quote") or "",
        "note": raw.get("note") or raw.get("description") or "",
    }


# ------------------------------------------------------------------ text mining
def is_entity_token(tok):
    """True only for symbol-like tokens, never ordinary capitalised prose.

    Examples accepted: EGFR, EGF, PI3K, PTEN, AKT, mTOR, p53, BAX, HIF-1α.
    Rejected: Lab, Wear, Autoclave, The, Entity, Type (table headers/prose).
    """
    t = str(tok).strip(" \t.,;:()[]{}'\"")
    if len(t) < 2:
        return False
    if t.upper() in STOP_LATIN:
        return False
    if re.search(r"[\u4e00-\u9fff]", t):
        return t not in CJK_STOP and not t.startswith(CJK_PREFIX_BAD)
    if re.fullmatch(r"[A-Z][a-z]+", t):          # Titlecase prose word
        return t in KNOWN_TITLECASE
    if re.fullmatch(r"[A-Z]{2,12}", t):          # gene/protein symbol
        return True
    if re.search(r"\d", t):                      # PI3K, FOXO3, p53, HIF-1α
        return True
    if re.match(r"^[a-z]{1,2}[A-Z]", t):         # mTOR, mRNA (mRNA stoplisted)
        return True
    if re.search(r"[\u0370-\u03ff]", t):         # Greek-letter symbol
        return True
    return False


def latin_candidates(sentence):
    out = []
    for m in LATIN_TOKEN.finditer(sentence):
        # A slash-separated list ("EGFR/PI3K/AKT/mTOR") is several entities,
        # never one composite node.
        for tok in m.group(0).split("/"):
            if is_entity_token(tok):
                out.append(tok)
    return out


def cjk_candidates(sentence):
    return [m.group(0) for m in CJK_TOKEN.finditer(sentence) if is_entity_token(m.group(0))]


def find_mentions(text, nodes):
    """All known entity mentions in `text`, with char offsets, longest-first."""
    out = []
    for n in nodes:
        for name in [n["label"]] + n.get("aliases", []):
            if not name:
                continue
            if re.fullmatch(r"[A-Za-z0-9\u0370-\u03ff\-/]+", name):
                pat = r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(name)
            else:
                pat = re.escape(name)
            for m in re.finditer(pat, text, re.I):
                out.append({"id": n["id"], "label": n["label"],
                            "start": m.start(), "end": m.end()})
    out.sort(key=lambda m: (m["start"], -(m["end"] - m["start"])))
    kept = []
    for m in out:
        if any(x["id"] == m["id"] and x["start"] == m["start"] for x in kept):
            continue
        if any(not (m["end"] <= x["start"] or m["start"] >= x["end"]) for x in kept):
            continue
        kept.append(m)
    return sorted(kept, key=lambda m: m["start"])


def split_clauses(sentence):
    """Split on punctuation and the stated conjunctions 并/且/同时/以及/and, plus 后."""
    parts = re.split(r"[，,；;。.!?！？]|(?:\s+and\s+)|(?:并|且|同时|以及)|后",
                     sentence)
    return [p.strip() for p in parts if p and p.strip()]


COMPARTMENT_CUES = [
    ("细胞膜", "membrane"), ("质膜", "membrane"), ("plasma membrane", "membrane"),
    ("cell membrane", "membrane"), ("membrane", "membrane"),
    ("细胞质", "cytoplasm"), ("胞质", "cytoplasm"), ("胞浆", "cytoplasm"),
    ("cytoplasm", "cytoplasm"), ("cytosol", "cytoplasm"),
    ("细胞核", "nucleus"), ("核内", "nucleus"), ("nucleus", "nucleus"),
    ("nuclear", "nucleus"),
    ("细胞外", "extracellular"), ("胞外", "extracellular"),
    ("extracellular", "extracellular"), ("secreted", "extracellular"),
]
UNRESOLVED_RE = re.compile(
    r"未说明|未提及|不清楚|未知|无法判断|not specified|not determined|unclear|unknown",
    re.I)
TRANSLOC_RE = re.compile(r"转位|入核|出核|translocat|import|export", re.I)


def compartment_cue(clause):
    best = None
    for cue, comp in COMPARTMENT_CUES:
        for m in re.finditer(re.escape(cue), clause, re.I):
            item = (m.start(), -len(cue), comp, cue)
            if best is None or item < best:
                best = item
    return (best[2], best[0], best[3]) if best else None


def pick_subject_object(sentence, mentions):
    """Nearest mention before cue -> source, nearest after -> target; mark order."""
    cue = CUE_RE.search(sentence)
    if not cue:
        return None, None, "no_cue"
    before = [m for m in mentions if m["start"] < cue.start()]
    after = [m for m in mentions if m["start"] >= cue.end()]
    if before and after:
        return before[-1], after[0], "ordered"
    if len(mentions) >= 2:
        ordered = sorted(mentions, key=lambda m: m["start"])
        return ordered[0], ordered[1], "heuristic"
    return None, None, "incomplete"


def parse_text_relations(corpus, nodes):
    """Clause-level relation parser for active/passive Chinese and English.

    Handles:
      A 激活 B; A 抑制 B;
      A 结合 B 后激活 C   (A binds B; A -> C activation, B kept as ligand/binding)
      A 被 B 激活后...并激活 C (B -> A, A -> C)
      A 与 B 的关系未说明 (unresolved, no edge)
    """
    results, bindings, unresolved, loc_events = [], [], [], []
    intents, intent_seen = [], set()

    for sp in corpus.spans:
        sentence = sp["quote"]
        mentions = find_mentions(sentence, nodes)
        if not mentions:
            continue
        if UNRESOLVED_RE.search(sentence) and len(mentions) >= 2:
            unresolved.append({
                "source_text": mentions[0]["label"], "target_text": mentions[1]["label"],
                "file": sp["file"], "locator": sp["locator"], "quote": sentence,
                "reason": "relation explicitly not specified in materials; no edge drawn",
            })
            continue

        subject = mentions[0]
        sentence_results, sentence_bindings = [], []
        for clause in split_clauses(sentence):
            cmentions = find_mentions(clause, nodes)
            comp = compartment_cue(clause)
            cue = CUE_RE.search(clause)
            kind = G.norm_kind(clause) if cue else None

            if comp:
                pre = [m for m in cmentions if m["start"] < comp[1]]
                target = pre[-1] if pre else (cmentions[0] if cmentions else subject)
                if target:
                    loc_events.append({
                        "id": target["id"], "compartment": comp[0],
                        "translocation": bool(TRANSLOC_RE.search(clause)),
                        "file": sp["file"], "locator": sp["locator"], "quote": sentence,
                    })

            if not cue or not kind:
                if cmentions:
                    subject = cmentions[-1]
                continue

            sid = tid = None
            passive = ("被" in clause and len(cmentions) >= 2)
            english_passive = (re.search(r"\b(?:is|are|was|were)\s+\w+(?:ed|ted|ated)\s+by\b",
                                         clause, re.I) and len(cmentions) >= 2)
            if passive:
                bei = clause.index("被")
                before = [m for m in cmentions if m["start"] < bei]
                after = [m for m in cmentions if m["start"] >= bei + 1]
                if before and after:
                    sid, tid = after[0]["id"], before[-1]["id"]
                    subject = before[-1]
            elif english_passive:
                by = re.search(r"\bby\b", clause, re.I)
                before = [m for m in cmentions if m["start"] < cue.start()]
                after = [m for m in cmentions if by and m["start"] >= by.end()]
                if before and after:
                    sid, tid = after[0]["id"], before[-1]["id"]
                    subject = before[-1]
            else:
                before = [m for m in cmentions if m["end"] <= cue.start()]
                after = [m for m in cmentions if m["start"] >= cue.end()]
                src = before[-1] if before else subject
                tgt = after[0] if after else None
                if before:
                    subject = before[-1]
                if src:
                    sid = src["id"]
                if tgt:
                    tid = tgt["id"]

            if not sid or not tid or sid == tid:
                # a transport/localization clause has no second endpoint; it is an
                # annotation, not a missing relation.
                continue
            key = (sid, tid, kind)
            if key not in intent_seen:
                intent_seen.add(key)
                intents.append({"source": sid, "target": tid, "kind": kind,
                                "file": sp["file"], "locator": sp["locator"],
                                "quote": sentence})
            if kind == "binding":
                sentence_bindings.append((sid, tid, sp, clause))
            else:
                sentence_results.append(
                    (sid, tid, kind, sp, "text cue: %s" % clause.strip()[:60]))

        for sid, tid, bsp, clause in sentence_bindings:
            # "A binds B then activates C": keep B as the stated ligand/binding partner,
            # but do not draw a second arrow that would misrepresent the sentence.
            if any(r[0] == sid and r[2] != "binding" for r in sentence_results):
                bindings.append({"source": sid, "target": tid, "quote": bsp["quote"],
                                 "file": bsp["file"], "locator": bsp["locator"],
                                 "reason": "ligand-binding modifier of a stated relation"})
            else:
                sentence_results.append((sid, tid, "binding", bsp, "text cue: binding"))
        results.extend(sentence_results)

    return {"results": results, "bindings": bindings, "unresolved": unresolved,
            "loc_events": loc_events, "intents": intents}


def build():
    work = os.environ.get("MECH_WORK", "/app/work")
    work_case = json.load(open(os.path.join(work, "case.json"), encoding="utf-8"))
    case = {}
    if work_case.get("case_path") and os.path.exists(work_case["case_path"]):
        try:
            case = json.load(open(work_case["case_path"], encoding="utf-8"))
            if isinstance(case, list) and case and isinstance(case[0], dict):
                case = case[0]
        except Exception:  # noqa: BLE001
            case = {}

    corpus = Corpus()
    material_records = []
    for m in work_case.get("materials", []):
        p = m.get("path", "")
        if not os.path.isfile(p):
            material_records.append({"path": p, "exists": False, "chars": 0})
            continue
        text = kernel.extract_text(p)
        corpus.add(p, text)
        material_records.append({"path": p, "exists": True, "chars": len(text),
                                 "sha256": kernel.sha256_file(p)})
    # The work order / task text is instruction, not evidence: it must never create
    # entities or relations, and its sentences cannot be verified against materials.
    # (Previously it was added to the corpus, which produced pseudo-entities such as
    # "EGFR/PI3K/AKT/mTOR" or prose fragments and failed quote verification.)

    report = {"materials": material_records, "conflicts": [], "isolated_entities": [],
              "unresolved_edges": [], "uncertainty": [], "limits": [], "mode": "create"}

    # edit mode detection
    svgs = [m["path"] for m in work_case.get("materials", [])
            if str(m.get("path", "")).lower().endswith(".svg") and os.path.isfile(m["path"])]
    task = work_case.get("task_text", "")
    edit_words = ("edit", "modify", "change", "annotate", "highlight", "rename", "update",
                  "编辑", "修改", "改图", "标注", "高亮", "重命名")
    if svgs or str(case.get("mode", "")).lower() in ("edit", "modify") or \
            (task and any(w in task.lower() for w in edit_words)):
        report["mode"] = "edit"
        report["edit_source"] = svgs[0] if svgs else ""
        json.dump({"mode": "edit", "status": "edit", "materials": material_records,
                   "edit_source": report["edit_source"]},
                  open(os.path.join(work, "spec.json"), "w"), ensure_ascii=False, indent=1)
        print("extract: edit mode source=%r" % report["edit_source"])
        return 0

    raw_nodes = dig(case, "entities", "nodes", "entity_list") or []
    raw_edges = dig(case, "edges", "relations", "relations_list", "interactions") or []
    if isinstance(raw_nodes, dict):
        raw_nodes = raw_nodes.get("nodes") or raw_nodes.get("items") or []
    if isinstance(raw_edges, dict):
        raw_edges = raw_edges.get("edges") or raw_edges.get("items") or []

    nodes, by_key = [], {}
    alias_map = {}

    def add_node(ent, origin, idx):
        label = ent["label"]
        key = G.node_key(label)
        if not key:
            return None
        if key in by_key:
            n = by_key[key]
            for a in [label] + ent.get("aliases", []):
                if a and a != n["label"] and a not in n["aliases"]:
                    n["aliases"].append(a)
                    alias_map[G.node_key(a)] = n["id"]
            return n
        raw_type = ent.get("type")
        etype = G.norm_type(raw_type) if raw_type else G.heuristic_type(label)
        comp = G.norm_compartment(ent.get("compartment"))
        inferred_comp = False
        if not comp:
            comp = G.heuristic_compartment(label, etype)
            inferred_comp = True
        nid = ent.get("id") or G.slug(label)
        base, i = nid, 2
        while any(n["id"] == nid for n in nodes):
            nid = "%s-%d" % (base, i)
            i += 1
        n = {"id": nid, "label": label, "type": etype, "compartment": comp,
             "compartment_inferred": inferred_comp, "aliases": list(ent.get("aliases", [])),
             "evidence": [], "origin": origin, "data_ref": "nodes[%d]" % idx,
             "status": "stated", "note": ent.get("note", "")}
        nodes.append(n)
        by_key[key] = n
        for a in [label] + n["aliases"]:
            alias_map.setdefault(G.node_key(a), nid)
        return n

    for i, raw in enumerate(raw_nodes):
        ent = norm_entity(raw, i)
        if ent:
            add_node(ent, "structured", i)

    # ---------- entity inventory: every symbol-like token in every sentence.
    # Symbols mentioned without a relation are still entities (isolated/unresolved),
    # never silently dropped.
    # Merge "中文名（SYMBOL）" style aliases before inventorying, so the same entity
    # is not counted twice.
    # Pre-scan "中文名（SYMBOL）" pairs. The merge loop below can only attach
    # aliases to nodes that already exist; for text-only inputs no node exists
    # yet, so the pairs are also used when the inventory creates nodes.
    paren_canon, paren_label = {}, {}
    for sp in corpus.spans:
        for m in re.finditer(
                r"([\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9α-ωΑ-Ω\-]{1,30})\s*[（(]\s*"
                r"([A-Za-z][A-Za-z0-9\-α-ωΑ-Ω/]{1,20})\s*[）)]", sp["quote"]):
            cjk, latin = m.group(1), m.group(2)
            ck = G.node_key(latin)
            if not ck:
                continue
            paren_label.setdefault(ck, latin)
            paren_canon[G.node_key(cjk)] = ck
            paren_canon.setdefault(ck, ck)

    for sp in corpus.spans:
        for m in re.finditer(
                r"([\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9\-]{1,30})\s*[（(]\s*"
                r"([A-Za-z][A-Za-z0-9\-α-ωΑ-Ω/]{1,20})\s*[）)]", sp["quote"]):
            cjk, latin = m.group(1), m.group(2)
            nid = alias_map.get(G.node_key(latin)) or alias_map.get(G.node_key(cjk))
            n = next((x for x in nodes if x["id"] == nid), None)
            if not n:
                continue
            for alias in (cjk, latin):
                key = G.node_key(alias)
                if key and key not in alias_map:
                    n["aliases"].append(alias)
                    alias_map[key] = n["id"]

    inventory, inv_seen = [], {}
    for sp in corpus.spans:
        for tok in latin_candidates(sp["quote"]) + cjk_candidates(sp["quote"]):
            key = G.node_key(tok)
            if not key:
                continue
            if key in inv_seen:
                inv_seen[key]["count"] += 1
                continue
            inv_seen[key] = {"token": tok, "key": key, "count": 1, "span": sp}
    def resolve_known(k):
        """alias_map lookup, including the 中文名（SYMBOL） pairs and CJK prefixes."""
        if k in alias_map:
            return alias_map[k]
        ck = paren_canon.get(k)
        if ck and ck in alias_map:
            return alias_map[ck]
        for pk, pk_canon in paren_canon.items():
            if len(k) >= 3 and pk.startswith(k) and re.match(
                    r"^[\d\u0370-\u03ff]", pk[len(k):]):
                vid = alias_map.get(pk_canon)
                if vid:
                    return vid
        return None

    for key, hit in inv_seen.items():
        nid = resolve_known(key)
        if not nid and re.search(r"[\u4e00-\u9fff]", hit["token"]):
            # a CJK prefix of an isoform alias, e.g. 缺氧诱导因子 -> 缺氧诱导因子1α
            for k, vid in alias_map.items():
                if len(key) >= 3 and k.startswith(key) and re.match(
                        r"^[\d\u0370-\u03ff]", k[len(key):]):
                    nid = vid
                    break
        if nid:
            n = next((x for x in nodes if x["id"] == nid), None)
            if n and hit["token"] not in n["aliases"] and G.node_key(hit["token"]) != G.node_key(n["label"]):
                n["aliases"].append(hit["token"])
                alias_map[key] = nid
        if not nid:
            ck = paren_canon.get(key)
            label = (paren_label.get(ck) if ck else None) or hit["token"]
            aliases = [hit["token"]] if label != hit["token"] else []
            ent = {"label": label, "id": "", "type": "", "compartment": "",
                   "aliases": aliases}
            n = add_node(ent, "text", len(nodes))
            if n:
                n["evidence"].append(hit["span"])
                nid = n["id"]
                alias_map[key] = nid
                if ck:
                    alias_map.setdefault(ck, nid)
        inventory.append({"token": hit["token"], "key": key, "node_id": nid,
                          "count": hit["count"]})
    report["token_inventory"] = inventory

    # ---------- text relations (only when case.json has no authoritative edge list)
    edges, edge_seen = [], set()

    def edge_key(s, t, k):
        return (s, t, k)

    def add_edge(sid, tid, kind, evidence, status, note=""):
        if not sid or not tid or sid == tid or not kind:
            return False
        k = edge_key(sid, tid, kind)
        if k in edge_seen:
            return False
        edge_seen.add(k)
        eid = "e%d" % (len(edges) + 1)
        e = {"id": eid, "source": sid, "target": tid, "kind": kind, "status": status,
             "evidence": [evidence] if evidence else [], "label": G.KINDS[kind][4],
             "note": note, "data_ref": "edges[%d]" % len(edges)}
        edges.append(e)
        return True

    parsed = {"results": [], "bindings": [], "unresolved": [], "loc_events": [],
              "intents": []}
    if not raw_edges:
        parsed = parse_text_relations(corpus, nodes)
        for sid, tid, kind, sp, note in parsed["results"]:
            add_edge(sid, tid, kind, sp, "stated", note=note)
        report["unresolved_edges"].extend(parsed["unresolved"])

    # explicit localization / translocation from the prose
    for ev in parsed["loc_events"]:
        n = next((x for x in nodes if x["id"] == ev["id"]), None)
        if not n:
            continue
        old = n["compartment"]
        n["compartment"] = ev["compartment"]
        n["compartment_inferred"] = False
        n.setdefault("localization_quote", ev)
        if not any(x.get("quote") == ev["quote"] for x in n.get("evidence", [])):
            n["evidence"].insert(0, ev)
        if ev["translocation"]:
            n["translocation"] = "%s -> %s" % (old, ev["compartment"])
            n["note"] = (n.get("note") or "").strip()
            n["note"] += (" " if n["note"] else "") + (
                "translocation stated: %s -> %s" % (old, ev["compartment"]))
    for b in parsed["bindings"]:
        src = next((x for x in nodes if x["id"] == b["source"]), None)
        tgt = next((x for x in nodes if x["id"] == b["target"]), None)
        if src and tgt:
            if (src["compartment"] == "membrane" and tgt.get("compartment_inferred")
                    and tgt["compartment"] == "extracellular"):
                tgt["compartment"] = "membrane"
                tgt["compartment_inferred"] = False
                tgt["note"] = "ligand bound by %s at the membrane" % src["label"]
            src["note"] = (src.get("note") or "").strip()
            src["note"] += (" " if src["note"] else "") + ("binds %s" % tgt["label"])
            if not tgt.get("note"):
                tgt["note"] = "ligand/binding partner of %s" % src["label"]
    report["binding_annotations"] = parsed["bindings"]

    # ---------- structured edges
    for i, raw in enumerate(raw_edges):
        e = norm_edge(raw)
        if not e:
            continue
        sid = alias_map.get(G.node_key(e["source"]))
        tid = alias_map.get(G.node_key(e["target"]))
        kind = G.norm_kind(e["kind_raw"])
        if not sid or not tid:
            report["unresolved_edges"].append(
                {"source_text": e["source"], "target_text": e["target"],
                 "kind_raw": str(e["kind_raw"]), "data_ref": "edges[%d]" % i,
                 "reason": "endpoint not found among extracted entities"})
            continue
        if not kind:
            report["unresolved_edges"].append(
                {"source_text": e["source"], "target_text": e["target"],
                 "kind_raw": str(e["kind_raw"]), "data_ref": "edges[%d]" % i,
                 "reason": "polarity cue absent/ambiguous; not drawn as a mechanism"})
            continue
        ev = None
        status = "stated"
        if e["evidence"]:
            sp = corpus.pair(e["source"], e["target"]) or corpus.find(str(e["evidence"]), e["target"])
            if sp:
                ev = sp
            else:
                ev = span("case.json", "edges[%d]" % i, str(e["evidence"]), verified=False)
                status = "inferred"
        else:
            ev = corpus.pair(_label(nodes, sid), _label(nodes, tid))
        if ev is None:
            # no prose sentence names both endpoints: cite the structured relation itself,
            # keep the edge but mark it inferred (never pretend the materials said it)
            ev = span(os.path.basename(work_case.get("case_path", "") or "case.json"),
                      "relations[%d]" % i, json.dumps(raw, ensure_ascii=False), verified=True)
            status = "inferred"
        add_edge(sid, tid, kind, ev, status,
                 note=("structured relation" if status == "stated"
                       else "structured relation without a verbatim prose sentence"))

    # ---------- evidence for every node
    for n in nodes:
        if not n["evidence"]:
            sp = None
            for name in [n["label"]] + n["aliases"]:
                sp = corpus.find(name)
                if sp:
                    break
            if sp:
                n["evidence"].append(sp)
            elif n.get("origin") == "structured":
                n["status"] = "inferred"
                n["evidence"].append(span("case.json", n["data_ref"], "", verified=False))
        if n["compartment_inferred"]:
            n["note"] = (n.get("note") or "").strip()
            n["note"] += (" " if n["note"] else "") + "compartment inferred from name/type"

    # ---------- conflicts (same name, divergent type/compartment)
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            if a["label"].lower() == b["label"].lower() and (
                    a["type"] != b["type"] or a["compartment"] != b["compartment"]):
                report["conflicts"].append(
                    "%s: type %s vs %s, compartment %s vs %s" % (
                        a["label"], a["type"], b["type"], a["compartment"], b["compartment"]))
    # divergent material evidence labelled the same in text is not treated as a
    # conflict: a sentence may co-mention an entity and an unrelated compartment.
    # Only structured duplicates with divergent type/compartment above are conflicts.

    # ---------- isolated entities
    deg = {n["id"]: 0 for n in nodes}
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    binding_ids = set()
    for b in parsed["bindings"]:
        binding_ids.add(b["source"])
        binding_ids.add(b["target"])
    report["isolated_entities"] = [n["label"] for n in nodes
                                   if deg.get(n["id"], 0) == 0 and n["id"] not in binding_ids]

    # ---------- coverage / uncertainty
    for n in nodes:
        if n["compartment_inferred"]:
            report["uncertainty"].append(
                "%s (%s): compartment inferred as %s; no explicit localization in materials."
                % (n["label"], n["type"], n["compartment"]))
        if n["status"] == "inferred":
            report["uncertainty"].append(
                "%s: no verbatim quote found; shown as inferred." % n["label"])
    for e in edges:
        if e["status"] != "stated":
            report["uncertainty"].append(
                "%s %s %s: %s; arrow drawn but polarity/direction not directly quoted."
                % (_label(nodes, e["source"]), e["kind"], _label(nodes, e["target"]),
                   e["status"]))
        if not e["evidence"]:
            report["uncertainty"].append(
                "edge %s (%s->%s) has no source quote." % (e["id"], e["source"], e["target"]))
    if report["isolated_entities"]:
        report["uncertainty"].append(
            "isolated entities (no extracted relation): " + ", ".join(report["isolated_entities"]))
    if report["unresolved_edges"]:
        report["uncertainty"].append(
            "%d relation(s) left unresolved and not drawn (see unresolved_edges)."
            % len(report["unresolved_edges"]))
    if not nodes:
        report["uncertainty"].append(
            "No entity could be extracted from case.json or materials; figure withheld.")
    if not edges and nodes:
        report["uncertainty"].append(
            "Entities found but no polarity relation passed the evidence test; figure withheld.")
    for m in material_records:
        if m.get("exists") and m.get("chars", 0) < 40:
            report["limits"].append(
                "%s yielded almost no text (%s chars); visual/manual reading may be needed."
                % (os.path.basename(m["path"]), m.get("chars")))

    # ---------- hard-gate metrics (check.py turns these into FAIL/blocked)
    inv = report.get("token_inventory", [])
    node_ids = {n["id"] for n in nodes}
    matched = sum(1 for t in inv if t.get("node_id") in node_ids)
    report["token_recall"] = round(matched / float(len(inv)), 3) if inv else 1.0
    accounted = {(e["source"], e["target"], e["kind"]) for e in edges}
    accounted |= {(b["source"], b["target"], "binding") for b in parsed["bindings"]}
    report["missing_relations"] = [
        it for it in parsed["intents"]
        if (it["source"], it["target"], it["kind"]) not in accounted]
    report["edge_endpoint_errors"] = [
        {"edge": e["id"], "source": e["source"], "target": e["target"]}
        for e in edges if e["source"] not in node_ids or e["target"] not in node_ids]
    if report["token_recall"] < 0.8:
        report["uncertainty"].append(
            "entity mention recall %.1f%% is below the 80%% hard gate." %
            (100.0 * report["token_recall"]))
    if report["missing_relations"]:
        report["uncertainty"].append(
            "%d stated relation(s) could not be drawn." % len(report["missing_relations"]))

    spec = {
        "mode": "create", "case_id": work_case.get("case_id"),
        "nodes": nodes, "edges": edges,
        "compartments": [{"id": c, "label": lbl, "order": G.CANON_ORDER[c]}
                         for c, lbl in G.COMPARTMENTS],
        "conflicts": report["conflicts"],
        "isolated_entities": report["isolated_entities"],
        "unresolved_edges": report["unresolved_edges"],
        "uncertainty": report["uncertainty"],
        "limits": report["limits"],
        "materials": material_records,
        "token_inventory": report.get("token_inventory", []),
        "token_recall": report["token_recall"],
        "missing_relations": report["missing_relations"],
        "edge_endpoint_errors": report["edge_endpoint_errors"],
        "binding_annotations": report.get("binding_annotations", []),
    }
    json.dump(spec, open(os.path.join(work, "spec.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("extract: nodes=%d edges=%d conflicts=%d isolated=%d unresolved=%d"
          % (len(nodes), len(edges), len(report["conflicts"]),
             len(report["isolated_entities"]), len(report["unresolved_edges"])))
    return 0


def _label(nodes, nid):
    for n in nodes:
        if n["id"] == nid:
            return n["label"]
    return nid


if __name__ == "__main__":
    sys.exit(build())
