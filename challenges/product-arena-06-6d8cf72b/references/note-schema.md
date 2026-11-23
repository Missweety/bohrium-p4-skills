# 笔记字段字典与记录 schema

## 1. 顶层结构（`notes.json`）

```json
{
  "case_id": "…",
  "paper": {"title": "…", "sections": ["Abstract", "1 Introduction", "2 Methods", "3 Results", "4 Discussion", "5 Conclusions"]},
  "fields": {
    "research_question": [], "methods": [], "data": [],
    "findings": [], "limitations": [], "reuse_points": []
  },
  "uncertainty": []
}
```

`paper.sections` 必须与原文标题一致且有序；`fields` 的键固定，不能用自定义键替代（自定义信息放 `text`）。

## 2. 单条记录

| 键 | 必填 | 说明 |
|-|-|-|
| `id` | 是 | 全篇唯一，前缀按字段：`RQ`/`M`/`D`/`F`/`L`/`U` + 两位序号 |
| `text` | 是 | 一句话陈述，不写成段落摘要；含数值时必须与原文一致 |
| `value` | 结论类必填 | 关键数值/区间/统计量（如 `41.2% → 88.6%`、`P < 0.05`）；无则 `qualitative` |
| `topic` | 否 | 可聚合主题键（`pH_effect`、`kinetics`），用于跨章节冲突检测与多篇比较 |
| `kind` | 是 | `author_claim`（原文说了）/ `inference`（笔记推出） |
| `basis` | inference 必填 | 支撑该推断的 `author_claim` id 列表，不能引自身 |
| `anchor.section` | 是 | 必须是 `paper.sections` 中的章节（或其子节编号） |
| `anchor.page` / `anchor.paragraph` | 至少一个 | 页码 `p.6`；段落序号按该章节内自然段从 1 起 |
| `anchor.figure` | 否 | 图表结论写 `Figure 3` / `Table 2` |
| `quote` | 是 | 原文逐字片段，≥12 字符，不改写、不省略、不翻译 |
| `conflict_group` | 冲突时必填 | 同一指标互相矛盾的两条共用同一 `C1` |

## 3. 六字段的判定标准

### research_question
- 必须能回答"作者想解决什么"；允许 1–3 条（主问题 + 子问题）。
- 原文没有明确问句时，取 Introduction 末段的目的是陈述，`text` 写 `not_stated` 并引用该句。
- ❌ "研究吸附"（过宽）｜✅ "改性生物炭对 Pb(II) 的吸附容量是否优于未改性生物炭"

### methods
- 每条写**方法与条件**：对象、样本量、关键参数、对照、统计检验。
- 不写"实验流程"式的流水账；同一方法的参数合并为一条。
- ❌ "进行了批实验"｜✅ "批实验：25 °C、pH 3–6、初始浓度 50 mg/L、三次平行（n = 3）"

### data
- 数据来源、规模、划分、可得性（补充材料/代码仓库/申请获取）。
- 未报告写 `not_reported`，**不得推测**；不得把图表数量当作样本量。

### findings
- 每条必须有可核对的数值或明确方向（"显著升高/无显著差异"）。
- 与统计量绑定：`P` 值、置信区间、误差（`mean ± SD, n = 3`）。
- 相关不写成因果；`may/suggest` 的结果保持弱表述。
- 无数值的定性结论：`value: "qualitative"`，并在 `text` 说明依据（如"作者仅给出趋势描述"）。

### limitations
- 作者明说的 → `kind: author_claim`；笔记推断的 → `kind: inference` + `basis`。
- 常见遗漏项要主动核对：样本代表性、外推范围、批次效应、未做对照、统计功效。

### reuse_points
- 每条必须写 `use`：怎么复用（迁移方法/复用数据/引用结论）+ 适用边界。
- ❌ "方法有价值"｜✅ "`use`: pH 3–6 区间的批实验参数可直接迁移到同类生物炭；超出该 pH 需重做对照"

## 4. 状态词约定

| 写法 | 含义 | 禁止替代写法 |
|-|-|-|
| `not_stated` | 原文没有陈述 | "未提及/大概没有" |
| `not_reported` | 原文没有报告该数据 | "没有做/数据为 0" |
| `qualitative` | 结论无数值 | "效果明显" |
| `conflict_group: C1` | 多处结论冲突、并列保留 | 只留一处、取平均 |

## 5. 多篇论文并排比较

同一领域多篇笔记并排时，只比较 `topic` 相同的条目，并保持字段口径一致：

| topic | paper A `value` | paper B `value` | 条件差异 |
|-|-|-|-|
| `pH_effect` | 41.2% → 88.6%（pH 3→6） | 35% → 79%（pH 4→7） | 初始浓度与生物炭粒径不同 |

条件不同不得直接判"更优"；条件差异写入比较表的独立列。
