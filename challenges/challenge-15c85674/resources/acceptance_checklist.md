# 交付前自查清单 · 文献智能问答

## 契约

- [ ] `result.json` 含 `case_id` / `paper_id` / `material_version`
- [ ] `answers[]` 覆盖**每一个**问题，无法回答的也保留条目
- [ ] 每项 `status` 取值合法（answered/partial/insufficient_evidence/input_error）
- [ ] 每个 `claim` 含 `claim_id` / `text` / `kind` / `evidence[]`
- [ ] 每条 `evidence` 的 `paragraph_id` 真实存在、`quote` 逐字命中
- [ ] `conditions[]` 保留数值、单位、比较对象、实验条件、结论范围
- [ ] `unanswered_parts[]` 每项写明原因
- [ ] `coverage` 说明已读章节、未读章节及原因
- [ ] `sources` / `uncertainty` / `change_log` 非空且真实

## 内容

- [ ] 逐题回答，覆盖每个问题及其全部子问；必要时整合方法、结果、讨论和表格中的信息
- [ ] 为主要论断附对应论文标识、原文段落编号和短引文，使答案与证据一一核对
- [ ] 准确保留数值、单位、比较对象、实验条件和结论范围，区分论文实测结果（reported）、作者解释与自己的推断（inferred）
- [ ] 材料未报告时说明无法确定；只能部分回答时列出缺口；原文冲突时指出冲突及出处；读取失败时明确报告
- [ ] answers[] 每个问题一项，含 question_id、answer、conditions，不得省略无法回答的问题
- [ ] claims[] 每项含 claim_id、text、kind 与 evidence[]（每条证据含 paragraph_id 与 quote）
- [ ] coverage 说明已读章节、未读章节及原因
- [ ] status 明确区分 answered / partial / insufficient_evidence / input_error

## 红线

- [ ] 未违反：任务仅依据给定材料作答，不联网检索、不做 PDF 解析/图像像素识别/补充附件读取
- [ ] 未违反：不能编造答案或引用
- [ ] 未违反：不得省略无法回答的问题
- [ ] 未违反：不得预置正式案例答案、伪造执行记录、读取隐藏评分数据或写入评分目录
- [ ] 未违反：完整覆盖与合理说明材料不足均可获分，不得仅凭状态标签或未回答列表判定漏答
- [ ] 未违反：不得因缺材料而伪造有依据的回答

## 可核验指标

- [ ] 答案覆盖率（9 题均有 answer 项）
- [ ] 子问题覆盖率
- [ ] 引文定位正确率（quote 与 paragraph_id 对应原文）
- [ ] claim-evidence 闭合率（每个主要论断都有可核证据）
- [ ] 条件字段完整率（数值/单位/比较对象/实验条件/范围随值保留）
- [ ] 状态标注与实际证据一致率（不靠状态标签掩盖漏答）
