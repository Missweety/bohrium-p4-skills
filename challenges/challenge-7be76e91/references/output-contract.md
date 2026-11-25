# 输出契约

`result.json` 顶层字段。`case.json.output_contract` 优先；未给时按本表兜底。
字段名大小写/下划线/连字符不敏感，同义词（`comparison`、`matrix`、`selection`、`scores`、
`cost_estimate`、`risk_register`、`evidence`、`candidate_plans` 等）归一到本表字段。
契约支持三种写法：`["field", ...]`、`[{"name": "...", "type": "..."}]`、`{"fields": [...]}`；
`case.json` 允许一层嵌套（`input`/`data`/`payload`）。契约要求但本技能未产出的字段，
写 `{"note": "...（类型 X）"}` 并在 `uncertainty/limits` 说明，不编造内容。

| 字段 | 类型 | 含义 | 完成标准 |
|-|-|-|-|
| `case_id` | string | 案例标识 | 与输入一致 |
| `status` | string | `ok`/`partial`/`blocked`/`refused` | `partial` 必须写 `limits` |
| `recommendation` | object | `{choice, plan_id, rationale, rejected[], sensitivity[]}` | 未选方案逐条给量化理由 |
| `comparison_matrix` | array | 每方案含 `field_values`（七字段实际取值）、`feasible`、`eliminated_by`、`cost_known`、`currency`、`time_days`、`weighted` | 同一字段、同一单位；不是只有存在标记 |
| `plans` | array | `{id, title, source, line, locator, fields_present, fields_missing}` | 缺字段显式列出；结构化候选带 case.json 路径 |
| `criteria` | array | `{criterion, weight, definition}` | 权重与口径可复核 |
| `scoring` | object | `{weights, ranked[], eliminated[]}` | 加权分可复算 |
| `cost_model` | object | `{currency, budget, per_plan[]}`（含 `formula`） | 缺价标下限；币种不一致不作位次 |
| `risks` | array | `{trigger, consequence, mitigation}` | 有触发条件与后果 |
| `exceptions` | array | `{case, action}` | 覆盖全淘汰/缺价/缺字段/设备不可得/币种不一致 |
| `confirmations` | array | `{item, why, evidence}` | 待确认不写成已落实 |
| `evidence_map` | array | `{claim, source, line, locator, quote}` | 每条判断可回查；结构化来源用 `case.json#路径` |
| `assumptions` | array | `{item, detail}` | 权重、成本口径、输入通道显式 |
| `variables`/`controls`/`procedure`/`parameters`/`resources`/`readout` | array | 按方案分组的七字段内容 | 缺失即空并注明 |
| `validation` | object | `{checks[], arithmetic_recomputed, rerun}` | 含候选数、七字段矩阵、门控、成本/时间、幸存者位次 |
| `uncertainty` | array | 判断不确定（口径、识别、缺数、币种） | 与 `limits` 区分 |
| `limits` | string | 缺文件、材料不足、脚本失败 | `partial/blocked` 时不得为空 |
| `changes` | array | 与契约差异及处理 | 无差异可为空 |
| `input_mode` | string | 结构化候选路径或材料切分 | 与实际输入一致 |
| `input_versions` | object | `case.json`/材料 sha1 | 可核对重跑版本 |
| `determinism` | object | 两次运行草稿/矩阵哈希与 `consistent` | 同输入应一致 |

附带工件：`comparison_report.md`（人读，含七字段横向表）、`comparison_matrix.csv`
（同名列含七字段实际取值、成本/工期/门控/加权分）。
