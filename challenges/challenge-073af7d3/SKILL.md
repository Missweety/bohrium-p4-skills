---
name: research-trend-evidence
description: 在给定文献集上做"可核对的研究前沿与趋势分析"：先筛选并去重，再按年份统计产出与阶段，按共词连通分量追踪主题演化，按"有全文>年份更早>结果句更多"而非被引数选各阶段代表作，把空白区分为作者明说缺口与证据稀薄主题，所有趋势句附来源编号与年度表，缺年份/缺全文/检索未覆盖逐项报告，不把检索遗漏当空白。
version: 1.1.1
license: MIT
---

# 研究前沿与趋势分析：年度分布 → 主题演化 → 代表作 → 空白

"前沿"不是一个列表，而是**可复算的时间切片 + 可回链的主题变化 + 口径明确的代表作**。
本技能把趋势判断压到文献集自身的年度统计与共词结构上，避免"关键词热=趋势""被引高=代表作"。

## 何时使用

触发：给定跨年份文献集（PDF/DOCX/Markdown/TXT/BibTeX/题录表），要求"分析研究趋势 / 前沿 /
主题演化 / 阶段划分 / 各阶段代表作 / 研究空白 / 年度产出"。

不触发：单篇精读、文献翻译、投稿选刊、纯检索发现（本技能不用外部检索补全）；只有一句主题
而无文献集时，先说明缺少语料，不编造年度分布。

## 输入

读取 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与 `task.md`。字段别名容错：

| 用途 | 字段（含别名） |
|-|-|
| case 标识 | `case_id` / `id` / `task_id` |
| 分析主题/问题 | `research_question` / `question` / `topic` / `goal` |
| 文献材料 | `materials` / `files` / `documents` / `literature` / `corpus` / `papers` |
| 纳入/排除 | `inclusion_criteria` / `include` / `纳入标准`，`exclusion_criteria` / `exclude` |
| 年份 | `year_from` / `start_year`，`year_to` / `end_year` |
| 全文要求 | `require_fulltext` / `fulltext_required` |
| 输出契约 | `output_contract` / `expected_output` / `schema` |

支持格式与失败口径同综述流水线：PDF（`pdftotext`，回退 `pypdf`）、DOCX、MD/TXT、BibTeX、
题录 CSV/JSON/JSONL；无文字层、损坏、未知类型进 `failures`。固定 3 个平台案例无需本地准备。

**题录表按行取文**：CSV/JSON/JSONL 的每条记录只用本行字段（题名、摘要、正文/全文列）抽取
结果句与引文，绝不借用同一文件其他行；只有行内显式全文列超过 400 字符才计为"有全文"。
`output_contract` 可为字典（字段名→类型）或数组（字段名，或 `{name,type}` 对象），
`result.json` 会按这些名字回填，而不是写一个空的 `fields`。

## 一条命令

```bash
python3 scripts/run_case.py --case /input/case.json --work /app/work --out /app/output --mode trends
```

| 步骤 | 命令 | 产物 | 关键点 |
|-|-|-|-|
| 1 | `kernel.py init` | `work/contract.json` | 固定契约与 case_id |
| 2 | `engine.py index` | `work/records.json` | 年份归一、DOI、摘要、全文长度、哈希；失败单列 |
| 3 | `engine.py screen` | `work/screening.json` | 去重 → 年份 → 全文 → 排除/纳入词；原因留痕 |
| 4 | `engine.py matrix` | `work/matrix.json` | 结果句、局限、证据强度、逐字引文 + 页/段 |
| 5 | `engine.py themes` | `work/themes.json` | 主题连通分量、冲突配对、空白候选 |
| 6 | `engine.py trends` | `work/trends.json` | 年度分布、阶段切分、各阶段代表作、新兴词 |
| 7 | `engine.py synthesize --mode trends` | `output/report.md` | 年度表 + 主题演化 + 代表作口径 + 空白 |
| 8 | `engine.py verify --mode trends` | `work/checks.json` | 筛选闭合、引文逐字、年度可复算、引用可解析 |
| 9 | `engine.py emit --mode trends` | `output/result.json` | 契约字段 + `report.md`/`matrix.csv`/`screening.csv` |

## 输出

- `report.md`：`研究问题与证据范围 → 年度产出与阶段（逐行可复算）→ 主题演化与阶段代表作 →
  研究空白 → 代表作口径 → 不确定性与限制`。
- `result.json`：`research_product`（含 `trends.distribution`、`trends.stages`、`themes`）、
  `evidence_matrix`、`screening`、`uncertainty`、`checks`、`failures`、`limits`。
- `matrix.csv` / `screening.csv`：逐篇字段与逐条排除原因。

`research_product.trends.distribution` 形如
`[{"year":2019,"count":3,"sources":["S02","S05","S07"]}]`；
`stages` 含 `years/count/top_terms/representative[{source_id,title,year,basis}]`。

字段细节见 `references/output-contract.md`，方法见 `references/method.md`，
合成示例见 `references/example-output.md`（明确标注示例）。

## 失败与降级

| 情况 | 处理 | `status` |
|-|-|-|
| 缺年份 | 保留在语料中并标 `year_missing`；不进年度表与阶段划分，报告与 `uncertainty.missing_year` 列出 | `partial` |
| 年份跨度不足 3 个不同年份 | 不强行分 3 阶段，按实际年份输出并在 `limits` 说明 | `partial` |
| 某年 0 篇 | 年度表不补 0 行，避免制造"断崖"；在正文说明空档 | 保持 |
| 缺全文/仅有摘要 | 证据强度降级，主题与代表作只基于可用文本 | `partial` |
| 文献量过小（<5） | 不做"新兴/衰退"判断，`emerging_terms` 置空并写 `emerging_suppressed` | `partial` |
| 纳入后 0 篇 | 空结果 + 排除原因统计，不放宽标准 | `partial` |
| 检索未覆盖 | 报告明确"不能区分检索遗漏与真实空白" | 保持 |

## 自查

```bash
python3 scripts/engine.py verify --mode trends
python3 scripts/kernel.py check --out /app/output
```

关键机检项：筛选计数闭合、矩阵只含纳入文献、引文逐字（全文比对，题录表按本行文本核对）、
题录行文本来源 `row_scoped_text`、年度表可从来源编号复算（`year_counts_recomputable`）、
报告引用全部可解析、无材料外编号。

## 改动记录

- 1.1.1：按独立复审补修 6 处——① 全空题录行被纳入后回退读整文件（跨行污染回归），现跳过空行且
  题录/BibTeX 永不回退到整文件；② 报告把"排除+重复"重复计数，现分开写并附排除原因；③ 引文只比对
  前 80 字符，现全文逐字比对；④ 年度表不复算，新增 `year_counts_recomputable`；⑤ `## Results`
  混入结果句，现剥离标题标记；文档类文件不再因 <400 字符被误判"仅有摘要"；⑥ 全部缺年份时
  `year_stats_present` 误判失败、未知契约字段静默置 null；现分别修正并在 `limits` 写明。
  另：`.ris` 不再走 BibTeX 分支（避免死分支）、同文件 sha256 只算一次。
- 1.1.0：修复 5 处真实可复现缺陷（合成用例见 `SMOKE.md`）——
  ① 题录表按整文件取文导致跨行污染（两行得到同一批结果句/引文）；改为按行 `row_text`，
  `verify` 新增 `row_scoped_text` 并按行核对引文；② 指定 `year_from` 时缺年份记录被静默排除；
  改为保留并标 `year_missing`，进入 `uncertainty`；③ `output_contract` 为数组时输出 `fields:null`
  且契约字段丢失；改为字典/数组（含 `{name,type}`）都回填；④ `<5` 篇、`<3` 年、0 纳入时仍报
  `ok`；改为 `partial` 并写入 `limits`，短窗口不再输出"新兴主题"；⑤ Markdown 标题
  （`## Results`）截断摘要解析，导致误报缺摘要；已兼容标题并可回退摘要段。
- 1.0.0：首版。四条失分线：输入兼容（字段别名、多格式、题录表、无文字层）；
  输出契约（年度分布/阶段/代表作 + 标准 `report.md`）；可机检项（年度可复算、引文逐字、
  引用解析、筛选闭合）；降级路径（缺年份、跨度过短、样本过小、空结果分别落盘）。
