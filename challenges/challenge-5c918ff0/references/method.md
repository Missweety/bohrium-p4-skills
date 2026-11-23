# 方法：多库记录规范化、去重、合并与回溯

本文描述 `scripts/merge_records.py` 的实际规则。脚本只处理输入中真实存在的记录；
它不查询数据库，也不判断论文的科学质量。

## 1. 读取与记录识别

- `--input` 可为目录或单文件；目录递归读取 `.csv/.tsv/.json/.jsonl`，按路径排序。
- JSON 对象识别 `records/rows/data/works/items/results/papers`；库状态识别
  `source_status/db_status/database_status/sources/databases`；查询日志识别
  `queries/search_queries/query_log`。
- 一个对象含 `title`、`doi` 或 `pmid` 即视为记录；没有身份值但含记录列
  （`authors/year/journal/type/raw_file/raw_locator/priority` 等）也作为记录进入校验，
  最终以 error `missing_identity` 丢弃并计入 `records_dropped`，退出码为 2。
- 只含库名与 `status/error` 的视为库状态；其余行记 `unclassified_record`。
- 定位符：CSV/TSV `row:N`（含表头的物理行号），JSONL `line:N`，JSON `item.key[i]`。
- `raw_file`/`raw_locator` 缺失时回退到实际文件与上述定位符，保证可回溯。

## 2. 规范化规则

| 字段 | 规则 | 失败处理 |
|-|-|-|
| DOI | 去 `https://doi.org/`、`http://dx.doi.org/`、`doi:`；去尾部 `.,;)]}`；转小写；须匹配 `^10\.\d{4,9}/\S+$` | 不匹配则视为无 DOI，不用它聚类 |
| PMID | 去 `pmid:` 前缀；必须为 1–12 位数字 | 否则视为无 PMID |
| 标题 | NFKC、转小写、标点转空格、去停用词后取 token；另存完整规范化串 | 空标题但有 DOI/PMID 仍保留 |
| 作者 | 按 `;` → `and` → 逗号切分；去除标点、转小写、合并空白 | 顺序差异保留为冲突，不擅自排序覆盖 |
| 年份 | 取字符串中第一个 1900–2099 的 4 位数 | 无法解析记 `missing` 并告警 |
| 期刊 | 与标题相同的规范化（大小写/标点/空白） | 空值记 `missing` |
| 类型 | 去标点后映射：`journalarticle/article` → `journal-article`，`conferencepaper` → `conference-paper`，`postedcontent` → `preprint`，`reviewarticle` → `review`，`bookchapter` → `book-chapter` 等 | 未识别保留紧凑串 |
| priority | 数值，越小越优先；非数值告警并使用默认序 | — |

停用词表只含通用词（`a/an/the/of/for/and/in/on/to/with/by/from/at/as/is/are/via/
using/into`），不移除 `study`、`analysis` 等可能承载主题的词，避免把不同论文判成重复。

## 3. 缺失与未知

- `missing`：该记录没有提供该字段（空串、字段不存在）。
- `unknown`：记录明确写了 `unknown`、`N/A`、`null`、`none`、`-`、`?` 等占位。
- 合并时只用 `present` 值；若整簇都缺失，`status=missing`；只有占位符则
  `status=unknown`，`value=null`。两者不得写成同一个状态，也不得用 `0` 或空串代替。

## 4. 去重与聚类

### 4.1 精确聚类

1. 按规范化 DOI 分组，同组记录合并（并查集 union）。
2. 按规范化 PMID 分组，同组记录继续合并。
3. 每个大小 >1 的组写入 `duplicates.csv`，`group_type=doi_exact|pmid_exact`，
   `decision=merged`。同一记录可同时出现在 DOI 组和 PMID 组，这是交叉验证，不是重复计数。

### 4.2 模糊候选

对当前不在同一簇的记录两两比较：

- `jaccard = |A∩B| / |A∪B|`，A/B 为标题 token 集合；空集时 Jaccard=0。
- 阈值：`--fuzzy-threshold` 默认 **0.9**；`>=` 阈值才算候选。
- 年份：两边都必须有年份，且 `|year_a - year_b| <= --year-tolerance`（默认 **1**）。
- 满足两条 → `group_type=fuzzy_title_year`，`decision=candidate_review`，默认不合并。
- Jaccard 达标但年份缺失或超出容差 → `fuzzy_near_miss`，`decision=not_merged`，
  写明原因，供人工复核。
- 同一对簇只保留最高 Jaccard 的一条候选，避免重复行。
- `--fuzzy-merge` 打开时才 union，并把 `decision` 改为 `merged_by_fuzzy`；报告中必须
  记录该参数与理由。默认关闭是刻意的：标题相近不等于同一论文。

### 4.3 不合并的情形

同名不同文、同一论文的预印本与期刊版（DOI 不同且年份可能不同）、仅有主题词相似的
平行工作、作者相同但标题不同，都不自动合并。它们最多进入候选或保持独立记录。

## 5. 字段合并与冲突

- 簇内逐字段收集 `present` 值；排序键：
  `(priority, source_db, raw_file, raw_locator, record_id)`，取第一个作为最终值。
- priority 缺失时：`--priority-order crossref,europepmc` 给出序号（从 1 开始）；
  仍未指定则统一用 1000，再按库名/文件/定位符稳定排序。
- 最终字段结构：

```json
{
  "value": "原始值",
  "normalized": "规范化值",
  "status": "present|missing|unknown",
  "source_db": "crossref",
  "raw_file": "crossref.json",
  "raw_locator": "records[0]",
  "source_record": "R00001",
  "source_count": 2
}
```

- 若同一字段存在多个不同的规范化值，按值分组：被选值写入字段，其余每个值写一行
  `conflicts.csv`（`chosen_*` 与 `other_*` 对照）。作者顺序不同也如实列为冲突，
  不擅自认定等价。
- `source_count` 是不同规范化值的个数，不是来源记录数。

## 6. 覆盖与缺口

- `coverage` 按 `source_db` 统计记录数与各字段 `present` 数；只反映输入快照。
- `source_status` 原样保留库状态、错误信息与定位。
- `gaps` 规则：
  - 状态不属于 `ok/success/available/complete/completed/200` → `source_unavailable_or_incomplete`；
  - 状态正常但 0 条记录 → `no_records`；
  - 有记录但未声明状态 → `status_unknown`。
- 报告必须区分"该库失败"、"该库成功但无结果"、"该库未声明状态"。

## 7. `merged.json` 结构

```json
{
  "generated_by": "merge_records.py",
  "scope_note": "Only supplied records ...",
  "input": {"root": "...", "files": ["..."], "record_rows_read": 0},
  "params": {"fuzzy_threshold": 0.9, "year_tolerance": 1,
             "fuzzy_merge": false, "priority_rule": "..."},
  "coverage": {"crossref": {"records": 0, "fields_present": {"doi": 0}}},
  "source_status": [{"source_db": "", "status": "", "error": ""}],
  "gaps": [{"source_db": "", "gap": "no_records", "detail": ""}],
  "stats": {"record_rows_read": 0, "records_valid": 0, "records_dropped": 0,
            "clusters": 0, "multi_record_clusters": 0,
            "exact_groups": 0, "fuzzy_candidates": 0, "conflicts": 0,
            "sources": 0, "gaps": 0, "issues": {}},
  "records": [{"cluster_id": "M0001", "record_ids": [], "source_dbs": [],
               "record_count": 2, "identity": {},
               "fields": {"title": {}}, "conflicts": []}],
  "issues": [{"severity": "", "code": "", "detail": "", "file": "", "locator": ""}]
}
```

`provenance.csv` 字段：
`cluster_id,field,record_id,source_db,raw_value,normalized_value,status,raw_file,
raw_locator,query,selected`。`selected=yes` 恰好是该字段被选中的来源记录。

## 8. 合成示例（非官方）

输入三条同行记录（虚构）：

| source_db | doi | pmid | title | year | priority |
|-|-|-|-|-|-|
| crossref | 10.9999/abc.1 | | Synthetic Widget Study | 2020 | 1 |
| europepmc | 10.9999/abc.1 | 12345678 | synthetic widget study | 2020 | 2 |
| openalex | 10.9999/abc.1 | 12345678 | Synthetic Widget Study | 2021 | 3 |

结果：三行按 DOI 精确聚成一簇；年限 2020 与 2021 产生 `year` 冲突；
`doi/title/year` 取 crossref（priority 最小），`pmid` 取 europepmc（唯一提供者）；
`provenance.csv` 有三条 doi 来源、两条 pmid 来源；`selected=yes` 每字段各一行。
这不代表任何真实文献。

## 9. 已知限制

- 只覆盖输入快照；不联网、不校验论文是否真实存在、不判断质量或撤稿状态。
- 标题模糊匹配对翻译标题、极短标题、副标题差异敏感；默认不自动合并。
- 作者切分是启发式，"Last, First" 与多作者逗号格式存在歧义，冲突交人工。
- 期刊缩写与全称、文献类型词表未穷尽；未识别类型保留原紧凑串并可能产生冲突。
- 年份缺失时不做模糊合并，宁可漏合并也不错误合并。
