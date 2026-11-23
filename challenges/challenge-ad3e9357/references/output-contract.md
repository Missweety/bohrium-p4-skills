# 输出契约：默认映射与案例覆盖规则

`/input/case.json` 中的 `output_contract` 是唯一权威。本文件只给默认映射与覆盖规则；字段名、类型、层级和必需性全部以运行时读到的契约为准。

## 1. 读取顺序

1. 读 `/input/case.json`，取 `case_id` 和 `output_contract`。
2. `output_contract` 可能是字段→类型对象、字段说明数组（`name/type/required/description`）或嵌套对象；先归一为 `字段路径 → (类型, 是否必需)`。
3. 读 `/input/task.md` 与 `environment/resources.yaml`（存在时），确认路径、命名和禁用项。
4. 先运行脚本产出工作数据，再生成 `/app/output/result.json`。

## 2. 默认语义映射

| 语义 | 可能键名 | 本次来源 |
|---|---|---|
| 案例标识 | `case_id`, `id`, `task_id` | 原样保留 |
| 检索结果/专利 | `results`, `patents`, `records`, `items`, `matches` | `normalized.csv` 逐记录行 |
| 号码规范化 | `normalized_numbers`, `numbers`, `publication_numbers` | `normalized.csv` 的 `number_input→normalized` |
| 同族 | `families`, `family_groups`, `clusters` | `families.json.families` |
| 法律状态 | `legal_status`, `patent_status`, `statuses` | `normalized.csv` 的 `status`、`status_class`、`status_date_norm`、来源与查询日期 |
| 权利要求 | `claims`, `claim_versions`, `claim_scope` | `/app/output/claims.csv` |
| 证据/来源 | `evidence`, `sources`, `provenance` | `record_id + source_file + locator` |
| 检索式 | `queries`, `search_strategy`, `search_terms` | `report.md` 主题检索式章节 |
| 许可/授权 | `license`, `authorization`, `data_scope`, `dependencies` | `report.md` 绿/黄/红分级表 |
| 证据强度 | `confidence`, `strength`, `risk` | `normalized.csv` 的 `evidence_strength` + 人工复核 |
| 计数 | `counts`, `summary`, `statistics` | `families.json.counts` |
| 运行状态 | `run_status`, `run_state` | 脚本 `status` 与人工判定合并 |
| 不确定性/缺口 | `uncertainty`, `limitations`, `gaps`, `issues` | `issues.csv` + 未完成项 |
| 报告 | `report`, `report_path`, `writeup` | `/app/output/report.md` |

## 3. 覆盖规则

1. **键名以契约为准**：契约写 `patents` 就不输出 `results`；嵌套路径按契约生成。
2. **类型保持**：数组保持数组，对象保持对象，不把同族数组压成字符串。
3. **必需字段**：逐项检查；无来源时写 `null`，并在 `field_status[字段]` 记录 `missing`、原因和已尝试来源，不得编造号码或状态。
4. **额外字段**：如 `family_scope_note`、`license_level`、`human_review`，从 `families.json.notes`、`report.md` 或许可分级表取值；无来源则 `null` + `field_status`。
5. **案例覆盖**：`case.json` 的字段级说明优先；不同案例可用不同字段路径，代码与文档不得假定固定路径。
6. **不预生成**：不得在提交物中放案例答案；`result.json` 必须在运行时由实际输入生成。

## 4. 默认 result.json 骨架（字段名仍以契约为准）

```json
{
  "case_id": "<运行时读取>",
  "run_status": "ok | partial | empty | failed",
  "results": [
    {
      "record_id": "R0001",
      "number_input": "…",
      "normalized": "US10123456B2",
      "jurisdiction": "US",
      "kind": "B2",
      "family_id": "…",
      "legal_status": "…",
      "status_class": "active",
      "source_class": "official",
      "evidence_strength": "high",
      "evidence": [{"source_file": "…", "locator": "page:1"}]
    }
  ],
  "families": [],
  "claims": [],
  "counts": {},
  "uncertainty": [],
  "field_status": {},
  "report_path": "/app/output/report.md",
  "sources": ["/app/work/patent-normalize/normalized.csv", "/app/work/patent-normalize/families.json"]
}
```

## 5. 运行状态与法律状态

`run_status` 只表示本次运行：

- `ok`：契约必需字段齐备，号码、同族、状态与来源可回查，无未决冲突。
- `partial`：主结果可用，但存在未核状态、同族口径不明、受限来源或部分字段无来源；必须在 `uncertainty` 列出。
- `empty`：检索确实无命中或输入无记录；保留空数组、检索式与原因。
- `failed`：输入不可用或脚本 fatal；保留错误，不输出猜测结果。

`legal_status`（逐条记录）只表示该专利的给定法律状态，来自 `normalized.csv` 的 `status`/`status_class` 与来源，不是运行状态。契约若只用裸 `status`，按位置判定：记录项内视为 `legal_status`，顶层视为 `run_status`，并在 `field_status` 说明映射。

`field_status` 建议结构：`{"<字段路径>": {"state": "filled|missing|partial", "source": "…", "note": "…"}}`。契约未要求可省略，但 `run_status` 与 `uncertainty` 不能省略。
