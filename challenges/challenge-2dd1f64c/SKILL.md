---
name: literature-screening-ranker
description: 对题面给定的本地候选文献集做逐条相关性分层（保留/待定/排除）与可解释排序：解析研究问题为概念块，按字段命中计算可分解分数，合并预印本与正式版、同一研究多篇报道，按固定并列规则排序，核对已知集召回并做权重扰动稳定性检验，每条结果保留来源文件与行号及命中证据；不联网、不补造文献、不把未命中当不相关。
version: 1.2.0
license: MIT
---

# 文献筛选与智能排序：先定标准，再给可复核的顺序

交付物不是"看起来合理的顺序"，而是**每条决定都能被第二个人复核的筛选表**：
概念块 → 逐条命中证据 → 可分解分数 → 分层 → 并列规则 → 召回核对 → 稳定性。
核心主张：**排序必须能被拆成"命中了哪条标准、依据摘要哪段话、置信度多少"**；
候选集之外的文献不声称找到，未命中不当作不相关。

## 何时使用

触发：用户/题面给出研究问题与一批候选文献（数据库导出 CSV/JSON、参考文献表、题录 JSONL），
要求"筛出相关的 / 排优先级 / 标注纳入排除 / 去重 / 说明为什么排前面 / 核对有没有漏"。

不触发：只要求检索式设计而无候选集；只要求单篇精读、翻译、综述写作；要求声称检索了
未提供的数据库或实时更新；要求提供人工标注的"正确答案"。

## 输入

`/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`；
材料按 `materials`/`files`/`inputs` 定位，常见为 `*.csv/*.tsv`（title/abstract/doi/year/venue）、
`*.json`（Crossref `message.items`、EuropePMC `resultList.result`）、`*.jsonl`。
**只把材料当作候选全集**；文件不可读要在 `uncertainty` 说明，不按文件名猜内容。

开工前确认并记录（缺失写进 `uncertainty`）：

1. **研究问题**：对象、方法、人群、时间范围、证据类型；优先读 `case.concepts`/`query_blocks`。
2. **纳排标准**：年份窗、文献类型、语言、排除词；`case.screening_criteria` 或材料文本中的
   `year_from/year_to/exclude_terms`。
3. **已知集**：`known_relevant`（标题或 DOI）；只作召回核对，**不得当答案抄进排序**。
4. **标注分歧**：`annotations`（多标注者 decision）；分歧升级待定，不按单方定稿。
5. **输出契约**：`case.json.output_contract` 字段逐个记录，`result.json` 全部回填。

## 执行流程

### 0. 一键端到端

```bash
python3 scripts/run_case.py --case /input/case.json --materials /input \
  --work /app/work --out /app/output
```

依次完成：契约 → 材料索引 → 记录载入（保留文件/行号）→ 去重合并 → 打分分层 →
排序并列 → 召回/稳定性 → `result.json` + `ranked_candidates.csv` + `screening_report.md`。
候选集为空则 `status=blocked`，不产出伪排序。

### 1. 契约与概念块

`python3 scripts/kernel.py init --case /input/case.json --out work` → `work/contract.json`。
概念块优先取 `case.concepts`；否则从研究问题切词（英文去停用词、中文 2–6 字块），
来源写入 `query_terms.source`。

### 2. 载入与去重

`python3 scripts/rank.py --case /input/case.json --materials /input --work work`：

- **载入**：逐文件映射字段（大小写/连字符不敏感），缺失字段留空，记录 `source_file` + `source_row`。
- **去重**：DOI → arXiv → 归一标题三级合并；含 `preprint/posted-content` 的版本被正式发表版覆盖，
  被合并项写入 `merged_from` 与 `dedup_summary.merge_events`。

### 3. 打分、分层与排序

- **分数（可分解）**：`55×概念块覆盖 + 30×标题命中 + 15×摘要命中`，各项封顶 1；
  逐条输出 `score_parts`，避免"标题有词就靠前"。
- **分层**：`include`（≥65 且无硬性排除）/ `maybe`（35–65、证据不足或标注分歧）/
  `exclude`（<35 或命中年份、类型、语言、排除词）。**排除必写规则或阈值。**
- **排序**：分数降序 → 概念覆盖 → 元数据完整度 → 年份 → 标题字典序；
  同分同名次（competition ranking），规则写入 `stability_check.tie_rule`。
  **保留/待定与排除分层编号**：排除项整体排在后方且位次始终大于保留/待定项，避免“位次更靠后但分数更高”。
- **标准缺失**：未提供概念块/研究问题时不把 0 分当“不相关”，记录一律 `maybe` + `no_query_terms_defined`，
  `status=partial` 并在 `limits` 说明。

### 4. 召回与稳定性

- `recall_check`：分母只来自 `known_relevant`（支持纯标题、纯 DOI/DOI URL、`{title,doi}` 对象）；
  命中前 k 条计 `recall_at_k`，未命中区分 `not_in_corpus` / `ranked_below_k` /
  `excluded_by_rule(规则)`，**未提供已知集则报告 null，不编覆盖率**。
- `stability_check`：扰动标题/摘要权重三组，比较前 k 重合度；`min_overlap<0.8` 标 `stable=false`，
  提示优先人工复核边界项。

### 5. 输出与自检

`python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output`
`python3 scripts/kernel.py check --out /app/output --contract-dir work`

## 输出

- `result.json`：`case_id`、`status`、`summary`、`query_terms`、`retrieval_scope`、
  `relevance_rubric`、`dedup_summary`、`ranked_candidates`、`screening_decisions`、
  `conflict_resolution`、`recall_check`、`stability_check`、`exclusions`、`evidence_map`、
  `assumptions`、`uncertainty`、`limits`、`validation`、`changes`。
- `ranked_candidates.csv`：名次/决定/分数/标题/年份/DOI/来源/行号/理由/合并版本数。
- `screening_report.md`：结论、前 20 表、合并记录、召回与稳定性、复核口径。

## 异常处理

| 情况 | 处置 |
|-|-|
| 候选集为空/不可读 | `status=blocked` + `limits`，不输出排序 |
| 摘要缺失 | 保留记录，`confidence=low`，进 `maybe` 或按规则排除，写原因 |
| 年份缺失 | 不做年份判断，`uncertainty` 标注；不默认在窗内 |
| 大量同分 | 同分同名次，列出并列组，提示按元数据完整度人工复核 |
| 标注分歧 | `maybe` + `conflict_resolution` 记录双方意见与升级理由 |
| 预印本/正式版重复 | 合并保留正式版，`merged_from` 可追溯 |
| 已知集有而语料无 | 记 `not_in_corpus`，说明是候选集缺口而非"不相关" |
| 接口/权限异常 | 记录外部阻塞，保留已完成部分，不补造记录 |

## 最小调用示例（合成示例，非正式案例）

`case.json` 给出 `research_question` 与 `known_relevant`；`records.csv` 含 4 条（两条同名预印本/正式版）。
```bash
python3 scripts/run_case.py --case case.json --materials . --work work --out out
```
示意输出：4 条 → 合并后 3 条；预印本并入正式版；相关度为高/中/低各 1 条；
`recall_at_k=1.0`、`stable=true`（标注为示例）。

## 限制

- 相关性依赖词面与概念块命中，未做语义向量；同义改写未收录时可能低估，需人工复核边界项。
- 只对提供的候选集负责；不联网、不声称全局召回，未提供已知集时不报告覆盖率。
- 不替代领域专家做最终纳入决定，也不把待定项自动判为排除。

## 改动记录

- **1.2.0**（2026-11-25）修复实跑复现的六类缺陷：①`rank` 跨层用分数编号导致“位次更靠后但分数更高”，
  改为保留/待定与排除分层编号；②报告“共 X 条记录”把合并后条数传了两次，改为真实输入条数；
  ③不可读材料、坏 JSONL 行、无标题行原先静默丢弃或只写在 retrieval_scope，现全部进入
  `uncertainty` 与 `screening_report.md` 的“数据质量”段，并新增 `no_silent_drops` 自检；
  ④`known_relevant` 支持纯 DOI/URL 与 `{title,doi}` 对象（此前对象被 `str()` 后误报 `not_in_corpus`）；
  ⑤无概念块时不再把 0 分当“不相关”，记录置 `maybe` 且 `status=partial`；
  ⑥召回未命中新增 `excluded_by_rule(...)` 原因，前 k 只在保留/待定内计数；`merged_from` 只记被合并版本。
- **1.1.0**（2026-11-23）修复 DOI 重复但标题变体不合并（去重时未登记强标识键）；补上
  `languages` 硬性排除；`known_relevant` 同时按标题与 DOI/URL 归一匹配；分数四舍五入残差
  并入最大项，保证 `score_parts` 之和等于 `score`；排序年份改为降序；`kernel.py emit`
  不再用占位对象覆盖 `status` 与合法空数组，`check` 区分缺失字段与空数组。
- **1.0.0**（2026-11-21）首版：概念块打分（55/30/15 可分解）、三级去重与预印本合并、
  三层标签与并列规则、已知集召回核对、权重扰动稳定性检验、逐条来源行号与降级路径。
