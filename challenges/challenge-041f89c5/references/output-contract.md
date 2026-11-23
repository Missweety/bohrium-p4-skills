# 输出契约（proposal-novelty-auditor v1.1.0）

运行时以 `case.json.output_contract` 为准；字段名按小写、去 `_`/`-`/空格 归一后匹配。
契约未定义口径的字段写入
`{"note": "输入契约未定义该字段的取值口径；保留字段名与空值说明，不补造内容。"}`。
所有相对路径相对材料根目录；哈希为 sha256。

## 标准字段

| 标准字段 | 常见契约别名 | 内容与完成标准 |
|-|-|-|
| `case_id` | caseId / id / task_id | 与输入一致 |
| `status` | run_status / state | `ok` / `partial` / `blocked` |
| `summary` | conclusion / abstract | 来源数、纳排数、创新判定、可行性结论一句话 |
| `problem_statement` | problem / research_question / question_definition | 对象/变量/基线/预期结论/可证伪条件及缺失项 |
| `scope` | scope / search_scope / boundary | 检索与证据范围、时间窗、语种、类型、来源数 |
| `sources` | sources / records / literature | 来源清单（ID、文件、定位、元数据、摘要、可读性） |
| `screening` | screening / eligibility / decisions | 逐条决定、理由码、理由、证据定位、是否需人工 |
| `reason_codes` | reason_codes / codebook | 理由码 → 中文口径 |
| `evidence_matrix` | evidence_matrix / comparison_matrix / matrix | 任务/方法/数据/评价/结论/可比较性及不可比原因 |
| `novelty` | novelty / innovation / novelty_assessment | 每条创新陈述的类型、最近工作、判定、`scope`、证据 |
| `feasibility` | feasibility / conditions / risk | 每条前提的状态、来源、影响、缓解；条件结论与风险 |
| `conflicts` | conflicts / contradictory_evidence | 相反结论、元数据冲突、仲裁与未决项 |
| `gaps` | gaps / research_gaps / opportunities | 空白候选与依据（`bounded=true`） |
| `uncertainty` | uncertainty | 缺摘要、来源不足、未决冲突、无文本层等 |
| `limits` | limits | 未覆盖范围；`partial`/`blocked` 时必须非空 |
| `validation` | validation / checks | 机检项（`check`/`pass`/`detail`） |
| `changes` | changes | 相对上一版变化（首版为空） |
| `assumptions` | assumptions | 材料即证据范围、摘录式抽取等前提 |

## 判定枚举

- 来源决定：`include` / `exclude` / `maybe`
- 理由码：`IN_TOPIC_MATCH`、`EX_YEAR_OUT_OF_WINDOW`、`EX_EXCLUDE_TERM`、`EX_TYPE_MISMATCH`、
  `REV_YEAR_MISSING`、`REV_WEAK_TOPIC_MATCH`、`REV_NO_TOPIC_MATCH`、`REV_METADATA_INCOMPLETE`
- 可比较性：`comparable` / `partially_comparable` / `not_directly_comparable`
- 创新类型：`method` / `data` / `scenario_transfer` / `conclusion_revision` / `unclassified`
- 创新判定：`covered` / `partially_covered` / `uncovered_within_scope` / `unknown`
- 前提状态：`supported` / `assumed` / `unsupported` / `unknown`
- 可行性结论：`feasible_within_scope` / `conditionally_feasible` / `not_supported` / `unknown`

## 机检项（`validation.checks`）

1. `every_source_screened` — 每个可读来源都有决定；
2. `every_decision_has_reason_code` — 理由码均在字典内；
3. `every_matrix_row_has_locator` — 矩阵每行有来源文件与页/行定位；
4. `novelty_has_scope` — 每条创新判定都有 `scope`，且无全局新颖性断言；
5. `feasibility_premises_stated` — 每条前提都有状态，未知项显式列出；
6. `supported_premises_cite_source` — 状态为 `supported` 的前提必须带来源文件与逐字片段；
7. `conflicts_registered` — 相冲突的结论已登记或说明无冲突；
8. `sources_traceable` — 每个来源可回溯到材料文件与定位；
9. `contract_fields_present` — 契约字段全部出现。

## 交付物

| 文件 | 必需内容 |
|-|-|
| `evidence_matrix.csv` | 来源、任务、方法、数据、评价、结论、可比较性、定位、抽取方式 |
| `novelty.csv` | 创新陈述、类型、最近工作、判定、scope、证据、是否需人工 |
| `feasibility.csv` | 前提、类别、状态、来源/假设、影响、缓解 |
| `conflicts.csv` | 类型、涉及来源、双方片段、仲裁、是否未决 |
| `report.md` | 问题拆解、纳排、矩阵、创新、可行性、冲突/空白、自查 |
| `run_manifest.json` | 版本、输入哈希、计数、校验结果 |
