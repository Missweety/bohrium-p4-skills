# 输出契约（研究趋势）

`result.json` 顶层字段；题面 `output_contract` 中的字段名原样回填，无值写 `null` 并进 `limits`。

| 字段 | 类型 | 说明 |
|-|-|-|
| `case_id` | string | 原样回填 |
| `status` | string | `ok` 要求 `checks.metrics` 全 true；否则 `partial`/`blocked` |
| `research_product` | object | `question`、`report_markdown`、`themes[]`、`trends{distribution,stages,emerging_terms}` |
| `answer` | string | 与 `research_product.report_markdown` 相同的草稿正文，便于通用消费者读取 |
| `evidence_matrix` | array | 每条纳入文献一行 |
| `screening` | object | `criteria`、`included`、`excluded`、`duplicates`、`counts` |
| `uncertainty` | object | `missing_year`、`missing_abstract`、`missing_fulltext`、`contradictions`、`note` |
| `checks` | object | `items[]`（name/ok/detail）+ `metrics` |
| `failures` | array | `{file|source_id, reason}` |
| `sources` | array | `{path, kind}`，仅实际读取的根目录 |
| `limits` | string | 未完成项与原因，不得为空字符串掩盖 |
| `counts` | object | `included`/`themes`/`gaps`/`years` |

## `evidence_matrix[]`

| 字段 | 说明 |
|-|-|
| `source_id` | `S01`…，全文与报告引用共用 |
| `title` / `authors` / `year` / `venue` / `doi` | 缺失为 `null`，不推断 |
| `design` | 原文出现的研究设计词（randomized/cohort/…）；未出现为 `not_reported` |
| `key_findings` | 原文结果句，最多 2 条，逐字，不改写 |
| `limitations` | 原文局限/未来研究句，最多 2 条 |
| `evidence_strength` | `high`（全文 + 数值结果 + p/CI/n）、`medium`（全文 + 结果句）、`low`（仅摘要或无结果句） |
| `quotes` | `[{quote, page, paragraph}]`，`quote` 必须是原文子串 |
| `themes_hint` | 高频词项（用于主题聚类，不是结论） |
| `has_fulltext` / `has_abstract` / `has_year` | 缺失证据的显式标记 |

## `screening`

```json
{"question": "...",
 "criteria": {"include_terms": ["buffer"], "exclude_terms": ["soil"],
              "year_from": 2010, "year_to": 2024, "require_fulltext": false,
              "source": "case fields"},
 "included": [{"source_id": "S02", "...": "..."}],
 "excluded": [{"source_id": "S01", "title": "...", "year": 1998,
               "reasons": ["year_out_of_range"]}],
 "duplicates": [{"source_id": "S03", "duplicate_of": "S02", "key": "10.1000/..."}],
 "counts": {"found": 7, "included": 3, "excluded": 4, "duplicates": 1,
            "reasons": {"year_out_of_range": 1, "duplicate": 1}}}
```

计数闭合：`found = included + excluded`；重复文献计入 `excluded` 且单列 `duplicates`。

## `research_product.trends`

| 字段 | 说明 |
|-|-|
| `distribution` | `[{year, count, sources[]}]`，只含实际有文献的年份，可由 sources 复算 |
| `stages` | `[{stage, years:[from,to], count, top_terms[], representative[{source_id,title,year,basis}]}]` |
| `emerging_terms` | `[{term, first_year, last_year, count}]`；仅 `count>=2`、跨度≤2 年且最近年份≥语料最大年份-1 |
| `missing_year` | 未进入年度统计的 source_id，不用文件时间补 |

## `uncertainty`

- `missing_year`：未进入年度统计的 source_id，**不得**用文件时间替代。
- `missing_abstract` / `missing_fulltext`：影响主题与证据强度，已在报告第 6 节说明。
- `contradictions`：`{theme_terms, a, b, note}`；`note` 固定提示需人工核对结局与统计口径。
- 无法确定项（如只有摘要、扫描件）只写事实与影响，不写"可能""大概"。

## 降级口径

- 纳入后为空：`research_product.report_markdown` 写清"无纳入文献"及排除原因统计，`status=partial`。
- 仅有题录无全文：可纳入，但 `evidence_strength=low`，主题只基于标题/摘要词项。
- 同一 DOI 多版本：保留首条，其余进 `duplicates` 并保留来源路径，不丢弃记录。
