---
name: evidence-trace-verifier
description: 按官方 claims-to-verify.json 逐条核验论断：拆复合论断→在全文材料中定位原句（文件+页码/章节+逐字引文）→按 supported / partially_supported / contradicted / insufficient_evidence 四态判定→保留比较方向、否定、显著性与适用条件→汇总冲突与证据空白。适用于文献论断核查、审稿质疑、数据结论溯源；不适用于无材料的主观评价或代写。
version: 2.0.0
license: MIT
---

# 文献证据溯源：按 claims-to-verify 逐条给出可复核判定

核验的目标不是"看起来对"，而是**第三个人能按你给的文件与位置，复现同一条判定**。
判定必须严格区分"证据支持""部分支持""证据反驳""材料不足"四种情况。

## 何时使用

触发：给定一份论断清单（`claims-to-verify.json`）与一组文献/数据材料，要求逐条判断
材料是否支持这些论断，并给出证据位置与结论。

不触发：没有可核验材料时要求"凭常识判断"；纯语言润色；要求代写新内容。

## 输入（以题面实际文件为准）

- `/input/claims-to-verify.json`（回退：`./claims-to-verify.json`、`/app/input/claims-to-verify.json`）：
  至少含 `claims`/`claims_to_verify`/`items`/`questions` 之一，元素可为字符串或
  `{id, text|claim|statement|question, type, conditions}`。
- `/input/case.json`：读取 `output_contract`、`case_id`；字段别名由 `kernel.py init` 容错。
- 同目录材料（PDF/HTML/Markdown/CSV/DOCX/XLSX）。**先确认材料可读**；不可读必须如实标记，
  不得凭标题猜内容。`claims-to-verify.json` 本身不是证据，索引时必须排除。

## 执行流程

1. **契约**：`python scripts/kernel.py init --case /input/case.json --out work`
   → `work/contract.json`（字段名与别名原样保留，`case_id` 回填）。
   若 case.json 未给 `output_contract`，自动使用 `references/output-contract.md` 的默认契约
   （`contract_source=skill_default`）；若 case.json 缺失，`status=blocked`，不得自行编造契约。
2. **规范化论断**：`python scripts/kernel.py claims --claims /input/claims-to-verify.json --out work`
   → `work/claims.json`。脚本会标出复合句（`auto_decomposed`）、数字、比较词、否定词、
   情态/外推词。**复合论断必须在核验时逐成分判断**：任一成分不被支持，就不能给 supported。
3. **索引材料**：`python scripts/kernel.py index --materials /input --exclude claims-to-verify.json case.json --out work`
   → `work/evidence.json` + `work/corpus.txt`（每个文件以 `===== FILE: <path> =====` 分块）。
   不可读文件进 `unreadable`，最终报告说明其影响。
4. **逐条定位**：为每条论断找证据，记录 `source`（文件）、`locator`（页码/章节/行号/表格单元格）、
   `quote`（逐字原文，≥12 字）与 `relation`（supports / contradicts / context）。
   引文必须逐字；跨行断字可在报告中说明，但脚本只会给"归一化匹配"警告，不能当逐字证据。
5. **四态判定**（写入 `work/matrix.json`，规则见 `references/verdict-rules.md`）：
   - `supported`：证据直接、逐字支持**整条**论断（含比较方向、否定与条件）；至少有 1 条
     `relation=supports`，强度 strong/moderate。
   - `partially_supported`：证据只支持一部分（范围/幅度/亚组/方向/条件），或不同来源部分冲突；
     必须写 `note` 说明**哪一部分超出证据**，强度 weak/moderate。
   - `contradicted`：有证据**直接否定**该论断；必须至少 1 条 `relation=contradicts`，
     并在 `note` 写出该引文如何与论断相反。**材料未提及 ≠ 反驳**。
   - `insufficient_evidence`：材料范围内无法判断；`evidence` 必须为空，`note` 写检索词、
     检索范围与为何不足。**不得把"没找到"写成"错误"**。
6. **机检**：`python scripts/claim_evidence_matrix.py --matrix work/matrix.json --corpus work/corpus.txt --out work/matrix_report.json --md /app/output/claim_evidence.md --base /input --claims work/claims.json`
   必须 `verdict=pass` 或 `review`。硬失败（引文不在语料/不在所引文件、四态与证据结构不符、
   复合/外推被误判、遗漏或多余论断）必须回到第 4–5 步修正。
7. **数字核对**：`python scripts/kernel.py verify --text /app/output/claim_evidence.md --evidence-dir work --out work`
   → `work/claims_numbers.json`（不会覆盖 `work/claims.json`）。报告中出现的数字都要能在材料中找到；
   找不到的改为定性表述或标注待核。
8. **写出结论**：核验报告须含：总体判断（可支撑/需修改/不可用）、四态计数、逐条证据表、
   冲突清单、证据空白清单、材料可读性限制。
9. **产出**：`python scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output`
   → `result.json`；`python scripts/kernel.py check --out /app/output --contract work/contract.json` 必须 PASS。
   门禁：契约字段非空；`source_map` 每条含 claim/value/source_path/locator；`status=ok` 时
   `claim_evidence` 工件真实落盘；`partial/blocked` 必写 `limits`。

## 判定规则表

| 情形 | 判定 | 反例 |
|-|-|-|
| 原文逐字支持整条论断（含方向/否定/条件） | supported + strong/moderate | 用相邻句"补全"引文 |
| 只支持方向、部分亚组、部分幅度或某一条件 | partially_supported + weak/moderate，note 写缺口 | 把部分支持写成 supported |
| 有原句直接否定论断 | contradicted + 证据 relation=contradicts | 仅凭"材料没提"判 contradicted |
| 材料范围内检索不到，或无法判断 | insufficient_evidence + 空证据 + 检索范围 | 把"没有证据"写成"论断错误" |
| 两条材料互相矛盾 | 并列双方位置；按证据强度判 partially_supported 或 contradicted，note 写裁决点 | 只引对结论有利的一条 |
| 论断含"可能/或许/推测/有望"等情态 | 不能用 contradicted 否定；最多 partially_supported 或 insufficient_evidence | 用未做过的实验"反驳"外推 |
| 引文只在整份语料、不在所引文件 | 硬失败 | 张冠李戴引用 |
| 页码/章节缺失，或数字无出处 | 硬失败 / 改定性或标注待核 | 编造百分比 |

## 硬性禁止

- 不伪造引文、页码、文件名；不把"主题相关"当作"支持该论断"。
- 不把 `insufficient_evidence` 说成"该结论错误"；证据空白只说明材料范围内未见。
- 不把 `partially_supported` 写成 `supported`；不隐去相反证据。
- 不因结论好看而提高 strength；不提交空表或只有结论没有位置信息的表。
- 不把"未做过的实验/未覆盖的人群"当成 `contradicted`。

## 输出

`/app/output/result.json`（契约字段全回填，含逐条 `verdicts`）+ `claim_evidence.md`
（逐条证据表、冲突与空白清单、四态计数）+ `matrix_report.json`（机检结果）。
字段定义见 `references/output-contract.md`。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 材料全部不可读 | `status: blocked`，列不可读文件与原因，不猜内容 |
| 部分材料不可读 | 照常核验可读部分，`status: partial`，`limits` 写覆盖缺口 |
| 论断无法拆成原子句 | 按成分逐条判定并在 note 说明粒度限制 |
| claims 文件缺失或为空 | `status: blocked`，不得自行编造论断清单 |
| 同一论断多来源冲突 | 双方位置都保留；给限定判定，列出待人工裁决的问题 |

## 改动记录

### v2.0.0（2026-11-21）

- 对齐官方 v2 输入：核验 `/input/claims-to-verify.json` 中的待验证问题，不再假定输入是
  "文稿中的事实性论断"；新增 `kernel.py claims` 规范化与复合句/比较/否定/情态标注。
- 判定枚举改为官方四态：`supported` / `partially_supported` / `contradicted` /
  `insufficient_evidence`；旧 `partial`、`not_covered`、`conflict` 会被机检直接判失败。
- 新增结构约束：`contradicted` 必须有 `relation=contradicts` 的逐字证据；`insufficient_evidence`
  必须空证据并写检索范围；"未提及"不得判为反驳；外推型论断不得判为 `contradicted`。
- 新增比较方向、否定、数字保真检查；冲突须双方位置并给限定判定。
- 索引阶段强制排除 `claims-to-verify.json` 与 `case.json`，避免把问题当证据。

### v1.0.0（2026-11-20）

- 首版：四态证据表 + 逐字引文与定位坐标机检。
