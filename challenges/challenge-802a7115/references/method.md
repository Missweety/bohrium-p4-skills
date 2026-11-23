# 方法与字段规则

本文件说明 `scripts/language_matrix.py` 的输入、判定规则、输出 schema 和人工复核边界。示例中的标识均为合成占位符。

## 1. 输入与读取

`--input` 接受单文件（`.csv/.tsv/.json/.jsonl`）或目录。目录按路径排序递归扫描，跳过 `case.json`、`task.md`、`resources.yaml`、`environment.yaml` 和隐藏目录。CSV 使用首行表头；JSON 接受数组，或对象中 `records/versions/works/rows/data/items` 的数组；JSONL 逐行解析。

字段别名按“去空白、连字符、下划线、点后小写”比较，例如 `work_id`、`workId`、`work` 等价。至少识别两个记录字段才把文件当作记录文件，否则记入 `input_notes` 并跳过。

定位规则：记录自带 `locator` 时优先使用；否则 CSV 记为 `row:N`（N 为物理行号，表头为第 1 行），JSON 记为 `record:N`，JSONL 记为 `line:N`。`container_file`/`container_locator` 始终指向实际解析位置，`source_file`/`locator` 保留记录声明。

## 2. 语种校验

1. Unicode NFKC 规范化，去首尾空白，`_` 转 `-`。
2. 一个 `language` 字段可含多个值：CSV 单元格用 `;`、`,`、`|`、`/` 分隔，JSON 可用数组；脚本拆分后按规范化标签去重。多语/双语记录会同时进入每个语种的矩阵格，`language` 与 `language_primary` 用 `;` 连接。
3. 常见语言全名映射为代码（`English → en`，`Portuguese → pt`，`中文/汉语/普通话 → zh` 等）。
4. ISO 639-2/3 代码先映射为 2 字母主标签（`por → pt`，`eng → en`，`zho/chi → zh`，`deu/ger → de` 等），再保留可能的区域后缀（如 `por-BR → pt-BR`）。
5. 语法要求 `^[a-z]{2,3}(-[a-z0-9]{2,8})*$`。合法标签保留完整小写形式（如 `pt-br`），`language_primary` 取第一段。
6. 映射后的主标签在内置表中 → `language_verified=true`；合法但未收录 → `language_unverified` 警告；任一值不合法 → `language_invalid` 错误。
7. 内置表只覆盖常见 2 字母代码和部分 ISO 639-2/3 代码，不是完整注册表。
8. `--expected-languages` 使用同一解析器：`por,eng` 会归一为 `pt,en`，中文名归一为 `zh`；覆盖检查只比较归一后的主标签。

语言判定的事实依据是实际原文，不是标签。脚本不重新识别语言；标签冲突时由 Agent 读原文后人工覆盖，并在 `report.md` 记录依据。

## 3. 版本类型

只接受 `original, translation, abstract_only, duplicate, bilingual`。常见别名归一：`orig/source → original`，`translated/full_translation → translation`，`abstract/abstract-only → abstract_only`，`dup → duplicate`，`multilingual → bilingual`。未知值记 `version_type_invalid`，不得猜测成最接近的类型。

全文覆盖只计 `original`、`translation`、`bilingual`；`abstract_only` 只证明有摘要，不证明有全文。精确重复记录不计入覆盖。

## 4. 重复、冲突与孤立

- **精确重复**：`work_id + version_id + language + version_type + DOI` 完全相同。按确定性顺序保留首条（`record_id` 最小），其余 `record_status=duplicate`，`duplicate_of` 指向保留记录。
- **版本冲突**：同一 `work_id + version_id` 出现不同语言、版本类型或 DOI。所有相关记录标 `version_conflict`，不自动择一。
- **孤立版本**：`translated_from` 在全部记录中不存在 → `orphan_version` 错误；只存在于其他 `work_id` → `orphan_cross_work` 警告；缺 `version_id` → `version_id_missing` 并计为孤立。
- **DOI 异常**：不符合 `^10\.\d{4,9}/\S+$` → `doi_invalid`；同一 DOI 跨作品 → `doi_cross_work_conflict`；同一作品多版本共享 DOI → `doi_shared_across_versions`（提示人工核对出版社版本编号）。

阈值均为确定性的集合运算，没有时间窗或概率分数。

## 5. 矩阵 schema

`matrix.json` 顶层：

| 字段 | 含义 |
|---|---|
| `tool`,`schema_version` | 固定标识 |
| `status` | `ok` / `issues` / `empty` / `failed` |
| `input`,`input_files`,`input_notes` | 输入路径、成功解析文件及计数、跳过原因 |
| `expected_languages` | 命令行声明的目标语种（归一后） |
| `counts` | 记录、作品、语种、翻译、摘要、重复、冲突、孤立、问题计数 |
| `works` | 逐作品矩阵数组 |
| `issues` | 与 `issues.csv` 相同的对象数组 |
| `notes` | 方法与边界声明 |

`works[]` 每项：`work_id, titles, dois, record_count, distinct_version_ids, languages{lang:{version_type:[version_id]}}, full_text_languages, abstract_only_languages, has_original, missing_expected_languages, flags, record_ids`。

`flags` 取值：`original_missing`、`abstract_only_coverage`、`multilingual_work`、`duplicate_versions`、`bilingual_present`、`missing_language`、`orphan_version`、`version_conflict`、`duplicate_version`。

`versions.csv` 列：`record_id, work_id, version_id, language, language_name, language_primary, language_verified, version_type, doi, title, translated_from, source_file, locator, container_file, container_locator, record_status, duplicate_of, flags`。

`issues.csv` 列：`severity, code, record_id/…`（本脚本为 `work_id, version_id, source_file, locator`）, `detail`。`severity` 仅用于排序和提示，不改变记录内容。

## 6. 问题代码

`work_id_missing`、`version_id_missing`、`language_missing`、`language_invalid`、`language_unverified`、`version_type_missing`、`version_type_invalid`、`title_missing`、`doi_invalid`、`translation_link_missing`、`provenance_missing`、`version_conflict`、`duplicate_version`、`orphan_version`、`orphan_cross_work`、`doi_cross_work_conflict`、`doi_shared_across_versions`、`original_missing`、`language_missing`（期望语种）、`expected_language_invalid`、`input_empty`、`input_error`。

## 7. 人工复核清单

- 每条译文的 `translated_from` 是否指向真实原文记录；
- 每个 `abstract_only` 是否确实没有全文版本；
- 多语作品的标题是否指向同一研究而非同名不同研究；
- 重复记录是否只是导出副本，而非不同版本；
- 期望语种是否来自案例声明，而不是自行假设；
- 每条引用能否回到当前原文的页/行。

## 8. 示例（合成）

输入一行：`W1,V2,en,translation,10.1000/abc,Study,V1,paper_en.pdf,page:1`。若 `V1` 是 `W1` 的 `pt/original`，矩阵记录 `W1` 的 `full_text_languages=[en,pt]`、`multilingual_work`；若 `V1` 缺失，则同时出现 `orphan_version` 与 `original_missing`。该示例只说明字段关系，不是任何官方案例的数据或答案。
