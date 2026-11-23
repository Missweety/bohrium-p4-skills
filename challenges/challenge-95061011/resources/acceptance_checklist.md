# 交付前自查清单 · 多文档比较与整合

## 契约

- [ ] `result.json` 含 `case_id` 与 `output_contract` 声明的全部字段
- [ ] `status` 为真实运行状态，不是占位值
- [ ] `sources` 非空，每条可定位（路径 + p.N/sec.N/sent.K 级锚点）
- [ ] `uncertainty` 列出未决项，或明确写 none
- [ ] `change_log` 至少一条，记录实际做过的动作

## 内容

- [ ] 读取工作单与全部语料文档，构建 common-field comparison matrix
- [ ] 每个取值带精确的 source_document_id 与 paragraph_id
- [ ] 先测试 task、metric、units、material、pollutant、budget 的可比性，再做定量综合
- [ ] 覆盖比较所需字段组：对象、数据、方法、条件、指标、结论、局限；每个单元格随值记录单位、数据集、指标口径与对照设置
- [ ] 判定哪些论文在同一条件下可比、哪些只能在可比子集内比较
- [ ] 保留所有 noncomparable 与 unreported 条件并明确写出
- [ ] 输出可被他人按记录复跑、抽样核对的比较结果
- [ ] 结果写入 /app/output/result.json，含 case_id 与全部 output_contract 字段

## 红线

- [ ] 未违反：单篇论文摘要不满足多文档比较要求
- [ ] 未违反：不得把不同数据集或不同染料/物质池化合并（do not pool unlike datasets or dyes）
- [ ] 未违反：不得各写各的字段口径，必须落到同一套定义使逐格对照有意义
- [ ] 未违反：不得用预制答案代替实际运行
- [ ] 未违反：实际输入文件和原论文是事实依据，不依据错误的领域标签补造数据
- [ ] 未违反：不得伪造 benchmark 分数或不可归因的冲突解释

## 可核验指标

- [ ] 单元格锚点闭合率（每个取值可回到 source_document_id + paragraph_id）
- [ ] 字段组覆盖率（对象/数据/方法/条件/指标/结论/局限）
- [ ] 可比性判定准确率与不可比项显式保留率
- [ ] 未报告项保留率（不以推断填补）
- [ ] 跨论文冲突标注率与归因可核验率
- [ ] 他人按记录复算一致率
