# 抽取口径 · 多文档比较与整合

## 必须做

1. 读取工作单与全部语料文档，构建 common-field comparison matrix
2. 每个取值带精确的 source_document_id 与 paragraph_id
3. 先测试 task、metric、units、material、pollutant、budget 的可比性，再做定量综合
4. 覆盖比较所需字段组：对象、数据、方法、条件、指标、结论、局限；每个单元格随值记录单位、数据集、指标口径与对照设置
5. 判定哪些论文在同一条件下可比、哪些只能在可比子集内比较
6. 保留所有 noncomparable 与 unreported 条件并明确写出
7. 输出可被他人按记录复跑、抽样核对的比较结果
8. 结果写入 /app/output/result.json，含 case_id 与全部 output_contract 字段

## 禁止

- 单篇论文摘要不满足多文档比较要求
- 不得把不同数据集或不同染料/物质池化合并（do not pool unlike datasets or dyes）
- 不得各写各的字段口径，必须落到同一套定义使逐格对照有意义
- 不得用预制答案代替实际运行
- 实际输入文件和原论文是事实依据，不依据错误的领域标签补造数据
- 不得伪造 benchmark 分数或不可归因的冲突解释

## 状态词表

- 运行级：`success` / `partial` / `failed` / `refused`
- 字段级：`reported`、`not_reported`、`source_conflict`、`extraction_failed`
- 本题相关：`unreported（原文未报告）`、`noncomparable（不可比）`、`部分完成`、`无法判断`、`拒答`、`运行失败`、`材料缺失`

## 证据锚点

- `p.N` — 第 N 页（1-based，PDF 物理页序，不是印刷页码）
- `sec.X` — 第 X 个章节单元
- `sent.K` — 该章节单元第 K 句
- `tab.M` — 第 M 张表
- `row.K` — 该表第 K 行
- `cap.M` — 第 M 条图注/表注
- `para.K` — 第 K 个段落（当输入直接提供段落编号时）

## 证据粒度

source_document_id + paragraph_id（单元格级锚点），并随值记录单位/数据集/指标口径

## 本题独有能力

在定量汇总前强制跑一遍可比性预检（task/metric/units/material/pollutant/budget），只输出“可比子集”内的综合并显式隔离不可比与未报告项。
