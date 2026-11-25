---
name: deck-content-organizer
description: 把论文/研究材料组织成受受众、时长与页数约束的学术汇报内容：先定报告目标与主线（problem→approach→results→conclusion），再按每页 30–60 秒做页预算，逐页产出判断句标题 + ≤6 条要点（每条 ≤14 字）+ 逐页口播讲稿与预设问答，最后核对总时长、页数与时间分配。交付幻灯片规格 JSON、Marp/Markdown 源、逐页讲稿与时间分配表；装有 python-pptx 时附带生成 pptx。适用于组会、答辩、评审等需要"讲得完、讲得清"的汇报组织；不适用于无需原文的通用 PPT 美化、科研绘图或论文润色。
version: 1.1.0
license: MIT
---

# 学术汇报内容组织：先定主线与页预算，再写页面

把"做一次学术汇报"拆成 **契约 → 材料索引 → 主线与受众 → 页/秒预算 → 逐页主张与讲稿 →
时长守恒校验 → 渲染/降级**。核心主张：

1. **一页只讲一件事**，标题是判断句，不是"实验结果二"；
2. **时长是硬约束**：每页 30–60 秒，总秒数必须落在目标时长的 ±10% 内；
3. **讲稿与页面分离**：口播讲过渡、强调与预设问答，不把要点念一遍；
4. 页面上的数字、图号必须能回到源材料，缺什么写什么，不补造。

## 何时使用

触发（满足任一）：

- 用户给出论文/报告/实验记录，要求"做成 N 分钟组会/答辩/评审 PPT"或"按这个页数组织汇报"；
- 要求先出大纲、页级要点与讲稿，再决定排版；
- 已有页面内容，需要检查"页数/时长/信息密度是否讲得完"；
- 题面 `case.json` 带有 `audience`、`duration_min`、`max_slides`、`output_contract`。

不触发：没有原文、要求凭空生成研究结论；只要模板套用或版式美化的（走模板适配包）；
只要论文写作/润色；只要科研绘图；要求把示意图包装成实验数据。

## 输入识别（字段名容错）

读取 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`。
**先打开真实文件**，按内容判断任务，不凭字段名猜语义。`kernel.py init` 做通用宽松识别；
页级字段由 `spec_io.normalize_spec` 再做一层别名容错：

| 语义 | 接受的别名 |
|-|-|
| 案例标识 | `case_id` / `caseId` / `id` / `task_id` / `case` |
| 受众 | `audience` / `readers` / `target_audience` / `listeners` / `听众` |
| 时长（分钟） | `duration_min` / `minutes` / `duration` / `talk_minutes` / `time_limit_min` / `时长` |
| 页数上限 | `max_slides` / `slide_limit` / `max_pages` / `page_limit` / `slide_count_limit` |
| 页列表 | `slides` / `pages` / `deck_outline` / `deck` / `slides_spec` |
| 主线 | `mainline` / `narrative` / `story` / `outline_mainline` / `主线` |
| 语言 | `language` / `lang` / `target_language` |

要点字段也容错：`bullets` / `points` / `body`；讲稿用 `notes.say` / `notes.script` / `notes.讲稿`；
图表用 `visual` 或 `figure`。**题面字段永远优先**，本 Skill 只补全没给的。

开工前必须确认（缺失不得默认）：

1. 受众（同行 / 跨学科 / 评委）与汇报性质（组会 / 答辩 / 评审 / 开题）；
2. 时长与页数上限；两者冲突时以"讲得完"为准并在 `uncertainty` 记录；
3. 语种与必须覆盖的章节；
4. `output_contract` 的字段名，逐个记录，`result.json` 全部回填。

## 执行流程

1. **契约**：`python3 scripts/kernel.py init --case /input/case.json --out work`
   → `work/contract.json`（case_id、任务、output_contract、受众与时长若有）。
2. **材料索引**：`python3 scripts/kernel.py index --materials /input --out work`
   → `work/evidence.json` + `work/corpus.txt`。PDF 无文本层、图不可提取时如实标记。
3. **主线与受众**：写 `work/deck_spec.json` 的 `mainline` 与 `audience` 四项：
   `problem`（不解决会怎样）、`approach`（一句话做法）、`results`（3–5 条，带图号/数字）、
   `conclusion`（改变了什么判断）、`limitations`（作者自述 + 你识别的边界）。
   **按贡献排序，不按论文段落顺序**；每条结论都要有 locator。
4. **页/秒预算**：先算能讲几页再写页面。
   `pages = round(duration_min × 60 / 45)`，并满足 `duration_min ≤ pages ≤ 2 × duration_min`
   与题面 `max_slides`；每页写 `seconds`（30–60）。总秒数偏差 > max(30 秒, 10%) 视为不合格。
   超预算的砍页顺序：背景铺垫 → 次要结果 → 方法细节；**永不砍**问题、核心方法、
   支撑主结论的证据、结论。
5. **逐页写规格**：每题四件套——
   - `title`：判断句，≤24 字；
   - `bullets`：**≤6 条、每条 ≤14 个非空白字符**（脚本按字符数硬查）；
   - `visual`：`type` + 论文原编号 `ref` + 图注（条件、n、误差线含义）；有可读真实图像时在 `path` 写其绝对路径，缺失时如实标注，不能冒充插图；示意图标注"示意"；
   - `notes`：`say`（30–60 秒口播，≥20 字）、`why`（过渡）、`qa`（1–2 条预设问答）。
   页面只放"讲的时候要指的东西"，推导进讲稿或备份页（`kind: backup`，不计主讲页）。
6. **生成产物**：
   `python3 scripts/deck_plan.py plan --spec work/deck_spec.json --out work --corpus work/corpus.txt --template <实际模板pptx路径>`
   必须传入 `--template <真实模板pptx路径>`；若是既有演示稿编辑任务，不得将模板新建冒充原稿编辑，需使用原稿按页修改并核查继承链。→ `work/deck_spec.json`（规范化）、`deck.md`（Marp 源）、`speaker_notes.md`（逐页讲稿）、
   `timing.csv` + `timing.md`（逐页与分段时长）、`deck_check.json` / `deck_check.md`（校验）、
   `draft.json`；装有 `python-pptx` 时另出 `deck.pptx`，若再有 LibreOffice 则转出
   `deck.pdf` 预览；两者都没有时降级，不报错。
7. **证据核验**（有原文时）：把 `evidence_map` 转成 `[{claim, quote, locator}]`，
   `python3 scripts/quote_check.py --evidence work/evidence_flat.json --corpus work/corpus.txt --out work/quote_check.json`
   逐字命中率必须 100%；不命中就回改引文或删除该页证据。
8. **时长守恒自检**：看 `deck_check.md` 的硬错误与警告；
   `errors > 0` 先改大纲（拆页、删次要内容、调整秒数），**不改校验器、不删证据**。
9. **产出**：`python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output`，
   再 `python3 scripts/deck_plan.py finalize --work work --out /app/output` 把本包附加字段
   （`outline`、`deck_outline`、`timing_table`、`evidence_map`、`render_log`、`self_check`）
   合并进 `result.json`；把 `deck.md`、`speaker_notes.md`、`timing.csv`、`deck_spec.json`
   复制到 `/app/output/`；生成了 pptx/pdf 时一并复制。`status=ok` 要求有可放映导出件，
   否则用 `partial` + `limits`。
10. **收尾**：`python3 scripts/kernel.py check --out /app/output` 与
    `python3 scripts/deck_plan.py selfcheck --work /app/output` 均须 PASS；抽查 2 页对照原文。

## 页面与时间规则（对齐评分维度）

| 维度 | 规则 | 反例 |
|-|-|-|
| 受众 | 背景比例、术语解释深度、结论强度随听众调整 | 给跨学科听众讲 5 页公式推导 |
| 主线 | 问题→做法→证据→意义，先结论后支撑 | 按 Abstract/Intro/Methods 逐段切页 |
| 一页一主张 | 标题写结论；一页只留一个可指的证据 | 一页四张图、12 条要点 |
| 密度 | ≤6 条、每条 ≤14 字、标题 ≤24 字 | 把论文段落贴进文本框 |
| 时长 | 30–60 秒/页；总量偏差 ≤10% | 8 分钟排 20 页 |
| 讲稿 | 讲过渡、强调、预设问答；口语、短句 | 备注 = 页面文字复制 |
| 证据 | 图号、数字、引文逐字可回查 | 原文只有 4 张图却引用 Fig. 5 |
| 时间表 | 分段汇总与总时长一致，可直接用于彩排 | 只给总时长，无法定位超时段落 |

## 硬性禁止

- 不虚构论文未报告的图、表、数值、样本量、显著性；没有就写"原文未报告"。
- 不改写数值与单位（含 `%`、`±`、CI、`n=`）；不把 `38%` 写成"约四成"。
- 不把示意图当实验数据页；不把他文结果当本文结果。
- 不超过题面页数上限；不靠压字号塞内容（投影正文 ≥18 pt）。
- 不在讲稿里复述页面要点；讲稿不得引入页面与原文都没有的新结论。
- 不伪造"已生成 pptx / 已渲染 PDF"；没有文件就写 `partial`。
- 不提交预制答案；所有页面必须由本次读取的输入推导。

## 输出契约

`/app/output/`：

- `result.json`：题面契约字段全回填 + `case_id`；本包附加 `outline`、`deck_outline`、
  `timing_table`、`speaker_notes_path`、`evidence_map`、`render_log`、`self_check`
  （见 `references/output-contract.md`）。
- `deck_spec.json`：规范化页级规格（可被模板适配/编辑包复用）。
- `deck.md`：Marp 兼容的 Markdown 源（含讲者备注）。
- `speaker_notes.md`：逐页口播、过渡、预设问答 + 时间分配表。
- `timing.csv` / `timing.md`：逐页与分段时长。
- `deck_check.md`：密度/时长/编号/数字核验结果。
- `deck.pptx`：仅在 python-pptx 可用且构建成功时存在。
- `deck.pdf`：仅在 pptx 构建成功且 LibreOffice 可用时存在（放映预览）。

`status`：`ok` = 校验通过且有导出件；`partial` = 缺构建/渲染依赖或部分页未完成；
`blocked` = 材料或 case.json 不可读；`refused` = 要求虚构数据。

## 自查

1. `deck_check.json` 的 `errors` 为 0；每条 warning 能解释或已改。
2. 逐页核对：标题是判断句；要点 ≤6 条且每条 ≤14 字；秒数 30–60。
3. 总秒数与 `duration_min` 偏差在 ±10% 内；分段汇总相加等于总时长。
4. 每个数字/图号能在 `corpus.txt` 命中；每条引文 `quote_check` 命中。
5. `speaker_notes.md` 的页数 = `deck_spec.json` 的页数；每页有 `say`。
6. `selfcheck` PASS；`result.json` 的 `case_id` 与输入一致。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 未声明受众 | 先按题面/材料推断并在 `uncertainty` 写明，不静默默认"同行" |
| 未声明时长 | 按逐页秒数反推总时长，warning；仍交付 |
| 时长与页数上限冲突 | 以讲得完为准：减页或调秒数，冲突写进 `uncertainty` |
| 论文无文本层/加密 | 只用已读部分；`partial` + `limits`，不猜图表内容 |
| 图为位图不可提取 | 用原文编号 + 图注 + 占位说明，不重绘假数据图 |
| 图表编号原文不存在 | 硬错误：改编号或删页，不允许"大概对" |
| 讲稿写不满 30 秒 | 补过渡与预设问答；仍不足则合并相邻页 |
| 无 python-pptx | 交付规格 JSON + Marp 源 + 讲稿，`partial`，不报错 |
| 无 LibreOffice/PDF 预览 | `render_log.exports` 只列实际存在的文件，不声称已渲染 |
| 预算耗尽（900 s / 64 请求） | 先落盘 `deck_spec.json` 与讲稿，`partial` + `limits` |

## 文件说明

- `scripts/kernel.py`：init / index / verify / emit / check，仅标准库，无网络。
- `scripts/spec_io.py`：别名容错、规格规范化、Marp/讲稿/时间表渲染、可选 pptx 构建。
- `scripts/deck_plan.py`：plan / check / finalize / selfcheck；页预算、密度、秒数、时长守恒校验。
- `scripts/quote_check.py`：证据引文逐字核验。
- `references/output-contract.md`：默认输出字段；题面契约优先。
- `references/quality-rubric.md`：5 个评分维度 → 本包检查项。
- `references/example.md`：合成输入/输出（示例，非正式案例答案）。

## 最小调用示例

```bash
python3 scripts/kernel.py init --case /input/case.json --out work
python3 scripts/kernel.py index --materials /input --out work
# 依据材料写 work/deck_spec.json（示意见 references/example.md）
python3 scripts/deck_plan.py plan --spec work/deck_spec.json --out work --corpus work/corpus.txt --template <实际模板pptx路径>
python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output
python3 scripts/deck_plan.py finalize --work work --out /app/output
cp work/deck_spec.json work/deck.md work/speaker_notes.md work/timing.csv /app/output/
cp work/deck.pptx work/deck.pdf /app/output/ 2>/dev/null || true
python3 scripts/deck_plan.py selfcheck --work /app/output
```

示意输出（示例）：6 页 / 8 分钟 → `plan: slides=6 total=07:50 errors=0 warnings=1`；
`speaker_notes.md` 6 段；`timing.csv` 合计 470 秒。

## 提交前逐页核验（执行，不只写报告）
打开指定模板和原文，逐页核对观点、数字、图号、证据来源；带论文图页必须有真实图像并等比插入。支持 figure/photo/schematic 的 `visual.path` 绝对路径；table 或图片不可读时工具标 partial，须自行补成可编辑表格或插入对应图片，再独立检查。模板含示例页时生成时会删除示例页并保留版式母版；该方法用于新建，不是修改原稿。导出 PDF 后逐页查看图像、文字溢出、字体与页面数；每页说明文字、出处和图注，准备现场问答，不能以 JSON 检查代替视觉核验。
