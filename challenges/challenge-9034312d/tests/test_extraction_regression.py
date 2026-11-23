#!/usr/bin/env python3
"""Regression tests for Chinese apparatus/route extraction.

The fixture lives inside the package at tests/fixtures/apparatus_chain/ and is
read-only for the test: every run writes only to a fresh temp directory.

Run from the submission directory:
    python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
FIXTURE = os.path.join(HERE, "fixtures", "apparatus_chain")
sys.path.insert(0, SCRIPTS)

import route_extract as E  # noqa: E402

with open(os.path.join(FIXTURE, "case.json"), encoding="utf-8") as fh:
    CASE = json.load(fh)
with open(os.path.join(FIXTURE, "protocol.md"), encoding="utf-8") as fh:
    PROTOCOL = fh.read()

EXPECTED_PARTS = ["原料瓶", "硅胶管", "蠕动泵", "预热盘管", "固定床反应器",
                  "氢气钢瓶", "减压阀", "质量流量计", "冷凝器", "收集瓶"]
EXPECTED_EDGES = [("原料瓶", "硅胶管"), ("硅胶管", "蠕动泵"), ("蠕动泵", "预热盘管"),
                  ("预热盘管", "固定床反应器"), ("氢气钢瓶", "减压阀"),
                  ("减压阀", "质量流量计"), ("质量流量计", "固定床反应器"),
                  ("固定床反应器", "冷凝器"), ("冷凝器", "收集瓶")]


def _edges(spec):
    pid = {p["id"]: p.get("label", "") for p in spec.get("parts") or []}
    return [(pid.get(c.get("from")), pid.get(c.get("to")))
            for c in spec.get("connections") or []]


class ExtractionRegression(unittest.TestCase):
    def test_apparatus_chain_exact_graph(self):
        spec, report = E.build_spec(CASE, FIXTURE, None)
        labels = [p.get("label") for p in spec.get("parts") or []]
        self.assertEqual(len(labels), 10, labels)
        self.assertEqual(sorted(labels), sorted(EXPECTED_PARTS))
        edges = _edges(spec)
        self.assertEqual(len(edges), 9, edges)
        self.assertEqual(sorted(edges), sorted(EXPECTED_EDGES))
        self.assertEqual(len(spec.get("stages") or []), 5)
        for p in spec.get("parts") or []:
            self.assertNotRegex(p.get("label", ""), r"(连接到|下端接|顶部连接|经|接)")

    def test_feed_direction_not_reversed(self):
        spec, _ = E.build_spec(CASE, FIXTURE, None)
        edges = _edges(spec)
        self.assertNotIn(("固定床反应器", "氢气钢瓶"), edges)
        self.assertNotIn(("氢气钢瓶", "冷凝器"), edges)

    def test_zero_connections_is_blocked(self):
        root = tempfile.mkdtemp(prefix="apparatus_verify_neg-")
        case = {"case_id": "zero-connections", "task": "negative", "title": "zero connections",
                "output_contract": {"装置清单": {}, "连接关系": {}}, "materials": ["protocol.md"]}
        with open(os.path.join(root, "protocol.md"), "w", encoding="utf-8") as fh:
            fh.write("本实验使用固定床反应器（内径未给出）。\n")
        cpath = os.path.join(root, "case.json")
        with open(cpath, "w", encoding="utf-8") as fh:
            json.dump(case, fh, ensure_ascii=False)
        out, work = os.path.join(root, "out"), os.path.join(root, "work")
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "run_case.py"),
                        "--case", cpath, "--materials", root, "--out", out, "--work", work],
                       check=True, cwd=SCRIPTS, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with open(os.path.join(out, "result.json"), encoding="utf-8") as fh:
            result = json.load(fh)
        self.assertEqual(result.get("status"), "blocked")
        self.assertFalse(result.get("selfcheck", {}).get("ok"))
        self.assertIn("no_connections",
                      [e.get("code") for e in result.get("selfcheck", {}).get("errors", [])])
        self.assertFalse(os.path.exists(os.path.join(out, "route.svg")))
        self.assertFalse(os.path.exists(os.path.join(out, "route.png")))


if __name__ == "__main__":
    unittest.main()
