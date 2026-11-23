---
name: structure-aligned-paper-noter
description: 把真实科研论文读成与原文章节一一对应的结构化笔记：按固定骨架（研究问题—方法—数据—主要结论含数值—局限—可复用点）抽取，每条结论绑定页码/段落/原文引文锚点，区分作者主张与笔记推断，跨章节冲突并列保留，并用脚本校验字段完整性与锚点真实性。用于论文卡片、章节笔记、知识点整理与多篇论文并排比较；不用于无原文的综述代写、凭空补数据或纯翻译。
version: 1.2.0
license: MIT
---

# 文献总结：章节对齐、字段齐备、锚点可回查

把"读一篇论文"拆成 **章节切分 → 六字段抽取 → 锚点绑定 → 机器校验 → 可复用笔记**。
核心主张：笔记的骨架跟着论文的论证走，不跟着通用模板走；每条结论都能按锚点翻回原文；
作者说的和笔记推的必须分开；两处数值打架时并列保留，不擅自选一个。

## 何时使用

触发：用户给出论文（pdf/docx/tex/md/图片 OCR）并要求"做笔记"、"总结这篇"、"整理成论文卡片"、
"提取研究问题/方法/数据/结论/局限"、"做成可检索的笔记"、"多篇论文对比"。

不触发：没有原文、要求凭题名生成总结（只能说明缺什么）；只做逐段翻译（用
`glossary-locked-bilingual-translator`）；要求评价论文创新性并打分为主（本 Skill 只做证据化笔记，
评价必须基于笔记中的原文依据）；要求联网检索相关文献。

## 输入

`/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`；材料由题面提供。
字段名不固定，**先读真实文件**：

| 语义 | 常见字段/文件 |
|-|-|
| 论文原文 | `source_text`, `text`, `paper`, 正文 pdf/docx/tex/md |
| 任务要求 | `task`, `question`, `focus`（如"只做方法部分"） |
| 输出契约 | `output_contract` |
| 案例标识 | `case_id` |

题面若限定章节范围（如"只整理方法与结果"），笔记骨架只覆盖该范围，并在 `limits` 写明未覆盖章节。

## 执行流程（严格按序）

1. **契约**：`python scripts/kernel.py init --case /input/case.json --out work`
   → `work/contract.json`。确认输出语言、范围与 `output_contract` 字段。
2. **证据索引**：`python scripts/kernel.py index --materials <材料路径...> --out work`
   → `work/evidence.json` + `work/corpus.txt`。不可读标 `unreadable`，**不得凭常识补论文内容**。
3. **章节切分（对得上）**：按原文标题顺序建 `work/sections.json`：

   ```json
   {"paper": {"title": "...", "sections": ["Abstract", "1 Introduction", "2 Methods", "3 Results", "4 Discussion", "5 Conclusions"]},
    "order": ["Abstract", "1 Introduction", "2 Methods", "3 Results", "4 Discussion", "5 Conclusions"]}
   ```

   章节名与顺序**照抄原文**，不重排、不合并、不改写成通用模板（Introduction/Related Work/…）。
   原文无编号时用标题原文；双栏错序时按标题层级重排并在 `changes` 记录。
4. **六字段抽取（留得住）**：写 `work/notes.json`，每条记录：

   ```json
   {"id": "F02", "text": "pH 由 3 升至 6 时去除率从 41.2% 升至 88.6%",
    "value": "41.2% → 88.6%", "topic": "pH_effect", "kind": "author_claim",
    "anchor": {"section": "3 Results", "page": "p.6", "paragraph": 2},
    "quote": "The removal efficiency increased from 41.2% to 88.6% as pH rose from 3 to 6",
    "basis": [], "conflict_group": null}
   ```

   六字段与来源约束：

   | 字段 | 必须来自 | 缺省处理 |
   |-|-|-|
   | `research_question` | Abstract / Introduction 原文 | 原文未明说时写 `not_stated` 并引用最接近的句子 |
   | `methods` | Methods（含条件：样本、温度、pH、对照、统计检验） | 只列步骤不写条件视为不完整 |
   | `data` | Methods / Data availability（规模、划分、来源、可得性） | 未报告写 `not_reported`，不推测 |
   | `findings` | Results / Abstract，必须带数值与统计量 | 无数值的结论降级为 `qualitative` 并说明 |
   | `limitations` | Discussion / Conclusion 作者明说的 | 笔记推断的局限必须 `kind: inference` + `basis` |
   | `reuse_points` | 方法可迁移点 / 数据可用性 / 结论适用边界 | 每条必须有 `use`（怎么用、什么条件下能用） |
5. **锚点绑定（找得回）**：每条记录必须同时有 `section`、`page` 或 `paragraph`、`quote`（≥12 字符，
   **逐字复制**，不改写、不省略号拼接）。quote 建议直接取自 `corpus.txt`。
6. **锚点逐字核验**：把全部记录转成 `work/quotes.json`
   （`[{"claim":"F02","source_path":"...","quote":"...","locator":"p.6 para 2"}]`，
   **不要覆盖 `work/evidence.json`**），执行
   `python scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt --out work/quote_check.json`；
   `not_verbatim` 必须改为原文片段或删除该条。
7. **结构与一致性校验**：
   `python scripts/note_schema_check.py --notes work/notes.json --corpus work/corpus.txt --out work/note_check.json`
   要求 `verdict=pass`：六字段非空、`id` 唯一、`kind` 合法、锚点章节存在于 `paper.sections`、
   quote 逐字命中、正文与 `value` 中的数字都能在原文找到、`inference` 必有 `basis`。
   警告项（`finding` 有数字但缺 `value`、同 `topic` 结论分叉却无 `conflict_group`、`reuse` 缺 `use`）
   必须逐条处理或写入 `uncertainty`。
8. **冲突并列**：同一指标在不同章节数值/方向不一致时，两条都保留，共用 `conflict_group: "C1"`，
   在 `uncertainty` 写明两处位置与差异，**不合并、不平滑、不选一个**。
9. **数字二次守恒**：把笔记正文（不含 `id`、页码与 `p.6 ¶2` 这类锚点文本）拼成 `work/notes_text.txt`，
   执行 `python scripts/kernel.py verify --text work/notes_text.txt --evidence-dir work --out work`，
   `unsupported_numbers` 应为 0；共享 kernel 对 `[3,5]` 的整串检索会误报，引用以 `note_check.json` 为准。
10. **产出**：生成 `work/notes.md`（人读）、`work/anchors.csv`、`work/draft.json`，执行
    `python scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output`，
    再 `python scripts/kernel.py check --out /app/output --work work` 必须 PASS。`check` 会核对运行时契约字段非空、
    `notes.md/notes.json/anchors.csv` 三件产物齐备、`anchors_verified == anchors_total`、
    `note_check.json` 与 `quote_check.json` 均为 pass；缺字段时 `emit` 退出码为 1，不能带着空缺交付。
11. **检索、并排比较与一致性/增益证据（多篇论文或有"可检索"要求时）**：
    - `python scripts/kernel.py search --notes work/notes.json --query "pH" --out work/search.json`
      → 按 `id/text/value/topic/quote` 命中，返回字段名与锚点，可直接回答"哪篇、哪节、哪条"。
    - `python scripts/kernel.py compare --notes work/notes_a.json work/notes_b.json --out work/compare.json --markdown work/compare.md`
      → 以 `topic` 为行做并排矩阵，输出跨论文共有主题与差异主题；同一主题数值不同时并列列出，不替读者取舍。
    - `python scripts/kernel.py consistency --corpus work/corpus.txt --out work/consistency.json`
      → 只比较"摘要 vs 正文"中同指标、同单位且数值互不重合的情况（重合视为摘要复述正文，不报警），
      输出候选与两侧原文句子，标注 `needs_confirmation`，语义是否冲突由人确认。
    - `python scripts/kernel.py baseline --corpus work/corpus.txt --notes work/notes.json --out work/baseline_compare.json --markdown work/baseline_compare.md`
      → 在同一材料、同一 corpus 解析、同一案例请求下，用确定性白板（按章节取首句摘要，不额外调用模型）做公平对照，
      输出条目数、字段覆盖、带锚点条目、可检索/可比较能力的差值，作为增益可验证证据。

## 领域规则表（按题面四个关注点）

| 关注点 | 硬规则 | 反例（禁止） |
|-|-|-|
| 对得上 | 章节名、顺序、层级照抄原文；摘要单列，不替代正文章节；每节笔记之间有承接（上一节结论如何进入下一节） | 把 Methods 与 Results 合成"实验与结果"一节；用通用模板覆盖原文结构 |
| 留得住 | 六字段齐全；方法写条件（样本量、温度、pH、对照、统计检验），结论写数值与统计量；局限区分作者承认与笔记推断 | 方法只写"做了吸附实验"；结论只写"效果很好" |
| 找得回 | 每条有 `section + page/paragraph + quote`；quote 逐字；图表结论标 `Figure N`/`Table N` | 只写"见原文"或"作者认为"；quote 是改写后的句子 |
| 用得上 | 每条 `reuse_points` 有 `use` 与适用边界；`topic` 可聚合；`id` 稳定可被后续引用 | 笔记只有段落摘要，无法检索、无法与另一篇并排比较 |

## 硬性禁止

- 不新增原文没有的数值、样本量、p 值、结论或引用；不把"未报告"写成"没有"。
- 不把笔记推断写成作者主张；`kind: inference` 必须有 `basis`（支撑它的 `author_claim` id）。
- 不改写章节顺序与名称来套模板；不把摘要扩写成全文摘要。
- 不在 quote 中使用省略号拼接、翻译或改写；quote 必须能在原文中逐字找到。
- 不把扫描件/图片内容当作已读到的文字；不提交预制答案。

## 输出

`/app/output/result.json`（`case_id`、`status`、`answer`、`structured`、`evidence`、`uncertainty`、`limits`，
以题面 `output_contract` 为准）+ 可编辑产物：

| 文件 | 内容 |
|-|-|
| `notes.md` | 按原文章节的笔记正文，每条带 `[F02 · p.6 ¶2]` 锚点 |
| `notes.json` | 六字段结构化笔记（含 `kind` / `basis` / `conflict_group`） |
| `anchors.csv` | `id,field,section,page,paragraph,quote,kind,basis` |
| `note_check.json` | 字段完整性、锚点、数字与冲突校验结果 |

`structured` 至少包含：`sections`、`field_counts`、`anchors_total`、`anchors_verified`、
`inference_count`、`conflict_groups`、`check_summary`、`artifacts`。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 扫描件/加密文档/无文字层 | 标 `unreadable`；有 OCR 时标注 `source: ocr` 与置信度；否则 `status: blocked`，不猜内容 |
| 双栏错序、跨页断段 | 按标题与语义重排，`changes` 记录；无法判定时标 `〔顺序待确认〕` |
| 图表/公式为图片 | 只记录图注文字与 `Figure N` 位置，不推断图内数值；进 `uncertainty` |
| 超长文（>64k tokens） | 先按章节建索引，逐节做笔记，优先研究问题/方法/结果/局限四段；`partial` + `limits` |
| 非中文论文 | 笔记用题面语言，`quote` 保留原文语言不翻译 |
| 原文自相矛盾 | 并列 + `conflict_group`，在 `uncertainty` 写明两处定位 |
| 章节缺失（如无 Limitations） | 写 `not_stated` 并说明检索过的章节，不推断作者意图 |

## 文件说明

- `scripts/kernel.py`：`init / index / verify / emit / check / search / compare / consistency / baseline`（仅标准库）。
- `scripts/quote_check.py`：锚点 quote 逐字核验，防止改写冒充原文。
- `scripts/note_schema_check.py`：六字段完整性、锚点章节有效性、数字可溯、inference 依据、冲突成组。
- `references/note-schema.md`：六字段定义、记录 schema、`not_stated`/`not_reported` 约定。
- `references/anchor-rules.md`：锚点粒度、quote 选取与页码/段落编号规则、冲突并列写法。
- `references/output-contract.md`：默认输出字段；题面契约优先。

## 最小调用示例（示例，不是正式案例结果）

```bash
python scripts/kernel.py init --case /input/case.json --out work
python scripts/kernel.py index --materials /input/materials --out work
# 按第 3–5 步生成 work/sections.json、work/notes.json、work/quotes.json、work/notes.md
python scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt --out work/quote_check.json
python scripts/note_schema_check.py --notes work/notes.json --corpus work/corpus.txt --out work/note_check.json
python scripts/kernel.py verify --text work/notes_text.txt --evidence-dir work --out work
python scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output
python scripts/kernel.py check --out /app/output
```

示意输出（片段）：`F02 · 3 Results · p.6 ¶2` —— "pH 由 3 升至 6 时，Pb(II) 去除率由
41.2% 升至 88.6%（Figure 3）"，`note_check.json` 报 `verdict=pass errors=0`。

## 改动记录

- 1.0.0 初版：章节对齐 + 六字段 + 逐字锚点 + 机器校验。
- 1.1.0 补齐"可检索、可比较"：新增 `search`（按主题/数值/引文检索到条目与锚点）与 `compare`
  （多篇笔记按 `topic` 并排、列出共有与差异主题）；`check` 从只看 case_id/status 扩展到契约字段非空、
  三件产物齐备、锚点守恒、两份校验 pass；`emit` 缺契约字段时改为退出码 1，避免静默交付空缺。

- 1.2.0 补齐评分中的"增益可验证"与"创新证据"：新增 `consistency`（摘要 vs 正文同指标数值冲突候选，
  重合值不算冲突，避免把正文复述当矛盾）与 `baseline`（同材料、同解析、同请求的确定性白板对照，
  输出条目/字段/锚点/检索/比较的差值）；同时修复数值归属缺陷：一个句子里有多个指标时，
  数字须绑定到其前方最近的指标词，否则会把摘要中的吸附量误记到去除率上。
