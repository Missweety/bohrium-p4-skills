# 默认输出契约（experimental-design）

`case.json` 若提供 `output_contract`，**以题面为准**（字段名、单位、币种、版本数都以题面为准）；
本文件只补全题面未列出的字段。`result.json` 必须含 `case_id` 且与输入一致。

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填 |
| status | enum | 是 | ok / partial / blocked / refused |
| plan | object | 是 | 方案主体：假设、变量、对照、参数、样本量、资源、排期、风险（见下） |
| plan_versions | array | 是 | 3 版候选 `[{id,label,n_per_group,cost,hours,changes}]` |
| recommendation | object | 是 | `{id, rationale, sacrifice}` 推荐版本与理由、牺牲项 |
| parameter_basis | array | 是 | `[{name,value,unit,basis,source,assumed,sensitivity}]` 参数依据表 |
| resource_arithmetic | object | 是 | `{consumables_subtotal, budget_total, budget_cap, equipment_hours, window_hours, checks}` |
| risks | array | 是 | `[{mode,indicator,threshold,stop_loss,fallback}]` |
| confirmations | array | 是 | `[{item,owner,why}]` 安全/伦理/设备可用性/专家确认 |
| artifact_path | string | 否 | 方案正文（plan.md）相对路径 |
| uncertainty | array | 是 | 缺材料、冲突值、assumed 参数汇总 |
| limits | string | 否 | partial 时说明缺哪些信息、哪些参数无法定值 |
| self_check | object | 否 | 校验摘要（work/checklist.json：errors/warnings/assumed_count） |
| changes | array | 否 | 相对初稿的修订 `[{target,before,after,reason}]` |

## plan 结构

| 字段 | 必填 | 说明 |
|-|-|-|
| goal | 是 | 研究目标原样 + 你对"可检验终点"的转写 |
| hypothesis.statement / direction / falsify_if / endpoint | 是 | 可证伪；写不出 falsify_if 即不合格 |
| variables.independent[] | 是 | `{name, levels, operational}` |
| variables.dependent[] | 是 | `{name, instrument, unit, sampling}` |
| variables.confounders[] | 是 | `{name, control}` 控制手段须具体 |
| controls[] | 是 | `{type, design, excludes}`，type ∈ negative/vehicle/positive/dose_gradient/sham |
| sample_size | 是 | `{n_per_group, groups, basis, inputs, effect_size_source, technical_replicates}` |
| parameters[] | 是 | `{name, value, unit, range, basis, source, action, assumption, sensitivity}` |
| steps[] | 是 | 至少 5 步 `{id, action, params[], resources[], readout, duration_h}`，每步绑定参数与判读 |
| resources.equipment[] | 是 | `{name, model, needs_h, available_h}` |
| resources.consumables[] | 是 | `{item, spec, qty, unit_price, currency}` |
| budget | 是 | `{total, cap, currency}` |
| schedule | 是 | `{sessions, hours_per_session, total_hours, window_hours}` |

## 一致性约束

- `parameter_basis` 中 `basis != assumed` 的条目，`value` 必须能在 `corpus.txt` 找到同源写法。
- `resource_arithmetic.consumables_subtotal` = Σ(qty×unit_price)，误差 ≤1；`budget_total ≤ cap`。
- `schedule.total_hours` = `sessions × hours_per_session`；`≤ window_hours`。
- `steps` 每条 `params` 必须是 `parameters[].name` 的子集；`Σ duration_h` 超过 `total_hours` 时须说明并行关系。
- `plan_versions` 至少 3 条且 `recommendation.id` 必须命中其中一条；三版的 `n_per_group/cost/hours` 不得完全相同。
- `recommendation` 必须写 `sacrifice`：为满足预算或时间窗牺牲了哪项可检验性。
- 任何 `assumed` 参数都必须出现在 `uncertainty` 或 `confirmations` 中，不能只标在参数表里。
- `status=ok` 时不允许存在未处置的冲突值；`partial` 必须有 `limits`。
