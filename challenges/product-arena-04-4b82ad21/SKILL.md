---
name: intro-related-work-builder
description: 从给定稿件、实验材料与本地文献库起草或改写论文的引言与相关工作：先建“本文证据卡 + 文献能力卡”，再按问题设定/方法路线/数据与评价分组比较，从已引文献的共同局限推导研究空白，写出与本文方法一一衔接的贡献条目，并输出段落级 claim→citation 映射、缺口推导表与贡献—图表对照表。用于“写引言”“整理相关工作”“补引用”“把贡献写清楚”“审一下引言逻辑”等请求；不用于无材料的自由创作、代写实验数据、纯语言润色或联网文献检索。
version: 1.3.0
license: MIT
---

# 引言与相关工作写作：立得住、分得清、说得实、对得上

本 Skill 把"写引言"变成 **证据先行、逐句绑定、可反向核对** 的写作流程：
**本文证据卡 → 文献能力卡 → 分组比较表 → 缺口推导 → 贡献对齐 → 逐段写作 → 机器审计**。
核心主张：引言的每一句论断要么有引用，要么明确是作者判断；每一个研究空白都由已引文献的
具体局限推出；每一条贡献都能在正文图表或结果中找到对应证据。

## 何时使用

触发：用户给出论文材料（稿件草稿、方法说明、实验结果表、图表、参考文献库、组会记录）并要求
撰写/改写 **引言（Introduction）** 或 **相关工作（Related Work）**；或要求补引用、检查综述
逻辑、把贡献写清楚、解释研究动机、为投稿重写背景段。

不触发：没有任何材料、要求凭空生成研究结论或文献综述（缺文献库时只能写"待补"框架）；
纯语言润色（用 `academic-polish-minimal-edit`）；只做参考文献格式整理（用
`citation-integrity-auditor`）；要求联网检索最新文献（本 Skill 只在给定材料与文献库内工作）。

## 输入

读取 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`。
常见材料：已有引言草稿、方法与实验描述、结果表/图、参考文献库（bib/ris/csv/md）、
目标期刊与字数要求。字段名不固定，先读真实文件：

| 语义 | 可能字段/文件 |
|-|-|
| 草稿/原文 | `manuscript`, `source_text`, `draft`, `intro.md` |
| 文献库 | `references`, `refs.bib`, `library.ris`, 文末参考文献节 |
| 本文方法/结果 | `methods`, `results`, `experiments`, 结果 csv/xlsx、图注 |
| 语言/体裁 | `language`, `genre`, `target_journal`, `word_limit` |
| 输出契约 | `output_contract` |
| 案例标识 | `case_id` |

文献库解析支持 BibTeX（`.bib`）与带编号的文末列表；RIS/EndNote/CSV/XLSX 先整理成这两种形式
（保留题名、作者、年，供引用核验），转换动作记入 `changes`。

## 平台运行路径（必须遵守）

平台把本 Skill 装到 `/skills/weekly-skill`，命令的工作目录是 `/app`，**不在 Skill 根目录**。
因此所有脚本必须用绝对路径调用，否则 `python scripts/kernel.py` 会因找不到文件直接失败：

```bash
SKILL_DIR=/skills/weekly-skill
python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out /app/work
```

材料在 `/input/materials`，产物写 `/app/output`。`case.json` 里的相对材料路径以 `/input` 为基准；
若题面写的是 `materials/...` 而实际位于 `/input/materials`，`index` 会打印 `MISSING` 而不是静默跳过，
把路径补全后复跑。

## 执行流程（严格按序，写前先建卡）

1. **契约**：`python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out /app/work`
   → `work/contract.json`。确认语言、字数、章节要求与 `output_contract` 字段。
2. **证据索引**：`python3 "$SKILL_DIR/scripts/kernel.py" index --materials <材料...> --out /app/work`
   → `work/evidence.json` + `work/corpus.txt`。不可读文件标 `unreadable`，**不得按领域常识补内容**。
3. **本文证据卡**（只从材料取）：方法要点、数据集与规模、评价指标、关键数值、图表编号。
   每条 `{fact_id, claim, value, source_path, locator}`；冲突两值都留并标 `conflict`。
4. **文献能力卡**：对文献库中每篇，记录 **它解决了什么 / 在什么条件下有效 / 明确局限**。
   只允许从材料的题名、摘要、正文片段提取；只有题名时 `capability: title_only`，
   不得推断其结论，也不得写"某研究表明……"。
5. **分组比较**：按 `references/intro-logic.md` 的三维（问题设定 / 方法路线 / 数据与评价）分组，
   每组写 2–4 句：共同目标 → 各自取舍 → 共同局限。**禁止按时间顺序逐篇罗列**。
6. **缺口推导**：每条空白必须是 `gap = 已引文献的局限(≥2 条引用) + 未覆盖的条件 + 为什么重要`。
   缺口句不足 2 条引用即视为无依据，降级为作者判断并写明"本文假设"。
7. **贡献对齐**：每条贡献写成 `动作 + 对象 + 证据指针 + 边界`，证据指针必须指向材料中的
   图表/章节/数值（`Figure 2`、`Table 1`、`Section 3.2`、具体指标）。找不到证据的贡献删除或
   标 `pending_evidence`，**不得保留无法核对的断言**。
8. **逐段写作**：四块结构（研究背景 → 相关工作 → 研究空白 → 本文贡献），每段先列本段
   claim 与拟用文献 key，再写句；每句登记 `claim → citation` 到 `work/claim_map.json`。
   写作时遵守 `references/claim-citation-rules.md` 的句式与引用位置规则。
9. **映射审计**：`python3 "$SKILL_DIR/scripts/claim_citation_linker.py" audit --draft /app/work/intro.md --refs <文献库> --out /app/work --gap-table /app/work/gap_table.csv --contribution-map /app/work/contribution_map.csv --strict`
   → `work/claim_map.json` + `work/claim_map.csv`，并给出结构化 `verdict`。必须处理：
   `needs_citation`（补引用或标 missing）、`gap_unsupported`（补 ≥2 条局限依据）、
   `stacked`（拆开或概括）、`decorative`（删或补具体结论）、`missing_ref`（库内无此条）、
   `unverified_numeric`（编号引用对不上 key 制文献库，见下）、
   `contribution_needs_evidence`（补证据指针）、`orphan_refs`（列了没引的条目）。
   同时自动校验：四块小节顺序（背景→相关工作→空白→贡献）、`gap_table.csv` 每行
   `cited_limitations` ≥2 且填了 `uncovered_condition`、`contribution_map.csv` 的证据指针
   形如 `Figure/Table/Section N` 且能在正文找到。`--strict` 下 `verdict != pass` 直接退出 1，
   作为定稿门禁。`--draft`/`--refs` 路径不存在时退出 2 并给出缺失路径，不会静默输出空映射。
   `Figures 2`、`Table 1`、`e.g.`、`et al.` 的句点不会被当成句末（曾把一个论断拆成
   "…（Fig." + "2），并以…" 两段并误报）；编号引用与 key 制 `.bib` 不匹配时给
   `unverified_numeric`，此时用 `--cite-map work/cite_map.csv`（列 `number,key`）把 `[1]`
   映射到 bib key 后复跑，即可逐条核验；无法映射的不要硬编造映射。
10. **守恒自检**：`python3 "$SKILL_DIR/scripts/kernel.py" verify --text /app/work/intro.md --evidence-dir /app/work --out /app/work`
    → `unsupported_numbers` 必须为 0，否则回改或进 `uncertainty`。
    `verify` 会先剔掉 Markdown 标题行（`## 3.2` 的节号不是数值论断）和引用标记，
    再把 `[3,5]`/`[3-5]`/`\cite{a,b}` 展开成单条逐号核对，并做 `3,000`≡`3000`、
    `3 %`≡`3%` 的等价归一；`corpus.txt` 缺失时以 `blocked` 退出 1 而不是抛栈。
    正文若为 GBK/GB18030 稿件会自动按 gb18030 解码（`draft_encoding` 记录实际编码）。
    **引用是否成立仍以 `work/claim_map.json` 的 `status` 为准**；`citations_not_in_sources`
    在 key 制文献库下对编号引用的提示，写进 `self_check.citation_check_note`。
11. **产出**：写 `work/draft.json`（`fields` 对齐契约，`artifacts` 放 intro.md、claim_map.csv、
    gap_table.csv、contribution_map.csv），
    `python3 "$SKILL_DIR/scripts/kernel.py" emit --draft /app/work/draft.json --contract-dir /app/work --out /app/output`，
    再 `python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract /app/work/contract.json` 必须 PASS。
    该门禁会核对契约字段非空、`source_map/changes` 结构、`intro/claim_map/gap_table/
    contribution_map` 是否真的落盘；`partial/blocked` 必须写 `limits`。
    `output_contract` 的四种写法（`{field:type}`、`{"fields":{…}}`、`{"fields":[…]}`、`[…]`）
    都会被 `init` 归一；契约即使自身列了 `case_id`/`status`，也不会把 `result.json` 的
    `case_id` 覆盖成 `null`。`changes`/`uncertainty`/`limits`/`notes`/`self_check`/`sources`
    允许为空但必须存在（无改动时不必编造改动记录），其余契约字段为空仍判 FAIL；
    契约字段若被塞在 `result["fields"]` 下会显式报错要求提升到顶层。
    `--contract-dir` 与 `--contract` 等价，传目录时自动拼 `contract.json`；契约文件缺失时
    只做结构检查并打印提示，不中断。

## 领域判定规则表

| 论断类型 | 证据要求 | 写法约束 |
|-|-|-|
| 背景事实 | ≥1 条引用支撑领域现状或规模 | 不用"近年来受到广泛关注"开头，直接给具体问题与约束 |
| 他人工作 | 每条引用对应其真实结论与适用条件 | 转述不得强于原文（`associated with` 不写 `causes`） |
| 研究空白 | ≥2 条已引文献的局限 + 未覆盖条件 | 空白必须能被本文方法回应，否则删 |
| 本文方法 | 材料中的方法描述 | 不引入未做过的模块或数据 |
| 本文贡献 | 图表/章节/数值指针 | 每条贡献一一对应证据，不夸大适用范围 |
| 作者判断 | 无文献可引时显式标注 | 用"我们推测/本文假设"，不进 `source_map` 当事实 |

### 综述堆砌的识别与处置

| 症状 | 判定 | 处置 |
|-|-|-|
| 连续 ≥3 句都是"X 做了 A[1]。Y 做了 B[2]。" | 逐篇摘要拼接 | 合并为同一维度的比较句，只保留差异与局限 |
| 单句 ≥3 条引用且未区分贡献 | 引用堆砌 | 拆句或改为"已有研究从 A、B 两路线展开[1-3]" |
| 引用只出现在段落末尾 | 挂载位置错误 | 移到被支撑的论断句 |
| 引用所在句只有"已有大量研究" | 装饰性引用 | 删引用或补该文献的具体结论 |
| 相关工作与本文方法无对照 | 分组失效 | 每组末尾补一句"与本文的差异" |

### 缺口推导模板（必须可复核）

```
已知：A 路线在条件 X 下有效，但受限于 Y [1,2]。
已知：B 路线覆盖了 Z，但未处理 W [3]。
因此：在 X+W 条件下，如何……仍未被回答。
本文：提出 M，在 X+W 下给出 E（Figure 2 / Table 1）。
```

## 硬性禁止

- 不引用文献库之外的条目；不凭记忆写作者、年份、DOI、期刊。
- 不把只有题名的文献写成"某研究表明……"；`title_only` 只能作为存在性引用。
- 不编造本文方法、数据规模、指标数值、图表编号或实验结论。
- 不用"近年来受到广泛关注/具有重要意义"等空转句替代具体问题。
- 不按时间顺序逐篇罗列；不做"作者 A 做了…作者 B 做了…"的摘要拼接。
- 不把作者判断写成文献结论；不夸大贡献适用范围与普适性。
- 不提交预制答案；产物必须由实际读取的输入推导。

## 输出

`/app/output/result.json`（回填契约全部字段 + `case_id`）+ 可编辑正文 + 三张核对表：

| 文件 | 内容 |
|-|-|
| `intro.md` | 引言与相关工作正文（四块结构，引用已嵌入） |
| `claim_map.csv` | 段落级/句级 `sid, section, role, citations, status, action` |
| `gap_table.csv` | `gap, cited_limitations, uncovered_condition, how_this_work_answers, locator` |
| `contribution_map.csv` | `contribution, evidence_pointer, boundary, verified` |
| `result.json` | `status` / `source_map` / `changes` / `uncertainty` / `limits` |

默认契约见 `references/output-contract.md`；题面 `output_contract` 优先。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 文献库为空或只有 1–2 条 | 只写"研究背景 + 本文贡献"框架，相关工作与空白标 `pending`，`status: partial` |
| 文献只有题名无摘要 | `capability: title_only`，只做存在性引用，不写具体结论 |
| 材料缺实验结果 | 贡献条目只写方法与设计，不写性能结论，`limits` 说明 |
| 已有草稿需保留结构 | 保留原有段落顺序与已核验引用，只改逻辑与缺口，`changes` 逐条记录 |
| 材料数字/结论冲突 | 两值都保留标 `conflict`，正文用中立表述并进 `uncertainty` |
| 目标期刊格式未知 | 用通用学术格式，`uncertainty` 说明未按特定期刊模板 |
| 语言与材料不一致 | 按 target_language 写作，术语首次出现给原文括注，不直译专名 |
| 超预算（900s / 64 请求） | 先落盘背景+贡献，相关工作标 `partial`，`limits` 列未完成段落 |
| `case.json` 非法 JSON / 非 UTF-8 | `init` 写 `{"status":"blocked","error":"case.json unreadable: …"}` 并退出 1，不再抛裸栈 |
| `case.json` 顶层是数组/字符串 | `init` 写 `blocked` + `error: case.json top level is list, expected object`，退出 1 |
| 材料路径不存在 | `index` 打印 `MISSING <path>` 并写进 `evidence.json.missing_materials`，不静默跳过 |
| 稿件为 GBK/GB18030 | 自动按 gb18030 解码，`evidence.json.files[].encoding` 与 `claims.json.draft_encoding` 记录实际编码 |
| 编号引用 + key 制文献库 | `unverified_numeric`（软）而非 `missing_ref`；用 `--cite-map` 映射后再复跑逐条核验 |
| 证据索引缺失就 `verify` | 以 `verdict: blocked` 退出 1 并提示先跑 `index`，不再 `FileNotFoundError` |
| `draft.json` 非法 JSON | `emit` 打印 `FAIL: draft unreadable: …` 并退出 2，不产出半成品 result.json |

## 文件说明

- `scripts/kernel.py`：init / index / verify / emit / check（仅标准库，无网络）。
- `scripts/claim_citation_linker.py`：句级 claim→citation 映射与七类引用问题检测
  （含编号引用对 key 制文献库的 `unverified_numeric`）。
- `references/intro-logic.md`：四块结构、分组维度、缺口推导与贡献模板。
- `references/claim-citation-rules.md`：论断—证据匹配规则、引用位置、堆砌反例。
- `references/output-contract.md`：默认输出字段；题面契约优先。

## 最小调用示例（示例，非正式案例结果）

```bash
SKILL_DIR=/skills/weekly-skill
python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out /app/work
python3 "$SKILL_DIR/scripts/kernel.py" index --materials /input/materials --out /app/work
# 建证据卡/文献卡 → 分组 → 缺口 → 贡献 → 写 /app/work/intro.md
python3 "$SKILL_DIR/scripts/claim_citation_linker.py" audit --draft /app/work/intro.md \
    --refs /input/materials/refs.bib --out /app/work
python3 "$SKILL_DIR/scripts/kernel.py" verify --text /app/work/intro.md --evidence-dir /app/work --out /app/work
python3 "$SKILL_DIR/scripts/kernel.py" emit --draft /app/work/draft.json --contract-dir /app/work --out /app/output
python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract /app/work/contract.json
```

示例输出（示意）：`intro.md` 含"研究背景 / 相关工作 / 研究空白 / 本文贡献"四节；
`claim_map.csv` 中 `S004` 标 `gap_unsupported` 并给出"补 ≥2 条局限"的处理建议；
`contribution_map.csv` 的 3 条贡献分别指向 `Figure 2`、`Table 1`、`Section 3.2`，
`result.json.status = "ok"`，`uncertainty` 记录 1 篇仅题名文献的引用限制。

## 改动记录

- **v1.1.0**（复核 63 分反馈后的迭代）
  - 失分点「可核验性 / 复得现」：`claim_citation_linker.py audit` 原来恒返回 0，审计结果只是
    打印，不能在定稿时拦住问题。现输出结构化 `verdict`，并支持 `--strict`（`verdict != pass`
    退出 1），把 `missing_ref / gap_unsupported / contribution_needs_evidence / stacked /
    decorative` 与结构问题都升为硬失败。
  - 失分点「结果完整性」：新增四块小节顺序自动检查（背景→相关工作→空白→贡献），
    `related` 存在但缺 `gap` 也报错；不再依赖临时手写 template json。
  - 失分点「贡献可核对 / 缺口有依据」：新增 `--gap-table` 与 `--contribution-map` 交叉校验——
    gap 每行 `cited_limitations` ≥2、必须填 `uncovered_condition`；贡献必须给出
    `Figure/Table/Section N` 形式且能在正文找到的指针，`verified` 非真给警告。
  - `kernel.py check` 升级为全量门禁（契约字段、`source_map/changes` 结构、
    `intro/claim_map/gap_table/contribution_map` 落盘、`partial` 必填 `limits`），
    并修复 `fields.limits` 被空值覆盖的缺陷。

- **v1.2.0**（本地合成夹具迭代 iter1）
  - **引用堆砌误判（主因）**：`claim_citation_linker.py` 的 `stacked` 只看句内引用条数，本 Skill
    自己推荐的概括式改写“已有研究从 A、B 两路线展开[1-3]”也会被判 `stacked` 并在 `--strict`
    下硬失败。现把 `路线/途径/方向/综述/概括/多个/若干/two/several/approaches` 纳入“已区分”
    线索；无分组线索的逐条堆砌（`A[1]，B[2]，C[3]`）仍然报 `stacked`。
  - **契约字段丢失**：`case.json` 未给 `output_contract` 时 `contract={}`，`emit` 的
    `if isinstance(fields, dict)` 分支遍历空字典，`artifact_path/source_map` 等 draft 字段被静默丢弃，
    仍打印 `missing_contract_fields=none`。现空契约时回落为整体复制 `draft.fields`。

- **v1.3.0**（本地合成夹具迭代 iter2；以下每条均为实测输出）
  - **句子切分错误（主因）**：`claim_citation_linker.py` 把 `（Fig. 2）` 的缩写句点当句末，
    一个论断被切成 `…（Fig.` 与 `2），并以…` 两段，句数由 10 虚增为 11 且断言被误判。
    新增 `ABBREV`（`Fig/Figs/Table/Eq/Ref/No/vs/cf/al/e.g/i.e/approx`）保护后再切分，
    实测 `sentences=10`（原 11）。
  - **章节误挂**：句 span 从上一节末尾的空白起算，标题后的句子被挂到上一节（贡献句 S009
    被标成"研究空白"）。改为 `m.start() + lead` 指向首个非空字符后，S009 正确归入"本文贡献"。
  - **编号引用对 key 制文献库全量硬失败**：draft 用 `[1]`–`[3]`、`refs.bib` 只有 key 时，
    每条引用都判 `missing_ref` 使 `--strict` 必然失败。现判 `unverified_numeric`（软），
    并提供 `--cite-map work/cite_map.csv`（列 `number,key`）把 `[1]`→`liu2019uv` 后逐条核验；
    实测 `--cite-map` 下 `citations=10 orphan_refs=0 verdict=review`（ok 9 / needs_citation 1）。
  - **空白句误判为 related**：`…仍未被回答` 这类缺口句因未命中 cue 被判 `needs_citation`。
    `CUES["gap"]` 补 `仍未被|尚不清楚|尚未见|未见报道|仍未知|待回答|not yet|unaddressed` 后，
    未补引用时正确报 `gap_unsupported`，补 `[2,3]` 后消失。
  - **贡献句漏识别**：`本文在 3% 氮掺杂体系上给出…` 未命中 `contribution` cue。
    放宽为 `本文[^。；，]{0,12}?(?:提出|设计|构建|贡献|实现|给出)` 后判为贡献句，
    并把 `role_of` 顺序调为 `boundary → gap → contribution → result → background`，
    避免"限于…"被背景词抢占。
  - **`case_id` 被契约置空**：契约自身列出 `case_id` 时 `emit` 用 `draft_fields.get(name)`
    覆盖，`result.json.case_id=null` 且 `check` FAIL。现 `emit` 跳过 `case_id`/`status`，
    实测输出 `case_id=intro-case-01` 且 `check PASS`。
  - **契约四形态**：`init`/`emit`/`check` 统一走 `normalize_contract()`，
    `{field:type}`、`{"fields":{…}}`、`{"fields":[…]}`、`[…]` 均可用；列表契约实测
    `contract_fields=3`。
  - **非法 `case.json` 裸栈**：改为写 `blocked` 契约并退出 1；顶层非对象同样 blocked（实测
    `case.json top level is list, expected object`）。`draft.json` 非法 JSON 时 `emit` 退出 2。
  - **`verify` 双重误报**：`## 3.2` 的节号与 `[37]` 引用被当数值/文献检索，实测旧逻辑报
    `unsupported_numbers=2`。现剔除标题行与引用标记、`_num_forms()` 归一（`3,000`≡`3000`、
    `3 %`≡`3%`）、`[3,5]`/`[3-5]`/`\cite{a,b}` 展开逐号核对；实测同一稿件
    `unsupported_numbers=0`（仅剩 `[1]` 因 key 制文献库提示）。
  - **GBK 稿件变乱码**：`extract` 用 `utf-8/replace` 读文本，GBK 中文稿全变 U+FFFD 后
    `verify` 报"无可核数值"。新增 `decode_text()`（utf-16 BOM → utf-8-sig → gb18030 → replace），
    实测 GBK 材料 `encoding=gb18030`、GBK 稿件 `unsupported_numbers=0`。
  - **材料路径不存在被静默忽略**：`index` 过滤 `os.path.exists` 后不提示。现打印
    `MISSING <path>` 并写 `missing_materials`（实测 `['/tmp/bohrium_iter4/adv/nope']`）。
  - **`check` 逼人造改动记录**：空 `changes`/`uncertainty` 被判 `contract field empty/missing`。
    现 `allowed_empty = {changes, uncertainty, limits, notes, self_check, sources}`，
    存在的空数组通过；契约字段嵌在 `result["fields"]` 下显式报错；`--contract-dir` 与
    `--contract` 等价，契约缺失只提示不中断。
  - **平台路径**：新增"平台运行路径"节，全部命令改为 `python3 "$SKILL_DIR/scripts/…"`
    绝对调用（`SKILL_DIR=/skills/weekly-skill`），避免 cwd=`/app` 时相对路径失效。
