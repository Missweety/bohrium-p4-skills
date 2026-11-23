# 输出契约（硬性要求）

本文件是 `scripts/run_bench.py` 与 `scripts/selfcheck.py` 共同遵守的契约。运行环境按 Harbor 约定：输入在 `/input`，工作区 `/app/work`，最终产物 `/app/output`。

## 1. 必需文件

| 路径 | 内容 | 自检判据 |
|---|---|---|
| `result.json` | 案例级契约结果 | JSON 可解析；`case_id` 与输入一致；`status ∈ {success, partial, failed}`；`contract_fields` 非空 |
| `report.json` | 汇总报告 | 含 `conditions`、`split`、`coverage`、`leakage`、`failure_examples`、`comparison` |
| `scores/<agent>.json` | 逐题评分记录 | 每条含 `item_id`、`score ∈ {0,1,2}`、`rationale`、`failure_type` |
| `runs/<agent>/answers.json` | 原始答案 | 与题目 ID 一一对应；可被重新评分 |
| `runs/<agent>/run_config.json` | 运行配置 | 含数据集哈希、单位哈希、题量预算、工具说明 |
| `checks/rubric_selfcheck.json` | 评分器自检 | 金标准→2、空→0、超长→0 全部成立 |
| `checks/trace.json` | 追溯链 | 每个测试题都有 题目→答案→评分 记录且 `chain_ok=true` |
| `checks.json` | 自检报告 | 由 `selfcheck.py` 生成，含 `pass`、逐项 `checks`、`issues` |

`/app/work` 下另需保留：`dataset.json`（含金标准与证据）、`split.json`（切分策略与两侧题目）、`public_test_items.json`（求解方可见视图）、`rejected_candidates.json`（泄漏拒绝记录）。

## 2. `result.json` 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 原样复制输入；缺失时写 `unknown` 并在 `uncertainty` 说明 |
| `status` | string | `success` / `partial` / `failed` |
| `status_reason` | string | 状态依据；非 success 必须指向具体缺口 |
| `benchmark` | object | `dataset_version`、`dataset_sha256`、`item_count`、`requested_items`、`by_type`、`by_source`、`split` |
| `items` | array | 每项：`item_id`、`task_type`、`difficulty`、`question`、`gold_answer`、`acceptable_variants`、`evidence[]`、`rubric`、`leakage_status`、`data_license` |
| `readings` | array | 案例声明的 `questions` 的作答结果；无则空数组并在 `uncertainty` 说明 |
| `evaluation` | object | `conditions`（各基线汇总）、`comparison`、`failure_examples`、`rubric_selfcheck_pass` |
| `sources` | array | 每个来源：`path`、`kind`、`readable`、`chars`、`sha256`、`extraction`、`anchor_scheme` |
| `uncertainty` | array | 材料缺口、不可读文件、题量不足、未实现契约字段、未答问题等 |
| `change_log` | array | 本次建题/切分/评分口径的变更记录 |
| `checks` | object | 五项布尔检查 |
| `contract_fields` | object | 输入 `output_contract` 声明的字段逐个映射；无法映射的写 `null` 并列入 `uncertainty` |

## 3. `output_contract` 兼容规则

- `output_contract` 可能是对象（字段名→说明）、字符串数组或对象数组（含 `name`/`field`/`id`）。
- 字段名优先取 `result.json` 顶层同名键；别名 `main_result`/`result`/`answers` 映射到 `{items, readings}`；`evidence`/`citations` 映射到 `sources`；`version` 映射到版本信息。
- **不得伪造**：无对应实现的字段一律 `null` 并记入 `uncertainty`，不得填示意数据。

## 4. 评分记录硬约束

- `score` 只能是 `0`、`1`、`2`；`gradable=false` 的记录不得计入汇总。
- 每条记录必须有非空 `rationale`；失败必须有 `failure_type`（`wrong_value`、`wrong_content`、`missing_or_wrong_anchor`、`empty_answer`、`answer_too_long`、`format_invalid`、`question_echo`、`refusal_mismatch`、`gold_missing` 等）。
- 记录中的 `source_path` / `evidence_unit` 必须能在 `dataset.json` 中找到。

## 5. 打包与安全约束

- 仅 UTF-8 文本文件；≤50 个文件；单文件 ≤500KB；合计 ≤2MB；禁止符号链接与二进制资源。
- 不得包含 API token、私钥、绝对个人路径；不访问网络、不读 `.secrets`、不提交平台。
- 合成示例必须显式标注 `SYNTHETIC`，不得冒充正式测试集或官方案例结果。
