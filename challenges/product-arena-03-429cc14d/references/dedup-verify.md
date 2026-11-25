# 去重判据与来源核验（本地、可解释、不联网）

原则：**去重是"证明两条记录指同一文献"，不是"看起来像"**。合并错一条，正文引用就会指向
错误的结论，比不合并更糟。因此判据分级、证据留痕、可疑不合并。

## 1. 去重判据分级

| 级别 | 判据 | 代码 `criterion` | 处置 |
|-|-|-|-|
| A 确定 | DOI 规范化后完全一致（忽略大小写、`https://doi.org/` 前缀） | `doi_exact` | 自动合并，保留字段更全的一条 |
| B 确定 | 题名规范化后完全一致（去标点/空格/大小写/全半角），且年份一致 | `title_exact` | 自动合并 |
| C 疑似 | 题名互相包含且较短题名长度 ≥20 字符、长度比 ≥0.9 | `title_containment` | 列候选，人工确认 |
| D 疑似 | 第一作者姓 + 年份 + 题名前 6 个实词一致 | `author_year_title` | 列候选，人工确认 |
| E 禁止 | 仅作者相同 / 仅年份相同 / 仅期刊相同 | — | **不得合并** |

规范化函数（与脚本一致）：NFKC → 小写 → 仅保留字母、数字、汉字。

## 2. 版本关系（不是"重复"，但不能当两项新工作）

| 情形 | 正确做法 |
|-|-|
| 预印本（arXiv/bioRxiv）与正式版 | 保留正式版为主条目；预印本在 `notes` 记 `preprint_of`，正文引用指向正式版 |
| 会议版与期刊扩展版 | 若题名/作者/核心结论一致，视为同一工作的两个版本，保留期刊版为主，会议版注 `conference_version_of` |
| 中文版与英文版（同一研究） | 保留与稿件语言一致的版本为主条目，另一版注 `translated_version_of`，**不合并为一条** |
| 数据库重复导出（CNKI + Scopus） | 按 A/B 级判据合并；字段冲突逐字段取并集并标注来源库 |

## 3. 合并证据模板（写入 `merge_groups[]`）

```json
{
  "kept": "12",
  "merged": ["27"],
  "criterion": "title_exact",
  "evidence": "normalized title identical: 'nanotio2photocatalyticdegradationofdye'",
  "field_resolution": {"doi": "kept 12 (27 empty)", "pages": "kept 12 (27 missing)"},
  "human_confirmed": false
}
```

要求：
- `evidence` 必须能被人复核（贴规范化题名、DOI 或字段对比），不能只写"看起来一样"。
- `field_resolution` 说明冲突字段取了谁、为什么。
- `human_confirmed=false` 的合并必须同时出现在 `uncertainty`。

## 4. 误合并反例（必须避免）

```
反例1：张三 2019《城市污水脱氮》 vs 张三 2019《城市污水除磷》
      同作者同年，题名不同 → 不得合并（E 级）。
反例2：Li et al. 2020 "Adsorption of Pb(II) by biochar" vs Li et al. 2020
      "Adsorption of Cd(II) by biochar" → 仅一字之差，题名规范化后不同，不得按 D 级自动合并。
反例3：同一论文的中文版与英文版 → 版本关系，不是重复条目。
反例4：题名相同但 DOI 不同、作者不同 → 极可能是同名不同文，按 C 级列候选，禁止自动合并。
```

## 5. 来源核验等级（无网络环境）

| 等级 | 含义 | 依据 |
|-|-|-|
| `verified` | 条目字段与文献库/材料内记录逐字段一致 | `corpus.txt` 中可定位到同一记录 |
| `partial` | 有记录，但字段缺失或与正文叙述不一致 | 记录存在 + 差异清单 |
| `unverified` | 文献库内查不到该条目 | 只有正文引用，无库记录 |
| `doi_not_checked_offline` | DOI 格式合法但无法在线解析 | 仅做正则与校验位检查 |

**禁止**：把 `unverified` 表述为"该文献不存在"；把"DOI 格式合法"表述为"DOI 有效"。

## 6. 逐条核验操作单

1. 在 `corpus.txt` 中按题名前 30 字符检索，确认记录真实存在并记录行号。
2. 比对作者顺序与人数规则；不一致记 `author_mismatch`。
3. 比对年份；正文叙述年份与条目年份不一致记 `year_mismatch`（常见于"2020 年提出"实为 2019 在线）。
4. 比对期刊/会议名与卷期页；缺失记 `field_gap`，冲突记 `conflict`。
5. 检查 DOI 正则 `^10\.\d{4,9}/\S+$`，并去掉末尾标点；无法解析时标 `doi_not_checked_offline`。
6. 判定正文论断与条目主题是否匹配：题名/关键词与句子主张无交集 → `topic_mismatch`，
   在报告中给出句子定位与条目题名，**不要自行换一条引用顶上**。

## 7. 报告字段最小集

```json
{"entry_id": "12", "verification": "partial", "missing": ["doi", "pages"],
 "conflicts": [{"field": "year", "in_text": "2020", "in_entry": "2019"}],
 "topic_match": "yes|no|unclear", "locator": "corpus.txt line 214"}
```
