---
name: results-discussion-writer
description: 把数据表、图表与图注、统计输出写成可投稿的结果与讨论章节：结果段按图表首次引用顺序逐段陈述观察，报告 n/均值/误差口径/检验统计量/p 值；讨论段区分"本研究观察"与"文献报告"，因果表述按证据强度限界，局限落到具体层面。输出章节 Markdown、图表读数台账、论断—来源映射与统计表述审计报告。用于撰写或改写 Results / Discussion 章节；不适用于无数据时编造趋势、替代统计分析或纯语言润色。
version: 1.3.0
license: MIT
---

# 结果与讨论章节写作：读数可回溯、因果有边界

把"数据已在手、图已画好"变成 **读数台账 → 发现清单 → 结果段（只陈述观察）→ 讨论段（证据对照）→ 机器审计 → 可编辑交付**。
核心主张：**正文每个数值回指某张图/表/统计输出；每个趋势的措辞强度与检验结果匹配；
每条因果表述要么有干预证据，要么降级为相关。**

## 何时使用

触发：用户给出数据表（csv/xlsx）、图表/图注（图片、md、pdf）、统计输出，要求写 Results、
Discussion、结果与讨论合并章，或要求"把图写成正文""按图序写结果""补讨论与局限"。

不触发：没有任何数据却要求给出趋势或显著性；要求替用户跑统计并产出新结论（应转分析类 Skill）；
纯语言润色；只写方法章。遇到这类请求先说明缺什么数据，再决定是否降级为"框架 + 缺口清单"。

## 输入

`/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`；材料可能是
csv/xlsx、图片、docx/pdf。**先读真实文件**，用 `kernel.py init` 做宽松识别；图片材料无法自动读数时
只登记"存在 + 可见元素"，不得凭图猜精确数值。字段名不固定，不要按标签假设内容。

## 平台运行路径（必须遵守）

平台把本 Skill 装到 `/skills/weekly-skill`，命令的工作目录是 `/app`，**不在 Skill 根目录**。
所有脚本必须用绝对路径调用，否则 `python scripts/kernel.py` 会因找不到文件直接失败：

```bash
SKILL_DIR=/skills/weekly-skill
python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out /app/work
```

材料在 `/input/materials`，产物写 `/app/output`。若题面写 `materials/...` 而实际位于
`/input/materials`，`index` 会打印 `MISSING <path>` 并写进 `evidence.json.missing_materials`，
补全路径后复跑。

## 执行流程

1. **契约**：`python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out /app/work` → `work/contract.json`。
2. **证据索引**：`python3 "$SKILL_DIR/scripts/kernel.py" index --materials <材料路径...> --out /app/work` → `work/evidence.json` + `work/corpus.txt`；
   unreadable 文件如实记录，不猜内容。
3. **读数台账**：建 `work/figure_readout.json`，每个数值一条：
   `{"fig":"Figure 2A","value":"15.1","unit":"%","stat":"mean","error":"SD 2.2","n":10,"source_path":"materials/stats.csv","locator":"row 3"}`。
   图与表/图注冲突时两值并列并标 `conflict: true`；只能目测时 `value` 留空并标 `missing: true`。
4. **发现清单**：按图表首次引用顺序列 `work/discoveries.json`（每段一个发现：`finding_id`、`figures`、
   `direction`、`magnitude`、`stats`），一个发现只对应一个主图，避免流水账与主次不分。
5. **章节骨架**：`work/section_template.json`（结果 / 讨论 / 局限；min_words 按材料长度设定）。
6. **写作**：
   - 结果段：按图序，每段一个发现，句式"在 X 条件下，A 组（n=…）均值…（SD…），高于/低于 B 组
     （统计量、p）"；只写观察，不写机制。
   - 讨论段：每段一个论断，写明"本研究观察 → 与文献一致/不一致 [n] → 可能原因（标推测）"；
     因果句必须先有干预或随机化证据。
   - 局限段：落到样本/测量/设计/统计四层中至少两层，并说明影响哪条结论。
7. **统计表述审计**：`python3 "$SKILL_DIR/scripts/stat_claim_checker.py" --draft /app/work/results_discussion.md --corpus /app/work/corpus.txt --map /app/work/claim_map.json --out /app/work/stat_check.json --strict`
   要求 `verdict=pass`（`--strict` 下 review 退出码为 1）：显著必须带 p 与 n、均值必须标 SD/SEM/CI、
   因果必须能指到干预证据、文献断言必须带引用、每张图/表都要在结果段被引用、讨论段不引入新数值、
   数值必须能回到 corpus 或 `claim_map`。材料本身缺某要素时按异常表降级并写 `limits`。
   - `significance` 中 `p_value=false` 或 `n=false` → 补 n/统计量/p，或降级措辞；
     只写“p 值见补充材料/待补”而没有具体数值不算报告了 p 值。
   - `dispersion.error_defined=false` → 补 SD/SEM/CI 口径；
   - `causal` 中 `intervention_evidence=false` → 改相关表述；
   - `literature` 非空 → 补引用或删掉文献性断言；
   - `figures.*.first_citation_order` 非 1..k → 调整引用顺序或编号；
   - `limitations.specific=false` → 重写局限；
   - `unsourced_numbers` 必须清零或逐条进 `uncertainty`。`p < 0.001`、`p ≤ 0.05` 这类**报告阈值**
     会被自动排除（语料里存的是精确 p，如 0.0001），不要把阈值当成"无出处数值"；
   - `claim_map` 文件存在但不是合法 JSON → `problems` 而非静默当作空映射（verdict=fail）。
8. **章节审计**：`python3 "$SKILL_DIR/scripts/section_audit.py" --draft /app/work/results_discussion.md --map /app/work/claim_map.json --template /app/work/section_template.json --corpus /app/work/corpus.txt --out /app/work/audit.json`，要求 `verdict != fail`。
   字数按**中文字符 + 英文词**统计（旧版把一整句中文算成 1 个词，900 字的段落被报成"12 词，过短"）；
   章节正文按**标题文本**定位（旧版按模板下标取正文，正文里多一个"摘要"标题就让后面每节错位）。
9. **数值/引用守恒**：`python3 "$SKILL_DIR/scripts/kernel.py" verify --text /app/work/results_discussion.md --evidence-dir /app/work --out /app/work`，两个计数为 0 才可交付。
   该步会剔除标题行与引用标记、把 `[3,5]`/`[3-5]`/`\cite{a,b}` 展开逐号核对、做
   `3,000`≡`3000`、`42.3%`≡`42.3` 的等价归一（CSV 一行 `10,42.3,2.1` 会被拆成独立数字索引），
   并排除 p 值报告阈值；语料缺失时以 `blocked` 退出 1。
10. **产出**：`work/draft.json` → `python3 "$SKILL_DIR/scripts/kernel.py" emit --draft /app/work/draft.json --contract-dir /app/work --out /app/output`；
    随后 `python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract-dir /app/work` 必须 PASS：
    逐项核对契约字段与四个必交工件（`results_discussion.md` / `figure_readout.json` /
    `claim_map.json` / `stat_check.json`）与 `partial` 的 `limits`。

预算纪律（64 请求 / 900s / 16k tokens）：先落 `figure_readout.json` 与结果段，再写讨论；
时间不足时保全"结果段 + 统计口径 + 局限"，讨论中的文献对照标 `partial`。

## 领域规则（按评分维度）

| 维度 | 规则 | 检查点 |
|-|-|-|
| 读得准 | 数值/单位/误差棒含义/有效数字与源一致；只目测时不给精确值 | `figure_readout` + `unsourced_numbers` |
| 分得清 | 结果段只写观察；讨论段承担解释、文献对照与局限；讨论不引入新数值 | `sectioning.*`、`interpretation inside results` |
| 说得住 | 显著=有 p 与 n；趋势未达显著要直说；相关不写因果 | `significance`、`dispersion`、`causal` |
| 核得了 | 每个数值回指图表/统计输出；每条论断对应本研究数据或具体文献 | `claim_map` + `literature` |
| 交代清楚 | 阴性结果、不一致文献、局限与适用边界都写 | `limitations`、讨论段自检 |

表述强度对照：`p < 0.05` → "显著高于/低于"；`p ≥ 0.05` → "未达显著差异（p = …）"；
仅观察性相关 → "与…相关/associated with"；机制 → "可能通过…（推测）"。

## 硬性禁止

- 不新增材料外的数值、n、p 值、图号、文献条目；不把目测值写成精确小数。
- 不在结果段写机制或因果；不把相关写成因果；不隐去阴性结果与不一致证据。
- 不混用 SD/SEM/CI 口径；不改有效数字位数为"看起来更整齐"。
- 不写"未来将进一步深入研究"这类空话局限；局限必须指向具体层面与受影响结论。
- 不伪造统计检验或"已做多重比较校正"；不提交预制答案。

## 输出

`/app/output/result.json`（回填契约全部字段 + `case_id`），以及：
`results_discussion.md`（可编辑章节）、`figure_readout.json`（图表读数台账）、
`claim_map.json`（论断—来源映射）、`stat_check.json`（统计表述审计）。
主产物路径写入 `artifact_path`；字段见 `references/output-contract.md`。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 缺统计输出（只有图） | 只写方向与量级，`p`/`n` 标 `[MISSING]`，`status: partial` |
| 图注与正文/数据表冲突 | 两值并列 + `CONFLICT`，正文用保守表述，进 `uncertainty` |
| 单位不明 | 写"单位见原图/待确认"，不擅自补 unit |
| 引用找不到对应文献 | 标 `[MISSING: citation]`，删除该文献性断言或降为"尚不清楚" |
| 图片无法读数 | 记录可见元素，标 `missing: true`，不猜小数 |
| 只有结果没有讨论材料 | 讨论段只写与本研究数据直接相关的解释，其余标 partial + limits |
| 超预算（900s / 64 请求） | 先落盘结果段与审计，`status: partial`，`limits` 列未写小节 |
| 无 python 环境 | 按 `references/results-discussion-rules.md` R1–R8 手工核对，`limits` 说明降级 |
| `case.json` 非法 JSON / 顶层非对象 | `init` 写 `{"status":"blocked","error":"case.json unreadable: …"}`（或 `top level is list, expected object`）并退出 1，不抛裸栈 |
| 材料路径不存在 | `index` 打印 `MISSING <path>` 并写入 `missing_materials`，不静默跳过 |
| 材料/稿件为 GBK/GB18030 | 自动按 gb18030 解码，`evidence.json.files[].encoding` 与 `claims.json.draft_encoding` 记录实际编码 |
| 材料首行是 `[1] Smith…` | 不再被误判为 UNREAD（旧判定是"文本以 `[` 开头即不可读"） |
| 稿件文件不存在 | `section_audit` 写 `verdict: fail` 报告并退出 1，不再 `FileNotFoundError` |
| `claim_map.json` 非法 | `stat_claim_checker` 报 `claim map unreadable (invalid JSON)` 并判 fail，不当作空映射放过 |
| `draft.json` 非法 | `emit` 打印 `FAIL: draft unreadable: …` 并退出 2 |

## 文件说明

- `scripts/kernel.py`：init / index / verify / emit / check（仅标准库）。
- `scripts/stat_claim_checker.py`：显著性/离散度/因果/图序/图表引用覆盖/章节分工/文献引用/局限/数值溯源审计（仅标准库，`--strict` 可作交付门禁）。
- `scripts/section_audit.py`：章节完整性 + 数值绑定 + 绝对化措辞审计。
- `references/results-discussion-rules.md`：R1–R8 规则与反例（可直接复用为自检清单）。
- `references/figure-reading-rules.md`：读数优先级、单位/误差/有效数字/多面板规则。
- `references/output-contract.md`：默认输出字段；题面 `output_contract` 优先。

## 最小调用示例

```bash
SKILL_DIR=/skills/weekly-skill
python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out /app/work
python3 "$SKILL_DIR/scripts/kernel.py" index --materials /input/materials --out /app/work
# 建 /app/work/figure_readout.json、/app/work/claim_map.json，写 /app/work/results_discussion.md
python3 "$SKILL_DIR/scripts/stat_claim_checker.py" --draft /app/work/results_discussion.md \
    --corpus /app/work/corpus.txt --map /app/work/claim_map.json --out /app/work/stat_check.json --strict
python3 "$SKILL_DIR/scripts/section_audit.py" --draft /app/work/results_discussion.md --map /app/work/claim_map.json \
    --template /app/work/section_template.json --corpus /app/work/corpus.txt --out /app/work/audit.json
python3 "$SKILL_DIR/scripts/kernel.py" verify --text /app/work/results_discussion.md --evidence-dir /app/work --out /app/work
python3 "$SKILL_DIR/scripts/kernel.py" emit --draft /app/work/draft.json --contract-dir /app/work --out /app/output
python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract-dir /app/work
```

## 改动记录

### v1.1.0（因 #89190 harbor_reward 0.58 迭代）

- **可机检项（主因）**：`stat_claim_checker.py` 原先 `review` 也返回 0，告警（缺 p/n、缺误差口径、
  无干预证据的因果、未引用文献、数值无出处）不会阻断交付。新增 `--strict`，流程要求 `verdict=pass`
  才可 emit；材料确实缺要素时按异常表降级并写 `limits`。
- **完整性**：新增“材料里出现但结果段未引用”的图表检测（`figures.*.not_cited` /
  `present_in_material`），对应评分项“按图表首次引用顺序逐段陈述”和遗漏图表的常见失分。
- **输入兼容性**：`claim_map.source_path` 改为多基准解析（映射文件目录、cwd、corpus 目录、`/input`），
  避免相对路径被误判为“文件不存在”而整份报告 fail；缺 `source_path` 与路径失效分开报错。
- **输出契约**：`kernel.py check` 原只查 `case_id`/`status`；现核对契约字段、四个必交工件
  （`results_discussion.md`/`figure_readout.json`/`claim_map.json`/`stat_check.json`）、
  `partial` 的 `limits`；`emit` 修复 `uncertainty` 为 None 时未回填 `[]` 的问题并带回 `self_check`。

示意输出（**示例，不是案例答案**）：`results_discussion.md` 含 3 个结果段（对应 Figure 1–3，
均带 n 与 SD 口径）与 1 个讨论段 + 1 个局限段；`stat_check.json` 的 `warnings` 为空，
`figures.figure.first_citation_order` 为 `[1, 2, 3]`。

### v1.2.0（本地合成夹具迭代 iter1）

- **显著性假通过（主因）**：`PVAL_RE` 原来把裸词“p 值”也算作已报告 p 值，于是
  “差异显著（p 值见补充材料）”在 `--strict` 下仍判 `p_value=true` 通过，违反“显著必须带 p 与 n”。
  现只认 `p = 0.03` / `p < 0.001` / `p 值 = 0.03` 这类带数值的写法，裸“p 值”判 `p_value=false` 并告警。
- **数值误判**：`unsourced_numbers` 用原样 token 做子串比对，正文写“66.67%”而数据表只有 `66.67`
  时被判无出处，且无法在诚实前提下清零。现按空格/百分号/千分位归一比对；`66.7%` 与数据
  `66.67` 等真实差异仍会报出。
- 归零项（合成夹具实测）：占比数值 `unsourced_numbers=[]`；“p 值见补充材料”转为告警；
  真缺失 p 值与错值 `66.7%` 的负例仍分别告警。

### v1.3.0（本地合成夹具迭代 iter2；每条均为实测输出）

- **p 值阈值被当"无出处数值"（主因）**：`p < 0.001` 是报告惯例，语料里存的是精确 p（0.0001），
  旧 `unsourced_numbers` 把 0.001 判为无出处，`--strict` 因此**永远无法 pass**，
  而诚实作者无法通过删句或改数来清除。三个脚本统一引入 `P_THRESH`，把
  `p < ≤ > ≥ ≈` 形式的阈值排除在数值核对之外；实测同一稿件 `unsourced_numbers` 由
  `['42.3%','2.1%','55.8%','3.4%','0.001']` → `[]`，`stat_claim_checker` 由 `review(1 warning)`
  → `pass(0 warnings)`。
- **CSV 一行被当单个数字**：`10,42.3,2.1` 被 `NUM_RE` 匹配成整串，`42.3` 从未成为独立 form，
  正文写 42.3% 反被判无出处。`_corpus_forms()` 增加数字串二次索引后，`verify` 由
  `unsupported_numbers=7` → `1`（且仅剩真实无出处的 0.001，已由阈值规则清零 → 0）。
- **子串匹配放过错数**：`12` 会在 `112.4` 里被当成"有出处"。新增 `_bounded()`（前后不得紧邻数字/小数点），
  `stat_claim_checker` 与 `section_audit` 的数值核对、图表编号核对全部改用有界匹配。
- **章节正文按模板下标取**：正文多一个"摘要"标题后，`结果/讨论/局限` 三节全部错位。实测旧版报
  `结果 short: 1 / 讨论 short: 26 / 局限 short: 12`；改为按标题文本定位后 `结果 short: 77`，其余两节不再误报。
- **中文词数统计错误**：旧正则 `[A-Za-z\u4e00-\u9fff]+` 把整句中文算 1 个词，
  190 字的结果段报成 26 词。新增 `count_words()` 按中文字符 + 英文词计数（26 → 77）。
- **`readable` 误判**：旧判定是"文本以 `[` 开头即 UNREAD"，一篇以 `[1] Smith…` 开头的参考文献
  material 会被标成不可读。改为只认特定的不可读占位串。
- **GBK 稿件乱码**：`decode_text()` 按 utf-8-sig → gb18030 解码，`stat_claim_checker.read` 同步；
  实测 GBK 稿件中 42.3/2.1/55.8 全部可核，仅真实无出处的 0.0003 被报出。
- **非法输入裸栈**：`section_audit` 稿件缺失 → `FAIL: draft missing` rc=1（原 `FileNotFoundError`）；
  `claim_map.json` 非法 → `problems` + `verdict=fail`（原 `JSONDecodeError` 裸栈）；
  `case.json` 非法/顶层非对象 → `blocked` rc=1；`draft.json` 非法 → `emit` rc=2。
- **契约形态与 case_id**：`init`/`emit`/`check` 统一 `normalize_contract()`（四形态）；
  `emit` 跳过 `case_id`/`status` 不再把结果置空；`check` 允许
  `uncertainty/limits/changes/notes/self_check/sources` 为空但必须存在，并拒绝把契约字段
  塞进 `result["fields"]`；`stat_claim_checker` 的 `CI`/`SD`/`SEM` 改为词边界匹配，
  避免 "specific" 之类英文词里的 "ci" 被当成误差口径。
- **平台路径**：新增"平台运行路径"节，全部命令改为 `python3 "$SKILL_DIR/scripts/…"`
  （`SKILL_DIR=/skills/weekly-skill`），避免 cwd=`/app` 时相对路径失效。
