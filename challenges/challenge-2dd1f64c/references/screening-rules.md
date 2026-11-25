# 筛选与排序规则

## 1. 概念块

- 优先 `case.concepts` / `query_blocks`，每个块是一组同义词/缩写/上下位词。
- 无显式概念块时，从研究问题切词：英文去停用词（the/and/study/…），中文取 2–6 字连续块。
- 概念块数量 2–5 个；不足时在 `uncertainty` 说明"标准偏窄"。

## 2. 分数（可分解）

```
score = 55 × coverage + 30 × title_match + 15 × abstract_match
coverage       = 命中的概念块数 / 概念块总数
title_match    = min(1, 标题命中词数 / 3)
abstract_match = min(1, 摘要命中词数 / 3)
```

- 只看标题/摘要，不读 PDF 全文；不对未提供字段做推断。
- 同义改写未收录会导致低估，边界项进 `maybe`。

## 3. 三层标签

| 标签 | 条件 |
|-|-|
| include（保留） | score ≥ 65 且未命中硬性排除 |
| maybe（待定） | 35 ≤ score < 65；摘要缺失；标注分歧 |
| exclude（排除） | score < 35 或命中年份/类型/语言/排除词 |

硬性排除优先于分数；判定条件与证据必须写进 `reason`。

## 4. 去重与版本

- 合并键顺序：`doi:` → `arxiv:` → 归一标题（小写、去标点、压空白）。
- 同组内 `preprint/posted-content/working paper/arxiv` 视为预印本；有正式版时保留正式版，
  预印本写入 `merged_from`，`version_note=merged_duplicate_versions(preprint_superseded)`。
- 同一研究多篇报道：标题不同则不自动合并，标 `maybe` 并要求人工确认是否同一研究。

## 5. 排序与并列

1. score 降序
2. coverage 降序
3. 元数据完整度（有 DOI 且 有年份 优先）
4. 年份降序
5. 标题字典序（保证可复现）

同分同名次；并列组在报告中列出，不擅自用随机顺序打破。
保留/待定（include/maybe）与排除（exclude）**分层编号**：排除项整体排在保留/待定之后，
其 rank 始终大于保留/待定的最大 rank，避免出现“位次更靠后但分数更高”的非单调结果。

## 6. 冲突与升级

- 多标注者 decision 不一致 → `maybe` + `conflict_resolution`，写明双方意见。
- 摘要信息不足以下结论 → `maybe`，`confidence=low`。
- 预印本与正式版结论冲突 → 保留两版来源，按正式版排序并标注待核。

## 7. 召回核对

- 分母只来自题面 `known_relevant`；不得用检索结果自身作分母。
  条目可为纯标题、纯 DOI/DOI URL 或 `{title,doi}` 对象。
- 前 k 只在保留/待定（include/maybe）内计数，排除项不占前 k 名额。
- 未命中原因分类：`not_in_corpus`（候选集缺口）、`ranked_below_k`（排序过低）、
  `excluded_by_rule(规则)`（硬性规则排除）。`not_in_corpus` 不等于"不相关"。

## 8. 数据质量与未纳入项

- 不可读文件、坏 JSONL 行、无标题行都必须写入 `uncertainty` 与报告“数据质量”段，并记录数量/行号，
  不允许静默丢弃；无标题行只计为未筛选，不臆造标题。
- 没有概念块/研究问题时，相关性分数不可计算：记录置 `maybe` + `no_query_terms_defined`，
  `status=partial`，不把 0 分当“不相关”。
