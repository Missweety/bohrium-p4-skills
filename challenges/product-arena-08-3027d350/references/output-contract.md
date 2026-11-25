# 默认输出契约（文献文档解析）

`case.json` 若给出 `output_contract`，**以题面为准**；下表只用于补全题面未列出的字段。
`/app/output/result.json` 顶层：

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填输入案例标识，不改写、不省略 |
| status | enum | 是 | `ok` / `partial` / `blocked` / `refused`（题面若用 success，可与 ok 同义） |
| answer | string | 是 | 按题面语言的解析结论；必须说明哪些页/表可读、哪些不可读 |
| structured | object | 是 | 结构化解析结果，见下 |
| evidence | array | 是 | `[{claim, source_path, page, block_id, quote}]`，quote 必须逐字出自原文 |
| artifacts | object | 否 | `{相对路径: 内容}`，如 `locator_table.csv`、`tables/table_1.csv`；emit 会落盘 |
| uncertainty | array | 是 | 未报告 / 无法判断 / 冲突项，无则空数组 |
| limits | string | 否 | partial/blocked 时说明缺哪些页段、为什么、人工接管位置 |
| sources | array | 否 | 输入文件清单（路径 + sha1 前 12 位） |
| changes | array | 否 | 人工校正记录 `{target, before, after, reason}` |
| self_check | object | 否 | `{quote_check, verify, check}` 三项结论与未通过原因 |

`structured` 子字段：

| 字段 | 类型 | 说明 |
|-|-|-|
| document | object | `{file, page_count, text_layer: true/false, layout: single/two_column/mixed/unknown, engine}` |
| sections | array | `[{section_id, number, title, level, page_start, page_end, block_id, blocks, chars}]` |
| tables | array | `[{table_id, caption, page_start, page_end, header_rows, spans, continued_from, csv_path, notes}]` |
| figures | array | `[{figure_id, caption, page, block_id, subpanels}]`，仅图注，不含读数 |
| equations | array | `[{eq_id, number, page, block_id, text}]`，保留原文 Unicode，不臆造 LaTeX |
| references | array | `[{ref_id, text, page, block_id, doi, year}]`，缺失字段留空字符串 |
| footnotes | array | `[{note_id, page, block_id, text, marker}]` |
| furniture | array | `[{page, block_id, text, kind: header/footer/page_number}]`，不计入正文 |
| unreadable_pages | array | 页码列表，必须在 `answer`/`limits` 同步说明 |
| document_map | object | 关键结构出现页索引 `{title: 1, abstract: 1, references: 9}` |

一致性要求：`evidence[].block_id` 必须存在于 `locator_table.csv`；`evidence[].page` 必须与定位表一致；
`tables[].csv_path` 必须真实存在。
