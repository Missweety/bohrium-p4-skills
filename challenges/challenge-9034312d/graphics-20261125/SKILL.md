---
name: apparatus-route-figure
version: 2.1.0
description: 把实验材料（文本/PDF/DOCX/XLSX）或已有 SVG 变成可编辑、可核验的“实验装置 + 技术路线图”：SVG（真实 <text>、方向箭头、线型图例、比例/未知标记）+ PNG + PDF + 图注 + 图元—源材料证据链（element_map）+ result.json，并自带机检与阻断逻辑。Use for apparatus diagrams, experimental setup figures, technical route/roadmap, labeled flow steps, and SVG figure editing with preserved structure.
---

# apparatus-route-figure

把「实验方案 / 装置清单 / 已有 SVG + 修改工单」变成「装置与技术路线图 + 图注 +
逐元素证据链 + result.json」。所有部件、连线与步骤都来自运行输入；材料没写的内容
不补画、不猜尺寸，推断项在图上用虚线/虚框并逐条登记。

## 什么时候用 / 不用

用：
- 需要“实验装置图”“实验流程图”“技术路线图/路线图”“装置连接关系”“带步骤的路线”。
- 材料是操作协议、方法段落、装置清单、论文实验部分，或 PDF/DOCX/XLSX 表格。
- 需要改已有 SVG/规格：改标签、加标注、高亮某设备，并要求保留未改动结构、给出
  before/after 哈希与变更清单。

不用：
- 纯数据图表（柱/线/散点/热图）——用 source-traced-figure。
- 需要把扫描图片/照片自动矢量化或 OCR 出精确文字（无文本层时会明确 blocked，不猜）。
- 需要真实工程制图尺寸（本包只做“示意、非等比”的可编辑矢量图）。

## 运行时约定

- 案例：`/input/case.json`；材料目录 `/input`（含 `task.md` 与材料文件）。
- 工作目录：`/app/work`（中间产物）；交付目录：`/app/output`。
- 本 Skill 安装在 `/skills/weekly-skill`；下文 `scripts/` 相对该目录。
- 预算：64 次模型请求、900 秒；脚本不联网。

## 一条命令（首选）

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --case /input/case.json --materials /input \
  --work /app/work --out /app/output
```

它会自动判断三种模式并写完 `result.json`：

| 模式 | 触发 | 产出 | status |
|-|-|-|-|
| 生成 | 材料里有可提取的装置/步骤 | `route.svg/png/pdf`、`spec.json`、`route_graph.json`、`element_map.json`、`caption.md`、`selfcheck.json`、`result.json` | 全部通过=`ok`，否则=`partial` |
| 改图 | case 有 `edit_instructions`/`edits`/`mode=edit` 且存在输入 SVG | `route.svg`、`source_figure.svg`、`edit_log.json`（before/after 哈希+变更清单）、`edit_element_map.json`、`result.json` | 有栅格器=`ok`，否则=`partial`（不伪造 PNG） |
| 阻断 | 0 个部件/0 条连线/0 个真实步骤，或 case.json 损坏、扫描件无文本层 | `result.json`（+`extraction_report.json`），**不写任何图** | `blocked`，`selfcheck=FAIL`，并给出已检查的文件/行/引文 |

成功时 `/app/output` 至少包含：`result.json`、`route.svg`、`route.png`、`route.pdf`、
`caption.md`、`element_map.json`、`spec.json`、`route_graph.json`、`selfcheck.json`、
`extraction_report.json`、`exports.json`、`geometry.json`。

## 分步兜底（一条命令失败时）

```bash
python3 scripts/kernel.py init --case /input/case.json --materials /input --work /app/work
python3 scripts/route_extract.py --case /input/case.json --materials /input --out /app/output --name route
python3 scripts/route_spec.py build --spec /app/output/spec.json --out /app/output --name route
python3 scripts/export_preview.py --svg /app/output/route.svg --spec /app/output/spec.json \
  --out /app/output --name route --formats png,pdf --dpi 150
python3 scripts/route_check.py --out /app/output --name route --require-preview
python3 scripts/kernel.py emit --draft /app/work/draft.json --out /app/output --work /app/work
python3 scripts/kernel.py check --result /app/output/result.json --work /app/work
```

改图兜底：

```bash
python3 scripts/edit_svg.py --svg /input/figure.svg --case /input/case.json \
  --out /app/output --name route
```

`route_extract.py` 会写出中间表示 `spec.json`（`parts / connections / stages /
units / scale_bar`）。人工核对后可手改 spec 再 `route_spec.py build`；只改一处即可重建，
不需要手工拖拽。

## 契约（result.json）

- **每个 output_contract 字段都出现**；类型按 case 原样（dict/list/string/嵌套均可）。
  认不出的字段写 `null` 并列入 `unmapped_contract_fields`，绝不静默丢弃。
- **不把契约值再包一层 `fields`**；`case_id/status/deliverables/element_map/caption/
  selfcheck/limits/uncertainty/sources/change_log` 始终存在。
- 字段别名容错：`steps↔stages`、`components/equipment↔parts`、`links/pipes↔connections`、
  `legend/figcaption↔caption`、`editlog/changes↔change_log` 等；中文键
  `装置清单/连接关系/技术路线/图注/自检/证据/限制/不确定度` 同样映射。
- `status` 只有 `ok / partial / blocked / failed`；`ok` 必须同时满足：SVG 存在、
  ≥1 条有向连线、≥1 个真实步骤（占位阶段不算）、PNG+PDF 非空、`selfcheck.ok=true`、
  ≥2 个路线阶段。0 连线或 0 步骤时 `status=blocked` 且 `selfcheck=FAIL`，不出图；
  材料未写里程碑只发 warning + uncertainty，不 FAIL、不虚构。

## 证据链（element_map）

每个部件、连线、步骤一行：

```json
{"element":"reactor","label":"固定床反应器","type":"part","subtype":"reactor",
 "source":"protocol.md:L3","locator":"protocol.md:L3",
 "quote":"装置由原料瓶、蠕动泵、固定床反应器、冷凝器和产物收集瓶组成。",
 "data_ref":"protocol.md:L3","status":"stated"}
```

- `status=stated`：材料原句明确写出；`inferred`：由上下文补全；`generated`：图例/单位/
  比例尺等生成件。
- 材料未写明的尺寸/温度/流量进入 `uncertainty` 与 `limits`，图上写“示意，非等比 / not to scale”。
- 图元的 `quote` 是真实源句；没有引文的元素不得标 `stated`。

## 鲁棒性

- 多材料合并；同一部件重复出现按名称/ID 去重。
- PDF 有文本层则读；扫描件/无文本层 → 明确写警告，不猜页内容。
- XLSX 读全部工作表（含 XML 实体还原）；DOCX 读正文；CSV/TSV/MD/TXT 直接读。
- 缺坐标由布局脚本计算（蛇形网格 + 阶段卡）；长 CJK 标签自动换行/截断。
- 缺 matplotlib 时导出走 SVG 兜底并标 `partial`；改图模式优先 cairosvg/rsvg/inkscape，
  都没有时用 matplotlib 重放编辑后的 SVG 生成 PNG/PDF（矩形/圆/线/折线/路径 M-L-C-Q/文本/箭头；
  渐变、滤镜、裁剪、弧线以 SVG 为准），仍不伪造无关预览。
- 英文材料：按英文句号切句（不切 `1.` 编号与小数），识别 `pump/valve/reactor/bottle/...`
  名词短语与 `connects by tube to / feeds / flows into` 流向；冠词与残留动词在标签清洗时去掉。
- 管路介质（硅胶管/软管/管路…）：只出现一处时按真实部件建节点（A→管→B）；同一介质在
  多处出现时改为连线属性 `medium`（A→B 且标注介质），避免共用节点形成星形枢纽。
- 装配说明 `在 A 与 B 之间加装 X 和 Y` 解析为 A→X→Y→B，方向由 A 指向 B。
- `case.json` 畸形/缺失 → `blocked`，带错误原文与已检查文件。

## 脚本清单

| 脚本 | 作用 |
|-|-|
| `scripts/run_case.py` | 一键编排：init → 生成/改图/阻断 → emit → check |
| `scripts/kernel.py` | 契约归一、材料读取（pdf/docx/xlsx）、result.json emit/check |
| `scripts/route_extract.py` | 材料 → `spec.json`（parts/connections/stages/units） |
| `scripts/route_spec.py` | spec lint + 渲染入口 |
| `scripts/route_svg.py` | 分层可编辑 SVG + `route_graph.json` + `element_map.json` |
| `scripts/route_check.py` | 机检：图层/证据/箭头/图例/比例/阶段/里程碑 → `selfcheck.json` |
| `scripts/export_preview.py` | PNG/PDF 导出（cairosvg/rsvg/inkscape/matplotlib/stdlib 兜底；`matplotlib-svg` 可重放任意 SVG） |
| `scripts/edit_svg.py` | 结构保留的 SVG 编辑（改字/标题/高亮/标注）+ before/after 哈希 + 变更清单 + 编辑后 PNG/PDF |
| `scripts/routelib.py` | 类型/形状/线型/换行等共享工具 |

## 版本与改动记录

### 2.1.0（本版，全部改动均由真实夹具复现后修复）

1. `run_case.py`：`--case/--materials/--out/--work` 统一 `abspath(expanduser(...))`；
   修复从任意 cwd 传相对路径时误报 `case.json not found` 并转为 `blocked`。
2. `route_extract.py`：句子级关系过滤（含流向动词的长句不再被当作单个部件名）。
3. `route_extract.py`：管路介质重复出现时改为连线 `medium`，修复 7 行
   “A 通过硅胶管连接到 B” 被抽成以“硅胶管”为中心的星形枢纽（10 条错边）；
   修复后主链 7 段 + 供气链 3 段方向正确。
4. `route_extract.py`：新增 `在 A 与 B 之间加装 X 和 Y → A→X→Y→B`，
   修复 `固定床反应器→质量流量计` 的方向反转。
5. `route_extract.py`：英文材料支持（英文句切分、`EN_PART_CORE` 名词短语、
   `connects by tube to / feeds / flows into`、冠词/残留动词清洗）；
   修复英文 PDF 抽取 0 部件直接 `blocked`。
6. `route_extract.py` / `route_svg.py` / `export_preview.py`：新增部件类型图例
   （类型 / Type：色块+形状，最多两行），修复“图例颜色/形状与图形不一致”。
7. `edit_svg.py`：支持 `set_title`（改写/插入 `<title>`，无可见标题时补可见标题），
   修复标题指令被静默丢弃；`highlight` 追加目标包围盒虚线框；未识别操作显式写入 warning。
8. `edit_svg.py` / `export_preview.py`：编辑后无原生栅格器时用 matplotlib 重放实际 SVG
   生成 PNG/PDF，修复改图模式只有 SVG、`status=partial`。
9. `route_check.py`：自检 detail 跳过 `<title>/<desc>` 文本，修复 “单位单位 / Units: …”。

## 参考

- `references/output-contract.md`：`result.json` 全字段 schema、类型与示例。
- `references/apparatus-spec-schema.md`：`spec.json` 中间表示字段。
- `references/quality-rubric.md`：评分维度 → 可勾选检查项。
- `references/limitations.md`：已知边界与不可承诺项。
