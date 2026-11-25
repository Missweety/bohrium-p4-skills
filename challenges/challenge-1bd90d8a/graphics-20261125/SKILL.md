---
name: source-traced-figure
description: 从科研数据表生成可编辑、可核验的图表（柱状/分组柱/折线/散点/直方/箱线/热图/多面板），或按指令修改已有 SVG/spec。输出 SVG+PNG+PDF、图注、图元—源行映射和 result.json，并自带机检。Use for scientific data figures, chart generation, chart editing, figure specs, element-to-source tracing.
version: 1.5.0
---

# source-traced-figure

把「数据表 / 已有 SVG + 工单」变成「图件 + 图注 + 图元—源行证据链 + result.json」。
所有数值由脚本从运行输入计算，不预置答案、不猜测缺失值、不做统计检验。

## 什么时候用 / 不用

用：
- 输入是 CSV / TSV / XLSX 表格，要求出柱状图、分组柱状图、折线图、散点图、直方图、
  箱线图、热图或多面板组合图。
- 需要图注、误差线口径、样本量、单位、缺失/异常值声明，或需要每个图元对应到源表行号。
- 要求修改已有图：改标题、改图型、改 y 轴范围、加标注、高亮某组，并保留可逆证据。

不用：
- 机制图、流程图、示意图、纯插图（本包只做数据图）。
- 需要统计检验/显著性推断（源表没有 p 值就不标，工具不代算）。
- 需要把扫描图片矢量化，或对 PNG 做像素级 PS。

## 运行时约定

- 案例：`/input/case.json`；材料目录 `/input`（含 task.md、数据表或 SVG）。
- 工作目录：`/app/work`（中间产物，可写）。
- 交付目录：`/app/output`（最终图件与 result.json）。
- 本 Skill 安装在 `/skills/weekly-skill`；命令中的 `scripts/` 相对该目录。
- 预算：64 次模型请求、900 秒；脚本本身不发网络请求。

## 一条命令（首选）

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --case /input/case.json --materials /input \
  --work /app/work --out /app/output
```

成功后 `/app/output` 至少有：
`result.json`、`figure.svg`、`figure.png`、`figure.pdf`、`caption.md`、
`element_map.json`、`chart_spec.json`、`chart_plan.json`、`data_profile.json`、
`selfcheck.json`、`render_meta.json`、`data_snapshot.json`；
有改图指令时还有 `chart_spec.original.json` 与 `edit_log.json`。

`run_case.py` 的退出码：0 = result.json 已写出（含普通 blocked/partial）；1 = 选出
的 y 列没有任何可用数值、面板为零图元（仍写出 `result.json`、`selfcheck=FAIL`）；
2 = 连 result.json 都写不出（此时看 `/app/work/run_log.txt`）。

可选覆盖（仅在 case 文本歧义时用）：
`--x COL --y COL --group COL --intent bar|grouped_bar|line|scatter|hist|box|heatmap|panel`
`--error sd|sem|ci95|none`、`--title "..."`、`--no-raster`。

## 分步执行（`run_case.py` 不可用或需要干预时）

```bash
cd /app/work
S=/skills/weekly-skill/scripts
python3 $S/kernel.py init --case /input/case.json --materials /input --work .
python3 $S/profile_data.py --input /input/data.csv --out .
python3 $S/plan_figures.py --input /input/data.csv --out . \
  --hint task.md --error sd [--x COL --y COL --group COL --intent TYPE]
python3 $S/build_spec.py --plan chart_plan.json --out . \
  --source-path /input/data.csv --normalized normalized.csv
python3 $S/map_elements.py --spec chart_spec.json --out /app/output
cp chart_spec.json data_profile.json /app/output/
python3 $S/render_figure.py --spec /app/output/chart_spec.json --out /app/output
# 若上一步因缺 matplotlib 退出 3：
python3 $S/svg_render.py --spec /app/output/chart_spec.json --out /app/output
python3 $S/check_figure.py --spec /app/output/chart_spec.json \
  --work /app/work --out /app/output
python3 $S/kernel.py emit --draft /app/work/draft.json --out /app/output
python3 $S/kernel.py check --result /app/output/result.json --work /app/work
```

改图（在 build_spec 之后、map/render 之前）：

```bash
# 改 spec：标题/图型/y 范围/标注/高亮/文本替换
python3 $S/edit_figure.py spec --spec chart_spec.json --out /app/output \
  --title "新标题" --chart-type line --y-min 0 --y-max 30 \
  --annotate "复核后修订" --highlight HighDose --set-text "Control=对照"
# 改已有 SVG：只做结构保留的标题/标注/高亮/文本替换
python3 $S/edit_figure.py svg --svg /input/source.svg --out /app/output \
  --title "新标题" --annotate "说明" --highlight HighDose
python3 $S/check_figure.py --svg-only --work /app/work --out /app/output
```

## 图型选择（确定性映射，工单指定优先）

| 数据结构 | 默认图型 |
|-|-|
| 分类 × 连续 | `bar`（柱高=组均值，误差线默认 SD） |
| 分类 × 分类 × 连续 | `grouped_bar`（x=第一分类，系列=第二分类） |
| 时间/有序 × 连续 | `line`（按 x 排序，可带误差线；两列都是数值时第一列为 x） |
| 连续 × 连续 | `scatter` |
| 单列连续 | `hist`（10 个等宽箱） |
| 分类 × 连续，要求分布 | `box`（Tukey 1.5×IQR） |
| 行标签 × 多个数值列，或 两个分类 + 连续 | `heatmap`（离散 Viridis） |
| 明确要求组合面板且存在分组列 | `panel` |

规则细节与误差线口径见 `references/chart-types.md`。

## 输入兼容与降级

- 编码：UTF-8 / UTF-8-BOM / GB18030 / Big5；分隔符：`,` `\t` `;` `|`。
- XLSX：标准库只读解析（zip + XML），自动选数值最多的 sheet；不执行宏。
- 列名单位：`体重(g)`、`[mg]`、`/kg`、`length_mm`、`expression_mg_ml` 会拆成
  变量名 + 单位；轴标签写成 `变量 (单位)`。
- 缺失/非数值：`NA`、`N/A`、`-`、空、`<LOD`、`>LOQ` 不参与统计，逐行记录。
- 完全重复行：保留并在图注声明（默认不去重）。
- 多数据文件：优先任务文本点名的文件，否则选数值覆盖最高者，并把候选写入 `uncertainty`。
- 类别 > 12：前 11 类 + `Other`，并在 caveat 声明。
- 无 matplotlib：自动回退标准库 SVG（几何/数值/文字正确），`status=partial`，
  `limits` 写明无 PNG/PDF；若本机有 cairosvg/rsvg-convert/inkscape 会自动补栅格。
- 无 CJK 字体：保留原文 `<text>` 并写 `limits` 警告，不静默替换成方框。
- `case.json` 不可解析：按默认契约继续，`uncertainty` 记录原因；有数据仍出图。
- 无数据且无 SVG：`status=blocked`，`result.json` 仍包含全部契约字段和原因。
- 选出的 y 列全空：`status=blocked`、`selfcheck=FAIL`、退出码 1；绝不把零图元
  当 `ok/PASS`。
- 分组列选择：常量列或缺失率 >30% 的列不会被用作 x/系列（例如空的 `note`）。

## result.json 契约

`references/output-contract.md` 定义了默认字段与一致性约束。核心字段：
`case_id`、`status`（ok/partial/blocked）、`figure_svg/png/pdf`、`caption`、
`element_map`、`data_profile`、`selfcheck`、`sources`、`limits`、`uncertainty`、
`change_log`、`deliverables`、`metrics`。原 case 的 `output_contract` 字段全部保留；
无法映射的字段进入 `unmapped_contract_fields`，不会得到空对象。

## 自查与失败处理

```bash
python3 /skills/weekly-skill/scripts/check_figure.py \
  --spec /app/output/chart_spec.json --work /app/work --out /app/output
```

- 退出 0 = `selfcheck.json.verdict=PASS`；退出 1 = FAIL，`errors` 给出具体元素/数值。
- 常见 FAIL 与修法见 `references/checklist.md`（例如轴范围越界、图例不同步、
  图元与源行不符、caption 缺误差线口径）。
- 不得为了过检而删检查、改数值或伪造 `note`；把无法核验的内容写进 `limits` /
  `uncertainty`，并把 `status` 降为 `partial`。

## 依赖

- Python 3.9+ 标准库（必需）。
- matplotlib（可选）：提供 PNG/PDF、抗锯齿与精确排版；缺失时自动降级。
- cairosvg / rsvg-convert / inkscape（可选）：把降级 SVG 转成 PNG/PDF。
- 不访问网络，不读取环境变量中的凭据，不写 `/Users/...` 绝对路径。

## 改动记录

- **1.5.0（2026-11-25）**：修复真实运行中复现的 5 个缺陷——
  1) 折线图在两列均为数值、任务点名“折线图/source_value_chart”时 x 列为空，
     `plan_figures.py` 抛 `UnboundLocalError: repeated` 并静默回退 histogram；
     现取首个数值列为 x、次列为 y，`repeated` 预置默认值，不再静默换图型。
  2) 直方图零计数分箱在 `element_map.json` 中没有 `source_rows`，导致
     `selfcheck` 误判 FAIL（单列数据必然触发）；现标记 `empty=true` 并只对非空箱
     要求可追溯源行。
  3) 负值柱的数据标签画在柱体内部（与柱色重叠不可读）；现负值标签落在柱下方，
     并为 bar 轴留出上下 5–6% 余量，标签不再压住刻度。
  4) 超长分类名被截成两行加省略号，图上丢失类别身份；现旋转标签按可用高度
     换 4–5 行，保留完整名称。
  5) 多行长的 `n<3` 图注会溢出画布并被裁切；现超长时压缩为
     “n<3 in k of N categories”，完整名称留在 caption.md。
  另将“缺失行”措辞由 excluded 改为 not drawn，避免把部分缺失误述为整行剔除。

## 限制

- 不做统计检验、不推断缺失值、不对异常值做自动剔除。
- 显著性只转写源表已有的 p 值/标记；源表没有就不标。
- SVG 编辑模式不做数据复算，也不重新导出 PNG/PDF（`status=partial`）。
- 图型转换（bar↔line↔grouped_bar）仅在同一面板、且数值层可重建时进行；
  跨图型（如 heatmap↔line）会给出 warning 并保留原图型。
- 热图/多面板的行列数有上限（行 30、列 12，面板 4）；超出会截断并声明。

## 最小示例（合成数据，非案例答案）

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --case /app/work/example_case.json --materials /app/work/example \
  --work /app/work/example_work --out /app/work/example_out
```

`references/example.md` 给出该合成表格、case.json、预期关键输出（含真实运行数字）
和逐项核验方法。示例只用于验证工具行为，不是任何评测案例的答案。
