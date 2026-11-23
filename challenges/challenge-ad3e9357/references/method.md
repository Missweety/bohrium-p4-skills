# 方法与字段规则

本文件说明 `scripts/patent_normalize.py` 的规范化规则、聚类口径、输出 schema 与复核边界。示例标识均为合成占位符。

## 1. 输入与读取

`--input` 接受单文件（`.csv/.tsv/.json/.jsonl`）或目录。目录按路径排序递归扫描，跳过 `case.json`、`task.md`、`resources.yaml`、`environment.yaml` 和隐藏目录。CSV 用首行表头；JSON 接受数组或 `records/patents/rows/data/items` 数组；JSONL 逐行解析。

字段别名按“去空白、连字符、下划线、点后小写”比较，例如 `number`、`publication_number`、`pub_no` 等价；`family_id`、`family`、`docdb_family_id` 等价。至少识别两个记录字段才把文件当作记录文件，否则记入 `input_notes` 并跳过。

定位：记录自带 `locator` 优先；否则 CSV `row:N`（表头为第 1 行）、JSON `record:N`、JSONL `line:N`。`container_file`/`container_locator` 指向实际解析位置。

`source_index.py` 不提供 OCR：扫描型 PDF（如部分 WO 出版物）若无嵌入文本会标记不可提取。此时不得从文件名或图像推测内容，应降级为公开著录项/摘要级信息，人工目视核对号码、kind、页码与状态，并在交付物标注 `ocr_unavailable` 与核对方式。

## 2. 公开号规范化

目标形式：`CC + 号码 + kind`，全部大写、无分隔符。

1. Unicode NFKC 后去除非字母数字字符；
2. 确定 `CC`：优先 `jurisdiction` 字段（常见机构名映射：USPTO→US、EPO→EP、WIPO→WO、JPO→JP、CNIPA→CN、KIPO→KR、DPMA→DE、UKIPO→GB、IPAU→AU、CIPO→CA、IPOS→SG）；否则取号码开头的 2–3 位已知专利局代码；
3. 剩余部分必须匹配 `^(\d+)([A-Z]\d{0,2})?$`，前段为号码、后段为 kind；
4. `kind` 期望形如字母加 0–2 位数字（A、A1、B2、U 等）；缺失标 `kind_missing`，异常标 `kind_unverified`；
5. 显式 `kind` 字段与号码尾部不一致时标 `kind_mismatch`，以号码尾部为准；
6. `jurisdiction` 与号码前缀不一致时标 `jurisdiction_mismatch`，采用号码前缀；无 `CC` 时 `normalized` 留空并标 `jurisdiction_missing`。

`normalized_valid` 仅在 `CC + 号码 + kind` 全部可解析时为真。解析失败保留原值，不猜补。

`application_no`、`priority` 只做去分隔符与大写；优先权按 `;` 或 `|` 拆分。缺司法辖区前缀的优先权号标 `priority_unverified`。带点校验位的申请号（如 `EP21123456.7`）去点后为 `EP211234567`，需在报告中说明这一转换。

## 3. 同族聚类口径

脚本用并查集构建“可观测族”：

- **号码合并**：同一 `normalized` 公开号的重复记录先并入同一记录组（保留 `duplicate_record`/`duplicate_of` 标记），不拆成多族；
- **显式族**：相同 `family_id`（去空白、大写后比较）的记录相连；
- **优先权扩展**：共享任一优先权号的记录相连；
- 以上关系共同出现时自然合并；既无 `family_id` 又无优先权的记录为单例，标 `family_unknown`；
- 同一簇出现多个不同 `family_id` → `family_conflict`（错误），不自动择一；
- 同簇多个优先权号 → `family_multiple_priorities`（提示），说明简单族与扩展族口径不同；
- 同簇 `scope` 取值：`declared_family`、`priority_extended`、`conflicting_declaration`、`singleton`。

`family_id` 与 `priority` 只反映本批记录中实际存在的连接，不是 DOCDB/INPADOC 完整族；报告必须写明这一点。

## 4. 状态分类与时效

状态文本先做分隔符归一，再按“否定/歧义 → 届满 → 失效 → 审中 → 有效”的顺序判定。否定词优先，避免 `not granted` 被 `granted`、`no longer in force` 被 `in force` 误判为有效：

| 类别 | 触发词示例 |
|---|---|
| `unknown`（否定/歧义） | no longer, not granted, not yet granted, never granted, not in force, not active, not valid, not enforceable, 未授权, 未生效, 不再有效, 尚未授权, 非有效 |
| `expired` | expired, lapsed, ceased, 失效, 届满, 终止 |
| `inactive` | abandoned, withdrawn, revoked, invalidated, rejected, refused, 撤回, 放弃, 驳回, 撤销, 无效 |
| `pending` | pending, under examination, filed, application, published, 申请中, 审查中, 审中, 待审, 公开 |
| `active` | active, granted, issued, registered, in force, valid, maintained, 授权, 有效, 维持 |

否定词命中一律返回 `unknown` 并标 `status_unverified`，不猜测为有效或失效。未匹配也返回 `unknown`。状态缺失、状态日期缺失或非法分别标 `status_missing`、`status_date_missing`、`status_date_invalid`。

日期接受 `YYYY-MM-DD`、`YYYY/MM/DD`、`YYYY.MM.DD`、`YYYYMMDD`、`YYYY-MM`、`YYYY`，并记录精度（day/month/year）。只有传入 `--as-of` 时才计算时效：状态日期晚于 as-of 标 `status_date_future`；早于 `--max-status-age-days`（默认 180）标 `status_stale`。年份/月份精度时另标 `status_date_low_precision`。**不传 `--as-of` 就不评估时效**，报告中明确说明。运行时使用当天日期 `--as-of "$(date +%F)"`，不要写死日期。

## 5. 来源与证据强度

`source_class`：

- `official`：`legal_scope` 为 official/primary/facsimile/registry/grant，或 `source_file` 含 uspto/epo/wipo/patentscope/espacenet/jpo/cnipa/kipo/dpma/inpi/ukipo/ipos/register/gazette 等标记；
- `secondary`：`legal_scope` 为 secondary/aggregator/third-party/derived/blog/news，或 `source_file` 含 google patents/freepatentsonline/justia/patentguru/lens.org/baidu/zhihu/sohu/blog/news 等；
- `unknown`：无法分类。

`legal_scope` 为 official 但来源标记为 secondary → `source_conflict`，按 secondary 处理。`legal_scope` 缺失 → `legal_scope_missing`。

`evidence_strength`：official 且号码有效、状态已分类且有状态日期 → `high`；official 或号码有效 → `medium`；其余 → `low`。仅凭状态文本子串（尤其是否定/歧义文本）不能得到 `high`。它只是记录级提示，不是法律结论。

## 6. 输出 schema

`normalized.csv` 列：`record_id, number_input, normalized, normalized_valid, jurisdiction, number_core, kind, kind_valid, application_no, application_no_norm, priorities, family_id, family_cluster, title, assignee, status, status_class, status_date, status_date_norm, status_date_precision, source_class, evidence_strength, legal_scope, source_file, locator, container_file, container_locator, duplicate_of, flags`。

`families.json` 顶层：`tool, schema_version, status, input, input_files, input_notes, as_of, max_status_age_days, counts, families, issues, notes`。`families[]` 每项：`family_id, basis, scope, declared_family_ids, priority_numbers, member_count, distinct_publications, jurisdictions, statuses, titles, assignees, conflicts, members[]`。成员含 `record_id, normalized, jurisdiction, kind, status, status_class, source_class, source_file, locator`。

`issues.csv` 列：`severity, code, record_id, normalized, source_file, locator, detail`。

重复记录：同一 `normalized` 号码只保留一个“规范记录”用于阅读，其余 `duplicate_of` 指向它；规范记录优先选择 `official` 来源。状态类别不同的同一号码标 `status_conflict`，两类信息都保留。

## 7. 问题代码

`number_missing`、`number_unparseable`、`jurisdiction_missing`、`jurisdiction_unverified`、`jurisdiction_mismatch`、`kind_missing`、`kind_unverified`、`kind_mismatch`、`application_no_missing`、`application_no_invalid`、`priority_unverified`、`family_unknown`、`family_conflict`、`family_multiple_priorities`、`record_conflict_family`、`status_missing`、`status_unverified`、`status_conflict`、`status_text_variant`、`status_date_missing`、`status_date_invalid`、`status_date_future`、`status_stale`、`status_date_low_precision`、`status_inactive`、`duplicate_record`、`source_missing`、`source_secondary`、`source_unverified`、`source_conflict`、`legal_scope_missing`、`input_empty`、`input_error`。

## 8. 人工复核清单

- 号码规范化结果是否与原始著录页逐项一致，尤其 kind 与 CC；
- 声明的 `family_id` 与优先权是否指向同一族，是否存在“同优先权不同声明族”；
- 状态是否来自官方登记页，查询日期与滞后是否写明；
- 聚合站记录是否只作线索，未被写成官方著录项；
- 权利要求版本是否来自实际公开文本，是否区分独立/从属与版本；
- 许可分级是否与数据源实际授权一致，红色来源是否已降级。

## 9. 示例（合成）

输入 `"US 10,123,456 B2",US,B2,16/123456,US 15/111,111,...` 与 `US10123456B2,US,B2,16/123456,US 15/111,111,...` 会规范为同一号码 `US10123456B2`，归入同一显式族，后者标 `duplicate_record` 并指向官方来源记录。若一条记录状态为 `Active`、另一条为 `Expired`，同时产生 `status_conflict`。该示例只说明规则，不是任何官方案例的数据或答案。
