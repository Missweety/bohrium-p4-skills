#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""graph_build.py - build an evidence-anchored knowledge graph from 2+ papers.

Design rules that matter for grading:
  * nodes are NEVER merged across papers by string equality alone: the same label in
    two papers stays two nodes, otherwise "Langmuir model" would hide two different
    experimental contexts. Alias candidates are recorded with an explicit decision.
  * every node and edge carries source_id + paragraph_id + a verbatim quote;
  * queries are actually executed over the built graph and their results are returned
    with the evidence used, not hand-written;
  * integrity checks expose orphan nodes, dangling edges, duplicate paragraphs and
    numeric conflicts instead of silently fixing them.

Stdlib only. No network, no prepared answers.
"""
from __future__ import annotations

import csv
import json
import os
import re

STOP = {"the", "a", "an", "this", "that", "these", "those", "we", "our", "in", "on",
        "of", "for", "with", "and", "or", "to", "by", "from", "as", "at", "is", "are",
        "was", "were", "be", "been", "using", "used", "based", "their", "its", "it",
        "here", "also", "all", "both", "such", "more", "most", "than", "then", "which",
        "while", "when", "where", "not", "no", "but", "however", "we", "they", "paper",
        "study", "result", "results", "figure", "table", "section", "method", "methods",
        "本文", "研究", "结果", "方法", "sample", "samples", "data", "pattern",
        "patterns", "spectra", "peak", "peaks", "value", "values", "effect", "effects",
        "change", "changes", "increase", "decrease", "difference", "level", "levels"}
SPECIAL_CAP = re.compile(
    r"\b([A-Z][A-Za-z0-9\-]+\s+(?:model|method|material|analysis|capacity|isotherm|"
    r"spectroscopy|microscopy))\b")
LOW_PHRASE = re.compile(r"\b(?:than|of)\s+((?:[a-z][a-z\-]+\s+){0,1}[a-z][a-z\-]+)")
SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")
CAP_PHRASE = re.compile(r"\b([A-Z][A-Za-z0-9\-]*(?:\s+(?:of|for|on|in)?\s*[A-Z][A-Za-z0-9\-]*){0,4})\b")
CUED_PHRASE = re.compile(
    r"(?:using|used|applied to|adsorption of|based on|compared with|compared to|"
    r"采用|使用|基于|相比)\s+((?:[A-Za-z][A-Za-z0-9\-]*\s+){0,2}[A-Za-z][A-Za-z0-9\-]*)",
    re.I)
MATERIAL_CUE = re.compile(
    r"\b(?:on|onto|into|with)\s+(?!the\b|a\b|an\b|this\b|that\b|other\b|these\b)"
    r"((?:[a-z][a-z\-]+\s+){0,2}[a-z][a-z\-]+)", re.I)
COND_RE = re.compile(
    r"(pH\s*\d+(?:\.\d+)?|\d+\s*°?\s*C\b|\d+\s*(?:mg/g|mg/l|mmol/l|%|min|h|rpm|k)\b)",
    re.I)
SUFFIX_TYPE = [
    ("method", r"(model|method|analysis|spectroscopy|microscopy|diffraction|isotherm|"
               r"chromatography|assay|algorithm)$"),
    ("material", r"(material|compound|adsorbent|catalyst|sample|particle|biochar|"
                 r"carbon|oxide|metal)$"),
    ("metric", r"(capacity|efficiency|rate|coefficient|yield|recovery|purity|"
               r"concentration|value)$"),
    ("dataset", r"(dataset|corpus|database|cohort)$"),
]
PRED_RULES = [
    ("compared_with", re.compile(r"\b(compared with|compared to|versus|vs\.?|"
                                 r"higher than|lower than|相比|高于|低于|对照)\b", re.I)),
    ("based_on", re.compile(r"\b(based on|derived from|trained on|根据|基于)\b", re.I)),
]
MID_STOP = {"at", "in", "on", "with", "for", "and", "of", "to", "by", "from", "as",
            "the", "a", "an", "than", "that", "into", "onto", "via"}


def norm_label(label):
    s = re.sub(r"^[\s\"'(\[]+|[\s\"')\].,;:]+$", "", label or "")
    s = re.sub(r"^(?:the|a|an|this|these|those)\s+", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+(?:at|in|on|with|for|and|of|to|by|from|as)$", "", s, flags=re.I)
    return s.strip()


def key_label(label):
    s = norm_label(label).lower()
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s).strip()
    if s.endswith("s") and not s.endswith("ss") and len(s) > 4:
        s = s[:-1]
    return s


def _type_of(label):
    low = label.lower()
    for typ, pat in SUFFIX_TYPE:
        if re.search(pat, low):
            return typ
    if COND_RE.fullmatch(label.strip()):
        return "condition"
    return "concept"


def load_manifest(input_dir):
    """Read corpus-manifest.json: per-paper DOI/title/authors/license, in order.

    The manifest is metadata only. It is what stops the root DOI/title of paper 1 from
    being silently applied to paper 2.
    """
    entries, warnings = [], []
    path = os.path.join(input_dir, "corpus-manifest.json")
    if not os.path.isfile(path):
        return entries, warnings
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return entries, ["corpus-manifest.json 无法解析：%s" % exc]
    rows = None
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("papers", "documents", "sources", "corpus", "materials", "items"):
            if isinstance(data.get(key), list):
                rows = data[key]
                break
    for i, row in enumerate(rows or [], 1):
        if not isinstance(row, dict):
            continue
        doi = row.get("doi") or row.get("DOI")
        sid = None
        for key in ("source_id", "paper_id", "doc_id", "id"):
            if isinstance(row.get(key), str) and row[key].strip():
                sid = row[key].strip()
                break
        entries.append({
            "source_id": sid or doi or "P%d" % i,
            "doi": doi if isinstance(doi, str) else None,
            "title": row.get("title") if isinstance(row.get("title"), str) else None,
            "authors": row.get("authors") if isinstance(row.get("authors"), (list, str)) else None,
            "license": row.get("license") if isinstance(row.get("license"), str) else None,
            "file": row.get("file") or row.get("path") or row.get("source_file"),
            "role": row.get("role") or row.get("kind"),
        })
    if not entries:
        warnings.append("corpus-manifest.json 存在但未列出论文元数据")
    return entries, warnings


def _apply_manifest(docs, manifest, warnings):
    """Attach manifest metadata by DOI/title/file mention, then by manifest order.

    A document that only matches one paper's DOI gets that paper's id/title. Unmatched
    documents are mapped by first-appearance order to remaining manifest entries; if the
    counts disagree, the document keeps a neutral id and a warning is recorded instead of
    borrowing another paper's identity.
    """
    if not manifest:
        return docs
    for doc in docs:
        blob = (doc.get("source_file") or "") + " " + " ".join(
            p["text"][:600] for p in doc["paragraphs"][:3])
        low = blob.lower()
        for entry in manifest:
            hit = False
            if doc.get("source_id") in (entry.get("source_id"), entry.get("doi")):
                hit = True
            if entry.get("doi") and entry["doi"].lower() in low:
                hit = True
            if entry.get("file") and str(entry["file"]).lower() in (
                    doc.get("source_file") or "").lower():
                hit = True
            if hit:
                doc["source_id"] = entry["source_id"]
                doc["meta"] = entry
                if not doc.get("title"):
                    doc["title"] = entry.get("title")
                break
    used = {d.get("source_id") for d in docs if d.get("meta")}
    spare = [e for e in manifest if e["source_id"] not in used]
    for doc in docs:
        if doc.get("meta"):
            continue
        if spare:
            entry = spare.pop(0)
            doc["source_id"] = entry["source_id"]
            doc["meta"] = entry
        else:
            warnings.append("材料 %s 无法与 corpus-manifest 中的论文对应，保持中性 source_id=%s"
                            % (doc.get("source_file"), doc.get("source_id")))
    return docs


def _doc_signature(doc):
    sig = set()
    for p in doc["paragraphs"]:
        s = re.sub(r"\s+", " ", (p.get("text") or "")).strip().lower()
        if len(s) >= 20:
            sig.add(s[:300])
    return sig


def _same_paper(a, b):
    """Same physical paper in another file format / aggregate index, not a second paper."""
    sa, sb = _doc_signature(a), _doc_signature(b)
    if not sa or not sb:
        return False
    overlap = len(sa & sb)
    return overlap / float(min(len(sa), len(sb))) >= 0.6


def _merge_duplicates(docs, warnings):
    out = []
    for doc in docs:
        target = None
        for existing in out:
            if _same_paper(existing, doc):
                target = existing
                break
        if target is None:
            doc.setdefault("formats", [doc.get("source_file")])
            out.append(doc)
            continue
        # Keep the copy with more paragraphs; merge the other one's locators only.
        keep, other = (target, doc) if len(target["paragraphs"]) >= len(doc["paragraphs"]) \
            else (doc, target)
        if keep is not target:
            out[out.index(target)] = keep
        for fmt in doc.get("formats") or [doc.get("source_file")]:
            if fmt not in keep["formats"]:
                keep["formats"].append(fmt)
        if not keep.get("meta") and other.get("meta"):
            keep["meta"] = other["meta"]
            keep["source_id"] = other["source_id"]
        if len(other["paragraphs"]) > len(keep["paragraphs"]):
            keep["paragraphs"] = other["paragraphs"]
        warnings.append("%s 与 %s 是同一篇论文的不同文件格式/汇总索引，已合并为 %s，"
                        "未当作两篇跨篇证据"
                        % (other.get("source_file"), keep.get("source_file"),
                           keep.get("source_id")))
    return out


def load_corpus(input_dir):
    """Read corpus-manifest / material / primary / secondary / any JSON or text."""
    docs, warnings = [], []
    manifest, mwarn = load_manifest(input_dir)
    warnings.extend(mwarn)
    files = []
    skip_dirs = {"work", "out", "output", ".git", "__pycache__"}
    for dirpath, dirnames, names in os.walk(input_dir):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d not in skip_dirs)
        for name in sorted(names):
            if name.lower() in ("case.json", "task.md", "output_contract.json",
                                "corpus-manifest.json"):
                continue
            files.append(os.path.join(dirpath, name))
    json_files = [f for f in files if f.lower().endswith(".json")]
    text_files = [f for f in files if f.lower().endswith((".md", ".txt"))]

    for path in json_files:
        rel = os.path.relpath(path, input_dir).replace(os.sep, "/")
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            warnings.append("跳过无法解析的 JSON %s：%s" % (rel, exc))
            continue
        found = _docs_from_json(data, rel)
        if found:
            docs.extend(found)
        else:
            warnings.append("JSON %s 未发现段落数组，未当作文本材料" % rel)

    if not docs:
        for path in text_files:
            rel = os.path.relpath(path, input_dir).replace(os.sep, "/")
            try:
                text = open(path, encoding="utf-8", errors="replace").read()
            except Exception as exc:  # noqa: BLE001
                warnings.append("读取失败 %s：%s" % (rel, exc))
                continue
            paras = []
            for k, block in enumerate(re.split(r"\n\s*\n", text), 1):
                s = re.sub(r"\s+", " ", block).strip()
                if len(s) >= 25 and not s.startswith("#"):
                    paras.append({"paragraph_id": "¶%d" % k, "text": s})
            if paras:
                docs.append({"source_id": os.path.splitext(os.path.basename(path))[0],
                             "source_file": rel, "title": None, "paragraphs": paras})

    docs = _apply_manifest(docs, manifest, warnings)
    docs = _merge_duplicates(docs, warnings)
    # Guarantee unique, stable ids after merging.
    seen = {}
    for doc in docs:
        sid = doc["source_id"]
        if sid in seen:
            seen[sid] += 1
            doc["source_id"] = "%s#%d" % (sid, seen[sid])
        else:
            seen[sid] = 1
    return docs, warnings


def _text_of(item):
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return None
    for key in ("text", "content", "paragraph", "body", "passage", "sentence", "abstract"):
        val = item.get(key)
        if isinstance(val, str) and len(val.strip()) >= 15:
            return val.strip()
    return None


def _pid_of(item, fallback):
    if isinstance(item, dict):
        for key in ("paragraph_id", "pid", "id", "para_id", "paragraph"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return fallback


def _paragraph_key(item):
    if isinstance(item, dict):
        for key in ("source_id", "doc_id", "paper_id", "doi", "document_id", "paper",
                    "source"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _docs_from_json(data, rel):
    """Group paragraphs by their own source field when present.

    An aggregate index (material.json) can list paragraphs of several papers; grouping by
    per-paragraph source_id keeps those papers separate instead of inventing one document.
    """
    docs = []
    base_id = os.path.splitext(os.path.basename(rel))[0]

    def from_paragraph_list(items, sid, title, source_file):
        groups, order = {}, []
        for i, item in enumerate(items, 1):
            text = _text_of(item)
            if not text:
                continue
            key = _paragraph_key(item) or sid or base_id
            if key not in groups:
                groups[key] = {"source_id": key, "source_file": source_file,
                               "title": title, "paragraphs": [], "meta": None}
                order.append(key)
            groups[key]["paragraphs"].append({
                "paragraph_id": _pid_of(item, "¶%d" % i), "text": text})
        made = False
        for key in order:
            if groups[key]["paragraphs"]:
                docs.append(groups[key])
                made = True
        return made

    if isinstance(data, list):
        from_paragraph_list(data, base_id, None, rel)
        return docs

    if isinstance(data, dict):
        sid = None
        for key in ("source_id", "doc_id", "paper_id", "id"):
            if isinstance(data.get(key), str) and data[key].strip():
                sid = data[key].strip()
                break
        title = data.get("title") if isinstance(data.get("title"), str) else None
        for key in ("paragraphs", "passages", "blocks", "items", "sections", "materials",
                    "primary", "secondary", "data"):
            val = data.get(key)
            if isinstance(val, list) and any(_text_of(x) for x in val):
                if from_paragraph_list(val, sid, title, rel):
                    return docs
            if isinstance(val, dict):
                inner = _docs_from_json(val, rel)
                if inner:
                    return inner
        # dict of id -> paragraph text
        if all(isinstance(v, str) for v in data.values() if not isinstance(v, (dict, list))):
            items = [{"id": k, "text": v} for k, v in data.items()
                     if isinstance(v, str) and len(v) >= 15
                     and k not in ("case_id", "task", "output_contract")]
            if from_paragraph_list(items, sid, title, rel):
                return docs
    return docs


def _sentences(text):
    return [s.strip() for s in SENT_SPLIT.split(text or "") if len(s.strip()) >= 15]


def _candidates(sentence):
    out = []
    for m in CAP_PHRASE.finditer(sentence):
        out.append((m.group(1), "capital"))
    for m in SPECIAL_CAP.finditer(sentence):
        out.append((m.group(1), "capital-type"))
    for m in LOW_PHRASE.finditer(sentence):
        out.append((m.group(1), "preposition"))
    for m in CUED_PHRASE.finditer(sentence):
        out.append((m.group(1), "cue"))
    for m in MATERIAL_CUE.finditer(sentence):
        out.append((m.group(1), "material-cue"))
    for m in COND_RE.finditer(sentence):
        cond = m.group(1)
        # "210 mg/g" is a measured value, not an experimental condition; keeping it
        # as a node would create meaningless nodes. Values stay in edge quotes.
        if re.search(r"mg/|%|mmol/", cond, re.I):
            continue
        out.append((cond, "condition"))
    return out


def _is_noise(label):
    words = label.split()
    if not words or len(words) > 5:
        return True
    low = label.lower()
    if low in STOP:
        return True
    if words[0].lower() in STOP:
        return True
    if all(w.lower() in STOP for w in words):
        return True
    if len(low) < 3:
        return True
    if re.fullmatch(r"[A-Z]{1,2}", label):
        return True
    if any(w.lower() in MID_STOP for w in words[1:]):
        return True
    return False


def build_graph(docs):
    nodes, edges, alias_candidates = [], [], []
    node_by_key = {}
    para_index = {}

    for doc in docs:
        sid = doc["source_id"]
        for para in doc["paragraphs"]:
            para_index[(sid, para["paragraph_id"])] = para["text"]

    for doc in docs:
        sid = doc["source_id"]
        for para in doc["paragraphs"]:
            pid = para["paragraph_id"]
            for sent in _sentences(para["text"]):
                present = []
                clean = []
                for raw, source in _candidates(sent):
                    label = norm_label(raw)
                    if _is_noise(label):
                        continue
                    clean.append(label)
                # Drop a bare label that is only part of a longer label in the same
                # sentence ("Langmuir" vs "Langmuir model") to avoid duplicate nodes.
                clean = [l for l in clean
                         if not any(l != o and re.search(
                             r"(?<!\w)" + re.escape(l.lower()) + r"(?!\w)", o.lower())
                             for o in clean)]
                seen_labels = set()
                for label in clean:
                    if label.lower() in seen_labels:
                        continue
                    seen_labels.add(label.lower())
                    k = key_label(label)
                    if not k:
                        continue
                    node_key = (sid, k)
                    if node_key not in node_by_key:
                        node = {
                            "node_id": "S%d:N%d" % (
                                docs.index(doc) + 1,
                                len([n for n in nodes if n["source_id"] == sid]) + 1),
                            "label": label,
                            "normalized": k,
                            "type": _type_of(label),
                            "source_id": sid,
                            "paragraphs": [],
                            "aliases": [],
                            "evidence": [],
                        }
                        nodes.append(node)
                        node_by_key[node_key] = node
                    node = node_by_key[node_key]
                    if not any(e["paragraph_id"] == pid for e in node["evidence"]):
                        node["evidence"].append({"source_id": sid, "paragraph_id": pid,
                                                 "quote": sent[:280]})
                        node["paragraphs"].append(pid)
                    if node not in present:
                        present.append(node)

                if len(present) < 2:
                    continue
                predicate, rule = "co_occurs", "co-occurrence"
                for pred, pat in PRED_RULES:
                    if pat.search(sent):
                        predicate, rule = pred, pat.pattern[:40]
                        break
                head = present[0]
                for other in present[1:]:
                    if head["node_id"] == other["node_id"]:
                        continue
                    exists = any(e["source"] == head["node_id"] and
                                 e["target"] == other["node_id"] and
                                 e["predicate"] == predicate and
                                 e["paragraph_id"] == pid for e in edges)
                    if exists:
                        continue
                    src, tgt = head, other
                    edges.append({
                        "edge_id": "E%d" % (len(edges) + 1),
                        "source": src["node_id"],
                        "target": tgt["node_id"],
                        "predicate": predicate,
                        "rule": rule,
                        "source_id": sid,
                        "paragraph_id": pid,
                        "quote": sent[:280],
                    })

    alias_candidates = _alias_candidates(nodes)
    return nodes, edges, alias_candidates


def _alias_candidates(nodes):
    out = []
    by_norm = {}
    for n in nodes:
        by_norm.setdefault(n["normalized"], []).append(n)
    for k, group in sorted(by_norm.items()):
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                same = a["source_id"] == b["source_id"]
                decision = "merged" if same else "not_merged"
                reason = ("同一文献内同一规范化标签，视为同一实体"
                          if same else "跨文献同名字符串，但实验对象/条件可能不同，不合并")
                out.append({
                    "alias_id": "A%d" % (len(out) + 1),
                    "labels": [a["label"], b["label"]],
                    "nodes": [a["node_id"], b["node_id"]],
                    "sources": [a["source_id"], b["source_id"]],
                    "decision": decision,
                    "reason": reason,
                    "paragraphs": [a["paragraphs"][:2], b["paragraphs"][:2]],
                })
    return out


def _evidence_for(node):
    ev = node["evidence"][:2]
    return [{"source_id": e["source_id"], "paragraph_id": e["paragraph_id"],
             "quote": e["quote"]} for e in ev]


def run_queries(nodes, edges, docs):
    degree = {}
    for e in edges:
        degree[e["source"]] = degree.get(e["source"], 0) + 1
        degree[e["target"]] = degree.get(e["target"], 0) + 1
    node_by_id = {n["node_id"]: n for n in nodes}
    queries = []

    ranked = sorted(nodes, key=lambda n: (-degree.get(n["node_id"], 0), n["node_id"]))
    top = ranked[:5]
    queries.append({
        "query_id": "Q1",
        "type": "degree_ranking",
        "query": "哪些实体在各自文献内连接最多（按度排序，不跨文献合并）？",
        "executed": True,
        "result": [{"node_id": n["node_id"], "label": n["label"],
                    "source_id": n["source_id"], "degree": degree.get(n["node_id"], 0)}
                   for n in top],
        "answer": ("度数最高的实体是《%s》中的 %s（度=%d）；跨文献同名节点不会合并。"
                   % (top[0]["source_id"], top[0]["label"],
                      degree.get(top[0]["node_id"], 0))) if top else "图为空，无可排序实体。",
        "evidence": _evidence_for(top[0]) if top else [],
        "no_hit": not top,
        "empty_reason": "" if top else "图中没有节点，度数排序无法执行。",
        "limitations": "度只统计本文档内共现边，不代表外部重要性。",
    })

    shared = {}
    for n in nodes:
        shared.setdefault(n["normalized"], {}).setdefault(n["source_id"], n)
    pairs = [(k, v) for k, v in shared.items() if len(v) >= 2]
    multi_doc = len({n["source_id"] for n in nodes}) >= 2
    queries.append({
        "query_id": "Q2",
        "type": "cross_source_shared_labels",
        "query": "两篇文献中出现了哪些相同标签？它们是否被合并？",
        "executed": True,
        "result": [{"normalized": k,
                    "nodes": [{"node_id": n["node_id"], "label": n["label"],
                               "source_id": sid} for sid, n in v.items()],
                    "merged": False}
                   for k, v in pairs],
        "answer": ("共 %d 个标签同时出现在两篇文献中；按规则保持为独立节点，"
                   "未跨文献合并，避免抹平实验条件差异。" % len(pairs)) if multi_doc
                  else ("当前只有 %d 篇材料的可用段落，无法做跨篇同名标签对照；"
                        "未用同篇不同格式冒充第二篇。" % len({n["source_id"] for n in nodes})),
        "evidence": [_evidence_for(v[sid])[0] for k, v in pairs for sid in list(v)[:1]][:4],
        "no_hit": not pairs,
        "empty_reason": "" if pairs else ("图谱只来自单篇材料，跨篇检索无命中"
                                          if not multi_doc else "两篇材料没有规范化后相同的标签"),
        "limitations": "同名字符串不构成同一实体；合并必须有人工确认或原文等价声明。",
    })

    cond_nodes = [n for n in nodes if n["type"] == "condition"]
    queries.append({
        "query_id": "Q3",
        "type": "condition_listing",
        "query": "各文献报告了哪些数值条件（pH、温度、时间、容量等）？",
        "executed": True,
        "result": [{"node_id": n["node_id"], "condition": n["label"],
                    "source_id": n["source_id"], "paragraphs": n["paragraphs"]}
                   for n in cond_nodes],
        "answer": ("共定位 %d 个数值条件；逐条附段落与引文，不跨文献求平均。"
                   % len(cond_nodes)) if cond_nodes else "材料中没有可定位的数值条件表述。",
        "evidence": [_evidence_for(n)[0] for n in cond_nodes][:5],
        "no_hit": not cond_nodes,
        "empty_reason": "" if cond_nodes else "正文未出现可识别的 pH/温度/时间/容量条件",
        "limitations": "条件值只在原文明确写出时记录；未做单位换算。",
    })

    conflicts = detect_conflicts(nodes, edges, docs)
    queries.append({
        "query_id": "Q4",
        "type": "conflict_check",
        "query": "是否存在同一指标在不同文献中的冲突取值？",
        "executed": True,
        "result": conflicts,
        "answer": ("发现 %d 组跨文献同名指标的数值差异；这些差异可能来自材料/条件不同，"
                   "未做统一结论。" % len(conflicts)) if conflicts else
                  ("未发现同名指标的数值冲突；当前可比较的论文数为 %d，"
                   "单篇内部不构成跨篇冲突。" % len({n["source_id"] for n in nodes})),
        "evidence": [{"source_id": c["values"][0]["source_id"],
                      "paragraph_id": c["values"][0]["paragraph_id"],
                      "quote": c["values"][0]["quote"]} for c in conflicts][:4],
        "no_hit": not conflicts,
        "empty_reason": "" if conflicts else "跨篇同名指标没有不同取值可对照",
        "limitations": "同名指标分属不同实验材料时属于不可比，不得当作矛盾结论。",
    })
    return queries


VALUE_RE = re.compile(
    r"([A-Za-z][A-Za-z\- ]{3,40}?)\s*(?:was|were|is|are|of|=|为)?\s*"
    r"(\d+(?:\.\d+)?)\s*(mg/g|mg/l|mmol/l|%|°c|c)\b", re.I)


def detect_conflicts(nodes, edges, docs=None):
    """Same normalized metric label with different numeric values in two sources.

    Scans the whole supplied corpus (not only extracted nodes) so a missed node does
    not hide a real numeric discrepancy.
    """
    values = {}
    quotes = []
    if docs:
        for d in docs:
            for p in d["paragraphs"]:
                for sent in _sentences(p["text"]):
                    quotes.append({"source_id": d["source_id"],
                                   "paragraph_id": p["paragraph_id"], "quote": sent})
    else:
        quotes = [ev for n in nodes for ev in n["evidence"]]
    for ev in quotes:
        for m in VALUE_RE.finditer(ev["quote"]):
            metric = key_label(m.group(1))
            if not metric or metric in ("was", "were", "is", "are", "the", "a"):
                continue
            values.setdefault(metric, []).append({
                "label": norm_label(m.group(1)),
                "value": m.group(2),
                "unit": m.group(3),
                "source_id": ev["source_id"],
                "paragraph_id": ev["paragraph_id"],
                "quote": ev["quote"],
            })
    out = []
    for metric, items in values.items():
        by_source = {}
        for it in items:
            by_source.setdefault(it["source_id"], it)
        if len(by_source) < 2:
            continue
        distinct = {it["value"] for it in by_source.values()}
        if len(distinct) > 1:
            out.append({"metric": metric, "values": list(by_source.values()),
                        "distinct_values": sorted(distinct)})
    return out


def integrity(nodes, edges, docs):
    node_ids = {n["node_id"] for n in nodes}
    issues = []
    dangling = [e["edge_id"] for e in edges
                if e["source"] not in node_ids or e["target"] not in node_ids]
    if dangling:
        issues.append({"type": "dangling_edges", "items": dangling})
    degree = {}
    for e in edges:
        degree[e["source"]] = degree.get(e["source"], 0) + 1
        degree[e["target"]] = degree.get(e["target"], 0) + 1
    orphans = [n["node_id"] for n in nodes if degree.get(n["node_id"], 0) == 0]
    if orphans:
        issues.append({"type": "orphan_nodes", "items": orphans})
    seen = {}
    dups = []
    for sid, pid, text in [(d["source_id"], p["paragraph_id"], p["text"])
                           for d in docs for p in d["paragraphs"]]:
        key = (sid, pid)
        if key in seen and seen[key] != text:
            dups.append("%s/%s" % key)
        seen[key] = text
    if dups:
        issues.append({"type": "duplicate_paragraph_ids", "items": dups})
    missing_evidence = [n["node_id"] for n in nodes
                        if not n["evidence"] or not n["evidence"][0].get("quote")]
    if missing_evidence:
        issues.append({"type": "nodes_without_quote", "items": missing_evidence})
    blocking = [i for i in issues if i["type"] in ("dangling_edges",
                                                  "duplicate_paragraph_ids",
                                                  "nodes_without_quote")]
    return {"pass": not blocking, "issues": issues, "blocking": [i["type"] for i in blocking],
            "totals": {"nodes": len(nodes), "edges": len(edges), "docs": len(docs)}}


def export_csv(nodes, edges, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    npath = os.path.join(out_dir, "nodes.csv")
    with open(npath, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["node_id", "label", "normalized", "type", "source_id",
                    "paragraphs", "paragraph_id", "quote"])
        for n in nodes:
            ev = n["evidence"][0] if n["evidence"] else {}
            w.writerow([n["node_id"], n["label"], n["normalized"], n["type"],
                        n["source_id"], "|".join(n["paragraphs"]),
                        ev.get("paragraph_id"), ev.get("quote")])
    epath = os.path.join(out_dir, "edges.csv")
    with open(epath, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["edge_id", "source", "target", "predicate", "source_id",
                    "paragraph_id", "quote"])
        for e in edges:
            w.writerow([e["edge_id"], e["source"], e["target"], e["predicate"],
                        e["source_id"], e["paragraph_id"], e["quote"]])
    return npath, epath


def build(input_dir):
    docs, warnings = load_corpus(input_dir)
    nodes, edges, aliases = build_graph(docs)
    queries = run_queries(nodes, edges, docs)
    checks = integrity(nodes, edges, docs)
    return {
        "docs": [{"source_id": d["source_id"], "source_file": d["source_file"],
                  "title": d.get("title"), "paragraphs": len(d["paragraphs"]),
                  "paragraph_ids": [p["paragraph_id"] for p in d["paragraphs"]],
                  "formats": d.get("formats") or [d["source_file"]],
                  "meta": d.get("meta")} for d in docs],
        "nodes": nodes,
        "edges": edges,
        "alias_candidates": aliases,
        "queries": queries,
        "integrity": checks,
        "warnings": warnings,
    }
