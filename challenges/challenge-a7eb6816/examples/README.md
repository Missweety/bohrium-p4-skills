# 示例：论文摘要 → 公众科普（**SYNTHETIC / 合成示例**）

> **重要：本目录全部内容为人工合成的演示数据，不对应任何真实论文、机构或比赛隐藏用例；文中数值与结论均为虚构，仅用于说明流程。** 本示例不构成任何官方评分或效果声明。

## 1. 输入

`/tmp/transform-demo/input/`：

- `case.json`（两种契约形态都测过）：

```json
{"case_id": "syn-001", "output_contract": ["transform_md", "preservation_map", "glossary"]}
```

```json
{"case_id": "syn-dict", "output_contract": {
  "transform_md": "markdown", "preservation_map": "rows",
  "glossary": "table", "word_count": "int"}}
```

- `task.md`（会被 extract 跳过）：`Transform the study into a public science article.`
- `study.md`（节选；本示例运行时的 `sources.json` 中记为 `doc.3`。注意：`doc.N` 按文件名字母序编号，增删文件后编号会变，一律以当次 `sources.json` 为准）：

```markdown
## Abstract
Recovery was 92% in the control group and 71% in the cooled group
(difference 21 percentage points, n = 24 per group). The result is an
association, not proof of causation.

## Results
The 95% confidence interval for the difference was 8 to 34 percentage points.

## Limitations
Only one cell line was tested, and the sample size was small. The study
cannot establish causality or rule out batch effects.
```

- 另有 `paper.pdf`（同样内容的单页 PDF）、`table.csv`、`page.html`、`report.docx`，用于覆盖 PDF/DOCX/CSV/HTML 抽取路径；TeX 路径另用独立合成片段验证（`\section`/`\cite` 转文本）。

## 2. plan.json（节选）

```json
{
  "audience": {"who": "对生命科学感兴趣的普通公众", "prior_knowledge": "none"},
  "genre": "popular_science",
  "target_length": {"max_words": 600, "max_chars": 1200},
  "sections": [
    {"id": "s3", "heading": "关键结果", "role": "finding",
     "paragraphs": ["对照组回收率为 92%，冷却组降至 71%，两者相差 21 个百分点。"]},
    {"id": "s6", "heading": "需要保留的边界", "role": "limitations",
     "paragraphs": ["作者提醒，这只是一项初步结果：只测试了一种细胞系，样本量较小，无法确立因果关系，也不能排除批次效应。"]}
  ],
  "claim_evidence": [
    {"id": "c1", "kind": "number",
     "claim": "对照组回收率为 92%，冷却组降至 71%，两者相差 21 个百分点。",
     "anchor": "doc.3 p.1 sec.2 para.2",
     "quote": "Recovery was 92% in the control group and 71% in the cooled group (difference 21 percentage points, n = 24 per group).",
     "section": "s3", "strength": "association", "source_strength": "association"}
  ],
  "glossary": [
    {"term": "trypan blue", "plain": "一种常用的细胞活性染色法", "action": "expand"},
    {"term": "置信区间", "plain": "估计结果可能波动的范围", "action": "expand"},
    {"term": "细胞系", "plain": "实验室中持续培养的一类细胞", "action": "keep"}
  ],
  "removals": [
    {"removed": "补充材料中的表格（与正文数值重复）", "source_anchor": "doc.4 p.1",
     "reason": "表格数值已在正文引用，保留会打断科普叙事", "risk": "low"}
  ]
}
```

## 3. 命令

```bash
python3 scripts/extract_sources.py --input /tmp/transform-demo/input --out /tmp/transform-demo/work/sources.json
python3 scripts/build_transform.py --plan /tmp/transform-demo/work/plan.json \
  --sources /tmp/transform-demo/work/sources.json --case /tmp/transform-demo/input/case.json \
  --out /tmp/transform-demo/out --work /tmp/transform-demo/work
python3 scripts/selfcheck.py --case /tmp/transform-demo/input/case.json \
  --out /tmp/transform-demo/out --sources /tmp/transform-demo/work/sources.json
```

## 4. 观察到的输出（合成样例）

`transform.md`（节选）：

```markdown
# 更冷的保存，真的能保住更多细胞吗？

## 关键结果

对照组回收率为 92%，冷却组降至 71%，两者相差 21 个百分点。

## 需要保留的边界

作者提醒，这只是一项初步结果：只测试了一种细胞系，样本量较小，无法确立因果关系，也不能排除批次效应。补充材料还提到，一个批次被排除在主分析之外。结论仍需重复实验验证。
```

`result.json` 摘要（实际运行结果）：

- `status = success`，`issues = []`；
- 7 条 claim 全部 `quote_verified = True`，`verification_rate = 1.0`；
- 9 个数值 token 全部可追溯：`92%`、`71%`、`21`、`24`、`-80`、`7`、`95%`、`8`、`34`；
- `metrics`：`chars=365`、`words=289`、`sentences=16`、`avg_sentence_chars=22.8`、`jargon_per_1000_chars=8.2`（由 `transform.md` 复算）；
- `preservation_map.csv` 7 行，`glossary.csv` 3 行，`omissions` 中被 `doc.4 p.1` 删除项覆盖。

`selfcheck.py`：`{"ok": true, "passed": 29, "failed": 0, "warnings": 0}`，退出码 0。

不同机器上的字符/词数会因文本微调而变化；以当次 `result.json` 与 `checks.json` 为准。

## 5. 异常探针（合成）

| 探针 | 构造 | 观察到的结果 |
|---|---|---|
| 不支持的体裁 | `genre="opera_libretto"` | `status=partial`，`unsupported_genre` warn，`uncertainty` 记录体裁假设；无 traceback |
| 数字无来源 | 正文加“另有 3 个样本未纳入分析” | `status=partial`，`unsupported_number` error；`selfcheck` 硬失败（退出码 1） |
| 引文被改 | 把 `92%` 的引文改成 `99%` | `status=partial`，`quote_unverified` error；`preservation_map` 标 `False`；无 traceback |
| 空输入 | `/input` 只有 `case.json` 与 `task.md` | `extract_sources.py` 退出码 2；`build_transform` 有 plan 时 `partial`，无 plan 时 `failed`；不编造正文 |
| 源文冲突 | 两段近似文字分别写 92% 与 87% | `status=partial`，`source_conflict` warn，`uncertainty.needs_human=true` |
| 契约为对象/列表 | 两种 `output_contract` | 所有键写入 `result.json` 顶层与 `contract_fields`；`selfcheck` 通过 |

## 6. 注意

- 本目录只用于演示字段与流程。真实任务必须使用 `/input` 的材料，逐字复制引文与锚点。
- 示例中的 `status=success` 只说明该合成样例通过了脚本核验，不代表官方 rubric 得分。
