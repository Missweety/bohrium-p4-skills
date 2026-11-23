---
name: proposal-novelty-auditor
description: 把模糊的科研设想推进到可决策的选题评估：把研究问题拆成对象/变量/比较基线/预期结论/可证伪条件，按任务-方法-数据-评价-结论建立逐条可比的文献矩阵并说明不可比原因，把每条创新陈述判定为方法/数据/场景迁移/结论修正并对最近工作逐条划界，核查数据/算力/实验条件/时间/人员等前提后给出带条件与失败风险的可行性结论；所有判断回链到来源文件与逐字片段，区分材料事实、显式假设与无法确定项，不声称全局无人研究。
version: 1.1.0
license: MIT
---

# 科研选题与创新性评估：问题可检验，创新有边界，可行有前提

一次交付四件互相一致的判断：

1. **可检验的问题**：对象、关键变量、比较基线、预期结论、可证伪条件缺一不可；
   缺项写 `undefined` + `needs_input`，不替用户补一个"看起来完整"的表述。
2. **已有的工作**：按任务/方法/数据/评价/结论建矩阵，并说明哪些工作**不能直接比较**及原因。
3. **创新点的边界**：每条创新陈述逐条对最近工作判定 `covered` / `partially_covered` /
   `uncovered_within_scope` / `unknown`；**不写"首次""尚无人研究"**，只写"在本次 N 篇来源内未发现覆盖"。
4. **可行性的条件**：每条前提有来源或明确标为假设；结论只能是 `conditionally_feasible` /
   `feasible_within_scope` / `not_supported` / `unknown`，并列出失败风险。

## 何时使用

触发：给定研究设想/基金申报草稿 + 一批文献或题录，要求
"把问题说清楚 / 做相关工作比较 / 判断创新点 / 评估可行性 / 找冲突证据与研究空白"。

不触发：单纯写综述或论文；只做文献格式转换；要求补全未提供的文献、实验数据或检索全库；
要求给出"绝对新颖"结论。

## 输入

运行时读取 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与 `task.md`。
常见字段别名：

| 用途 | 字段（含别名） |
|-|-|
| 研究设想 | `proposal` / `idea` / `research_idea` / `motivation` / `abstract` / `summary` |
| 研究问题 | `research_question` / `question` / `topic` |
| 问题要素 | `object` / `variables` / `baseline` / `expected_conclusion` / `falsifier`（也接受同名中文键） |
| 创新陈述 | `novelty_claims` / `innovations` / `contributions`（字符串、字符串数组或 `{claim,type}`） |
| 纳排标准 | `criteria` / `inclusion` / `exclusion` / `year_from` / `year_to` / `languages` / `types` |
| 前提与资源 | `prerequisites` / `constraints` / `resources` / `assumptions` |
| 输出契约 | `case.json.output_contract` |

材料支持 `.json/.jsonl/.csv/.tsv` 题录、`.pdf`、`.docx`、`.html`、`.md/.txt`。
题录字段别名：`title/标题`、`authors/作者`、`year/年份`、`venue/journal/期刊`、`abstract/摘要`、
`doi`、`url`、`keywords/关键词`、`type/类型`、`language/语种`。PDF 若无文本层则只登记元数据，
不把文件名当摘要。

## 执行流程

### 0. 一键端到端

```bash
python scripts/run_case.py --case /input/case.json --materials /input \
  --work /app/work --out /app/output
```

依次：契约 → 来源清单（哈希/定位）→ 去重 → 问题拆解 → 纳排与理由码 → 证据矩阵
→ 创新逐条判定 → 可行性前提核查 → 冲突与空白 → 契约回填与自检。

### 1. 来源清单与去重

每个来源登记 `source_id`、文件、页码/行号、sha256、标题、作者、年份、期刊、DOI、摘要。
DOI 优先、其次归一标题去重；合并保留 `provenance`。标题归一不做路径截断，
含 `/` 的标题不会被截短后与其它记录误合并。不可读/无文本层写入 `uncertainty`，
不计入"已筛查"来凑数。

### 2. 问题拆解（可检验性）

优先读取案例显式字段；缺失时从设想文本按线索句提取，并标 `source=extracted`。
- 对象：研究谁/什么（`object`）
- 关键变量：自变量/因变量/控制变量
- 比较基线：与什么比（现有方法/空对照/人类基线）
- 预期结论：可观测的结果方向
- 可证伪条件：什么结果会推翻它

任一缺失 → `undefined` + `needs_input=true`，并给出**模板**（明确标注是模板，不是用户的结论）。
`falsifiable = 基线存在 and 预期结论可观测 and 可证伪条件存在`。

### 3. 纳排与理由码

硬条件优先：年份窗、文献类型、语种、排除词。相关性用问题概念词覆盖：
≥2 个概念词 → `include`；1 个 → `maybe`（`REV_WEAK_TOPIC_MATCH`，`needs_human=true`）；
0 个 → `maybe`（`REV_NO_TOPIC_MATCH`），**不直接判排除**，避免误排。
每条决定带 `reason_code`、理由、逐字证据（标题/摘要原句）与文件+页/行定位。

### 4. 证据矩阵

对纳入/待定来源抽取：任务、方法、数据、评价方式、结论、可比较性。
抽取为**摘录式**：命中线索句才填，否则 `not_reported` 并标 `unknown`，不生成文献没有的结论。
`comparability`：任务/数据/评价至少两项可对齐 → `comparable`；否则
`not_directly_comparable` 并写明差异（任务不同/数据不同/无评价细节）。

### 5. 创新逐条判定

创新类型：`method` / `data` / `scenario_transfer` / `conclusion_revision` / `unclassified`。
每条陈述找最近工作（按概念词重合），给出：
- `verdict`：`covered` / `partially_covered` / `uncovered_within_scope` / `unknown`
- `nearest`：来源 ID、逐字片段、共享词
- `scope`：**仅限本次纳入的 N 篇来源**
- 覆盖不足或来源过少 → `unknown` + `needs_human=true`，不升级为"首次"。

### 6. 可行性

从案例前提或设想文本提取：数据、算力、实验条件、时间窗口、人员能力、伦理/合规。
每条：`status` ∈ `supported`（有来源片段）/ `assumed`（案例显式假设）/ `unsupported` /
`unknown`；给出来源定位、影响与缓解。声明 `supported` 但检索不到可引用片段的，
一律降级 `unknown` 并写明原因，不输出空证据的"支持"。结论：
全部支持 → `feasible_within_scope`；存在未知/不支持 → `conditionally_feasible`（列条件）；
无任何前提 → `unknown`。同时输出失败风险清单。

### 7. 冲突、空白与边界

- 结论相冲突的来源（同任务、相反方向词）登记 `conclusion_conflict`，按范围差异仲裁，
  无法裁决 → `unresolved` + `uncertainty`；
- 研究空白只从"未覆盖创新 + 缺失证据维度"推出，逐条 `bounded=true`，不声明全局空白；
- 明确不覆盖：未提供的文献、未做的实验、未检索的数据库。

### 8. 交付与自检

产出 `result.json` + `evidence_matrix.csv` + `novelty.csv` + `feasibility.csv` +
`conflicts.csv` + `report.md`。自检：每条来源有决定；每条决定有理由码；
每条判断有定位；创新判定都带 scope；可行性前提都有状态且 `supported` 必带来源片段；
不出现全局新颖性断言。

## 输出

字段与机检口径见 `references/output-contract.md`。核心字段：
`problem_statement`、`screening`、`evidence_matrix`、`novelty`、`feasibility`、
`conflicts`、`gaps`、`uncertainty`、`limits`、`validation`，以及契约全部字段。

## 异常处理

| 情况 | 处置 |
|-|-|
| 无来源/题录为空 | `status=blocked`，不产出评估结论 |
| 摘要缺失 | 矩阵字段 `not_reported`，可比较性置 `unknown`，不据标题推断 |
| 年份/语种缺失 | 不默认在窗内；`maybe` + 元数据缺失理由 |
| 创新陈述缺失 | `novelty=[]` + `limits` 说明"未提供可判定的创新陈述" |
| 来源不足 3 篇 | 新颖性一律 `unknown`，不给"未覆盖"结论 |
| 证据冲突 | 登记并仲裁；不能裁决则保留双方并升级人工 |
| 前提无来源 | `unknown` + 风险与补充核查建议，不写成"可行" |
| 文件不可读/无文本层 | 只登记元数据，不参与证据矩阵 |

## 最小调用示例（合成示例，非正式案例）

`case.json`：研究问题"跨域少样本分类能否用合成数据替代人工标注"，
给出对象/变量/基线/预期结论/可证伪条件，`novelty_claims` 2 条，`year_from=2022`；
材料含 `records.json`（4 条，其中 2 条结论相反）、`notes.md`（1 条方法说明）。

```bash
python scripts/run_case.py --case case.json --materials . --work work --out out
```

示意输出（示例）：来源 5 → 去重 4；纳入 3 / 待定 1；矩阵 3 行（1 行不可直接比较）；
创新 2 条（1 条 `partially_covered`，1 条 `unknown`）；可行性 3 条前提
（1 supported / 1 assumed / 1 unknown）→ `conditionally_feasible`；冲突 1 条已登记。
以上数字为示例，不代表正式案例结果。

## 限制

- 证据抽取为线索句摘录，不做全文语义推理；`not_reported` 不等于文献没有做。
- 相关性用概念词覆盖，同义改写未收录时可能降为 `maybe`，需人工确认。
- 新颖性只在给定来源范围内判断，**不构成全局新颖性结论**。
- 可行性判断依赖案例提供的前提；未提供的前提一律 `unknown`，不代填。
- 不联网、不补造文献、不虚报完成状态。

## 改动记录

- **1.1.0**（2026-11-23）修复 6 处真实缺陷：① 标题归一不再 `basename`，含 `/` 的标题
  不再被截断后与其它记录误合并（合成用例：两条不同记录曾被并成 1 条）；② 字符串型
  `novelty_claims` 不再被整段丢弃，按分号/换行/句切分逐条判定；③ 案例声明 `supported`
  但无来源片段的前提降级 `unknown` 并写明原因，新增机检项
  `supported_premises_cite_source`；④ 仅给出 `year_to` 时，年份缺失也走
  `REV_YEAR_MISSING`，不再落入可纳入判定；⑤ 字符串型 `prerequisites` 不再整段丢弃；
  ⑥ 中文句号后无空格也能切句，且 docx/md 兜底标题改用 `file_stem`（独立复审发现的回归）。
  另将"策略/机制/协议/pipeline/protocol"纳入方法类创新线索。
- **1.0.0**（2026-11-21）首版：五要素问题拆解与可证伪判定；题录/PDF/文档多源清单与 DOI/标题去重；
  六类理由码纳排；五字段摘录式证据矩阵与不可比原因；四类创新逐条判定（带 scope，禁全局断言）；
  六类可行性前提与四种条件结论；结论冲突登记与有界空白；契约回填与 8 项机检。
