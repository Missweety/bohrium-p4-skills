# apparatus spec 字段与错误码

`work/spec.json` 是唯一可编辑真源：部件坐标、连线端点、阶段字段与证据都在这里，SVG 由脚本重建。

## 1. 顶层结构

```json
{
  "figure": {"width_px": 1500, "height_px": 1300, "dpi": 300,
             "title": "连续流催化加氢装置与技术路线",
             "apparatus_bbox": {"x": 16, "y": 72, "w": 1468, "h": 660},
             "stage_bbox": {"x": 16, "y": 740, "w": 1468, "h": 250},
             "legend_at": [32, 1020]},
  "parts": [{"id": "pump", "label": "进料泵", "type": "pump", "shape": "circle",
             "x": 300, "y": 190, "w": 110, "h": 110, "font_pt": 9, "sub": "0.5 mL/min",
             "status": "stated", "evidence": "02_api_raw/case.json#parts.pump"}],
  "connections": [{"id": "c1", "from": "feed", "to": "pump", "kind": "material",
                   "label": "原料", "status": "stated", "evidence": "…", "direction": "forward"}],
  "stages": [{"id": "s1", "order": 1, "label": "催化剂装填与活化",
              "objective": "装填 0.5 g Pd/C 并以氢气原位还原 2 h。",
              "outputs": ["活化床层"], "milestone": "氢气消耗稳定",
              "depends_on": [], "status": "stated", "evidence": "…"}],
  "units": {"temperature": "°C", "pressure": "MPa", "flow": "mL/min"},
  "scale_bar": {"label": "示意，非等比", "length_px": 0},
  "caption": "图 3 …",
  "notes": ["虚线=推断连接"]
}
```

## 2. 字段约束

| 对象 | 必填 | 可选 | 约束 |
|-|-|-|-|
| figure | `width_px`、`height_px`、`title` | `dpi`、`apparatus_bbox`、`stage_bbox`、`legend_at` | 装置区与路线区不得重叠；标题是机检项 |
| parts | `id`、`label`、`type`、`x/y/w/h` | `shape`、`sub`、`font_pt`(≥7)、`status`、`evidence`、`data_ref` | 必须落在 `apparatus_bbox` 内；不可互相重叠；`stated` 必须有 evidence |
| connections | `id`、`from`、`to`、`kind` | `label`、`status`、`evidence`、`direction` | 端点必须是部件 id；`direction` 取 forward/bidirectional |
| stages | `id`、`order`、`label`、`objective`、`outputs` | `milestone`、`depends_on`、`status`、`evidence` | order 从 1 连续；`depends_on` 只能指向更早的 order；milestone 可选，材料未声明时只告警并写入 uncertainty；阶段落在 `stage_bbox` 内 |
| legend | `kind` | `text`、`status` | 缺省按实际 kind 自动生成 |
| units | 至少一项 | — | 缺单位时写定性说明并进 `uncertainty` |
| scale_bar | `label` | `length_px` | 有长度时 30–420 px；无长度则标签含“示意/not to scale” |

`type` 与外观（Okabe-Ito + 形状，不依赖颜色也能区分）：

| type | 中文 | 形状 |
|-|-|-|
| reservoir / vessel | 储液储气 / 容器 | 圆角矩形 |
| pump | 泵 | 圆形 |
| valve | 阀 | 菱形 |
| reactor | 反应器 | 圆角矩形 |
| column | 柱/分离柱 | 竖柱 |
| detector / instrument | 检测器 / 仪器 | 仪器框 |
| sensor | 传感器 | 三角 |
| separator | 分离器 | 仪器框 |
| waste | 废液废气 | 废料框 |
| tubing / support | 管路 / 支架 | 圆角 / 直角 |

`kind` 与线型：`flow` 蓝实线、`material` 品红实线、`gas` 浅蓝点划线、`energy` 橙虚线、
`signal` 绿点线、`waste` 红长虚线。

## 3. 构建期错误码（`route_spec.py build --strict`）

| code | 级别 | 处理 |
|-|-|-|
| `bad_canvas` / `missing_title` / `bad_bbox` | error | 补画布、标题、面板框 |
| `duplicate_id` / `missing_label` / `missing_parts` | error | 改 id、补标签、至少一个部件 |
| `bad_part_type` / `bad_shape` / `font_too_small` | error | 用枚举值，字号 ≥7 pt |
| `part_outside_apparatus` / `out_of_canvas` / `part_overlap` / `text_overflow` / `text_outside_shape` | error | 调坐标、加宽/加大形状或缩字号换行（不截断实体名） |
| `bad_connection_ref` / `bad_kind` / `bad_direction` / `connection_without_direction` | error | 端点用部件 id、kind 用枚举、方向显式 |
| `self_loop` / `duplicate_connection` / `isolated_part` / `connection_label_long` | warn | 逐条判断是否漏画或画错 |
| `too_few_stages` / `bad_stage_order` / `unknown_dependency` / `bad_dependency` | error | 阶段 ≥2、order 连续、依赖只能指向前序 |
| `missing_objective` / `missing_outputs` | error/warn | 每阶段写目标与产出 |
| `missing_milestone` | warn | 材料未声明里程碑时只告警，不虚构、不阻断 |
| `stage_outside_panel` / `stage_out_of_canvas` / `stage_overlap` / `stage_text_overflow` | error | 调 `stage_bbox`、阶段高度或缩短文字（渲染会换行并在超出时截断） |
| `legend_out_of_canvas` / `legend_overlaps_stage_panel` / `legend_missing_kind` / `legend_extra_kind` / `legend_too_long` | error/warn | 改 `legend_at`、删手写图例、合并同义流向 |
| `missing_units` / `missing_scale_bar` / `missing_scale_length` / `bad_scale_length` | error/warn | 补单位与比例尺说明 |
| `missing_evidence` | error | stated 元素补材料定位，或降级为 inferred |

## 4. 自检错误码（`route_check.py`，解析 SVG）

`missing_svg`、`svg_parse`、`svg_root`、`missing_layers`、`missing_title`、`title_not_rendered`、
`part_count_mismatch`、`part_not_rendered`、`part_without_title`、`part_without_source`、
`connection_count_mismatch`、`connection_not_rendered`、`connection_without_direction`、
`connection_without_source`、`bad_connection_ref`、`stage_count_mismatch`、`stage_not_rendered`、
`stage_number_missing`、`stage_order`、`stage_without_source`、`milestone_not_rendered`、
`missing_milestone`、`bad_dependency`、`empty_structure`、`missing_legend`、`legend_missing_kind`、
`missing_units`、`missing_scale_bar`、`palette_not_colorblind_safe`、`missing_element_map`、
`element_map_incomplete`、`element_map_no_source`。

自检失败时先看 `errors[].element` 定位，再回 `spec.json` 修，不要手改 SVG。
