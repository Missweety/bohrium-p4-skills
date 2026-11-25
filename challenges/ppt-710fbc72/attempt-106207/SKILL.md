---
name: academic-deck-template-fitter
description: 解析学术 PPT 模板的版式槽位（标题/正文/图注/页脚/日期/页码）与母版主题（颜色、字体、画布比例），把页面内容映射到正确占位符，并输出槽位映射表与合规检查（字号下限、WCAG 对比度、留白覆盖率、每页字数上限、页脚一致性）。支持直接改起始演示稿、按图号插入图像/原生表格、补图注/页脚/页码，并把页级证据写进备注与 result.json。支持 .pptx（OOXML 解析）+ template.json；装有 python-pptx 时按模板母版生成可编辑 pptx，缺失时用标准库兜底生成文本版 pptx 并如实标注未继承母版。交付模板画像、槽位映射、证据映射、合规报告、幻灯片规格 JSON、Marp/Markdown 源与逐页讲稿。适用于套用实验室/会议模板、检查排版合规、把生成稿落到指定版式；不适用于无模板的纯内容组织或自由设计。
version: 1.3.0
license: MIT
---

# 学术 PPT 模板与格式适配：先读模板，再落内容

把“套模板”拆成 **模板画像（probe）→ 内容规格（spec）→ 槽位映射（fit）→ 合规检查（compliance）→ 渲染/降级**。
核心主张：

1. **先解析再排版**：模板的槽位、字号、颜色、画布比例必须从文件里读出来，不凭经验假设；
2. **内容不被模板吃掉**：字号、对比度、留白、字数都是硬指标，不达标就换版式/拆页，不压字号；
3. **映射可复核**：每一页用了哪个版式、哪个标题槽、正文字号多少，都有表可查；
4. **无模板也能交付**：默认 16:9 槽位 + 明确标注，不阻塞、不假装匹配。

## 何时使用

触发（满足任一）：

- 用户给出 `.pptx` / `.potx` / `template.json`，要求“按这个模板做/套模板”；
- 要求检查字体、字号、对比度、留白、每页字数、页脚是否合规；
- 已有生成稿，需要落到指定版式并输出槽位映射；
- 题面 `case.json` 带 `template` / `template_path` / `theme` 等字段。

不触发：没有模板、只要求组织内容（走内容组织包）；要求自由视觉设计/动画；
只做论文写作或科研绘图。

## 输入识别（字段名容错）

读取 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与 `task.md`。
**先打开真实文件**，按内容判断任务。通用字段由 `kernel.py init` 宽松识别，
模板与页级字段再做一层容错：

| 语义 | 接受的别名 |
|-|-|
| 案例标识 | `case_id` / `caseId` / `id` / `task_id` / `case` |
| 模板文件 | `template` / `template_path` / `template_file` / `pptx` |
| 模板画像 | `template_profile` / `profile` / `theme` |
| 页列表 | `slides` / `pages` / `deck_outline` / `deck` |
| 受众/时长 | `audience` / `target_audience`；`duration_min` / `minutes` |
| 页数上限 | `max_slides` / `max_pages` / `slide_limit` |
| 字号要求 | `min_font_pt` / `font_floor` / `min_fonts` |
| 语言 | `language` / `lang` |

模板可能是：`/input/materials/template.pptx`、`/input/template.json`，
或题面直接说明“使用会议模板”（此时按默认槽位并在 `uncertainty` 写明）。
**题面阈值优先于本包默认值**；题面没给才用默认。

开工前确认：模板路径、目标画布比例（16:9 / 4:3）、字号与字数要求、
是否需要按模板生成 pptx、`output_contract` 字段名。

**运行目录与解释器**：以下命令默认在 skill 根目录（含 `SKILL.md` 的目录）执行。
若不确定当前目录，先 `cd` 到 skill 根目录；也可用绝对路径
`python3 /skills/weekly-skill/scripts/...`。环境没有 `python` 时统一用 `python3`。

**契约形态**：`case.json.output_contract` 可能是对象、字符串数组，或
`[{name,type,...}]` 字段规格数组。`kernel.py init` 会原样落盘，`emit` 用
`contract_field_names()` 统一取字段名；三种形态都必须能写出 `result.json`，
不得因字段规格对象而崩溃或只写 `fields: null`。

## 执行流程

1. **契约**：`python3 scripts/kernel.py init --case /input/case.json --out work`
   → `work/contract.json`。
2. **材料索引**：`python3 scripts/kernel.py index --materials /input --out work`
   → `work/evidence.json` + `work/corpus.txt`。
3. **模板画像**：
   `python3 scripts/template_fit.py probe --template /input/materials/template.pptx --out work`
   → `work/template_profile.json` + `template_profile.md`：
   - 画布：`slide_size.w_in / h_in`
   - 主题：`theme.colors`（dk1/lt1/accent1…，含 `clrMap` 映射）、`theme.fonts`（major/minor）
   - 版式：`layouts[].name` 与 `slots.{title,body,caption,footer,date,number}`，
     每个槽位含占位符类型、idx、字号、位置（英寸）
   - `.pptx` 走 OOXML（zip + XML），**不需要 python-pptx**；`.json` 走规范化。
4. **写内容规格** `work/deck_spec.json`：页型、判断句标题、要点、`visual`、
   `notes.say`。密度规则与内容组织包一致（≤6 条、每条尽量短），
   但**以模板槽位容量为准**：正文字号越小、版式正文区越小，越要拆页。
   图表页写 `visual.type`（figure/table）、`ref`（图号/表号）、`caption`，
   图像写 `visual.path`（材料目录内相对路径），表格写 `visual.table = {header, rows}`；
   未给 `path` 时按 `ref` 的数字整词匹配文件名（`Fig. 1` 不会误配 `fig10.png`），
   仍找不到则只保留图注并写 `uncertainty`，不臆造。
   非标题页尽量给 `evidence`（`ref/quote/locator`），供页级证据映射。
5. **映射与合规**：
   `python3 scripts/template_fit.py fit --spec work/deck_spec.json --profile work/template_profile.json --out work --template <模板> --materials /input/materials [--base-deck <起始稿>]`
   （或 `--template <path>` 一步完成）→
   `work/slot_map.json` + `slot_map.md`（每页版式与槽位）、
   `work/compliance.json` + `compliance.md`（逐项检查）、
   `deck_spec.json`（含 `layout`）、`deck.md`、`speaker_notes.md`、`draft.json`，
   同时按真实模板母版生成 `deck.pptx`：逐页套用版式，填标题/正文/图注/页脚/页码，
   图表页按 `visual.path` 等比插入图像、按 `visual.table` 插入原生表格，
   并把页级证据写入演讲者备注；再用 LibreOffice 转 `deck.pdf` 预览。
   题面若给起始演示稿，用 `--base-deck` 在原页上改写（页数不足才新增页）。
   没有 python-pptx 时用标准库兜底生成文本版 pptx，并写明未继承母版。
6. **处理不合规**（见下表）：优先换版式 → 拆页 → 精简文字 → 调模板；
   **不允许**为通过检查而压字号、改单位、删证据。
7. **落盘**：`emit` + `finalize` + 复制产物：

```bash
python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output
python3 scripts/template_fit.py finalize --work work --out /app/output
cp work/deck_spec.json work/deck.md work/speaker_notes.md work/slot_map.json work/compliance.json /app/output/
cp work/deck.pptx work/deck.pdf /app/output/ 2>/dev/null || true
python3 scripts/kernel.py check --out /app/output
python3 scripts/template_fit.py selfcheck --work /app/output
```

## 合规规则（对齐评分维度）

| 检查 | 阈值 | 级别 | 处理 |
|-|-|-|-|
| 字号下限 | title 28 / body 18 / caption 12 / footer 9 pt | 硬错误 | 换大字号版式或拆页 |
| 对比度 | 正文/背景 ≥4.5；强调色/背景 ≥3.0 | 硬错误/警告 | 换深色字或浅底 |
| 留白 | 槽位覆盖 ≤75%；>90% 硬错误 | 警告/硬错误 | 减内容或换版式 |
| 边距 | 左 ≥0.3 in、上 ≥0.25 in | 警告 | 调整版式 |
| 每页字数 | ≤380 字（标题+主张+要点） | 硬错误 | 拆页/精简 |
| 槽位覆盖 | 非标题页须有 title+body；图表页建议 caption | 硬错误/警告 | 换版式 |
| 页脚 | 整册统一 ftr | 警告 | 统一母版 |
| `slot_map` 完整性 | 条数 = 页数 | 硬错误 | 修版式选择 |

只检查**实际使用**的版式；模板里未使用的版式不参与字号/留白判定（避免误报）。

## 硬性禁止

- 不伪造模板信息：解析不到颜色/字号就写“未声明”，不填看起来合理的值。
- 不压字号过关：正文不得低于 18 pt；投影场景宁拆页。
- 不静默改单位、数值、图号来凑字数或对比度。
- 不把内容塞进图注/页脚槽位；槽位语义必须匹配。
- 不声称“已按模板生成 pptx”而没有真实文件。
- 模板缺失/损坏时不得报错退出：降级默认槽位并写 `uncertainty`。
- 不提交预制答案；映射必须由本次读取的模板与内容推导。

## 输出契约

见 `references/output-contract.md`。要点：

- `result.json`：`case_id`、`status`、`template`、`artifact_path`、`artifact_format`、
  `slide_count`、`deck_outline`（每页含 `layout`）、`slot_map`、`evidence_map`
  （页级证据：slide/ref/quote/locator）、`compliance`、`notes_path`、`render_log`
  （含 `tool` 与逐页 `pages`：版式、图/表、图注、证据条数）、`self_check`、
  `uncertainty`、`limits`。
- `status`：`ok` = 合规无硬错误且有导出件；`partial` = 有硬错误/缺依赖；
  `blocked` = 模板与内容都不可读；`refused` = 要求伪造模板或数据。
- `compliance.checks` 每项：`{check, level, detail}`，`level` ∈ error/warning/info。

## 自查

1. `compliance.json.errors` 为 0；每条 warning 能解释或已改。
2. `slot_map` 条数 = 页数；每页 `layout` 来自模板画像。
3. 字号、对比度、留白、字数四项均有检查记录（不能缺项）。
4. 图表页有 `caption` 槽位或有明确警告；有图像文件时 pptx 里确实插入了图，表格是原生表。
5. `speaker_notes.md` 页数 = 页数；`selfcheck` PASS。
6. `result.json.case_id` 与输入一致；`template.source` 与实际模板对应。
7. `render_log.pages` 条数 = 页数，且 `evidence_map` 覆盖所有非标题页（缺证据已写 warning）。
8. 有起始稿时，按规格页数复用并裁剪起始页（不足才新增）；复用页会清掉页内旧文本/旧图/旧表
   （空装饰形状与母版/版式设计保留），旧页与旧内容不残留。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 未给模板 | 默认 16:9 槽位，`template.source=default` + `uncertainty` |
| 模板损坏/加密/非 pptx | 捕获异常，降级默认槽位，不崩溃 |
| 槽位无字号声明 | warning，提示人工确认，不臆造 |
| 无 caption 槽位 | 图表页 warning，建议换带图注版式 |
| 无 footer 槽位 | 全局 warning，不阻断 |
| 主题色缺失 | 跳过对比度计算并 warning，不假装通过 |
| 字节数/页数超限 | 拆页或精简文字，不压字号 |
| 无 python-pptx | 用 `pptx_min.py` 标准库兜底生成文本版 pptx + 画像/映射/合规/讲稿；`uncertainty` 写明未继承母版 |
| 无 LibreOffice/PDF | 不声称已渲染；exports 只列真实文件 |
| 预算耗尽（900 s / 64 请求） | 先落盘 `template_profile.json` + `slot_map.json` + `compliance.json` |

## 文件说明

- `scripts/kernel.py`：init / index / verify / emit / check，仅标准库，无网络。
- `scripts/spec_io.py`：别名容错、规格规范化、Marp/讲稿渲染、按模板构建 pptx（图/表/图注/页脚/页码/备注）。
- `scripts/pptx_min.py`：python-pptx 缺失时的标准库 pptx 兜底构建（文本版，不继承母版）。
- `scripts/template_fit.py`：probe / fit / check / finalize / selfcheck；
  OOXML 解析、槽位映射、字号/对比度/留白/字数检查。
- `scripts/quote_check.py`：证据引文逐字核验。
- `references/output-contract.md`：模板/槽位/合规字段与阈值。
- `references/quality-rubric.md`：5 个评分维度 → 本包检查项。
- `references/example.md`：合成模板与适配示例（非正式答案）。

## 最小调用示例

```bash
python3 scripts/kernel.py init --case /input/case.json --out work
python3 scripts/kernel.py index --materials /input --out work
python3 scripts/template_fit.py probe --template /input/materials/template.pptx --out work
python3 scripts/template_fit.py fit --spec work/deck_spec.json --out work \
    --profile work/template_profile.json \
    --template /input/materials/template.pptx --materials /input/materials
python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output
python3 scripts/template_fit.py finalize --work work --out /app/output
cp work/deck_spec.json work/deck.md work/speaker_notes.md work/slot_map.json \
   work/compliance.json work/deck.pptx work/deck.pdf /app/output/ 2>/dev/null || true
python3 scripts/kernel.py check --out /app/output
python3 scripts/template_fit.py selfcheck --work /app/output
```

示意输出（示例）：`probe: layouts=11 colors=12 warnings=0`；
`fit: slides=5 layouts=11 errors=0 warnings=3 pptx=yes`。

## 修订版处理边界

起始稿与目标模板是不同文件时，辅助脚本不具备把旧页忠实迁移到新母版的能力：会返回未生成并注明原因，不能宣称模板已应用。需要执行的 Agent 应读取原页与目标模板，用实际可用的演示文稿工具在目标母版中新建页并迁移各项内容、图表、备注；渲染逐页核验，缺能力则如实 partial。输出文件不得覆盖原模板或起始稿，图号匹配不唯一时需人工核对或提供明确路径。PDF 渲染以本次进程成功及新文件验证为准；命令非零时不得采用历史产物。


### 图像与源文件完整性（v3）
指定的 `visual.path` 优先且必须真实存在，缺失时不再按图号猜测替代图；检查报告标记 missing-image 和 partial。显式传入的模板或起始稿不可读时停止生成，不静默换默认模板。PPTX 或 PDF 未生成、指定图表缺失时只能 partial。不同母版的起始稿和模板仍不支持自动迁移；先逐页读取原稿并由 Agent 显式迁移，再检查内容和目标母版，不能宣称自动完成。

## 改动记录（v1.3.0，2026-11-25）

本版只改可复现的真实缺陷，合成夹具实测（非官方案例）。模板编辑链（python-pptx 打开模板 → 清空模板示例页 → 按版式 `add_slide` → 复用版式标题/正文占位符 → 写备注 → 保存）经 zip 复核：产物仍含 11 个 `slideLayout`、`slideMaster1`、`theme1/theme2`，`[Content_Types].xml` 主部件为 `presentation.main+xml`，占位符 idx 0/1 继承自版式。

1. **空规格报 ok**：`slides=[]` 时旧逻辑 `errors=0`、`status=ok`、rc0，导出 0 页 pptx。现视为硬错误（“空稿不能判合规”），`partial`、rc1。
2. **缺图/未插表只留在 render_log**：旧 `limits` 为空却 `partial`，复核者看不到原因。现把“某页图表未真实插入”写进 `limits`、`uncertainty`，rc1。
3. **复用旧页时版式未真正切换却照常 ok**：`--base-deck` 复用页无法改 `slide_layout`，旧包只记录实际版式。现比对规格期望版式与实际版式，不一致写 `limits` 并降为 `partial`，不再静默。
4. **`check`/`selfcheck` 不核导出件**：`result.json` 写 `status=ok`、`artifact_path=deck.pptx` 时，文件被删仍 PASS。现状态为 ok/success 时逐项校验 `artifact_path` 与 `render_log.exports` 真实存在。
5. **`render_log.template` 泄露本机路径**：现只写模板文件名。
6. **非法 deck_spec.json 抛栈**：现打印 blocked 并返回 1。
7. **`visual.path` 带 `materials/` 前缀找不到图**：现先按原相对路径、再按文件名回退。
8. **`fit` 退出码与真实状态脱节**：旧为“无硬错误即 0”，缺图/未继承模板也 rc0。现 rc0 仅当 `draft.status=ok`。

实测（`/tmp/t4`，13.333×7.5in 模板 + 10 页规格 + 真实 PNG + 原生表格）：`fit: slides=10 layouts=11 errors=0 warnings=5 pptx=yes`，`status=ok`、`fit rc=0`；`deck.pptx` 10 页、第 6 页 PICTURE、第 7 页 TABLE、备注齐、模板示例页 STALE 文本无残留、模板文件哈希不变；`deck.pdf` 10 页；`emit→finalize→kernel check→selfcheck` 全 PASS，契约字段无缺失/无类型错误。缺 `fig2b.png` 时 `partial`+`limits` 指明第 8 页、rc1；起始稿用 Two Content 而规格要 Title and Content 时 `partial` 并逐页报版式不一致；删 `deck.pdf` 后 `kernel check` FAIL。

