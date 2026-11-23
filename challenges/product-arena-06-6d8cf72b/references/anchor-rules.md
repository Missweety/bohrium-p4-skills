# 锚点规则：粒度、引文选取与冲突并列

## 1. 锚点三要素

`section`（章节）+ `page` 或 `paragraph`（位置）+ `quote`（原文逐字片段）。

- 只有页码没有引文 → 无法核验，判 `quote missing`。
- 只有引文没有位置 → 无法回看，判 `anchor needs page or paragraph`。
- 章节名必须出现在 `paper.sections` 中；子节写 `3.2 Uptake`，脚本按编号前缀与标题双重匹配。

## 2. 页码与段落编号

| 对象 | 写法 | 说明 |
|-|-|-|
| 页码 | `p.6` | 用 PDF 实际页序（非期刊印刷页码）时在 `limits` 说明 |
| 跨页段 | `p.6-7` | 一段跨两页，仍算一个段落锚点 |
| 段落 | `paragraph: 2` | 该章节内自然段从 1 起；标题、图注不计入 |
| 图 | `figure: "Figure 3"` | 结论来自图时必填，同时给 `page` |
| 表 | `figure: "Table 2"` | 同上；表头数值要写列名 |
| 补充材料 | `section: "Supplementary S2"` | 必须能在 corpus 中找到对应标题 |

双栏 PDF 常见段落错序：先按标题切章，再按"句末标点 + 首行缩进"判段；仍不确定的段落在
`uncertainty` 标 `〔段落边界待确认〕`，不要硬编号。

## 3. quote 选取

- 长度 ≥12 字符，通常取 1–2 句；**逐字复制**，保留原文大小写与标点。
- 禁止：用 `...` 拼接两句、把两段拼成一句、翻译后当引文、删除限定词（`may`、`not`）。
- 引文应包含该条笔记的关键变量或数值，便于人工一眼核对。
- 引文中的连字符/软连字符/ﬁ 连字由 `quote_check.py` 归一化后再比对，不影响命中。

反例：
- ❌ 笔记写"去除率显著提高"，quote 取 `The removal efficiency increased`（丢了 `from 41.2% to 88.6%`）
- ❌ quote 写 `removal efficiency increased ... as pH rose`（省略号拼接）
- ✅ quote 写 `The removal efficiency increased from 41.2% to 88.6% as pH rose from 3 to 6`

## 4. 作者主张 vs 笔记推断

| 类型 | `kind` | 要求 | 示例 |
|-|-|-|-|
| 原文陈述 | `author_claim` | quote 直接支撑 | "作者报告 pH 6 时去除率 88.6%" |
| 笔记推断 | `inference` | 必须有 `basis`（≥1 条 `author_claim` id），措辞用"可能/提示" | "提示该材料在酸性条件下不稳定（依据 F02、M03）" |

推断不得进入 `findings` 充当作者结论；若必须记录，放 `limitations` 或 `uncertainty` 并标 `inference`。

## 5. 冲突并列

同一 `topic` 在不同章节出现不一致时：

```json
{"id": "F05", "topic": "uptake_capacity", "conflict_group": "C1",
 "text": "摘要报告吸附量 48.2 mg/g", "value": "48.2 mg/g",
 "anchor": {"section": "Abstract", "page": "p.1", "paragraph": 1}, "quote": "…48.2 mg/g…"}
{"id": "F09", "topic": "uptake_capacity", "conflict_group": "C1",
 "text": "结果节报告吸附量 42.7 mg/g", "value": "42.7 mg/g",
 "anchor": {"section": "3 Results", "page": "p.6", "paragraph": 3}, "quote": "…42.7 mg/g…"}
```

- 两条都保留，共用 `conflict_group`；`uncertainty` 记 `{conflict_group, 位置, 差异, 可能原因}`。
- 禁止取平均、取更"合理"的一个、或只保留摘要值。
- 差异可能来自单位/干重基准/温度不同时，在 `text` 补条件，但仍保持并列。

## 6. 交付前自检

1. `note_check.json` 的 `errors` 为 0；警告逐条处理。
2. `quote_check.json` 全部 `ok`，无 `not_verbatim`。
3. 每个 `fields` 键非空；`not_stated`/`not_reported` 出现处都有 quote。
4. 每条 `findings` 带数值或明确方向；推断条目都有 `basis`。
5. 冲突条目共用 `conflict_group`，且 `uncertainty` 有对应说明。
6. `paper.sections` 与原文标题顺序一致，未覆盖章节写入 `limits`。
