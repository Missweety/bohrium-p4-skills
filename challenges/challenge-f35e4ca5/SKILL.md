---
name: reading-01-figure-table-parsing
description: Parse scientific figure captions and all supplied tables into structured data with units, precision and error ranges, and anchor every extracted value to a verbatim quote. Use for 科研图表解析 / figure-table extraction: parses axis labels/scale/units from text, table headers/rows from Markdown/CSV/TSV/XLSX, caption sample sizes and significance marks, and registers each supplied image's metadata. Pixel-level digitization/OCR is explicitly out of scope and reported as a gap, never fabricated.
version: 1.3.0
---

# 科研图表解析

## 用途与适用条件

让 Agent 在 3 个固定科研案例上，把每例给出的原图片与全部原表解析成带单位、精度和误差范围的结构化数据，并让每个数值都能回指到材料中的逐字引文与行列/段落锚点。图片本身只登记文件名、格式、宽高与哈希；刻度/图例/数据点的像素读数不在本 Skill 能力内，明确列为缺口。

**适用条件**：输入目录含任务说明与科研材料；材料为可抽取文本的 PDF/TeX/DOCX/Markdown，或 CSV/TSV/XLSX 原表与图片。

**不适用**：要求从图片像素数字化曲线、OCR 扫描件、联网检索或生成新数据。此类按「异常处理」如实降级，不猜测。

## 调用方式

```bash
python3 /skills/weekly-skill/scripts/run_case.py --input /input --output /app/output --work /app/work
```

**这一条命令即产出完整且已自检的结果**：每个请求字段都有一行、已带逐字引文与锚点、状态已判定，`output_contract` 声明的必填字段全部到位。**你不需要再手写判定文件。**

产物：`/app/output/result.json`（契约结果，含 `case_id`）、`/app/work/review_sheet.json`（紧凑复核表，供可选抽检）、`/app/work/doc.json`（页/节/句/数值/表/图注）、`/app/work/field_results.json`（字段表逐条结果）、`/app/work/audit.json`（独立复核报告）。

## 输入

/input/case.json（案例与任务说明入口，运行时实际输入）; task.md（题面，运行时实际输入）; 每例给出的原图片及全部原表（组织方输入修订 v2 明确的必做对象）; 实际 PDF 科研材料（PDF parsing receives the actual PDF without a pre-extracted answer layer，无预抽取答案层）; environment/resources.yaml（资源入口，bundled files 相对于该目录）; 3 个固定科研案例由评测平台提供，参赛者不自带测试案例

材料分层处理：

- **正文**：PDF/TeX/DOCX/Markdown/TXT → 页、节、句、坐标轴声明、图注与数值。
- **原表**：Markdown 管道表、`.csv`/`.tsv`、`.xlsx`（标准库解压 + sharedStrings，不依赖 openpyxl）→ 表头角色（x 轴/数值/误差/显著性）、行与单元格。
- **图片**：`.png/.jpg/.jpeg/.gif/.bmp/.webp` → 仅登记格式、宽高、字节数与 sha256；`pixel_reading=not_performed`，不输出臆造刻度或数据点。
- **目标字段表**：`target-fields.json` 的 `fields[*].description` 决定要抽什么；图表结构可确定回答的字段优先走确定性取值（轴/表/图注），否则走词表抽取。

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

- **不要通读 doc.json / 原文全文**（token 预算不够），只看这张表。
- 抽检只看两件事：该行 `value` 是否逐字出现在同一行 `quote` 里；`paragraph_id` 是否指向材料中真实存在的位置。
- 发现问题才改 `result.json` 里那一行，并在 `change_log` 记一笔。

### 交付纪律

- **每条 `reported` 的引文必须逐字包含 `value`**：value 不是引文的逐字片段就是错的。
- **不确定就判 `not_reported`**，不要用近似句凑数；**字段缺失不等于 0**。
- 铁律：**猜出来的值不算抽取；引文逐字命中不等于语义正确。**

## 抽取口径

### 必须做

- 其余 8 条见 `resources/extraction_protocol.md`

### 禁止

- 其余 6 条见 `resources/extraction_protocol.md`

完整口径清单见 `resources/extraction_protocol.md`。

### 证据粒度要求

图表编号/子图编号 + 坐标轴与刻度位置 + 数值与单位 + 页码/段落/图注定位（每个数值回指到图中具体位置与读取依据）

## 异常处理

| 情况 | 处置 |
|-|-|
| 只有 task.md / case.json，没有材料 | `status=failed`，`uncertainty` 说明没有可解析正文，不进入无意义抽取 |
| PDF 文件头损坏/非 PDF | 判 `tier=unreadable` 且 `status=failed`，不把 0 结果报成 success |
| 材料只有图片 | `status=partial`，登记图片元数据并明确"像素读数未执行"缺口 |
| 文本为 GBK/UTF-16 | 按 UTF-8→GB18030→UTF-16 解码，引文保持原文，不乱码 |
| 表格分隔行 `|-|-|` | 识别为分隔行，不当作数据行计数 |
| 扫描件无文本层 | `extraction_failed` 并说明人工接管位置，不 OCR 编造 |
| 输出目录已存在 | 覆盖本次产物；表格/图片清单与 result 保持一致 |

遇到材料缺失、无法判断、冲突、部分完成、运行失败等情形，按对应状态如实标注，不得静默跳过或用推测值填充；状态词表见 `resources/extraction_protocol.md`。

## 自查方法

```bash
python3 /skills/weekly-skill/scripts/audit_result.py --result /app/output/result.json \
    --case /input/case.json --doc /app/work/doc.json
```

确认契约齐备、锚点可定位、引文逐字命中、数值保真、状态诚实、边界三件套齐备。可核验指标与完整清单见 `resources/acceptance_checklist.md`。

## 限制与依赖

- 语义等价性脚本**无法**判定：脚本保证「有据可查」，是否答对由你抽检复核。
- 版式解析依赖 PDF 文本层；扫描件输出 `extraction_failed` 并说明人工接管位置。
- 跨页表格只能定位到「页 + 表 + 行」，续表行归属由模型判断并记入 `uncertainty`。
- 预算有限（64 次请求 / 900 秒），脚本一次成型，勿反复重跑全文抽取。
- **不做图片像素读数**：不 OCR、不做坐标轴像素标定、不数字化曲线；图片只登记元数据，相关字段标 `not_reported` 并在 `parsed.extraction_gaps` 写明 `image_pixel_reading`。
- 纯 Python 3 标准库，无第三方依赖、无网络请求；有 poppler 则版面更佳，缺失自动降级并在 `coverage.tier` 标注层级。词表见 `resources/field_lexicon.json`，方法见 `references/method.md`。

## 最小调用示例（合成示例，非正式案例）

随包 `examples/` 提供可直接运行的材料：`case.json`、`paper.md`（图注 + 坐标轴声明）、`table_dose.csv`（4 行原表）、`target-fields.json`（7 个字段）。在任意 cwd 用绝对路径运行：

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --input /skills/weekly-skill/examples --output /tmp/fig_out --work /tmp/fig_work
```

本机实测（示例材料，非正式案例）：`status=success`、`tier=plain-text`；表格 1 张 / 4 行，
坐标轴 2 条、图注 1 条、数值 5 个；7 个字段全部 `reported`（x 轴 `log`、单位 `µM`、y 轴 `%`、
`n=6`、dose 10 → `64.3`、dose 100 → `**`、误差 `3.8`）；16 条证据、4 个来源；
独立复核 `pass=true`（113 个数值可回溯）。以上数字只说明链路可跑通，不代表正式案例结果或分数。

## 改动记录

- **1.3.0**（2026-11-25）工程修复：修正"只有 task.md 时 `primary=None` 崩溃"；Markdown 单横线
  分隔行不再计入数据行；文本按 UTF-8→GB18030→UTF-16 解码；损坏/非 PDF 从 `success` 改为
  `failed` 且 `tier=unreadable`；新增 CSV/TSV/XLSX 原表解析（纯标准库）与图片元数据登记；
  新增图表结构确定性取值（轴 scale/unit/label、图注 n、表格单元格/误差/显著性），
  样例 7/7 字段 `reported`；无正文时不再崩溃并按 partial/failed 诚实降级；去掉文档中
  "像素标定/曲线数字化"的夸大表述，改为明确缺口；`text_path` 改为相对文件名，避免绝对路径；
  更新可运行 `examples/` 与命令为 `python3` 绝对路径。
- **1.2.0**（2026-11-23）加入逐字段证据、独立复核与契约映射。
- **1.1.0**（2026-11-22）首版可运行抽取链路。
