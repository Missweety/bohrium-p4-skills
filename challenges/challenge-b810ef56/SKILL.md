---
name: claim-evidence-writer
description: 把需要文献支撑的写作任务拆成「论断清单 → 证据表 → 成稿」三段：先切分可判定论断，再为每条匹配原文引用与章节/页码定位，按 材料支持 / 材料未涉及 / 与材料冲突 三态标注并给出强度与限定语，冲突不裁决只列待核清单，最终输出 claim-evidence 表与带论断编号的可编辑成稿。不适用于无材料的自由创作、纯语言润色或文献检索。
version: 1.3.0
license: MIT
---

# 文献证据驱动写作（writing 赛道）

核心不是"多写几段"，而是让稿件里每一句有依据的话都能被指认 **依据在哪里、依据有多强、哪里还没核**。
交付物是三件套：**论断清单 → claim-evidence 表 → 成稿**，三者用 `C1/C2...` 编号互相指认。

## 平台路径（务必按此执行）

评测时 Skill 装在 `/skills/weekly-skill`，工作目录通常是 `/app`，**两者不同**；相对路径
`scripts/...` 会直接 `can't open file`。所有命令都用绝对路径调用，解释器统一 `python3`：

```bash
SKILL_DIR=/skills/weekly-skill        # 若你确实在 skill 目录内，也可写 SKILL_DIR=.
python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out /app/work
```

下文为可读性省略了 `$SKILL_DIR/`，执行时必须补全。

## 何时使用

触发（满足任一）：

- 给定文献/摘录/笔记/PDF，要求写综述、引言、讨论、结论或"带引用的段落"；
- 要求核查已有稿件中某句是否有依据、引用是否支持该句；
- 要求整理"论断—证据"对照表、证据强度或待核清单。

不触发：没有任何材料却要求给结论（属自由创作/编造）；只改语言不改事实（润色类）；
只要文献列表不写正文（检索类）。遇到这类请求先说明缺什么，再决定是否降级。

## 输入

`/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`；材料由题面提供
（pdf/md/docx/txt/csv/图片）。**先读真实文件**：字段名不固定，用 `kernel.py init` 做宽松识别；
`index` 抽不出文字的 PDF（扫描件）记 `unreadable`，**不得用模型记忆补原文**。

## 执行流程

1. **契约**：`python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out work`
   → `work/contract.json`（case_id、output_contract）。题面字段一个都不能少。
2. **证据索引**：`python3 "$SKILL_DIR/scripts/kernel.py" index --materials <材料...> --out work`
   → `work/evidence.json`（文件、字符数、sha1、可读性）+ `work/corpus.txt`（统一文本，定位基准）。
3. **论断切分**：把任务要求与初稿拆成单句可判定的论断（一条论断只含一个可核事实/因果/比较）。
   写入 `work/claims.json`：`{id, text, type: factual|causal|comparative|method|claim_of_consensus}`。
   规则见 `references/claim-splitting.md`；一条长句含两个断言就拆成 `C3a/C3b`。
4. **证据抽取**：为每条论断从 `corpus.txt` 找**最短可支撑片段**，记录
   `{source, locator, quote}`；locator 用 `line`/`p.`/`§`/`row`，quote 必须逐字来自材料。
   摘要不足以支撑时继续找正文；找不到就进入"材料未涉及"，**不许改写原句来"制造"支持**。
5. **三态判定**（本题核心，见 `references/evidence-states.md`）：
   - `supported`：至少一条 quote 直接支持该论断，且强度与表述相称；
   - `not_covered`：材料中无相关陈述 → 证据留空，`note` 写检索范围与关键词；
   - `conflict`：材料内部存在相反/不一致陈述 → 两条 quote 都保留，**不裁决**，进待核清单。
6. **矩阵校验**：`python3 "$SKILL_DIR/scripts/claim_evidence_matrix.py" --matrix work/matrix.json --corpus work/corpus.txt --base <材料根> --out work/evidence_check.json --md work/claim_evidence.md`
   逐条校验：quote 是否逐字命中**且落在所引源文件**（按 `===== FILE: =====` 分块核对，防"张冠李戴"）、
   三态与证据数是否自洽、`supported` 是否给出了真实强度、数字是否在材料中出现（按数字边界比对，
   `12` 不会被 `112.4` 放行）。`--base` 是 `evidence.source` 相对路径的基准目录；材料在
   `/input/materials` 时写 `--base /input`，否则会误报 `missing_source`。
   必须 `verdict != fail`、`errors` 清零后才能进入写作。标点/换行差异会以
   `quote_normalized_match` 警告提示，需人工确认是否只是排版差异。
   矩阵或语料缺失 / 不是合法 JSON 时脚本直接报错并退出 2，**不会抛栈**，按提示修路径或语法。
7. **成稿**：按 `task.md` 的体裁/受众/语言写作；**每个含事实的句子标注论断号**（如 `…（C4）` 或脚注），
   句子表述与证据强度匹配：related≠caused、单研究≠共识、动物/体外≠人群。
   `not_covered` 的论断只能写成研究缺口或删除；`conflict` 的论断写"材料间存在分歧"并指向待核编号。
8. **守恒自查**：`python3 "$SKILL_DIR/scripts/kernel.py" verify --text work/draft.md --evidence-dir work --out work`
   → `unsupported_numbers`、`citations_not_in_sources` 清零或逐条进 `uncertainty`。
9. **产出**：写 `work/draft.json`（字段见 `references/output-contract.md`），
   `python3 "$SKILL_DIR/scripts/kernel.py" emit --draft work/draft.json --contract-dir work --out /app/output`；
   同时落盘 `manuscript.md`、`claim_evidence.md`、`claims.json`。
   **定稿前复跑一致性校验**：`claim_evidence_matrix.py … --manuscript work/draft.md`，
   要求成稿中每个 `supported/conflict` 论断都能找到 `（C#）` 标注，且成稿没有矩阵外的编号。
10. **收尾**：`python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract work/contract.json` 必须 PASS；
    该门禁会核对 `case_id` 与契约一致、契约字段非空、`source_map/changes` 结构、
    `manuscript`/`claim_evidence` 实际落盘；`partial/blocked` 必须写 `limits`。
    `changes`/`uncertainty` 允许是空数组（真的没改动、真的没有待核项），门禁只要求存在且类型正确——
    **不要为了过门禁编造条目**。契约支持 `{field: type}` / `{"fields": {...}}` / `{"fields": [...]}` /
    `["field", ...]` 四种写法；`case_id` 只从 case 文件取，不会被 `fields` 覆盖成 null。

## 领域规则表

| 维度 | 规则 |
|-|-|
| 找得到 | 每条论断有编号；每条 `supported` 有 `source + locator + quote`，quote 逐字可回查 |
| 对得上 | quote 必须真的支持**这句**话；只能支撑更弱结论时，降级表述或标 `partial_support` |
| 三态不混 | 三态只能是 `supported / not_covered / conflict`；"大概有文献说过"不算支持 |
| 冲突不裁决 | 材料互相矛盾时并列两方证据与位置，写"存在分歧"，进待核清单，不选边 |
| 强度相称 | 综述/单中心/小样本/体外 → 用 `may/suggest/associated with`；不写 `proves/causes` |
| 不上升 | 相关性不写成因果；单篇不写成领域共识；机制未明要写"机制尚不清楚" |
| 数字可溯 | 每个数值来自材料并带定位；缺定位的数字删除或标 `uncertain` |
| 引用真实 | 只用材料中出现的文献；缺元数据标 `missing_citation`，**不臆造 DOI/卷期页码** |
| 可复核 | `claim_evidence.md` 的每一行能独立回查；成稿论断编号与表格编号一致 |

## 硬性禁止

- 不新增材料外的文献、DOI、样本量、效应量、p 值或"领域共识"。
- 不把 `not_covered` 写成"已有研究表明"；不把 `conflict` 单方裁决成结论。
- 不伪造"已核对原文/已查数据库/已联系作者"等状态。
- 不用模型记忆里的文献条目充数；不把摘要当全文却声称"全文核实"。
- 不提交预制答案；不生成脱离本次输入的证据表。

## 输出

`/app/output/`：

- `manuscript.md`：成稿，含论断编号，可继续编辑
- `claim_evidence.md`：claim-evidence 表（论断 / 三态 / 强度 / 原文引用 + 定位 / 待核）
- `claims.json`：机器可读的论断与证据（含 `state`、`strength`、`note`）
- `result.json`：`case_id` + 契约全部字段 + `source_map` + `changes` + `uncertainty` + `limits`

`uncertainty` 至少覆盖：`not_covered` 论断、`conflict` 待核项、仅有摘要的条目、不可读材料。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 文献不可得 / 仅摘要 | 只按摘要能支持的强度标注（通常是 `weak`），`note` 写"仅摘要"，成稿加限定语 |
| 原文与摘要矛盾 | 两处都记录，标 `conflict`，以原文为准的表述需人工确认，不擅自采信 |
| 证据互相冲突 | 不裁决；并列引用 + "存在分歧" + 待核编号 |
| 材料不可读（扫描 PDF） | 标 `unreadable`，不进证据表；缺口写入 `uncertainty` |
| 材料超长 | 先按章节建索引，只对当前论断检索相关段落，记录检索范围 |
| 预算不足（900s/64 请求） | 先落盘已完成的论断与表格，`status: partial`，`limits` 列出未处理论断 |
| 论断无法判定 | 标 `not_covered` 或 `uncertain`，写明缺什么，不猜 |
| `case.json` 非法 JSON / 顶层非对象 | `init` 不抛栈：写 `contract.json{status:blocked, error}` 并退出 1 |
| 矩阵 JSON 非法 / 语料缺失 | `claim_evidence_matrix.py` 打印 `matrix is not valid JSON (...)` 或 `missing corpus: ...`，退出 2 |
| 材料非 UTF-8（GBK/latin-1 等） | `evidence.json` 逐文件记 `encoding: non-utf8` 并提示人工核对数字/姓名；不静默采用 |
| 材料路径不存在 / 目录为空 | `evidence.json.missing_materials` 记录并打印；不按记忆补证据 |
| 输出目录已存在 | 全部写入 `exist_ok=True` 覆盖，重复运行结果一致 |
| 矩阵编号重复 | 矩阵脚本报 `duplicate_id` 错误，改号后再写稿 |
| python 不可用 | 手工执行等价校验（quote 能否在原文检索到、状态与证据数是否自洽），在 `limits` 说明 |

## 文件说明

- `scripts/kernel.py`：init / index / verify / emit / check，仅标准库，无网络。
- `scripts/claim_evidence_matrix.py`：矩阵结构校验 + 三态自洽 + quote 逐字命中及**所属源文件**核对 +
  成稿编号双向一致性（`--manuscript`）+ Markdown 表格渲染。
- `references/evidence-states.md`：三态判定口径、强度分级、限定语对照与反例。
- `references/claim-splitting.md`：论断切分规则与边界案例。
- `references/output-contract.md`：默认输出字段；题面 `output_contract` 优先。

## 最小调用示例（示例，非正式案例结果）

```bash
python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out work
python3 "$SKILL_DIR/scripts/kernel.py" index --materials /input/materials --out work
python3 "$SKILL_DIR/scripts/claim_evidence_matrix.py" --matrix work/matrix.json --corpus work/corpus.txt \
    --base /input --out work/evidence_check.json --md work/claim_evidence.md
python3 "$SKILL_DIR/scripts/kernel.py" verify --text work/draft.md --evidence-dir work --out work
python3 "$SKILL_DIR/scripts/kernel.py" emit --draft work/draft.json --contract-dir work --out /app/output
python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract work/contract.json
```

示意输出（示例）：`evidence_check.json` → `{"verdict":"review","errors":[],"warnings":["C5: number 12.4 not found in corpus"]}`；
`claim_evidence.md` → 一行 `| C3 | 处理组降解率更高 | supported | moderate | "处理组 12.4%" · facts.md:3 | — |`；
`result.json` → `{"case_id":"demo","status":"ok","claim_evidence":"claim_evidence.md"}`。

## 改动记录

- **v1.1.0**（复核 62 分反馈后的迭代）
  - 失分点「对得上 / 引用准确性」：原脚本只检查 quote 是否在**整份语料**里出现过，不校验是否来自
    所引源文件，存在"张冠李戴"漏检。现按 `===== FILE: =====` 分块核对，新增 error
    `quote_not_in_cited_source`。
  - 失分点「复得现 / 可复核」：新增 `--manuscript` 双向一致性校验——`supported`/`conflict`
    论断必须带 `（C#）` 标注，成稿出现的编号必须存在于矩阵（`unknown_claim_id_in_manuscript`）。
  - 失分点「quote 逐字匹配过严」：新增 NFKC + 全半角标点 + 破折号 + 空白归一化回退，
    归一化后命中的给 `quote_normalized_match` 警告而不是直接判死，减少 PDF 抽取噪声导致的误报。
  - 失分点「说得准」：新增 `supported` 强度不得为 `none`（error）、`not_covered` 强度应为
    `none/weak`（warning）；`kernel.py check` 升级为全量门禁（契约字段、source_map/changes 结构、
    manuscript/claim_evidence 落盘、partial 必填 limits），并修复 `fields.limits` 被空值覆盖。

- **v1.2.0**（本地合成夹具复核后的迭代）
  - 失分点「对得上 / 引用真实性」：quote 校验原先是纯子串匹配，材料写 `112.4%` 时伪造的
    `12.4% in run 7` 会被判为逐字命中，矩阵直接 `pass`。现要求英文/数字两端落在词与数字边界
    （`bounded`），归一化分支改为折叠空白而非删除空白；中文 quote 仍按原样匹配。
  - 失分点「异常处理 / 运行稳定性」：`claims` 被写成对象（`{"C1": {...}}`）时脚本以
    `AttributeError` 崩溃。现在对象形式按 `values()` 归一化，非对象条目报 `bad_claim_entry`
    并以 `verdict=fail` 退出，不再抛栈。

- **v1.3.0**（本地合成夹具迭代 iter2；夹具 `/tmp/bohrium_iter2/ch02`，虚构材料，非正式案例）
  - **`verify` 把标题号与引用号当数值**：原实现对全文直接跑数字正则，`## 3.2` 与 `[37]` 被计入
    `unsupported_numbers`（实测 `unsupported_numbers=2`），而 SKILL 要求该项为 0——等于要求 agent
    改标题或改引用才能"通过"。现扫描前剔除 Markdown 标题行与引用标记，并做百分号/空格/千分位
    归一（`_num_forms`），同一输入 `unsupported_numbers=0`，`[37]` 转入 `citations_not_in_sources`。
  - **合并引用误报**：`[3,5]` 被整串比对语料，恒报 `citations_not_in_sources`。现展开逐号核对
    `"[n]"`，`\cite{a,b}` 逐 key 核对。
  - **契约含 `case_id` 时结果为 null**：`emit` 先写契约的 `case_id`，再用 `fields` 的空值覆盖，
    `result.json.case_id=null`、`check` 报 FAIL（实测 `missing_contract_fields=['case_id']`）。
    现 `case_id`/`status` 只取 case 与 draft。列表契约（`output_contract: ["..."]`）此前把
    draft 整体塞进 `result["fields"]`，顶层没有任何契约字段；现统一 `normalize_contract()` 展平四种形态。
  - **门禁逼人编造**：`check` 对 `changes`/`uncertainty` 的空数组报
    `contract field empty/missing`（实测"真的没有改动、真的没有待核项"也 FAIL），会诱导补假条目。
    现将 `changes/uncertainty/limits/notes/self_check` 设为"存在且类型正确即可空"。
  - **矩阵数字漏报**：`number_not_in_corpus` 用子串匹配，材料只有 `112.4%` 时论断里的
    `12 samples` 不报警。改为 `bounded()` 数字边界比对，实测报 `number_not_in_corpus number 12`；
    真实数值（`66.7%`）仍不误报。
  - **矩阵脚本裸栈**：非法 JSON、缺失语料原先直接 traceback。现打印
    `matrix is not valid JSON (...)` / `missing corpus: ...` 并退出 2；`--base` 补文档
    （材料在 `/input/materials` 时须 `--base /input`，否则 `missing_source` 误报）。
  - **表格渲染**：论断或 quote 含换行时整行断裂，现统一折叠为空格并转义 `|`。
  - **材料异常**：`index` 补记 `missing_materials` 与逐文件 `encoding`（非 UTF-8 提示人工核对）。
  - **命令与路径**：全部命令改为 `python3 "$SKILL_DIR/scripts/..."` 绝对调用（平台装在
    `/skills/weekly-skill`、cwd 为 `/app`），任意 cwd 实测走通 init→index→矩阵→verify→emit→check。

