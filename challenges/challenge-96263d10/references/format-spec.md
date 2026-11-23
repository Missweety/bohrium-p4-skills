# 格式规格（format-spec/v1）

规格有三个来源，优先级从高到低：
1. `task.md` 中的明确要求（priority 3）；
2. JSON/YAML 规格或非任务说明文本（priority 2）；
3. 模板 DOCX 的样式与节属性（priority 1）；
4. 内置默认值（priority 0）。

冲突不会被静默丢弃：保留高优先级值，并写入 `spec.json.conflicts` 与
`result.json.issues`。每个字段的来源与原文片段记录在 `provenance`/`meta.spec_sources`。

模板 DOCX 与 JSON/YAML 规格可以同时存在：先读模板 DOCX，再由结构化规格覆盖同名字段。

## 1. 顶层结构

```json
{
  "schema": "format-spec/v1",
  "page": {"size_name": "A4", "width_cm": 21.0, "height_cm": 29.7,
           "orientation": "portrait", "columns": 1,
           "margins_cm": {"top": 2.5, "bottom": 2.5, "left": 3.0, "right": 3.0}},
  "body": {"font_latin": "Times New Roman", "font_east_asia": "SimSun",
           "size_pt": 12.0,
           "line_spacing": {"type": "multiple", "value": 1.5},
           "first_line_indent_cm": 0.74, "space_before_pt": 0.0,
           "space_after_pt": 0.0, "alignment": "both"},
  "headings": {
    "1": {"size_pt": 16.0, "bold": true, "alignment": "center",
          "space_before_pt": 12.0, "space_after_pt": 6.0,
          "page_break_before": false},
    "2": {"size_pt": 14.0, "bold": true, "alignment": "left"}
  },
  "heading_numbering": {
    "enabled": true,
    "levels": [{"ilvl": 0, "numFmt": "decimal", "lvlText": "%1"},
               {"ilvl": 1, "numFmt": "decimal", "lvlText": "%1.%2"}]
  },
  "captions": {
    "figure": {"label": "Figure", "separator": ". ", "position": "below",
               "size_pt": 10.0, "alignment": "center", "bold": false, "italic": false},
    "table": {"label": "Table", "separator": ". ", "position": "above",
              "size_pt": 10.0, "alignment": "left", "bold": false, "italic": false}
  },
  "references": {"heading": "References", "style": "numeric_bracket",
                 "size_pt": 10.5, "hanging_indent_cm": 0.74, "line_spacing": 1.0},
  "page_numbers": {"enabled": true, "position": "footer_center",
                   "fmt": "decimal", "start": 1},
  "header": {"enabled": false, "text": null},
  "toc": {"enabled": false},
  "tables": {"style": "three_line"},
  "export": {"formats": ["docx", "pdf"]},
  "unknown": [], "conflicts": [], "provenance": {},
  "meta": {"template_used": false, "template_missing": false,
           "unmatched_requirements": []}
}
```

## 2. 单位与取值

- 长度：内部统一为 cm；输入接受 `cm`、`mm`、`pt`、`in` 与中文字符数（2 字符 ≈ 2×字号）。
- 字号：pt；中文别名可解析（初号 42、小初 36、一号 26、二号 22、小二 18、三号 16、
  小三 15、四号 14、小四 12、五号 10.5、小五 9）。
- 行距：`{"type": "multiple"|"exact"|"at_least", "value": 1.5}`；文本中的「1.5 倍」
  「固定值 20 磅」可解析。
- 页边距：`margins_cm` 四个方向；文本「上下 2.5cm」「左右 3.0cm」「页边距 2.5cm」均可。
- 纸张：`A3/A4/A5/B5/Letter/Legal`；未给宽高时按名称派生。
- 对齐：`left` / `center` / `right` / `both`（两端对齐）。
- 表格：`three_line`（三线表）/ `grid`（全框线）/ `none`（无框线）。
- 参考文献：`numeric_bracket`（GB/T 7714 顺序编码）/ `author_year`。
- 页码位置：`footer_center` / `footer_right` / `footer_left` / `header_center` 等。

## 3. JSON/YAML 别名

- `page.size` / `page.paper` / `纸张`、`page.margin(s)` / `page.margins_cm` / `页边距`。
- `body.text` / `body.font` / `body.font_size` / `字号`、`body.line_spacing` / `行距`。
- `headings.heading1` / `headings.h1` / `headings.1`；键可用数字或 `h1`。
- `captions.figure` / `captions.table`；`figure`/`fig`、`table`/`tab` 均可。
- `references.bibliography` / `refs`；`references.style` / `style`。
- `page_numbers` / `pageNumbers` / `页码`；`header` / `页眉`；`toc` / `目录`。
- `tables.style` / `tables.border(s)` / `表格`，字符串值也接受。
- `export.formats` / `exports` / `导出`，值可为 `["docx","pdf"]` 或字符串。

无法识别的扁平键会写入 `unknown`，不会静默丢弃。

## 4. 从模板 DOCX 能读到什么

- `word/styles.xml`：`docDefaults`、`Normal`、`Heading1`–`Heading4`、`Caption`、
  `Bibliography` 的字体、字号、加粗、斜体、对齐、行距、段前段后、缩进。
- `word/document.xml` 的 `sectPr`：纸张宽高、方向、四边页边距、分栏数、页码格式、
  页眉/页脚引用。
- `word/numbering.xml`：标题 `numId` → `abstractNum` → 各级 `numFmt` 与 `lvlText`，
  用于还原「1 / 1.1 / 1.1.1」编号。
- 页脚中的 `PAGE` 域 → 页码启用与位置；页眉文本 → `header.text`。

模板中无法识别的内容（缺样式、编号缺失、多节不一致）会写 warning，
由 `result.json.uncertainty` 暴露，而不是猜测。

## 5. 文本要求如何映射

`task.md` 默认严格模式：只处理同时含格式关键词（页边距/字号/行距/标题/题注/表格/
参考文献/页码/分栏/页眉/公式等）与数值或「要求/必须/需要/使用」的行。
明确要求但生成器未实现的（公式、页眉版式、脚注、水印、行号、上标、封面等）
写入 `meta.unmatched_requirements`，报告中标为 `unsupported`。
