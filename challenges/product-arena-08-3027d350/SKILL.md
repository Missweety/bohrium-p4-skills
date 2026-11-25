---
name: paper-structure-parser
description: 把科研 PDF/DOCX 还原为带页码与区块定位的结构化文档：章节树（多级编号）、正文段落、表注与表格 CSV、图注、公式编号、参考文献、页眉页脚与脚注分离。适用于"解析这篇论文/还原版面结构/提取章节与表格/为引用取证"；扫描件无文本层时明确标记 unreadable 并给替代路径，不用领域常识补写缺失内容。不适用于仅需摘要式总结、或只需图内数值读数（后者见图表解析类 Skill）。
version: 1.1.0
license: MIT
---

# 文献文档解析：先建定位图，再逐字落盘

把"解析一篇论文"拆成 **文本层体检 → 区块与页码定位表 → 章节树 → 表格/图注/公式/参考文献结构化 → 逐字引文核验 → 交付**。
核心主张：结果里每一个段落、每一行表格、每一条参考文献都要能指回 `file + page + block_id`；指不回去的，
只能标 `unreadable` 或降级，绝不用领域常识补全。

## 何时使用

触发：用户给出科研 PDF（含扫描版）/DOCX/论文原文，要求"解析全文结构"、"还原章节层级与编号"、
"把表格转成 CSV"、"提取图注/公式/参考文献"、"给出可引用的页码定位"、"翻译或问答前的原文整理"。

不触发：只要一段摘要或结论概括（走文献总结/问答类 Skill）；只要读图中数据点与坐标轴
（走 `figure-evidence-reader`）；没有材料、要求凭记忆综述某领域。遇到这类请求先说明缺口，
再决定是否只做其中可做的部分。

## 输入

`/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`；材料按题面提供，
PDF 是**未预抽取的原始 PDF**。字段名不固定，**不要凭文件名、标签或 DOI 假设论文内容**，
先 `kernel.py init` 做宽松识别，再以实际抽出的文本为准。

材料路径可以是相对 `case.json` 的路径（平台常见写法 `"materials": ["materials/paper.pdf"]`）。
`kernel.py index --case /input/case.json` 会按"当前目录 → case.json 所在目录 → `contract.json` 记录的
case 目录 → `/input`"依次解析，避免从 `/app/work` 运行时把相对路径当缺失、静默产出 0 个文件。

## 执行流程

1. **契约**：`python3 scripts/kernel.py init --case /input/case.json --out work`
   → `work/contract.json`（case_id、output_contract、task 原文、materials）。题面契约字段一个都不能少。
   case.json 非法 JSON 或顶层不是对象时，写 `contract.json`（`status: blocked` + `error`）并以退出码 1 结束，
   不再抛 Python 堆栈。
2. **抽取与索引**：`python3 scripts/kernel.py index --case /input/case.json --materials <材料路径...> --out work`
   → `work/evidence.json`（文件清单、sha1、可读性、reason、encoding）+ `work/corpus.txt`（统一文本）。
   PDF 走 `pdftotext -layout`，空或失败退 `pypdf`；两者都抽不出 → 该文件 `readable: false`、
   `reason: no_text_layer(...)`，**不会**以 `chars=0, readable=true` 冒充解析成功。
   文本文件按 `utf-8 → gb18030` 依次试解，`encoding` 记入索引；出现替换字符标 `garbled_replacement_chars`。
   材料全部缺失/全部不可读时以退出码 1 报 `BLOCKED`，绝不静默继续。
3. **文本层体检**：`python3 scripts/doc_structure.py --input work/corpus.txt --out work`
   → `work/sections.json`（章节树 + `documents[]`）、`work/locator_table.csv`（逐块定位表）、
   `work/structure_stats.json`、`work/structure.md`（可读大纲，供人工核对）。
   先看 stats 的三个数：`pages`、`pages_without_text`、`multi_column_signal`。
   `pages_without_text / pages ≥ 0.6` 判为扫描件，进入降级路径（见异常表），**不要假装解析成功**。
4. **校正定位表**：逐页抽查 `locator_table.csv` 的 `type`（heading / body / caption / equation /
   footnote / reference / furniture / unreadable）。误判（如把 "2.1 mM NaCl" 当二级标题）改回 `body`，
   在 `changes` 记录 `{target, before, after, reason}`。
5. **表格结构化**：对各 `Table N` 题注后的块，整理为 `work/tables/table_<n>.csv`：
   首行为表头（多层表头用 `header_rows: 2` 记在 `tables[]`）、合并单元格写 `spans`、
   跨页续表写 `continued_from: table_<n>_p<k>`。还原不出的单元格留空并在 `table_notes` 说明，
   **不得按常识填数**。
6. **图注 / 公式 / 参考文献**：图注逐字保留（含 (a)(b) 子图标记）；公式保留原文 Unicode 符号
   （²、⁻¹、α、Δ）与右侧编号，不臆造 LaTeX；参考文献按条目原样，缺卷期页就留空字段。
7. **证据装配与逐字核验**：把 claim—原文对写进 `work/quotes.json`（`[{claim, source_path, page,
   block_id, quote}]`；注意 `work/evidence.json` 是第 2 步的索引文件，两者不要混用），quote 必须是
   `corpus.txt` 中的原样片段（`--min-len` 默认 12，过短的引文无法证明逐字复用，会被判 `short_quote`）；
   然后
   `python3 scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt --out work/quote_check.json`
   必须 `verdict=pass`；0 条引文也会判 `review`（"什么都没核"不等于通过）。不通过就改 quote 或降级
   该 claim，不许"改到能匹配"而篡改原文。
8. **守恒与产出**：`python3 scripts/kernel.py verify --text work/summary.md --evidence-dir work --out work`
   → `unsupported_numbers` 应为 0（数值按整词比对，`20` 不会被 `120` 蒙混通过；论文自带的页码/编号
   可先在 corpus 中确认存在）；写 `work/draft.json`（字段见 `references/output-contract.md`），
   `python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output`，
   再 `python3 scripts/kernel.py check --out /app/output --contract-dir work`，必须 PASS。

## 领域规则（按评分维度对齐）

| 维度 | 规则 |
|-|-|
| 提得全 | 正文、题注、脚注、参考文献逐块抽取；在**同一文件**内 ≥60% 页面首/尾 2 行重复的短行判为页眉页脚，标 `furniture` 且不计入正文（按文件统计：多份材料同跑不会互相稀释页眉计数）；脚注保留为 `type: footnote` 并挂在所在页 |
| 排得对 | 优先信任 `pdftotext -layout` 的视觉行序；某页行内含 ≥3 个连续空格（跨栏空隙）比例高时，`multi_column_signal` 上升，该页各块标 `reading_order_confidence: low` 并进 `uncertainty`；跨页续接段落用 `continued: true` 标记，不强行合并成一句；`page` 按文件从 1 起，跨文件顺序看 `page_global` |
| 拆得清 | 章节编号原样保留（`1.2.3` 不重排、不补父级）；表格行=记录、列=字段、合并单元格写 `spans`；公式按编号索引，保留上下标原始字符；`References` 之后的条目才标 `reference`，不跨文件泄漏 |
| 核得回 | 每个 block 必有 `file` + `page` + `block_id`（如 `B0042`）；`evidence[]` 只允许逐字 quote，`block_id` 必须存在于 `locator_table.csv`（`check` 会交叉核对）；结论里出现页码时必须是解析出的真实页 |
| 不补写 | 缺页、乱码、OCR 缺字处写 `[unreadable p.N]` 或 `?`，乱码块标 `garbled: true`；作者、单位、DOI、样本量缺就留空并进 `uncertainty`，不得用论文印象补 |

## 硬性禁止

- 不输出"看起来像全文"的连续大段文本而丢掉分块与页码——那无法复核。
- 不把页眉、页脚、页码、边注混进正文段落。
- 不用领域常识补缺失段落、作者、单位、参考文献条目或表格数值。
- 不把"抽不出文本"写成"论文未提及"；这是两种不同的结论。
- 不伪造解析器版本、页数、OCR 结果或评测分数。
- 不提交预制答案；所有产物必须由本次实际读取的输入推导。

## 输出

`/app/output/result.json`（`case_id`、`status`、`answer`、`structured`、`evidence`、`uncertainty`、`limits`；
契约字段见 `references/output-contract.md`，题面 `output_contract` 优先），并落盘：
`sections.json`（章节树）、`locator_table.csv`（页码/区块定位表）、`tables/table_<n>.csv`、
`structure.md`（可读大纲）。中间件放 `/app/work`。

`emit` 会把契约里的每个字段名都当成结果顶层键；契约写成数组（`["answer","structured","evidence"]`）
时同样逐个填充，缺字段会打印 `missing_contract_fields=[...]` 并返回退出码 1。

`status` 取值：`ok`（文本层完整且结构可还原）、`partial`（部分页/表/公式不可读，已标注）、
`blocked`（无文本层且无法降级，或材料缺失）、`refused`（请求超出材料范围）。
`partial`/`blocked` 必须写非空 `limits`，否则 `check` 判 FAIL。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 扫描版无文本层 | `index` 记 `readable:false, reason:no_text_layer(...)`；`status: partial`；`structured.unreadable_pages` 列全部页号；`answer` 只声明"无可抽取文本层"，给替代路径：①提供可读版 PDF/OCR 结果 ②仅基于图注与题面可见文字作答 ③按题面允许则人工核对；不逐页猜测文字 |
| PDF 加密/损坏 | 记录 `error` 摘要与 `reason`；`blocked`；列出已成功解析的页（若有） |
| case.json 非法/非对象 | `init` 写 `contract.json`（status=blocked + error）并退出码 1，不抛堆栈 |
| 材料路径缺失/为空 | `index` 打印 `MISSING ...`、写 `missing_inputs`、退出码 1；`limits` 说明缺哪些材料，不产出空成功结果 |
| 乱码字体（ToUnicode 缺失） | `index` 标 `garbled_replacement_chars`；`doc_structure` 给 `garbled: true` 并统计 `garbled_pages`，该块不参与结论；提示需 OCR 或原始文件 |
| 双栏串行 / 阅读顺序可疑 | 降低该页 `reading_order_confidence`，把可疑块写进 `uncertainty`，并在 `answer` 说明哪些页存在顺序风险 |
| 表格跨页 / 合并单元格 | 拆成两张 CSV 用 `continued_from` 关联；合并单元格写 `spans`，无法判定归属则整行标 `uncertain` |
| 图片型表格（无文本） | 不输出数值；标 `table_<n>: image_only`，给需要原图/可读版的说明 |
| 预算不足（64 请求 / 900s / 16k tokens） | 先落盘已完成的章节与定位表，`status: partial`，`limits` 列出未处理页段 |
| python / pdftotext 不可用 | `reason` 会写明 `pdftotext_missing`/`pypdf_error`；手工逐页读取并在 `limits` 说明降级方式；不因此编造页码 |

## 文件说明

- `scripts/kernel.py`：init / index / verify / emit / check 五个子命令，仅标准库（PDF 走系统 pdftotext 或 pypdf）。
  `index` 支持 `--case` 解析相对材料路径；`check` 支持 `--contract-dir` / `--work-dir`，交叉核对契约字段、
  `partial` 的 `limits`、`evidence[].block_id` 与 `tables[].csv_path`。
- `scripts/doc_structure.py`：按文件分页、按文件识别页眉页脚、按文件重置 `References` 状态，
  输出章节树、逐块定位表、`structure.md`。
- `scripts/quote_check.py`：逐条核验引文是否与原文逐字一致（容忍连字、软连字符、换行）；空列表与过短引文判 review。
- `references/output-contract.md`：默认输出字段；题面契约优先。
- `references/pdf-structure-map.md`：结构元素清单、判别规则与反例。
- `references/example.md`：一组示意输入/输出（示例，不是正式案例答案）。

## 最小调用示例

```bash
python3 scripts/kernel.py init --case /input/case.json --out work
python3 scripts/kernel.py index --case /input/case.json --materials /input/materials --out work
python3 scripts/doc_structure.py --input work/corpus.txt --out work
# 依据 work/locator_table.csv 校正后写 work/sections_curated.json 与 work/tables/*.csv
python3 scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt --out work/quote_check.json
python3 scripts/kernel.py verify --text work/summary.md --evidence-dir work --out work
python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output
python3 scripts/kernel.py check --out /app/output --contract-dir work
```

示意输出（节选自 `references/example.md`，非正式案例结果）：

```json
{"case_id":"demo-doc-1","status":"partial",
 "structured":{"sections":[{"number":"2.1","title":"Materials","level":2,"page_start":2,"block_id":"B0017"}],
               "unreadable_pages":[7]},
 "evidence":[{"claim":"section 2.1 heading","source_path":"materials/paper.pdf","page":2,
              "block_id":"B0017","quote":"2.1 Materials"}]}
```

## 变更记录

| 版本 | 改动 | 触发缺陷（本地合成夹具真实复现） |
|-|-|-|
| 1.1.0 | `doc_structure` 页眉页脚改为**按文件**统计（阈值 `max(2, ceil(0.6×该文件页数))`）；`page` 按文件从 1 起并新增 `page_global`；`References` 状态按文件重置 | 两份材料（3 页 + 1 页）同跑时 `furniture_patterns=[]`，页眉被并入正文块 `B0003`（"…limits. Journal of Demo Chemistry 2024…"）；另一文件正文被误标 `reference`；页码变成 `p5/p6` 无法指回原 PDF |
| 1.1.0 | `kernel.index` 无文本层 PDF 判 `readable:false + reason`；文本编码回退 `utf-8→gb18030` 并记 `encoding`；不再用 `startswith("[")` 判定可读 | 纯图形 PDF：`ok chars=0`、`unreadable=[]`，被当成解析成功；GBK 材料解出 `���Ĳ���` 仍 `readable:true`；以 `[1] Smith…` 开头的 md 被误判不可读 |
| 1.1.0 | `kernel.index` 缺材料写 `missing_inputs` 并退出 1；新增 `--case` 解析相对材料路径 | 材料目录不存在时静默 `files: []` + 退出 0，后续产出空成功结果；从 `/app/work` 用相对路径必然 0 文件 |
| 1.1.0 | `kernel.init` 捕获非法 JSON / 顶层非对象，写 blocked 契约 | `case.json` 截断 → `JSONDecodeError` 堆栈；`[]` → `AttributeError: 'list' object has no attribute 'keys'` |
| 1.1.0 | `kernel.verify` 数值改整词比对，`review` 返回 1 | 原文 `120 min`，草稿写 `20 min` 仍 `verdict=pass`（子串命中） |
| 1.1.0 | `kernel.emit` 支持数组契约、缺字段退出 1；`check` 支持 `--contract-dir`/`--work-dir` 并核对契约字段、`partial` 的 `limits`、`evidence[].block_id`、`tables[].csv_path` | 契约 `["answer","structured","evidence"]` 时结果只剩 `fields` 键且 `missing_contract_fields=none`；`return 0 if not missing else 0` 永远 0；`partial` 空 `limits`、伪造 `B9999` 仍 PASS |
| 1.1.0 | `quote_check` 空列表判 review、短引文标 `short_quote`；支持 `{evidence|quotes|items}` | 0 条引文报 `pass 0/0`；3 字引文"能搜到"就 pass |
| 1.1.0 | `doc_structure` 生成 `structure.md`；输入缺失返回码 2；文档命令统一 `python3` | SKILL 承诺 `structure.md` 但无脚本产出；corpus 不存在时抛 `FileNotFoundError` |
