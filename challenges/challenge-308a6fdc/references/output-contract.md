# 输出契约（writing）

`case.json` 若提供 `output_contract`，以题面为准；本文件是补全规则，用于题面缺字段时保证交付完整。
`kernel.py emit` 会先填入默认值，再合并 `draft.json`；`check` 会逐项复检。

## `result.json` 顶层

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填输入标识 |
| status | enum | 是 | `ok` / `success` / `partial` / `blocked` / `refused` |
| artifact_path | string | 是 | 主产物相对路径，默认 `manuscript.md` |
| artifact_format | string | 否 | `md` / `tex` / `docx` |
| source_map | array | 是 | 每条 `{claim, value, source_path, locator}`；partial 时保留已核实部分 |
| changes | array | 是 | `{target, type, before, after, reason}`；无改动可空数组 |
| uncertainty | array | 是 | 缺材料/不可核验/冲突/缺引用；无则 `[]` |
| limits | string | 条件 | status 为 `partial` / `blocked` 时必填，说明缺什么、影响哪些结论 |
| self_check | object | 是 | 至少含 `audit_verdict`；建议含 `numbers_unbound`、`citations_unresolved`、`conflicts`、`placeholders_unregistered` |
| conflicts | array | 否 | 已保留并登记的冲突值 |
| todo | array | 否 | 待补/待核清单（与 `todo.md` 同源） |
| references | array | 否 | 文献条目 |
| figures / tables | array | 否 | 图/表 label、caption、来源 |

`status` 规则：

- `ok`：题面要求的章节齐全，audit 无 FAIL；
- `partial`：有缺数据、冲突、未核验项，已在 `uncertainty` + `limits` 说明；
- `blocked`：没有 case/材料或无法抽取，`manuscript.md` 仍需写"无法完成 + 原因"；
- `refused`：请求本身不适合（如要求编造数据），说明拒绝理由。

## `source_map` 条目

```json
{"claim":"treated degradation","metric":"treated degradation","value":"21.7",
 "source_path":"/input/materials/exp.csv","locator":"row 3, col degradation_pct",
 "fact_id":"C0007"}
```

- `claim`：这条事实在正文中对应的陈述；
- `value`：数字/字符串，必须与正文写法一致（`12.4%` 与 `12.4` 视为同一数值）；
- `source_path`：绝对路径或相对 `/app` 的路径；
- `locator`：行号/单元格/页/图表区域，不能为空；
- `metric`：可选，同 metric 不同 value 会被判为冲突；
- `fact_id`：可选，`work/facts.json` 的候选编号。

## `uncertainty` 条目

```json
{"id":"U01","type":"missing_material","where":"Results paragraph 1",
 "what":"treated degradation value","why":"exp.csv row 3 is empty",
 "next_step":"作者补数或确认未采集"}
```

`type` 取值：

| type | 用途 |
|-|-|
| `missing_material` | 材料缺该数据/文件/图 |
| `unverifiable` | 材料存在但无法核验（扫描件、无文本层、口径不明） |
| `conflict` | 同一事实在不同材料中数值矛盾 |
| `missing_citation` | 需要引用但材料没有文献信息 |
| `ambiguous_instruction` | 题面要求冲突或口径不清 |

正文占位 `【待补：<what>｜<why>】`、`【待核：<what>】` 必须能匹配某条 `uncertainty` 的 `what` 或 `where`，
否则 `section_audit.py` 判 FAIL。

## 交付门禁

`kernel.py check --out /app/output --contract-dir work` 检查：

1. `result.json` 存在且必填字段非空；
2. `status` 合法；`partial`/`blocked` 时 `limits` 非空；
3. `source_map` 每条含 claim/value/source_path/locator；
4. `artifact_path` 指向的文件存在且非空，`manuscript.md` 存在；
5. `audit.json` 存在，`self_check.audit_verdict` 存在；
6. 题面 `output_contract` 的每个字段都出现在结果中。

任一不满足返回 1；不要通过删字段或改 status 绕过。
