#!/usr/bin/env python3
"""elements.py - enumerate every drawable element from chart_spec.json.

One function builds the element list used by both the element map and the figure
caption, so the provenance file and the caption can never describe different figures.
Each element carries: element id, kind, panel, label, value/error/n, source file,
source column and the 1-based source row numbers it was computed from.

Data elements always get source_rows; structural elements (title, axis, legend) point
at the spec/file level instead. Missing values are never listed as if they were drawn.
"""
import os
import re


def _panel_prefix(pid):
    return "panel:%s" % pid


def display_field(field):
    name, unit = field.get("name", ""), field.get("unit", "")
    if unit and not re.search(r"[\(\[]\s*%s\s*[\)\]]" % re.escape(unit), name):
        return "%s (%s)" % (name, unit)
    return name


def _rows(values):
    out = []
    for r in values or []:
        if r is not None and r not in out:
            out.append(r)
    return out


def iter_elements(spec):
    source = spec.get("source", {}).get("file", "")
    header_row = spec.get("source", {}).get("header_row", 1)
    local = spec.get("source", {}).get("normalized") or source
    out = []

    for pi, panel in enumerate(spec.get("panels", [])):
        pid = panel.get("id") or chr(ord("A") + pi)
        pre = _panel_prefix(pid)
        out.append({"element": pre + ":title", "kind": "title", "panel": pid,
                    "text": panel.get("title", ""),
                    "source": "chart_spec.json#panels[%d].title" % pi, "source_rows": []})
        for key in ("x", "y", "color"):
            ax = panel.get("axis", {}).get(key)
            if not ax:
                continue
            field = panel.get("fields", {}).get(key) or panel.get("fields", {}).get("y", {})
            out.append({"element": pre + ":axis:" + key, "kind": "axis", "panel": pid,
                        "label": ax.get("label", ""), "unit": ax.get("unit", ""),
                        "field": field.get("name", ""), "column": field.get("column"),
                        "source": local, "header_row": header_row, "source_rows": []})
        y_field = panel.get("fields", {}).get("y", {})
        y_display = display_field(y_field)
        ct = panel.get("chart_type")
        for si, series in enumerate(panel.get("series", [])):
            rows = []
            if ct in ("bar", "grouped_bar"):
                for v in series.get("values", []):
                    rows += v.get("source_rows", [])
            elif ct == "line":
                for pt in panel.get("points", []):
                    if pt.get("series") == series.get("label"):
                        rows += pt.get("source_rows", [])
            elif ct == "scatter":
                for pt in panel.get("points", []):
                    if pt.get("group") in ("", series.get("label")):
                        rows.append(pt.get("row"))
            elif ct == "box":
                for b in panel.get("boxes", []):
                    rows += b.get("source_rows", [])
            elif ct == "hist":
                for b in panel.get("bins", []):
                    rows += b.get("rows", [])
            elif ct == "heatmap":
                for c in panel.get("cells", []):
                    rows += c.get("source_rows", [])
            out.append({"element": pre + ":series:%d" % si, "kind": "series", "panel": pid,
                        "label": series.get("label", ""), "chart": ct,
                        "field": y_display, "column": y_field.get("column"),
                        "error_type": series.get("error_type"),
                        "source": local, "source_rows": _rows(rows)})
            if ct in ("bar", "grouped_bar"):
                for v in series.get("values", []):
                    out.append({"element": pre + ":bar:%d|%s" % (si, v.get("label")),
                                "kind": "bar", "panel": pid, "label": v.get("label"),
                                "series": series.get("label"), "value": v.get("value"),
                                "error": v.get("error"), "error_type": v.get("error_type"),
                                "n": v.get("n"), "field": y_display,
                                "column": y_field.get("column"),
                                "source": local, "source_rows": v.get("source_rows", [])})
        if ct == "line":
            for k, pt in enumerate(panel.get("points", [])):
                out.append({"element": pre + ":point:%d" % k, "kind": "point", "panel": pid,
                            "x": pt.get("x"), "y": pt.get("y"), "error": pt.get("error"),
                            "error_type": pt.get("error_type"), "n": pt.get("n"),
                            "series": pt.get("series"), "field": y_display,
                            "column": y_field.get("column"), "source": local,
                            "source_rows": _rows(pt.get("source_rows") or [pt.get("row")])})
        elif ct == "scatter":
            x_field = panel.get("fields", {}).get("x", {})
            for k, pt in enumerate(panel.get("points", [])):
                out.append({"element": pre + ":point:%d" % k, "kind": "point", "panel": pid,
                            "x": pt.get("x"), "y": pt.get("y"), "group": pt.get("group"),
                            "field": y_display, "column": y_field.get("column"),
                            "x_field": display_field(x_field),
                            "x_column": x_field.get("column"),
                            "source": local, "source_rows": [pt.get("row")]})
        elif ct == "hist":
            for k, b in enumerate(panel.get("bins", [])):
                out.append({"element": pre + ":bin:%d" % k, "kind": "bin", "panel": pid,
                            "lo": b.get("lo"), "hi": b.get("hi"), "count": b.get("count"),
                            "field": y_display, "column": y_field.get("column"),
                            "source": local, "source_rows": b.get("rows", [])})
        elif ct == "box":
            for b in panel.get("boxes", []):
                out.append({"element": pre + ":box:%s" % b.get("label"), "kind": "box",
                            "panel": pid, "label": b.get("label"), "n": b.get("n"),
                            "min": b.get("min"), "q1": b.get("q1"),
                            "median": b.get("median"), "q3": b.get("q3"),
                            "max": b.get("max"), "outliers": b.get("outliers", []),
                            "field": y_display, "column": y_field.get("column"),
                            "source": local, "source_rows": b.get("source_rows", [])})
        elif ct == "heatmap":
            for ri, rl in enumerate(panel.get("row_labels", [])):
                for ci, cl in enumerate(panel.get("col_labels", [])):
                    cell = next((c for c in panel.get("cells", [])
                                 if c.get("row_label") == rl and c.get("col_label") == cl), None)
                    if not cell:
                        continue
                    out.append({"element": pre + ":cell:%d|%d" % (ri, ci), "kind": "cell",
                                "panel": pid, "row_label": rl, "col_label": cl,
                                "value": cell.get("value"), "n": cell.get("n"),
                                "field": cell.get("field") or y_display,
                                "column": cell.get("column"), "source": local,
                                "source_rows": cell.get("source_rows", [])})
        if panel.get("legend", {}).get("show"):
            for item in panel.get("legend", {}).get("items", []):
                out.append({"element": pre + ":legend:%s" % item.get("label"),
                            "kind": "legend", "panel": pid, "label": item.get("label"),
                            "color": item.get("color"),
                            "source": "chart_spec.json#panels[%d].legend.items" % pi,
                            "source_rows": []})
        for ann in panel.get("annotations", []):
            out.append({"element": pre + ":annotation:" + ann.get("id", ""),
                        "kind": "annotation", "panel": pid, "text": ann.get("text", ""),
                        "place": ann.get("place"), "source": ann.get("source", ""),
                        "source_rows": ann.get("source_rows", [])})
        for hl in panel.get("highlights", []):
            out.append({"element": pre + ":highlight:" + str(hl.get("target")),
                        "kind": "highlight", "panel": pid, "target": hl.get("target"),
                        "color": hl.get("color"), "note": hl.get("note"),
                        "source": "chart_spec.json#panels[%d].highlights" % pi,
                        "source_rows": []})

    for ann in spec.get("annotations", []):
        out.append({"element": "annotation:" + ann.get("id", ""), "kind": "annotation",
                    "panel": "", "text": ann.get("text", ""), "place": ann.get("place"),
                    "source": ann.get("source", ""),
                    "source_rows": ann.get("source_rows", [])})
    return out


def write_map(spec, out_dir):
    import hashlib
    import json
    elements = iter_elements(spec)
    payload = {
        "chart": spec.get("chart_type"),
        "title": spec.get("title"),
        "source": spec.get("source", {}).get("file"),
        "source_sha256": spec.get("source", {}).get("sha256"),
        "spec_sha256": hashlib.sha256(
            json.dumps(spec, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "elements": elements,
        "counts": {"total": len(elements),
                   "data": sum(1 for e in elements if e["kind"] in
                               ("bar", "point", "bin", "box", "cell"))},
    }
    path = os.path.join(out_dir, "element_map.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    return payload
