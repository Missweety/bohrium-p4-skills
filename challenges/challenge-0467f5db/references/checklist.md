# 交付前自检清单

逐项核对，任一项不满足都不得声称"完成"。建议把勾选结果写进 `/app/work/checklist.md`。

## A. 输入与参考集

- [ ] 已读取 `/input/case.json` 与 `task.md`，记录了真实 `case_id`。
- [ ] 已运行 `source_index.py extract`，记录文件数、可读数、不可读数与哈希。
- [ ] 参考集条数、命中记录条数、去重前数量都能从文件复算。
- [ ] 参考集每条都有 `ref_id`；缺失的已按规则编号并在报告说明。
- [ ] DOI、标题、作者、年份已逐条核对，缺字段的地方是空值而不是猜测值。
- [ ] 撤稿/无法获取全文/重复记录进入 `unavailable_records`，没有被静默删除。
- [ ] 参考集版本已冻结（文件名 + sha256 + 条数 + 时间）。

## B. 匹配规则

- [ ] 规则与阈值已写入 `/app/work/matching-rule.json`：DOI 精确；
      标题+年份+作者 Jaccard ≥ 0.85。
- [ ] 规则在正式比对前确定，未因结果不理想而临时放宽。
- [ ] 若修改过规则，整批已重跑，并在 `changes` 记录原因与影响。

## C. 逐条比对

- [ ] 分母 = 参考集总数 − 不可用数，且 `hit + miss + uncertain = 分母`。
- [ ] 每条参考恰好一个状态：`hit` / `miss` / `uncertain`。
- [ ] `uncertain` 没有被算进命中分子。
- [ ] `matched_record_ids` 指向真实存在的命中记录，不是占位编号。
- [ ] DOI 冲突、年份缺失、作者缺失、近似标题都显式标记。
- [ ] `coverage.csv` 覆盖全部纳入分母的记录。

## D. 覆盖率与遗漏率

- [ ] 覆盖率公式写明：`hits / denominator`。
- [ ] 遗漏率公式写明：`misses / denominator`。
- [ ] 同时给出含全部参考集的覆盖率，便于复核分母选择的影响。
- [ ] 分母为 0 或命中文件缺失时，比率是 `null`，不是 0。
- [ ] 报告数字与 `result.json`、`coverage.csv` 一致。

## E. 漏检分类

- [ ] 每个 `miss` 都有类别；未标注的统一为 `unlabeled`。
- [ ] 每条非 `unlabeled` 类别都能指到查询式/字段/时间窗/来源/记录异常。
- [ ] 没有使用"数据库覆盖不足""关键词不好"这类无法核对的泛泛归因。
- [ ] 没有把"没找到"直接写成"不相关"。
- [ ] 分类来源已标注：`reference_set` / `classify_input` / `unlabeled`。

## F. 补检与边际收益

- [ ] 补检记录包含 `proposed_query, executed, new_hits, yield, stop_reason`。
- [ ] `executed=true` 的查询确实执行过，且有真实导出或记录可核对。
- [ ] 未执行的补检保持 `executed=false`，报告中明确写"拟定/未执行"。
- [ ] 新增命中能映射回 `ref_id` 时才计算残余遗漏；否则写"不可计算"及原因。
- [ ] 没有声称"补检后遗漏下降"，除非有对齐后的数字支持。

## G. 闭环复核

- [ ] 对 `miss` 与 `uncertain` 做了人工抽检，记录抽检数、一致数、不一致项。
- [ ] 不一致项有裁决结论，不是只列出来。
- [ ] 残余遗漏的规模与原因有说明，或明确写"不可计算"。
- [ ] 停止条件逐条满足，或写明部分完成的范围。

## H. 契约与文件

- [ ] 已读取 `output_contract`，`result.json` 包含其中每个字段。
- [ ] 无法产出的契约字段为 `null`，并在 `contract_mapping.unresolved_fields` 与 `limits` 说明。
- [ ] `result.json` 的 `case_id` 与输入一致。
- [ ] `status` 与实际完成度一致（`ok` / `partial` / `blocked`）。
- [ ] `uncertainty` 与 `limits` 分开写，且非空说明到位。
- [ ] `/app/output` 下存在 `coverage.csv`、`misses.csv`、`report.md`、`result.json`、`audit.json`。
- [ ] `report.md` 能被第二个人按文件与编号独立复算。

## I. 禁止项

- [ ] 没有用检索结果反推参考集或分母。
- [ ] 没有编造文献、DOI、作者、年份、查询式或命中数。
- [ ] 没有声称"全球召回""该库已穷尽"或未经核实的人工双评。
- [ ] 没有把未执行的补检写成已执行。
- [ ] 没有把摘要、文件名或领域标签当作全文证据。
- [ ] 没有把合成示例的结果当成正式案例结果提交。
