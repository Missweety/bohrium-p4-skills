# 输出契约

## 必需文件（/app/output）

| 文件 | 内容 | 校验 |
|---|---|---|
| `result.json` | 契约结果 | JSON 可解析；`case_id` 与输入一致；`output_contract` 字段齐全 |
| `mindmap.md` | 缩进大纲（可编辑） | 非空；含节点类型/置信度/锚点 |
| `mindmap.mm` | FreeMind XML（可编辑） | XML 可解析；节点数与 result.json 一致 |
| `mindmap.svg` | 真实布局的矢量预览 | XML 可解析；宽度/高度 > 0；文本非空 |
| `nodes.csv` | 节点证据表 | 表头含 id,label,type,confidence,anchor,quote,verified |
| `checks.json` | 自检报告 | 含 passed/failed/issues |

## result.json 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 原样复制输入 `case_id`；缺失时用 `unknown` 并写明 |
| `status` | string | `success` / `partial` / `failed` |
| `sources` | array | 每个输入文件：path, bytes, sha256, readable, anchor_scheme |
| `uncertainty` | array | 材料缺口、矛盾、需人工确认项 |
| `change_log` | array | 本次整理中的合并、降级、修订 |
| `mindmap` | object | title, purpose, audience, root_id, node_count, edge_count, files |
| `nodes` | array | id, label, type, parent, confidence, evidence, aliases |
| `edges` | array | from, to, relation, confidence, basis/evidence |
| `evidence_index` | object | anchor -> {quote, verified, doc} |
| `issues` | array | 未核验、未读、冲突等 |
| `contract_fields` | object | `output_contract` 各字段的实际值，逐项对应 |

## output_contract 兼容

运行时读取 `/input/case.json` 的 `output_contract`（对象或字段数组）。脚本把其中每个字段名并入 `result.json` 顶层，值优先取 `plan.json` 的 `contract_fields`，其次取同名主结果字段，最后写 `null` 并在 `issues` 说明未提供。不得伪造字段内容。
