# 输出契约与字段映射

`/input/case.json` 的 `output_contract` 是权威字段表。本文件只定义**默认兜底字段**与
**别名映射规则**；实际字段名、类型和数量以运行时读到的 `output_contract` 为准，
不得把本项目录当成固定答案模板。

## 1. 动态映射流程

1. 读取 `case.json`：`case_id` 与 `output_contract`。
2. `output_contract` 支持三种形态：
   - 字符串数组：`["coverage","misses","report"]`；
   - 对象：`{"coverage": {...}, "misses": [...]}`，取顶层键作为字段；
   - 逗号/分号/换行分隔的字符串。
3. 运行：

```bash
python scripts/coverage_audit.py --input /input --case /input/case.json --out /app/output
```

4. 脚本按别名把核心结果写到 `result.json` 顶层；每个契约字段都会出现。
5. 若 `contract_mapping.unresolved_fields` 非空，说明该字段没有证据支持的内容：
   - 保持 `null`；
   - 在 `limits` 或 `uncertainty` 写明"该字段本次不可产出及原因"；
   - 不得用编造内容、占位答案或样例结果填充。

## 2. 默认字段（未给 output_contract 时）

| 字段 | 类型 | 内容 | 完成标准 |
|-|-|-|-|
| `case_id` | string | 与输入一致 | 原样保留 |
| `status` | string | `ok` / `partial` / `blocked` | `partial`/`blocked` 必须在 `limits` 说明 |
| `reference_set` | object | 总数、分母、不可用清单、重复候选、ref_id 列表 | 分母可复算 |
| `coverage` | object | 分子、分母、覆盖率、遗漏率、不确定率、公式 | `H+M+Q=D` 成立 |
| `coverage_rate` | number/null | 覆盖率标量（`hits / denominator`） | 与 `coverage.coverage_rate` 一致 |
| `matches` | array | 每条参考的 `status/match_method/matched_record_ids/match_reason` | 每条参考恰好一个状态 |
| `misses` | array | `status=miss` 的记录与类别 | 只含确认遗漏 |
| `miss_categories` | array | 类别、数量、ref_id、来源 | 未标注集中为 `unlabeled` |
| `supplemental_search` | object | 轮次、是否执行、新增命中、边际收益、残余遗漏 | 未执行不得写成已执行 |
| `report` | string | `report.md` 路径 | 文件存在且可读 |
| `limits` | array | 数据缺失、不可读、无法计算项 | 失败时不得为空 |
| `uncertainty` | array | 判定不确定与冲突 | 与 `limits` 区分 |
| `changes` | array | 与题面契约的差异及处理 | 无差异可为空 |
| `summary` | string | 一行结论（含分子/分母） | 数字与 `coverage` 一致 |

`matched_record_ids` 在 CSV 中以 `; ` 连接；在 JSON 中保持数组。

## 3. 常见契约字段别名

大小写、空格、连字符、下划线不敏感。命中任一别名即映射到对应核心字段：

| 契约字段常见写法 | 映射到 |
|-|-|
| `reference_set`、`references`、`refs`、`reference_list`、`gold_set`、`known_set` | `reference_set` |
| `coverage`、`coverage_metrics`、`metrics`、`coverage_analysis` | `coverage` |
| `coverage_rate`、`coverage_percent`、`coverage_ratio`、`覆盖率` | `coverage_rate` |
| `matches`、`hit_matrix`、`match_matrix`、`per_reference`、`comparison`、`match_table` | `matches` |
| `misses`、`missed`、`omissions`、`miss_list`、`omission_list` | `misses` |
| `miss_categories`、`omission_categories`、`miss_grouping`、`miss_reasons` | `miss_categories` |
| `supplemental_search`、`supplement`、`supplementary`、`follow_up`、`next_queries` | `supplemental_search` |
| `report`、`report_path`、`readable_report`、`report_file` | `report` |
| `evidence`、`evidence_map`、`sources`、`provenance` | `evidence` |
| `uncertainty`、`uncertainties`、`open_questions` | `uncertainty` |
| `limits`、`limitations`、`constraints` | `limits` |
| `changes`、`change_log` | `changes` |
| `summary`、`conclusion`、`findings`、`headline` | `summary` |

未列出的字段：脚本不猜测语义，写 `null` 并进入 `unresolved_fields`。由执行者阅读
`audit.json` 后决定是否用真实内容补充；仍然无证据则保留 `null` 并说明。

## 4. 案例覆盖规则

- **契约字段多于默认字段**：多出的字段逐个映射；映射不到就留空并说明，不凑数。
- **契约字段少于默认字段**：`result.json` 仍保留核心字段（便于复核），不删除证据。
- **契约要求数组但本次只有标量**：按真实内容返回标量并在 `changes` 记录差异，
  不把单条包装成多条。
- **契约要求嵌套对象**：返回脚本定义的对象结构；若字段名不同，在 `changes` 说明。
- **案例给出额外约束**（时间窗、语言、指定数据库）：写入 `inputs` 与 `limits`，
  在 `report.md` 的方法段说明；不得事后扩大范围。
- **案例给出预置 `miss_category`**：原样使用；没有给出且无证据的遗漏保持 `unlabeled`。

## 5. 状态与诚实性

- `status=ok`：参考集与命中记录都存在且可解析，指标可计算。
- `status=partial`：缺命中文件、部分文件不可读、分母为 0 或存在未解决限制；指标可为 `null`。
- `status=blocked`：参考集为空或无法识别，不能计算覆盖率。
- `uncertainty` 记录"判断不确定"（作者解析、版本冲突、近似标题）；
  `limits` 记录"数据或环境限制"（文件缺失、权限、工具不可用）。两者不得混写。
- 任何"未执行""不可计算""未核实"都必须在字段中显式出现，不能只写在散文里。

## 6. 交付路径

所有最终产物写入 `/app/output`：

```
/app/output/coverage.csv
/app/output/misses.csv
/app/output/report.md
/app/output/result.json
/app/output/audit.json
```

中间文件（索引、冻结参考集、规则、分类、补检）写入 `/app/work`，不进入交付目录。
