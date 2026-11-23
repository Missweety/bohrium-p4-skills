---
name: structured-quality-appraisal
description: 把文献研究质量评价落成“研究设计→适用域→判断→原文证据→总体等级”的可复核表格：校验必需字段与判断词汇，按 RCT/观察性/诊断/系统综述的最小域集合查缺，要求页码/章节/表格定位与原文片段，区分明确存在/可能存在/未见迹象/证据不足，按最差域汇总并允许带理由覆盖。适用于偏倚风险与报告质量评价、系统综述质量核查；不把摘要改写当评价，不补造原文或页码。
version: 1.0.0
license: MIT
---

# 文献研究质量评价：每条判断都能回到原文

交付物不是"设计合理、样本适中、结论可靠"的整体评语，而是一张**逐域可复核的评价表**：

研究设计 → 适用域 → 每域判断 → 原文定位与片段 → 等级汇总 → 反例与人工复核。

核心主张：**没有原文定位的判断不成立；原文没报告的内容只能记"证据不足"，不能补一个看起来合理的等级。**

## 何时使用

触发：用户给出一篇或一批文献（全文/章节/表格/摘要），要求"评价研究质量"、"做偏倚风险评价"、
"按 RoB 2 / ROBINS-I / QUADAS-2 / AMSTAR 检查"、"判断这篇文献的结论是否站得住"、
"把评价结果整理成可复核表格"；或题面带 `output_contract`、`design`、`domain`、`judgement`、
`evidence_file`、`evidence_locator`、`quote` 等字段。

不触发：只要求写摘要或翻译；要求替代同行评审、事实核验或临床决策；
要求在没有原文的情况下补出页码、引文或"完整评价"；只做文献检索与覆盖率审计（走另一类 Skill）。

## 输入

执行时先读 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`，
再读取实际文献与评价材料；工作目录 `/app/work`，最终产物写 `/app/output`。

| 语义 | 常见字段/文件 |
|-|-|
| 案例标识 | `case_id` |
| 评价行 | `appraisals`、`rows`、`judgements`、`ratings`，或 `*apprais*.csv/json` |
| 文献原文 | `papers`、`materials`、`sources`，或题面给定的 PDF/文本 |
| 总体覆盖（可选） | `overrides`、`*override*.csv/json` |
| 输出契约 | `output_contract`（字段逐个回填） |

评价行最小字段：

```
study_id, design, domain, judgement, evidence_file, evidence_locator, quote, note
```

- `judgement ∈ {low, some_concerns, high, unclear}`；
- `design ∈ {rct, observational, diagnostic, systematic_review}`（支持常见别名与中文）；
- `evidence_locator` 应写到页码/章节/表格/图，例如 `page:3`、`section:methods`、`table:2`；
- `quote` 必须是原文片段，不是转述。

字段名大小写、空格、连字符不敏感；中英文列名均可识别。缺失字段按空值校验并报告，
**不得用推测值补齐**。

若评价行直接以数组嵌在 `case.json`（如 `appraisals`/`rows`），脚本会优先读取；
否则在 `/input` 目录内发现评价表，识别不了时用 `--rows` 显式指定。

题面没有现成评价表时，`/input` 往往只有 PDF/文本与 `case.json`。此时**不得直接报错退出**：
先阅读原文，把评价行写入 `/app/work/appraisals.csv`，再按输出契约第 2 步用 `--rows` 运行。
确实无法产出评价行时，输出 `status=blocked` 的 `result.json`（含已检查文件与原因）并退出 1。

## 输出契约（动态）

`/input/case.json` 的 `output_contract` 是权威字段表，不得写死案例字段或预生成答案。

1. 读取并记录 `output_contract` 的每个字段及要求的类型/含义。
2. 评价行必须来自对原文的阅读：题面已给评价表时直接使用；未给时先在 `/app/work/appraisals.csv`
   写入八字段评价行（每研究每域一行；非 `unclear` 必须带 `evidence_file + evidence_locator + quote`），
   再运行
   `python scripts/quality_appraise.py --input /input --rows /app/work/appraisals.csv --case /input/case.json --out /app/output`，
   脚本按别名映射核心结果。
3. 检查 `/app/output/result.json`：每个契约字段是否存在；
   `contract_mapping.unresolved_fields` 中的字段本次没有证据支持，保持 `null` 并说明，
   **不得编造内容填满**。
4. 字段名差异大时按 `references/output-contract.md` 的别名表补充映射；
   仍无法对应时写入 `changes`，不改变事实。

默认交付：`appraisal.json`、`appraisal.csv`、`report.md`、`result.json`，以及 `issues.csv`。

## 六步工作流（严格按序）

### 第 1 步：识别真实研究设计

- 打开原文的摘要、方法、结果与图表标题，确认研究设计：`rct`、`observational`、
  `diagnostic`、`systematic_review`。
- 不凭题面标签或文件名判断；标签与实际不符时以原文为准，并记录冲突。
- 设计无法确认时写 `unknown_design`，不任意挑一个设计去套检查表；该研究记 `partial`。

```bash
python scripts/source_index.py extract --input /input --out /app/work/source-index.json
```

先建立文件索引（路径、sha256、可读性、页码/行号），后续每个判断都引用其中的定位。

### 第 2 步：选择适用域

按设计选择最小必填域：

| 设计 | 最小必填域 |
|-|-|
| `rct` | `randomization_process`、`deviations_from_intended_interventions`、`missing_outcome_data`、`measurement_of_outcome`、`selection_of_reported_result` |
| `observational` | `confounding`、`selection_of_participants`、`classification_of_interventions`、`missing_data`、`measurement_of_outcomes`、`selection_of_reported_result` |
| `diagnostic` | `patient_selection`、`index_test`、`reference_standard`、`flow_and_timing` |
| `systematic_review` | `search_strategy`、`study_selection`、`data_collection`、`risk_of_bias_assessment`、`synthesis`、`reporting_completeness` |

- 只评价与本设计相关的域；额外域可以保留，但标 `domain_not_applicable` 提示。
- 缺少必填域时不得用"未提及"直接判 `low`；输出 `missing_domain` 错误，要求补评或明确说明未完成。
- 记录设计到域的映射与依据，写入 `/app/work/domain-plan.json`。

### 第 3 步：逐条定位到页码/章节/表格并保留原文

- 每个判断必须有：`evidence_file` + `evidence_locator` + `quote`。
- 定位优先级：具体页码/表格/图 > 章节 > 段落；只有 `3` 这类裸数字会触发
  `locator_without_unit` 警告，应改为 `page:3` 或 `table:2`。
- `quote` 逐字保留原文，不改写、不拼接、不用摘要替代；短于 12 字符会触发 `short_quote` 警告。
- PDF 无文本、图表不可解析、语言不支持时，记录限制并把该域判 `unclear`，
  **不得根据标题或摘要猜原文**。

```bash
python scripts/source_index.py verify --index /app/work/source-index.json \
  --claims /app/work/evidence-claims.json --out /app/work/quote-check.json
```

可选：把 `evidence_file/locator/quote` 组成 claims 数组校验是否逐字存在；
校验失败必须回到原文修正，不能保留"看起来像"的引文。

### 第 4 步：区分“明确存在 / 可能存在 / 未见迹象 / 证据不足”

| 证据状态 | 判定 | 说明 |
|-|-|-|
| 明确存在且影响结论 | `high` | 原文有直接证据，例如未设盲、结局选择性报告、混杂未调整 |
| 可能存在，证据不完整 | `some_concerns` | 提示风险但原文未充分报告，需在 `note` 说明缺什么 |
| 明确未见该问题 | `low` | 原文明确描述且可核对，例如"由计算机生成随机序列" |
| 原文未报告或无法获取 | `unclear` | 记"证据不足"，不得降级为 `low`，也不得升级为 `high` |

- `unclear` 必须有 `note` 说明缺什么证据（缺报告、缺全文、图表不可读等）。
- 判断与原文冲突时以原文为准，并在 `note` 记录冲突点。
- 摘要不足以支撑方法学判断时，只能 `unclear`；摘要改写不算评价。

### 第 5 步：等级汇总与阈值

- 每个研究按域汇总计数：`low / some_concerns / high / unclear`。
- `overall` 取**最差域**：`low < some_concerns < high`；`unclear` 不参与排序。
- 所有域都是 `unclear` 时，`overall=unclear`；没有有效判断时 `overall=unknown`。
- 允许带理由覆盖：提供 `study_id, overall, reason`，理由为空则覆盖被拒绝并报
  `override_without_reason`。
- 报告中写出 `worst_domains`、`overall_source`（`worst_domain` / `override` / `all_unclear` /
  `no_valid_judgement`）与覆盖理由，不能只给一个孤立等级。

```bash
# 先根据原文写出逐条评价表，再运行汇总；缺少评价表时脚本输出 blocked，不会伪造等级
python scripts/quality_appraise.py --input /input --rows /app/work/appraisals.csv \
  --case /input/case.json --out /app/output
python scripts/quality_appraise.py --input /input --rows /app/work/appraisals.csv \
  --overrides /app/work/overrides.csv --case /input/case.json --out /app/output
```

### 第 6 步：反例与不一致证据，人工复核与分歧记录

- 主动查找与当前判断相反的证据：未报告的阴性结果、方案偏离、亚组切换、补充材料中的不同口径。
- 同一研究不同域判断互相矛盾时（例如"随机化 low"但"基线严重不平衡"），
  在 `note` 记录并提交人工裁决，不自动改判。
- 人工复核：逐条核对 `appraisal.csv` 的定位与原文；记录复核人、抽检数、一致数、不一致项与裁决。
- 分歧处理：保留原始判断与复核判断两套记录，不覆盖原文；可沉淀为判据修订建议。

## 脚本

| 命令 | 作用 |
|-|-|
| `python scripts/source_index.py extract --input /input --out /app/work/source-index.json` | 文件索引与定位（哈希、页码/行号、可读性） |
| `python scripts/source_index.py verify ...` | 校验引文是否逐字存在于指定位置 |
| `python scripts/quality_appraise.py --input /input --out /app/output` | 自动发现评价表，校验、汇总并生成交付物 |
| `... --rows FILE` | 显式指定评价表（如 Agent 产出的 `/app/work/appraisals.csv`） |
| `... --overrides FILE` | 指定总体等级覆盖（必须带理由） |
| `... --case /input/case.json` | 读取 `case_id` 与 `output_contract` 并映射 `result.json` |

脚本只用 Python 3 标准库、无网络、不修改输入；相同输入重复运行结果一致（不含时间戳）。
退出码：`0` 校验通过；`1` 输入无效；`2` 完成但存在校验问题（`status=partial`）。

## 异常与边界处理

| 情况 | 处置 |
|-|-|
| 评价表为空或无法识别 | `status=blocked`，不生成判断；列出已检查文件 |
| `/input` 只有 PDF/case.json，无评价表 | 先阅读原文产出 `/app/work/appraisals.csv` 再运行；无法产出时写 `status=blocked` 的 `result.json` 并退出 1 |
| 仅有摘要、无全文 | 相关域判 `unclear`，`note` 写明"仅摘要"；不得补造方法与页码 |
| 全文不可得/权限不足 | 记录 `limits`，不评价不可见内容 |
| 图表不可解析/扫描件无文本 | 该域 `unclear`；需要视觉核对时明确说明 |
| 语言不支持 | 记录限制；不要用机器猜测替代原文 |
| 设计不明确或与标签不符 | `unknown_design`，不做适用域完整性判断，`status=partial` |
| 必填域缺失 | `missing_domain` 错误；不得用 `low` 填充 |
| 判断词汇非法 | `invalid_judgement` 错误；该行不进入汇总 |
| 非 `unclear` 缺证据定位/引文 | `missing_evidence_*` 错误；必须补齐或改为 `unclear` |
| 定位只有数字 | `locator_without_unit` 警告；改为 `page:`/`table:` 等 |
| 引文过短 | `short_quote` 警告；确认是逐字片段 |
| 证据文件找不到 | `evidence_file_not_found` 警告；核对路径或题面材料 |
| 同一研究同一域重复 | 保留首行，`duplicate_domain` 错误；其余不进入汇总 |
| 同一研究设计冲突 | `design_conflict` 错误；提交人工裁决 |
| 覆盖无理由 | `override_without_reason` 错误；覆盖被拒绝 |
| 契约字段未知 | 保持 `null`，写入 `contract_mapping.unresolved_fields` 与 `limits` |

## 停止条件

满足以下全部条件即可停止并交付：

1. 每项研究的设计已确认，或明确标为 `unknown_design`；
2. 每项研究的适用域要么有判断，要么列入 `missing_domains` 并说明未完成原因；
3. 每个非 `unclear` 判断都有 `evidence_file + locator + quote`；
4. 每个 `unclear` 都有说明证据不足原因的 `note`；
5. `overall` 已按最差域计算，或覆盖带非空理由；
6. `appraisal.json`、`appraisal.csv`、`issues.csv`、`report.md`、`result.json` 已写入 `/app/output`。

时间或预算耗尽仍未完成时，保存 `status=partial` 与已完成部分，写明未覆盖的域和文献，
不得用推测补全。

## 禁止编造

- 不得把摘要改写、文件名或领域标签当作评价依据；
- 不得补造原文、页码、表格编号、引文或研究设计；
- 不得把 `unclear` 当作 `low`，也不得为了"看起来完整"给缺失域补一个等级；
- 不得声称完成了双人独立评价或全文核读（除非确有其事）；
- 不得声称评价结果可直接替代同行评审、临床或政策决策；
- 不得把未执行的核查写成已执行。

## 最小调用示例

见 [examples/example.md](examples/example.md)（**合成示例，非官方案例**）。判定规则、四态映射、
阈值与字段 schema 见 [references/method.md](references/method.md)，契约映射见
[references/output-contract.md](references/output-contract.md)，交付前逐项核对
[references/checklist.md](references/checklist.md)。

## 限制

- 只检查结构化评价行的完整性、一致性与证据定位，不判断科学结论是否正确。
- 不能验证 `quote` 与原文语义是否支持该判断；`source_index.py verify` 只校验逐字存在。
- 设计识别与域映射依赖原文可见文本；扫描件、补充材料缺失会影响判断。
- 最小域集合是通用检查点，不覆盖所有学科或所有量表条目；可按案例扩展但需说明来源。
- 不替代正式系统综述的质量评价流程、双人复核或统计合并。

## 版本记录

- **1.0.0**（2026-11-23）首版：四类设计的最小域集合、判断词汇与四态映射、
  证据定位校验、最差域汇总与带理由覆盖、问题清单与动态契约映射。
