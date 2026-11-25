---
name: glossary-locked-bilingual-translator
description: 把真实科研文献按术语表锁定的译名逐段翻译成可核验的双语对照结果：先抽取并锁定领域术语，再按原文段号切分、携带上下文续译，保护公式/单位/数字/引用/图表编号，最后用术语一致性与逐字引文核验脚本自检。用于论文全文或明确段落区间的翻译、双语对照排版与译文审校；不用于无原文的创作、摘要代写、纯语言润色或凭空补数据。
version: 1.2.0
license: MIT
---

# 文献翻译：术语锁定、段号对齐、可核验的双语对照

把"翻译一篇论文"拆成 **段落索引 → 术语表锁定 → 逐段翻译（带上下文）→ 机器核验 → 双语交付**。
核心主张：术语是全篇硬约束，不是提示词里的建议；段号是主键，一段都不能少、不能重、不能错位；
数字、单位、公式、引用与图表编号是保护区，只能原样搬运，不能顺手改写。

## 何时使用

触发：用户给出论文原文（pdf/docx/tex/md/txt/图片 OCR 结果）并要求翻译成中文（或其他目标语言），
或要求"双语对照"、"逐段对照排版"、"统一术语译名"、"校对译文是否漏段/改数"、"按段落续译长文"。

不触发：没有原文、要求直接写出译文或摘要（缺材料时只能说明缺什么）；只做语言润色而不需要对照原文；
只做文献总结/结构化笔记（用 `structure-aligned-paper-noter`）；要求联网查证术语标准译法（本 Skill 只在
给定材料与术语表内工作，术语来源必须写清）。

## 输入

`/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`；材料由题面提供。
字段名不固定，**先读真实文件**，不要凭标签猜内容：

| 语义 | 常见字段/文件 |
|-|-|
| 原文 | `source_text`, `text`, `paper`, 正文 pdf/docx/tex/md |
| 目标语言 | `target_language`, `language`, `lang` |
| 术语表 | `glossary`, `terms.tsv`, 用户随材料给出的词表 |
| 输出契约 | `output_contract` |
| 案例标识 | `case_id` |

术语表统一转成 TSV（四列，制表符分隔，`#` 开头为注释）：

```
source_term	target_term	code	banned_variants
sorption	吸附		吸收|吸着
solid-phase extraction	固相萃取	SPE	固相提取
```

`code` 可空；`banned_variants` 用 `|` 分隔，表示**禁止出现的旧译/错译**。术语表由材料或用户提供时
原样继承；没有术语表时按第 4 步自行抽取，并在 `uncertainty` 标注 `glossary_source: auto`。

## 执行流程（严格按序）

1. **契约**：`python3 scripts/kernel.py init --case /input/case.json --out work`
   → `work/contract.json`。确认目标语言、翻译范围（全文/段落区间）、`output_contract` 字段。
2. **证据索引**：`python3 scripts/kernel.py index --case /input/case.json --materials <材料路径...> --out work`
   → `work/evidence.json`（可读性、字符数、sha1、`encoding`、`reason`）+ `work/corpus.txt`。不可读文件标
   `readable:false` 并给 `reason`（如 `no_text_layer(...)`），**不得按领域常识补写原文**。
   材料路径写成相对 `case.json` 的 `materials/...` 时不必先 `cd`，`--case` 会按 case 目录解析。
   材料全部缺失或全部不可读时 `index` 退出码 1 并打印 `BLOCKED`，此时直接走"材料缺失"降级，不要产出空译文。
3. **段落切分**：建 `work/segments.json`，一段一条记录：

   ```json
   {"id":"P001","section":"Abstract","page":1,"span":"p.1","text":"...","kind":"body"}
   ```

   规则：`id` 按阅读顺序连续编号（`P001` 起，标题 `H`、图注 `C`、表注 `T` 同编号空间但前缀区分）；
   跨页/跨栏被折断的同一段**合并为一条**并在 `span` 记 `p.3-4`；标题、图题、表题、脚注各自独立成段；
   参考文献条目按 `R001` 起编号，不参与正文翻译但保留编号。切分后自查：段数 = 原文可见段数，
   每个 `id` 只出现一次，`text` 非空。
4. **术语锁定**：优先用给定术语表；缺省时从 `corpus.txt` 抽取高频领域名词/复合名词（多词短语优先），
   写入 `work/glossary.tsv`，每条标注来源（`given` / `auto`）。同一概念只允许一个 `target_term`；
   同义原文（如 `sorption` / `adsorption`）要么合并为一条，要么在 `uncertainty` 说明区分依据。
5. **逐段翻译**：每段翻译时携带三样上下文——本节标题、上一段原文末句与译文末句、当前已锁定的术语表。
   输出到 `work/bilingual.json`：

   ```json
   {"segments":[{"id":"P001","section":"Abstract","locator":"p.1 para 1",
     "source":"...","target":"...","terms_used":["sorption","SPE"]}]}
   ```

   长文按章节分批，每批译完立刻落盘，**不要等全文译完再写**（预算 900s，先保完整再打磨）。
6. **术语与保真核验**：
   `python3 scripts/term_consistency.py --glossary work/glossary.tsv --bilingual work/bilingual.json --out work/term_check.json`
   要求 `missing_locked = 0`、`variant_drift = 0`、`numbers_missing = 0`、`markers_missing = 0`、
   `citations_missing = 0`、`empty_targets = 0`；`numbers_added` 非 0 时 `verdict=review`，
   必须逐条回改或写入 `uncertainty` 说明（多半是模型自作主张补了原文没有的数字）。
   `citations_added` 仅作提示（目标语中的作者-年份写法可能误报），不改变 verdict。
   术语表为空、或术语一次都没在原文出现时，`locked_hit_rate` 为 `null` 并给 warning（review），
   不再以 `1.0` 假装全部命中；术语表路径不存在时脚本给出 `FAIL: glossary not found`（退出码 1）。
   `--bilingual` 接受 `{"segments":[...]}`、`{"segments":{id:{...}}}`、`[{...}]` 与 `{id:{...}}`。
7. **原文逐字核验**：把每段原文作为 `quote` 写成 `work/quotes.json`（**不要写到 `work/evidence.json`，
   那是 kernel 的索引文件，覆盖后 `verify` 会失败**）：
   `[{"claim":"P001 原文","source_path":"...","quote":"<原文片段>","locator":"p.1 para 1"}]`，
   然后 `python3 scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt --bilingual work/bilingual.json --out work/quote_check.json`。
   出现 `not_verbatim` 说明该段是模型补写而非原文，必须删除或改为原文。
   `--bilingual` 会核对"每个段号都有引文"：`segments_uncovered` 非空即 `verdict=review`；
   空 evidence（0 条引文）不再报告 `pass 0/0`；短于 12 字符的引文会标 `short_quotes`，无法证明逐字复用。
8. **数字/引用守恒**：把全部译文正文拼成 `work/target_only.txt`（不含段号，避免 `P001` 的数字被误判），
   `python3 scripts/kernel.py verify --text work/target_only.txt --evidence-dir work --out work`
   → `unsupported_numbers` 应为 0；共享 kernel 会把 `[3,5]`、`\cite{a,b}` 当整串检索而误报，
   **以第 6 步 `term_check.json` 的 `citations_missing` 为准**，误报写入 `self_check.citation_check_note`。
9. **产出**：写 `work/draft.json`（`fields` 对齐契约，`artifacts` 放 `translation.md`、
   `glossary.tsv`、`segment_alignment.csv`、`term_check.json`），执行
   `python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output`。
10. **收尾**：`python3 scripts/kernel.py check --out /app/output --contract-dir work` 必须 PASS；
    `status: partial` 时 `limits` 为空会 FAIL，契约字段为 null 也会 FAIL。

## 领域规则表（按题面四个关注点）

| 关注点 | 硬规则 | 反例（禁止） |
|-|-|-|
| 术语稳 | 全篇（标题/摘要/正文/图注/表格/结论）只用 `target_term`；首次出现写 `中文译名（English term, ABBR）`，其后用译名或缩写 | 摘要写"吸附"、正文写"吸着"、图注写"吸收" |
| 段落全 | 一段一 `id`，跨页续段合并、`span` 记页码范围；不合并不同小节、不把两段压成一段 | 漏掉跨栏末段；把 Methods 两段并成一段导致段号错位 |
| 关系准 | `may/might/could` → 可能/或许；`can` → 能够；`suggest` → 提示/表明；`demonstrate/show` → 证明/显示；**不得升级或削弱情态强度** | 原文 `may contribute` 译成"导致了" |
| 否定范围 | `not all X` → 并非所有 X；`no evidence of X` → 无证据表明 X（≠ 证明 X 不存在）；`neither ... nor` 保留双否定 | `not all samples` 译成"所有样本都不" |
| 数字 | 原样搬运，不四舍五入、不换算单位、不补有效数字；`±`、`~`、`<`、`n =`、范围写法保留 | `12.4%` 写成"约 12%"；`25 °C` 换成 `298 K` |
| 单位 | 保留国际符号原样（`mV`、`µg/L`、`kDa`），中文只加说明不改符号 | 把 `mV` 写成"毫伏"后又在表里写 `mV` |
| 公式 | 行内/行间公式照抄 LaTeX；变量符号不翻译；只译公式前后的文字 | 把 `k_{obs}` 改写成"观测速率常数 k" |
| 引用 | 编号引用 `[12]`、`[3,5]`、`\cite{key}`、作者-年份姓氏原样保留；只译"et al."为"等" | 把 `[12]` 重排成 `[1]`；把 `Smith et al., 2020` 译成"史密斯等，2020" |
| 图表编号 | `Figure 3` → `图 3`，`Table 2` → `表 2`，编号数字不变；表头逐项翻译并与原表列序一致 | `Figure 3` 译成"下图"；表头换序 |
| 可核验 | 每段译文能按 `id` 回指原文段落；译不准处保留原文并标注 `〔原文: ...〕`，同时进 `uncertainty` | 用模糊意译掩盖不懂的术语 |

## 硬性禁止

- 不删段、不并段、不重复段、不调整段序；不改写原文数字、单位、公式、引用编号与图表编号。
- 不改变限定与否定强度（`may` ≠ 会；`not all` ≠ 都不）；不把相关写成因果。
- 不补原文没有的句子、结论、数据或文献；不把图像/表格里的内容当成已读到的事实。
- 不把"术语表"写在提示里却不执行；出现变体译名必须回改，不得只在报告里承认。
- 不提交预制答案；所有产物必须由实际读取的输入推导。

## 输出

`/app/output/result.json`（`case_id`、`status`、`answer`、`structured`、`evidence`、`uncertainty`、`limits`，
字段以题面 `output_contract` 为准）+ 以下可编辑产物：

| 文件 | 内容 |
|-|-|
| `translation.md` | 双语对照：每段 `### P001 · p.1 para 1` → 原文引用块 + 译文；文末附术语表 |
| `glossary.tsv` | 锁定术语表（含来源标注 `given`/`auto`） |
| `segment_alignment.csv` | `id,section,page,span,source_chars,target_chars,terms_used` |
| `term_check.json` | 术语命中率、变体漂移、数字/编号/引用缺失明细 |

`structured` 至少包含：`segments_total`、`segments_translated`、`locked_hit_rate`、
`glossary_entries`、`check_summary`（六个零指标）、`artifacts`。

## 异常与降级

| 情况 | 处理 |
|-|-|
| PDF 无文字层/扫描件 | `kernel.py index` 标 `readable:false` 且 `reason: no_text_layer(...)`；有 OCR 工具时 OCR 后标注 `source: ocr` 与置信度；否则 `status: partial/blocked`，不猜内容 |
| 材料路径缺失/目录为空 | `index` 打印 `MISSING`、写 `missing_inputs` 并退出码 1；`limits` 说明缺哪些材料，不产出空译文 |
| `case.json` 非法 JSON / 顶层非对象 | `init` 写 `contract.json`（`status: blocked` + `error`）并退出码 1，不抛堆栈 |
| 文本编码非 UTF-8 | `index` 依次尝试 `utf-8-sig → utf-8 → gb18030`，`encoding` 记入索引；仍出现替换字符则标 `garbled_replacement_chars`，该段不得作为术语/数字依据 |
| 双栏错序、跨页断句 | 按语义与编号重排，`span` 记录页码范围，`changes` 记重排动作；无法确定处标 `〔顺序待确认〕` |
| 公式/表格为图片 | 保留占位 `〔公式图像: 图 3 位置〕` / `〔表格图像: 表 2〕`，进 `uncertainty`，不自行还原 |
| 参考文献无法解析 | 保留原始编号与字符串，只译正文；不补全作者或年份 |
| 原文语言混杂 | 逐段检测语言，非源语言段保留原文并标注，不强行翻译 |
| 术语表缺失或冲突 | 自行抽取并标 `glossary_source: auto`；同一 source 出现冲突 target 时脚本保留首个并写 `glossary_conflicts`（review），正文按保留项执行，另一项进 `uncertainty` |
| 超预算（64 请求/900s） | 先译方法与结果主段并落盘，`status: partial`，`limits` 列出未译段号 |
| 原文残缺 | 只译可读部分，`limits` 写清缺页/缺段，不用常识补全 |

## 文件说明

- `scripts/kernel.py`：`init / index / verify / emit / check`（仅标准库）。
- `scripts/quote_check.py`：逐字核验每段原文确实存在于 `corpus.txt`，防止补写。
- `scripts/term_consistency.py`：术语锁定命中率、变体漂移、数字/图表编号/引用保真检查。
- `references/translation-fidelity.md`：术语、情态、否定、数字单位、公式引用的规则与反例。
- `references/glossary-alignment.md`：术语表格式、段号与双语对照约定、未译标注规则。
- `references/output-contract.md`：默认输出字段；题面契约优先。

## 最小调用示例（示例，不是正式案例结果）

```bash
python3 scripts/kernel.py init --case /input/case.json --out work
python3 scripts/kernel.py index --case /input/case.json --materials /input/materials --out work
# 人工/模型按第 3–5 步生成 work/segments.json、work/glossary.tsv、work/bilingual.json
python3 scripts/term_consistency.py --glossary work/glossary.tsv --bilingual work/bilingual.json --out work/term_check.json
python3 scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt --bilingual work/bilingual.json --out work/quote_check.json
python3 scripts/kernel.py verify --text work/target_only.txt --evidence-dir work --out work
python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output
python3 scripts/kernel.py check --out /app/output --contract-dir work
```

示意输出（片段）：`P001` 原文 `Sorption of Pb(II) reached 12.4% at 25 °C [12].` →
译文 `Pb(II) 的吸附（sorption）在 25 °C 时达到 12.4% [12]。`，
`term_check.json` 报 `verdict=pass, locked_hit_rate=1.0, counts 全 0`。

## 变更记录

| 版本 | 变更 | 触发缺陷（本地合成夹具复现） |
|-|-|-|
| 1.2.0 | `term_consistency` 标记比对改大小写无关；新增 `第N节/第N章` 识别且与 `Section N` 同步剥离；上标指数归一 | 正确译法 `Figure 3A → 图 3a` 被判 `markers_missing fig3A`；`Section 2 → 第 2 节` 同时报 `markers_missing sec2` 与 `numbers_added '2'`；`10-4 → 10⁻⁴` 被判丢数字 |
| 1.2.0 | 术语表按 `utf-8-sig` 读取并去 BOM；同一 source 冲突 target 时保留首个并写 `glossary_conflicts`（review） | 带 BOM 且无表头的术语表把首词读成 `\ufeffsorption`，`occurrences=0` 却 `locked_hit_rate=1.000, pass`；重复冲突词条静默覆盖成 `吸附→吸着`，产生 3 条假 `missing_locked` |
| 1.2.0 | `term_consistency` 无命中时 `locked_hit_rate=null` + warning；坏 JSON 给 `FAIL` 退出码 1 | 0 次命中显示 100% 锁定；`bilingual.json` 截断抛 `JSONDecodeError` 栈 |
| 1.2.0 | `quote_check` 坏 JSON 干净失败、非对象条目记 `bad_entry`；`--bilingual` 坏文件不再影响主流程 | `quotes.json` 截断抛栈；`["P001 source"]` 抛 `AttributeError: 'str' object has no attribute 'get'` |
| 1.2.0 | `kernel` 无文本层 PDF 判 `readable:false+reason`；文本 `utf-8→gb18030` 回退并记 `encoding`；`index` 支持 `--case` 解析相对路径、全缺失/全不可读退出 1；`init` 捕获坏 JSON/非对象；`verify` 容忍缺失 `evidence.json`；`check` 捕获坏 `result.json` | 纯图形 PDF `readable=true chars=0`；GBK 材料解出替换字符仍 pass；`materials/...` 相对路径从 `/app/work` 运行必然 0 文件；`case.json` 截断/`[]` 抛栈；删掉 `evidence.json` 后 `verify` 抛 `FileNotFoundError` |
| 1.2.0 | 文档命令统一 `python3` | 原文所有示例为 `python scripts/...`，镜像内不保证 `python` 存在 |
| 1.1.0 | `numbers_added` 纳入 verdict（review 级）；空术语表/空段集给出 warning 并 review | 译文 P004 凭空多出"50 次"，`term_consistency` 仍 `verdict=pass`；表头-only 术语表报 `glossary_entries=0, locked_hit_rate=1.0, verdict=pass` |
| 1.1.0 | `term_consistency` 术语表缺失给出 `FAIL: glossary not found`（退出码 1），bilingual 支持四种形态 | 路径写错时抛 `FileNotFoundError` 栈；`{id:{...}}` 形态抛 `AttributeError: 'str' object has no attribute 'get'` |
| 1.1.0 | `quote_check` 新增 `--bilingual` 段号覆盖核对；0 条引文不再 pass；短引文标记 | 5 段只给 3 条引文、甚至 `[]` 空引文，都报 `verdict=pass failed=0/…`，漏段无法被发现 |
| 1.1.0 | `kernel.verify` 数值改整词比对；`emit` 支持数组契约、缺字段返回非零；`check` 增加 `--contract-dir` 与 partial limits 校验 | 与写作题同源缺陷：子串数值漏检、契约字段丢失仍 PASS |
