# output_contract 与 result.json 字段说明

字段集合由 `/input/case.json` 的 `output_contract` 决定，支持：

```json
["case_id", "status", "answer", "reproduction", "plan", "evidence", "limits"]
{"fields": ["case_id", "status", "reproduction", "limits"]}
{"required": ["case_id", "status", "reproduction", "limits"]}
```

别名归一（大小写/连字符/下划线不敏感）：`results`/`verification` → `reproduction`；
`claim_list` → `claims`；`check_list` → `checks`；`summary`/`conclusion` → `answer`；
`reproduction_plan`/`steps` → `plan`；`materials` → `sources`；`gaps`/`unknowns` → `uncertainty`；`limitations` → `limits`；
`inconsistencies` → `conflicts`。未识别字段用 `structured` 填充并写 `_contract_field`。

若契约直接要求 `claims` 或 `checks`，返回顶层数组（与 `reproduction.claims` /
`reproduction.checks` 内容一致），不会把整个 `reproduction` 对象塞进数组字段。

## 必填字段（默认）

| 字段 | 类型 | 含义 | 复核方式 |
| --- | --- | --- | --- |
| `case_id` | string | 案例标识 | 与 case.json 对照 |
| `status` | enum | `success`/`partial`/`blocked`/`failed` | 与 counts/limits 一致 |
| `answer` | string | 判定摘要（各状态计数与缺失依赖） | 与 summary 一致 |
| `reproduction` | object | `{claims, checks, plan, plan_complete, conflicts, summary, method}` | 见下 |
| `plan` | object | data/environment/parameters/commands/code 逐项 | specified 必须有 quote |
| `evidence` | array | `{claim, source_path, locator, quote, claim_id}` | quote 可在材料检索 |
| `sources` | array | 材料清单与可读性 | 与 doc.json 一致 |
| `uncertainty` | array | 每条非确定判定的说明 | 与 claim 状态对应 |
| `limits` | string | 缺失依赖、冲突、降级原因 | 与状态一致 |
| `change_log` | array | 真实执行步骤 | 与 work 产物对应 |

附加键：`conflicts`、`metrics`、`coverage`、`audit`、`contract_check`、`artifacts`。

## reproduction.claims[]

| 键 | 说明 |
| --- | --- |
| `claim_id` | `C1`, `C2`… |
| `claim` / `quote` | 原文陈述与逐字引文 |
| `paragraph_id` / `source_file` | 段落锚点（JATS p id / p.N¶k / ¶k） |
| `status` | `recomputed_consistent` / `recomputed_inconsistent` / `partially_reproduced` / `not_reproducible` / `not_checkable` |
| `missing_dependencies` | 缺失的依赖类别 |
| `checks` | 本句触发的复算列表 |
| `note` | 判定口径 |

## reproduction.checks[]

| 键 | 说明 |
| --- | --- |
| `test` | `student_t` / `normal_z` / `percent_change` |
| `inputs` | 仅来自原文的输入（t、df、z、from、to） |
| `computed_p` / `computed_pct` | 本机复算值 |
| `reported_p` / `reported_pct` / `reported_operator` | 原文报告值与比较符 |
| `tolerance` | 由报告值小数位决定 |
| `verdict` | `consistent` / `inconsistent` / `not_checkable` |
| `paragraph_id` / `quote` | 证据锚点 |

## plan 各类别条目

`{kind, item, value, status: specified|missing, paragraph_id, quote, note}`
`status=specified` 必须有 `paragraph_id` 与可在材料中检索到的 `quote`；
`available on request` 归为 missing（未提供），不视为可复现依赖。

## 状态判定

```
无可读材料                                  -> blocked
无 claims                                   -> partial
存在 recomputed_inconsistent                -> partial
全部依赖齐全且全部 consistent 且审计通过     -> success
其余                                        -> partial
运行器内部异常                              -> failed（仍写 result.json）
```

## 禁止

- 不把“作者声称”写成“已复现”；不把可索取的数据/代码算作已提供。
- 不修改原文报告值来“对齐”复算。
- 不写绝对机器路径、token、密钥；不联网。
- 不声称任何未真实运行的分数或复现成功。
