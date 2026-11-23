# 默认输出契约（reading 契约 + 深度研究附加字段）

`case.json` 若提供 `output_contract`，**以题面为准**：其中每个字段都必须出现在 `result.json` 顶层，
缺失视为未完成。本文件只做补全。

## 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填输入案例标识 |
| status | enum | 是 | ok / partial / blocked / refused |
| answer | string | 是 | 综述主文（题面语言），每条结论带证据 id |
| structured | object | 是 | 见下表 |
| evidence | array | 是 | `[{claim, source_path, locator, quote, grade, stance}]` |
| uncertainty | array | 是 | 冲突、单一来源、不可读材料、年份缺失等 |
| limits | string | 否 | partial 时说明未完成子问题与材料限制 |

## structured 建议字段

| 字段 | 内容 |
|-|-|
| `decomposition` | `[{id, text, facet, depends_on, search_terms[], stop_condition}]` |
| `search_log` | `[{subq, query, tool, scope, hits, empty, decision}]` |
| `evidence_matrix` | `[{id, subq, source_path, locator, quote, grade, directness, stance, year}]` |
| `coverage` | `[{subq, verdict, evidence_count, distinct_sources, single_source}]` |
| `conflicts` | `[{subq, sources[], difference}]` |
| `counter_evidence` | 反证证据 id 与定位 |
| `gaps` | `[{subq, basis, missing}]` |
| `verification_todo` | `[{item, needs, would_upgrade, blocks}]` |
| `source_inventory` | `{files_total, files_readable, files_unreadable[]}` |
| `artifacts` | 实际落盘文件名列表 |

## 落盘产物

`research_report.md`、`evidence_matrix.csv`、`plan.json`、`search_log.json`、`evidence_rank.json`、
`quote_check.json`（中间件放 `/app/work`）。

## status 取值

- `ok`：全部子问题 covered，或无覆盖已用检索记录明确声明。
- `partial`：部分子问题 weak/not_covered、材料不可读，或预算内未完成。
- `blocked`：材料缺失/不可读，无法形成任何有证据的结论。
- `refused`：请求需要联网或材料外文献，超出执行期能力。
