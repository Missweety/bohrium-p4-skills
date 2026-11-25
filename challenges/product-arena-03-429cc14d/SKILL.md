---
name: citation-integrity-auditor
description: 审计并整理学术稿件的正文引用与文末文献表。建立句级引用点，核对作者/年份/期刊/卷期页/DOI 与正文—列表一一对应，按 DOI→题名→版本判据识别重复条目并给出合并依据，统一到声明的 GB/T 7714-2015、APA 7 或 Vancouver 格式，并按首次出现重排编号、输出可编辑稿件与机器可读核验报告。用于“整理参考文献”“引用格式转换”“编号错乱”“查重条目”“核对 DOI”“正文引用和文献表对不上”等请求；不用于代写论文正文、凭空补充文献、文献综述检索（无本地文献库时）或仅做语言润色。
version: 1.3.0
license: MIT
---

# 参考文献与引用管理：挂得对、编得顺、收得净、对得上

把一个"整理引用"的请求变成 **可逐条复核的交付物**：整理后的稿件 + 同步的文献表 +
引用点清单 + 核验/去重/编号报告。核心主张：**任何一条引用都必须落到文献库里一条真实记录上，
任何一次合并、重排、删除都要留判据和前后差异**。没有材料支撑的条目只能标记，不能补造。

## 平台路径（务必按此执行）

评测时 Skill 装在 `/skills/weekly-skill`，工作目录通常是 `/app`，**两者不同**，相对路径
`scripts/...` 会直接 `can't open file`。因此所有命令都用绝对路径调用，且不依赖当前目录：

```bash
SKILL_DIR=/skills/weekly-skill        # 若你确实在 skill 目录内，也可写 SKILL_DIR=.
python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out /app/work
```

下文为可读性省略了 `$SKILL_DIR/`，执行时**必须补全为绝对路径**，解释器统一用 `python3`。

## 何时使用

触发：稿件含正文引用（`[1]` 顺序编码、`(Author, 2020)` 著者—出版年、`\cite{key}`、脚注）
或文末参考文献表，且用户要求：插入/补引用、更新与重排编号、去重合并、格式转换
（GB/T 7714-2015 / APA / Vancouver / BibTeX / RIS）、核对 DOI 与元数据、检查正文—文献表
一致性、找出过引/装饰性引用/张冠李戴。

不触发：要求从零撰写正文内容（用 `intro-related-work-builder` 或写作类 Skill）；
要求联网检索并新增文献（本 Skill 只在给定文献库内工作，缺文献写 `missing`）；
纯语言润色（用 `academic-polish-minimal-edit`）；只问"这篇论文讲了什么"。

## 输入

执行时读取 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`。
材料通常包括：待整理稿件（md/docx/pdf/tex）、文献库（bib/ris/csv/md 文末列表/数据库导出）、
可选的目标格式说明与期刊要求。字段名不固定，**先读真实文件再判断**：

| 语义 | 可能字段/文件 |
|-|-|
| 稿件 | `manuscript`, `source_text`, `paper`, `draft.md/.docx/.tex` |
| 文献库 | `references`, `refs.bib`, `library.ris`, `cnki_export.csv`, 文末“参考文献”节 |
| 目标格式 | `target_style`, `citation_style`, `journal_style`（缺省声明为 GB/T 7714-2015） |
| 编号制 | 顺序编码制 / 著者—出版年制 / 脚注制 |
| 输出契约 | `output_contract`（字段名、类型、必填） |
| 案例标识 | `case_id` |

文献库解析原生支持四类：BibTeX（`.bib`）、RIS（`.ris`）、EndNote XML（`.xml`）、
表格导出（`.csv/.tsv/.xlsx`，按 title/题名、year/年、doi、journal/期刊、volume/卷、issue/期、
pages/页码、author/作者 等列名别名映射）与带编号的文末列表（`[1] ...` / `1. ...` / `［1］`）。
字段缺失写 `field_gaps`，**不得按记忆补全**；任何转换动作记入 `changes`，不得借转换之机改写字段值。

## 执行流程（严格按序）

1. **契约**：`python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out work`
   → `work/contract.json`（case_id、output_contract、任务原文）。题面契约字段一个都不能少。
2. **建证据索引**：`python3 "$SKILL_DIR/scripts/kernel.py" index --materials <稿件> <文献库> --out work`
   → `work/evidence.json` + `work/corpus.txt`。docx/xlsx/pdf 自动抽取；扫描件标 `unreadable`，
   **不得凭常识补文献内容**。若稿件是 docx，先确认文末列表也被抽到（查看 `work/corpus.txt` 是否含“参考文献”节）。
3. **解析引用点与条目**：
   `python3 "$SKILL_DIR/scripts/citation_formatter.py" audit --manuscript work/manuscript.md --refs <文献库> --style gb7714 --out work`
   → `work/citation_report.json`（`cited_not_listed` / `listed_not_cited` / `first_appearance` /
   `duplicate_candidates` / `field_gaps` / `style_issues`）+ `work/citation_points.csv`。
   若稿件是 docx/pdf/xlsx，先 `python3 "$SKILL_DIR/scripts/kernel.py" extract --path <原稿> --out work/manuscript.md`
   落成文本（保留段落与文末“参考文献”节），再跑本步；不要在原文件上直接改。
   文献库是 `.ris/.csv/.tsv/.xlsx/.xml` 时 `--refs` 直接传原文件，脚本会按列名/标签解析并报告条目数；
   `refs=0` 视为解析失败，先查分隔符与表头，不得当作“没有文献”。
4. **逐条核验（人工+材料，不联网）**：对每个条目核对 作者顺序、年份、题名、期刊/会议、卷(期)、
   页码、文献类型标识、DOI。判定等级只有三级：
   `verified`（文献库/材料内字段一致）、`partial`（有记录但字段缺失/不一致）、`unverified`（库内无记录）。
   缺字段的条目写入 `field_gaps` 处理清单，**不允许按记忆补全作者或 DOI**。
5. **正文—条目一一对应**：把 `citation_points.csv` 的每个 token 对齐到句子，检查
   ①编号存在但列表无条目 → `cited_not_listed`；②列表有条目但正文从未引用 → `listed_not_cited`
   （需判断是"漏引"还是"该删"，写进 `changes`）；③一句多引/多句一引是否指向同一论断。
6. **位置判定（挂得对）**：逐句判断是否需要来源支撑——出现具体数值、比较级、因果动词
   （导致/证明/显著优于）、他人方法或结论时必须有引用；引用应贴在承载该论断的句子末尾，
   而不是整段末或图表注。无库内文献可支撑的句子标 `missing_citation`，不得随意挂一条。
7. **过引/装饰性引用/错配识别**：
   - 过引：同一句 ≥3 条引用且未区分各自贡献；或同一文献在同一段落反复出现 ≥3 次。
   - 装饰性：引用所在句只有"已有研究表明/大量文献关注"而无具体结论，或引用挂在纯过渡句上。
   - 错配：引用条目主题（题名/关键词）与句子论断不符；作者年份与正文叙述不一致；
     预印本/正式版/中英文版被当成两项不同工作。
   三类问题均写入报告 `issues[]`，给出句子定位与理由，不静默删除。
8. **去重与合并（收得净）**：按 `references/dedup-verify.md` 的判据分级处理。
   合并必须写 `merge_groups[]`：`{kept, merged, criterion, evidence}`；`criterion` 只能是
   `doi_exact` / `title_exact` / `title_containment` / `author_year_title`。
   **仅凭作者相同不合并**；`criterion` 为后两级时须人工确认，结论进 `uncertainty`。
9. **格式统一（编得顺）**：声明目标格式（题面未给则 GB/T 7714-2015），按
   `references/citation-formats.md` 统一：作者人数与缩写、`[J]/[C]/[M]/[D]` 类型标识、
   中英文标点、DOI 前缀、卷期页顺序。只做格式改写，不改事实字段；字段本身冲突时保留两值并标注。
10. **编号重排**：`python3 "$SKILL_DIR/scripts/citation_formatter.py" renumber --manuscript work/manuscript.md --refs <文献库> --out work --style gb7714`
    → `work/manuscript_renumbered.md`（正文 + 重排后的文献表，可直接继续编辑）+
    `work/refs_renumbered.md` + `work/renumber_map.csv`。
    编号按正文首次出现排序、连续无跳号；一句多引合并为 `[3,5]`。
    支持两种引用体系：数字 `[1]` 与键 `\cite{key}`（BibTeX 主场景）。`\cite{a,b}` 会按首现顺序
    改写为 `[2,5]`，`renumber_map.csv` 的 `kind` 列区分 `number`/`key`。
    正文引用了库内没有的编号时不再静默跳过：`renumber_map.csv` 追加
    `kind="unmapped: cited but absent from the library"` 行并在终端打印清单，
    这些编号原样保留，转写进 `citation_report.cited_not_listed` 与 `limits`，**不得补条目凑数**。
    文献表按 `--style` 用库内字段渲染（GB/T 的 `[J]`/作者大写/`卷(期): 页`、APA 的 `&`/DOI URL、
    Vancouver 的 `姓 首字母`），字段不足的条目退回原始记录文本，不拼接缺失字段。
    重排后复查图表注、附录与交叉引用中的编号是否同步（脚本不覆盖的位置人工核对并记 `changes`）。
11. **守恒自检**：
    - 数字：`python3 "$SKILL_DIR/scripts/kernel.py" verify --text work/manuscript_renumbered.md --evidence-dir work --out work`
      → `unsupported_numbers` 必须为 0，否则回改或写入 `uncertainty`。
      扫描前会剔除 Markdown 标题行与引用标记（`[37]`、`\cite{key}`），并按空格/百分号/千分位
      归一后比对，标题号与引用号不再计入。数值比对仍为子串匹配，部分真实数值改动可能漏报
      （如 `12.4` 被语料中的 `112.4` 放行），已列入遗留，不能视为真实改动必被报出。
    - 引用：合并引用 `[3,5]` / `\cite{a,b}` 会先展开，逐号检查 `"[n]"` 是否在语料中出现，
      规范写法不再被误报 `citations_not_in_sources`。若仍有报告，按 `corpus.txt` 定位；
      **引用一致性最终以 `work/citation_report.json` 的 `cited_not_listed` 为准**。
    - 复跑 `audit`：`verdict=review`（`cited_not_listed` / `listed_not_cited` / `duplicate_candidates` /
      `style_issues` 任一非空）必须逐条解释进 `changes` 或 `uncertainty`。
12. **产出**：写 `work/draft.json`（`fields` 对齐契约，`artifacts` 放正文与文献表），
    `python3 "$SKILL_DIR/scripts/kernel.py" emit --draft work/draft.json --contract-dir work --out /app/output`，
    再 `python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract-dir work` 必须 PASS：
    逐项核对契约字段、四个必交工件（`manuscript_renumbered.md` / `refs_renumbered.md` /
    `citation_report.json` / `renumber_map.csv`）与 `partial` 的 `limits`。
    契约支持三种形态：`{"field": "type", ...}`、`{"fields": {...}}`、`["field", ...]`；
    `case_id`/`status` 只从 case 与 draft 顶层的 `status` 取，不会被 `fields` 覆盖成 null。

## 领域判定规则表

| 判定 | 规则 | 处置 |
|-|-|-|
| 必须引用 | 含具体数值、比较/因果、他人方法或结论的句子 | 库内有对应文献则挂；无则 `missing_citation` |
| 不必引用 | 纯过渡、本文方法描述、常识性定义（仍需谨慎） | 不加引用，不视为缺陷 |
| 引用位置 | 句末（英文标点前）/ 被支撑短语后 | 整段末、图表注、标题处挂引用判为位置错误 |
| 编号连续性 | `[1..N]` 无跳号，首次出现升序 | 不连续 → `renumber` |
| 一句多引 | 各文献分别支撑不同子论断，或合并陈述同一结论 | 无法区分 → 过引告警 |
| 条目重复 | DOI 完全一致；题名规范化后完全一致 | 直接合并 |
| 疑似重复 | 题名互相包含且长度比 ≥0.9；同作者+同年+题名高度相似 | 列为候选，须人工确认 |
| 不得合并 | 仅作者相同 / 仅年份相同 / 同名作者不同题名 | 保留为两条，注明理由 |
| 版本关系 | 预印本 vs 正式版 vs 会议版 | 保留正式版为主条目，其余在 `notes` 说明，不静默删除 |
| 元数据冲突 | 同一 DOI 的年份/卷期在两处不同 | 两值都记录，标 `conflict`，交人工裁决 |

## 硬性禁止

- 不新增文献库之外的条目；不凭记忆补 DOI、卷期页、作者或期刊名。
- 不把 `unverified` 写成"已核实"；不把"库里没有"写成"该文献不存在"。
- 不静默删除任何条目或引用；删除/合并必须进 `changes` 并给出判据。
- 不改动论断含义来迁就已有引用（不得为了用某条文献而改写结论）。
- 不伪造运行状态、格式转换结果或核验记录；不提交预制答案。

## 输出

`/app/output/result.json`（回填契约全部字段 + `case_id`）+ 可编辑稿件 + 同步文献表 +
引用点清单 + 核验报告。默认落盘：

| 文件 | 内容 |
|-|-|
| `manuscript_renumbered.md` | 整理后的正文（编号已同步） |
| `refs_renumbered.md` | 与正文一一对应的文献表 |
| `citation_report.json` | 一致性、重复候选、字段缺口、过引/错配清单 |
| `renumber_map.csv` | 旧编号→新编号映射，可反向追溯 |
| `result.json` | `status` / `source_map`（条目→材料定位）/ `changes` / `uncertainty` / `limits` |

默认契约见 `references/output-contract.md`；题面 `output_contract` 优先。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 文献库缺失/为空 | `status: partial`，只做正文引用点与格式审计，`limits` 说明无法核验条目 |
| 文献库为扫描 PDF/图片 | 标 `unreadable`，要求可读版本；不 OCR 猜测，不补条目 |
| 稿件与文献表编号体系不同（如正文 `\cite`、列表数字） | 两种体系同时映射并按首现统一编号；无法落库的编号写 `unmapped` 行并进 `cited_not_listed` |
| 同一文献多版本/中英文双题名 | 按判据列为候选，保留主条目 + `notes`；不确定进 `uncertainty` |
| 编号冲突/重号 | 以首次出现为准重排，冲突对写入 `renumber_map.csv` 并在报告标注 |
| DOI 无法解析（无网络） | 标 `unverified: doi_not_checked_offline`，不声明"DOI 有效" |
| 文献库为 RIS/CSV/XLSX 且未转换 | 先整理为 bib 或编号列表并记 `changes`；无法转换则 `status: partial` 并列出缺失字段 |
| 稿件格式不支持（加密 docx/纯图 PDF） | `status: partial|blocked`，说明缺哪个文件、影响哪些引用点 |
| `case.json` 非法 JSON / 顶层不是对象 | `init` 不抛栈：写 `contract.json{status:blocked, error}` 并退出 1，流程按 `blocked` 落盘 |
| 材料非 UTF-8（GBK/latin-1 等） | `evidence.json` 记 `encoding: non-utf8`，按替换字符解码并提示人工核对数字/姓名；不静默采用 |
| 材料路径不存在 / 目录为空 | `evidence.json.missing_materials` 记录并在终端提示；不按记忆补文献 |
| 输出目录已存在 | 所有写入用 `makedirs(exist_ok=True)` + 覆盖，重复运行结果一致 |
| 预算不足（900s / 64 请求） | 先落盘已完成部分，`status: partial` + `limits` 列出未处理章节 |

## 文件说明

- `scripts/kernel.py`：init / index / verify / emit / check（仅标准库，无网络）。
- `scripts/citation_formatter.py`：引用点解析、一致性/重复/字段审计、按首次出现重排编号。
- `references/citation-formats.md`：GB/T 7714-2015、APA 7、Vancouver 的字段顺序与检查项。
- `references/dedup-verify.md`：去重判据分级、合并证据模板、核验等级定义。
- `references/output-contract.md`：默认输出字段；题面契约优先。

## 最小调用示例（示例，非正式案例结果）

```bash
python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out work
python3 "$SKILL_DIR/scripts/kernel.py" index --materials /input/materials --out work
python3 "$SKILL_DIR/scripts/citation_formatter.py" audit --manuscript work/manuscript.md \
    --refs /input/materials/refs.bib --style gb7714 --out work
python3 "$SKILL_DIR/scripts/citation_formatter.py" renumber --manuscript work/manuscript.md \
    --refs /input/materials/refs.bib --out work
python3 "$SKILL_DIR/scripts/kernel.py" verify --text work/manuscript_renumbered.md --evidence-dir work --out work
python3 "$SKILL_DIR/scripts/kernel.py" emit --draft work/draft.json --contract-dir work --out /app/output
python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract-dir work
```

示例输出（示意）：`citation_report.json` 报 `cited_not_listed: []`、`duplicate_candidates:
[{"a":"12","b":"27","criterion":"title_exact"}]`；`renumber_map.csv` 给出 `12→7`、`27` 合并进 `7` 的
映射与判据；`result.json.status = "ok"`，`uncertainty` 记录 1 条待人工确认的版本关系。

## 改动记录

### v1.1.0（因 #89192 harbor_reward 0.54 迭代）

- **输入兼容性（主因）**：原 `parse_refs` 只认 `.bib` 与编号列表，遇到 CNKI/Scopus 导出的
  `.ris`、`.csv`、`.xlsx` 或 EndNote `.xml` 会解析出 0 条文献，后续一致性检查全部失真。
  现按扩展名原生解析 RIS（TY/ER 分块、TI/PY/DO/JO/VL/IS/SP）、表格（列名中英文别名映射）、
  EndNote XML，并在 `refs=0` 时给出硬性 `style_issues`，不再静默“通过”。
- **输出契约**：`kernel.py check` 原来只查 `case_id`/`status`，契约字段缺失或四个交付工件缺失
  仍会 PASS。现逐项核对契约字段、`manuscript_renumbered.md`/`refs_renumbered.md`/
  `citation_report.json`/`renumber_map.csv` 是否存在且非空、`partial` 是否写了 `limits`。
- **可机检项**：新增 key 级一致性（`\cite{key}` 引用了库外 key → `cited_not_listed`）、
  全角括号 `［1］/【1】` 与中文顿号分隔、`\citep/\citet` 识别；去重新增
  `title_containment`（规范化题名互相包含且长度比 ≥0.9）候选，避免只靠完全相等漏掉版本重复。
- **降级路径**：新增 `kernel.py extract` 把 docx/pdf/xlsx 原稿落成 `work/manuscript.md`，
  避免“人工还原段落”造成引用点丢失；抽取失败返回非 0 并由 `limits` 说明受影响章节。

### v1.2.0（本地合成夹具迭代 iter1）

- **误合并（主因）**：编号列表解析时把“作者段”当题名（`[1] Zhang San, Li Si. …` 的题名被取成
  `Zhang San, Li Si`），同作者不同题名会被判为 `duplicate_candidates`，与 `references/dedup-verify.md`
  的 E 级“仅作者相同不得合并”冲突。现按作者段识别跳过作者、取真正题名；重复判据改为
  `doi_exact` / `title_exact`（题名规范一致**且年份一致**），不再输出文档未定义的 `title` 值。
- **数值误判**：`kernel.py verify` 把 Markdown 标题号（`## 3.2`）与引用标记（`[37]`）当作正文数值，
  `unsupported_numbers` 恒不为 0，只能靠人工抹平。现扫描前剔除标题行与引用标记，并按
  空格/百分号/千分位归一比对；本次夹具中 `66.7%` 与源数据 `66.67` 的差异能被报出，但仍是
  子串比对，部分真实差异（如 `12.4` 被 `112.4` 放行）可能漏报，列为遗留。
- 归零项（合成夹具实测）：同作者异题名 `dup=0`、真实重复仍报 `title_exact`；标题号/引用号
  `unsupported_numbers=0`；本次夹具 `66.7%` 报 1 条（漏报场景见上一条与遗留）。

### v1.3.0（本地合成夹具迭代 iter2）

夹具位置 `/tmp/bohrium_iter2/ch03`（虚构文献与数值，非正式案例）。以下每条都有真实命令输出。

- **BibTeX 稿件重排产出空文献表（主因）**：`renumber` 只接受数字键
  （`if str(r["key"]).isdigit()`），而 `.bib` 的键是 `zhang2019tio2` 这类字符串，`\cite{key}` 正文
  又是 key 引用，于是 `refs={}`、`order=[]`，脚本仍 `rc=0` 打印 `renumbered 0 citations; refs=0`，
  写出 `refs_renumbered.md` 仅含 `# 参考文献` 表头——交付物看着成功、实际没有文献表。
  现改为 key↔编号统一映射：`\cite{a,b}` → `[2,5]`，文献表按首现顺序输出，`renumber_map.csv`
  增加 `kind` 列（`number`/`key`）。同一夹具现输出 `renumbered 3 citations; refs=3`。
- **正文编号在库内无对应条目时静默通过**：稿件自带 `[1]-[4]`、库为 3 条 bib 时，`[4]` 原样留在
  正文却无任何提示。现追加 `kind="unmapped: cited but absent from the library"` 行并打印清单。
- **`output_contract` 形态导致 `case_id` 被清空 / 字段错层**：契约含 `case_id` 字段时，
  `emit` 先用契约再被 `fields` 里的空值覆盖，`result.json.case_id=null`（`check` 报 FAIL）；
  契约是字段名列表时，`emit` 把 draft 整体塞进 `result["fields"]`，顶层没有契约字段，而
  `check` 只看到 `fields` 键非空 → 假 PASS。现统一 `normalize_contract()` 展平三种形态，
  `case_id`/`status` 只取 case 与 draft，`check` 额外拒绝"契约字段嵌在 fields 下"的布局。
- **非法 `case.json` 抛裸栈**：原 `init` 直接 `json.load` 崩溃，无 `contract.json`、无可读信息。
  现写 `{status:blocked, error:"case.json unreadable: ..."}` 并退出 1；`emit` 遇到不可读契约降级
  为仅用 draft 字段，遇到不可读 draft 明确报错退出 2。
- **合并引用误报**：`[3,5]` 被整串去 `corpus.txt` 检索，恒报 `citations_not_in_sources=1`。
  现展开后逐号核对 `"[n]"`/key，同一夹具 `citations_not_in_sources=0`。
- **`audit` 对漏引不表态**：`listed_not_cited` 非空时 `verdict` 仍为 `pass`。现纳入 review 判据；
  并新增 `first_appearance_keys` 便于核对 key 制稿件的首现顺序。
- **材料异常不记录**：`index` 对不存在路径静默跳过、对非 UTF-8 材料静默替换解码。现写
  `evidence.json.missing_materials` 与逐文件 `encoding`，终端提示人工核对数字/姓名。
- **`section_audit` 两处误判**：章节正文按模板下标取，缺一节后后续全错位；中文词数按
  `[A-Za-z\u4e00-\u9fff]+` 整段计 1 词，9 字的方法节被判 2 词。现按标题文本取正文、CJK 逐字计数。
- **命令与路径**：全部命令改为 `python3 "$SKILL_DIR/scripts/..."` 绝对调用（平台装在
  `/skills/weekly-skill`、cwd 为 `/app`），解释器统一 `python3`；任意 cwd 实测可跑通
  init→index→audit→renumber→verify→emit→check。
