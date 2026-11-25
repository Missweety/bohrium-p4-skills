---
name: reading-03-multi-document-comparison
version: 1.3.0
description: Align multiple papers onto one field definition and produce a comparison matrix. Use for 多文档比较与整合 / cross-document synthesis: every cell carries source document id and paragraph id, comparability of task, metric, units and dataset is tested first, and non-comparable or unreported cells are preserved rather than dropped.
---

# 多文档比较与整合

## 用途与适用条件

让 Agent 在 3 个固定多论文案例上，把同一研究问题的多篇论文落到同一套字段定义上，产出带逐格来源锚点、经可比性检验的比较矩阵/方法矩阵/整合报告，而不是单篇摘要。

**适用条件**：输入目录含任务说明与科研材料；材料为可抽取文本的 PDF/TeX/DOCX/Markdown，或含可解析的表格与图注。

**不适用**：扫描件无文本层、材料缺失、需联网检索、或要求生成新数据。此类按「异常处理」如实降级，不猜测。

## 调用方式

```bash
python3 /skills/weekly-skill/scripts/run_case.py --input /input --output /app/output --work /app/work
```

**这一条命令即产出完整且已自检的结果**：每个请求字段都有一行、已带逐字引文与锚点、状态已判定，`output_contract` 声明的必填字段全部到位。**你不需要再手写判定文件。**

产物：`/app/output/result.json`（契约结果，含 `case_id`）、`/app/output/comparison_matrix.csv`（逐格比较表）、`/app/work/review_sheet.json`（紧凑复核表，供可选抽检）、`/app/work/docset.json`（逐文档页/节/句/数值/表/图注）、`/app/work/field_results.json`（字段表逐条结果）、`/app/work/comparison.json`（比较矩阵 + 可比性判定）、`/app/work/audit.json`（独立复核报告）。

### 多文档比较流程（本题核心）

1. 读 `/input/comparison-workorder.json`，取 `documents[].source_document_id` 与 `file` 的对应关系；文件缺失记入 `uncertainty` 而不是静默跳过。
2. 每篇文档独立抽取，再按**同一份** `target-fields.json` 逐字段取值；每一行都带 `source_document_id` 与 `document_file`。
3. 用 `scripts/compare_docs.py` 生成 `comparison_matrix`：`matrix`（字段 × 文档）、`rows[].relation`（agree / differ / unit_mismatch / single_source / none）、`comparability`（task / metric / units / material / pollutant / budget 六项）、`comparable_subset`、`conflicts`（含归因或 `unattributed`）、`unreported`。
4. 单位不同不换算、污染物不同不合并、样本量不同不合并统计；这些判断写进 `comparability` 并在 `uncertainty` 说明。
5. 同时写出 `comparison_matrix.csv`（每文档三列：value / unit / paragraph_id），便于逐格复核。

## 输入

/input/comparison-workorder.json（组织方修订 v2 指定的真实工作单输入）; /input/case.json（运行时实际输入）; task.md（题面，运行时实际输入）; 全部 supplied corpus documents（语料论文文档，每篇含 source_document_id 与段落编号）; environment/resources.yaml（资源与预装工具清单）

## 输出契约

`result.json` 必须包含 `case.json` 中 `output_contract` 声明的**全部**字段，外加 `case_id`、`status`、`sources`、`uncertainty`、`change_log`。字段集合以运行时契约为准，本 Skill 不硬编码字段名。

| 内容 | 本题落地 |
|---|---|
| 主结果 | 按题目字段表抽出的结构化结果（每个 field_id 一条） |
| 证据 | 每条结果的页码 / 段落 / 表格行列锚点 + 逐字引文 |
| 边界 | 未报告、冲突、抽取失败的字段分别标注，可人工接管 |

### 证据锚点规范

每个结论性字段都要带锚点，格式：

```
p.N            第 N 页（1-based，PDF 页序，非印刷页码）
sec.X          第 X 个章节单元
sent.K         该单元第 K 句
tab.M/row.K    第 M 张表第 K 行
cap.M          第 M 条图注/表注
```

锚点要细到**第二个人能独立抽查**：必须附**逐字引文**，且引文能在该锚点位置找到。

### 状态取值

`status` 只取 `success` / `partial` / `failed`。字段级状态区分：

- `reported` —— 原文确有对应内容，已附锚点与引文
- `not_reported` —— 原文未报告该字段。**不等于 0，不等于空字符串，不等于 null 充数**
- `source_conflict` —— 原文多处给出互斥内容，已列出冲突位置
- `extraction_failed` —— 材料不可读或抽取链路失败

### 可选抽检（默认不必做）

`/app/work/review_sheet.json` 是紧凑复核表：每个字段一行，附 ≤3 条候选引文。

- **不要通读 docset.json / 原文全文**（token 预算不够），只看这张表。
- 抽检只看两件事：该行 `value` 是否逐字出现在同一行 `quote` 里；`paragraph_id` 是否指向材料中真实存在的位置。
- 发现问题才改 `result.json` 里那一行，并在 `change_log` 记一笔。

### 交付纪律

- **每条 `reported` 的引文必须逐字包含 `value`**：value 不是引文的逐字片段就是错的。
- **不确定就判 `not_reported`**，不要用近似句凑数；**字段缺失不等于 0**。
- 铁律：**猜出来的值不算抽取；引文逐字命中不等于语义正确。**

## 抽取口径

### 必须做

- 读取工作单与全部语料文档，构建 common-field comparison matrix
- 每个取值带精确的 source_document_id 与 paragraph_id
- 其余 6 条见 `resources/extraction_protocol.md`

### 禁止

- 单篇论文摘要不满足多文档比较要求
- 不得把不同数据集或不同染料/物质池化合并（do not pool unlike datasets or dyes）
- 其余 4 条见 `resources/extraction_protocol.md`

完整口径清单见 `resources/extraction_protocol.md`。

### 证据粒度要求

source_document_id + paragraph_id（单元格级锚点），并随值记录单位/数据集/指标口径

## 异常处理

遇到材料缺失、无法判断、冲突、部分完成、运行失败等情形，按对应状态如实标注，不得静默跳过或用推测值填充；状态词表见 `resources/extraction_protocol.md`。

## 自查方法

```bash
python3 /skills/weekly-skill/scripts/audit_result.py --result /app/output/result.json \
    --case /input/case.json --docset /app/work/docset.json
```

确认契约齐备、锚点可定位、引文逐字命中、数值保真、状态诚实、边界三件套齐备、必填字段不为占位空壳（A10）。可核验指标与完整清单见 `resources/acceptance_checklist.md`。

## 限制与依赖

- 语义等价性脚本**无法**判定：脚本保证「有据可查」，是否答对由你抽检复核。
- 版式解析依赖 PDF 文本层；扫描件输出 `extraction_failed` 并说明人工接管位置。
- 跨页表格只能定位到「页 + 表 + 行」，续表行归属由模型判断并记入 `uncertainty`。
- 预算有限（64 次请求 / 900 秒），脚本一次成型，勿反复重跑全文抽取。
- 纯 Python 3 标准库，无第三方依赖、无网络请求；有 poppler 则版面更佳，缺失自动降级并在 `coverage.extraction.tier` 标注层级。词表见 `resources/field_lexicon.json`，方法见 `references/method.md`。

## 变更记录

| 版本 | 日期 | 改动 | 触发证据（真实运行） |
|---|---|---|---|
| 1.3.0 | 2026-11-25 | 多文档：按工作单逐篇抽取并生成 `comparison_matrix`（字段×文档、可比性六项、可比子集、冲突归因、CSV），每行带 `source_document_id` | 1.2.0 只抽取 `primary` 一篇，DOC-B 完全未读；`comparison_matrix` 输出 `{"status":"not_reported"}` 且 audit 仍 pass |
| 1.3.0 | 2026-11-25 | 单位白名单补 `mg/g`、`mg/L`、`g/L`、`ppm` 等比值单位 | `45.2 mg/g` 的 unit 被丢弃为 `None` |
| 1.3.0 | 2026-11-25 | 名称型取值清洗（去章节标题行 / 换行）与中文短语裁剪 | `adsorbent` 取值为 `"Abstract\nRice-husk"`；中文整行被当成取值 |
| 1.3.0 | 2026-11-25 | 否定式守卫：`was not tested/reported` → `not_reported` | `regeneration` 取到锚词本身（原文 "regeneration was not tested"） |
| 1.3.0 | 2026-11-25 | 概念词典补中文锚点（生物炭/投加量/去除率/等温线等） | 中文论文 9 个字段全部 `not_reported` |
| 1.3.0 | 2026-11-25 | 文本编码探测 `utf-8-sig → utf-8 → gb18030`，并记录 `encoding` | GBK 论文被按 utf-8 解码成替换字符，正文全坏 |
| 1.3.0 | 2026-11-25 | 修复文档首行正文被丢弃（`split_units`），单行文档不再为空壳 | GBK 单行文档 units 文本为空、sentences=0 |
| 1.3.0 | 2026-11-25 | `audit_result.py` 新增 `--docset` 多文档索引与 A10 占位/空壳检测 | 比较矩阵为空、`case.json` 损坏时仍报 success |
| 1.3.0 | 2026-11-25 | 0 个字段抽到 / `case.json` 不可解析时状态降级为 `partial` | 上述两情形原为 `success` |
