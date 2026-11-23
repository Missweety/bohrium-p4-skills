#!/usr/bin/env python3
"""mathml_extract.py - turn publisher MathML formula nodes into LaTeX skeletons.

Reads the organizer-provided formula subset (e.g. artifacts/source-formulas.xml), keeps each
<math> node's xml id and nearest ancestor id, and converts mfrac / msub / msup / msqrt / mtable
into a LaTeX skeleton. Output is a skeleton to be aligned with the paper, not a finished answer.

Usage:
  python scripts/mathml_extract.py --xml artifacts/source-formulas.xml --out work/formulas_extracted.json
"""
import argparse
import json
import sys
import xml.etree.ElementTree as ET

SKIP = {"annotation", "annotation-xml"}
WRAP = {"math", "mrow", "semantics", "mstyle", "mpadded", "mphantom", "merror", "mtd"}


def local(tag):
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def tex(el):
    tag = local(el.tag)
    kids = [c for c in el if local(c.tag) not in SKIP]
    if tag in {"mi", "mn", "mo"}:
        return (el.text or "").strip()
    if tag in {"mtext", "ms"}:
        return "\\text{%s}" % (el.text or "").strip()
    if tag == "mfrac" and len(kids) >= 2:
        return "\\frac{%s}{%s}" % (tex(kids[0]), tex(kids[1]))
    if tag == "msup" and len(kids) >= 2:
        return "%s^{%s}" % (tex(kids[0]), tex(kids[1]))
    if tag == "msub" and len(kids) >= 2:
        return "%s_{%s}" % (tex(kids[0]), tex(kids[1]))
    if tag == "msubsup" and len(kids) >= 3:
        return "%s_{%s}^{%s}" % (tex(kids[0]), tex(kids[1]), tex(kids[2]))
    if tag == "msqrt":
        return "\\sqrt{%s}" % "".join(tex(c) for c in kids)
    if tag == "mroot" and len(kids) >= 2:
        return "\\sqrt[%s]{%s}" % (tex(kids[1]), tex(kids[0]))
    if tag in {"mover", "munder"} and len(kids) >= 2:
        cmd = "overset" if tag == "mover" else "underset"
        return "\\%s{%s}{%s}" % (cmd, tex(kids[1]), tex(kids[0]))
    if tag == "munderover" and len(kids) >= 3:
        return "\\underset{%s}{\\overset{%s}{%s}}" % (tex(kids[1]), tex(kids[2]), tex(kids[0]))
    if tag == "mfenced":
        op = el.get("open") or "("
        cl = el.get("close") or ")"
        return "\\left%s%s\\right%s" % (op, ", ".join(tex(c) for c in kids), cl)
    if tag == "mtable":
        return " \\\\ ".join(tex(r) for r in kids)
    if tag == "mtr":
        return " & ".join(tex(c) for c in kids)
    if tag in WRAP:
        return "".join(tex(c) for c in kids)
    return "".join(tex(c) for c in kids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        root = ET.parse(a.xml).getroot()
    except Exception as exc:  # noqa: BLE001
        print("FAIL: cannot parse XML:", exc)
        return 1
    parents = {c: p for p in root.iter() for c in p}
    out = []
    for node in root.iter():
        if local(node.tag) != "math":
            continue
        chain, cur = [], parents.get(node)
        while cur is not None:
            if cur.get("id"):
                chain.append(cur.get("id"))
            cur = parents.get(cur)
        xml_id = node.get("id") or (chain[0] if chain else "math-%d" % (len(out) + 1))
        label = ""
        for k in node.iter():
            if local(k.tag) == "label":
                label = "".join(k.itertext()).strip()
                break
        plain = " ".join("".join(node.itertext()).split())
        out.append({"xml_id": xml_id, "label": label or xml_id, "latex": tex(node),
                    "source_ids": chain[:3], "plain": plain[:200],
                    "locator": "xml:%s" % xml_id})
    report = {"source": a.xml, "count": len(out), "formulas": out,
              "note": "LaTeX is a skeleton from MathML; align with the paper before use"}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("extracted=%d -> %s" % (len(out), a.out))
    for f in out[:10]:
        print("  %-8s %s" % (f["xml_id"], f["latex"][:90]))
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
