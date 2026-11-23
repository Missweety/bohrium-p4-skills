# 判定规则、阈值与字段 schema

本文档对应 `scripts/quality_appraise.py`，规则版本 `quality-appraise/1.0`。

## 1. 输入 schema

一行 = 一项研究的**一个适用域**的一次判断。

| 字段 | 必需 | 类型 | 说明 |
|-|-|-|-|
| `study_id` | 是 | string | 研究标识；同一研究的行必须一致 |
| `design` | 是 | enum | `rct` / `observational` / `diagnostic` / `systematic_review` |
| `domain` | 是 | string | 评价域；按设计归一（见第 3 节） |
| `judgement` | 是 | enum | `low` / `some_concerns` / `high` / `unclear` |
| `evidence_file` | 条件 | string | 非 `unclear` 时必需 |
| `evidence_locator` | 条件 | string | 非 `unclear` 时必需；写页码/章节/表格/图 |
| `quote` | 条件 | string | 非 `unclear` 时必需；逐字原文 |
| `note` | 建议 | string | 判断理由；`unclear` 时说明缺什么证据 |
| `study_title` | 可选 | string | 文献标题 |
| `reviewer` | 可选 | string | 评价人；用于复核追踪 |
| `overall_override` | 可选 | enum | 总体等级覆盖 |
| `overall_reason` | 条件 | string | 覆盖时必需且非空 |

支持 CSV/TSV/JSON/JSONL；CSV 分隔符自动识别 `,`、`;`、`\t`。
JSON 可为对象数组，或包含 `appraisals`/`rows`/`judgements`/`ratings` 等数组的对象。
一个目录下有多个评价表时，凡具备 `domain` 与 `judgement` 列的文件会被合并。

可选覆盖文件：

```csv
study_id,overall,reason
S1,high,外部效度存在严重问题
```

## 2. 词汇归一

### 2.1 判断

| 规范值 | 可接受写法（示例） |
|-|-|
| `low` | `low`、`low risk`、`low_risk`、`低`、`低风险` |
| `some_concerns` | `some concerns`、`some_concerns`、`moderate`、`中`、`部分担忧` |
| `high` | `high`、`high risk`、`高`、`高风险` |
| `unclear` | `unclear`、`no information`、`ni`、`unknown`、`not reported`、`不明确`、`证据不足` |

- `moderate` 映射为 `some_concerns`，并产生 `judgement_alias` 警告。
- 其他无法识别的值 → `invalid_judgement` 错误，该行不进入汇总。

### 2.2 设计

| 规范值 | 可接受写法（示例） |
|-|-|
| `rct` | `rct`、`randomized`、`randomised_controlled_trial`、`随机对照试验` |
| `observational` | `observational`、`cohort`、`case_control`、`cross_sectional`、`队列研究`、`病例对照` |
| `diagnostic` | `diagnostic`、`diagnostic_accuracy`、`dta`、`诊断准确性` |
| `systematic_review` | `systematic_review`、`meta_analysis`、`系统综述`、`荟萃分析` |

设计无法识别 → `unknown_design` 错误；保留原值展示，但不做适用域完整性判断。

## 3. 适用域与最小集合

| 设计 | 最小必填域 | 说明 |
|-|-|-|
| `rct` | `randomization_process` | 随机序列生成与分配隐藏 |
| | `deviations_from_intended_interventions` | 方案偏离、盲法、实施偏倚 |
| | `missing_outcome_data` | 失访、结局缺失 |
| | `measurement_of_outcome` | 结局测量与评估盲法 |
| | `selection_of_reported_result` | 选择性报告 |
| `observational` | `confounding` | 混杂控制 |
| | `selection_of_participants` | 参与者选择 |
| | `classification_of_interventions` | 干预/暴露分类 |
| | `missing_data` | 数据缺失 |
| | `measurement_of_outcomes` | 结局测量 |
| | `selection_of_reported_result` | 选择性报告 |
| `diagnostic` | `patient_selection` | 患者选择与谱偏倚 |
| | `index_test` | 待评价试验的实施与解读 |
| | `reference_standard` | 参考标准 |
| | `flow_and_timing` | 病例流程与时间间隔 |
| `systematic_review` | `search_strategy` | 检索策略 |
| | `study_selection` | 研究筛选 |
| | `data_collection` | 数据提取 |
| | `risk_of_bias_assessment` | 偏倚风险评估 |
| | `synthesis` | 证据合成 |
| | `reporting_completeness` | 报告完整性与发表偏倚 |

常见中文域（如"随机化过程""偏离既定干预""结局数据缺失""报告结果选择""混杂""参考标准"
"检索策略""数据提取"）会归一到对应规范域。设计不同、同名域含义不同（如 `missing_data`
与 `missing_outcome_data`）时，以该设计的映射优先。

必填域缺失 → `missing_domain` 错误。额外域保留，但产生 `domain_not_applicable` 警告。

## 4. 四态证据与等级

| 证据状态 | 等级 | 判定条件 |
|-|-|-|
| 明确存在且影响结论 | `high` | 原文直接描述该问题，且可定位 |
| 可能存在 | `some_concerns` | 有提示性证据但报告不完整；`note` 说明缺什么 |
| 明确未见迹象 | `low` | 原文明确描述且可核对，不是"没提到" |
| 证据不足 | `unclear` | 未报告、只有摘要、图表不可读、语言不可读等 |

硬规则：

- `unclear` 不是 `low`，不参与最差域排序，也不被默认降级。
- 非 `unclear` 必须同时有 `evidence_file`、`evidence_locator`、`quote`。
- 证据不全的非 `unclear` 行记 `insufficient_evidence` 错误，并**不计入域计数与 overall**；
  `unclear` 仍保留在计数中，用于说明"证据不足"。
- `quote` 必须逐字；`source_index.py verify` 只检查逐字存在，不检查语义支持。
- `quote` < 12 字符 → `short_quote` 警告。
- `locator` 只有数字（如 `3`）→ `locator_without_unit` 警告。

## 5. 汇总阈值

设某研究**该设计必填域内**的有效判断集合 `J`（额外域保留展示但不参与总体排序；
`unclear` 也不参与排序）：

```
severity(low) = 0
severity(some_concerns) = 1
severity(high) = 2

overall = argmax(severity(j) for j in J)
worst_domains = { d | severity(d) = max severity }
```

- `J` 为空且存在 `unclear` → `overall=unclear`，`overall_source=all_unclear`。
- 完全没有有效判断（例如非 `unclear` 行都缺证据而被排除）→ `overall=unknown`，
  `overall_source=no_valid_judgement`，并在 `overall_reason` 与 `uncertainty` 说明缺口。
- 覆盖规则：`overall_override` 必须是合法判断，且 `overall_reason` 非空；
  否则产生错误并忽略覆盖，保留最差域结果。
- 覆盖后 `overall_source=override`，`overall_reason` 原样保留，供复核。

## 6. 校验问题代码

| 代码 | 级别 | 触发条件 |
|-|-|-|
| `missing_study_id` | error | 行缺少 `study_id` |
| `missing_design` | error | 行缺少 `design` |
| `unknown_design` | error | 设计不在四类内 |
| `missing_domain` | error | 行缺 `domain`，或研究缺必填域 |
| `missing_judgement` | error | 行缺 `judgement` |
| `invalid_judgement` | error | 判断词汇非法 |
| `missing_evidence_file` | error | 非 `unclear` 但缺证据文件 |
| `missing_evidence_locator` | error | 非 `unclear` 但缺定位 |
| `missing_quote` | error | 非 `unclear` 但缺引文 |
| `insufficient_evidence` | error | 非 `unclear` 但证据文件/定位/引文不全；该行不计入域计数与 overall |
| `duplicate_domain` | error | 同一研究同一域重复（保留首行） |
| `design_conflict` | error | 同一研究出现多个有效设计 |
| `invalid_override` | error | 覆盖值非法 |
| `override_without_reason` | error | 覆盖无理由（覆盖被拒绝） |
| `judgement_alias` | warning | 使用了可接受别名（如 moderate） |
| `short_quote` | warning | 引文少于 12 字符 |
| `locator_without_unit` | warning | 定位只有数字 |
| `unclear_without_note` | warning | `unclear` 且无 `note`、无 `quote` |
| `domain_not_applicable` | warning | 域不在该设计的必填集合 |
| `evidence_file_not_found` | warning | 输入目录下找不到证据文件 |

`status` 规则：存在 error → `partial`；无 error 但有输入限制 → `partial`；否则 `ok`；
评价行为空 → `blocked`。

## 7. 输出

### `appraisal.json`

```json
{
 "rules_version": "quality-appraise/1.0",
 "status": "ok",
 "studies": [{
   "study_id": "S1",
   "design": "rct",
   "applicable_domains": ["..."],
   "present_domains": ["..."],
   "missing_domains": [],
   "counts": {"low": 3, "some_concerns": 1, "high": 1, "unclear": 0},
   "worst_domains": ["selection_of_reported_result"],
   "overall": "high",
   "overall_source": "worst_domain",
   "overall_reason": "",
   "domains": [{"domain": "...", "judgement": "...", "evidence_file": "...",
                "evidence_locator": "...", "quote": "...", "evidence_ok": true}]
 }],
 "counts": {"by_domain": {}, "by_judgement": {}, "by_design": {}},
 "issues": [],
 "uncertainty": [],
 "limits": []
}
```

### `appraisal.csv`

所有输入行（含无效行）逐行输出，并附带 `judgement_valid`、`evidence_ok`、
`included_in_summary`、`source_file`、`row`，便于定位与复核。

### `issues.csv`

`severity, code, study_id, domain, row, message, source_file`。

### `result.json`

默认字段加 `output_contract` 映射；未解析字段为 `null` 并记录于 `contract_mapping`。

## 8. 示例（合成，非官方案例）

输入行：

```csv
study_id,design,domain,judgement,evidence_file,evidence_locator,quote,note
S1,rct,randomization_process,low,p1.pdf,page:3,"Participants were randomised by a computer-generated sequence",adequate
S1,rct,selection_of_reported_result,high,p1.pdf,table:2,"The trial was stopped early for benefit",selective
S1,rct,measurement_of_outcome,unclear,p1.pdf,page:6,"","outcome assessor blinding not reported"
```

结果：

- `randomization_process=low`、`selection_of_reported_result=high`、
  `measurement_of_outcome=unclear`；
- `overall=high`，`worst_domains=["selection_of_reported_result"]`；
- 另缺 `deviations_from_intended_interventions` 与 `missing_outcome_data` 两个必填域，
  产生两条 `missing_domain` 错误；
- 因此 `status=partial`，不能声称评价完整。

反例：

- 把 `measurement_of_outcome` 的 `unclear` 改成 `low` → 违反"证据不足不得降级"；
- 引文写成"作者未报告盲法" → 这是转述，不是原文，不能作为 `quote`；
- 给研究补一个 `overall=low` 但不写理由 → 覆盖被拒绝并报错。

## 9. 已知限制

- 只校验结构与证据定位，不判断判断的科学正确性。
- 设计识别依赖可见文本；扫描件、仅摘要、补充材料缺失会导致 `unclear` 或 `partial`。
- 最小域集合是通用检查点，不等同于完整量表；扩展域需自行说明来源与阈值。
- 中文/英文之外的术语可能无法归一，需人工补充别名或直接使用规范值。
- 不替代双人独立评价、共识会议或统计合并。
