# 输出契约：以 `case.json` 为准的动态映射

## 1. 权威与处理顺序

`/input/case.json` 的 `output_contract`（别名 `expected_output` / `schema`）是唯一权威。
本文档只提供**默认映射**，用于契约缺失或未覆盖字段时兜底；不得用默认结构覆盖实际契约，
也不得把任何默认值当成"预生成答案"。

1. `output_contract` 为对象：按字段逐项产出，保留原键名、层级、类型与枚举范围。
2. `output_contract` 为数组：每项按 `name`/`field`/`key` 取字段名，按 `type` 取值；
   无名称项在报告中说明无法映射。
3. 嵌套契约（如 `fields`、`required`、`items`）先展开到叶字段，再逐一赋值；
   `required` 项不得缺失。
4. 无法从真实输入得到的字段：输出 `null`/空数组，并在 `limitations` 或该字段状态中
   说明原因；不得编造。
5. 契约未要求但有助于复核的字段可追加，但不得改名或删除契约字段，追加项需在
   `report.md` 说明。

不得把 JSON Schema 描述、类型声明、占位符或模板文本写进 `result.json`；字段值必须是
本次运行的真实结果。

## 2. 必须始终保留

| 字段 | 类型 | 要求 |
|-|-|-|
| `case_id` | string | 原样复制；缺失时说明实际读到的文件与原因 |
| `status` | string | `ok` / `partial` / `blocked`，与完成度一致 |
| `sources` | array | 实际库集合、文件、查询记录与定位 |
| `uncertainty` | array/object | 缺失、未知、冲突、单库失败、覆盖边界 |
| `change_log` | array | 参数调整、人工仲裁、`--fuzzy-merge` 等决定 |

## 3. 默认字段映射（契约缺省时）

```json
{
  "case_id": "<原样>",
  "status": "ok|partial|blocked",
  "task": {
    "research_question": "<来自 case.json/task.md>",
    "databases_requested": ["<实际库>"],
    "databases_available": ["<实际成功库>"]
  },
  "merged_result": {
    "artifact": "merged.json",
    "record_count": 0,
    "cluster_count": 0,
    "multi_source_clusters": 0,
    "records": ["<来自 merged.json.records>"]
  },
  "deduplication": {
    "artifact": "duplicates.csv",
    "exact_groups": 0,
    "fuzzy_candidates": 0,
    "near_misses": 0,
    "policy": "exact identifiers merged; fuzzy review-only by default"
  },
  "conflicts": {
    "artifact": "conflicts.csv",
    "count": 0,
    "items": ["<来自 conflicts.csv>"]
  },
  "provenance": {
    "artifact": "provenance.csv",
    "rows": 0,
    "chain": "source_db -> query -> raw_file:raw_locator -> mapping -> cluster -> merged value"
  },
  "coverage": {
    "per_source": {"<db>": {"records": 0, "fields_present": {}}},
    "gaps": ["<来自 merged.json.gaps>"],
    "note": "只反映输入快照，不声称全局覆盖"
  },
  "limitations": [],
  "artifacts": ["merged.json", "provenance.csv", "conflicts.csv",
                "duplicates.csv", "report.md"],
  "reproduce": ["<实际执行过的命令>"]
}
```

字段映射要点：

- `merged_result.record_count` = `merged.json.stats.clusters`；
  `multi_source_clusters` = `stats.multi_record_clusters`；两者都应能从 `records` 复算。
- `deduplication.fuzzy_candidates` = `stats.fuzzy_candidates`；默认这些是候选，
  不是已合并数。
- `conflicts.count` = `conflicts.csv` 数据行数；`provenance.rows` = `provenance.csv`
  数据行数。
- `coverage.per_source` 取 `merged.json.coverage`；`gaps` 取 `merged.json.gaps`，
  不得只写"部分库不可用"而省略库名与状态。
- `status=partial` 时 `limitations` 必须列出具体缺失字段/库/未决候选；
  `blocked` 时说明卡点与已产出的部分。

## 4. 案例覆盖规则

契约可能使用不同组织方式，按语义映射：

| 契约常见名 | 取值来源 |
|-|-|
| `results` / `records` / `merged_records` | `merged.json.records` |
| `count` / `total` / `unique_count` | `stats.clusters`（去重后的唯一论文数） |
| `duplicates` / `dedup` | `duplicates.csv` 行；区分 merged 与 candidate_review |
| `conflicts` / `field_conflicts` | `conflicts.csv` 行 |
| `sources` / `per_database` | `merged.json.coverage` 与 `source_status` |
| `evidence` / `provenance` / `trace` | `provenance.csv` 行 |
| `missing` / `gaps` / `coverage_gaps` | `merged.json.gaps` + `issues` 中缺失字段统计 |
| `ranking` / `relevance` | 若契约要求排序，写明实际排序键（如 priority、来源数、年份）与并列规则 |

要求"每条记录带来源"时，以合并记录的 `fields.*.source_db/raw_file/raw_locator` 为准，
不得只给库名而无定位符。要求"覆盖比较"时，用 `coverage.per_source.fields_present`
对比各库字段完整度，并明确单库独有的记录数与字段。

## 5. 一致性与禁止项

- `result.json`、`merged.json`、各 CSV、`report.md` 的记录数、簇数、冲突数必须一致。
- 每条合并记录的关键字段必须能沿 `provenance.csv` 回溯到库、查询、原始定位。
- 所有路径使用 `/input`、`/app/work`、`/app/output`；不写个人绝对路径。
- 不提交预生成答案、固定案例结论、伪造的响应或运行统计。
- 合成示例必须标注"合成示例，非官方案例"。
