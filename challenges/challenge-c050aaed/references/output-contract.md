# 输出契约（anchored-annotation-notes v1.1.0）

运行时以 `case.json.output_contract` 为准；支持 `{"required": [...]}`、`{"fields": [...]}`、
`{"properties": {...}}` 或字段列表；字段名按小写、去 `_`/`-`/空格 归一后匹配下表。
契约未定义口径的字段不臆造取值，写入
`{"note": "输入契约未定义该字段的取值口径；已保留字段名与空值说明，不补造内容。"}`。
所有相对路径均相对材料根目录；哈希为 sha256。

## 标准字段

| 标准字段 | 常见契约别名 | 内容与完成标准 |
|-|-|-|
| `case_id` | caseId / id / task_id | 与输入案例一致 |
| `status` | run_status / state | `ok` / `partial` / `blocked` |
| `summary` | conclusion / abstract | 文件数、批注数、锚点通过率、笔记数、关联数一句话结论 |
| `input_inventory` | inventory / manifest / file_list | 每个文件的相对路径、sha256、字节、类型、可读/加密/符号链接 |
| `documents` | documents / files / docs | 文档 ID、标题、载体、页数、元数据、权限、重复与版本族 |
| `metadata_summary` | metadata / metadata_summary | 标题/作者/时间/页数/文件类型分布与缺失字段统计 |
| `version_relations` | version_relations / versions / dedup | 重复（同哈希）与版本族（同标题不同哈希）及合并依据 |
| `annotations` | annotations / highlights / marks | 逐条：类型、页、坐标、颜色、标签、逐字引文、备注、来源定位、锚点状态 |
| `anchor_quality` | anchor_quality / anchoring / locator_quality | 各锚点状态计数、通过率、多义/低保真/失败清单 |
| `notes` | notes / knowledge / structured_notes | 笔记类型、论断、支撑批注与引文、来源定位、支撑状态 |
| `links` | links / relations / associations | 起止笔记、依据类型、共享项、置信度、是否接受、拒绝原因 |
| `search_index_meta` | search_index / index / retrieval | 索引版本、笔记数、词表规模、支持的过滤维度 |
| `search_results` | search_results / queries / retrieval_results | 案例给出的每个检索问题的命中与召回说明 |
| `operations_log` | operations_log / ops / changes_log | 读取、解析、合并、跳过、恢复的操作序列（含脚本版本） |
| `conflicts` | conflicts / issues | 页码漂移、引文找不到、锚点多义、类型未识别等 |
| `failures_recovery` | failures_recovery / skipped / recovery | 不可读、加密、无文本层、批注对象不可解析及采取的降级 |
| `uncertainty` | uncertainty | 缺页/缺引文/低保真/未验证笔记等不确定项 |
| `limits` | limits | 未覆盖范围；`partial`/`blocked` 时必须非空 |
| `validation` | validation / checks | 机检项列表（`check`/`pass`/`detail`） |
| `changes` | changes | 相对上一版的变化（首版为空数组） |
| `assumptions` | assumptions | 材料即全集、颜色含义仅取图例等前提 |

## 锚点状态（`anchor.status`）

| 状态 | 含义 | `verified` |
|-|-|-|
| `exact` | 引文在该页原文精确出现，记录 `start`/`end` | true |
| `normalized` | 去空白/标点后出现，区间映射回原文 | true |
| `ambiguous` | 出现多次，记录首个区间并升级人工 | true（`ambiguous=true`） |
| `quote_missing` | 批注无引文（如 Ink 涂鸦） | false |
| `page_unknown` | 导出记录无页码 | false |
| `text_layer_unavailable` | PDF 无可用文本层（扫描/加密） | false |
| `low_fidelity_text` | 文本层乱码率过高，找不到引文 | false |
| `quote_not_found` | 文本层正常但引文不在该页 | false |
| `coordinate_only` | 只有坐标/笔迹，无文字 | false |
| `export_only` | 只有导出记录，无对应文档可校验 | false |

## 批注类型

`highlight` / `underline` / `strikethrough` / `wavy_underline` / `note` / `marginal_note` /
`free_text` / `handwriting` / `comment` / `web_clip` / `unknown`。

## 关联依据（`links.basis`）

`same_version_family`（同版本族）、`shared_label`（相同显式标签）、
`shared_entity`（共享词表实体/大写缩写）、`same_page_adjacent`（同页邻接≤80 字符）、
`keyword_overlap`（仅词面重合，默认拒绝）。

## 机检项（`validation.checks`）

1. `input_manifest_complete` — 每个可读材料文件都有哈希记录；
2. `every_annotation_has_locator` — 每条批注都有来源文件与对象/行号；
3. `no_guessed_anchor` — `verified=true` 必有 `start/end`，且来自实际查找；
4. `every_note_has_support` — 每条笔记至少 1 条支撑批注且引文非空；
5. `no_link_without_basis` — 接受关联都有依据与共享项；
6. `duplicates_and_versions_registered` — 重复/版本族已登记；
7. `contract_fields_present` — 契约字段全部出现在 `result.json`；
8. `no_silent_drop` — 不可读/不支持文件均在 `failures_recovery` 中列明。

## 交付物

| 文件 | 必需内容 |
|-|-|
| `annotations.csv` | 批注 ID、文档、类型、页、引文、备注、颜色、标签、锚点状态/区间、是否待复核 |
| `notes.csv` | 笔记 ID、类型、标题、论断、类型、支撑批注、来源、支撑状态 |
| `links.csv` | 起止笔记、依据、共享项、置信度、是否接受、原因 |
| `search_index.json` | 倒排索引与过滤元数据，供 `search.py` 使用 |
| `search_results.csv` | 检索问题、过滤条件、命中排名与锚点状态（案例给出问题时） |
| `audit_report.md` | 清单、锚点质量、版本关系、笔记/关联、冲突与自查 |
| `run_manifest.json` | 脚本版本、输入哈希、生成时间、计数与校验结果 |
