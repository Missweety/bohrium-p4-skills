---
name: paper-to-academic-deck
description: 把论文原文转成 10–14 页、30–60 秒/页的学术汇报：先从 PDF/docx/md/纯文本抽取标题、作者、摘要、图表与结论（抽不到就标 missing），再按"问题—方法—结果—结论"排页，逐页给判断句标题、≤6 条要点、配图建议与来源页码、口播稿与证据映射，最后产出可机检的 deck_spec.json、Marp/Markdown 源、讲稿与 selfcheck.json，有 python-pptx 时再导出 .pptx。适用于组会、答辩、会议汇报与"按模板/页数/时长做 PPT"；不适用于无原文的通用 PPT 美化、科研绘图或论文润色。
version: 2.2.0
license: MIT
---

# 论文转学术 PPT：一页一主张，句句有出处

流水线：**契约 → 原文索引 → 字段抽取 → 叙事主线 → 页/秒预算 → 页级规格 → 机器校验 →
渲染导出 → 自检记录**。

两条底线：
1. **不编造**。论文没写的图、表、数值、样本量一律不出现；抽取失败就在 `paper.json` 标
   `missing`，并在 `uncertainty` 说明，不用"合理猜测"填空。
2. **可机检**。页数、字数、秒数、图表编号、来源页码、配色对比度都落进 `deck_spec.json`，
   由 `deck_plan.py` 跑出 PASS/FAIL；校验不过先改规格，不许改阈值或删证据。

## 何时使用

触发：用户给出论文 / 预印本 / 研究报告（pdf、docx、md、txt）并要求"做成汇报 PPT /
组会 slides / 答辩课件 / 按这个模板排 N 页 / 配讲稿 / 控制在 N 分钟"；或题面带模板文件、
页数上限、汇报时长、`output_contract`。

不触发：没有原文却要求生成研究汇报；只改已有 PPT 的配色/动画；只做科研绘图；只做论文润色或
翻译；要求把示意图包装成实验数据。

## 输入识别（字段别名容错）

先读 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录题面。
论文、模板、起始稿按 `materials` / `files` / `inputs` 定位，**先打开真实文件**：页数、
模板版式、可读性以文件为准，不以题面文字为准。

`spec_io.py` 对常见别名做归一，任一写法都能识别：

| 目标字段 | 接受的别名 |
|-|-|
| `duration_min` | `minutes`、`duration`、`talk_minutes`、`time_limit_min`、`时长` |
| `max_slides` | `slide_limit`、`max_pages`、`page_limit`、`slide_count_limit` |
| `slides` | `pages`、`deck_outline`、`deck` |
| `mainline` | `narrative`、`story`、`主线` |
| `bullets` | `points`、`body` |
| `visual` | `figure`（字符串时按图片处理） |
| `source_pages` | `source_page`、`pages`、`page` |
| `notes.say` | `script`、`讲稿` |
| `theme` | `colors`、`palette`、`配色` |

`paper_parse.py` 同样容忍：中英文章节名（Abstract/摘要、Conclusion/结论、Limitations/局限）、
`Fig. 2a` / `Figure 2` / `图 2`、`Table 1` / `表 1`、Markdown `#`/`##`、`1 Introduction`
与 `1 引言` 两种编号。

开工前确认（缺失写 `uncertainty`，不默认）：页数上限与时长、受众、语言、是否有模板/起始 deck、
必须包含的章节、`output_contract` 的每个字段名。

**运行目录与解释器**：以下命令默认在 skill 根目录（含 `SKILL.md` 的目录）执行。
若不确定当前目录，先 `cd` 到 skill 根目录；也可用绝对路径
`python3 /skills/weekly-skill/scripts/...`。环境没有 `python` 时统一用 `python3`。

**契约形态**：`case.json.output_contract` 可能是对象、字符串数组，或
`[{name,type,...}]` 字段规格数组。`kernel.py init` 会原样落盘，`emit` 用
`contract_field_names()` 统一取字段名；三种形态都必须能写出 `result.json`，
不得因字段规格对象而崩溃或只写 `fields: null`。

## 执行流程

1. **契约**
   `python3 scripts/kernel.py init --case /input/case.json --out work`
   → `work/contract.json`（case_id、任务、output_contract、页数/时长）；同时复制
   `materials` 到 `work/materials/` 后 `kernel.py index --materials work/materials --out work`
   → `work/evidence.json`、`work/corpus.txt`。PDF 无文本层、图片不可提取时如实标记。
2. **字段抽取**
   `python3 scripts/paper_parse.py --paper work/materials/paper.pdf --out work`
   → `work/paper.json`：`title`、`authors`、`abstract`、`sections`、`figures`、`tables`、
   `conclusion`、`limitations`，每项带 `status`（ok/missing）、`locator`（`p.3` 或 `L41`）。
   PDF 给出页号；docx/md/txt 没有页概念，只给行号 `L<n>` 并在 `notes` 注明，**不假造页码**。
   多材料时用 `--materials work/materials` 自动挑主论文（pdf > docx > md > txt）。
   打印 `missing: ...` 的字段必须原样进入 `uncertainty`。
3. **叙事主线**
   写 `work/deck_spec.json.mainline`，六槽：`problem`、`gap`、`approach`、
   `results`（3–5 条，每条带 `locator`）、`conclusion`、`limitations`。
   顺序按论证，不按论文章节。每条都能指到原文的图/表/页；作者结论与支撑细节分开。
4. **页/秒预算**
   - 页数：主讲页 10–14（题面 `max_slides` 更小时取更小值）；
   - 时长：`Σseconds = duration_min × 60`，允许 ±max(30 秒, 10%)；
   - 每页 30–60 秒，口播稿约 `seconds × 2–3` 字；
   - 配额建议：标题 1、问题 1–2、gap 1、方法 2–3、结果 3–5、局限 1、结论 1。
   超页先砍背景与次要结果，不砍"问题—方法—关键证据—结论"。
5. **页级规格**
   每页写 `work/deck_spec.json.slides[]`：`kind`、`title`（判断句 ≤24 字）、`takeaway`、
   `bullets`（≤6 条、每条 ≤14 字）、`visual{type,ref,caption[,path,table]}`、
   `evidence[{ref,quote,locator}]`、`source_pages`、`seconds`、`notes{say,why,qa}`。
   `visual.ref` 只用论文原编号；`schematic` 的 `caption` 必须写"示意"。
   `visual.path` 指向 `materials/` 内的图片文件（相对路径按 materials 目录解析），
   `visual.table` 给 `{header:[...], rows:[[...],...]}`；能找到素材才插入真实图片/原生表格，
   找不到时保留全宽正文并写入 `uncertainty`，不重绘、不臆造。
   `quote` 必须是原文逐字（空格与连字会被归一后比对）。
6. **机器校验**
   `python3 scripts/deck_plan.py plan --spec work/deck_spec.json --case /input/case.json \
      --paper work/paper.json --corpus work/corpus.txt --out work`
   一次产出 `deck_spec.json`、`deck.md`（Marp）、`speaker_notes.md`、`timing.md`、
   `timing.csv`、`deck_check.md/json`、`selfcheck.json`、`draft.json`；有 python-pptx 时
   追加 `deck.pptx`（有 LibreOffice 再追加 `deck.pdf`）。
   退出码 1 = 有硬错误：**先改规格再重跑**，不许改阈值。
7. **产出与收尾**
   `python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output`
   → `result.json`；`python3 scripts/deck_plan.py finalize --work work --out /app/output`
   合并技能附加字段。
   然后把 `deck_spec.json`、`deck.md`、`speaker_notes.md`、`timing.csv`、`timing.md`、
   `paper.json`、`selfcheck.json`、`deck.pptx`/`deck.pdf` 复制到 `/app/output/`。
   `python3 scripts/kernel.py check --out /app/output` 与
   `python3 scripts/deck_plan.py selfcheck --work /app/output --paper /app/output/paper.json \
      --corpus work/corpus.txt` 都必须 PASS。
   抽查 3 页：图表编号、数值、单位、图注逐字对回原文。

## 输出契约

完整字段见 `references/deck-contract.md`（`deck_spec.json` 的页级结构与 `result.json` 的
附加字段）。最低交付：

| 文件 | 内容 |
|-|-|
| `deck_spec.json` | 可机检的页级规格：主线 + 每页标题/要点/图表/证据/页码/秒数/讲稿 |
| `deck.md` | Marp 源，一页一个 `#` 标题，备注在 HTML 注释中 |
| `speaker_notes.md` | 逐页 30–60 秒口播、过渡、预设问答，末尾时间分配表 |
| `timing.csv` / `timing.md` | 逐页秒数、累计时间、分段占比 |
| `selfcheck.json` | `verdict: PASS/FAIL` + 每项检查的阈值与证据 |
| `paper.json` | 抽取字段与 `missing` 清单（页面内容的唯一事实源） |
| `deck.pptx` / `deck.pdf` | 可选；缺依赖时降级，`status: partial` |

`status`：`ok` = 页/秒合规、selfcheck PASS、有可编辑源文件与渲染记录；`partial` = 缺构建/渲染
依赖或部分页缺失；`blocked` = 论文不可读；`refused` = 要求虚构图或数据。

不要输出契约外的新顶层字段；技能的附加字段统一放在 `result.json` 的固定键下。

## 自查（PASS/FAIL 口径）

`deck_plan.py` 会逐项写入 `selfcheck.json`，级别为 error（判 FAIL）或 warning（记录不拦）。

| 检查 | 阈值 | 级别 |
|-|-|-|
| 主讲页数 | 10–14（或题面更小上限） | error |
| 标题 | 非空、判断句、≤24 字 | error / warning |
| 要点密度 | ≤6 条、每条 ≤14 字、单页 ≤180 字 | error |
| 逐页秒数 | 30–60 秒 | error |
| 总时长 | 与 `duration_min×60` 偏差 ≤max(30s, 10%) | error |
| 口播稿 | ≥60 字；明显短于页时长给警告 | error / warning |
| 图表编号 | 形如 `Fig. 2a`/`Table 1`，且能在原文命中 | error |
| 图表来源 | 每页 `source_pages` 非空；页码不超论文总页 | error / warning |
| 图注 | 非空；示意图写"示意" | error / warning |
| 证据 | 每页 ≥1 条，`quote` 逐字命中原文 | error |
| 数字 | 页面出现的数字能在原文找到（可用 `--lenient-numbers` 降级） | error |
| 标题层级 | 每页恰好 1 个 H1，页内无 H2/H3 | error |
| 对比度 | 正文/背景 ≥4.5，强调/背景 ≥3.0 | error / warning |
| 首尾页 | 第 1 页 title、末页 conclusion | warning |

修复顺序：先清 error（删页、拆页、改标题、补证据），再看 warning（口播复述、标题重复、
示意未标注）。**不要为过检缩字号或删掉唯一的证据页。**

## 降级与异常

| 情况 | 处理 |
|-|-|
| 论文无文本层/加密 | `paper_parse.py` 返回 `status: blocked` 或 `missing` 列表；只做已读部分，`partial` + `limits` |
| 缺作者/摘要/结论 | 显式 `missing`，封面/结论页不补造；写入 `uncertainty` |
| 图为位图无法提取 | 引用原编号与图注；能定位到 materials 图像文件则插入真实图片，否则保留全宽正文并写入 `uncertainty`；不重绘假数据图 |
| 公式为图片 | 以图引用，不手打公式；无法核对处进 `uncertainty` |
| 无 python-pptx | 只交付 `deck_spec.json` + `deck.md` + `speaker_notes.md`，`status: partial`，`limits` 写明 |
| 无 LibreOffice | 跳过 `deck.pdf`，在 `render_log.preview = null`，不声称已渲染 |
| 模板占位符不足 | 用最接近版式并记录偏差；不覆盖母版/页脚/配色 |
| 页数或时长冲突 | 先砍背景与次要结果；仍冲突则缩页并写明取舍 |
| 预算耗尽 | 先落盘规格与已完成页，`partial` + `limits` |

## 文件说明

- `scripts/kernel.py`：init / index / verify / emit / check，仅标准库，无网络。
- `scripts/paper_parse.py`：PDF/docx/md/txt 字段抽取，输出 `paper.json` 与 `missing`。
- `scripts/spec_io.py`：规格别名归一、Marp/讲稿/时间表渲染、可选 pptx/pdf 导出。
- `scripts/deck_plan.py`：plan / check / finalize / selfcheck，含页/秒预算与全部机检项。
- `scripts/quote_check.py`：独立引文逐字核验（复核 `evidence_map` 用）。
- `references/deck-contract.md`：`deck_spec.json` 与 `result.json` 字段契约。
- `references/quality-rubric.md`：5 个评分维度 → 检查项 → 证据文件。
- `references/slide-narrative.md`：主线抽取、页型模板、讲稿写法、反例。
- `references/output-contract.md`：兼容入口，字段以 `deck-contract.md` 为准。
- `references/example.md`：合成示例（含 2 图 1 表的输入片段与一页完整规格）。
- `SMOKE.md`：真实命令、输出与关键数字。

## 最小调用示例

```bash
python3 scripts/kernel.py init --case /input/case.json --out work
python3 scripts/kernel.py index --materials work/materials --out work
python3 scripts/paper_parse.py --paper work/materials/paper.pdf --out work
# 写 work/deck_spec.json（示意见 references/example.md）
python3 scripts/deck_plan.py plan --spec work/deck_spec.json --case /input/case.json \
    --paper work/paper.json --corpus work/corpus.txt --out work
python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output
python3 scripts/deck_plan.py finalize --work work --out /app/output
cp work/deck_spec.json work/deck.md work/speaker_notes.md work/timing.csv \
   work/paper.json work/selfcheck.json work/deck.pptx /app/output/ 2>/dev/null
python3 scripts/kernel.py check --out /app/output
python3 scripts/deck_plan.py selfcheck --work /app/output --paper /app/output/paper.json \
    --corpus work/corpus.txt
```


## 逐页构建和渲染的质量门禁
模板已有示例页不属于目标稿：构建时仅继承母版与版式，删除示例页，再依页级规格创建；输入模板不可覆盖。推断图号匹配多个素材时不择一，标记缺失并要求提供明确路径。每页应包含一个可辨识的主张，图表和数值与原文对应，演讲备注补充解释和衔接。导出后检查实际 PPTX 页数、每页可编辑文字、图片比例和边界，渲染 PDF/PNG 后逐页检查裁切、溢出、字体替换；失败或无法渲染标为 partial，不能使用旧 PDF 冒充本次导出。视觉布局应服务页面论证，不以装饰替代证据。

指定了模板路径时必须传入实际 `--template <模板路径>`；模板不存在或不可读应返回 partial，不得声称默认模板是指定模板。已有起始稿若无法原位编辑必须如实标记 partial。

## 改动记录（v2.2.0，2026-11-25）

本版只改可复现的真实缺陷，合成夹具实测（非官方案例）：

1. **题面页数上限被规格覆盖**：`normalize_spec` 原来只在规格缺 `max_slides` 时才读题面，规格写 14、题面写 6 时仍按 14 放行，10 页稿被判合规。现题面为上限权威（取更小值），题面 `min_slides` 取更大值；`audit` 的窗口下界再按上限收敛，不再出现"窗口 10–6"。
2. **论文不可读时误报"标题已解析"**：`paper_parse.py` 在无文本层时写出 `{"status":"blocked","missing":[...]}`，不含 `title/abstract/conclusion` 键，旧审计 `paper.get("title", {}).get("status")` 取到 `None` 判为"已解析"。现按缺键即 `missing`，并新增 `paper.status=blocked` 硬错误。
3. **非法 JSON 直接抛栈**：`kernel.py init` 与 `deck_plan.py` 读坏 `case.json`/`deck_spec.json` 时抛 `JSONDecodeError`。现分别落 `contract.json {status: blocked}` 并返回 1、打印 blocked，不再 traceback。
4. **`visual.path` 带 `materials/` 前缀时找不到图**：规格写 `materials/fig2a.png`（与 case 的字段写法一致）时旧逻辑拼成 `materials/materials/...`，静默降级为"未找到图像文件"。现在先按给的相对路径找，再退回按文件名在 materials 目录找。
5. 文档命令统一 `python3`（含脚本 docstring 与 `references/example.md`）。

实测（`/tmp/c7`，合成论文 10 页）：`plan errors=0 warnings=9 selfcheck=PASS pptx=yes`；pptx 10 页、第 6 页 PICTURE、第 7 页原生 TABLE，PDF 10 页；模板稿 2 页示例被清除、画布继承 13.333×7.5 in、模板文件哈希不变；`--no-pptx` 与无 `soffice` 均降级为 `partial` 并写明原因。

