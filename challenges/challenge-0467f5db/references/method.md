# 方法、判定规则与数据契约

本文档说明 `scripts/coverage_audit.py` 如何把参考集与命中记录变成可复算的覆盖结论。
规则版本：`coverage-audit/1.0`。

## 1. 两个集合

### 1.1 参考集（分母来源）

每条记录至少有：

| 字段 | 必需 | 说明 |
|-|-|-|
| `ref_id` | 建议 | 稳定标识；缺失时脚本按 `REF-001` 编号，但会降低可追溯性 |
| `doi` | 二选一 | DOI；支持 `10.x/...`、`https://doi.org/...`、`doi:` 前缀 |
| `title` | 二选一 | 标题；与 DOI 至少有一个可用 |
| `authors` | 建议 | 分号、竖线、`&`、顿号、`and` 或逗号分隔；用于作者 Jaccard |
| `year` | 建议 | 4 位年份；缺失会导致无法确认命中 |
| `include_reason` | 建议 | 纳入理由（综述/指南/专家清单等） |
| `unavailable` | 可选 | 撤稿、无法获取全文等；真值进入不可用清单 |
| `miss_category` | 可选 | 已知遗漏类别；未给则输出 `unlabeled` |

### 1.2 命中记录（分子来源）

| 字段 | 必需 | 说明 |
|-|-|-|
| `record_id` | 建议 | 导出记录标识；缺失时按 `HIT-001` 编号 |
| `doi` | 二选一 | 同上 |
| `title` | 二选一 | 同上 |
| `authors` | 建议 | 同上 |
| `year` | 建议 | 同上 |
| `query_id` | 建议 | 该记录来自哪次查询，用于漏检归因 |
| `source` | 建议 | 数据库/导出批次 |

支持 CSV、TSV、JSON、JSONL。CSV 分隔符自动在 `,`、`;`、`\t` 中判断。
JSON 可以是对象数组，也可以是包含 `references`/`reference_set` 与 `hits`/`records` 两个数组的对象。

## 2. 规范化

- `norm_doi`：转小写，去掉 `https://doi.org/`、`http://dx.doi.org/`、`doi:` 前缀与尾部标点。
- `norm_title`：NFKC → 小写 → `&` 视为 `and` → 只保留字母与数字。
  因此大小写、空格、连字符、标点差异不影响"标题相同"的判断。
- `norm_year`：取第一个 19xx/20xx。
- `author_surnames`：按 `;`、`|`、`&`、`、` 与单词 `and` 分作者；含逗号时取逗号前整段作为姓氏
  （如 "Smith, John" → `smith`）；不含逗号时取首个非首字母缩写 token，即按 "Family Given"
  顺序（如 "Smith John" → `smith`，"J Smith" → `smith`）；中文无空格姓名整串保留。
  返回姓氏集合。

## 3. 匹配判定（固定阈值）

按顺序执行，命中即停止：

1. 双方 DOI 均非空且规范化后相等 → `hit`，`match_method=doi`，`match_score=1.0`。
2. 规范化标题完全相同：
   - 年份均存在且相等，作者均存在且姓氏 Jaccard ≥ **0.85** → `hit`，
     `match_method=title_year_author`。
   - 年份冲突 → `uncertain`（`year conflict`）。
   - 任一年份缺失 → `uncertain`（`year missing`）。
   - 作者缺失 → `uncertain`（`author metadata missing`）。
   - 作者 Jaccard < 0.85 → `uncertain`（给出实际 Jaccard）。
3. 标题不完全相同，但字符二元组 Jaccard ≥ **0.90** 且年份相同 → `uncertain`（`near title`）。
4. 其余 → `miss`。

设计取舍：

- `uncertain` 永不进入命中分子；覆盖率不会因为"看起来像"而虚高。
- 没有 DOI 时，标题+年份+作者三者同时成立才算命中，避免同名综述误配。
- 作者阈值 0.85 允许作者列表略有出入（如少一位合作者、缩写差异），但不允许完全换作者。
- 标题近似阈值 0.90 只用于提示人工复核，不用于自动命中。

## 4. 指标与公式

设：

- `N` = 参考集总条数（含不可用）；
- `U` = 不可用条数；
- `D = N − U` = 分母；
- `H` = `hit` 数；
- `M` = `miss` 数；
- `Q` = `uncertain` 数。

输出：

```
覆盖率        = H / D
遗漏率        = M / D
不确定率      = Q / D
含全部参考集覆盖率 = H / N
```

`H + M + Q = D` 必须成立。分母为 0 或未提供命中文件时，比率输出 `null`，不输出 0 冒充结果。

## 5. 漏检分类

分类来源只有三种，按优先级：

1. 参考集自带的 `miss_category`（`category_source=reference_set`）；
2. 通过 `--classify` 提供、且带证据的分类（`category_source=classify_input`）；
3. 无 → `unlabeled`（不推断原因）。

允许的类别是开放的，但必须能落到证据。推荐类别与所需证据：

| 类别 | 需要的证据 |
|-|-|
| `query_term_gap` | 查询式原文 + 同义/缩写/拼写变体未覆盖的位置 |
| `field_limit` | 检索字段设置（仅标题/仅摘要）与实际匹配字段 |
| `time_window` | 导出或查询的时间过滤条件 |
| `source_not_indexed` | 记录来自哪个库、该库是否被检索 |
| `identifier_anomaly` | 缺失/错误 DOI、标题截断、作者字段异常 |
| `unavailable` | 撤稿、禁售、无全文等状态 |
| `unlabeled` | 无可用证据 |

禁止把"数据库覆盖不足""关键词不好"作为最终类别；必须细化到查询式、字段、时间窗或来源。

## 6. 补检记录

`--supplements` 文件字段：

| 字段 | 说明 |
|-|-|
| `miss_category` | 对应遗漏类别 |
| `proposed_query` | 拟定或实际执行的查询式 |
| `executed` | `true/false`；默认 false；只有真实执行才可写 true |
| `new_hits` | 新增命中记录标识列表或数量 |
| `yield` | 新增命中数量；未给时由 `new_hits` 推导 |
| `stop_reason` | 停止该轮补检的理由 |
| `recovers_ref_ids` | 新增命中中能映射回参考集的 `ref_id` |
| `screened` | 该轮筛选记录数（可选） |
| `source` / `note` | 来源与备注 |

没有补检记录时，脚本按遗漏类别生成模板：`executed=false`、`new_hits=[]`、`yield=null`。

残余遗漏只在以下情况计算：存在已执行轮次，且每个已执行轮次都能通过 `recovers_ref_ids`
（或可直接识别为 `ref_id` 的 `new_hits`）映射回参考集。否则输出 `null` 并给出原因。

## 7. 输出文件

### `coverage.csv`

一行一条纳入分母的参考记录：

`ref_id, doi, title, authors, year, unavailable, status, match_method, matched_record_ids,
match_score, match_reason, doi_conflict, candidate_record_id, miss_category, category_source,
include_reason, note`

### `misses.csv`

只包含 `status=miss` 的记录；`uncertain` 保留在 `coverage.csv` 与 `result.json` 中，
避免把"不确定"当成"已确认遗漏"。

### `report.md`

人读报告：输入与口径、指标表、不可用记录、重复候选、逐条状态、遗漏分组、补检与残余遗漏、
不确定性与限制、复跑命令。

### `audit.json` / `result.json`

`audit.json` 是完整结构化结果；`result.json` 在 `--case` 提供时额外把 `output_contract`
字段映射到顶层，并写 `contract_mapping`。

## 8. 示例（合成，非官方案例）

参考记录：

```
ref_id=R2, doi=(空), title="Beta Study of Y", authors="Brown K; Lee M", year=2021
```

命中记录：

```
record_id=H2, doi=(空), title="Beta study of Y!!", authors="Brown K; Lee M", year=2021
```

标题规范化后都是 `betastudyofy`；年份相同；作者姓氏集合都是 `{brown, lee}`，Jaccard = 1.0 →
`hit`，`match_method=title_year_author`。

反例：标题相同但作者为 `Kims S`，与 `Kim S` 的姓氏集合 Jaccard = 0 → `uncertain`，不计入命中。

## 9. 已知限制

- 仅比较元数据，不验证全文内容或研究结论。
- 作者姓氏提取是启发式：假设无逗号时按 "Family Given" 顺序；若导出为 "Given Family"
  （如 "John Smith"）会被误取为 `john`，需抽检或回填带逗号格式。复姓（"van der Berg"）
  无逗号时只取首词；机构作者、全角姓名同样可能不准确。
- 逗号分隔的姓名按两两配对（"Smith, John, Doe, Jane"）；段数为奇数时退化为取首 token，
  可能误配，需人工复核。
- 标题二元组相似度对极短标题区分力弱，因此只用于 `uncertain` 提示。
- 参考集重复只标记不合并；是否合并由人工依据版本信息裁决。
- 覆盖率不构成数据库全局召回或检索穷尽性的证明。
