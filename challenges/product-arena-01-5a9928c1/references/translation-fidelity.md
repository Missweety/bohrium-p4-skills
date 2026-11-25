# 译文保真规则（术语之外的"关系准"）

本文件约束译文的**信息关系**：谁指谁、否定到哪、限定多强、数字单位是否原样。
术语与段号规则见 `glossary-alignment.md`。

## 1. 情态与限定强度

原文的确定程度是科学结论的一部分，译文只能等强，不能加强也不能削弱。

| 原文 | 允许译法 | 禁止译法 | 原因 |
|-|-|-|-|
| `may` / `might` / `could` | 可能、或许、有望 | 会、能够、导致 | 可能性被写成事实 |
| `can` / `is able to` | 能够、可以 | 证明、一定 | 能力被写成证明 |
| `suggest` / `indicate` | 提示、表明（弱） | 证明、证实 | 证据强度被抬高 |
| `demonstrate` / `show` | 显示、证明 | 提示、可能 | 强度被削弱 |
| `is associated with` | 与……相关 | 导致、引起 | 相关被写成因果 |
| `consistent with` | 与……一致 | 证明了 | 一致性被写成确证 |
| `likely` / `unlikely` | 很可能 / 不太可能 | 可能 / 不可能 | 概率档位被压平 |
| `up to` | 最高可达 | 达到 | 上限被写成实测值 |
| `approximately` / `~` | 约、大约 | 删除 | 精度被拔高 |

反例：
- 原文 `These results may reflect ion exchange.` → ❌ "这些结果反映了离子交换。"（`may` 丢失）
- 原文 `The trend is consistent with surface complexation.` → ❌ "该趋势证明了表面络合。"（一致性被升级）

## 2. 否定与作用域

否定词必须覆盖与原文相同的作用域；`not` 的位置移动会改变结论。

| 原文 | 正确 | 错误 |
|-|-|-|
| `not all samples` | 并非所有样品 | 所有样品都不 |
| `no significant difference` | 无显著差异 | 差异不显著地存在 / 没有差异 |
| `no evidence of X` | 无证据表明 X | 证明不存在 X |
| `did not increase` | 未增加 | 下降 |
| `neither A nor B` | 既非 A 也非 B | 不是 A 或 B |
| `only in group A` | 仅在 A 组 | 在 A 组也有（范围扩大） |
| `except at pH < 3` | 除 pH < 3 外 | pH < 3 时（丢掉排除关系） |

## 3. 指代与逻辑连接

- `it / they / this / such` 必须译成**明确名词**（回指最近的同性别、同数名词）；回指不唯一时写
  `〔指代待确认：可能指 A 或 B〕` 并进 `uncertainty`，不要用"其""该"糊过去。
- `whereas / while` → 而、然而（对比）；`although / even though` → 尽管（让步）；`therefore / thus`
  → 因此（因果）；`however` → 然而（转折）。不得把对比写成因果、把让步写成条件。
- 条件句保留条件：`if ... , ...` 不译成"当……时"（时间≠条件）；`unless` → 除非。
- 方式/范围状语位置变化不得改变修饰对象（`only in vitro` 只修饰体外实验）。

## 4. 数字、单位、公式

- 数字逐字符搬运：`12.4` 不写"约 12"；`1.2 × 10^3` 不写"1200"；`n = 24` 保留 `n =`；
  `P < 0.05` 保留符号；范围 `10–20 mg/L` 保留原文连接符与单位位置。
- 单位用国际符号原样：`mV`、`µg/L`、`kDa`、`°C`、`rpm`、`mol/L`；中文只在首次出现时加中文名，
  不得替换符号，也不得做单位换算。
- 公式整段照抄 LaTeX（`$k_{obs}$`、`\frac{a}{b}`），变量名、上下标、希腊字母不变；只译公式前后
  的说明文字。公式编号 `(1)`、`Eq. (1)` 保留编号。
- 表格数值不重排、不补零、不统一小数位；原文 `–`（未测）与 `0` 区分对待。

## 5. 引用与图表编号

- 编号引用原样：`[12]`、`[3,5]`、`[3–5]`、`\cite{smith2020}`；不合并、不重排、不删除。
- 作者-年份保留姓氏原文与年份：`(Smith et al., 2020)` → `(Smith 等, 2020)`；不改姓氏拼写。
- `Figure 3` → `图 3`；`Table 2` → `表 2`；`Fig. 3A` → `图 3A`；`Supplementary Fig. S2` →
  `补充图 S2`。编号数字与字母后缀不得变化。
- 表头逐列翻译，列序与原文一致；合并单元格用"（合并）"标注，不拆列。
- 图注保留分句结构（(a)(b)(c) 对应关系），比例尺、误差线说明（`mean ± SD, n = 3`）原样保留。

## 6. 句子切分与合并

- 长英文句可拆成两句，但**不得丢失任何限定成分**；拆句后每句仍须能指回原文同一句（记 `source_sentence`）。
- 相邻短句可合并，但合并后不得产生原文没有的因果/递进关系。
- 每个译文段必须与一个原文段 `id` 一一对应；句子级对照记在 `segment_alignment.csv` 的
  `sentences` 列（`S1a|S1b` 形式），便于逐句回查。

## 7. 交付前自检清单

1. 术语：`term_check.json` 的 `missing_locked`、`variant_drift` 都为 0。
2. 段号：`id` 连续无重复，`segments_translated == segments_total`，跨页段 `span` 有页码范围。
3. 数字：`numbers_missing`、`numbers_added` 都为 0；单位符号与原文一致。
4. 引用：`citations_missing` 为 0，括号编号未被改写。
5. 编号：`markers_missing` 为 0，图表编号未被泛指化。
6. 情态/否定：抽查每段含 `may/might/could/suggest/not/no` 的句子，强度与作用域一致。
7. 不确定项：所有 `〔原文: ...〕` 标注都能在 `uncertainty` 找到对应条目。
