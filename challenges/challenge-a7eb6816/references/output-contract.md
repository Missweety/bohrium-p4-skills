# 输出契约（Output Contract）

本文件定义 `build_transform.py` 写出的交付物、`result.json` 的字段、`case.json` 中 `output_contract` 的兼容方式，以及 `selfcheck.py` 的复算口径。实现以 `scripts/` 中的代码为准；文档与代码冲突时，以代码为准并提 issue。

## 1. 文件清单

| 文件 | 是否必需 | 说明 |
|---|---|---|
| `/app/output/transform.md` | 是 | 成稿正文。UTF-8。标题为一级标题，章节为二级标题；`## 术语与缩写` 之后为附录，不参与目标篇幅统计。 |
| `/app/output/preservation_map.csv` | 是 | 逐条 claim 的来源与输出位置。UTF-8（带 BOM，便于表格软件打开）。 |
| `/app/output/glossary.csv` | 是 | 术语/缩写的处理清单。UTF-8（带 BOM）。 |
| `/app/output/result.json` | 是 | 机器可读结果与契约字段。UTF-8。 |
| `/app/output/checks.json` | 由自检生成 | 独立复算结果；`ok=false` 表示存在硬错误。 |

`transform.md` 为空不等于“篇幅为 0”，而是 `status=failed`。

## 2. preservation_map.csv 列

```csv
claim_id,kind,claim,source_doc,anchor,quote,quote_verified,strength,source_strength,output_location,output_excerpt,match,status
```

- `claim_id`：与 `plan.claim_evidence[].id` 一致；未填时自动 `c1..cN`。
- `kind`：`claim|conclusion|number|limitation|scope|method|citation|definition`。
- `claim`：正文中的说法（用于定位与复核）。
- `quote`：从 `sources.json` 复制的源文引文；核验采用“忽略空白、大小写与常见排版符号”的子串匹配。
- `quote_verified`：`True` 表示引文在源文中命中；`False` 表示未命中，必伴随 `quote_unverified` error。
- `source_doc`：从 `anchor` 解析出的 `doc.N`。
- `output_location`：`<section_id>#p<K>`（第 K 个正文段落）；`match=exact` 为原样命中，`fuzzy` 为高重叠定位。
- `output_excerpt`：对应正文段落前 140 字符。
- `status`：`verified | unverified | missing_quote | not_in_output`（未核验/未定位时如实标记）。

要求：正文中的每个结论/数字/局限都应有一行；`selfcheck` 在 `status=success` 时要求所有引文 `quote_verified=True`。

`omissions` 的“已覆盖”判定：源段落与正文的词面重合率 ≥ 12%，**或**存在一条已核验且已定位、`anchor` 指向该段落的 claim。后者用于跨语言改写（英文源 → 中文稿），避免译文被误判为遗漏。

## 3. glossary.csv 列

```csv
term,plain_language,action,aliases,occurrences,inline_expanded,status,source_note
```

- `action`：`expand`（首次出现处就地解释）、`replace`（正文改用日常说法）、`keep`（保留术语，靠术语表解释）。
- `inline_expanded`：`True/False/None`；`expand` 项为 `False` 时产生 `glossary_not_expanded` error。
- `occurrences`：正文（不含术语附录）中的出现次数。
- 面向非专业读者时，正文出现的缩写若不在术语表且不在常用白名单（PDF/DOI/URL/DNA/RNA 等）内，会产生 `unglossed_jargon` error；专业读者降为 warn。

## 4. result.json 结构

```json
{
  "case_id": "…",
  "status": "success|partial|failed",
  "status_reason": "一句话说明为什么是这个状态",
  "sources": [{"doc": "doc.1", "path": "paper.pdf", "sha256": "…", "engine": "pdftotext",
               "readable": true, "paragraphs": 42, "warnings": []}],
  "uncertainty": [{"issue": "…", "decision": "…", "needs_human": true}],
  "change_log": ["读取 sources.json：…", "核验数值：…", "status=…：…"],
  "issues": [{"code": "quote_unverified", "severity": "error", "detail": "…", "where": "c1"}],
  "deliverables": [{"name": "transform.md", "path": "/app/output/transform.md",
                    "bytes": 1234, "sha256": "…"}],
  "transform": {"title": "…", "genre": "popular_science", "genre_label": "公众科普文章",
                "audience": {"who": "…", "prior_knowledge": "none", "purpose": "…", "reading_level": "…"},
                "target_length": {"max_words": 800},
                "sections": [{"id": "s1", "heading": "…", "role": "hook", "paragraphs": ["…"]}],
                "file": "transform.md", "word_count": 0, "char_count": 0},
  "metrics": {"chars": 0, "words": 0, "cjk_chars": 0, "latin_words": 0, "sentences": 0,
              "avg_sentence_chars": 0.0, "long_sentence_ratio": 0.0,
              "jargon_occurrences": 0, "jargon_per_1000_chars": 0.0,
              "flesch_reading_ease": null, "metrics_source": "transform.md#body"},
  "preservation": {"claims": [], "claim_count": 0, "verified_claims": 0,
                   "verification_rate": 0.0, "located_claims": 0, "locate_rate": 0.0,
                   "map_file": "preservation_map.csv"},
  "glossary": [],
  "removals": [{"removed": "…", "source_anchor": "doc.1 p.3", "reason": "…", "risk": "low"}],
  "omissions": [{"anchor": "doc.1 p.3 sec.2 para.9", "excerpt": "…", "coverage": 0.04,
                 "has_number": true, "has_limitation": false, "status": "logged|unlogged"}],
  "limitations_check": {"source_limitation_sentences": 0, "covered": 0, "coverage": 1.0,
                        "uncovered": []},
  "numbers": [{"token": "71%", "digits": "71", "status": "verbatim|verbatim_digits|derived|unsupported",
               "source_anchor": "doc.1 p.2 sec.4 para.4", "basis": ""}],
  "conflicts": [{"anchor_a": "…", "anchor_b": "…", "excerpt_a": "…", "excerpt_b": "…",
                 "numbers_a": [], "numbers_b": []}],
  "contract_fields": {"case.json 中 output_contract 的每个键": "对应值"}
}
```

### 数值状态

- `verbatim`：输出 token（如 `71%`）在源文数字集合中逐字出现。
- `verbatim_digits`：数字部分（`71`）在源文出现，但单位/百分号写法不同；视为可追溯，`selfcheck` 接受。
- `derived`：源文无此写法，但 `plan.numbers[]` 给出非空 `basis`；`selfcheck` 接受。
- `unsupported`：三者皆非；`build_transform` 记 error，`selfcheck` 硬失败。

`digits_of` 只保留数字与小数点；因此 `0.71` 不等于 `71`，`1,000` 归一为 `1000`。标题行、列表编号、URL、DOI、方括号引用编号不参与数值检查。

## 5. output_contract 兼容

`case.json` 的 `output_contract` 支持：

1. **列表**：`["transform_md", "preservation_map", "glossary"]`，或 `[{"name": "…"}, {"field": "…"}]`。
2. **对象**：每个键都写入 `result.json` 顶层与 `contract_fields`；若含 `required`/`fields`/`properties`，其内部名称也一并展开。
3. **其它键名**：`outputContract` / `contract` / `required_outputs` 作为别名。

键名解析顺序：

1. `plan.contract_fields[键名]`（你显式提供的值，优先级最高）；
2. 内置槽位（见下表）；
3. `result.json` 中同名顶层字段；
4. `plan.json` 中同名字段；
5. 空字符串，并记 `contract_field_empty` warning。

| 契约键（含常见别名） | 取值 |
|---|---|
| `transform` / `transform_md` / `article` / `manuscript` / `rewrite` / `final_text` / `markdown` / `正文` | `transform.md` 全文 |
| `artifact_path` / `output_path` / `deliverable_file` / `deliverable_path` / `filename` | `"transform.md"` |
| `preservation` | `result.preservation` 对象 |
| `preservation_map` / `source_map` / `claim_map` / `evidence_map` / `claims` | claim 行数组（同 CSV） |
| `glossary` / `terms` / `terminology` | 术语对象数组 |
| `metrics` / `readability` / `length` | `result.metrics` |
| `word_count` / `char_count` / `summary` / `readability_notes` | 由 metrics/首段计算 |
| `limits` / `constraints` | `result.limitations_check` |
| `self_check` / `audit` | 核验摘要（claim 数、通过数、无源数值数、error 数、metrics） |
| `numbers` / `omissions` / `removals` / `conflicts` | 对应数组 |
| `sources` / `uncertainty` / `change_log` / `changes` / `issues` / `deliverables` / `status` / `case_id` / `title` / `audience` / `genre` / `target_length` | 同名结构字段 |

注意：`status=success` 仍可能带 warning；但任何 error 都会使状态变为 `partial`。`failed` 只用于无来源、plan 缺失或正文为空。

`title` / `audience` / `genre` / `target_length` 这 4 个键实际存放在 `result.transform` 下（不是 `result.json` 顶层），解析时优先从 `result.transform` 取值；早期版本误按顶层读取，会得到 `null`。

## 6. 指标口径（均由 transform.md 正文实际计算）

正文 = `transform.md` 中 `## 术语与缩写` 之前的部分（含标题与章节小标题），附录不计入。

- `chars`：去除空白后的字符数。
- `words`：CJK 字符数 + 拉丁词数（拉丁词按 `[A-Za-z][A-Za-z'\-]*` 计）。这是中英混排的可比近似值，不是语言学词数。
- `sentences`：按 `。！？!?`、句点后接空白+大写、空行切分。
- `avg_sentence_chars`：每句去空白字符数的平均值，保留 1 位小数。
- `long_sentence_ratio`：超过 60 字符的句子占比，保留 3 位小数。
- `jargon_occurrences`：`glossary` 中术语在正文中的出现次数（拉丁词按词边界、大小写不敏感；中文按子串）。
- `jargon_per_1000_chars`：`jargon_occurrences / chars * 1000`，保留 1 位小数。
- `flesch_reading_ease`：仅当拉丁词占 `words` 的 50% 以上时计算；否则为 `null`，不编造。

`selfcheck.py` 会从文件重新计算并与 `result.metrics` 对比；不要手改指标。

## 7. issues 约定

```json
{"code": "unsupported_number", "severity": "error|warn", "detail": "人类可读说明", "where": "锚点/claim id/plan 路径"}
```

常见 error：`unsupported_number`、`quote_unverified`、`claim_missing_quote`、`claim_not_in_output`、`claim_strength_upgrade`、`fabricated_experience`、`fabricated_quote`、`glossary_plain_missing`、`glossary_not_expanded`、`unglossed_jargon`（非专业读者）、`omission_unlogged_number`、`omission_unlogged_limitation`、`limitations_absent`、`removal_missing_reason`、`no_claim_evidence`、`no_readable_sources`、`plan_missing`。

常见 warn：`unsupported_genre`、`genre_element_missing`、`omission_unlogged`、`source_conflict`、`limitation_under_preserved`、`removal_risk_invalid`、`over_length_margin`、`under_length`、`sentences_too_long`、`jargon_density_high`、`declared_number_unused`、`contract_field_empty`、`unverified_quotation`、`jargon_retained`、`appendix_number_unsupported`。

## 8. selfcheck 的硬失败（退出码 1）

- `result.json` 缺失/不可解析；必需交付物缺失或为空；
- 契约键缺失、为 `null`、`contract_fields` 不完整或与顶层不一致；`case_id` 不一致；
- 指标无法由 `transform.md` 复算（字符/词/句/术语次数不一致）；
- 正文出现无源数值且无推导依据，或 `result.numbers` 把无源数值标成 `verbatim`；
- `preservation_map` 把源文找不到的引文标成 `verified`；声明核验率高于实际；
- 删除项缺 `reason`；存在未登记遗漏且 `status=success`；
- 占位符（TODO/TBD/FIXME/`{{…}}`/`[待…]`/`待填写`/`此处省略`/`XXX`）；
- 篇幅超过上限 110% 且 `status=success`；
- `status=success` 但存在 error issue、未核验 claim 或未登记遗漏。

自检只做“文件与声明是否自洽”，不替代原作者对学术内容的判断。

`status=failed` 时，下列检查降为 warn（诚实失败不应被判成产物损坏）：`sources_readable`、`numbers_traceable`、`preservation_map_nonempty`、`contract_keys_nonnull`。其余硬检查（文件存在、契约键存在、指标可复算、`numbers_status_truthful`、`status=success` 的一致性）不变。
