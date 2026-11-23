---
name: evidence-first-research
description: 把研究问题拆成可独立检索的子问题与带依赖的检索计划，仅基于给定的本地材料逐题取证，按来源层级/直接性/研究设计给证据分级，产出带行号定位引文的综述、冲突与反证、基于检索缺口的研究空白和待验证清单。用于文献综述、证据综合、选题评估、趋势分析；不联网检索，不编造文献、检索命中数或已完成实验。
version: 1.2.0
license: MIT
---

# 深度研究 Agent：拆解、取证、分级、有边界地综合

把一次深度研究拆成 **问题分解 → 检索规划 → 逐题取证 → 证据分级 → 综合与反证 → 空白与待验证**。
核心主张：结论的可靠性不取决于读了多少篇，而取决于每个结论句能回到具体材料的具体段落、
证据强度被如实标注、冲突与反证没有被抹平、研究空白能指出是哪个检索式没有命中。

**执行期不联网**：材料只有题面给定的文件。任何"检索到 N 篇文献"的说法都必须等于
`work/evidence.json` 里真实文件的数量；没有的材料就是没有。

## 何时使用

触发：用户给出一个研究问题 + 一批本地材料（论文全文/摘要/报告/表格/笔记），要求
"做文献综述"、"综合这些证据回答 X"、"系统筛选/趋势分析"、"评估这个选题值不值得做"、
"把支持与反对的证据都列出来"、"说明研究空白"。

不触发：单篇论文的逐句精读与笔记（走结构化笔记类 Skill）；单篇文档的版面解析（走解析类 Skill）；
需要联网检索新文献（本 Skill 只能声明"库内不足"，不代替真实检索）；
要求代写论文正文或润色（证据化综述 ≠ 写作代劳）。

## 输入

`/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`；
材料在题面给定路径，可能包含论文 PDF、摘要文本、综述、数据表、检索记录或 screening 清单。
字段名不固定，**先读真实文件**：

| 语义 | 常见字段/文件 |
|-|-|
| 研究问题 | `question`, `research_question`, `task`, `topic` |
| 材料 | `materials`, `sources`, `documents`, `corpus_dir`, `bibliography` |
| 纳排/范围约束 | `inclusion`, `exclusion`, `time_range`, `scope` |
| 输出契约 | `output_contract`（字段全部回填） |
| 案例标识 | `case_id` |

题面若给了纳排规则或时间窗，先把它写进 `plan.json` 的 `scope`，再开始检索；不得事后扩大范围。

## 执行流程（严格按序）

1. **契约**：`python scripts/kernel.py init --case /input/case.json --out work`
   → `work/contract.json`（`case_id` + `output_contract` 全部字段）。
2. **材料台账**：`python scripts/kernel.py index --materials <材料路径...> --out work`
   → `work/evidence.json`（每个文件的路径、字节、sha1、可读性）+ `work/corpus.txt`。
   记下三个事实数字：`files_total`、`files_readable`、`files_unreadable`。
   **这三个数就是本次研究可用的来源总数**，正文任何"共 N 篇/N 份材料"只能取自它们。
3. **问题分解**：写 `work/plan.json`：

   ```json
   {"question": "原文问题",
    "scope": {"inclusion": "...", "exclusion": "...", "time_range": "材料内实际年份范围"},
    "subquestions": [
      {"id": "Q1", "facet": "object|mechanism|method|comparison|temporal|evidence_requirement",
       "text": "可独立检索的子问题", "depends_on": [], "search_terms": ["...", "..."],
       "expected_evidence": "能回答它需要什么样的材料", "stop_condition": "什么情况下停止检索",
       "priority": 1}],
    "decomposition_basis": "依据问题原文中的哪些成分拆分"}
   ```

   要求：子问题覆盖对象、机制/因果、方法、时间或范围、比较关系、证据要求六类中与本题相关的部分；
   每个子问题都能由一段材料独立回答或独立判为无覆盖；`depends_on` 只写真实前置（如"先确定术语"→"再比较数值"）。
   只把原句改写成关键词不算分解。
4. **检索规划**：写 `work/search_plan.json`：按 `depends_on` 拓扑排序，标出可并行组；
   每个子问题写检索式（含同义词、缩写、单位/旧称）、来源范围（哪些文件或目录）、
   停止条件（命中饱和 / 覆盖全部相关文件 / 达预算上限）。避免多个子问题用同一检索式重复扫同一批文件——
   若确实共享前置检索，写成一条 `shared_query` 并让多个子问题引用它。
5. **执行检索并记录**：对每个检索式在材料目录执行
   `grep -rn -- "<term>" <材料目录>`（无 grep 时用 Python 逐文件读并按行匹配），
   把命令、命中文件与行号写进 `work/search_log.json`：
   `{"subq":"Q1","query":"...","tool":"grep -rn","scope":"materials/","hits":[{"path":"...","line":42}],"empty":false}`。
   零命中也必须记录，它是"研究空白"的唯一合法依据。命中后回读上下文（前后各 3–5 行）再判定是否相关。
6. **证据表（可回链）**：写 `work/evidence_table.json`：

   ```json
   {"subquestions": [{"id": "Q1", "text": "..."}],
    "evidence": [
      {"id": "E01", "subq": "Q1", "claim": "该材料支持的具体判断",
       "source_path": "materials/a.md", "locator": "L120-126", "quote": "原文逐字片段",
       "source_type": "peer_reviewed|conference|review|preprint|thesis|report|dataset|web",
       "directness": "direct|indirect|background", "design": "experimental|rct|meta_analysis|cohort|modeling|none",
       "stance": "support|refute|mixed", "year": 2021}]}
   ```

   `quote` 从 `corpus.txt` **逐字复制**（≥12 字符）；`locator` 用文件内行号（PDF 用 `p.N ¶k`）；
   `source_type` 只按材料本身可判断的属性填（有期刊/会议信息才算 peer_reviewed，否则 `report` 或 `preprint`），
   **不确定就填 `report`/`web`，不为了提高等级往高里填**。
7. **证据分级**：`python scripts/evidence_rank.py --table work/evidence_table.json \
   --out work/evidence_rank.json [--as-of <最新年份>] [--window 5]`
   → 每条证据 A/B/C/D 级（缺 quote 或 locator 判 X 不可采信），每个子问题的
   `verdict`（covered / weak / not_covered）、`distinct_sources`、`single_source`、`conflict`、
   `gaps`、`conflicts`、`single_source_subqs`。`verdict=review` 时必须先补齐 X 项再继续。
8. **逐字核验**：把全部 evidence 转 `work/quotes.json`
   （`[{"claim":"E01","source_path":"...","quote":"...","locator":"..."}]`，**不要覆盖 `work/evidence.json`**），
   执行 `python scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt \
   --out work/quote_check.json`；`not_verbatim` 必须改回原文或删除该条。
9. **综合报告**：写 `work/report.md`，固定结构：

   ```
   1. 研究问题与范围（含纳排、材料总数 = files_readable）
   2. 拆解树（Q1..Qn + 依赖 + 每个子问题的检索式数/命中数）
   3. 证据矩阵（按子问题列证据 id、来源、等级、直接性、定位）
   4. 综合结论（每条一个论断 + [E01,E07]，并标"一致/多数/单项"）
   5. 冲突与反证（stance=refute 或 conflicting 的证据必须出现）
   6. 研究空白（基于 not_covered 子问题与 empty 检索式，写清缺什么材料）
   7. 待验证清单（要坐实当前结论还需什么证据/实验/数据）
   8. 不确定性与限制（不可读材料、单一来源子问题、年份缺失）
   ```

   结论强度措辞必须与证据等级匹配：

   | 证据状况 | 允许的措辞 | 禁止的措辞 |
   |-|-|-|
   | ≥2 个独立来源，均 A/B 且方向一致 | "多项材料一致表明…" | — |
   | 1 个来源 A/B | "一项材料报告…"、"现有材料显示…" | "研究普遍认为"、"已证实" |
   | 仅 C/D | "有材料提及，但证据较弱/间接…" | "结果表明" |
   | 仅背景性引用 | "该说法在材料中仅作为背景出现…" | 当作结论 |
   | 无证据 | "库内材料未覆盖…" | "尚无研究"、"领域空白" |

10. **正文交叉核对**：`python scripts/report_audit.py --report work/report.md \
    --rank work/evidence_rank.json --search-log work/search_log.json \
    --evidence work/evidence.json --out work/report_audit.json --strict`
    → 必须 `verdict=pass`。它检查：八段结构齐全；「综合结论」每个断言句都带 `[E..]` 且编号在证据表内；
    `stance=refute` 的证据确实出现在「冲突与反证」段；每个 `not_covered` 子问题在「研究空白」段出现并给检索依据；
    材料总数措辞等于 `files_readable`；「普遍认为/一致表明/已证实」必须有 ≥2 个独立 A/B 来源支撑；
    不得出现「领域空白/尚无研究」。
11. **数字守恒**：把 `report.md` 转 `work/report_text.txt`（去掉 `[E01]`、`L120-126` 这类锚点），
    `python scripts/kernel.py verify --text work/report_text.txt --evidence-dir work --out work`
    → `unsupported_numbers` 应为 0。正文出现的年份、样本量、效应值必须来自材料；
    "共 N 篇材料"必须等于 `files_readable`。
12. **产出**：写 `work/draft.json`（`fields` 覆盖契约字段），
    `python scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output`，
    再 `python scripts/kernel.py check --out /app/output --contract work/contract.json` 必须 PASS；
    门禁会核对契约字段非空、每条 `evidence` 都有 `source_path/locator/quote`、`partial/blocked` 必写 `limits`。

## 领域规则表

| 环节 | 硬规则 | 反例（禁止） |
|-|-|-|
| 拆解 | 每个子问题可独立检索、可独立判为 uncovered；标出真实依赖；覆盖对象/机制/方法/时间/比较/证据要求中相关项 | 把原句拆成关键词列表；8 个子问题其实是同一问的不同说法 |
| 检索规划 | 每个子问题有检索式、来源范围、停止条件；共享检索显式声明；记录零命中 | 所有子问题用同一检索式扫同一批文件；无停止条件导致重复检索 |
| 取证 | 每条证据有 `source_path + locator + 逐字 quote`；`source_type` 按材料实际信息填 | 只写"某研究表明"；把摘要当全文结论；把预印本标成同行评议 |
| 分级 | 按脚本规则给 A/B/C/D；单一来源单独标出；X 必须先修 | 把所有材料一律当"高质量证据"；用等级差异掩盖冲突 |
| 综合 | 结论句带证据 id；单一来源不写成共识；冲突写双方；反证必须出现 | "多项研究一致认为"（实际只有 1 篇）；只列支持证据 |
| 空白 | 空白 = 某个子问题 `not_covered` 或检索 `empty`，写清缺什么 | "该领域仍有广阔研究空间"这类套话 |
| 边界 | 结论不超出材料覆盖的人群/条件/时间范围；推论标 `my_inference` | 用 3 篇材料总结整个领域；把机制推断写成实验结论 |

## 硬性禁止

- 不联网、不调用外部检索服务；不声称检索过材料之外的内容。
- 不编造文献条目、作者、年份、DOI、期刊、样本量、效应值、被引次数或"检索到 N 篇"。
- 不把单一来源写成"共识"或"普遍认为"；不隐藏 `stance: refute` 的证据。
- 不把"本次检索未命中"写成"该问题不存在研究"；不把不可读材料写成"未涉及"。
- 不把机制推断、跨材料外推写成实验结论；推断必须标 `my_inference` 并给 `basis`。
- 不提交预制答案；不写"完成实验/已验证"等未实际执行的动作。
- 不在产物中写入绝对个人路径、账号或 token。

## 输出

`/app/output/result.json`：`case_id`、`status`、`answer`（综述主文）、`structured`、`evidence`、
`uncertainty`、`limits`；题面 `output_contract` 的其他字段全部回填。`reading` 契约之外的附加字段建议：

| 附加字段 | 内容 |
|-|-|
| `decomposition` | `[{id, text, facet, depends_on, search_terms[], stop_condition}]` |
| `search_log` | `[{subq, query, tool, scope, hits, empty}]`，含零命中 |
| `evidence_matrix` | `[{id, subq, source_path, locator, quote, grade, directness, stance, year}]` |
| `coverage` | `[{subq, verdict, evidence_count, distinct_sources, single_source}]` |
| `conflicts` | `[{subq, sources[], difference}]` |
| `counter_evidence` | 与主结论方向相反的证据 id 与定位 |
| `gaps` | `[{subq, basis: "not_covered|empty_query", missing}]` |
| `verification_todo` | 待验证清单（要什么数据/实验才能坐实） |
| `source_inventory` | `{files_total, files_readable, files_unreadable[]}` |

落盘产物：`research_report.md`、`evidence_matrix.csv`、`plan.json`、`search_log.json`、
`evidence_rank.json`、`quote_check.json`。

`status`：`ok`（全部子问题 covered 或无覆盖已声明）、`partial`（部分子问题 weak/not_covered、
材料不可读或预算不足）、`blocked`（材料缺失/不可读）、`refused`（问题超出材料范围）。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 材料目录为空或路径不存在 | `blocked`；列出尝试路径与 `files_total=0`；不生成综述 |
| 部分子问题检索零命中 | 记 `empty: true`，换同义词/缩写再试一轮；仍空 → `gaps` + 明确"库内未覆盖"，不写"领域空白" |
| PDF 无文本层 / 加密 | 标 `unreadable` 与原因，不进入证据；`partial` + `limits` |
| 材料只有摘要/二手综述 | 降级 `directness: indirect` 或 `source_type: review`，结论措辞相应降级 |
| 证据互相冲突 | 双方都进证据矩阵，`conflicts` 记定位与差异；无法判定时写"材料间存在冲突，未找到解释差异的段落" |
| 只有单一来源覆盖某子问题 | `single_source: true`；正文写"一项材料报告"，不写"一致表明" |
| 某条证据 quote 核验失败 | 改回原文片段或删除；删除后在 `limitations` 说明该子问题证据减少 |
| 预算不足（64 请求 / 900s / 16k tokens） | 先落盘 `plan.json` + 已完成子问题的证据与结论，`partial` + `limits` 列未完成子问题 |
| 题面要求联网/最新文献 | `refused` 或 `partial`，说明"执行期不联网，仅基于给定材料" |

## 文件说明

- `scripts/kernel.py`：`init / index / verify / emit / check`（仅标准库，复用共享骨架）。
- `scripts/evidence_rank.py`：证据分级（来源层级/直接性/设计/时效）、子问题覆盖、冲突与单一来源识别。
- `scripts/quote_check.py`：引文逐字核验（容忍换行、连字、软连字符），并核对 quote 是否来自**声明的源文件**
  （`wrong_source`）。
- `scripts/report_audit.py`：正文与证据表/分级/检索记录的交叉核对（八段结构、结论句锚点、
  反证出场、空白与零命中对应、材料总数、过度断言）。
- `references/research-protocol.md`：分解模板、检索规划与停止条件、工具调用记录格式。
- `references/evidence-grading.md`：分级规则、结论措辞对照、冲突/空白/待验证写法与反例。
- `references/output-contract.md`：默认输出字段（`reading` 契约 + 本题附加字段）；题面契约优先。

## 最小调用示例（示例，不是正式案例结果）

```bash
python scripts/kernel.py init --case /input/case.json --out work
python scripts/kernel.py index --materials /input/materials --out work
# 写 work/plan.json、work/search_plan.json；按计划执行 grep -rn 并记录 work/search_log.json
# 依据命中写 work/evidence_table.json、work/quotes.json、work/report.md、work/draft.json
python scripts/evidence_rank.py --table work/evidence_table.json --out work/evidence_rank.json
python scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt --out work/quote_check.json
python scripts/report_audit.py --report work/report.md --rank work/evidence_rank.json \
    --search-log work/search_log.json --evidence work/evidence.json --out work/report_audit.json --strict
python scripts/kernel.py verify --text work/report_text.txt --evidence-dir work --out work
python scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output
python scripts/kernel.py check --out /app/output --contract work/contract.json
```

示意输出（片段，示例）：`evidence_rank.json` 报 `covered=4/6 gaps=2 conflicts=1 inadmissible=0`；
报告句"两项独立材料均报告 X 与 Y 正相关 `[E01,E04]`"，另一子问题写"库内材料未覆盖 Z
（检索式 `"Z"`、`"Z analog"` 在 9 份材料中零命中）"。

## 改动记录

- **v1.2.0**（v1.1.0 正式分 58.67 低于 v1.0 的 63.67，按可复现缺陷回修）
  - `report_audit.py` 段名优先级：`tree` 的通用词「子问题」原来排在 `matrix` 前，
    导致按本 SKILL 自带模板写的「3. 证据矩阵（按子问题列证据…）」被误判为拆解段，
    `--strict` 直接报 `missing section: matrix`。现将 `tree` 放到最后匹配，
    并先用标题主干（去掉「（…）」说明）判段；「7. 待验证清单（…当前结论…）」不再被「结论」抢走。
  - `report_audit.py` 标题占位：模板标题「综合结论（…+ [E01,E07]）」里的示例锚点会被当成
    未知证据 id 报错。现锚点扫描跳过 Markdown 标题行。
  - `report_audit.py` 过度断言判定：原按「同一子问题 ≥2 个 A/B 来源」计数，
    会误拦合法的跨子问题综合句（E01@Q1 + E02@Q2）。改为统计该句锚点所引证据中不同
    A/B `source_path` 的个数 ≥2。
  - `kernel.py index` 可读性：原来只要正文以 `[` 开头就判 `unreadable`，编号参考文献
    （`[1] Smith 2021`）或 JSON 数组会被整份排除，`files_readable` 与材料总数措辞随之失真。
    现只认真正的占位失败标记（unsupported type / PDF 无文本层 / xlsx 失败 / 图像）。
  - `quote_check.py` 归属核验：声明源在语料里找不到对应块时，v1.1.0 会静默放行；
    现返回 `wrong_source` 并给出实际命中的源；同一 basename 多文件时按候选集合逐个核对。
  - `evidence_rank.py` 冲突识别：`mixed` 表示材料内部结论不一致，原来只认 support+refute，
    现 `mixed` 或 support+refute 均标 `conflict`。
  - `kernel.py verify` 数字守恒：章节编号（`## 7.`）与列表序号（`1.`）会被当成数据报
    `unsupported_numbers`。现先剥离标题/序号再取数；零命中检索式改用非数字写法
    （如 `five-year`），避免把检索词当数据。
  - `report_audit.py` 其余加固：结论段的 `- ` 列表句不再跳过锚点检查；段内小标题
    （`### 5.1`）不再截断所属大段；`--rank/--search-log/--evidence` 缺失时 fail-closed；
    禁语扫描跳过标题行；有冲突的子问题必须在「冲突与反证」段出现至少一条该子问题证据。
    序号剥离只认 1–2 位（避免 `2019.` 被误删），`quote_check` 的路径后缀匹配收紧
    （避免 `a.md` 命中 `data.md`）。
- **v1.1.0**（复核 63.67 分反馈后的迭代）
  - 失分点「结论可核验 / 反证不缺席」：原来正文与证据表之间没有任何机检，`stance=refute` 是否真的写进
    「冲突与反证」、结论句是否带 `[E..]`、锚点是否在证据表内全靠自律。新增 `scripts/report_audit.py`
    做交叉核对（结构 8 段、结论句锚点、反证出场、空白与零命中对应、材料总数、过度断言、禁止措辞），
    `--strict` 下 `verdict != pass` 退出 1，接在定稿流程里。
  - 失分点「引用归属」：`quote_check.py` 只验 quote 是否在整份语料里出现，存在把 A 文件的句子挂到 B 文件
    的漏检。现按 `===== FILE: =====` 分块核对声明源，新增 `wrong_source` 状态。
  - 失分点「交付诚实」：`kernel.py check` 升级为全量门禁——契约字段非空、`evidence` 每条必须有
    `source_path/locator/quote`、`status=ok` 不得有缺失 quote、`partial/blocked` 必写 `limits`、
    报告类产物路径必须真实存在；并修复 `fields.limits` 被空值覆盖的缺陷。
