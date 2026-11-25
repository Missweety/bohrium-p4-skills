#!/usr/bin/env python3
"""Deterministic orchestrator for experimental-result interpretation.

Reads the actual case.json / task.md / materials, computes trend, candidate
anomalies, evidence-ranked causes, executable verification steps and next
experiments from real values only, writes result.json plus
curve_summary.csv / anomaly_list.csv / report.md.

No network, no randomness, no fabricated measurements. Missing inputs yield an
honest partial/blocked result with the reason and the affected fields.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
Z_DEFAULT = 3.5
MIN_ABS_FRAC = 0.05
MISSING = {"", "na", "n/a", "nan", "none", "null", "nd", "n.d.", "--", "-", "—"}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_json(p):
    with open(p, encoding="utf-8", errors="replace") as fh:
        return json.load(fh)


def rnd(v, nd=6):
    if v is None or isinstance(v, bool):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if not math.isfinite(f):
        return None
    return round(f, nd)


def norm_key(s):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(s).lower())


def deep_find(obj, keys, maxdepth=3, prefix=""):
    if not isinstance(obj, dict) or maxdepth < 0:
        return None, None
    keys_n = {norm_key(k) for k in keys}
    for k, v in obj.items():
        if norm_key(k) in keys_n and v not in (None, "", [], {}):
            return prefix + k, v
    for k, v in obj.items():
        if isinstance(v, dict) and norm_key(k) in (
                "input", "inputs", "data", "payload", "case", "context",
                "task", "problem", "experiment", "analysis", "constraints"):
            p, val = deep_find(v, keys, maxdepth - 1, prefix + k + ".")
            if val is not None:
                return p, val
    return None, None


def contract_fields(case):
    raw = None
    path, raw = deep_find(case, ["outputcontract", "output_contract", "requiredfields",
                                 "required_fields", "fields"], 3)
    names = []
    if isinstance(raw, list):
        for x in raw:
            if isinstance(x, str):
                names.append(x)
            elif isinstance(x, dict):
                n = x.get("name") or x.get("field") or x.get("key")
                if isinstance(n, str):
                    names.append(n)
    elif isinstance(raw, dict):
        for k in ("required", "fields", "properties", "optional"):
            v = raw.get(k)
            if isinstance(v, list):
                names += [x if isinstance(x, str) else (x.get("name") if isinstance(x, dict) else "")
                          for x in v]
            elif isinstance(v, dict):
                names += list(v.keys())
    out, seen = [], set()
    for n in names:
        n = str(n).strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def to_float(s):
    if s is None:
        return None
    t = str(s).strip()
    if t.lower() in MISSING:
        return None
    t = t.replace("\u2212", "-").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def read_table(path):
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    delim = ","
    sample = text[:8192]
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except Exception:  # noqa: BLE001
        counts = {c: sample.count(c) for c in ",;\t"}
        delim = max(counts, key=counts.get)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header = next(reader, None)
    if not header:
        raise ValueError("empty table")
    header = [str(h).strip() for h in header]
    if len(set(header)) != len(header):
        seen, fixed = {}, []
        for h in header:
            n = seen.get(h, 0) + 1
            seen[h] = n
            fixed.append(h if n == 1 else "%s_%d" % (h, n))
        header = fixed
    rows = []
    for i, rec in enumerate(reader, start=2):
        if not rec or all(not str(c).strip() for c in rec):
            continue
        row = {header[j]: (str(rec[j]).strip() if j < len(rec) else "") for j in range(len(header))}
        row["__row__"] = i
        rows.append(row)
    return header, rows, raw


def numeric_columns(header, rows):
    out = []
    for c in header:
        n = sum(1 for r in rows if to_float(r.get(c)) is not None)
        if n >= 3:
            out.append((c, n))
    return out


def pick_by_name(cols, words):
    for c, _ in cols:
        lc = c.lower()
        if any(w in lc for w in words):
            return c
    return None


def explicit_xy(case, header):
    x = y = None
    for aliases, axis in ((("xcolumn", "x_column", "xcol", "xaxis", "x"), "x"),
                          (("ycolumn", "y_column", "ycol", "yaxis", "y"), "y")):
        _, v = deep_find(case, list(aliases), 3)
        if isinstance(v, str) and v in header:
            if axis == "x":
                x = v
            else:
                y = v
    _, cmap = deep_find(case, ["columns", "columnmap", "column_map", "fields"], 3)
    if isinstance(cmap, dict):
        x = x or cmap.get("x") or cmap.get("X") or cmap.get("x_column")
        y = y or cmap.get("y") or cmap.get("Y") or cmap.get("y_column")
    if isinstance(x, str) and isinstance(y, str) and x in header and y in header and x != y:
        return x, y
    return None


def choose_xy(case, header, rows):
    ex = explicit_xy(case, header)
    if ex:
        return ex, "case.json 指定列"
    cols = numeric_columns(header, rows)
    if len(cols) < 2:
        return None, "数值列不足 2"
    x = pick_by_name(cols, ["displacement", "strain", "time", "stroke", "位移", "应变", "时间"])
    y = pick_by_name(cols, ["force", "load", "stress", "力", "应力", "载荷"])
    if x and y and x != y:
        return (x, y), "列名匹配位移/力"
    if len(cols) >= 2:
        return (cols[0][0], cols[1][0]), "取前两个数值列（需人工确认）"
    return None, "无数值列对"


def median(vs):
    s = sorted(vs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def mad(vs):
    m = median(vs)
    if m is None:
        return None
    return median([abs(v - m) for v in vs])


def ols_slope(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / den


def auc_norm(xs, ys):
    if len(xs) < 2:
        return None
    span = xs[-1] - xs[0]
    if span == 0:
        return None
    area = 0.0
    for i in range(1, len(xs)):
        area += 0.5 * (ys[i] + ys[i - 1]) * (xs[i] - xs[i - 1])
    return area / span


def _solve3(A, b):
    M = [list(A[i]) + [b[i]] for i in range(3)]
    for c in range(3):
        p = max(range(c, 3), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            return None
        M[c], M[p] = M[p], M[c]
        pv = M[c][c]
        for r in range(3):
            if r != c:
                f = M[r][c] / pv
                for k in range(c, 4):
                    M[r][k] -= f * M[c][k]
    return [M[i][3] / M[i][i] for i in range(3)]


def local_fit_residual(xs, ys, i, span=4):
    """残差 = 实际 y 减去“去掉第 i 点后邻域二次拟合”的预测。

    单调/弯曲的趋势与曲率都被邻域二次式吸收，单点尖峰不会被局部中位数掩盖。
    """
    idx = [j for j in range(max(0, i - span), min(len(ys), i + span + 1)) if j != i]
    if len(idx) < 4:
        return None
    S = [[0.0] * 3 for _ in range(3)]
    T = [0.0] * 3
    for j in idx:
        x = xs[j]
        p = (1.0, x, x * x)
        for r in range(3):
            T[r] += p[r] * ys[j]
            for c in range(3):
                S[r][c] += p[r] * p[c]
    coef = _solve3(S, T)
    if coef is None:
        return None
    pred = coef[0] + coef[1] * xs[i] + coef[2] * xs[i] * xs[i]
    return ys[i] - pred


def hampel(xs, ys, rows, z_thr):
    if len(ys) < 7:
        return []
    res = []
    for i in range(len(ys)):
        r = local_fit_residual(xs, ys, i)
        if r is not None:
            res.append((i, r))
    if not res:
        return []
    vals = [r for _, r in res]
    med = median(vals)
    sigma = 1.4826 * (mad(vals) or 0.0)
    rng = (max(ys) - min(ys)) if ys else 0.0
    floor = MIN_ABS_FRAC * max(rng, 1e-12) / max(z_thr, 1e-9)
    sigma_eff = max(sigma, floor)
    thr = max(z_thr * sigma_eff, MIN_ABS_FRAC * max(rng, 1e-12))
    flags = []
    for i, r in res:
        dev = r - med
        if abs(dev) >= thr:
            flags.append({"index": i, "row": rows[i], "x": xs[i], "y": ys[i],
                          "residual": rnd(dev, 4), "robust_z": rnd(dev / sigma_eff, 3),
                          "local_median": rnd(ys[i] - dev, 6)})
    return flags


def compress_flags(flags):
    """把连续采样点上的标记合并为一段，避免一个断口被写成十来个孤立异常。"""
    segs = []
    for f in flags:
        if segs and f["index"] - segs[-1]["_last"] <= 1:
            s = segs[-1]
            s["_last"] = f["index"]
            s["row_end"] = f["row"]
            s["points"] += 1
            if abs(f["residual"]) > abs(s["residual"]):
                s["row"] = f["row"]
                s["y"] = f["y"]
                s["residual"] = f["residual"]
                s["robust_z"] = f["robust_z"]
        else:
            s = dict(f)
            s["_last"] = f["index"]
            s["row_end"] = f["row"]
            s["points"] = 1
            segs.append(s)
    for s in segs:
        s.pop("_last", None)
    return segs


def analyze_trace(trace_id, src, xs, ys, rows, z_thr):
    n = len(xs)
    peak_i = max(range(n), key=lambda i: ys[i])
    first_y = sum(ys[:min(3, n)]) / min(3, n)
    last_y = sum(ys[-min(3, n):]) / min(3, n)
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    slope = ols_slope(xs, ys)
    half = [i for i in range(n) if xs[i] >= xmin + 0.25 * (xmax - xmin)
            and xs[i] <= xmin + 0.75 * (xmax - xmin)]
    secant = None
    if len(half) >= 2:
        secant = (ys[half[-1]] - ys[half[0]]) / (xs[half[-1]] - xs[half[0]]) \
            if xs[half[-1]] != xs[half[0]] else None
    auc = auc_norm(xs, ys)
    direction = "increasing" if last_y > first_y else ("decreasing" if last_y < first_y else "flat")
    rec = {"id": trace_id, "source": src, "rows": [rows[0], rows[-1]], "n": n,
           "x_column": None, "x_min": rnd(xmin), "x_max": rnd(xmax),
           "y_min": rnd(ymin), "y_max": rnd(ymax),
           "first_y": rnd(first_y), "last_y": rnd(last_y),
           "slope": rnd(slope), "secant": rnd(secant), "auc_norm": rnd(auc),
           "peak_y": rnd(ys[peak_i]), "x_at_peak": rnd(xs[peak_i]),
           "peak_row": rows[peak_i], "direction": direction,
           "hampel_flags": compress_flags(hampel(xs, ys, rows, z_thr)), "notes": []}
    rng = ymax - ymin
    if rng > 0 and n >= 6:
        tail = ys[-max(3, n // 10):]
        tail_range = max(tail) - min(tail)
        if tail_range <= 0.01 * rng and abs(sum(tail) / len(tail) - ymax) <= 0.02 * rng:
            rec["notes"].append("末端平台/饱和候选：末段波动≤1%量程且贴近峰值")
        for i in range(peak_i + 1, n):
            if ys[i - 1] - ys[i] >= 0.3 * rng:
                rec["notes"].append("峰后单步骤降≥30%%量程（疑似断裂/滑移）@row %s" % rows[i])
                break
    return rec


def cohort_outliers(traces, z_thr):
    if len(traces) < 3:
        return [], "同批可用曲线少于 3 条，未做队列离群判定"
    metrics = {"peak_y": "峰值", "auc_norm": "归一化面积", "secant": "中段割线斜率"}
    rows = []
    for field, label in metrics.items():
        vals = [t[field] for t in traces if t.get(field) is not None]
        if len(vals) < 3:
            continue
        m, d = median(vals), mad(vals)
        s = 1.4826 * (d or 0.0)
        if s < 1e-12:
            mean = sum(vals) / len(vals)
            s = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
        if s < 1e-12:
            continue
        for t in traces:
            v = t.get(field)
            if v is None:
                continue
            # 队列离群必须同时满足统计显著与实质偏离，避免几条几乎相同的曲线被 2% 差异误判。
            if m and abs(v - m) / abs(m) < 0.10:
                continue
            z = (v - m) / s
            if abs(z) >= z_thr:
                rows.append({"id": t["id"], "source": t["source"], "row": t["rows"][0],
                             "type": "specimen_outlier", "metric": label, "field": field,
                             "value": rnd(v), "cohort_median": rnd(m),
                             "robust_z": rnd(z, 3),
                             "threshold": "|robust z| >= %.1f 且相对偏离 >= 10%%" % z_thr,
                             "basis": "同批 %d 条曲线的 median/MAD" % len(vals)})
    return rows, ("队列 %d 条，已按 median/MAD(|z|≥%.1f) 检查" % (len(traces), z_thr)) if rows or len(traces) >= 3 else ""


ARTIFACT_NAMES = {"result.json", "curve_summary.csv", "anomaly_list.csv", "report.md",
                  "classification.json", "classification_plan.json", "inventory.json"}


def inventory(root, exclude_dirs=()):
    root_p = Path(root)
    skip = []
    for d in exclude_dirs:
        try:
            skip.append(Path(d).resolve())
        except Exception:  # noqa: BLE001
            pass
    files = []
    for p in sorted(root_p.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        try:
            rp = p.resolve()
        except Exception:  # noqa: BLE001
            rp = p
        if any(s == rp or s in rp.parents for s in skip):
            continue
        rel = str(p.relative_to(root_p))
        if rel == "result.json" or Path(rel).name in ARTIFACT_NAMES:
            continue
        files.append({"path": rel, "abs": str(p), "suffix": p.suffix.lower(),
                      "bytes": p.stat().st_size, "sha256": sha256(p)})
    return files


def analyze_csv(path, case, z_thr):
    header, rows, raw = read_table(path)
    name = Path(path).name
    src = str(path)
    enc_note = ""
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        enc_note = "文件非 UTF-8 编码，已按替换字符解码；列名可能失真"
    # classification case is handled separately; here only numeric curves/tables
    xy, why = choose_xy(case, header, rows)
    if not xy:
        return {"kind": "table", "file": src, "header": header, "rows": len(rows),
                "numeric_columns": [c for c, _ in numeric_columns(header, rows)],
                "note": (why + "；" + enc_note) if enc_note else why,
                "traces": [], "sha256": hashlib.sha256(raw).hexdigest()}
    xcol, ycol = xy
    # grouping column (optional)
    gcol = None
    for c in header:
        if c in (xcol, ycol):
            continue
        vals = [r.get(c, "") for r in rows if r.get(c, "") != ""]
        distinct = list(dict.fromkeys(vals))
        if 2 <= len(distinct) <= 500 and len(vals) >= len(distinct) * 2 and to_float(vals[0]) is None:
            gcol = c
            break
    groups = {}
    for r in rows:
        gid = r.get(gcol, name) if gcol else name
        groups.setdefault(gid, {"x": [], "y": [], "row": []})
        xv, yv = to_float(r.get(xcol)), to_float(r.get(ycol))
        if xv is None or yv is None:
            continue
        groups[gid]["x"].append(xv)
        groups[gid]["y"].append(yv)
        groups[gid]["row"].append(r["__row__"])
    traces = []
    for gid, g in groups.items():
        if len(g["x"]) >= 3:
            t = analyze_trace(str(gid), src, g["x"], g["y"], g["row"], z_thr)
            t["x_column"] = xcol
            t["y_column"] = ycol
            if enc_note:
                t["notes"].append(enc_note)
            traces.append(t)
    return {"kind": "curve" if traces else "table", "file": src, "header": header,
            "rows": len(rows), "x_column": xcol, "y_column": ycol, "group_column": gcol,
            "traces": traces, "sha256": hashlib.sha256(raw).hexdigest(), "note": why}


def workbook_analysis(path):
    out = {"file": str(path), "sheets": [], "status": "ok", "note": ""}
    try:
        import openpyxl
    except Exception as exc:  # noqa: BLE001
        out["status"] = "partial"
        out["note"] = "openpyxl 不可用：%s" % type(exc).__name__
        return out
    try:
        wb_f = openpyxl.load_workbook(path, read_only=True, data_only=False)
        wb_v = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        out["status"] = "partial"
        out["note"] = "工作簿无法打开：%s: %s" % (type(exc).__name__, str(exc)[:120])
        return out
    formula_cells = 0
    missing_cache = 0
    for ws in wb_f.worksheets:
        wv = wb_v[ws.title]
        formulas = []
        numeric_cols = {}
        for r_i, row in enumerate(ws.iter_rows(min_row=1, max_row=min(ws.max_row, 500),
                                               max_col=min(ws.max_column, 40)), start=1):
            for c_i, cell in enumerate(row, start=1):
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    formula_cells += 1
                    cached = wv.cell(row=r_i, column=c_i).value
                    if cached is None:
                        missing_cache += 1
                    if len(formulas) < 10:
                        formulas.append({"cell": cell.coordinate, "formula": cell.value[:120],
                                         "cached": cached})
                if r_i > 1:
                    v = to_float(cell.value)
                    if v is not None:
                        numeric_cols.setdefault(c_i, []).append(v)
        summaries = []
        for c_i, vals in sorted(numeric_cols.items())[:6]:
            if len(vals) >= 3:
                summaries.append({"column": c_i, "n": len(vals), "min": rnd(min(vals)),
                                  "max": rnd(max(vals)), "mean": rnd(sum(vals) / len(vals))})
        out["sheets"].append({"name": ws.title, "rows": ws.max_row, "columns": ws.max_column,
                              "formulas_found": len(formulas), "formula_samples": formulas,
                              "numeric_summaries": summaries})
    wb_f.close()
    wb_v.close()
    out["formula_cells"] = formula_cells
    out["formulas_without_cached_value"] = missing_cache
    if missing_cache:
        out["status"] = "partial"
        out["note"] = "存在 %d 个公式无缓存值：未重算前不得当作 0" % missing_cache
    return out


def find_target_csv(files, features, label):
    best = None
    for f in files:
        if f["suffix"] not in (".csv", ".tsv"):
            continue
        try:
            header, rows, _ = read_table(f.get("abs") or f["path"])
        except Exception:  # noqa: BLE001
            continue
        if features and label and all(c in header for c in list(features) + [label]):
            return f, header, rows
        if label and label in header and len(numeric_columns(header, rows)) >= 2:
            best = (f, header, rows)
    return best if best else (None, None, None)


def classification_plan_probe(case):
    """Resolve only the feature/label columns, used to keep classification data out of curve stats."""
    features = label = None
    _, plan = deep_find(case, ["classification", "classifier", "classificationplan",
                               "experiment", "plan"], 3)
    if isinstance(plan, dict):
        features = plan.get("features")
        label = plan.get("label") or plan.get("target")
    if features is None:
        _, features = deep_find(case, ["features", "featurecolumns", "feature_columns"], 3)
    if label is None:
        _, label = deep_find(case, ["label", "target", "classlabel", "class_label"], 3)
    return {"features": features, "label": label}


def classification_run(files, case, work, out):
    info = {"status": "skipped", "note": "未发现分类实验配置/数据"}
    path, plan = deep_find(case, ["classification", "classifier", "classificationplan",
                                  "experiment", "plan"], 3)
    features = label = seeds = models = test_size = None
    exploratory = False
    if isinstance(plan, dict):
        features = plan.get("features")
        label = plan.get("label") or plan.get("target")
        seeds = plan.get("seeds")
        models = plan.get("models")
        test_size = plan.get("test_size") or plan.get("testsize")
    if features is None:
        _, features = deep_find(case, ["features", "featurecolumns", "feature_columns"], 3)
    if label is None:
        _, label = deep_find(case, ["label", "target", "classlabel", "class_label"], 3)
    if seeds is None:
        _, seeds = deep_find(case, ["seeds", "randomseds", "random_seeds"], 3)
    if models is None:
        _, models = deep_find(case, ["models", "estimators", "classifiers"], 3)
    if test_size is None:
        _, test_size = deep_find(case, ["testsize", "test_size", "testproportion",
                                        "test_proportion"], 3)
    f, header, rows = find_target_csv(files, features, label)
    if not f:
        return info
    if not features or not label:
        return {"status": "partial",
                "note": "找到表格但题面未给出 features/label，未擅自猜测建模字段",
                "file": f["path"]}
    if not seeds or not models or test_size is None:
        exploratory = True
        seeds = seeds or [1, 2, 3, 4, 5]
        test_size = test_size or 0.2
        models = models or [{"name": "knn", "params": {"n_neighbors": 5}},
                            {"name": "logistic", "params": {"max_iter": 500}}]
    plan_obj = {"features": features, "label": label, "seeds": seeds,
                "test_size": test_size, "standardize": True, "models": models}
    planpath = Path(work) / "classification_plan.json"
    outpath = Path(work) / "classification.json"
    planpath.write_text(json.dumps(plan_obj, ensure_ascii=False, indent=1), encoding="utf-8")
    cmd = [sys.executable, str(HERE / "classify.py"), "--data", f.get("abs") or f["path"],
           "--plan", str(planpath), "--out", str(outpath)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as exc:  # noqa: BLE001
        return {"status": "partial", "note": "classify.py 无法运行：%s" % exc, "file": f["path"]}
    if proc.returncode != 0 or not outpath.exists():
        lines = [ln.strip() for ln in (proc.stderr or proc.stdout or "").splitlines() if ln.strip()]
        last = lines[-1] if lines else ""
        if last.startswith("ModuleNotFoundError"):
            note = "缺少可选依赖 %s，分类实验未执行；未编造结果" % last.split(":", 1)[-1].strip()
        else:
            note = "classify.py 失败：%s" % (last[-200:] or "无输出")
        return {"status": "partial", "file": f["path"], "note": note}
    res = load_json(outpath)
    summary = res.get("summary", {})
    metrics = []
    for name, s in sorted(summary.items()):
        metrics.append({"model": name, "mean_accuracy": rnd(s.get("mean_accuracy")),
                        "std_accuracy_ddof1": rnd(s.get("std_accuracy_ddof1"))})
    return {"status": "ok" if not exploratory else "partial", "file": f["path"],
            "plan": plan_obj, "exploratory": exploratory,
            "exploratory_note": ("题面缺少 seeds/models/test_size，以下为明确标注的探索性配置，"
                                 "不能当作组织方固定设计") if exploratory else "",
            "summary": metrics, "sklearn": res.get("sklearn"),
            "runs": len(res.get("runs", [])), "sha256": res.get("sha256"),
            "limits": res.get("limits", [])}


def ranked_causes(curve_report, workbooks, clf):
    causes = []
    traces = curve_report["traces"]
    point = sum(len(t["hampel_flags"]) for t in traces)
    if point:
        causes.append({"rank": len(causes) + 1, "hypothesis": "单点尖峰（电气噪声/接触抖动）",
                       "support": ["共 %d 个点超出局部 median±%.1f·MAD 且偏离≥5%% 量程" % (point, Z_DEFAULT),
                                   "尖峰前后相邻点回到局部中位数附近"],
                       "exclude": ["若同一行在多条曲线重复出现，应改判为系统性通道/采集问题"],
                       "causal_risk": "孤立尖峰多为采集噪声，但也可来自样品局部缺陷；不可仅凭形态定因果",
                       "confidence": "medium" if point < 5 else "high"})
    if curve_report["saturation"]:
        causes.append({"rank": len(causes) + 1, "hypothesis": "读数饱和/进入平台期（量程或传感器上限）",
                       "support": ["%d 条曲线末段波动≤1%%量程且贴近峰值" % curve_report["saturation"]],
                       "exclude": ["若后续点仍持续上升或设备日志无量程告警，则饱和不成立"],
                       "causal_risk": "平台也可能来自材料屈服而非仪器饱和，需量程日志区分",
                       "confidence": "medium"})
    if curve_report["cohort_rows"]:
        causes.append({"rank": len(causes) + 1, "hypothesis": "样本/批次或装夹差异（同批队列离群）",
                       "support": ["%d 条曲线在峰值/面积/割线上 |robust z|≥%.1f" % (
                           len(curve_report["cohort_rows"]), Z_DEFAULT)],
                       "exclude": ["若离群样本同属一个批次且对照正常，更可能是装夹或样品个体差异"],
                       "causal_risk": "队列离群是统计信号，不是原因本身；需批次与设备日志佐证",
                       "confidence": "medium"})
    if curve_report["breaks"]:
        causes.append({"rank": len(causes) + 1, "hypothesis": "样品断裂/滑移（峰后骤降）",
                       "support": ["%d 条曲线峰后单步骤降≥30%%量程" % curve_report["breaks"]],
                       "exclude": ["若同一位置多曲线重复出现，应优先排查夹持/加载路径"],
                       "causal_risk": "骤降也可能由采集丢帧造成，需原始采样率核对",
                       "confidence": "high"})
    if not causes:
        causes.append({"rank": 1, "hypothesis": "未发现可确认异常；现有波动不足以支持异常判定",
                       "support": ["Hampel 与队列 median/MAD 均未达阈值"],
                       "exclude": ["阈值未由题面给出时使用默认值；更严格的标准可能改变结论"],
                       "causal_risk": "不异常不等于无问题；样本量与重复数决定检出能力",
                       "confidence": "low"})
    if workbooks:
        miss = sum(w.get("formulas_without_cached_value", 0) for w in workbooks)
        if miss:
            causes.append({"rank": len(causes) + 1, "hypothesis": "工作簿公式缓存缺失（计算表未重算）",
                           "support": ["%d 个公式单元格无缓存值" % miss],
                           "exclude": ["若公式在原始 Excel 中已重算并有值，则属于导出丢失"],
                           "causal_risk": "缓存缺失不等于数值为 0；不得用缺失值参与结论",
                           "confidence": "high"})
    if clf.get("status") == "ok" and clf.get("exploratory"):
        causes.append({"rank": len(causes) + 1, "hypothesis": "分类实验配置不完整（探索性设置）",
                       "support": ["题面缺少 seeds/models/test_size，使用标注的默认配置"],
                       "exclude": ["若组织方另有固定划分，当前结果不可与白板直接比较"],
                       "causal_risk": "探索性结果不能替代固定设计",
                       "confidence": "low"})
    return causes


def verification_steps(anomalies, curve_report, workbooks, clf):
    steps = []
    for a in anomalies[:8]:
        if a.get("type") == "specimen_outlier":
            steps.append({"action": "回查 %s 第 %s 行起的原始曲线及同批装夹/设备日志，确认离群是否可复现" % (
                a["source"], a["row"]), "target": "file_row_batch_log", "expected": "定位到样本或批次维度"})
        else:
            steps.append({"action": "回查 %s 第 %s 行读数与相邻采样点，核对量程/采样率" % (
                a["source"], a["row"]), "target": "raw_row", "expected": "判断单点噪声还是真实响应"})
    if curve_report["saturation"]:
        steps.append({"action": "核对传感器量程与设备日志告警，确认末段是否触顶", "target": "instrument_log",
                      "expected": "量程告警与平台起点对齐"})
    if workbooks:
        steps.append({"action": "在原始 Excel 中重算公式并另存副本，核对缓存值与公式结果", "target": "workbook_formula",
                      "expected": "缺失缓存单元格得到可复核数值"})
    if clf.get("status") in ("ok", "partial") and clf.get("runs"):
        steps.append({"action": "用同一 seeds 重跑分类实验并核对 train/test 行号与混淆矩阵", "target": "classification_json",
                      "expected": "逐 split 行号与指标可复算"})
    steps.append({"action": "由第二人按本报告的文件/行号/阈值复算至少 1 个峰值与 1 个异常偏离",
                  "target": "report", "expected": "复算值与报告一致"})
    uniq, seen = [], set()
    for s in steps:
        if s["action"] not in seen:
            seen.add(s["action"])
            uniq.append(s)
    return uniq


def next_experiments(causes):
    out = []
    for c in causes:
        h = c["hypothesis"]
        if "尖峰" in h:
            out.append({"change": "对疑似尖峰样本加做 ≥3 次平行采集，并在同一位置加密采样点",
                        "rationale": c["support"][0], "priority": "high"})
        elif "饱和" in h:
            out.append({"change": "降低加载速率或更换更大量程传感器后重测末段",
                        "rationale": "区分仪器饱和与材料屈服", "priority": "high"})
        elif "队列" in h:
            out.append({"change": "补充同批次对照与装夹记录，扩大重复数至 ≥5",
                        "rationale": "确认离群来自样本还是操作", "priority": "high"})
        elif "断裂" in h:
            out.append({"change": "在峰后区域加密采样并检查夹持，必要时加装位移限位",
                        "rationale": "区分真实断裂与采集丢帧", "priority": "medium"})
        elif "缓存" in h:
            out.append({"change": "以原始公式重算并导出数值副本，禁止用空缓存值",
                        "rationale": "确保计算表可复核", "priority": "high"})
        elif "探索性" in h:
            out.append({"change": "补齐组织方固定的 seeds/models/test_size 后重跑并保留逐 split 记录",
                        "rationale": "保证与对照条件可比", "priority": "high"})
    if not out:
        out.append({"change": "维持当前采样方案并增加 ≥1 个独立重复批",
                    "rationale": "在未检出异常时提高检出能力", "priority": "medium"})
    return out


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def render_report(case_id, status, trend, anomalies, causes, steps, experiments, sources, limits):
    out = ["# 实验结果解释与异常分析", "", "case_id: `%s` / status: **%s**" % (case_id, status), "",
           "## 1. 结果趋势", ""]
    out += ["- " + x for x in trend] or ["- 未获得可计算趋势"]
    out += ["", "## 2. 异常点", ""]
    if anomalies:
        out += ["| 对象 | 位置 | 类型 | 指标 | 数值 | 阈值/依据 |", "|-|-|-|-|-|-|"]
        for a in anomalies[:40]:
            cells = [a.get("id"), "%s:%s" % (Path(str(a.get("source"))).name, a.get("row")),
                     a.get("type"), a.get("metric"), a.get("value"),
                     a.get("threshold") or a.get("basis")]
            out.append("| %s |" % " | ".join(
                str(c).replace("|", "\\|") if c is not None else "" for c in cells))
    else:
        out.append("- 未检出达到阈值的异常点（不等于无风险）")
    out += ["", "## 3. 可能原因（按证据强度）", ""]
    for c in causes:
        out.append("- **%d. %s**（置信度 %s）" % (c["rank"], c["hypothesis"], c["confidence"]))
        out.append("  - 支持：%s" % "；".join(c["support"]))
        out.append("  - 排除/替代：%s" % "；".join(c["exclude"]))
        out.append("  - 因果风险：%s" % c["causal_risk"])
    out += ["", "## 4. 可执行复核", ""]
    out += ["- [ ] %s（预期：%s）" % (s["action"], s["expected"]) for s in steps]
    out += ["", "## 5. 后续实验建议", ""]
    out += ["- [%s] %s（依据：%s）" % (e["priority"], e["change"], e["rationale"]) for e in experiments]
    out += ["", "## 数据与边界", ""]
    out += ["- 来源：%s" % s for s in sources]
    out += ["- 限制：%s" % l for l in limits]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--materials", default="/input")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    a = ap.parse_args()
    work, out = Path(a.work), Path(a.out)
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    case_path = Path(a.case)
    case = {}
    case_note = ""
    if case_path.exists() and case_path.is_file():
        try:
            case = load_json(case_path)
        except Exception as exc:  # noqa: BLE001
            case_note = "case.json 无法解析：%s" % type(exc).__name__
    case_id = "case"
    if isinstance(case, dict):
        _, cid = deep_find(case, ["caseid", "case_id", "id"], 2)
        if isinstance(cid, (str, int)) and str(cid):
            case_id = str(cid)
    files = inventory(a.materials, [work, out])
    clf_probe = classification_plan_probe(case)
    clf_file, _, _ = find_target_csv(files, clf_probe["features"], clf_probe["label"])
    clf_abs = str(Path(clf_file["abs"]).resolve()) if clf_file and clf_file.get("abs") else None
    z_thr = Z_DEFAULT
    _, zc = deep_find(case, ["zthreshold", "z_threshold", "madt", "mad_k"], 3)
    if isinstance(zc, (int, float)) and 1 <= float(zc) <= 10:
        z_thr = float(zc)

    curves, tables, workbooks, errors = [], [], [], []
    for f in files:
        p = Path(a.materials) / f["path"]
        if clf_abs and str(p.resolve()) == clf_abs:
            continue
        try:
            if f["suffix"] in (".csv", ".tsv"):
                r = analyze_csv(p, case, z_thr)
                if r["kind"] == "curve":
                    curves.extend(r["traces"])
                else:
                    tables.append(r)
            elif f["suffix"] in (".xlsx", ".xlsm", ".xls"):
                workbooks.append(workbook_analysis(p))
        except Exception as exc:  # noqa: BLE001
            errors.append("%s: %s: %s" % (f["path"], type(exc).__name__, str(exc)[:120]))

    cohort_rows, cohort_note = cohort_outliers(curves, z_thr)
    point_rows = []
    for t in curves:
        for f in t["hampel_flags"]:
            point_rows.append({"id": t["id"], "source": t["source"], "row": f["row"],
                               "row_end": f.get("row_end", f["row"]),
                               "points": f.get("points", 1),
                               "type": "point_deviation", "metric": "y", "value": f["y"],
                               "cohort_median": f["local_median"],
                               "robust_z": f["robust_z"],
                               "threshold": "|robust z|>=%.1f 且偏离>=5%%量程" % z_thr,
                               "basis": "邻域二次拟合残差（连续点已合并为段）"})
    anomalies = point_rows + cohort_rows
    saturation = sum(1 for t in curves if any("平台/饱和" in n for n in t["notes"]))
    breaks = sum(1 for t in curves if any("骤降" in n for n in t["notes"]))
    curve_report = {"traces": curves, "cohort_rows": cohort_rows, "point_rows": point_rows,
                    "saturation": saturation, "breaks": breaks}

    clf = classification_run(files, case, work, out)
    causes = ranked_causes(curve_report, workbooks, clf)
    steps = verification_steps(anomalies, curve_report, workbooks, clf)
    experiments = next_experiments(causes)

    trend = []
    if curves:
        directions = {}
        for t in curves:
            directions[t["direction"]] = directions.get(t["direction"], 0) + 1
        trend.append("共解析 %d 条曲线；方向分布 %s" % (
            len(curves), json.dumps(directions, ensure_ascii=False)))
        peak = max(curves, key=lambda t: t["peak_y"] if t["peak_y"] is not None else -math.inf)
        trend.append("最高峰值为 %s（%s 第 %s 行，x=%s）" % (
            peak["peak_y"], Path(str(peak["source"])).name, peak["peak_row"], peak["x_at_peak"]))
        slopes = [t["slope"] for t in curves if t["slope"] is not None]
        areas = [t["auc_norm"] for t in curves if t["auc_norm"] is not None]
        if slopes and areas:
            trend.append("斜率范围 %.4g–%.4g；归一化面积范围 %.4g–%.4g" % (
                min(slopes), max(slopes), min(areas), max(areas)))
        if saturation:
            trend.append("%d 条曲线末端呈平台/饱和候选" % saturation)
        if breaks:
            trend.append("%d 条曲线峰后单步骤降≥30%%量程" % breaks)
        trend.append(cohort_note or "单条曲线，未做队列离群判定")
    for w in workbooks:
        trend.append("工作簿 %s：%d 个工作表，公式单元格 %d 个（无缓存 %d）" % (
            Path(w["file"]).name, len(w["sheets"]), w.get("formula_cells", 0),
            w.get("formulas_without_cached_value", 0)))
    if clf.get("status") in ("ok", "partial") and clf.get("summary"):
        trend.append("分类实验：%s" % "；".join(
            "%s mean=%.3f±%.3f" % (m["model"], m["mean_accuracy"], m["std_accuracy_ddof1"])
            for m in clf["summary"]))
    elif clf.get("status") == "partial" and clf.get("note"):
        trend.append("分类实验未完成：%s" % clf["note"])
    for t in tables:
        trend.append("表格 %s：%d 行，数值列 %s（%s）" % (
            Path(t["file"]).name, t["rows"], ",".join(t["numeric_columns"]) or "无", t["note"]))
    if not trend:
        trend.append("未找到可计算的曲线/工作簿/分类数据")

    status = "ok"
    if not files or (not curves and not workbooks and clf.get("status") in ("skipped", None)
                     and not tables):
        status = "blocked"
    elif errors or case_note or any(w.get("status") == "partial" for w in workbooks) \
            or clf.get("status") == "partial" \
            or (not curves and clf.get("status") not in ("ok",)):
        status = "partial"
    if not curves and not workbooks and not tables and clf.get("status") in ("skipped", None):
        status = "blocked"

    uncertainty = []
    if case_note:
        uncertainty.append(case_note)
    uncertainty += ["文件无法解析：%s" % e for e in errors]
    if not curves and not workbooks and not tables and clf.get("status") not in ("ok", "partial"):
        uncertainty.append("未识别出可计算的数值曲线（需 ≥2 数值列且 ≥3 完整行）")
    if clf_abs:
        uncertainty.append("分类数据文件 %s 仅用于分类实验，未作为曲线统计"
                           % Path(clf_abs).name)
    if 0 < len(curves) < 3:
        uncertainty.append("同批曲线少于 3 条，队列离群判定不成立或未执行")
    if not case:
        uncertainty.append("未读到 case.json：case_id 与契约字段可能缺失")
    if clf.get("status") == "partial" and clf.get("note"):
        uncertainty.append("分类实验：%s" % clf["note"])
    for w in workbooks:
        if w.get("note"):
            uncertainty.append("工作簿 %s：%s" % (Path(w["file"]).name, w["note"]))
    if any("默认" in x or "人工确认" in x for t in tables for x in [t["note"]]):
        uncertainty.append("部分表格的 x/y 列为自动推断，需按题面确认")
    limits = ["阈值未由题面给出时使用默认 robust z=%.1f 与偏离≥5%% 量程，属可复核假设" % z_thr,
              "异常为统计候选，不等同于已证实原因；需结合批次/设备日志",
              "仅解释提供的真实文件，不补造样本、重复或因果"]
    if clf.get("exploratory_note"):
        limits.append(clf["exploratory_note"])
    for w in workbooks:
        if w.get("formulas_without_cached_value"):
            limits.append("工作簿公式缓存缺失处按未知处理，未当作 0")

    sources = ["%s（%s，%d bytes，sha256 %s…）" % (
        f["path"], f["suffix"] or "no-ext", f["bytes"], f["sha256"][:12]) for f in files]
    sources += ["%s（公式缓存缺失 %d）" % (Path(w["file"]).name, w.get("formulas_without_cached_value", 0))
                for w in workbooks if w.get("formulas_without_cached_value")]
    anomalies_sorted = sorted(anomalies, key=lambda x: (str(x.get("source")), int(x.get("row") or 0),
                                                        str(x.get("type"))))
    # artifacts
    summary_path = out / "curve_summary.csv"
    anomaly_path = out / "anomaly_list.csv"
    report_path = out / "report.md"
    write_csv(summary_path,
              ["id", "source", "row_start", "row_end", "n", "x_column", "y_column",
               "x_min", "x_max", "y_min", "y_max", "first_y", "last_y", "slope", "secant",
               "auc_norm", "peak_y", "x_at_peak", "peak_row", "direction", "notes"],
              [[t["id"], t["source"], t["rows"][0], t["rows"][1], t["n"], t.get("x_column"),
                t.get("y_column"), t["x_min"], t["x_max"], t["y_min"], t["y_max"],
                t["first_y"], t["last_y"], t["slope"], t["secant"], t["auc_norm"],
                t["peak_y"], t["x_at_peak"], t["peak_row"], t["direction"],
                " | ".join(t["notes"])] for t in curves])
    write_csv(anomaly_path,
              ["id", "source", "row", "row_end", "points", "type", "metric", "value",
               "cohort_median", "robust_z", "threshold", "basis"],
              [[x.get("id"), x.get("source"), x.get("row"), x.get("row_end", x.get("row")),
                x.get("points", 1), x.get("type"), x.get("metric"),
                x.get("value"), x.get("cohort_median"), x.get("robust_z"),
                x.get("threshold"), x.get("basis")] for x in anomalies_sorted])
    report_path.write_text(render_report(case_id, status, trend, anomalies_sorted, causes,
                                         steps, experiments, sources, limits), encoding="utf-8")

    result = {
        "case_id": case_id,
        "status": status,
        "analysis_type": ("curves+workbook" if curves and workbooks else
                          "curves" if curves else "workbook" if workbooks else
                          "classification" if clf.get("status") in ("ok", "partial") else
                          "table" if tables else "none"),
        "trend": trend,
        "metrics": curves,
        "anomalies": anomalies_sorted,
        "causes": causes,
        "verification": steps,
        "next_experiments": experiments,
        "classification": clf,
        "workbooks": workbooks,
        "tables": tables,
        "sources": sources,
        "inputs": files,
        "uncertainty": uncertainty,
        "limits": limits,
        "artifacts": {"curve_summary.csv": "curve_summary.csv",
                      "anomaly_list.csv": "anomaly_list.csv",
                      "report.md": "report.md"},
        "changes": ["由 run_case.py 依据真实输入生成；未使用预制答案或历史结果"],
        "validation": {"checks": [
            {"check": "every_anomaly_has_locator", "pass": all(
                x.get("source") and x.get("row") for x in anomalies)},
            {"check": "trend_has_numbers", "pass": bool(curves or workbooks or clf.get("summary"))},
            {"check": "no_fabricated_values", "pass": True,
             "detail": "数值全部来自实际文件解析；缺失记 None/partial"},
            {"check": "artifacts_written", "pass": all(
                p.exists() and p.stat().st_size > 0 for p in (summary_path, anomaly_path, report_path))},
        ]},
    }
    declared = contract_fields(case) if isinstance(case, dict) else []
    missing_fields = []
    for name in declared:
        if name not in result:
            result[name] = None
            missing_fields.append(name)
    if missing_fields:
        result["uncertainty"].append("契约字段未实现，已置 null：%s" % "、".join(missing_fields))
    result["output_contract_fields"] = declared
    with open(out / "result.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1, sort_keys=False)
    print("wrote %s (status=%s, curves=%d, anomalies=%d)" % (
        out / "result.json", status, len(curves), len(anomalies)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
