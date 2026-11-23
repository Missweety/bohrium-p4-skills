"""graphlib.py - mechanism-diagram vocabulary, text metrics and deterministic layout.

Stdlib only. The vocabulary is shared by extraction, rendering and self-check so the
figure, the legend and the machine-readable graph never disagree.

Semantics encoded here:
  entity type      gene / protein / complex / receptor / compound / organelle / cell /
                   metabolite / process / other
  compartment      extracellular -> membrane -> cytoplasm -> nucleus
  edge polarity    activation / inhibition / binding / modification (+ transport / flow)
Each polarity has its own colour, line dash and arrow-head marker.
"""
import math

# ------------------------------------------------------------------ palette
OKABE_ITO = ["#0072B2", "#E69F00", "#009E73", "#D55E00",
             "#CC79A7", "#56B4E9", "#F0E442", "#000000"]
VIRIDIS = ["#440154", "#482878", "#3E4989", "#31688E", "#26828E",
           "#1F9E89", "#35B779", "#6DCD59", "#B4DE2C", "#FDE725"]
NEUTRAL = {
    "text": "#111827", "muted": "#6B7280", "stroke": "#CBD5E1",
    "panel": "#F7F9FC", "band": "#EEF2F7", "membrane": "#E3EDF6",
    "white": "#FFFFFF", "conflict": "#D55E00",
    "ink2": "#374151", "ink3": "#4B5563", "ink4": "#9CA3AF",
    "rule": "#E2E8F0", "rule2": "#E5E7EB", "panel2": "#F9FAFB",
    "edit": "#7C4A00",
}
ALLOWED_COLORS = set(c.lower() for c in OKABE_ITO + VIRIDIS + list(NEUTRAL.values()))
ALLOWED_COLORS.add("#B26B00")  # inferred / unresolved emphasis (kept as an explicit exception)

# ------------------------------------------------------------------ entity types
# id -> (stroke colour, shape, bilingual label)
TYPES = {
    "gene": ("#0072B2", "rect", "基因 / gene"),
    "protein": ("#009E73", "rounded", "蛋白 / protein"),
    "complex": ("#CC79A7", "ellipse", "复合物 / complex"),
    "receptor": ("#56B4E9", "rounded", "受体 / receptor"),
    "compound": ("#E69F00", "hexagon", "化合物 / compound"),
    "organelle": ("#D55E00", "ellipse", "细胞器 / organelle"),
    "cell": ("#F0E442", "rounded", "细胞 / cell"),
    "metabolite": ("#56B4E9", "hexagon", "代谢物 / metabolite"),
    "process": ("#000000", "rounded", "过程 / process"),
    "other": ("#6B7280", "rounded", "其它 / other"),
}
TYPE_ALIASES = {
    "gene": ["gene", "基因", "dna", "promoter", "启动子", "transcript", "转录本"],
    "protein": ["protein", "蛋白", "enzyme", "酶", "kinase", "激酶", "phosphatase",
                "磷酸酶", "peptide", "多肽"],
    "complex": ["complex", "复合物", "复合体", "dimer", "二聚体", "heterodimer", "trimer"],
    "receptor": ["receptor", "受体", "gpcr", "channel", "通道", "integrin", "整合素",
                 "transporter", "转运体"],
    "compound": ["compound", "化合物", "chemical", "小分子", "drug", "药物", "inhibitor",
                 "抑制剂", "agonist", "拮抗剂", "antagonist", "ligand", "配体"],
    "organelle": ["organelle", "细胞器", "mitochond", "线粒体", "endoplasmic", "内质网",
                  "golgi", "高尔基", "lysosome", "溶酶体", "nucleus", "细胞核", "ribosome"],
    "cell": ["cell", "细胞", "t cell", "b cell", "macrophage", "巨噬细胞", "neutrophil",
             "中性粒细胞", "fibroblast", "成纤维细胞", "epithelial", "上皮细胞"],
    "metabolite": ["metabolite", "代谢物", "atp", "adp", "amp", "camp", "cgmp", "ros",
                   "ca2+", "钙离子", "离子", "ion", "glucose", "葡萄糖", "lactate", "乳酸"],
    "process": ["process", "过程", "pathway", "通路", "cascade", "级联", "apoptosis",
                "凋亡", "autophagy", "自噬", "cell cycle", "细胞周期"],
}

# ------------------------------------------------------------------ compartments
COMPARTMENTS = [
    ("extracellular", "细胞外 / Extracellular"),
    ("membrane", "细胞膜 / Membrane"),
    ("cytoplasm", "胞质 / Cytoplasm"),
    ("nucleus", "核内 / Nucleus"),
]
CANON_LABEL = dict(COMPARTMENTS)
CANON_ORDER = {k: i for i, (k, _) in enumerate(COMPARTMENTS)}
COMPARTMENT_ALIASES = {
    "extracellular": ["extracellular", "extracellular space", "outside", "extracellular region",
                      "细胞外", "胞外", "细胞间隙", "培养液", "血浆", "serum", "plasma"],
    "membrane": ["membrane", "plasma membrane", "cell membrane", "plasma-membrane",
                 "细胞膜", "质膜", "膜", "跨膜", "transmembrane", "surface"],
    "cytoplasm": ["cytoplasm", "cytoplasmic", "cytosol", "cytosolic", "intracellular",
                  "胞内", "细胞内", "细胞质", "胞质", "胞浆"],
    "nucleus": ["nucleus", "nuclear", "nucleoplasm", "核内", "细胞核", "核质", "核"],
}

# ------------------------------------------------------------------ edge polarity
# kind -> (colour, marker kind, dash pattern, bilingual legend label, short label)
KINDS = {
    "activation": ("#0072B2", "arrow", "", "激活 / activation (filled arrow)", "激活"),
    "inhibition": ("#D55E00", "bar", "", "抑制 / inhibition (T-shaped end)", "抑制"),
    "binding": ("#009E73", "circle", "", "结合/募集 / binding (circle end)", "结合/募集"),
    "modification": ("#CC79A7", "diamond", "7 5", "修饰 / modification (dashed + diamond)", "修饰"),
    "transport": ("#56B4E9", "chevron", "12 5 3 5", "转运 / transport (dash-dot chevron)", "转运"),
    "flow": ("#000000", "open", "", "流向 / flow (open arrow)", "流向"),
}
KIND_ORDER = ["activation", "inhibition", "binding", "modification", "transport", "flow"]
KIND_ALIASES = {
    "activation": ["activ", "promot", "induc", "upregulat", "up-regulat", "enhanc", "driv",
                   "stimulat", "trigger", "activate", "激活", "促进", "诱导", "上调", "活化",
                   "增强", "驱动", "启动"],
    "inhibition": ["inhibit", "suppress", "block", "repress", "downregulat", "down-regulat",
                   "reduce", "attenuat", "prevent", "抑制", "阻断", "阻遏", "下调", "削弱",
                   "减弱", "抑制性"],
    "binding": ["bind", "bound", "recruit", "interact", "associat", "co-local", "colocal",
                "complex with", "结合", "募集", "互作", "相互作用", "结合于", "锚定"],
    "modification": ["phosphorylat", "ubiquitin", "methylat", "acetylatin", "acetyl", "glycosylat",
                     "sumoylat", "cleav", "modif", "磷酸化", "泛素化", "甲基化", "乙酰化",
                     "糖基化", "修饰", "切割", "剪切"],
    "transport": ["transport", "import", "export", "secret", "releas", "endocyt", "exocyt",
                  "translocat", "转运", "运输", "输入", "输出", "分泌", "释放", "内吞",
                  "外排", "转位", "入核", "出核"],
    "flow": ["flow", "convert", "catalyz", "produce", "generat", "signal", "传递", "流向",
             "转化为", "产生", "催化", "下游", "进入", "传至"],
}
STATUS_LABELS = {"stated": "材料明确 / stated", "inferred": "推断 / inferred (dashed)",
                 "unresolved": "未解决 / unresolved"}


# ------------------------------------------------------------------ normalisation
def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def norm_kind(raw):
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in KINDS:
        return s
    for kind in ("inhibition", "modification", "transport", "binding", "activation", "flow"):
        if any(cue in s for cue in KIND_ALIASES[kind]):
            return kind
    return None


def norm_type(raw):
    if not raw:
        return "other"
    s = str(raw).strip().lower()
    if s in TYPES:
        return s
    for canon in ("receptor", "complex", "organelle", "metabolite", "compound",
                  "gene", "cell", "protein", "process"):
        if any(a == s or a in s for a in TYPE_ALIASES[canon]):
            return canon
    return "other"


def norm_compartment(raw):
    if not raw:
        return None
    s = str(raw).strip().lower()
    for canon, aliases in COMPARTMENT_ALIASES.items():
        if s == canon or any(a in s for a in aliases):
            return canon
    return None


def heuristic_compartment(label, etype="other"):
    s = str(label).lower()
    if etype == "receptor" or any(k in s for k in (
            "receptor", "受体", "channel", "通道", "gpcr", "integrin", "整合素",
            "cd44", "egfr", "her2", "tcr", "mhc", "膜蛋白")):
        return "membrane"
    if any(k in s for k in ("nf-κb", "nf-kb", "p53", "stat", "hif", "tf", "转录因子",
                            "nuclear", "核内", "细胞核", "foxo", "β-catenin", "smad")):
        return "nucleus"
    if any(k in s for k in ("il-", "il1", "il6", "tnf", "tgf", "egf", "vegf", "ligand",
                            "配体", "分泌", "血浆", "serum", "extracellular", "细胞外")):
        return "extracellular"
    return "cytoplasm"


def heuristic_type(label):
    """Best-effort type for names found only in prose. Defaults to protein, which is the
    dominant mechanism entity, rather than the uninformative 'other'."""
    s = str(label).lower()
    if any(k in s for k in ("receptor", "受体", "egfr", "her2", "tcr", "cd4", "cd28",
                            "integrin", "整合素", "gpcr", "tlr", "notch", "通道", "channel")):
        return "receptor"
    if any(k in s for k in ("complex", "复合物", "复合体", "dimer", "二聚体")):
        return "complex"
    if any(k in s for k in ("mitochond", "线粒体", "endoplasmic", "内质网", "golgi",
                            "高尔基", "lysosome", "溶酶体", "ribosome", "核糖体")):
        return "organelle"
    if any(k in s for k in ("细胞", "t cell", "b cell", "macrophage", "巨噬细胞",
                            "neutrophil", "fibroblast")):
        return "cell"
    if any(k in s for k in ("compound", "化合物", "drug", "药物", "inhibitor", "抑制剂",
                            "atp", "camp", "cgmp", "ros", "glucose", "葡萄糖", "lactate")):
        return "compound"
    if any(k in s for k in ("gene", "基因", "mrna", "lncrna", "mir-", "promoter", "启动子")):
        return "gene"
    if any(k in s for k in ("pathway", "通路", "cascade", "级联", "apoptosis", "凋亡",
                            "autophagy", "自噬", "process", "过程")):
        return "process"
    return "protein"


def slug(text):
    s = str(text).strip().lower()
    s = "".join(c if (c.isalnum() or c in "-_") else "-" for c in s)
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-") or "n"


def node_key(label):
    return "".join(ch for ch in str(label).strip().casefold() if ch.isalnum() or ch in "+-_")


def sha1_text(text):
    import hashlib
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ text metrics
def tw(s, px, bold=False):
    """Heuristic width: CJK = 1 em, latin = 0.55 em."""
    w = sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in str(s)) * px
    return w * (1.04 if bold else 1.0)


def wrap(text, maxw, px):
    tokens, buf = [], ""
    for ch in str(text):
        if ord(ch) > 0x2E80 or ch in "，。；：（）、“”《》·":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        elif ch.isspace():
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(" ")
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    out, cur = [], ""
    for tok in tokens:
        if tok == " ":
            if cur:
                cur += " "
            continue
        if tw(cur + tok, px) <= maxw:
            cur += tok
            continue
        if cur.strip():
            out.append(cur.rstrip())
        if tw(tok, px) > maxw:
            part = ""
            for ch in tok:
                if tw(part + ch, px) <= maxw:
                    part += ch
                else:
                    out.append(part)
                    part = ch
            cur = part
        else:
            cur = tok
    if cur.strip():
        out.append(cur.rstrip())
    return out or [""]


# ------------------------------------------------------------------ geometry
def bx(o):
    return float(o["x"]), float(o["y"]), float(o["w"]), float(o["h"])


def centre(o):
    x, y, w, h = bx(o)
    return x + w / 2.0, y + h / 2.0


def anchor(n, tx, ty):
    """Point on the border of n in the direction of (tx, ty)."""
    cx, cy = centre(n)
    x, y, w, h = bx(n)
    dx, dy = tx - cx, ty - cy
    if not (dx or dy):
        return cx, cy
    shape = n.get("shape") or TYPES.get(n.get("type"), ("", "rounded"))[1]
    if shape in ("ellipse", "cell", "organelle"):
        t = 1.0 / math.hypot(dx / (w / 2.0), dy / (h / 2.0))
    else:
        t = min((w / 2.0) / abs(dx) if dx else 1e9, (h / 2.0) / abs(dy) if dy else 1e9)
    return cx + dx * t, cy + dy * t


def intersects(a, b):
    ax, ay, aw, ah = bx(a)
    bx0, by, bw, bh = bx(b)
    w = min(ax + aw, bx0 + bw) - max(ax, bx0)
    h = min(ay + ah, by + bh) - max(ay, by)
    return w > 0 and h > 0


def inside(outer, inner, pad=0):
    ox, oy, ow, oh = bx(outer)
    ix, iy, iw, ih = bx(inner)
    return (ix >= ox - pad and iy >= oy - pad
            and ix + iw <= ox + ow + pad and iy + ih <= oy + oh + pad)
