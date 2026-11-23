#!/usr/bin/env python3
"""route_extract.py - 从 case.json 或材料文本抽取装置部件/连线/阶段，生成可编辑规格。

用法：
  python scripts/route_extract.py --case /input/case.json --materials /input --out work

优先使用结构化字段（parts/connections/stages）；字段缺失、类型不符或为空时自动回退到
材料文本抽取（第二遍扫描补连线与阶段），不因单个字段缺省而产出空图。
只把带明确设备名词与流向动词的 A→B 作为 inferred 候选，交执行者逐条核对；
不补材料里没有的部件、接口或步骤；不判断实验方案的科学性。
"""
import argparse
import json
import math
import os
import re
import sys

import routelib as r

try:
    import kernel as K
except Exception:  # noqa: BLE001
    K = None

ALIASES = {
    "case_id": ["case_id", "id", "caseId", "task_id"],
    "title": ["title", "figure_title", "name"],
    "parts": ["parts", "components", "modules", "apparatus", "equipment", "devices"],
    "connections": ["connections", "links", "pipes", "tubing", "flows", "connectors"],
    "stages": ["stages", "phases", "milestones", "steps", "workflow", "procedure"],
    "units": ["units", "measurement_units", "unit_map"],
    "scale_bar": ["scale_bar", "scalebar"],
    "caption": ["caption", "figure_caption", "notes_text"],
    "figure": ["figure", "canvas", "layout"],
    "output_contract": ["output_contract", "outputContract", "expected_output", "schema"],
}

TEXT_EXT = {".md", ".txt", ".csv", ".tsv", ".tex", ".rst"}
FOOTER_H = 260.0  # route_svg 中 units/notes/scale/caption 占用的底部固定高度

# 装置名词后缀（长后缀优先，避免 "器" 吞掉 "检测器"）
PART_SUFFIX = ("质量流量控制器|流量控制器|流量计|压力表|温度计|热电偶|控制器|检测器|传感器|"
               "反应器|反应釜|分离器|冷凝器|预热器|混合器|过滤器|干燥器|换热器|搅拌器|"
               "色谱柱|层析柱|分离柱|填充柱|电解槽|储液罐|储气罐|储罐|"
               "收集瓶|试剂瓶|缓冲瓶|废液瓶|洗气瓶|钢瓶|气瓶|烧瓶|烧杯|坩埚|量筒|"
               "离心机|注射泵|蠕动泵|真空泵|高压泵|计量泵|平流泵|螺杆泵|"
               "背压阀|减压阀|球阀|针阀|电磁阀|止回阀|三通阀|截止阀|"
               "空冷器|加热炉|管式炉|恒温槽|水浴|冷阱|膜组件|超滤膜|纳滤膜|"
               "紫外灯|激光器|电源|分析仪|光谱仪|质谱仪|工作站|记录仪|"
               "电极|探头|管路|管道|软管|三通|接口|取样口|支架|夹具|底座|"
               "泵|阀|罐|瓶|柱|塔|炉|管|槽|器|机|仪|计|表|膜|釜")
PAT_ZH_PART = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9\-（）()]{0,14}(?:%s))" % PART_SUFFIX)
PAT_EN_PART = re.compile(r"\b([A-Za-z][A-Za-z0-9\-]{1,20}(?:\s[A-Za-z][A-Za-z0-9\-]{1,20})?)\s?"
                         r"(?:pump|valve|reactor|column|detector|sensor|flask|beaker|reservoir|tank|"
                         r"separator|controller|meter|furnace|condenser|preheater|mixer|"
                         r"mass flow controller|mfc)\b", re.I)
ARROWS = re.compile(r"\s*(?:→|->|—>|–>|=>|⇒|⟶|➔|➜|＞|-->)\s*")
ZH_VERBS = r"(?:送入|送至|进入|流入|导入|泵入|通入|接入|连接到|连接至|连至|汇入|排入|收集至|输送至|流入|流经|经过|送往)"
PAT_ZH_SIMPLE = re.compile(r"([^，。；;,\s：:、]{1,18})\s*%s\s*([^，。；;,\s。]{1,18})" % ZH_VERBS)
PAT_ZH_VIA = re.compile(r"([^，。；;,\s：:]{1,18})\s*(?:经|通过|由)\s*([^，。；;,\s：:]{1,18})\s*"
                        r"(?:送入|进入|流入|导入|泵入|通入|接入|连接到|连接至|汇合|混合|放空|外排|排出|"
                        r"降温|冷却|加热|预热|换热|增压|减压|稳压|计量)")
PAT_ZH_MERGE = re.compile(r"([^，。；;,\s：:]{1,18})\s*(?:与|和|同)\s*([^，。；;,\s：:]{1,18})\s*"
                          r"(?:汇合|混合|合并)")
PAT_EN_FLOW = re.compile(r"\b([A-Za-z][A-Za-z0-9\-]{1,20})\b\s+"
                         r"(?:flows?\s+into|is\s+connected\s+to|feeds?|passes?\s+to|goes?\s+to|"
                         r"transfers?\s+to|enters)\s+\b([A-Za-z][A-Za-z0-9\-]{1,20})\b", re.I)
PAT_STEP = re.compile(r"^\s*(?:步骤|阶段|第)?\s*([0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*"
                      r"(?:步|阶段|章|节)?\s*[：:、.)\-—]?\s*(.{4,200})$")
PAT_STEP_INLINE = re.compile(r"(?:步骤|阶段|Step|Stage)\s*([0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*"
                             r"[：:、.)\-—]?\s*(.{4,120})", re.I)
LIST_ITEM = re.compile(r"^\s*(?:[-*•·▪]|\(?\d{1,2}[.)、]|[（(]\d{1,2}[）)])\s*(.{2,80})$")
PARAMS = re.compile(r"[（(]([^）)]{1,60})[）)]")
STOP_PREFIX = re.compile(r"^(?:装置由|系统由|设备由|装置|系统|设备|包括|包含|分别为|组成|在线|"
                         r"将|把|向|从|由|经|与|和|及|对|在|先|再|然后|随后|其中|其|该|本|此|"
                         r"打开|关闭|启动|开启|调节|加入|注入|装填|连接|安装|进入|流经|经过|通过|"
                         r"的|并|后|后经|后进入)")
NUM_ZH = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
BRANCH = re.compile(r"(气相|液相|有机相|水相|尾气|废液|废气|废料)")
ABSENCE_RE = re.compile(r"(未给出|未提供|未标注|未说明|未确定|不详|待定|未知|"
                        r"not specified|unspecified|unknown)", re.I)
MERGE_HINT = re.compile(r"(汇合|混合|合并|并入)")
NOT_PART = re.compile(r"^(?:温度|压力|流量|时间|体积|浓度|质量|转速|功率|电流|电压|单位|参数|"
                      r"实验|方法|结果|步骤|阶段|目标|说明|备注|序号|名称)$")
# 供料/权威方向："反应器顶部连接氢气钢瓶，经减压阀与质量流量计"
# 语义是 钢瓶→减压阀→质量流量计→反应器，而不是 反应器→钢瓶。
FEED_TOP = re.compile(r"(?:顶部|上部|入口|进口|顶端)\s*连接")
FEED_SRC = re.compile(r"(?:氢气|氮气|氧气|氩气|空气|气体|钢瓶|气瓶)")
# 分句开头的步骤编号（"1. " / "2、" / "三）"）不是部件名，解析前去掉
LIST_NO = re.compile(r"^\s*(?:\d{1,2}|[一二三四五六七八九十]{1,3})\s*[.、．)）]\s*")


def clause_tokens(clause, ev, resolve):
    """把一个分句按关系词解析成有序部件序列（括号内不切）。"""
    tokens = []
    if ARROWS.search(clause):
        for t in ARROWS.split(clause):
            p = resolve(clean_token(t), ev, "stated")
            if p:
                tokens.append(p)
    else:
        for piece in REL_SPLIT.split(strip_parens(clause)):
            tok = clean_token(piece)
            if not tok:
                continue
            p = resolve(tok, ev, "stated")
            if p:
                tokens.append(p)
    seq = []
    for p in tokens:
        if not seq or seq[-1] is not p:
            seq.append(p)
    return seq


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def pick(d, key):
    if not isinstance(d, dict):
        return None
    for name in ALIASES.get(key, [key]):
        if name in d and d[name] not in (None, "", [], {}):
            return d[name]
    return None


def as_items(value, key_field="label"):
    """结构化字段类型容错：只接受 list，或 id->spec 的 dict；其余（str/number/units 字典）返回 []。"""
    if isinstance(value, list):
        out = []
        for v in value:
            if isinstance(v, str):
                out.append({key_field: v})
            elif isinstance(v, dict):
                out.append(dict(v))
        return out
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if isinstance(v, dict) and (v.get(key_field) or v.get("id") or v.get("name")):
                item = dict(v)
                item.setdefault("id", k)
                item.setdefault(key_field, k)
                out.append(item)
            elif isinstance(v, str) and re.search(r"[\u4e00-\u9fa5A-Za-z]", k):
                out.append({key_field: k, "sub": v})
        return out
    return []


def find_case(explicit):
    cands = [explicit] if explicit else []
    cands += ["/input/case.json", "case.json", "/app/input/case.json", "input/case.json"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def read_materials(root):
    out = []
    if not root or not os.path.exists(root):
        return out
    paths = [root] if os.path.isfile(root) else []
    if not paths:
        skip_dir = {"work", "out", "output", "outputs", "__pycache__", ".git", "node_modules"}
        for dirpath, dirnames, names in os.walk(root):
            dirnames[:] = [d for d in sorted(dirnames)
                           if d not in skip_dir and not d.startswith(("work", "out"))]
            for n in sorted(names):
                if n.startswith(".") or n in ("case.json", "task.md"):
                    continue
                paths.append(os.path.join(dirpath, n))
    for p in paths:
        ext = os.path.splitext(p)[1].lower()
        if ext == ".json" or ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"):
            continue
        if K is not None:
            text = K.extract(p)
        elif ext in TEXT_EXT:
            text = open(p, encoding="utf-8", errors="replace").read()
        else:
            text = "[unsupported: %s]" % ext
        if text:
            out.append((p, text))
    return out


VERB_INSIDE = re.compile(r"(?:送入|送至|进入|流入|导入|泵入|通入|接入|汇合|排入|收集至|输送至|流经|经过|送往)")

# 关系连接词（长词在前，避免 "连接到" 被 "接" 抢先切断）
REL_SPLIT = re.compile(
    r"(?:连接到|连接至|连至|连接|接至|接入|再进入|进入|送入|送至|流入|导入|泵入|通入|"
    r"流向|来自|回到|返回|经过|流经|经|通过|由|至|接|和|与|及|或|、)")
QUALIFIER_TAIL = re.compile(r"(?:顶部|下端|上端|底部|出口|入口|进口|上游|下游|内侧|外侧|"
                            r"内部|前端|后端|左侧|右侧|上方|下方)+$")
QUALIFIER_HEAD = re.compile(r"^(?:顶部|下端|上端|底部|出口|入口|进口|上游|下游|内侧|外侧|"
                            r"内部|前端|后端|左侧|右侧|上方|下方)+")
PAREN_STRIP = re.compile(r"[（(][^（()）]*[）)]")


def split_top(s, seps):
    """按分隔符切分，但括号内的分隔符不切；保留括号内容。"""
    out, buf, depth = [], [], 0
    for ch in str(s):
        if ch in "（(":
            depth += 1
            buf.append(ch)
        elif ch in "）)":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch in seps and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


def strip_parens(s):
    """去掉成对括号及其内容；同时清掉不平衡的孤立括号，避免标签截断。"""
    s = str(s or "")
    prev = None
    while prev != s:
        prev = s
        s = PAREN_STRIP.sub("", s)
    return s.replace("（", "").replace("(", "").replace("）", "").replace(")", "")


def clean_token(s):
    s = strip_parens(s)
    s = s.strip(" \t：:，,。.；;、的")
    for _ in range(4):
        new = STOP_PREFIX.sub("", s).strip(" 的")
        new = QUALIFIER_HEAD.sub("", new).strip(" 的")
        if new == s:
            break
        s = new
    s = QUALIFIER_TAIL.sub("", s)
    return s.strip(" \t：:，,。.；;、的")


def last_part_name(s):
    ms = list(PAT_ZH_PART.finditer(str(s or "")))
    if ms:
        return clean_token(ms[-1].group(1))
    return ""


def clean_label(s):
    s = str(s or "").strip()
    s = re.sub(r"^[\s\-*•·▪>#]+", "", s)
    s = strip_parens(s)
    # 关系串（"冷凝器下端接收集瓶"）只保留最后一个真实部件名，绝不合并两个实体
    if re.search(r"(连接到|连接至|连接|接入|再进入|进入|送入|送至|流入|导入|泵入|通入|"
                 r"下端接|上端接|顶部连接|出口接|入口接|接|经|与|和|及)", s):
        t = last_part_name(s)
        if t:
            s = t
    # 词内残留动词：取动词右侧的真实受事（"液相产物流入收集瓶" -> "收集瓶"）
    hits = list(VERB_INSIDE.finditer(s))
    if hits and len(hits[-1].group(0)) < len(s) - 1:
        tail = s[hits[-1].end():].strip(" 的")
        if len(tail) >= 2:
            s = tail
    s = s.strip(" \t：:，,。.；;、的")
    for _ in range(2):
        new = STOP_PREFIX.sub("", s).strip(" 的")
        if new == s:
            break
        s = new
    s = re.sub(r"\s{2,}", " ", s)
    return s


def looks_like_part(s):
    if not s or len(s) < 2 or len(s) > 20:
        return False
    if NOT_PART.match(s) or re.fullmatch(r"[0-9.%‰\s\-/]+", s):
        return False
    if s.endswith(("度", "率", "量", "值", "性", "比")):
        return False
    # 含连接词/动词/部位词的长串不是部件名（如“混合器与原料储罐”“气相经背压阀”“反应器出口经冷凝器”）
    if re.search(r"(经|与|和|及|或|并|先后|然后|送入|进入|流入|泵入|通入|汇合|出口|入口|顶部|底部)", s):
        return False
    # 动词短语不是部件（"冲洗管路"、"检查气密性"），但保留 预热器/加热炉/冷却器 这类真实设备
    if re.match(r"^(冲洗|清洗|检查|装填|更换|吹扫|排空|密封|检漏|分析|取样|升温|降温|"
                r"进料|通入|打开|关闭|启动|停止|拆卸|安装|连接|调节)", s) \
            and not s.endswith(("接口", "取样口", "进样口")):
        return False
    return bool(PAT_ZH_PART.fullmatch(s) or PAT_EN_PART.fullmatch(s))


def step_no(tok):
    if tok.isdigit():
        return int(tok)
    if tok in NUM_ZH:
        return NUM_ZH[tok]
    if tok.startswith("十"):
        return 10 + NUM_ZH.get(tok[1:], 0)
    return None


def kind_from_text(text):
    for key, kws in (("waste", ("废液", "废气", "尾气", "排空", "废料", "排放")),
                     ("gas", ("氢气", "氮气", "氧气", "气体", "通气", "吹扫", "气相", "氩气")),
                     ("signal", ("信号", "数据", "采集", "通讯", "反馈", "控制线")),
                     ("energy", ("加热", "冷却", "换热", "蒸汽", "电力", "电源", "热量")),
                     ("material", ("物料", "样品", "粉末", "进样", "固体")),
                     ("flow", ("液体", "溶液", "液流", "流体", "进料", "底物", "产物"))):
        if any(k in text for k in kws):
            return key
    return "flow"


def build_spec(case, materials, args):
    fig_in = pick(case, "figure")
    fig_in = fig_in if isinstance(fig_in, dict) else {}
    figure = {
        "width_px": int(fig_in.get("width_px", 1500)),
        "height_px": int(fig_in.get("height_px", 1300)),
        "dpi": int(fig_in.get("dpi", 300)),
        "figure_type": "apparatus_route",
        "title": str(pick(case, "title") or fig_in.get("title") or "").strip()
        or "Experimental apparatus and technical route",
        "description": "Editable apparatus and technical-route figure generated from a structured spec.",
        "background": "#FFFFFF",
    }
    figure["height_px"] = max(1000, figure["height_px"])
    figure["width_px"] = max(1200, figure["width_px"])

    parts, connections, stages = [], [], []
    by_key = {}
    ctx = {"quote": ""}  # current source line / JSON snippet, attached to every element
    report = {"case_id": pick(case, "case_id"), "mode": "structured", "files": [],
              "unresolved": [], "evidence_missing": [], "inferred_parts": [],
              "inferred_stages": [], "unspecified": [], "warnings": [], "coverage": {},
              "stage_placeholder": False}

    def add_part(label, ptype=None, evidence="", status=None, data_ref="", ident=None,
                 coords=None, sub="", quote=""):
        label = clean_label(label)
        if not label:
            return None
        keys = [label.casefold()] + ([str(ident).casefold()] if ident else [])
        for k in keys:
            if k in by_key:
                p = by_key[k]
                if evidence and not p.get("evidence"):
                    p["evidence"] = evidence
                    p["status"] = status or "inferred"
                return p
        cid = r.slug(ident or label)
        used = {x["id"] for x in parts}
        base, i = cid, 2
        while cid in used:
            cid = "%s-%d" % (base, i)
            i += 1
        ptype = r.norm_type(ptype or label)
        p = {"id": cid, "label": label, "type": ptype,
             "shape": (r.TYPES.get(ptype) or ("", "rounded"))[1],
             "evidence": evidence or "", "quote": (quote or ctx["quote"])[:240],
             "status": status or ("stated" if evidence else "inferred"),
             "data_ref": data_ref or evidence or "", "sub": sub}
        if coords:
            for k in ("x", "y", "w", "h"):
                if k in coords and isinstance(coords[k], (int, float)):
                    p[k] = coords[k]
        if not p["evidence"]:
            report["evidence_missing"].append(label)
        parts.append(p)
        for k in keys:
            by_key[k] = p
        return p

    def match_part(token):
        t = clean_label(token)
        if not t:
            return None
        p = by_key.get(t.casefold())
        if p:
            return p
        # 含连接词/动词的短语不可能是单个部件名，避免 "反应器出口经冷凝器" 被误匹配成反应器
        if re.search(r"(经|通过|与|和|同|及|或)", t):
            return None
        # "反应器出口/冷凝器顶部" 这类部位词：去掉部位后缀再按后缀匹配
        base = re.sub(r"(出口|入口|进口|顶部|底部|上游|下游|外侧|内侧|内部|内)$", "", t)
        if base and base != t and len(base) >= 2:
            cands = [c for c in parts if c["label"].endswith(base)]
            if len(cands) == 1:
                return cands[0]
            if cands:
                return max(cands, key=lambda c: len(c["label"]))
        best = None
        tc = t.casefold()
        for k, cand in by_key.items():
            if len(k) < 2:
                continue
            inside = k in tc                       # 词里含完整部件名："反应器出口" ⊃ "固定床反应器"? 否，反向
            back = tc in k and looks_like_part(t)  # 简写："收集瓶" ⊂ "产物收集瓶"
            if inside or back:
                if best is None or len(k) > len(best[0]):
                    best = (k, cand)
        return best[1] if best else None

    def resolve(token, evidence, status="inferred"):
        p = match_part(token)
        if p:
            if evidence and not p.get("evidence"):
                p["evidence"] = evidence
                p["status"] = "inferred"
            return p
        t = clean_label(token)
        if looks_like_part(t):
            p = add_part(t, None, evidence, status)
            report["inferred_parts"].append(t)
            return p
        return None

    def add_conn(pa, pb, evidence, text, explicit=None, status=None):
        if not pa or not pb or pa["id"] == pb["id"]:
            return
        kind = r.norm_kind(explicit) or kind_from_text(text)
        # 同端点只保留一条（保留先出现的种类），避免同一管路被反抽成多条
        if any(c["from"] == pa["id"] and c["to"] == pb["id"] for c in connections):
            return
        if any(c["from"] == pb["id"] and c["to"] == pa["id"] for c in connections):
            return
        connections.append({"id": "c%d" % (len(connections) + 1), "from": pa["id"], "to": pb["id"],
                            "kind": kind, "status": status or "inferred", "label": "", "medium": "",
                            "rate": "", "direction": "forward", "evidence": evidence,
                            "quote": ctx["quote"][:240], "data_ref": evidence})

    # ---------------- 1. 结构化字段（带类型容错）
    raw_parts = as_items(pick(case, "parts"))
    raw_conns = as_items(pick(case, "connections"))
    raw_stages = as_items(pick(case, "stages"))
    for p in raw_parts:
        label = p.get("label") or p.get("name") or p.get("id")
        ev = p.get("evidence") or p.get("source") or ""
        sub = p.get("sub") or p.get("capacity") or p.get("spec") or ""
        ctx["quote"] = json.dumps(p, ensure_ascii=False)[:240] if isinstance(p, dict) else str(p)
        add_part(label, p.get("type") or p.get("category"), ev, p.get("status"),
                 p.get("data_ref") or p.get("spec") or "", p.get("id"), p, sub,
                 quote=ctx["quote"])
    for c in raw_conns:
        a = c.get("from") or c.get("source") or c.get("src") or c.get("upstream")
        b = c.get("to") or c.get("target") or c.get("dst") or c.get("downstream")
        ev = c.get("evidence") or c.get("source_ref") or ""
        ctx["quote"] = json.dumps(c, ensure_ascii=False)[:240] if isinstance(c, dict) else str(c)
        if not a or not b:
            report["unresolved"].append({"connection": c, "reason": "missing endpoint"})
            continue
        pa = match_part(a) or add_part(a, None, ev, "inferred", "", a)
        pb = match_part(b) or add_part(b, None, ev, "inferred", "", b)
        kind = r.norm_kind(c.get("kind") or c.get("type") or c.get("medium") or c.get("label")) or "flow"
        connections.append({"id": "c%d" % (len(connections) + 1), "from": pa["id"], "to": pb["id"],
                            "kind": kind, "status": c.get("status") or ("stated" if ev else "inferred"),
                            "label": c.get("label") or c.get("medium") or "",
                            "medium": c.get("medium") or "", "rate": c.get("rate") or c.get("flow_rate") or "",
                            "direction": c.get("direction") or "forward",
                            "evidence": ev, "quote": ctx["quote"][:240],
                            "data_ref": c.get("data_ref") or ev})
    for s in raw_stages:
        stages.append({
            "id": s.get("id") or "s%d" % (len(stages) + 1),
            "order": int(s.get("order") or s.get("step") or len(stages) + 1),
            "label": s.get("label") or s.get("name") or s.get("title") or "Stage %d" % (len(stages) + 1),
            "objective": s.get("objective") or s.get("aim") or s.get("description") or "",
            "methods": s.get("methods") or s.get("actions") or [],
            "inputs": s.get("inputs") or [],
            "outputs": s.get("outputs") or s.get("products") or [],
            "depends_on": s.get("depends_on") or s.get("depends") or [],
            "milestone": s.get("milestone") if isinstance(s.get("milestone"), str)
            else (s.get("milestone_label") or ""),
            "evidence": s.get("evidence") or "",
            "quote": (json.dumps(s, ensure_ascii=False)[:240] if isinstance(s, dict) else str(s)),
            "status": s.get("status") or ("stated" if s.get("evidence") else "inferred"),
        })

    # ---------------- 2. 文本扫描（结构化缺字段时补充；两遍：先部件，再连线/阶段）
    mats = read_materials(materials)
    # case.json 自带的叙述文本同样是一等材料（很多案例把装置描述写在 case 里而非附件）
    if isinstance(case, dict):
        inline = [(k, case[k]) for k in ("source_text", "text", "content", "notes", "abstract",
                                         "description", "material", "context")
                  if isinstance(case.get(k), str) and len(case[k].strip()) >= 24]
        if inline:
            mats = [("case.json(%s)" % k, v) for k, v in inline] + mats
    if mats:
        lines = []
        for path, text in mats:
            report["files"].append(path)
            if re.match(r"^\[(pdf text layer unavailable|unreadable|unsupported|"
                        r"docx unreadable|xlsx unreadable)", str(text).strip(), re.I):
                report["warnings"].append("%s: %s" % (os.path.basename(path),
                                                      str(text).strip()[:160]))
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if line.strip():
                    lines.append(("%s:L%d" % (os.path.basename(path), lineno), line))
        mentions = 0
        for ev, line in lines:
            ctx["quote"] = line
            # 括号感知切分：括号内（如“甲苯，500 mL”）不切断；关系词（经/连接到/接入/
            # 再进入/接/和/与）也作为边界，避免 "冷凝器下端接收集瓶" 被并成一个节点。
            clean_line = strip_parens(line)
            cands = []
            for seg in split_top(clean_line, "，,。；;:：\t"):
                for piece in REL_SPLIT.split(seg):
                    tok = clean_token(piece)
                    if not tok:
                        continue
                    ms = [clean_token(x) for x in PAT_ZH_PART.findall(tok)]
                    for nm in (ms or [tok]):
                        if looks_like_part(nm):
                            cands.append(nm)
                for m in PAT_EN_PART.finditer(seg):
                    cands.append(m.group(1).strip())
            seen = set()
            cands = [c for c in cands if not (c in seen or seen.add(c))]
            # 长名优先：先登记“固定床反应器”，再让“反应器”并入，避免产生重复节点
            for tok in sorted(cands, key=len, reverse=True):
                mentions += 1
                p = resolve(tok, ev, "stated")
                if p:
                    pm = re.search(re.escape(p.get("label", "")) + r"[（(]([^）)]{1,40})[）)]", line)
                    if pm and not p.get("sub"):
                        val = pm.group(1).strip()
                        if re.search(r"\d", val) and not ABSENCE_RE.search(val) and len(val) <= 24:
                            p["sub"] = val
            item = LIST_ITEM.match(line)
            if item:
                body = clean_label(item.group(1))
                if body and looks_like_part(body) and not match_part(body):
                    sub = ""
                    pm = PARAMS.search(item.group(1))
                    if pm:
                        sub = pm.group(1).strip()[:40]
                    p = resolve(body, ev, "stated")
                    if p and sub and not p.get("sub"):
                        p["sub"] = sub
        report["coverage"]["mentions"] = mentions

        # explicit "not specified" statements -> uncertainty, never silently dropped
        for ev, line in lines:
            if ABSENCE_RE.search(line):
                report["unspecified"].append({"locator": ev, "quote": line.strip()[:200]})

        for ev, line in lines:
            ctx["quote"] = line
            # 连线类型按所在分句判定，避免整行出现“氢气”就把液相连线标成 gas
            clauses = split_top(line, "，,。；;")
            carry = {}
            ci = 0
            while ci < len(clauses):
                clause = LIST_NO.sub("", clauses[ci])
                ckind = kind_from_text(clause)
                seq = clause_tokens(clause, ev, resolve)

                # 供料方向：反应器顶部连接气源，经阀/流量计后进入反应器。
                # 先识别再决定是否消费下一分句（"经减压阀与质量流量计"）。
                if FEED_TOP.search(clause):
                    reactor = next((p for p in seq if p.get("type") == "reactor"
                                    or re.search(r"(反应器|反应釜)", p.get("label", ""))), None)
                    gas = next((p for p in seq if FEED_SRC.search(p.get("label", ""))), None)
                    if reactor and gas and reactor is not gas:
                        mids = [p for p in seq if p is not gas and p is not reactor]
                        consumed = ci
                        if ci + 1 < len(clauses) and re.match(r"^\s*经", clauses[ci + 1]):
                            mids += clause_tokens(clauses[ci + 1], ev, resolve)
                            consumed = ci + 1
                        chain = [gas] + mids + [reactor]
                        for a, b in zip(chain, chain[1:]):
                            add_conn(a, b, ev, clause, status="stated")
                        carry[ckind] = (consumed, reactor)
                        ci = consumed + 1
                        continue

                if seq:
                    # 无主语分句（"再进入预热盘管"）承接上一分句的末节点（先查旧 carry）；
                    # 先落 carry 边再落本分句链，保证 JSON/绘制顺序与原文流向一致。
                    if re.match(r"^\s*(?:再|又|然后|随后|再进入|进入|接|至|流入|送入|通往)", clause):
                        prev = None
                        for k in (ckind,) + tuple(carry):
                            hit = carry.get(k)
                            if hit and hit[0] >= ci - 1 and hit[1] is not seq[0]:
                                prev = hit[1]
                                break
                        if prev:
                            add_conn(prev, seq[0], ev, clause, status="inferred")
                    for a, b in zip(seq, seq[1:]):
                        add_conn(a, b, ev, clause, status="stated")
                    carry[ckind] = (ci, seq[-1])
                for m in PAT_EN_FLOW.finditer(clause):
                    add_conn(resolve(m.group(1), ev), resolve(m.group(2), ev),
                             ev, clause, status="stated")
                ci += 1

        if not stages:
            found = {}
            for ev, line in lines:
                ctx["quote"] = line
                for m in PAT_STEP_INLINE.finditer(line):
                    n = step_no(m.group(1))
                    if n and n not in found:
                        found[n] = (m.group(2), ev)
                m = PAT_STEP.match(line)
                if m and not re.match(r"^\s*[（(]?\d{1,2}[）)]?\s*[.、]\s*\d", line):
                    n = step_no(m.group(1))
                    if n and n not in found:
                        found[n] = (m.group(2), ev)
            for n in sorted(found):
                text, ev = found[n]
                body = text.strip()
                head = split_top(body, "，,。；;")[0].strip()
                outputs = re.findall(r"(?:得到|产出|获得|建立|完成|达成|收集)([^，。；;]{2,24})", body)
                stages.append({
                    "id": "s%d" % (len(stages) + 1), "order": n,
                    "label": (strip_parens(head) or "步骤 %d" % n)[:36],
                    "objective": body[:90],
                    "methods": [], "inputs": [], "outputs": [o.strip() for o in outputs[:3]],
                    "depends_on": [len(stages)] if stages else [],
                    "milestone": "M%d" % n if re.search(r"里程碑|达成|验收|完成", body) else "",
                    "evidence": ev, "quote": body[:240], "status": "stated"})
                report["inferred_stages"].append(stages[-1]["label"])
            if stages:
                report["mode"] = "structured+text" if raw_parts else "text_candidates"
                report["warnings"].append("阶段由材料步骤解析，depends_on 按顺序默认串联，需人工核对并行支路")

    # ---------------- 3. 归一与兜底
    if not stages:
        if len(parts) >= 2:
            report["stage_placeholder"] = True
            stages = [{"id": "s1", "order": 1, "label": "装置搭建与调试", "objective": "",
                       "methods": [], "inputs": [], "outputs": ["装置具备运行条件"], "depends_on": [],
                       "milestone": "", "evidence": report["files"][0] if report["files"] else "",
                       "status": "inferred"}]
            report["warnings"].append("材料未给出阶段描述；已按装置运行顺序生成单阶段占位，"
                                      "需在 uncertainty 说明或在 notes 补充真实阶段")
        else:
            stages = [{"id": "s1", "order": 1, "label": "Stage 1", "objective": "",
                       "methods": [], "inputs": [], "outputs": [], "depends_on": [],
                       "milestone": "", "evidence": "", "status": "inferred"}]
            report["unresolved"].append({"stages": "no stages found; placeholder added"})
    stages.sort(key=lambda s: (s["order"], s["label"]))
    for i, st in enumerate(stages):
        st["order"] = i + 1
        st["font_pt"] = 8
        if not str(st.get("objective") or "").strip():
            st["objective"] = st["label"]
    id2order = {s["id"]: s["order"] for s in stages}
    for st in stages:
        deps = []
        for d in st.get("depends_on") or []:
            if d in id2order:
                deps.append(id2order[d])
            elif str(d).isdigit():
                deps.append(int(d))
        st["depends_on"] = sorted({d for d in deps if d < st["order"]})
    if not any(s.get("milestone") for s in stages):
        # 不虚构里程碑：材料没写就只发警告，由 uncertainty 与图注说明
        report["warnings"].append("材料未显式声明里程碑；图中不标里程碑，需在 uncertainty 说明")
    if len(stages) < 2:
        report["warnings"].append("仅解析到 %d 个阶段；技术路线表达能力受限，需在 limits 说明" % len(stages))

    if parts:
        pt = 9 if len(parts) <= 12 else (8 if len(parts) <= 20 else 7.5)
        for p in parts:
            p.setdefault("font_pt", pt)
            p["shape"] = p.get("shape") or (r.TYPES.get(p.get("type"), ("", "rounded"))[1])

    units = pick(case, "units")
    units = units if isinstance(units, dict) else {}
    scale = pick(case, "scale_bar")
    scale = scale if isinstance(scale, dict) else {}
    spec = {
        "figure": figure, "parts": parts, "connections": connections, "stages": stages,
        "legend": [], "notes": [], "units": units,
        "scale_bar": {"label": scale.get("label") or "示意，非等比 / not to scale",
                      "length_px": int(scale.get("length_px", 0) or 0)},
        "caption": str(pick(case, "caption") or ""),
        "expected": (case.get("expected") or case.get("expected_graph") or {})
        if isinstance(case, dict) else {},
    }
    auto_size(spec)
    order_parts(spec)
    layout(spec)
    report.update({"parts": len(parts), "connections": len(connections), "stages": len(stages),
                   "stated_parts": sum(1 for p in parts if p.get("status") == "stated"),
                   "stated_connections": sum(1 for c in connections if c.get("status") == "stated"),
                   "typed_parts": sum(1 for p in parts if p.get("type") != "other")})
    report["coverage"].update({"parts": len(parts), "typed_ratio":
                               round(report["typed_parts"] / len(parts), 3) if parts else 0.0})
    if len(parts) < 3:
        report["warnings"].append("仅识别到 %d 个部件，图面信息量不足，需人工补充材料解析" % len(parts))
    if not connections:
        report["warnings"].append("未识别到连线/流向；请在 spec.json 手工补 connections 后重跑")
    return spec, report


def auto_size(spec):
    """按部件数量自适应画布，避免多部件时文本溢出导致渲染失败。"""
    fig = spec["figure"]
    n = len(spec["parts"])
    kinds = {c.get("kind") for c in spec.get("connections") or []} or {"flow"}
    legend_h = 46 + 38 * len(kinds)
    cols = min(4, max(2, int(math.ceil(math.sqrt(max(n, 1) * 1.5)))))
    rows = max(1, int(math.ceil(n / float(cols))))
    need_w = 260 * cols + 96
    need_h = 112 + rows * 150 + legend_h + 24 + 300 + FOOTER_H
    if n <= 8:
        need_h = max(1300, 112 + rows * 150 + legend_h + 300 + FOOTER_H)
    fig["width_px"] = max(fig["width_px"], need_w)
    fig["height_px"] = max(fig["height_px"], min(need_h, 3400))
    if fig["width_px"] > 2600:
        fig["width_px"] = 2600


def order_parts(spec):
    """按主流向重排部件顺序：网格是蛇形排布，按上游→下游排序可显著减少连线交叉。

    只在部件没有给定显式坐标时生效；不增删任何部件，仅调整画布位置。
    """
    parts = spec.get("parts") or []
    conns = spec.get("connections") or []
    if not conns or any("x" in p for p in parts):
        return
    ids = [p["id"] for p in parts]
    out_edges = {i: [] for i in ids}
    indeg = {i: 0 for i in ids}
    for c in conns:
        a, b = c.get("from"), c.get("to")
        if a in out_edges and b in indeg and b not in out_edges[a]:
            out_edges[a].append(b)
            indeg[b] += 1
    seen, order = set(), []

    def visit(start):
        queue = [start]
        while queue:
            n = queue.pop(0)
            if n in seen:
                continue
            seen.add(n)
            order.append(n)
            queue.extend(m for m in out_edges[n] if m not in seen)

    for i in ids:
        if indeg[i] == 0 and i not in seen:
            visit(i)
    for i in ids:
        if i not in seen:
            visit(i)
    pos = {i: k for k, i in enumerate(order)}
    spec["parts"] = sorted(parts, key=lambda p: pos.get(p["id"], len(pos)))


def layout(spec):
    fig = spec["figure"]
    W, H = fig["width_px"], fig["height_px"]
    parts = spec["parts"]
    if not parts:
        return
    kinds = {c.get("kind") for c in spec.get("connections") or []} or {"flow"}
    try:
        legend_h = 46.0 + 38.0 * max(1, len(r.legend_items(spec)))
    except Exception:  # noqa: BLE001
        legend_h = 46.0 + 38.0 * len(kinds)
    stage_h = 250.0
    # 底部 260px 由 units/notes/scale/caption 占用（route_svg 的固定偏移），必须让出来
    app_h = max(360.0, H - 72.0 - legend_h - 24.0 - stage_h - FOOTER_H - 20.0)
    fig["apparatus_bbox"] = {"x": 16.0, "y": 72.0, "w": W - 32.0, "h": app_h}
    # 图例单独占一条，压在阶段区之上，避免 legend 与 stage panel 相互遮挡
    fig["legend_at"] = fig.get("legend_at") or [32.0, 72.0 + app_h + 8.0]
    fig["stage_bbox"] = {"x": 16.0, "y": 72.0 + app_h + legend_h + 16.0, "w": W - 32.0, "h": stage_h}
    cols = min(4, max(2, int(math.ceil(math.sqrt(len(parts) * 1.5)))))
    rows = max(1, int(math.ceil(len(parts) / float(cols))))
    x0, y0 = 48.0, 108.0
    x1, y1 = W - 48.0, 72.0 + app_h - 20.0
    cell_w = (x1 - x0) / cols
    cell_h = (y1 - y0) / rows
    for i, p in enumerate(parts):
        if all(k in p for k in ("x", "y", "w", "h")):
            continue
        row, col = i // cols, i % cols
        if row % 2 == 1:
            col = cols - 1 - col
        w = max(96.0, min(230.0, cell_w - 30.0))
        h = max(56.0, min(cell_h - 20.0, 150.0))
        if p.get("shape") == "column":
            w = min(w, 100.0)
            h = min(cell_h - 16.0, 170.0)
        if p.get("shape") == "circle":
            w = min(w, h)
        elif p.get("shape") == "triangle":
            # 三角形顶部窄：加宽才能让 4–5 字标签完整落在形状内
            w = min(cell_w - 30.0, max(260.0, h * 1.8))
        p["w"], p["h"] = w, h
        p["x"] = x0 + col * cell_w + (cell_w - w) / 2
        p["y"] = y0 + row * cell_h + (cell_h - h) / 2
    stages = spec["stages"]
    n = len(stages)
    gap = 24.0
    box_w = (W - 64.0 - gap * (n - 1)) / n
    sb = fig["stage_bbox"]
    for i, s in enumerate(stages):
        s["x"] = 32.0 + i * (box_w + gap)
        s["y"] = float(sb["y"]) + 44.0
        s["w"] = box_w
        s["h"] = float(sb["h"]) - 52.0
        s["shape"] = "rect"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case")
    ap.add_argument("--materials", default="/input")
    ap.add_argument("--out", default="work")
    ap.add_argument("--name", default="route")
    a = ap.parse_args()
    case_path = find_case(a.case)
    if not case_path:
        dump({"status": "blocked", "missing": "case.json not found"}, os.path.join(a.out, "extraction_report.json"))
        print("blocked: case.json not found")
        return 1
    case = json.load(open(case_path, encoding="utf-8"))
    spec, report = build_spec(case, a.materials, a)
    spec["figure"]["name"] = a.name
    dump(spec, os.path.join(a.out, "spec.json"))
    dump(report, os.path.join(a.out, "extraction_report.json"))
    print("spec=%s parts=%d connections=%d stages=%d mode=%s"
          % (os.path.join(a.out, "spec.json"), len(spec["parts"]), len(spec["connections"]),
             len(spec["stages"]), report["mode"]))
    for w in report["warnings"]:
        print(" warn:", w)
    if report["evidence_missing"]:
        print("warn: %d elements without evidence -> inferred" % len(report["evidence_missing"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
