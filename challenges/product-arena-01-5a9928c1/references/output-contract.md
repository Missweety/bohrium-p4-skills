# 默认输出契约（阅读03 · 文献翻译）

题面 `output_contract` 优先；本文件只在其缺项时补全。`result.json` 顶层字段：

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填输入案例标识 |
| status | enum | 是 | ok / partial / blocked / refused |
| answer | string | 是 | 主结果：译文摘要 + 覆盖段号范围（如 `P001-P048`），按目标语言书写 |
| structured | object | 是 | 见下表 |
| evidence | array | 是 | `[{claim, source_path, locator, quote}]`，`quote` 必须是原文逐字片段 |
| uncertainty | array | 是 | 未译/未定术语/指代不明/公式为图等，含原因与段号 |
| limits | string | 否 | partial 时说明未覆盖段号与原因 |
| changes | array | 否 | 段重排、OCR、术语合并等修改记录 |

`structured` 字段：

| 键 | 类型 | 说明 |
|-|-|-|
| segments_total | int | 切分出的原文段数（含标题/图注/表注） |
| segments_translated | int | 已有译文的段数 |
| covered_range | string | 已译段号范围，如 `P001-P048` |
| glossary_entries | int | 术语表条目数 |
| glossary_source | enum | given / auto / mixed |
| locked_hit_rate | number | 术语锁定命中率（0–1） |
| check_summary | object | `{missing_locked, variant_drift, numbers_missing, numbers_added, markers_missing, citations_missing, empty_targets}` |
| artifacts | object | `{translation, glossary, alignment, term_check}` 相对路径 |

`status` 判定：
- `ok`：全部段有译文，`check_summary` 六项错误指标为 0。
- `partial`：部分段未译/公式表格为图/原文残缺，`limits` 必须列出段号。
- `blocked`：无可用原文（扫描件无 OCR、文件损坏），不产出伪译文。
- `refused`：请求要求改写数据或伪造原文，说明拒绝理由。
