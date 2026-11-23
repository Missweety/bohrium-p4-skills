# 输出契约与字段映射

`/input/case.json` 的 `output_contract` 是权威字段表。本文件只定义默认兜底字段与别名映射，
**不得据本文件写死案例字段或预生成答案**；实际字段以运行时的契约为准。

## 1. 动态映射流程

1. 读取 `case.json`：`case_id` 与 `output_contract`。
2. `output_contract` 形态：
   - 字符串数组：`["appraisal","issues","report"]`；
   - 对象：取顶层键作为字段；
   - 逗号/分号/换行分隔的字符串。
3. 运行：

```bash
python scripts/quality_appraise.py --input /input --case /input/case.json --out /app/output
```

4. 脚本按别名把核心结果写到 `result.json` 顶层，每个契约字段都会出现。
5. `contract_mapping.unresolved_fields` 非空的字段表示本次没有证据支持：
   - 保持 `null`；
   - 在 `limits` 或 `uncertainty` 说明原因；
   - 不得用编造内容或示例子结果填充。

## 2. 默认字段（未给 output_contract 时）

| 字段 | 类型 | 内容 | 完成标准 |
|-|-|-|-|
| `case_id` | string | 与输入一致 | 原样保留 |
| `status` | string | `ok` / `partial` / `blocked` | `partial`/`blocked` 必须在 `limits` 说明 |
| `appraisal` | array | 每项研究：设计、适用域、逐域判断、证据、计数、overall | 每条判断可回溯 |
| `appraisal_table` | string | `appraisal.csv` | 文件存在且逐行可查 |
| `overall` | object | `study_id -> {overall, overall_source, overall_reason, worst_domains}` | 每项研究都有总体等级与来源 |
| `overall_summary` | string | 研究数与 overall 摘要 | 与逐研究结果一致 |
| `domain_counts` | object | 各域 low/some_concerns/high/unclear 计数 | 与逐域判断一致 |
| `issues` | array | 校验问题（级别、代码、行、说明） | 错误项如实列出 |
| `report` | string | `report.md` | 人读报告存在 |
| `evidence` | object | 输入、词汇、文件路径 | 可复跑 |
| `uncertainty` | array | 判断不确定（unclear、覆盖、设计缺失） | 与 `limits` 区分 |
| `limits` | array | 数据/环境限制（缺文件、不可读、空输入） | 失败时不得为空 |
| `changes` | array | 与契约的差异及处理 | 无差异可为空 |

附加工件：`appraisal.json`（完整结构）、`issues.csv`（问题清单）。

## 3. 常见契约字段别名

大小写、空格、连字符、下划线不敏感。

| 契约字段常见写法 | 映射到 |
|-|-|
| `appraisal`、`appraisals`、`studies`、`evaluation`、`quality_appraisal`、`study_appraisal` | `appraisal` |
| `appraisal_table`、`appraisal_csv`、`table`、`rows`、`domain_table` | `appraisal_table` |
| `overall`、`overall_judgement`、`overall_rating`、`总体等级` | `overall` |
| `overall_summary`、`summary`、`conclusions`、`headline` | `overall_summary` |
| `domain_counts`、`counts`、`domain_summary`、`domains` | `domain_counts` |
| `issues`、`problems`、`flags`、`quality_issues` | `issues` |
| `report`、`report_path`、`readable_report`、`report_file` | `report` |
| `evidence`、`evidence_map`、`sources`、`provenance` | `evidence` |
| `uncertainty`、`uncertainties`、`open_questions` | `uncertainty` |
| `limits`、`limitations`、`constraints` | `limits` |
| `changes`、`change_log` | `changes` |
| `status`、`run_status` | `status` |

未列出的字段：脚本不猜测语义，写 `null` 并进入 `unresolved_fields`。执行者可依据
`appraisal.json` 的真实内容补充；无证据时保留 `null` 并说明。

## 4. 案例覆盖规则

- **契约字段多于默认字段**：逐个映射；映射不到就留空说明，不凑数。
- **契约字段少于默认字段**：`result.json` 仍保留核心字段，便于复核，不删除证据。
- **契约要求数组但本次只有单条**：按真实内容返回单条或单元素数组，并在 `changes` 记录。
- **契约要求按研究嵌套**：返回脚本的 `appraisal` 结构（按 `study_id` 分组）；字段名不同时在
  `changes` 说明。
- **案例指定量表或域集合**：以案例为准，在 `vocabulary.design_domains` 与报告方法段说明；
  不得把通用最小集合冒充案例指定量表。
- **案例要求总体等级**：用 `overall`，并写 `overall_source` 与 `overall_reason`；
  不允许只给等级不给出处。

## 5. 状态与诚实性

- `status=ok`：所有必填字段有效、无校验错误、非 `unclear` 判断都有证据定位。
- `status=partial`：存在 `missing_domain`、`invalid_judgement`、缺证据、设计不明、输入限制等；
  必须写明哪些研究/域未完成。
- `status=blocked`：评价行为空或无法识别，不生成判断。
- `uncertainty` 记录判断层面的不确定（`unclear`、覆盖、设计缺失）；
  `limits` 记录数据/环境限制（文件缺失、不可读、空输入）。两者不得混写。
- "未评价""未执行""不可核实"必须体现在字段中，不能只写在正文。

## 6. 交付路径

```
/app/output/appraisal.json
/app/output/appraisal.csv
/app/output/issues.csv
/app/output/report.md
/app/output/result.json
```

中间文件（索引、域计划、覆盖文件、证据 claims）写入 `/app/work`，不进入交付目录。
