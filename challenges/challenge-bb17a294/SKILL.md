---
name: bilingual-academic-translator
description: 把给定中英文科研材料按锁定术语表双向译为可核验的双语对照稿：先建段号与术语表，再按段翻译并在译文中守恒情态强度、否定范围、数字单位、公式、引用与图表编号，最后用脚本逐段核对并用逐字引文检查防止补写。用于论文全文或指定段落的翻译、双语对照排版与译文审校；不用于无原文的创作、摘要代写、纯语言润色或凭空补数据。
version: 1.2.0
license: MIT
---

# 学术翻译与双语写作：术语锁定、段号对齐、限定强度守恒

把"翻译一篇论文"拆成 **段落索引 → 双向术语表锁定 → 逐段翻译（带上下文与语域）→ 三重核验 → 双语交付**。
核心主张：术语是全篇硬约束；段号是主键，一段都不能少、不能重、不能错位；数字、单位、公式、引用与
图表编号是保护区；`may / might / 可能 / 提示` 的强度是科学结论的一部分，译文只能等强。

## 何时使用

触发：用户给出论文原文（pdf/docx/tex/md/txt/图片 OCR 结果），要求译成中文或英文、要求"双语对照"、
"逐段对照排版"、"统一术语译名"、"校对译文是否漏段/改数/改口径"、"按段落续译长文"、"按中文期刊或
英文期刊体例排版译文"。

不触发：没有原文、要求直接写出译文或摘要（缺材料时只能说明缺什么）；只做语言润色且不需要对照原文；
只做文献总结/结构化笔记；要求联网查证术语标准译法（本 Skill 只在给定材料与自建术语表内工作，术语来源
必须写清）；要求把未发表数据写进译文。

## 输入

`/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`；材料由题面提供。
字段名不固定，**先读真实文件**，不要凭标签猜内容：

| 语义 | 常见字段/文件 |
|-|-|
| 原文 | `source_text`, `text`, `paper`, 正文 pdf/docx/tex/md |
| 目标语言 | `target_language`, `language`, `lang`（缺省按"中→英 或 英→中"反向推断） |
| 术语表 | `glossary`, `terms.tsv`, 用户随材料给出的词表 |
| 期刊体例 | `journal_style`, `style_guide`, `template`（中文期刊/英文期刊二选一，未给则按通用体例） |
| 输出契约 | `output_contract` |
| 案例标识 | `case_id` |

术语表统一转成 **5 列 TSV**（制表符分隔，`#` 开头为注释），中英两侧同时锁定：

```
zh_term	en_term	code	banned_zh	banned_en
吸附	sorption		吸着|吸收	absorption
固相萃取	solid-phase extraction	SPE	固相提取	SPE extraction
```

`code` 可空；`banned_zh` / `banned_en` 用 `|` 分隔，表示该语向**禁止出现的旧译/错译**（4 列文件只填
`banned_zh` 一列，脚本把变体按"目标侧"处理）。术语表由材料或用户提供时原样继承；没有术语表时按第 4 步
自行抽取并在 `uncertainty` 标注 `glossary_source: auto`。

## 平台运行路径（必须遵守）

平台把本 Skill 装到 `/skills/weekly-skill`，命令的工作目录是 `/app`，**不在 Skill 根目录**。
所有脚本必须用绝对路径调用，否则 `python scripts/kernel.py` 会因找不到文件直接失败：

```bash
SKILL_DIR=/skills/weekly-skill
python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out /app/work
```

材料在 `/input/materials`，产物写 `/app/output`。

## 执行流程（严格按序）

1. **契约**：`python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out work`
   → `work/contract.json`。确认语向、翻译范围（全文/段落区间）、期刊体例与 `output_contract` 字段。
2. **证据索引**：`python3 "$SKILL_DIR/scripts/kernel.py" index --materials <材料路径...> --out work`
   → `work/evidence.json` + `work/corpus.txt`。不可读文件标 `unreadable`，**不得按领域常识补写原文**。
3. **段落切分**：建 `work/segments.json`，一段一条：

   ```json
   {"id":"P001","section":"Abstract","page":1,"span":"p.1","text":"...","kind":"body"}
   ```

   规则：`id` 按阅读顺序连续编号（正文 `P`、标题 `H`、图注 `C`、表注 `T`、脚注 `N`、文献 `R`）；
   跨页/跨栏被折断的同一段**合并为一条**并在 `span` 记 `p.3-4`；标题、图题、表题、脚注各自独立；
   参考文献条目按 `R001` 起编号，不参与正文翻译但保留编号与原位。
4. **术语锁定（双向）**：优先用给定术语表；缺省时从 `corpus.txt` 抽取高频领域名词/复合名词（多词短语
   优先），写入 `work/glossary.tsv` 并标来源（`given`/`auto`）。同一概念只允许一个译名；同义原文
   （`sorption` / `adsorption`）要么合并，要么在 `uncertainty` 写区分依据。学科歧义词（如 `cell`）
   必须按本题学科定一条译名，另一义写进 `banned`。
5. **逐段翻译**：每段携带三样上下文——本节标题、上一段原文末句与译文末句、当前锁定术语表；同时按
   第 7 节的语域规则选体例。输出 `work/bilingual.json`：

   ```json
   {"segments":[{"id":"P001","section":"Abstract","locator":"p.1 para 1",
     "source":"...","target":"...","terms_used":["sorption"]}]}
   ```

   长文按章节分批，每批译完立刻落盘（预算 900s，先保完整再打磨）；**不要等全文译完再写**。
6. **保真核验**：
   `python3 "$SKILL_DIR/scripts/bidir_consistency.py" --glossary work/glossary.tsv --bilingual work/bilingual.json --out work/fidelity_check.json`
   要求 `missing_locked`、`variant_drift`、`numbers_missing`、`numbers_added`、`units_missing`、
   `markers_missing`、`citations_missing`、`empty_targets` 全为 0；`citations_added` 多为模型补引，
   必须删除。`glossary_unused` 只提示未用到的术语，不算错误。
7. **强度与语域核验**：
   `python3 "$SKILL_DIR/scripts/modality_register.py" --bilingual work/bilingual.json --out work/modality_check.json`
   要求 `strength_flags=0`、`promotional=0`、`colloquial=0`。每一处 `strength_changed` 都要回改，
   不允许"在报告里承认、正文不改"。
8. **原文逐字核验**：把每段原文作为 `quote` 写入 `work/quotes.json`
   （`[{"claim":"P001 原文","source_path":"...","quote":"<原文片段>","locator":"p.1 para 1"}]`），
   `python3 "$SKILL_DIR/scripts/quote_check.py" --evidence work/quotes.json --corpus work/corpus.txt --out work/quote_check.json`。
   `not_verbatim` 说明该段是补写而非原文，必须删除或改回原文。
9. **数字/引用守恒**：把译文正文拼成 `work/target_only.txt`（不含段号，避免 `P001` 被误判），
   `python3 "$SKILL_DIR/scripts/kernel.py" verify --text work/target_only.txt --evidence-dir work --out work`。
   `unsupported_numbers` 应为 0；共享 kernel 会把 `[3,5]`、`\cite{a,b}` 当整串检索而误报，
   **以第 6 步 `fidelity_check.json` 的计数为准**，误报写入 `self_check.citation_check_note`。
10. **产出**：写 `work/draft.json`（`fields` 对齐契约，`artifacts` 放 `translation.md`、`bilingual.csv`、
    `glossary.tsv`、`fidelity_check.json`），再
    `python3 "$SKILL_DIR/scripts/kernel.py" emit --draft work/draft.json --contract-dir work --out /app/output`。
11. **收尾**：`python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract-dir /app/work` 必须 PASS；`status: partial` 必须写 `limits`。
    `check` 会核对 `source_map`/`uncertainty` 两个必填数组字段是否存在且为数组；`changes` 为可选字段
    （见 `references/output-contract.md`），缺省不报错，存在时校验其为对象数组且每项非空。`ok/success`
    时还会核对 `translation.md`/`bilingual.csv`/`glossary.tsv`/`fidelity_check.json` 四个工件是否落盘且非空。

## 领域规则表

### 4.1 术语与段对齐

| 规则 | 硬要求 | 反例（禁止） |
|-|-|-|
| 术语稳 | 标题/摘要/正文/图注/表格/脚注/结论只用锁定译名；首次出现写 `中文译名（English term, ABBR）`，其后用译名或缩写 | 摘要"吸附"、正文"吸着"、图注"吸收" |
| 缩写 | 首次出现给全称＋缩写，此后统一用缩写；不得同一缩写在两处指不同概念 | `SPE` 一处指固相萃取、一处指固态电解质 |
| 段对齐 | 一段一 `id`；`bilingual.json` 的 `id` 集合与 `segments.json` 完全一致，顺序一致 | 漏掉跨栏末段；把 Methods 两段并成一段导致段号错位 |
| 图表题注 | 题注独立成段并与正文引用编号一致；`Figure 3`→`图 3`，`Table 2`→`表 2`，`Fig. 3A`→`图 3A` | `Figure 3` 译成"下图"；题注与正文编号各说一套 |
| 文献条目 | 参考文献按 `R` 编号原位保留；只译必要的标题说明，作者、年份、卷页、DOI 原样 | 重排文献顺序、删掉 DOI、把作者名译成中文 |

### 4.2 数字、单位与公式

| 规则 | 硬要求 | 反例（禁止） |
|-|-|-|
| 数字 | 逐字符搬运；不四舍五入、不补有效数字、不改写范围与 `±`、`<`、`~`、`n =` | `12.4%`→"约 12%"；`n = 24`→"24 例" |
| 中英数量级 | `万/亿` 与 `thousand/million/billion` 可换算，但必须**原值＋括注**并保持数值一致：`1.2 万`→`1.2 × 10^4 (12,000)` 或 `12,000 (1.2 万)` | 把 `1.2 万` 直接写成 `1.2 million` |
| 单位 | 国际符号原样：`mV`、`µg/L`、`kDa`、`°C`、`mol/L`；不在正文做单位换算 | `25 °C` 换成 `298 K`；`µg` 写成 `ug` |
| 公式 | 行内/行间公式照抄 LaTeX，变量符号不翻译，只译公式前后文字；编号 `(1)` 保留 | 把 `k_{obs}` 改写成"观测速率常数 k" |
| 表格 | 表头逐列翻译且列序不变；数值不重排、不补零、不统一小数位；`–`（未测）与 `0` 区分 | 表头换序、把未测写成 0 |

### 4.3 语义边界（限定强度与否定）

| 原文 | 允许 | 禁止 | 原因 |
|-|-|-|-|
| `may / might / could` / 可能、或许 | 可能、或许、有望 / may, might, could | 会、导致、证明 / demonstrate, prove, cause | 可能性被写成事实 |
| `suggest / indicate` / 提示、表明 | 提示、表明、显示 / suggest, indicate | 证明、证实 / prove, confirm | 证据强度被抬高 |
| `demonstrate / show` / 证明、证实 | 显示、证明 / demonstrate, show | 可能、或许 / may, might | 强度被削弱 |
| `is associated with` / 与…相关 | 与……相关 / be associated with | 导致、引起 / cause, lead to | 相关被写成因果 |
| `consistent with` / 与…一致 | 与……一致 / be consistent with | 证明了 / prove | 一致性被写成确证 |
| `not all` / 并非所有 | 并非所有、不是所有 / not all | 所有都不 / none of | 否定作用域翻转 |
| `no evidence of X` / 无证据 | 无证据表明 X / no evidence of X | 证明 X 不存在 / prove absence | 无证据≠反证 |
| `up to` / 最高可达 | 最高可达、至多 / up to | 达到 / reach | 上限被写成实测值 |
| `approximately / ~` / 约 | 约、大约 / approximately | 删除 | 精度被拔高 |
| `neither A nor B` / 既不…也不 | 既非 A 也非 B / neither … nor | 不是 A 或 B / not A or B | 双否定被拆成单否定 |

### 4.4 引用与期刊语域

| 项目 | 中文期刊体例（默认） | 英文期刊体例（默认） | 反例 |
|-|-|-|-|
| 引用标记 | 保留原文编号或作者-年份；`Smith et al., 2020`→`Smith 等，2020` | 保留 `[12]`、`[3,5]`、`\cite{key}`、`(Smith et al., 2020)` 原样 | 重排编号、把 `et al.` 译成 `etc.` |
| 标点 | 中文全角标点；数字与单位之间留半角空格 | 英文半角标点；`Fig. 3` 用句点缩写 | 中文正文用英文逗号、英文正文用全角逗号 |
| 人称与语气 | 少用"我们"，方法用"本研究/本文"；避免口语与宣传语 | 可用 `we`，但避免 `we feel`、`a lot of`、`huge` | 中文摘要写"我们搞定了"，英文写"world-leading" |
| 句长 | 长英文句可拆，但不得丢失限定成分；拆句记 `source_sentence` | 中文长句可合并短句，但不得新增因果/递进 | 合并后凭空多出"因此" |
| 时态/体 | 中文用"了/已/将"区分已完成与拟开展 | 方法与结果用过去时，结论用现在时，全篇统一 | 结果段混用现在时与过去时 |

## 硬性禁止

- 不删段、不并段、不重复段、不调整段序；不改写原文数字、单位、公式、引用编号与图表编号。
- 不改变限定与否定强度（`may` ≠ 会；`not all` ≠ 都不）；不把相关写成因果。
- 不补原文没有的句子、结论、数据或文献；不把图像/表格里的内容当成已读到的事实。
- 不把术语表写在提示里却不执行；出现变体译名必须回改正文，不得只报告。
- 不把学术表述改成宣传口吻（"国际领先""填补空白"）或口语（"很多""搞定"）。
- 不提交预制答案；所有产物必须由实际读取的输入推导。

## 输出

`/app/output/result.json`（`case_id`、`status`、`artifact_path`＝`translation.md`、`artifact_format`、
`source_map`、`changes`、`uncertainty`、`limits`、`self_check`；若题面 `output_contract` 要求
`answer`/`structured`，同时回填）+ 以下可编辑产物：

| 文件 | 内容 |
|-|-|
| `translation.md` | 双语对照：每段 `### P001 · p.1 para 1` → 原文引用块 + 译文；文末附术语表与体例声明 |
| `bilingual.csv` | `id,section,span,source,target,terms_used`，可直接进 CAT/TMX 流程 |
| `glossary.tsv` | 双向锁定术语表（含来源标注 `given`/`auto`） |
| `fidelity_check.json` | 术语命中率、变体漂移、数字/单位/编号/引用缺失明细 |
| `modality_check.json` | 强度、否定、宣传语与口语化告警 |

`structured` 至少包含：`direction`（zh2en/en2zh/mixed）、`segments_total`、`segments_translated`、
`locked_hit_rate`、`glossary_entries`、`check_summary`（关键计数）、`artifacts`。

输出形态按题面选择：**纯译文**（`translation.md` 只放译文）、**双语对照**（默认，段号＋原文＋译文）、
**带修订标记**（`bilingual.csv` 提供 `source,target`，或在对照稿中用 `~~原文~~ → 译文` 标出改动）。
题面未指定时用双语对照。

## 异常与降级

| 情况 | 处理 |
|-|-|
| PDF 无文字层/扫描件 | `kernel.py index` 标 `unreadable`；有 OCR 时标注 `source: ocr` 与置信度，否则 `partial/blocked`，不猜内容 |
| 双栏错序、跨页断句 | 按语义与编号重排，`span` 记页码范围，`changes` 记重排动作；不确定处标 `〔顺序待确认〕` |
| 公式/表格为图片 | 保留占位 `〔公式图像: 图 3 位置〕` / `〔表格图像: 表 2〕`，进 `uncertainty`，不自行还原 |
| 参考文献无法解析 | 保留原始编号与字符串，只译正文；不补全作者、年份或 DOI |
| 原文语言混杂 | 逐段判断语向，非源语言段保留原文并标注，不强行翻译 |
| 术语表缺失或冲突 | 自行抽取并标 `glossary_source: auto`；两套译名并列写入 `uncertainty`，正文按一套执行 |
| 术语表给的是单语词表 | 按学科习惯补另一侧译名，写入 `glossary.tsv` 并标 `auto`，不假装是给定译名 |
| 目标语向无法判断 | 按首段 CJK 占比判定，混合语料逐段判定并在 `structured.direction` 写 `mixed` |
| 输入编码错误 | 用 `errors="replace"` 读取并在 `uncertainty` 记乱码位置；无法修复的段保留原文 |
| 超预算（64 请求/900s） | 先译方法与结果主段并落盘，`status: partial`，`limits` 列出未译段号 |
| `bilingual.json` 非法 JSON / 不是段数组 | `bidir_consistency.py`、`modality_register.py` 打印 `FAIL: bilingual JSON invalid: …` 并退出 2（原为 `JSONDecodeError` 裸栈） |
| 术语表文件不存在 / 编码非 UTF-8 | `bidir_consistency.py` 报 `FAIL: glossary missing: …` 退出 2；GBK 术语表按 gb18030 解码 |
| 证据 JSON 非法或不是列表 | `quote_check.py` 报 `FAIL: evidence JSON invalid: …` / `evidence must be a list …`，退出 2 |
| PDF 连字符断词（`experi-\nmental`） | `quote_check.norm()` 先合并行末连字符再比对，避免逐字一致的引文被判 `not_verbatim` |
| 语料为 GBK/GB18030 | `quote_check.read_text()` 依次尝试 utf-8-sig / gb18030（原来直接 `UnicodeDecodeError`） |
| `case.json` 非法 / 顶层非对象 | `kernel.py init` 写 `blocked` 契约并退出 1，不抛裸栈 |

## 文件说明

- `scripts/kernel.py`：`init / index / verify / emit / check`（仅标准库）。
- `scripts/quote_check.py`：逐字核验每段原文确实存在于 `corpus.txt`，防止补写。
- `scripts/bidir_consistency.py`：双向术语锁定、变体漂移、数字/单位/编号/引用保真、段号完整性。
- `scripts/modality_register.py`：中英双向的情态强度、否定范围、宣传语与口语化检查。
- `references/bilingual-style.md`：中英学术语域、期刊体例、句式与标点规则＋反例。
- `references/glossary-and-alignment.md`：双向术语表格式、段号与双语对照约定、未译标注规则。
- `references/output-contract.md`：默认输出字段；题面契约优先。

## 最小调用示例（示例，不是正式案例结果）

```bash
python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out work
python3 "$SKILL_DIR/scripts/kernel.py" index --materials /input --out work
# 按第 3–5 步生成 work/segments.json、work/glossary.tsv、work/bilingual.json
python3 "$SKILL_DIR/scripts/bidir_consistency.py" --glossary work/glossary.tsv --bilingual work/bilingual.json --out work/fidelity_check.json
python3 "$SKILL_DIR/scripts/modality_register.py" --bilingual work/bilingual.json --out work/modality_check.json
python3 "$SKILL_DIR/scripts/quote_check.py" --evidence work/quotes.json --corpus work/corpus.txt --out work/quote_check.json
python3 "$SKILL_DIR/scripts/kernel.py" verify --text work/target_only.txt --evidence-dir work --out work
python3 "$SKILL_DIR/scripts/kernel.py" emit --draft work/draft.json --contract-dir work --out /app/output
python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract-dir /app/work
```

示意输出（片段）：`P001` 原文 `These results may reflect ion exchange at 25 °C [12].` →
译文 `这些结果可能反映 25 °C 下的离子交换 [12]。`；`fidelity_check.json` 报
`verdict=pass, locked_hit_rate=1.0, counts 全 0`，`modality_check.json` 报 `verdict=pass`。

## 改动记录

### v1.1.0（本地合成夹具迭代 iter1）

- **交付门禁假成功（主因）**：`kernel.py check` 原来只查 `case_id`/`status`，只有这两个字段、
  没有 `source_map`、没有 `translation.md` 的 result.json 也打印 PASS，与本 Skill 的
  `references/output-contract.md` 及“check 必须 PASS 才可交付”矛盾。现核对 `source_map`/`uncertainty`
  两个必填数组字段与 `ok/success` 的四个交付工件（缺失或 <8 字节即 FAIL），`partial/blocked`
  必须有 `limits`；`changes` 按契约作可选字段，缺失/null 不报错。
- **限定强度误判**：`modality_register.py` 对中文禁用词做裸子串匹配，`一定` 命中“在**一定**条件下”
  这种非情态短语，把合格的 `may → 可能` 译文判成 `strength_changed`，`strength_flags=0` 无法达成。
  现对 `一定` 排除“一定条件/程度/范围/时间/数量/比例/规格/区间”等固定搭配，其余情态抬高
  （如 `may` 译成“一定导致”）仍然报 `strength_changed`。
- 归零项（合成夹具实测）：合格译文 `strength_flags=0`、`verdict=pass`；完整产物 `check` PASS；
  仅 `case_id`+`status` 的 result.json 由 PASS 变为 FAIL 并列出 6 条缺失。

### v1.1.1（复核修正）

- **changes 可选性回归**：v1.1.0 初版把 `changes` 列为必填数组，与 `references/output-contract.md`
  的“必填=否”冲突，缺 `changes` 的合规稿被判 `FAIL - result.json missing changes`。现按文档处理：
  字段缺失或为 `null` 不报错；存在时必须为对象数组，且每项 `target/type/before/after/reason`
  至少一项非空，否则 FAIL。`source_map`/`uncertainty` 必填校验不变。
- 回归用例（合成夹具）：无 `changes` PASS、`changes: null` PASS、合法对象数组 PASS；
  `changes: "P001"` FAIL、`changes:[{"target":"","reason":""}]` FAIL、缺 `source_map` FAIL。

### v1.2.0（本地合成夹具迭代 iter2；每条均为实测输出）

- **合法译法被误判为"强度丢失"（主因）**：`up to` 译成「高达」、`not all` 译成「不是全部」是标准译法，
  但允许译法表里缺这两个词，`modality_register.py` 把它判成 `strength_not_preserved`，
  逼作者为过检查而改坏译文。实测同一份 EN→ZH 夹具：
  `counts={"strength_flags": 2}` → `0`，`verdict=review`(rc=1) → `pass`(rc=0)。
- **小数点/缩写被当句末**：`sentences()` 按 `[。！？.!?]` 切分，`78.9%`、`p < 0.001`、`Fig. 2`
  全被切开，实测 `可达 78.9%，p < 0.001。见图 2。` 由 **4 片**（`可达 78.` / `9%，p < 0.` / `001。` / `见图 2。`）
  恢复为 **2 句**；句对错位会让情态规则落到错误的句子上。
- **PDF 连字符断词导致引文核验失败**：语料中是 `experi-\nmental`，引文写 `experimental`，
  `quote_check` 判 `not_verbatim`（`verdict=review failed=1/1`）。`norm()` 增加行末连字符合并后
  `verdict=pass failed=0/1`。
- **GBK 语料直接崩**：`open(..., encoding="utf-8")` 抛 `UnicodeDecodeError: 'utf-8' codec can't
  decode byte 0xb4`。新增 `read_text()`（utf-8-sig → gb18030），同一 GBK 语料
  `verdict=pass failed=0/1`。
- **非法输入裸栈**：`bilingual.json` 截断 → `bidir_consistency` / `modality_register` 由
  `JSONDecodeError` 裸栈改为 `FAIL: bilingual JSON invalid: …` 退出 2；证据 JSON 非法 →
  `quote_check` 报 `FAIL: evidence JSON invalid` 退出 2；术语表缺失 → `FAIL: glossary missing` 退出 2；
  `case.json` 非法 → `init` 写 blocked 契约退出 1。非对象的段/证据条目会被丢弃并在
  `non_object_segments_dropped` 计数，而不是抛 `AttributeError`。
- **契约与 case_id**：`init`/`emit`/`check` 统一 `normalize_contract()`（四形态）；`emit` 不再让契约里的
  `case_id`/`status` 覆盖结果（实测 `case_id=bi-case-01` 保留，`missing_contract_fields=none`）；
  `check` 增加 `--contract-dir`、允许 `changes/uncertainty/limits/notes/self_check/sources` 为空但必须存在，
  并拒绝契约字段嵌在 `result["fields"]` 下；`verify` 剔除标题行与引用标记、合并引用展开逐号核对、
  语料缺失时以 `blocked` 退出 1。
- **平台路径**：新增"平台运行路径"节，全部命令改为 `python3 "$SKILL_DIR/scripts/…"`
  （`SKILL_DIR=/skills/weekly-skill`），避免 cwd=`/app` 时相对路径失效。
