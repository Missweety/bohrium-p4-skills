# 输出契约

## 必需文件（/app/output）

| 文件 | 内容 | 校验 |
|---|---|---|
| `result.json` | 契约结果 | JSON 可解析；`case_id` 与输入一致；`output_contract` 字段齐全 |
| `mindmap.md` | 缩进大纲（可编辑） | 非空；含节点类型/置信度/锚点 |
| `mindmap.mm` | FreeMind XML（可编辑） | XML 可解析；节点数与 result.json 一致 |
| `mindmap.svg` | 真实布局的矢量预览 | XML 可解析；宽度/高度 > 0；文本非空 |
| `nodes.csv` | 节点证据表 | 表头含 id,label,type,confidence,anchor,quote,verified；数据行数 = `result.nodes` 数 |
| `checks.json` | 自检报告 | 含 `ok`/`passed`/`failed`/`warnings`/`issues`/`checks`；只有 `severity=hard` 失败才使 `ok=false` |

`mindmap.png` 为可选预览：环境存在 `rsvg-convert` 或 `cairosvg` 时生成并写入 `mindmap.files.png`；缺失时记 `png_preview_missing`(warn) 并写入 `uncertainty`。

## result.json 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 原样复制输入 `case_id`；缺失时用 `unknown` 并写明 |
| `status` | string | `success` / `partial` / `failed` |
| `status_reason` | string | 一句话说明状态原因 |
| `sources` | array | 每个输入文件：path（相对实际输入目录）, bytes, sha256, readable, engine, anchor_scheme |
| `uncertainty` | array | 材料缺口、矛盾、需人工确认项 |
| `change_log` | array | 本次整理中的合并、降级、修订（含根节点自动补齐） |
| `mindmap` | object | title, purpose, audience, root_id, node_count, edge_count, files |
| `nodes` | array | id, label, type, parent, confidence, evidence, aliases, verified |
| `edges` | array | from, to, relation, confidence, basis/evidence |
| `evidence_index` | object | anchor -> {quote, verified, doc} |
| `stats` | object | node_count, edge_count, verified_nodes, checked_nodes, verification_rate, max_depth, unverified_nodes |
| `issues` | array | 仅 error：`{code, severity:"error", detail}` |
| `warnings` | array | 提示：`{code, severity:"warn", detail}`，不影响 `status` |
| `contract_fields` | object | `output_contract` 各字段的实际值，逐项对应 |

## output_contract 兼容

运行时读取 `/input/case.json` 的 `output_contract`（对象、含 `required`/`fields`/`properties` 的对象，或字段数组），别名 `outputContract` / `contract` / `required_outputs` 同样识别。脚本把其中每个字段名并入 `result.json` 顶层，值按顺序取：`plan.contract_fields` → 内置槽位（含常见别名，如 `mind_map`/`outline` → `mindmap`，`relations` → `edges`，`evidence` → `evidence_index`，`files`/`artifacts` → `mindmap.files`，`svg`/`preview` → 预览文件路径）→ `result.json` 同名顶层字段 → `plan.json` 同名字段；都取不到时写 `null` 并记 `contract_field_unresolved`(warn)。不得伪造字段内容。

## 状态判定

- `failed`：`plan.json` 缺失/非法、没有任何可读段落，或结构错误严重到只有 0–2 个节点。
- `partial`：仍有 error 级结构/证据问题（引文找不到、父节点缺失、关系端点缺失、推断缺依据等）。
- `success`：没有 error，`verification_rate = 1.0`；可以有 warning。
- `status=failed` 时，`selfcheck` 把节点/关系数量阈值与引文数量检查视为提示，但仍要求产物文件存在且可解析。
