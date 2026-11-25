---
name: paper-field-extraction
description: 从给定论文材料中按目标字段表逐字段抽取结论与数值（含单位、统计量、实验条件、对照组与段落锚点），缺项按 not_reported 处理。输入为 case.json + target-fields.json + materials，产物为 result.json。适用于文献结论/数据抽取、证据表生成、字段核验类任务。
---

# 文献结论与数据抽取（paper-field-extraction）

本 Skill 只做一件事：**把目标字段表里的每一项，落到论文原文的可核对位置**。
每个 reported 字段都必须同时具备 `value`、`paragraph_id`、`quote`，且 `value` 是
`quote` 的逐字子串；找不到就写 `not_reported`，绝不填 0、绝不推测。

## 何时使用

- 任务要求“按字段抽取论文中的数值/结论/实验条件/对照”。
- 输入提供 `target-fields.json`（或 case.json 内的 fields）与一段或多段材料。
- 需要可复核的证据表，而不是一段自由总结。

不适用：需要重新做实验、需要跨文献统计合并（应另建综述流程）、材料是纯扫描件且无 OCR。

## 一键运行

包内脚本不依赖工作目录，任意 cwd 均可运行；默认路径与平台一致：

```bash
python3 scripts/run_case.py
# 等价的显式写法（本地调试）
python3 scripts/run_case.py --input /input --work /app/work --output /app/output
```

可选参数：`--case <case.json>` 指定案例文件，`--input/--work/--output` 覆盖默认目录。
退出码恒为 0（除非参数非法）：**即使材料缺失或 case.json 损坏，也会写出降级 result.json**，
避免整次尝试因异常丢分；降级原因写入 `limits` 与 `uncertainty`。

产物：

| 路径 | 内容 |
| --- | --- |
| `/app/output/result.json` | 契约全字段结果（必填字段见 references/output-contract.md） |
| `/app/work/doc.json` | 材料索引：paragraph_id、正文、表格行、可读性 |
| `/app/work/field_results.json` | 逐字段行（抽取器原始产物） |
| `/app/work/audit.json` | 独立复核报告（逐字性、锚点、状态合法性） |

## 输入约定

- `/input/case.json`：`case_id`、`output_contract`（支持 list / `{"fields":[...]}` / `{"required":[...]}`）。
- `/input/target-fields.json`：目标字段数组；每项至少含 `field_id` 与 `description`，
  可选 `aliases`、`unit`、`type`。也兼容 case.json 里的 `target_fields`。
- 材料目录：PDF / Markdown / TXT / TeX / CSV / DOCX / JATS XML；放在 `/input` 任意子目录。

段落锚点规则（写进每条证据）：

- JATS XML：沿用真实 `<p id="...">`；
- PDF：`p.<页码>¶<段号>`（仅前 40 页，超出会写入 limits）；
- Markdown/TXT：`¶<段号>`；表格：`<文件>/tab.<M>/row.<K>`。

## 字段状态（互斥）

| status | 含义 | 必须满足 |
| --- | --- | --- |
| `reported` | 原文明确报告 | value 是 quote 的逐字子串；quote 能在材料中检索到；paragraph_id 可解析 |
| `not_reported` | 原文未报告 | value 为 null；note 说明原因 |
| `source_conflict` | 同字段出现互斥取值 | 保留 candidates，不擅自选一个当结论 |
| `extraction_failed` | 材料不可读/未索引 | value 为 null，需人工接管 |

数值字段的 `unit` 只在原文写出单位时填写；不按学科惯例补单位。
`statistic`（如 `95% CI`、`±`、`p < 0.05`）与 `experimental_condition`、`comparator`
均取原文片段，并接受复核“是其 quote 的子串”。

## 交付要求

1. `result.json` 必须含 output_contract 的每个字段（`contract_check.missing` 应为空）。
2. 每条 reported 证据带 `source_path` / `locator`（=paragraph_id）/ `quote`。
3. `limits` 写清缺项、不可读材料、页数截断、未提供字段表等边界。
4. `change_log` 记录真实步骤（索引数量、抽取数量、复核结果）。
5. 不写入任何绝对机器路径、token、密钥；不联网。

## 异常处理

| 情况 | 行为 |
| --- | --- |
| case.json 缺失/非法 JSON | 回退默认契约，`status=partial`，`limits` 说明解析失败 |
| 没有 target-fields.json | 不猜测字段集合；`fields=[]`、`status=partial` |
| 材料为空/全不可读 | `status=blocked`，为每个请求字段写 `extraction_failed` 行 |
| PDF 无文本层/未装 pdftotext | 标 unreadable 并说明；不伪造正文 |
| 字段无匹配句 | `not_reported`，note 写明检索词 |
| 审计不通过 | 降级为 `partial`，`limits` 写明问题数 |

## 自检

```bash
python3 scripts/audit_result.py --result /app/output/result.json \
  --case /input/case.json --doc /app/work/doc.json --fields /app/work/field_results.json
```

审计以独立进程重跑，检查：契约字段齐全、每字段一行、状态合法、value/quote 逐字、
锚点可解析、not_reported 不带值。详见 references/output-contract.md 与
references/extraction-protocol.md。
