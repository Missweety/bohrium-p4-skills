# 默认输出契约（阅读10 · 文献总结与结构化笔记）

题面 `output_contract` 优先；本文件只补缺项。`result.json` 顶层字段：

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填输入案例标识 |
| status | enum | 是 | ok / partial / blocked / refused |
| answer | string | 是 | 主结果：按原文章节的笔记正文（Markdown），每条带锚点 |
| structured | object | 是 | 见下表 |
| evidence | array | 是 | `[{claim, source_path, locator, quote}]`，`quote` 必须是原文逐字片段 |
| uncertainty | array | 是 | 未报告/无法判断/冲突项，含定位与原因 |
| limits | string | 否 | partial 时说明未覆盖章节与原因 |
| changes | array | 否 | 章节重排、OCR、锚点修正等记录 |

`structured` 字段：

| 键 | 类型 | 说明 |
|-|-|-|
| sections | array | 原文实际章节顺序 |
| field_counts | object | 六字段各自条目数 |
| anchors_total | int | 锚点总数 |
| anchors_verified | int | quote 逐字命中的锚点数 |
| inference_count | int | `kind: inference` 条目数 |
| conflict_groups | array | `[{group, topic, positions, values}]` |
| check_summary | object | `{errors, warnings, missing_fields, quote_not_verbatim}` |
| artifacts | object | `{notes_md, notes_json, anchors_csv, note_check}` 相对路径 |

`status` 判定：
- `ok`：六字段非空、`errors=0`、quote 全部逐字命中。
- `partial`：部分章节未覆盖/图表为图/超长截断，`limits` 列出章节。
- `blocked`：无可用文本层，不产出伪笔记。
- `refused`：要求补造数据或代写结论，说明拒绝理由。
