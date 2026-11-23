# 输出契约：以 `case.json` 为准的动态映射

## 1. 权威来源

`/input/case.json` 的 `output_contract`（别名 `expected_output` / `schema`）是唯一权威。
先读取它，再决定 `result.json` 的字段名、层级、类型与必填项。本文档只给**默认映射**，
用于契约缺失或未覆盖某项时兜底；不得用本文档覆盖实际契约，也不得把默认结构当成
"适用于所有案例的固定答案"。

处理顺序：

1. 若 `output_contract` 是对象：按其中的字段逐项产出，保留原键名、原层级、原类型。
2. 若 `output_contract` 是数组：每项视为一个字段说明，按 `name`/`field`/`key` 取名，
   按 `type` 取值；缺少名称的项在报告中注明无法映射。
3. 若契约嵌套（如 `fields: [{name: ...}]` 或 `required: [...]`），先展开到叶字段，
   再逐一赋值；`required` 中的字段不得缺失。
4. 若契约给出枚举（如 `status: [ok, partial, blocked]`），只能取枚举值。
5. 若契约要求的字段在真实输入中无法得到：输出 `null`/空数组，并在 `limitations`
   或该字段旁的 `status` 说明原因；不得填造。
6. 契约没有要求但有助于复核的字段可以追加，但不得改名或删除契约字段，追加项需在
   `report.md` 说明。

不要在 `result.json` 中输出 JSON Schema 描述、字段类型声明或占位模板；字段值必须是
本次运行的真实结果。

## 2. 必须始终保留

| 字段 | 类型 | 要求 |
|-|-|-|
| `case_id` | string | 从 `case.json` 原样复制；缺失时写实际读到的文件与 `null` 原因 |
| `status` | string | `ok` / `partial` / `blocked`，与实际完成度一致 |
| `sources` | array | 实际读取的文件、来源库、种子标识与定位符 |
| `uncertainty` | array/object | 空结果、缺失边、冲突、权限、覆盖边界 |
| `change_log` | array | 运行中做过的重跑、参数调整或人工判断 |

## 3. 默认字段映射（契约缺省时）

```json
{
  "case_id": "<原样>",
  "status": "ok|partial|blocked",
  "task": {
    "research_question": "<来自 case.json/task.md>",
    "seed_papers": [{"raw": "", "node_id": "", "resolved": true}]
  },
  "graph": {
    "artifact": "graph.json",
    "nodes": 0,
    "edges": 0,
    "components": 0,
    "snapshot_only": true
  },
  "citations": {
    "artifact": "citations.csv",
    "edge_count": 0,
    "evidence_rows": 0
  },
  "paths": [
    {"seed": "", "target": "", "mode": "forward|reverse", "length": 0,
     "hops": [{"from": "", "to": "", "relation": "cites|cited_by",
               "source_db": "", "evidence_file": "", "evidence_locator": ""}]}
  ],
  "merge_candidates": [
    {"type": "doi_exact|title_year_exact", "key": "", "action": "review_only",
     "members": []}
  ],
  "related_work": {
    "signals_available": ["co_citation|bibliographic_coupling|author|dataset"],
    "items": [{"node_id": "", "signal": "", "evidence_file": "", "evidence_locator": ""}],
    "note": "没有实际信号时为空数组并说明"
  },
  "coverage": {
    "input_files": [],
    "sources": [],
    "stopped_at": "<深度/快照边界/无新边>",
    "pruned_branches": []
  },
  "limitations": [],
  "artifacts": ["graph.json", "citations.csv", "report.md"],
  "reproduce": ["<实际执行过的命令>"]
}
```

字段映射要点：

- `graph.nodes/edges/components` 取 `graph.json.stats` 的实际值，不另行估算。
- `citations.evidence_rows` 等于 `citations.csv` 数据行数；`edge_count` 等于唯一
  `edge_id` 数，二者必须能对上。
- `paths` 只能来自 `graph.json.paths`；没有路径时为空数组，并在 `limitations` 写
  `no_path_within_depth` 或 `seed_not_in_edges`。
- `merge_candidates` 只能来自 `graph.json.merge_candidates`，不得把候选写成已合并。
- `related_work` 只在输入确有共被引/耦合/作者/数据集信号时非空。
- `status=partial` 时必须在 `limitations` 或 `uncertainty` 中给出具体缺口；`blocked`
  时说明卡在哪一步、已产出了哪些部分（可为空）。

## 4. 案例覆盖规则

案例契约可能要求不同的组织方式，例如按"检索问题 → 候选文献 → 排序依据 → 遗漏说明"
组织，或把 `results` 放在顶层数组。此时：

- 先用本技能的真实产物填充语义相同的字段：`results`/`candidates` ← 排序后的文献节点
  或路径目标；`evidence` ← `citations.csv` 行；`missing`/`gaps` ← issues 与未覆盖库；
  `ranking_basis` ← 入度/路径长度/证据完整度/来源数等实际使用的规则。
- 契约要求"每篇文献一行"时，以节点为单位输出；同一论文的多个版本仍是不同节点，
  用合并候选连接，不擅自合并。
- 契约要求"排序"时必须写明排序键与并列处理，不能只给一个顺序不明的列表。
- 契约要求 `summary`/`conclusion` 时，只总结已有证据；不得出现输入中不存在的文献。

## 5. 一致性与禁止项

- `result.json`、`graph.json`、`citations.csv`、`report.md` 的计数必须一致。
- 所有路径使用 `/input`、`/app/work`、`/app/output`；不写本地个人绝对路径。
- 不提交预生成答案、案例专属结论或伪造的运行统计；合成示例必须标注"合成示例"。
- 每个 `status` 都要有可复核依据：实际执行命令、实际文件、实际 issues。
