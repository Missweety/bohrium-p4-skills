# 输出契约：默认映射与案例覆盖规则

`/input/case.json` 中的 `output_contract` 是唯一权威。本文件只给默认映射和覆盖规则；任何案例的字段名、类型、层级与必需性都以运行时读到的契约为准。

## 1. 读取顺序

1. 读 `/input/case.json`，取 `case_id`（若无则用文件名/任务中的显式标识）和 `output_contract`。
2. `output_contract` 可能是：字段到类型的对象、字段说明数组（含 `name/type/required/description`），或嵌套对象。先归一为 `字段路径 → (类型, 是否必需)`。
3. 读 `/input/task.md` 与 `environment/resources.yaml`（存在时），确认额外路径、命名和禁用项。
4. 先运行脚本产出工作数据，再按契约生成 `/app/output/result.json`。

## 2. 默认语义映射

契约字段名不固定，按语义匹配到以下产物。匹配时优先精确键名，其次同义键，再次字段说明文本。

| 语义 | 可能键名 | 本次来源 |
|---|---|---|
| 案例标识 | `case_id`, `id`, `task_id` | 原样保留，不改写 |
| 检索结果/候选 | `results`, `candidates`, `papers`, `items`, `matches` | `versions.csv` 去重后的作品/版本行 + 证据定位 |
| 语言矩阵 | `matrix`, `language_matrix`, `versions`, `languages` | `matrix.json.works` |
| 证据/来源 | `evidence`, `sources`, `provenance`, `citations` | 每条记录的 `record_id + source_file + locator` |
| 查询记录 | `queries`, `search_log`, `rounds` | `report.md` 的逐语种查询表 |
| 术语表 | `terms`, `glossary`, `terminology` | `report.md` 术语表章节（或可选 `term-table.csv`） |
| 翻译日志 | `translation_log`, `translations` | `translation-log.csv` |
| 计数 | `counts`, `summary`, `statistics` | `matrix.json.counts` |
| 状态 | `status`, `run_status`, `state` | `matrix.json.status` 与人工判定合并 |
| 不确定性/缺口 | `uncertainty`, `limitations`, `gaps`, `issues` | `issues.csv` + 未完成项 |
| 报告 | `report`, `report_path`, `writeup` | `/app/output/report.md` |

## 3. 覆盖规则

1. **键名以契约为准**：契约写 `candidates` 就不要输出 `results`；写嵌套 `result.literature[]` 就按嵌套生成。默认映射只用于决定“取哪份数据”，不用于改契约字段名。
2. **类型保持**：契约要求数组时给数组（每条含证据位置），要求字符串时给路径或摘要，要求对象时给对象；不把数组压成逗号串。
3. **必需字段**：逐项检查是否存在。无法产生时写 `null`，并在 `field_status[字段]` 记录 `missing`、原因和已尝试来源；不得用编造内容占位。
4. **额外字段**：契约有而默认映射没有的字段（如 `ranking_basis`、`dedup_report`），从 `matrix.json`、`versions.csv`、`report.md` 的真实内容取值；仍无来源则 `null` + `field_status`。
5. **case 覆盖**：案例可在 `case.json` 中给出字段级说明（例如要求 `evidence[].page`）。以说明为准；同一语义在不同案例的字段路径可以不同，代码和文档都不得假定固定路径。
6. **不预生成**：不得在提交物中放案例答案；`result.json` 必须在运行时根据实际输入生成。

## 4. 默认 result.json 骨架（字段名仍以契约为准）

```json
{
  "case_id": "<运行时读取>",
  "status": "ok | partial | empty | failed",
  "results": [
    {
      "work_id": "…",
      "version_id": "…",
      "language": "…",
      "version_type": "…",
      "doi": "…",
      "title": "…",
      "evidence": [{"source_file": "…", "locator": "page:1", "quote": "原文逐字片段"}]
    }
  ],
  "matrix": {"works": []},
  "translation_log": [],
  "counts": {},
  "uncertainty": [],
  "field_status": {},
  "report_path": "/app/output/report.md",
  "sources": ["/app/work/lang-matrix/matrix.json", "/app/work/lang-matrix/versions.csv"]
}
```

## 5. 状态取值

- `ok`：契约必需字段齐备，记录与证据可回查，无未处理冲突。
- `partial`：主结果可用，但存在未读原文、缺失语种、冲突未裁决或部分字段无来源；必须在 `uncertainty` 列出。
- `empty`：输入确实无记录，或全部记录被排除；保留空数组和原因。
- `failed`：输入不可用或脚本 fatal；保留错误信息，不输出猜测结果。

`field_status` 建议结构：`{"<字段路径>": {"state": "filled|missing|partial", "source": "…", "note": "…"}}`。若契约未要求，可省略，但 `status` 与 `uncertainty` 不能省略。
