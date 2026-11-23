# 写作题卡与评分锚点规范

## 1. 题卡字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `item_id` | 是 | `F`事保真 / `S`结构 / `C`引用 / `A`不编造 |
| `task_type` | 是 | `fact_preserve` / `section_coverage` / `citation_map` / `absence_guard` |
| `task` | 是 | 面向谁、保留什么、长度上限；**不得出现金标准数值** |
| `gold` | 是 | 按题型：`numbers`+`document_numbers`+`conditions`+`source_text`；`required_sections`；`claims`；`absent_topic` |
| `source_units` | 是 | 支撑该题的来源单元 |
| `evidence` | 是 | `[{unit_id, source_path, quote, locator}]`，引文必须逐字来自原文 |
| `rubric` | 是 | `2/1/0` 的可观察判据 |
| `difficulty` | 是 | 1–5（长段 +1、句内多值 +1） |
| `data_license` | 是 | 来自 `case.json`，缺省 `provided-by-organizer` |

## 2. 四族题的标准

### fact_preserve（事实保真）
- 来源：含带单位测量值的段落。数值用“值+单位”规范化（`mL`=`ml`、`%`=`percent`）。
- 金标准：该段全部测量值 + 限定条件原句；`document_numbers` 为全文数值集合，用于判定“材料外数字”。
- 判据：值+单位齐全、无材料外数字、限定条件不丢、非整段照搬（最长同文 <30 词）、长度合规。

### section_coverage（结构完整）
- 必需小节来自 `case.required_sections`，缺省 `Background/Methods/Results/Limitations`。
- 判据：小节标题命中（`## X` / `**X**` / `X:`），且每节正文含 `[src: <unit_id>]` 锚点。

### citation_map（引用映射）
- 主张 = 含数值/否定表述的整句；关键词取自该句实词。
- 判据：主张关键词出现且锚点命中该句所属单元；错锚点不算。

### absence_guard（不编造未报告项）
- 来源：`No data on X are available` / `未报告` 一类否定句。
- 判据：在同句内为该主题给数值 → 0；明确写未报告且有否定证据锚点 → 2；沉默 → 1。

## 3. 锚点语法

```text
[src: materials.md#P4]       段落
[src: materials.md#T1:r2]    表格行
```

- 锚点必须指向真实 `unit_id`；`work/units.json` 是唯一权威清单。
- 同一稿子可多次出现锚点；评分只看是否存在指向正确单元的锚点。

## 4. 可接受变体 vs 实质错误

| 类别 | 例 |
|---|---|
| 可接受 | 同义改写、单位等价、精度等价（`1.42`=`1.42`）、拆分长句 |
| 不可接受 | 改数值/单位、丢限定条件、把“未报告”写成有值、编造 DOI/作者、整段照搬冒充改写 |

## 5. 难度与依据

难度由 `difficulty_basis` 支撑：段落 >320 字符（+1）、句内 ≥2 个带单位值（+1）、需跨段/表（+1），基础 2–3，封顶 5。难度必须可复算。
