# 交付前自检清单

逐项核对，任一项不满足都不得声称"评价完成"。建议把勾选结果写进 `/app/work/checklist.md`。

## A. 输入与设计

- [ ] 已读取 `/input/case.json` 与 `task.md`，记录了真实 `case_id`。
- [ ] 已运行 `source_index.py extract`，记录文件数、可读数、不可读数与哈希。
- [ ] 每项研究的真实设计已从原文确认（`rct`/`observational`/`diagnostic`/`systematic_review`）。
- [ ] 设计与题面标签不一致时已记录冲突并以原文为准。
- [ ] 设计无法确认的研究标为 `unknown_design`，没有随意套用检查表。
- [ ] 仅摘要/无全文/语言不可读/图表不可解析的研究已记录限制。

## B. 适用域

- [ ] 按设计选择了最小必填域，并在 `/app/work/domain-plan.json` 记录依据。
- [ ] 每个必填域要么有判断，要么在 `missing_domains` 中列出并说明未完成原因。
- [ ] 没有用 `low` 填充"原文未提及"的域。
- [ ] 额外域保留时已标 `domain_not_applicable`，没有混入必填域统计。

## C. 证据定位

- [ ] 每个非 `unclear` 判断都有 `evidence_file`。
- [ ] 每个非 `unclear` 判断都有带单位的 `evidence_locator`（页码/章节/表格/图）。
- [ ] 每个非 `unclear` 判断都有逐字 `quote`，不是转述或摘要改写。
- [ ] `quote` 已用 `source_index.py verify` 或人工核对确认逐字存在。
- [ ] 没有把只有数字的定位当作合格定位。
- [ ] 没有编造页码、表格编号、引文或证据文件路径。

## D. 判断与四态

- [ ] 判断只用 `low` / `some_concerns` / `high` / `unclear`。
- [ ] "明确存在"→`high`，"可能存在"→`some_concerns`，"明确未见"→`low`，
      "未报告/证据不足"→`unclear`，映射一致。
- [ ] `unclear` 没有被当作 `low`。
- [ ] 每个 `unclear` 的 `note` 说明了缺什么证据。
- [ ] 判断与原文冲突处已在 `note` 记录，没有悄悄改判。

## E. 汇总与覆盖

- [ ] `overall` 按最差域计算：`low < some_concerns < high`。
- [ ] `unclear` 不参与排序；全为 `unclear` 时 `overall=unclear`。
- [ ] `worst_domains` 与 `overall_source` 已输出。
- [ ] 覆盖 `overall` 时理由非空，且 `overall_source=override`。
- [ ] 没有无理由覆盖，也没有覆盖后删除原最差域记录。
- [ ] 域计数与逐域判断一致。

## F. 反例与人工复核

- [ ] 已主动查找与判断相反的证据（阴性结果、方案偏离、亚组切换、补充材料）。
- [ ] 同一研究不同域矛盾处已记录并提交人工裁决。
- [ ] 人工复核记录包含复核人、抽检数、一致数、不一致项与裁决。
- [ ] 原始判断与复核判断分开保存，没有覆盖原文。

## G. 契约与文件

- [ ] 已读取 `output_contract`，`result.json` 包含其中每个字段。
- [ ] 无法产出的契约字段为 `null`，并在 `contract_mapping.unresolved_fields` 与 `limits` 说明。
- [ ] `result.json` 的 `case_id` 与输入一致。
- [ ] `status` 与实际完成度一致（`ok` / `partial` / `blocked`）。
- [ ] `uncertainty` 与 `limits` 分开写，且非空说明到位。
- [ ] `/app/output` 下存在 `appraisal.json`、`appraisal.csv`、`issues.csv`、`report.md`、
      `result.json`。
- [ ] 报告中的计数、overall 与 `appraisal.json` 一致，第二个人可按行号复算。

## H. 禁止项

- [ ] 没有把摘要改写、文件名或领域标签当作评价依据。
- [ ] 没有补造原文、页码、引文、研究设计或判断依据。
- [ ] 没有声称完成双人独立评价或全文核读（除非确有其事）。
- [ ] 没有声称评价可直接替代同行评审或临床/政策决策。
- [ ] 没有把未执行的核查写成已执行。
- [ ] 没有把合成示例的结果当成正式案例结果提交。
