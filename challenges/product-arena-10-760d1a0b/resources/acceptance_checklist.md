# 交付自查清单（knowledge graph）

逐项可在本地实际复现；未核实的项不得勾选。

## 运行

- [ ] `python3 scripts/run_case.py --input <in> --work <work> --output <out>` 退出码 0。
- [ ] `out/result.json` 含 case.json `output_contract` 的全部字段，`contract_check.missing` 为空。
- [ ] `out/knowledge_graph.json`、`nodes.csv`、`edges.csv` 均生成且非空（有节点时）。

## 证据

- [ ] 每个 node 有 `source_id`、`paragraph_id`、`quote`。
- [ ] 每条 edge 有 `source`/`target`/`predicate`/`source_id`/`paragraph_id`/`quote`。
- [ ] 随机抽 3 条 quote，能在对应段落的原文中逐字找到。
- [ ] 没有任何节点来自“常识补全”，全部能在正文定位。

## 跨篇对齐

- [ ] 两篇材料的 `source_id` 不同；根 DOI/title 没有套到第二篇。
- [ ] 跨篇同名标签在 `alias_decisions` 中为 `not_merged`，理由非空。
- [ ] 没有把 `material.json` 与 `primary/secondary` 当成两篇跨篇证据。

## 查询

- [ ] ≥3 条查询 `executed=true`，每条有 `result` 与 `answer`。
- [ ] 有命中的查询附引文；零命中查询有 `no_hit=true` 与 `empty_reason`，且 `evidence` 为空。
- [ ] `answer` 中的数字与 `result` 长度/内容一致。

## 状态与边界

- [ ] `status` 与材料篇数、查询数、审计结果一致。
- [ ] 单篇输入时 `status=partial`，`limits` 写明未做双篇对照。
- [ ] 无材料时 `status=blocked`，图谱为空，没有编造节点。
- [ ] `limits` 不写未发生的失败；`notes`/`change_log` 记录真实去重与告警。

## 复核

- [ ] `python3 scripts/audit_result.py --result out/result.json --graph work/graph.json --input <in> --case <in>/case.json` 报告 `pass=true`。
- [ ] 审计失败时，运行器已把 `status` 降为 `partial` 并写明错误数。

## 合规

- [ ] 包内无绝对机器路径、token、密钥、符号链接。
- [ ] 文档中的命令均为 `python3`，在任意 cwd 可运行。
- [ ] 没有把示例或合成结果声称为正式案例得分。
