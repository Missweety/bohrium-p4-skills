# 输出契约（硬性要求）

运行约定：输入 `/input`，工作区 `/app/work`，最终产物 `/app/output`。本文件是 `scripts/run_case.py` 与 `scripts/selfcheck.py` 共同遵守的契约。

## 1. 必需文件

| 路径 | 内容 | 自检判据 |
|---|---|---|
| `draft.md` | 可编辑交付稿 | 非空；sha256 与 `result.deliverable.draft_sha256` 一致；无占位符 |
| `facts.csv` | 必需事实与来源映射 | 至少一行；`unit_id` 可在来源中找到；`present_in_draft` 与实际一致 |
| `citation_map.json` | 主张→来源 | 有 `claims`；每条 `unit_id` 真实存在 |
| `result.json` | 案例级契约结果 | 可解析；`case_id` 与输入一致；`status ∈ {success,partial,failed}`；`contract_fields` 非空 |
| `report.json` | 汇总报告 | 含 `conditions`、`comparison`、`coverage`、`leakage`、`failure_examples` |
| `scores/<condition>.json` | 逐题评分 | 记录含 `item_id`、`score ∈ {0,1,2}`、`rationale`、`failure_type` |
| `runs/<condition>/draft.json` | 每个条件的稿子 | 含 `sha256` 与正文 |
| `checks/rubric_selfcheck.json` | 评分器自检 | 完美稿→2、空稿→0 全部成立 |
| `checks/trace.json` | 追溯链 | 题目→稿件→评分记录且 `chain_ok=true` |
| `checks.json` | 自检报告 | 由 `selfcheck.py` 生成 |

`/app/work` 需保留：`dataset.json`（含金标准）、`units.json`（`unit_id`→定位/正文，供写稿放锚点）、`public_items.json`（去金标准的题面视图，供写稿）。

## 2. `result.json` 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 原样复制；缺失写 `unknown` 并说明 |
| `status` | string | `success`/`partial`/`failed` |
| `status_reason` | string | 非 success 必须指向具体缺口 |
| `deliverable` | object | `draft`、`draft_sha256`、`chars`、`sections`、`facts`、`citation_map`、`source_of_draft` |
| `fact_source_map` | array | 每条事实：`item_id`、`value_raw`、`value`、`unit`、`source_path`、`unit_id`、`locator`、`present_in_draft` |
| `citation_map` | object | `draft_sha256` + `claims[]`（`claim_id`、`unit_id`、`locator`、`quote`、`anchored_in_draft`） |
| `benchmark` | object | `dataset_version`、`dataset_sha256`、`item_count`、`by_type`、`items[]` |
| `evaluation` | object | `conditions`、`comparison`、`failure_examples`、`rubric_selfcheck_pass` |
| `sources` | array | `path`、`kind`、`readable`、`chars`、`sha256`、`extraction`、`anchor_scheme` |
| `uncertainty` | array | 来源缺口、未落稿事实、空外部稿、未实现契约字段等 |
| `change_log` | array | 本题型集合、照搬阈值、基线条件 |
| `checks` | object | 六项布尔检查 |
| `contract_fields` | object | 按输入 `output_contract` 逐项映射；未实现写 `null` 并记 `uncertainty` |

## 3. `output_contract` 兼容规则

- 支持对象（字段名→说明）、字符串数组、对象数组（`name`/`field`/`id`）。
- 别名映射：`main_result`/`result`/`output` → `artifacts`；`evidence`/`citations`/`fact_map` → `fact_source_map`；`draft`/`manuscript`/`text` → `{path, sha256}`；`version` → 版本信息。
- **不得伪造**：未实现字段一律 `null` + `uncertainty.unmapped_contract_fields`。

## 4. 评分记录硬约束

- `score ∈ {0,1,2}`；`gradable=false` 不计入汇总。
- 每条记录必须有非空 `rationale`；失败必须有 `failure_type`：`number_dropped`、`invented_number`、`lost_condition`、`verbatim_copy`、`too_long`、`too_short`、`empty_draft`、`section_missing`、`section_incomplete`、`citation_missing`、`citation_incomplete`、`missing_or_wrong_anchor`、`absence_not_stated`、`invented_for_absent`、`gold_missing`。
- 记录的 `source_units` 必须能在 `work/dataset.json` 找到。

## 5. 打包与安全约束

- 仅 UTF-8 文本；≤50 文件；单文件 ≤500KB；合计 ≤2MB；禁止符号链接与二进制。
- 不含 token/私钥/个人绝对路径；不访问网络、不读 `.secrets`、不提交平台。
- 合成示例必须标 `SYNTHETIC`，不得冒充正式测试集或官方案例结果。
- `/input/draft.md` 只作为被评稿件，绝不作为来源单元进入建题。
