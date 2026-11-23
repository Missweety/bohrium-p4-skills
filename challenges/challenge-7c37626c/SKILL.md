---
name: auditable-formula-reader
description: 把论文中的公式还原成可校验的 LaTeX/Unicode 结构，为每个符号绑定原文定义位置、单位、取值范围与定义来源等级，按步给出带依据的推导并做数值/量纲复核；无法识别的符号标 unknown，源材料缺少公式表示时如实报 partial/insufficient_evidence，不反推公式、不补零。用于行间公式转写、变量表、推导分步解释与代入核验；不用于无原文的公式默写、自动证明或替代数值模拟。
version: 1.2.0
license: MIT
---

# 公式解析：认得准、讲得清、推得顺、算得回

把"读一个公式"拆成 **定位与还原 → 结构自检 → 符号表 → 分步推导 → 数值复核 → 边界声明**。
核心主张：每个符号都能指回原文那一句，每一步推导都能说出用了什么依据，每次代入都带单位与
有效数字；**认不出的符号就写 `unknown`，材料里没有的公式表示就写 `insufficient_evidence`。**

## 预算受限执行顺序（900 秒 / 64 请求 / 16k tokens）

只有第 3–8 步消耗模型请求；第 1–2 步是纯脚本，不占请求额度。按此单一路径执行，不要并行开分支。

| # | 动作 | 模型请求 | 立即落盘 |
|-|-|-|-|
| 1 | 读 `/input/case.json` 与 `task.md`，锁定 `output_contract` 字段与 focus 式号 | 0 | `work/contract.json`（可选，`kernel.py init`） |
| 2 | `python scripts/run_case.py --case /input/case.json --work /app/work --out /app/output`：索引 PDF/XML、抽取 MathML、生成四个骨架、跑两个 checker、写 result.json | 0 | `result.json`、`formula_sheet.md`、`symbols.csv`、`formulas.json` |
| 3 | 按 locator 回读公式上下文，每批 3–6 式核对 LaTeX 结构 | ≤8 | `work/formulas.json` |
| 4 | 补符号含义/单位/范围；引文必须逐字，找不到就 `unknown` | ≤8 | `work/symbols.json`、`work/quotes.json` |
| 5 | 补推导步骤、假设、近似与边界（每步给 basis） | ≤8 | `work/derivations.json` |
| 6 | 数值复核：只有拿到带单位的真实输入才代入，否则 `not_checkable` | ≤5 | `work/numeric_checks.json` |
| 7 | 重跑 `formula_check.py` 与 `quote_check.py`，只修硬错误 | ≤4 | `work/formula_check.json`、`work/quote_check.json` |
| 8 | 重写契约字段到 result.json 顶层 + formula_sheet.md + symbols.csv | ≤2 | `/app/output` |

预算上限 ≈35 请求，保留 ≥29 作重试；每完成一批就落盘，不攒到最后。

**降级判定（按顺序命中即执行）**

- 第 2 步后 `t > 300s` 或可抽取公式为 0：跳过 3–6，直接把第 2 步骨架作为交付，
  只做第 7–8 步，`status=partial`（无材料则 `blocked`），未处理项写 `limits`。
- `t > 600s` 或剩余请求 ≤6：立即停止新增公式/推导，跳到第 7–8 步；未处理式号逐条写 `limits`。
- PDF 无文本层 / `materials` 缺失：不 OCR 猜公式、不反推，写 `insufficient_evidence` + `limits`。
- checker 连续两次同一硬错误：保留错误原文在 `check_summary`，不再重试，`status=partial`。

**中断时的落盘优先级**：`result.json`（契约字段、`case_id`、`status`、`limits` 先齐全）→
`formula_sheet.md` → `symbols.csv` → 其余 JSON。任何时刻中断都必须留有一份契约完整的
`result.json`，宁可 `partial` 也不空输出。

## 何时使用

触发：给定论文 PDF / 出版商 XML / 公式片段，要求"把公式转成 LaTeX"、"解释这个公式的变量"、
"这个推导每一步怎么来的"、"代入数值算一遍"、"检查符号/单位是否一致"、"建立变量表"。

不触发：要求默写某领域的标准公式（没有原文）；要求求解论文未给出的方程或反推未报告参数；
要求替代数值模拟/拟合工具；只做正文翻译（用翻译类 Skill）。

## 输入

执行时读取 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`。
材料按题面提供，常见形态：

| 语义 | 常见字段/文件 | 处理方式 |
|-|-|-|
| 论文正文 | `materials/*.pdf`（无预抽取答案层） | `kernel.py index` 抽取文本，按 `p.N ¶k` 定位 |
| 出版商 XML | `artifacts/publisher-source.xml` | 原始副本，用于核对上下文与编号，**不是答案** |
| 公式节点子集 | `artifacts/source-formulas.xml`（MathML 分式/上下标 + 来源 ID） | `mathml_extract.py` 转为 LaTeX 骨架，再人工/模型补齐 |
| 任务与范围 | `task`, `question`, `focus`（如"只解析式 (1)–(4)"） | 先写进 `work/scope.json`，不擅自扩大 |
| 输出契约 | `output_contract` | 字段全部回填 |

**先读真实文件**。若某案例只有文字与结论、没有公式表示或可复算数据，这是真实的缺失分支：
按第 3 步标 `insufficient_evidence`，不得从数值结果反推公式。

## 执行流程（严格按序）

> 一键主路径：`python scripts/run_case.py --case /input/case.json --work /app/work --out /app/output`
> 已完成第 1–2 步的材料索引、MathML 抽取、四个骨架、两个 checker 与 result.json/formula_sheet.md/symbols.csv；
> 第 3–11 步按下面的规则继续人工/模型补齐。本地无 `/input` 时加 `--dry-run --case <样例>`。

1. **契约**：`python scripts/kernel.py init --case /input/case.json --out work`
   → `work/contract.json`。记录语言、公式范围（哪些式号）与 `output_contract` 字段。
2. **证据索引**：`python scripts/kernel.py index --materials <materials 与 artifacts 路径...> --out work`
   → `work/evidence.json` + `work/corpus.txt`。PDF 无文本层标 `unreadable`，不猜公式内容。
3. **公式清点（认得准）**：写 `work/formulas.json`，逐式登记：

   ```json
   {"id": "F3", "label": "Eq. (3)", "status": "transcribed",
    "latex": "q_e = \\frac{q_m K_L C_e}{1 + K_L C_e}",
    "source": {"path": "materials/paper.pdf", "locator": "p.4 ¶2", "xml_id": "eq3"},
    "structure": {"fractions": 1, "subscripts": 2, "superscripts": 0, "bracket_depth": 1},
    "symbols": ["q_e", "q_m", "K_L", "C_e"],
    "conditions": ["single-site adsorption", "equilibrium"]}
   ```

   `status` 只允许 `transcribed`（有原文公式可还原）/ `extracted`（来自 MathML 节点）/
   `insufficient_evidence`（源材料无公式表示或截断）。`insufficient_evidence` 时 `latex` 必须为空，
   写 `reason` 与已核对的替代信息（如"仅有 qmax 数值，无等温式"），**不得补写公式**。
   有 `source-formulas.xml` 时先跑
   `python scripts/mathml_extract.py --xml artifacts/source-formulas.xml --out work/formulas_extracted.json`，
   再以 `xml_id` 对齐到 `work/formulas.json`。
4. **结构自检**：逐式核对上下标、括号层级、希腊字母、分式分子分母、单位是否与原文一一对应；
   任何缺失项写入 `formulas.json.structure` 与 `uncertainty`。允许保留 Unicode 等价式，但须与 LaTeX 一一对应。
5. **符号表（讲得清）**：写 `work/symbols.json`：

   ```json
   {"symbol": "K_L", "meaning": "Langmuir equilibrium constant", "unit": "L/mg",
    "range": "> 0", "definition_status": "author_defined",
    "locator": {"path": "materials/paper.pdf", "page": "p.4", "paragraph_id": "¶2"},
    "quote": "K_L is the Langmuir constant (L mg-1)"}
   ```

   `definition_status` 四值：

   | 状态 | 含义 | 必填 |
   |-|-|-|
   | `author_defined` | 原文明确给出定义 | `unit`、`locator`、逐字 `quote` |
   | `context_inferred` | 由相邻段落/量纲推得 | `locator`、`quote`、`inference_basis` |
   | `conventional` | 领域通用符号，原文未定义 | `basis`（为何按此约定） |
   | `unknown` | 无法识别或原文缺失 | `note`；**禁止**用于数值代入 |

   同一符号在不同式子里含义不同（如 `k` 既是速率常数又是 Boltzmann 常数）必须拆成 `K1`/`K2`
   并在 `note` 说明，不得合并。
6. **分步推导（推得顺）**：写 `work/derivations.json`：

   ```json
   {"formula_id": "F4", "target": "线性化 Langmuir 式",
    "steps": [{"n": 1, "expr": "q_e(1 + K_L C_e) = q_m K_L C_e", "basis": "由 F3 两边乘分母"},
              {"n": 2, "expr": "C_e/q_e = 1/(q_m K_L) + C_e/q_m", "basis": "两边除以 q_e q_m K_L 并整理"}],
    "assumptions": ["单层吸附", "位点等价且无相互作用"],
    "approximations": [], "boundary": "低浓度到饱和前均适用",
    "depends_on": ["F3"]}
   ```

   每步必须有 `basis`（用到的前式、代数操作或假设）；`depends_on` 写真实跨式引用；
   禁止跳步把三行代数压成一步"整理可得"。假设与近似必须来自原文或显式标注为 `reader_added`。
7. **数值复核（算得回）**：写 `work/numeric_checks.json`：

   ```json
   {"formula_id": "F3",
    "inputs": [{"symbol": "q_m", "value": 48.2, "unit": "mg/g", "sig_figs": 3},
               {"symbol": "K_L", "value": 0.15, "unit": "L/mg", "sig_figs": 2},
               {"symbol": "C_e", "value": 10, "unit": "mg/L", "sig_figs": 2}],
    "computed": {"value": 29.0, "unit": "mg/g", "sig_figs": 2},
    "reported": {"value": 28.9, "unit": "mg/g", "locator": "p.5 ¶1"},
    "status": "consistent", "tolerance": 0.01,
    "note": "输入最少 2 位有效数字；复算 28.9 取 2 位为 29.0，与报告值在 1% 容差内一致"}
   ```

   `status`：`consistent` / `inconsistent` / `not_checkable`。缺任一输入 → `not_checkable` 并说明缺哪个，
   **不得把缺失值当 0**。单位必须逐项写；量纲不一致直接判 `inconsistent` 并给出期望量纲。
   有效数字不得超过输入中最少者；中间值可多保留一位并注明。
8. **机器校验**：
   `python scripts/formula_check.py --formulas work/formulas.json --symbols work/symbols.json \
   --derivations work/derivations.json --numerics work/numeric_checks.json \
   --corpus work/corpus.txt --out work/formula_check.json`
   要求 `verdict=pass`：LaTeX 括号配平、公式引用符号与符号表双向一致、`author_defined` 有逐字引文、
   `unknown` 不参与数值代入、推导步有 `basis` 且编号连续、数值检查有单位与有效数字。
9. **引文逐字复核**：把符号定义与数值来源转 `work/quotes.json`
   （`[{"claim":"K_L","source_path":"...","quote":"...","locator":"p.4 ¶2"}]`，
   **不要覆盖 `work/evidence.json`**），执行
   `python scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt \
   --out work/quote_check.json`；`not_verbatim` 改回原文或把该符号降级为 `unknown`。
10. **写公式页**：生成 `work/formula_sheet.md`（逐式：LaTeX、结构说明、符号表、推导、数值核验、
    边界与未知项）与 `work/symbols.csv`
    （`symbol,meaning,unit,range,definition_status,locator,quote`）。
11. **数字守恒**：把正文（去掉 `F3`、`p.4 ¶2` 等锚点）写入 `work/answer_text.txt`，
    `python scripts/kernel.py verify --text work/answer_text.txt --evidence-dir work --out work`
    → `unsupported_numbers` 应为 0（推导中间式里的常数需在正文说明来源）。
12. **产出**：写 `work/draft.json`（`fields` 覆盖契约字段），
    `python scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output`，
    再 `python scripts/kernel.py check --out /app/output --contract-dir work` 必须 PASS；`partial` 必须写 `limits`。
    契约字段一律写在 result.json **顶层**（不要嵌套在 `fields` 里）；无公式的案例同样要给
    `answer`、`structured`（`formulas: []` + `insufficient_evidence` + `unknown_symbols: []`）与
    至少一条 `evidence`（原文"无公式表示"的定位与引文）。

## 领域规则表（对应题面四个关注点）

| 关注点 | 硬规则 | 反例（禁止） |
|-|-|-|
| 认得准 | 上下标、括号层级、分式结构、希腊字母逐项对应；MathML 节点保留来源 ID | 把 `q_m K_L` 写成 `qmKL`；丢掉分母括号；`α` 与 `a` 混用 |
| 讲得清 | 每个符号有含义、单位、范围、定义状态与原文定位；原文未定义不冒充定义 | 变量表只写"K 为常数"；按常识补单位；同一 `k` 两种含义合并 |
| 推得顺 | 每步给依据（前式/代数操作/假设）；近似与边界单列；跨式依赖标出 | "整理可得"跳三步；假设事后补；把近似写成恒等 |
| 算得回 | 输入带单位与有效数字；量纲先查；结果与报告值比对并给容差 | 无单位代入；把缺失输入当 0；结果保留 6 位有效数字 |

## 硬性禁止

- 不补写源材料中不存在的公式；`insufficient_evidence` 时不以数值结果反推表达式。
- 不猜测无法识别的符号或单位；`unknown` 必须保留并说明缺什么，不能悄悄替换成常见符号。
- 不把缺失参数、缺失数据填成 0、1 或"典型值"；缺就写 `not_checkable`。
- 不省略推导步骤、不伪造 `basis`、不把 `reader_added` 假设写成作者假设。
- 不做无单位的数值代入，不给出超过输入精度的有效数字。
- 不把 XML 公式目录当成完整答案或推导；不把标注/编号当公式内容。
- 不提交预制答案；不写入绝对个人路径、账号或 token。

## 输出

`/app/output/result.json`（`case_id`、`status`、`answer`、`structured`、`evidence`、`uncertainty`、
`limits`，以题面 `output_contract` 为准）+ 可编辑产物：

| 文件 | 内容 |
|-|-|
| `formula_sheet.md` | 逐式公式页：LaTeX、结构、符号、推导、数值核验、边界 |
| `symbols.csv` | 符号表（含定义状态、定位、引文） |
| `formulas.json` | 公式清单（含 `status`、来源、结构计数） |
| `derivations.json` | 分步推导（步骤、依据、假设、依赖） |
| `numeric_checks.json` | 数值代入与量纲核验记录 |
| `formula_check.json` / `quote_check.json` | 机器校验结果 |

`structured` 至少包含：`formulas`、`symbols`、`derivations`、`numeric_checks`、
`insufficient_evidence`（式号+原因）、`unknown_symbols`、`check_summary`、`artifacts`。

`status`：`ok`（范围内公式均可还原且校验通过）、`partial`（部分式缺表示/部分符号 unknown/
部分数值不可复算）、`blocked`（材料不可读或无公式材料）、`refused`（要求反推未报告公式或补造数据）。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 扫描件/公式为图片且无 OCR | 标 `unreadable` 或 `insufficient_evidence`，只记式号与图注，不猜结构 |
| 公式截断/跨页断行 | 记录可见部分与断点，`status: insufficient_evidence` + `reason`，不拼补缺失项 |
| XML 解析失败 | 回退 PDF 文本层；在 `limits` 说明未使用 XML，不伪造 `xml_id` |
| 符号严重歧义（同形多义） | 拆分为不同符号 id，`note` 写两种候选与判据；无法判定则 `unknown` |
| 原文未给单位 | 符号表 `unit: null` + `note`，数值检查 `not_checkable`；不按常识补单位 |
| 代入无解/缺输入 | `not_checkable`，列出缺失符号；不反推、不补 0 |
| 数值与报告值不符 | `inconsistent`，给中间值、量纲与可能原因（符号/单位/数量级），不擅改报告值 |
| 超预算（64 请求/900s/16k tokens） | 先落盘已完成公式与符号表，`partial` + `limits` 列未处理式号 |

## 文件说明

- `scripts/run_case.py`：一次命令跑完主路径（索引材料 → MathML 抽取 → formulas/symbols/
  derivations/numeric_checks 骨架 → `formula_check.py` + `quote_check.py` → result.json +
  formula_sheet.md + symbols.csv），只写真实抽取结果，抽不到的公式 `insufficient_evidence` 且 latex 为空。
- `scripts/selftest.py`：在 `/tmp` 构造合成案例并实跑 `run_case.py`，用真实输出断言契约字段、
  结构计数与三个负例（无公式 / unknown 代入 / 括号不配平）。
- `scripts/kernel.py`：`init / index / verify / emit / check`（仅标准库，共享骨架）。
- `scripts/mathml_extract.py`：从 `source-formulas.xml` 提取 `<math>` 节点，按 mfrac/msup/msub/msqrt
  转为 LaTeX 骨架，保留 `xml_id` 与来源位置。
- `scripts/formula_check.py`：括号配平、符号双向覆盖、定义状态与引文、推导步骤依据、
  数值单位与有效数字的机器校验。
- `scripts/quote_check.py`：引文逐字核验（容忍换行、连字、软连字符）。
- `references/formula-reading.md`：公式/符号/推导/数值记录 schema、定义状态判定、反例。
- `references/output-contract.md`：默认输出字段；题面契约优先。

## 最小调用示例（示例，不是正式案例结果）

```bash
python scripts/run_case.py --case /input/case.json --work /app/work --out /app/output
# 上面一条命令已完成索引/抽取/骨架/checker/result.json；需要分步调试时用下面等价链路：
python scripts/kernel.py init --case /input/case.json --out work
python scripts/kernel.py index --materials /input/materials /input/artifacts --out work
python scripts/mathml_extract.py --xml /input/artifacts/source-formulas.xml --out work/formulas_extracted.json
# 按第 3–7 步写 work/formulas.json、symbols.json、derivations.json、numeric_checks.json
python scripts/formula_check.py --formulas work/formulas.json --symbols work/symbols.json \
  --derivations work/derivations.json --numerics work/numeric_checks.json \
  --corpus work/corpus.txt --out work/formula_check.json
python scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt --out work/quote_check.json
python scripts/kernel.py verify --text work/answer_text.txt --evidence-dir work --out work
python scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output
python scripts/kernel.py check --out /app/output --contract-dir work
```

示意输出（片段，示例）：`F3` 还原为 `q_e = \frac{q_m K_L C_e}{1 + K_L C_e}`，
`K_L` 为 `author_defined`（`p.4 ¶2`，单位 `L/mg`）；`F4` 推导第 2 步依据"由 F3 两边乘分母并整理"；
代入 `q_m=48.2 mg/g, K_L=0.15 L/mg, C_e=10 mg/L` 复算得 `29.0 mg/g`（2 位有效数字），
与报告的 `28.9 mg/g` 在 1% 容差内一致。
`F5` 标 `insufficient_evidence`：源材料无该式表示，仅有结果数值。

## 改动记录

- 1.2.0（2026-11-22）：对应失分线「预算/时序、主路径可执行性、降级落盘」。
  1) 新增「预算受限执行顺序」：一条 ≤8 步主路径，标注每步模型请求上限（总计 ≈35，留 ≥29 余量）、
     300s/600s/剩余请求 ≤6 的降级判定，以及中断时 `result.json → formula_sheet.md → symbols.csv`
     的落盘优先级。
  2) 新增 `scripts/run_case.py`：单命令完成契约解析、材料索引（PDF 仅 pdftotext，失败即 unreadable）、
     MathML 抽取、四个骨架、`formula_check.py` + `quote_check.py`、契约字段顶层回填与产物落盘；
     抽不到的公式一律 `insufficient_evidence` 且 `latex` 为空，数值缺输入不填 0。支持
     `--dry-run --case` 本地运行。
  3) 新增 `scripts/selftest.py`：/tmp 合成案例实跑，断言契约字段/结构计数，并验证三个负例
     （无公式材料、unknown 符号代入、LaTeX 括号不配平）确实被 `formula_check.py` 拒绝。
- 1.1.0（2026-11-20）：对应失分线「输出契约 / 可机检项 / 输入兼容 / 降级路径」。
  1) 修复 `emit` 把 `contract.fields=[...]` 当字段字典的缺陷：契约字段此前只写入一个 `fields` 键，
     顶层 `answer/structured/evidence` 可能缺失；现按字段名逐个回填到顶层（输出契约）。
  2) `check` 新增契约字段齐全、`evidence` 每项 claim/quote/locator、`structured` 含
     formulas/symbols/insufficient_evidence/unknown_symbols、`partial` 必写 limits 四项机检（可机检项）。
  3) `mathml_extract.py` 增加 `munderover` 与 `mfenced`（`\underset{\overset{}}`、`\left…\right`），
     兼容带命名空间/带 m: 前缀的出版商 XML（输入兼容）。
  4) 无公式案例强制仍给顶层 `answer`、`structured`（空 formulas + insufficient_evidence + 空
     unknown_symbols）与一条"无公式表示"的原文证据，避免降级成空输出（降级路径）。
