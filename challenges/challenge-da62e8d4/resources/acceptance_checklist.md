# 交付验收清单（复现与方法验证）

运行前：
- [ ] `case.json` 可解析；contract 为 list / fields / required 之一。
- [ ] 材料有文本层；PDF 能被 `pdftotext` 读取。

运行后：
- [ ] `result.json` 的 `contract_check.missing` 为空。
- [ ] `status` 与判定计数一致；`limits` 写明缺失依赖。
- [ ] 每条 claim 有 `paragraph_id` + `quote`，quote 可在 `work/doc.json` 检索到。
- [ ] 每个 check 有 `inputs`、`computed_*`、`reported_*`、`tolerance`、`verdict`。
- [ ] `audit.pass=true`，且审计确实重算了存储数值（非抄写）。
- [ ] `summary` 各计数与列表长度一致：claims/checks/conflicts/状态分项。
- [ ] `conflicts` 条目均有 `abs_diff`，未修改原文报告值。
- [ ] “available on request” 的代码/数据未被当作已提供。
- [ ] `work/checks.csv`、`work/reproduction.json`、`output/reproduction_report.md` 均生成。
- [ ] 无 not_checkable 被写成“复现成功”。

禁止项：
- [ ] 包内无绝对机器路径、token、密钥、符号链接。
- [ ] 未声称任何未真实运行的复现结果或分数。
