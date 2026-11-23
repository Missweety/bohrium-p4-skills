# 公式阅读规范：还原、符号、推导与数值

本文件展开 `SKILL.md` 第 3–7 步。示例均为接口示例，不是正式案例答案。

## 1. 公式记录（`work/formulas.json`）

```json
{"id": "F3", "label": "Eq. (3)", "status": "transcribed",
 "latex": "q_e = \\frac{q_m K_L C_e}{1 + K_L C_e}",
 "source": {"path": "materials/paper.pdf", "locator": "p.4 ¶2", "xml_id": "eq3"},
 "structure": {"fractions": 1, "subscripts": 2, "superscripts": 0, "bracket_depth": 1},
 "symbols": ["q_e", "q_m", "K_L", "C_e"],
 "conditions": ["single-site adsorption", "equilibrium"]}
```

| status | 含义 | 约束 |
|-|-|-|
| `extracted` | 来自 `source-formulas.xml` 的 MathML 节点 | 必须有 `xml_id`，LaTeX 需与 PDF 版式核对 |
| `transcribed` | 从 PDF/文本还原 | 必须有 `source.path + locator`，括号配平 |
| `insufficient_evidence` | 源材料无公式表示/截断/不可读 | `latex` 必须为空，`reason` 必填 |

**MathML 只是节点子集，不是答案**：`mathml_extract.py` 产出的是骨架（不补间距、不补编号、
不做线性化），必须回到 PDF/正文核对上下标与分式层级后再标 `transcribed`。

## 2. 符号定义状态判定（`definition_status`）

按顺序判断，命中即停：

1. 原文写了"where X is…"、变量表或行内定义 → `author_defined`（必须 `locator + 逐字 quote`）。
2. 原文未直接定义，但相邻句/量纲可推出含义 → `context_inferred`（`inference_basis` 写明推法）。
3. 领域通用符号且原文省略定义 → `conventional`（`basis` 写为什么按此约定，如"标准 Langmuir 记号"）。
4. 形似但无法确认（字形糊、上下标丢失、同形多义无判据）→ `unknown`（`note` 写缺什么）。

规则：

- `unit` 键必须存在：有单位写单位；无量纲写 `"1"`；原文未给写 `null` + `note`，**不按常识补**。
- 同一符号两种含义必须拆分（`k_r` 速率常数 / `k_B` Boltzmann），不得共用一条记录。
- 单位写法统一为 `mg/g`、`L/mg`、`mg/L` 这类可解析形式；原文用 `mg g-1` 时在 `note` 保留原写法。

## 3. 推导记录（`work/derivations.json`）

```json
{"formula_id": "F4", "target": "线性化 Langmuir 式", "depends_on": ["F3"],
 "steps": [{"n": 1, "expr": "q_e(1 + K_L C_e) = q_m K_L C_e", "basis": "由 F3 两边乘 (1 + K_L C_e)"},
           {"n": 2, "expr": "C_e/q_e = 1/(q_m K_L) + C_e/q_m", "basis": "两边除以 q_e q_m K_L 并整理"}],
 "assumptions": ["单层吸附", "位点等价、无相互作用"],
 "approximations": ["忽略活度系数，用浓度代替活度"],
 "boundary": "适用于平衡态、单一吸附质；高浓度偏离单层假设"}
```

- 每步 `basis` 只允许三类：引用前式（`由 F3 …`）、明确代数操作（`两边除以…`）、显式假设（`假设…`）。
- 假设若不在原文，标 `reader_added` 并在正文说明，不能写"作者假设"。
- 跨式引用写进 `depends_on`；`formula_check.py` 会校验引用存在。
- 禁止把多于一步的代数压缩成"整理可得"；禁止在推导中引入未定义符号。

## 4. 数值复核（`work/numeric_checks.json`）

```json
{"formula_id": "F3",
 "inputs": [{"symbol": "q_m", "value": 48.2, "unit": "mg/g", "sig_figs": 3},
            {"symbol": "K_L", "value": 0.15, "unit": "L/mg", "sig_figs": 2},
            {"symbol": "C_e", "value": 10, "unit": "mg/L", "sig_figs": 2}],
 "computed": {"value": 29.0, "unit": "mg/g", "sig_figs": 2},
 "reported": {"value": 28.9, "unit": "mg/g", "locator": "p.5 ¶1"},
 "status": "consistent", "tolerance": 0.01,
 "note": "K_L·C_e 无量纲；复算 28.9 取 2 位为 29.0，与报告值在容差内一致"}
```

检查顺序：**符号齐全 → 单位换算 → 量纲 → 数值 → 有效数字**。

| 情况 | status | 必填 |
|-|-|-|
| 输入齐全、量纲一致、与报告值差 ≤ 容差 | `consistent` | `computed`、`reported` |
| 量纲不符/数值差超容差 | `inconsistent` | `note` 写可能原因（符号、单位、数量级） |
| 缺输入、缺单位、原文无报告值 | `not_checkable` | `note` 列缺失项；**不得补 0** |

有效数字：结果不得超过输入中最小 `sig_figs`；中间值多留 1 位并注明。单位不同先换算
（如 `mg/L ↔ mol/L` 需摩尔质量），换算系数写进 `note`。

## 5. 反例

| 反例 | 问题 | 正确做法 |
|-|-|-|
| `q_e = qmKL Ce / (1+KLCe)` | 上下标全丢 | 保留 `q_m`、`K_L`、`C_e` 与分式结构 |
| 变量表写"K_L 为常数，单位 L/mg"但原文未写单位 | 按常识补单位 | `unit: null` + `note`，或标 `conventional` 并给 `basis` |
| 原文只有 qmax 数值，却写出完整等温式 | 反推公式 | `insufficient_evidence` + `reason`，只用已有数值做条件核对 |
| 推导写"化简得式 (4)" | 跳步 | 每步 `expr + basis`，至少保留关键代数操作 |
| 代入时 `C_e` 缺失，按 0 计算 | 补零 | `not_checkable`，列缺失输入 |
| 结果写 28.9230769 mg/g | 伪精度 | 按输入取 2–3 位有效数字，并说明取值规则 |
| 把 XML `<annotation>` 里的线性文本当公式 | 混淆标注与公式 | 只用 MathML 结构节点，标注仅作对照 |

## 6. 复用与扩展

新增公式时：登记 `formulas.json` → 补符号表（含定义状态）→ 若做推导则写 `derivations.json` →
若有数值则写 `numeric_checks.json` → 重跑 `formula_check.py` 与 `quote_check.py`。
新增案例若没有公式表示，保留 `insufficient_evidence` 分支，**不要为凑满字段而构造公式**。
