# output_contract 与 result.json 字段说明

`result.json` 的字段集合由 `/input/case.json` 的 `output_contract` 决定。运行器支持：

```json
["case_id", "status", "answer", "graph", "queries", "evidence", "limits"]
{"fields": ["case_id", "status", "answer", "graph", "queries", "evidence", "limits"]}
{"required": ["case_id", "status", "answer", "graph", "queries", "evidence", "limits"]}
```

字段名按别名表归一（大小写、连字符、下划线不敏感）：`knowledge_graph`/`nodes_edges` → `graph`；
`nodes`/`entities` → `nodes`；`edges`/`relations`/`triples` → `edges`；
`query_results`/`qa` → `queries`；`aliases`/`merge_decisions` → `alias_decisions`；
`quality_checks`/`consistency` → `integrity`；`citations`/`quotes` → `evidence`；
`limitations` → `limits`。无法识别的字段名用 `structured` 填充，并写
`_contract_field` / `_note`，便于人工发现，而不是留 null。

## 必填字段（默认契约）

| 字段 | 类型 | 含义 | 复核方式 |
| --- | --- | --- | --- |
| `case_id` | string | 案例标识 | 与 `/input/case.json` 对照 |
| `status` | enum | `success` / `partial` / `blocked` / `failed` | 与材料数、查询数、审计一致 |
| `answer` | string | 图谱规模与查询摘要 | 数字与 `metrics` 一致 |
| `graph` | object | `nodes` / `edges` / `alias_candidates` / `docs` / `integrity` | 与 CSV 导出一致 |
| `queries` | array | 实际执行的查询及结果、答案、证据、限制 | `executed=true` |
| `alias_decisions` | array | 每个跨篇同名候选的 `merged` / `not_merged` 与理由 | 与 graph 节点对应 |
| `integrity` | object | `pass`、`issues`、`blocking`、`totals` | 与图谱实际内容一致 |
| `evidence` | array | `{claim, source_path, locator, quote, node_id/query_id}` | quote 可在材料中检索 |
| `sources` | array | 每篇材料：`source_id`、`file`、`title`、`paragraph_count`、`doi/authors/license` | 与 manifest 对照 |
| `uncertainty` | array | 未合并项、查询限制、案例解析问题 | 与 alias/limits 对应 |
| `limits` | string | 边界与失败原因；成功时可为空串 | 与 status 一致 |
| `change_log` | array | 真实执行步骤（含审计结果、耗时） | 与工作目录产物对应 |
| `notes` | array | 材料去重、无法对应 manifest 等提示 | 与 sources 对应 |

附加键（不替代契约字段）：`metrics`、`conflicts`、`structured`、`coverage`、
`artifacts`、`audit`、`contract_check`。

## graph.nodes[] 行结构

| 键 | 说明 |
| --- | --- |
| `node_id` | `S<篇序>:N<序号>`，同一篇内稳定 |
| `label` | 原文表述 |
| `normalized` | 归一化标签（小写、去标点、复数收敛） |
| `type` | `method` / `material` / `metric` / `dataset` / `condition` / `concept` |
| `source_id` | 所属论文（来自 corpus-manifest 或材料自身 id） |
| `paragraphs` | 出现过的段落锚点 |
| `evidence` | `[{source_id, paragraph_id, quote}]`，quote 为原句片段 |

## graph.edges[] 行结构

| 键 | 说明 |
| --- | --- |
| `edge_id` | `E<序号>` |
| `source` / `target` | 节点 ID，必须都存在 |
| `predicate` | `co_occurs` / `compared_with` / `based_on` |
| `rule` | 触发该关系的匹配规则 |
| `source_id` / `paragraph_id` / `quote` | 该边唯一的原文依据 |
| 方向 | `source → target` 按句中出现顺序；比较关系保留原文主语在前 |

## queries[] 行结构

| 键 | 说明 |
| --- | --- |
| `query_id` | `Q1`–`Q4` |
| `type` | 四种查询类型之一 |
| `query` | 查询语句 |
| `executed` | 必须为 true（真实在图上执行） |
| `result` | 查询结果（数组/对象） |
| `answer` | 人读结论，数字与 result 一致 |
| `evidence` | 支撑引文；空结果时必须为空 |
| `no_hit` / `empty_reason` | 零命中时如实标注，禁止编造引文 |
| `limitations` | 该查询的适用边界 |

## 证据与定位

- `quote` 必须能在对应 `source_id` + `paragraph_id` 的正文中检索到（归一化空白/连字后）。
- 本包材料给的是 JATS 段落 ID；**不声称 PDF 页码**，也不推断图像像素或补充附件数值。
- 审计不通过时，运行器把 `status` 从 `success` 降为 `partial`，并把错误数写入 `limits`。

## 状态判定

```
无任何可读段落                                  -> blocked
有段落但只有单篇材料 / 查询<3 / 完整性 blocking  -> partial
≥2 篇 + ≥3 查询 + 无 blocking + 审计通过         -> success
运行器内部异常                                  -> failed（仍写 result.json）
```

## 禁止

- 不写绝对机器路径、token、密钥。
- 不跨文献按字符串直接合并节点；不把共现写成因果。
- 不把 0 命中伪造成有证据；不用同篇另一种格式冒充第二篇论文。
- 不声称未真实运行的分数或外部验证结果。
