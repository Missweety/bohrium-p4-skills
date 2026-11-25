#!/usr/bin/env python3
"""search.py - 在沉淀结果上做带过滤的检索。

  python3 /skills/weekly-skill/scripts/search.py --index /app/output/search_index.json --query "关键结论"
  python3 /skills/weekly-skill/scripts/search.py --index ... --query "方法" --tag 方法 --doc-id doc_xxx --json

输出 JSON；零命中时给出放宽建议并明确"不得解读为资料不存在"。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="/app/output/search_index.json")
    ap.add_argument("--query", required=True)
    ap.add_argument("--tag")
    ap.add_argument("--doc-id", dest="doc_id")
    ap.add_argument("--note-type", dest="note_type")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        with open(a.index, encoding="utf-8") as fh:
            index = json.load(fh)
    except Exception as exc:
        print(json.dumps({"status": "blocked", "reason": "index_unreadable: %s" % exc},
                         ensure_ascii=False))
        return 0
    filters = {}
    if a.tag:
        filters["tag"] = a.tag
    if a.doc_id:
        filters["doc_id"] = a.doc_id
    if a.note_type:
        filters["note_type"] = a.note_type
    res = core.search_index(index, a.query, filters)
    res["hits"] = res["hits"][:a.limit]
    res["status"] = "ok" if res["hits"] else "no_result"
    meta = {m["note_id"]: m for m in index.get("notes") or []}
    for h in res["hits"]:
        h["note"] = meta.get(h["note_id"], {})
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else
          json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
