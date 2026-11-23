# chart_spec.json（spec v1.1）

`chart_spec.json` 是渲染的唯一真源。`render_figure.py` 与 `svg_render.py` 只读该文件，
不读原始数据；因此同一 spec + 同一环境重跑，图件与哈希稳定。数据事实由
`plan_figures.py` 计算一次，之后所有改图都在 spec 层完成。

## 顶层

| 字段 | 类型 | 说明 |
|-|-|-|
| `spec_version` | string | `"1.1"` |
| `chart_id` | string | 默认 `figure` |
| `chart_type` | enum | `bar`/`grouped_bar`/`line`/`scatter`/`hist`/`box`/`heatmap`/`panel` |
| `source` | object | `file`、`path`、`sha256`、`bytes`、`rows`、`header_row`、`sheet`、`normalized` |
| `title` / `title_source` | string | 图题；`default` 或 `user` |
| `palette` | object | `name`、`colors`（Okabe-Ito 8 色）、`viridis`（10 色采样） |
| `style` | object | `width_in`、`height_in`、`dpi`、`font_pt`、`title_pt`、`line_width`、`marker_size`、`bar_width_ratio`、`grid`、`cjk` |
| `panels` | array | 每个面板一个对象，见下 |
| `error` / `error_semantics` | object | `sd`/`sem`/`ci95`/`none` 及中英文说明 |
| `missing` | object | `count`、`rows`、`policy`、`declared` |
| `outliers` | object | `method`（IQR_1.5）、`count`、`rows`、`values`、`policy` |
| `duplicates` | object | `count`、`rows`、`policy` |
| `significance_provided` | bool | 仅当源表存在 p 值/显著性标记时为 true |
| `annotations` | array | 全局注记：`id`、`kind`、`place`、`text`、`source`、`source_rows` |
| `caveats` | array[string] | 进入图注与 `result.uncertainty`/`limits` 的中文说明 |
| `layout` | object | `mode`（single/grid）、`panel_count` |

## panel

| 字段 | 说明 |
|-|-|
| `id` | `A`、`B`…；多面板时用于元素 id 前缀 |
| `chart_type` | 单面板可为 `bar` 等；组合图为 `panel` 容器 |
| `title` | 面板标题 |
| `fields` | `x`/`y`/`group`/`color`：`{name, unit, column}`，`column` 为 0 基列号 |
| `axis` | `x`/`y`/`color`：`{label, unit, kind, min, max, ticks, categories, pinned?}` |
| `series` | 见下 |
| `values` | bar/grouped_bar：`[{label, value, error, error_type, n, source_rows}]` |
| `points` | line/scatter：`[{x, y, row, series, error, n, source_rows}]` |
| `bins` | hist：`[{lo, hi, count, rows}]` |
| `boxes` | box：`[{label, min, q1, median, q3, max, n, outliers, source_rows}]` |
| `row_labels` / `col_labels` / `cells` | heatmap：单元格 `{row, column, row_label, col_label, value, n, source_rows}` |
| `legend` | `{show, position, items:[{label, color}]}`；`items` 由 series 生成 |
| `annotations` / `highlights` | 面板级注记与高亮 |

### series

```json
{"label": "body_weight (g)", "color": "#0072B2", "error_type": "SD",
 "values": [{"label": "Control", "value": 21.8, "error": 0.52, "n": 7,
             "source_rows": [2,3,4,5,6,7,8]}]}
```

- 颜色只能取 `palette.colors` 或 `palette.viridis`；机检拒绝其它彩色。
- 柱高是组统计量；`error` 由 `error_type` 决定；`n<3` 时 `error=null`。
- `source_rows` 是 1 基源表行号，表头为第 1 行。

## 数值轴与刻度

- 类别轴：`kind="category"`，`categories` 有序。
- 数值轴：`kind="numeric"`，`min`/`max`/`ticks` 由 nice-number 算法生成（3–8 个刻度，
  步长 1/2/2.5/5 × 10^k）。
- 柱状图/直方图默认从 0 起；若改图指令显式把 y 轴下界设为非 0，`pinned=true`，
  机检给 warning 并要求图注声明“截断显示”。
- `hist` 的 y 轴是计数，标签固定 `Count`。

## 元素 id（element_map.json）

| 类型 | id 形式 |
|-|-|
| 标题 | `panel:A:title` |
| 坐标轴 | `panel:A:axis:x`、`:axis:y`、`:axis:color` |
| 系列 | `panel:A:series:0` |
| 柱 | `panel:A:bar:0|Control`（系列序号 \| 类别） |
| 点 | `panel:A:point:3` |
| 箱 | `panel:A:box:Control` |
| 直方箱 | `panel:A:bin:2` |
| 热图单元 | `panel:A:cell:1|2`（行序 \| 列序） |
| 图例项 | `panel:A:legend:Liver` |
| 注记 | `panel:A:annotation:edit:1` 或 `annotation:edit:1` |
| 高亮 | `panel:A:highlight:HighDose` |

数据元素（bar/point/bin/box/cell）必须带 `source_rows` 与非空 `column`；
结构元素（title/axis/legend/annotation/highlight）指向 spec 路径，`source_rows=[]`。

## 编辑键（`edit_figure.py spec`）

| CLI | spec 路径 | 影响 |
|-|-|-|
| `--title` | `title` | 标题、图注、`panel:*:title` |
| `--chart-type` | `chart_type`、`panels[].chart_type` | 重建数据层；bar↔grouped_bar↔line 可逆 |
| `--y-min` / `--y-max` | `panels[].axis.y` | 固定范围并重算刻度（`pinned`） |
| `--annotate` | `annotations` | 新增注记，进入图、图注与 element_map |
| `--highlight` | `panels[].highlights` | 给目标柱/文本加高亮框 |
| `--set-text` | 文本替换 | 仅用于 SVG 编辑模式 |

`edit_figure.py` 输出 `chart_spec.original.json`、`chart_spec.json` 与 `edit_log.json`：
`operations`、`changes[{path,kind,before,after}]`、`structurally_changed`、
`structural_fields_touched`、`structure_preserved`、`spec_sha256_before/after`、
`warnings`。SVG 模式另有 `mode="svg"`、`source.sha256`、`output_sha256`、
`structure_preserved`（删除插入节点 + 反向文本替换后逐字节等于输入）。

## 不变式

1. 所有图上数值来自 `series[].values[].value`、`points[].y`、`bins[].count`、
   `boxes[].*`、`cells[].value`，不得手填。
2. `sum(n) + missing.count == source.rows`（柱/箱）；折线/散点为
   `len(points) + missing.count == source.rows`；热图为单元格覆盖行数 + 缺失行数。
3. `legend.items` 与 `series[].label` 集合一致；单系列不显示图例。
4. `axis.min < axis.max`，刻度严格递增且落在范围内。
5. `source.normalized` 指向 `work/` 下的规范化 CSV，供复算与行号核对。
