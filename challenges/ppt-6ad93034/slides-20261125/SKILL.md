---
name: academic-deck-generate-edit
description: 从论文/大纲生成学术演示稿，或按指令编辑指定页并输出逐页 diff。两种模式共用一份页级规格：先生成判断句标题、要点、图表引用与讲稿，再校验数字/图号能否回到原文，最后输出幻灯片规格 JSON、Marp/Markdown 源、逐页讲稿与 .pptx（装有 python-pptx 时）；编辑模式把"第几页、改什么、改成什么、为什么"记录成 diff 清单，未应用项与不确定性如实上报。适用于论文转 PPT、组会/答辩稿迭代、按导师意见改页；不适用于无原文的通用美化、科研绘图或论文润色。
version: 1.1.0
license: MIT
---

# 学术 PPT 生成与编辑：一稿到底，改动有据

把"做 PPT / 改 PPT"变成 **契约 → 材料索引 → 页级规格 → 审计 → 生成或编辑 → diff → 渲染/降级**。
核心主张：

1. **生成与编辑同构**：两种模式输出同一种 `deck_spec.json`，编辑后的稿仍过同一套质量门；
2. **改动必须可追溯**：每条编辑记录页号、字段、前后值与原因；没写原因就是没做完；
3. **数字与图号必须回到原文**：不按印象取整，不引用不存在的 Fig. 5；
4. **真实成品优先**：必须交可编辑 PPTX 和实际导出预览；未生成时只能报告 partial。生成模式传入真实模板；编辑已有稿时不得将本脚本当作原位编辑器，需直接编辑起始 PPTX 并保留未指定页面。
5. 图片引用需来自真实素材并写 `visual.path` 绝对路径；若源图不可用，记录缺失，不得称插入成功。

## 何时使用

触发（满足任一）：

- 给出论文/研究材料，要求"生成一版学术 PPT / 演示稿 / 组会 slides"；
- 给出已有稿或页级大纲，要求"把第 3 页标题改一下 / 压缩这几页 / 补一张结果页"；
- 要求记录每轮改了什么、为什么改，便于回退或交导师复核；
- 题面带 `output_contract`、页数、模板或版本记录要求。

不触发：要求凭空生成实验数据或结论；只做模板套用/版式合规（走模板适配包）；
只做论文写作/润色；只做科研绘图；只要求播放动画。

## 输入识别（字段名容错）

读取 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`。
通用字段由 `kernel.py init` 宽松识别，页级字段由 `spec_io.normalize_spec` 二次容错：

| 语义 | 接受的别名 |
|-|-|
| 案例标识 | `case_id` / `caseId` / `id` / `task_id` / `case` |
| 页列表 | `slides` / `pages` / `deck_outline` / `deck` / `slides_spec` |
| 受众 | `audience` / `readers` / `target_audience` / `listeners` |
| 时长/页数 | `duration_min` / `minutes`；`max_slides` / `max_pages` / `slide_limit` |
| 主线 | `mainline` / `narrative` / `story` |
| 要点 | `bullets` / `points` / `body` |
| 讲稿 | `notes.say` / `notes.script` / `notes.讲稿` |
| 图表 | `visual` / `figure` |

编辑指令 `edits.json` 也容错：页号 `slide` / `page` / `index`；值 `value` / `after` / `to`；
原因 `reason` / `why`。**题面字段永远优先**，本 Skill 只补全没给的。

开工前确认：材料语言与受众、页数/时长、是否给了起始稿（edit 模式）、
`output_contract` 字段名。缺失写 `uncertainty`，不默认。

## 执行流程

### A. 生成模式

1. **契约**：`python3 scripts/kernel.py init --case /input/case.json --out work`
   → `work/contract.json`。
2. **材料索引**：`python3 scripts/kernel.py index --materials /input --out work`
   → `work/evidence.json` + `work/corpus.txt`；不可读文件如实标记。
3. **写页级规格** `work/deck_spec.json`：`mainline` + `slides[]`。
   每页四件套：判断句 `title`（≤24 字）、`bullets`（≤6 条，默认每条 ≤40 字）、
   `visual`（原文图号 `ref`、图注和来源图像绝对路径 `path`）、`notes.say`（≥20 字，讲过渡与追问点）。
   先按贡献排序，不按论文章节顺序；一页只讲一件事。
4. **审计**：`python3 scripts/deck_build.py generate --spec work/deck_spec.json --out work --corpus work/corpus.txt`
   → `deck_spec.json`（规范化）、`deck.md`、`speaker_notes.md`、`deck_check.json`/`.md`、
   `diff.json`（生成模式为空）、`draft.json`、可选 `deck.pptx` 与 `deck.pdf` 预览。
   `errors > 0` 时先改规格，不改校验器。
5. **落盘**：`emit` + `finalize` + 复制产物（见“输出契约”）。

### B. 编辑模式

1. **底稿**：确认 `work/deck_spec.json` 或用户给的稿；先 `generate`/`check` 确认底稿可读。
2. **把指令翻成声明式编辑** `work/edits.json`：用户说“第 3 页标题改成 X”，就写
   `{"slide":3,"op":"set_title","value":"X","reason":"用户要求"}`。支持的操作：

   | op | value | 说明 |
   |-|-|-|
   | `set_title` / `set_takeaway` | 字符串 | 改单字段 |
   | `set_bullets` | 字符串数组 | 整体替换要点 |
   | `set_seconds` | 整数 | 调整讲稿时长 |
   | `set_notes_say` / `set_notes_why` | 字符串 | 改口播/过渡 |
   | `add_qa` | `{q,a}` | 追加预设问答 |
   | `set_visual` | `{type,ref,caption}` | 换图表引用 |
   | `replace_text` | `find` + `replace`（可加 `field`） | 页内替换 |
   | `insert_after` | 完整页对象 | 在指定页后插页 |
   | `delete` | 无 | 删页 |
   | `move` | 目标序号 | 调页序 |

   每条必须写 `reason`；无法映射成 op 的条目会进“未应用”表，**不得静默丢弃**。
3. **应用与 diff**：`python3 scripts/deck_build.py edit --base work/deck_spec.json --edits work/edits.json --out work_edit --corpus work/corpus.txt`
   → `work_edit/deck_spec.json`（新版）、`deck.md`、`speaker_notes.md`、
   `diff.json` + `diff.md`（第几页、什么操作、前后值、原因、未应用项）、`deck_check.*`、
   `draft.json`、可选 `deck.pptx` 与 `deck.pdf` 预览。
4. **复核**：逐条看 `diff.md`；任何“未在 edits 中声明”的 `drift` 都要解释或回退。
5. **落盘**：`emit` + `finalize` + 复制产物。

### C. 收尾（两种模式相同）

```bash
python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output
python3 scripts/deck_build.py finalize --work work --out /app/output
cp work/deck_spec.json work/deck.md work/speaker_notes.md work/diff.json work/diff.md /app/output/
cp work/deck.pptx work/deck.pdf /app/output/ 2>/dev/null || true
python3 scripts/kernel.py check --out /app/output
python3 scripts/deck_build.py selfcheck --work /app/output
```

`/app/output/` 需含 `result.json`、`deck_spec.json`、`deck.md`、`speaker_notes.md`、
`diff.json`、`diff.md`，生成了 pptx/pdf 时一并复制。`status=ok` 要求有导出件；否则 `partial` + `limits`。

## 页面与编辑规则（对齐评分维度）

| 主题 | 规则 | 反例 |
|-|-|-|
| 一页一主张 | 标题写结论；页面只留可指的证据 | 标题“实验结果二” |
| 数字 | 与原文同值同单位；不四舍五入美化 | 原文 31 um 写成“约 30 微米” |
| 图号 | 用原文编号；Fig./Table 必须能在 corpus 命中 | 原文 4 张图却引用 Fig. 5 |
| 示意 vs 数据 | 示意图标 `schematic` 且图注写“示意” | 示意图与实测柱状图并列比较 |
| 讲稿 | 讲过渡、强调、预设问答；不复述页面 | 备注 = 要点复制 |
| 编辑 | 只改指定页与指定字段；diff 逐条有原因 | 改一页顺手改母版/其他页 |
| 版本 | 保留 `work/deck_spec.json`，新版写 `work_edit/` | 覆盖原稿无法回退 |
| 交付 | 无 pptx 时如实 `partial`；不伪造渲染 | 声称“已导出 PDF”但无文件 |

## 硬性禁止

- 不虚构论文未报告的图、表、数值、样本量、显著性。
- 不改写数值与单位；不把 `p=0.03` 写成 `p<0.01`。
- 不把示意图当实验数据页；不把他文结果当本文结果。
- 编辑时不得静默改动未指定页；出现 `drift` 必须解释或回退。
- 不删除/覆盖用户原稿；新版写入独立目录。
- 不伪造 pptx/PDF 已生成；`render_log.exports` 只列真实文件。
- 不提交预制答案；页面必须由本次读取的输入推导。

## 输出契约

见 `references/output-contract.md`。要点：

- `result.json`：`case_id`、`status`、`mode`、`artifact_path`、`artifact_format`、`slide_count`、
  `deck_outline`、`notes_path`、`diff`、`changes`、`evidence_map`、`render_log`、
  `self_check`、`uncertainty`、`limits`。
- `diff` 每条：`{slide, op, field, before, after, reason}`；生成模式为 `[]`。
- `status`：`ok` = 审计通过且有导出件（编辑模式还要求 diff 非空）；`partial` = 缺依赖/
  有未应用编辑；`blocked` = 材料或底稿不可读；`refused` = 要求虚构数据。

## 自查

1. `deck_check.json.errors` 为 0；每条 warning 能解释或已改。
2. `diff.md` 的改动数与 `edits.json` 匹配；无“未应用”或已说明。
3. 页面数字、图号在 `corpus.txt` 命中；证据引文逐字命中（可加跑 `quote_check.py`）。
4. `speaker_notes.md` 页数 = `deck_spec.json` 页数；每页有 `say`。
5. 编辑后 `deck.md` 与 `deck_spec.json` 一致（同一次运行产出）。
6. `selfcheck` PASS；`result.json.case_id` 与输入一致。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 无底稿却要求编辑 | 先 `generate` 或 `check`；无材料则 `blocked`，不凭空造页 |
| 编辑页号越界 | 记入“未应用”，`uncertainty` 说明，不静默跳过 |
| 未知 op | 同上，并提示先翻译成声明式操作 |
| 编辑后审计报错 | 回改 `edits.json` 或页面；`status: partial` |
| 论文无文本层/加密 | 只用已读部分，`partial` + `limits` |
| 图为位图 | 引用编号与图注，不重绘假数据 |
| 无 python-pptx | 交付 spec + Marp + 讲稿 + diff，`partial`，不报错 |
| 无 LibreOffice/PDF | 不声称已渲染；exports 只列真实文件 |
| 预算耗尽（900 s / 64 请求） | 先落盘 `deck_spec.json` 与 `diff.json`，`partial` + `limits` |

## 文件说明

- `scripts/kernel.py`：init / index / verify / emit / check，仅标准库，无网络。
- `scripts/spec_io.py`：别名容错、规格规范化、Marp/讲稿渲染、可选 pptx 构建。
- `scripts/deck_build.py`：generate / edit / check / finalize / selfcheck；编辑应用与 diff。
- `scripts/quote_check.py`：证据引文逐字核验。
- `references/output-contract.md`：默认输出字段与 `edits.json` 规范。
- `references/quality-rubric.md`：5 个评分维度 → 本包检查项。
- `references/example.md`：合成生成/编辑示例（非正式答案）。

## 最小调用示例

```bash
python3 scripts/kernel.py init --case /input/case.json --out work
python3 scripts/kernel.py index --materials /input --out work
python3 scripts/deck_build.py generate --spec work/deck_spec.json --out work --corpus work/corpus.txt
python3 scripts/deck_build.py edit --base work/deck_spec.json --edits work/edits.json --out work_edit --corpus work/corpus.txt
python3 scripts/kernel.py emit --draft work_edit/draft.json --contract-dir work --out /app/output
python3 scripts/deck_build.py finalize --work work_edit --out /app/output
python3 scripts/deck_build.py selfcheck --work /app/output
```

示意输出（示例）：5 页底稿生成 → `generate: slides=5 errors=0 pptx=yes`；
5 条编辑 + 1 次插页 → `edit: changes=6 failures=0 slides=6 errors=0`。
