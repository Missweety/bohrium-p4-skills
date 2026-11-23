# 题卡与评分锚点规范

## 1. 题卡字段

| 字段 | 必填 | 写法 |
|---|---|---|
| `item_id` | 是 | `B01…`，追溯链起点，同一版本内不复用 |
| `task_type` | 是 | `numeric` / `table` / `absence` / `condition` / `definition` / `relation` |
| `question` | 是 | 目标语言、单义；**不得**出现金标准或金标准中的数值 |
| `gold_answer` | 是 | 直接摘自来源的答案；`absence` 题为 `not reported` |
| `acceptable_variants` | 是 | 合法写法（单位变体、等价表述）；风格差异放这里，实质错误不放过 |
| `evidence` | 是 | `[{unit_id, source_path, quote, locator, char_start, char_end}]`，引文必须是原文逐字片段 |
| `rubric` | 是 | `levels{0,1,2}` + `unit_policy` + `anchor_policy` |
| `difficulty` | 是 | 1–5，含 `difficulty_basis`（如 `multiple_numbers_in_sentence`、`long_context`） |
| `leakage_status` | 是 | `clean`；被拒候选进 `rejected_candidates.json` |
| `data_license` | 是 | 来自 `case.json`，缺省 `provided-by-organizer` |

## 2. 题型与金标准构造

- **numeric**：句内唯一带单位量；`m-2`、`s-1`、`×10-3` 等指数片段不算测量值。金标准保留单位，变体含“值+单位”与原始写法。
- **table**：定位到 `table_id` + `row_index` + 列名；金标准为该单元格值，不含整行。
- **absence**：取自“No data on … are available / 未报告”一类否定句；金标准为 `not reported`，编造数值判 0。
- **condition**：取自 `only when / provided that / 仅当` 限定句；金标准必须包含限定条件本身。
- **definition**：取自 `X is defined as …`；金标准为定义谓语部分。
- **relation**：取自 `A was higher than B` 一类比较句；金标准为方向与比较对象。

## 3. 0/1/2 锚点（可观察现象）

| 类型 | 2 分 | 1 分 | 0 分 |
|---|---|---|---|
| 数值/表格 | 值一致且单位等价，定位命中证据单元/引文 | 值对但单位缺失或不符，或定位缺失 | 值错、空、超长、复述题干、编造 |
| 定义/关系/条件 | 核心要素与金标准一致且定位正确 | 要素部分命中或定位缺失 | 冲突、空、超长 |
| 未报告 | 明确说未报告并给出否定证据定位 | 只说“无法判断”但未编造 | 编造数值或声称有结果 |

锚点必须写成**可观察**的判据（“值相等”“引文重叠 ≥0.55”“定位含同一 unit_id”），不写“准确”“完整”这类无法核对的话。

## 4. 可接受变体 vs 实质错误

- 可接受：单位等价（`mL`=`ml`）、数值精度等价（`1.42`=`1.42`）、同义术语（术语表内）。
- 不可接受：单位换错、把图示估读当原始数据、把“未报告”改写成有值、丢掉限定条件、增加材料外事实。

## 5. 难度

难度 = 基础难度（题型）× 附加项：句内多值（+1）、长上下文 >320 字符（+1）、需跨段/跨表（+1），上限 5。难度必须能由 `difficulty_basis` 复算。
