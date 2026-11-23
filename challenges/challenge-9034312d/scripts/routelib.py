"""routelib.py - 装置图/技术路线图共享几何、文本度量、色盲友好配色与词表归一（仅标准库）。

配色只使用 Okabe-Ito（定性）与 Viridis（定量）抽样；selfcheck 会拒绝其他彩色值。
"""
import math
import re

OKABE_ITO = ["#0072B2", "#E69F00", "#009E73", "#D55E00",
             "#CC79A7", "#56B4E9", "#F0E442", "#000000"]
VIRIDIS = ["#440154", "#482878", "#3E4989", "#31688E", "#26828E",
           "#1F9E89", "#35B779", "#6DCD59", "#B4DE2C", "#FDE725"]
NEUTRAL = {"text": "#111827", "muted": "#6B7280", "stroke": "#CBD5E1",
           "panel_fill": "#F7F9FC", "white": "#FFFFFF", "band": "#EEF2F7"}
ALLOWED_COLORS = set(c.lower() for c in OKABE_ITO + VIRIDIS + list(NEUTRAL.values()))

# 连线类型 -> (颜色, 线型, 标签)
KINDS = {
    "flow": ("#0072B2", "", "流体/液流"),
    "material": ("#CC79A7", "", "物料/样品"),
    "gas": ("#56B4E9", "10 4 2 4", "气体"),
    "energy": ("#E69F00", "6 4", "能量/电力"),
    "signal": ("#009E73", "2 5", "信号/数据"),
    "waste": ("#D55E00", "8 4", "废液/废气"),
}
KIND_LABELS = {
    "flow": "流体 / flow",
    "material": "物料 / material",
    "gas": "气体 / gas",
    "energy": "能量 / energy",
    "signal": "信号 / signal",
    "waste": "废液废气 / waste",
}
STATUS_LABELS = {"stated": "材料明确", "inferred": "推断（虚线）"}

# 部件类型 -> (描边色, 形状)
TYPES = {
    "reservoir": ("#0072B2", "rounded"),
    "vessel": ("#56B4E9", "rounded"),
    "pump": ("#E69F00", "circle"),
    "valve": ("#D55E00", "diamond"),
    "reactor": ("#009E73", "rounded"),
    "column": ("#CC79A7", "column"),
    "detector": ("#0072B2", "instrument"),
    "sensor": ("#009E73", "triangle"),
    "separator": ("#56B4E9", "instrument"),
    "instrument": ("#0072B2", "instrument"),
    "waste": ("#D55E00", "waste"),
    "tubing": ("#6B7280", "rounded"),
    "support": ("#6B7280", "rect"),
    "other": ("#6B7280", "rounded"),
}
TYPE_LABELS = {
    "reservoir": "储液/储气", "vessel": "容器", "pump": "泵", "valve": "阀",
    "reactor": "反应器", "column": "柱/分离柱", "detector": "检测器", "sensor": "传感器",
    "separator": "分离器", "instrument": "仪器", "waste": "废液/废气", "tubing": "管路",
    "support": "支架", "other": "其他",
}

TYPE_ALIASES = {
    "reservoir": ["reservoir", "tank", "储液罐", "储罐", "液罐", "水槽", "气瓶", "钢瓶", "试剂瓶", "原料瓶"],
    "vessel": ["vessel", "flask", "beaker", "烧杯", "烧瓶", "反应瓶", "容器", "离心管",
               "混合器", "收集瓶", "缓冲瓶", "储液瓶", "取样瓶"],
    "pump": ["pump", "泵", "蠕动泵", "真空泵", "注射泵", "隔膜泵", "进样泵", "高压泵", "计量泵"],
    "valve": ["valve", "阀", "三通阀", "电磁阀", "球阀", "止回阀", "背压阀", "减压阀", "针阀"],
    "reactor": ["reactor", "反应器", "反应釜", "反应腔", "光反应器", "电解槽", "生物反应器"],
    "column": ["column", "柱", "层析柱", "色谱柱", "分离柱", "填充柱", "吸附柱"],
    "detector": ["detector", "检测器", "探测器", "光谱仪", "质谱", "紫外", "荧光"],
    "sensor": ["sensor", "传感器", "探头", "电极", "热电偶", "温度计", "流量计", "ph计"],
    "separator": ["separator", "分离器", "离心机", "过滤器", "膜组件", "冷凝器", "萃取", "冷阱"],
    "instrument": ["instrument", "仪器", "设备", "分析仪", "控制器", "电源", "记录仪",
                   "预热器", "预热盘管", "盘管", "恒温槽", "水浴", "加热炉", "工作站"],
    "waste": ["waste", "废液", "废液瓶", "废气", "排放", "尾气", "废料"],
    "tubing": ["tubing", "tube", "pipe", "管路", "管道", "软管", "连接管", "三通"],
    "support": ["stand", "支架", "台架", "夹具", "底座"],
}

KIND_ALIASES = {
    "flow": ["flow", "liquid", "fluid", "stream", "流体", "液体", "液流", "管路", "输送",
             "流入", "流出", "进料", "出料", "循环"],
    "material": ["material", "solid", "sample", "物料", "样品", "固体", "试剂", "粉末", "进样"],
    "gas": ["gas", "air", "nitrogen", "气体", "氮气", "空气", "通气", "曝气", "氧气"],
    "energy": ["energy", "power", "heat", "electric", "能量", "电力", "加热", "冷却", "热", "电"],
    "signal": ["signal", "data", "control", "信号", "数据", "控制", "通讯", "反馈", "采集"],
    "waste": ["waste", "exhaust", "effluent", "废液", "废气", "排放", "尾气", "废料"],
}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def tw(s, px, bold=False):
    w = sum(1.0 if ord(c) > 0x2E80 else 0.56 for c in str(s)) * px
    return w * (1.05 if bold else 1.0)


def wrap(text, maxw, px):
    toks, buf = [], ""
    for ch in str(text):
        if ord(ch) > 0x2E80 or ch in "，。；：（）、“”":
            if buf:
                toks.append(buf)
                buf = ""
            toks.append(ch)
        elif ch.isspace():
            if buf:
                toks.append(buf)
                buf = ""
            toks.append(" ")
        else:
            buf += ch
    if buf:
        toks.append(buf)
    out, cur = [], ""
    for tok in toks:
        if tok == " ":
            if cur:
                cur += " "
            continue
        if tw(cur + tok, px) <= maxw:
            cur += tok
            continue
        if cur.strip():
            out.append(cur.rstrip())
        cur = ""
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
    return out


def fit(s, maxw, px):
    """单行裁剪：超宽时截断并加省略号，保证不越出容器。"""
    s = str(s)
    if tw(s, px) <= maxw:
        return s
    out = ""
    for ch in s:
        if tw(out + ch + "…", px) > maxw:
            break
        out += ch
    return out + "…"


def shape_half_width(shape, w, h, dy):
    """部件形状在垂直偏移 dy 处的半宽；用于保证文字留在形状内部而不是外接矩形内。"""
    if h <= 0 or w <= 0:
        return 0.0
    if shape == "triangle":
        return max(0.0, (dy + h / 2.0) / h * (w / 2.0))
    if shape == "diamond":
        return max(0.0, (1.0 - abs(dy) / (h / 2.0)) * (w / 2.0))
    if shape in ("circle", "ellipse"):
        if abs(dy) >= h / 2.0:
            return 0.0
        return (w / 2.0) * math.sqrt(max(0.0, 1.0 - (dy / (h / 2.0)) ** 2))
    return w / 2.0


def part_layout(p, dpi):
    """返回 (pt, 标签行, 副标签行)：字号逐级下调至文字同时满足形状内宽与高度。"""
    x, y, w, h = bx(p)
    shape = p.get("shape") or TYPES.get(p.get("type"), ("", "rounded"))[1]
    base = float(p.get("font_pt", 9))
    raw = str(p.get("label", ""))
    sub_raw = str(p.get("sub", ""))
    for i in range(11):
        pt = max(7.0, base - 0.5 * i)
        px = pt * dpi / 72.0
        # 三角形/菱形在文字所在高度上的可用宽度远小于外接矩形；先按中心宽度换行，
        # 再逐步收紧行宽，让上行文字也落在收窄后的形状内。
        center = max(28.0, 2.0 * shape_half_width(shape, w, h, 0.0) - 14.0)
        widths = [center]
        if shape in ("triangle", "diamond", "circle", "ellipse"):
            widths += [max(24.0, center * f) for f in (0.78, 0.62, 0.5)]
        for maxw in widths:
            # 绝不截断部件名：行数由换行决定，放不下就继续缩字号/收紧行宽
            lines = wrap(raw, maxw, px) or [""]
            sub = wrap(sub_raw, maxw, px * 0.72)[:2] if sub_raw else []
            total_h = ((len(lines) - 1) * px * 1.2 + px * 0.9
                       + len(sub) * px * 0.72 * 1.2 + 8.0)
            fits = total_h <= h
            dy = -(len(lines) - 1) * px * 1.2 / 2.0
            for ln in lines:
                if tw(ln, px) > max(10.0, 2.0 * shape_half_width(shape, w, h, dy) - 8.0):
                    fits = False
                    break
                dy += px * 1.2
            for ln in sub:
                if tw(ln, px * 0.72) > max(10.0, 2.0 * shape_half_width(shape, w, h, dy) - 8.0):
                    fits = False
                    break
                dy += px * 0.72 * 1.2
            if fits:
                return pt, lines, sub
        if pt <= 7.0:
            break
    return 7.0, wrap(raw, max(20.0, w - 18), 7.0 * dpi / 72.0) or [""], []


def text_fits(p, dpi):
    """复检 part_layout 的行宽是否都在形状内部（供 route_spec lint 使用）。"""
    x, y, w, h = bx(p)
    shape = p.get("shape") or TYPES.get(p.get("type"), ("", "rounded"))[1]
    pt, lines, sub = part_layout(p, dpi)
    px = pt * dpi / 72.0
    dy = -(len(lines) - 1) * px * 1.2 / 2.0
    for ln in lines:
        if tw(ln, px) > max(10.0, 2.0 * shape_half_width(shape, w, h, dy) - 6.0):
            return False
        dy += px * 1.2
    for ln in sub:
        if tw(ln, px * 0.72) > max(10.0, 2.0 * shape_half_width(shape, w, h, dy) - 6.0):
            return False
        dy += px * 0.72 * 1.2
    return True


def stage_layout(s, dpi):
    """阶段卡四行结构（编号+标题 / objective / 产出 / 里程碑）的统一度量。"""
    pt_t = min(float(s.get("font_pt", 8)), 8.0)
    pt_b = max(6.0, pt_t - 1.5)
    px_t = pt_t * dpi / 72.0
    px_b = pt_b * dpi / 72.0
    w, h = float(s.get("w", 100)), float(s.get("h", 190))
    all_t = wrap(s.get("label", ""), w - 72, px_t)
    tlines = all_t[:2] or ["Phase %s" % s.get("order", "")]
    if len(all_t) > 2:
        tlines[-1] = fit(tlines[-1], w - 72 - px_t, px_t) + "…"
    olimit = 3 if len(tlines) == 1 else 2
    obj = s.get("objective", "")
    _o = re.sub(r"[\s。.;；,，、:：]+$", "", str(obj))
    _l = re.sub(r"[\s。.;；,，、:：]+$", "", str(s.get("label", "")))
    if _o == _l:
        obj = ""  # 目标与标题同句时不在图面重复；数据仍保留 objective
    all_o = wrap(obj, w - 28, px_b)
    olines = all_o[:olimit]
    if olines and len(all_o) > olimit:
        last = olines[-1]
        olines[-1] = (last + "…") if tw(last + "…", px_b) <= w - 28 \
            else fit(last, w - 28 - px_b, px_b) + "…"
    title_y = 30.0
    obj_y = title_y + (len(tlines) - 1) * px_t * 0.95 + px_t * 1.25
    obj_bottom = obj_y + (len(olines) - 1) * px_b * 1.05 + px_b * 0.9 if olines else obj_y
    return {"pt_title": pt_t, "pt_body": pt_b, "px_title": px_t, "px_body": px_b,
            "title_lines": tlines, "objective_lines": olines,
            "title_y": title_y, "objective_y": obj_y,
            "output_y": h - 40.0, "milestone_y": h - 14.0,
            "need": obj_bottom + 8.0 + px_b * 0.85}


def bx(o):
    return float(o["x"]), float(o["y"]), float(o["w"]), float(o["h"])


def ct(n):
    x, y, w, h = bx(n)
    return x + w / 2, y + h / 2


def anchor(n, tx, ty):
    cx, cy = ct(n)
    x, y, w, h = bx(n)
    dx, dy = tx - cx, ty - cy
    if not (dx or dy):
        return cx, cy
    shape = n.get("shape", TYPES.get(n.get("type"), ("", "rounded"))[1])
    if shape in ("circle", "ellipse", "sensor"):
        t = 1 / math.hypot(dx / (w / 2), dy / (h / 2))
    else:
        t = min((w / 2) / abs(dx) if dx else 1e9, (h / 2) / abs(dy) if dy else 1e9)
    return cx + dx * t, cy + dy * t


def ix(a, b):
    ax, ay, aw, ah = bx(a)
    bx0, by, bw, bh = bx(b)
    w = min(ax + aw, bx0 + bw) - max(ax, bx0)
    h = min(ay + ah, by + bh) - max(ay, by)
    return w * h if w > 0 and h > 0 else 0.0


def inside(a, b, pad=2):
    ax, ay, aw, ah = bx(a)
    bx0, by, bw, bh = bx(b)
    return (bx0 >= ax - pad and by >= ay - pad
            and bx0 + bw <= ax + aw + pad and by + bh <= ay + ah + pad)


def slug(text):
    s = str(text).strip().lower()
    s = "".join(c if (c.isalnum() or c in "-_") else "-" for c in s)
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-") or "n"


def norm_type(raw):
    if not raw:
        return "other"
    s = str(raw).strip().lower()
    if s in TYPES:
        return s
    for canon, aliases in TYPE_ALIASES.items():
        if s == canon or any(a in s for a in aliases):
            return canon
    return "other"


def norm_kind(raw):
    if not raw:
        return None
    s = str(raw).strip().lower()
    if s in KINDS:
        return s
    for canon, aliases in KIND_ALIASES.items():
        if s == canon or any(a in s for a in aliases):
            return canon
    return None


def legend_items(spec):
    if spec.get("legend"):
        return spec["legend"]
    kinds, statuses = [], {}
    for c in spec.get("connections", []):
        k = c.get("kind", "flow")
        if k not in kinds:
            kinds.append(k)
        statuses.setdefault(k, set()).add(c.get("status", "stated"))
    out = []
    for k in kinds:
        st = "inferred" if statuses[k] == {"inferred"} else "stated"
        text = KIND_LABELS.get(k, k) + ("（推断，虚线）" if st == "inferred" else "")
        out.append({"id": "lg_%s" % k, "kind": k, "status": st, "text": text})
    return out


def legend_box(spec, items, width, height):
    x, y = (spec.get("figure", {}).get("legend_at") or [32, height - 280])
    return x, y, 640.0, 46.0 + 38.0 * max(1, len(items))
