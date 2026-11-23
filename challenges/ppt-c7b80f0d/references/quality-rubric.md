# 质量量表（quality-rubric）

五个评分维度 → 可机检项 → 证据文件。每一项都对应 `selfcheck.json` 里的 `checks[].id`；
交付前按"硬门槛 → 区分度"顺序过一遍。error 项任一不过 = FAIL，warning 项记录但不拦。

## 维度 1｜论文解析与事实准确

| 检查项 | 阈值 | 机检 id | 证据 |
|-|-|-|-|
| 标题可回原文 | `paper.title.status != missing` | `paper.title` | `paper.json.title.locator` |
| 摘要/结论未编造 | 缺失时标 missing 并进 `uncertainty` | `paper.abstract`、`paper.conclusion` | `paper.json.missing` |
| 主线六槽齐全 | `problem`/`approach`/`conclusion` 非空 | `mainline.problem` 等 | `deck_spec.json.mainline` |
| 关键结果数量 | 3–5 条且各带 locator | `mainline.results` | `mainline.results[].locator` |
| 每页证据逐字 | ≥1 条，`quote` 归一后命中原文 | `slideN.evidence` | `corpus.txt` |
| 数字可回溯 | 页面数字全部命中原文（`--lenient-numbers` 可降为警告） | `slideN.number_*` | `deck_check.md` |

不合格信号：摘要页出现原文没有的百分比；结果页写"显著提升"却无数字；作者栏靠猜。
修法：删掉无出处句，回 `paper.json` 找原文；找不到就写"原文未报告"。

## 维度 2｜叙事结构与页面聚焦

| 检查项 | 阈值 | 机检 id | 证据 |
|-|-|-|-|
| 主讲页窗口 | 10–14 页（题面更小时取更小） | `slides.window` | `selfcheck.summary.content_pages` |
| 页型合法 | 属于 8 种 kind | `slideN.kind` | `deck_spec.json` |
| 标题是判断句 | 非空、≤24 字、不重复 | `slideN.title`、`titles.unique` | `deck.md` |
| 一页一主张 | ≤6 条要点，每条 ≤14 字，单页 ≤180 字 | `slideN.bullets`、`slideN.bullet_len`、`slideN.page_chars` | `deck_check.md` |
| 首尾结构 | 第 1 页 title、末页 conclusion | `order.first`、`order.last` | `deck_spec.json.slides` |
| 标题层级 | 每页 1 个 H1，页内无 H2/H3 | `headings.deck` | `deck.md` |

不合格信号：按 Abstract/Intro/Methods 切块；一页 12 条要点；标题"结果二"。
修法：先重写 `mainline`，再按 10–14 页配额重新分页；信息进讲稿，不留在页面。

## 维度 3｜图表与视觉规范

| 检查项 | 阈值 | 机检 id | 证据 |
|-|-|-|-|
| 图号存在 | 形如 `Fig. 2a`/`Table 1`，且在 `paper.json` 清单或原文命中 | `slideN.ref_number`、`slideN.ref_trace`、`figures.listed` | `paper.json.figures` |
| 图注完整 | 非空；含条件、n、误差线含义 | `slideN.caption` | `deck.md` |
| 示意标注 | `schematic` 图注含"示意" | `slideN.schematic` | `deck_spec.json.visual` |
| 来源页码 | 每页 `source_pages` 非空且不超论文页数 | `slideN.source`、`source.pages` | `paper.json.page_count` |
| 配色对比度 | 正文/背景 ≥4.5，强调/背景 ≥3.0 | `contrast.body`、`contrast.accent` | `theme` |

不合格信号：原文只有 4 张图却引用 Fig. 5；图注只有"结果如图"；示意图与实测柱状图同页。
修法：改回原编号、补图注三件套、把示意图单独成页并标"示意"。

## 维度 4｜讲稿与时间节奏

| 检查项 | 阈值 | 机检 id | 证据 |
|-|-|-|-|
| 逐页秒数 | 30–60 秒 | `slideN.seconds` | `timing.csv` |
| 总时长 | 与目标偏差 ≤max(30s, 10%) | `timing.total` | `timing.md` 合计行 |
| 口播成稿 | ≥60 字；明显短于页时长给警告 | `slideN.notes`、`slideN.notes_short` | `speaker_notes.md` |
| 不复述页面 | 不包含要点 80% 连续原文 | `slideN.notes_restate` | `speaker_notes.md` |
| 时间表自洽 | 逐页合计 = 总时长；分段占比可读 | `artifact.timing_sum` | `timing.md` |

不合格信号：12 分钟讲 20 页；备注只有"讲一下这页"；每页讲稿都是要点复制。
修法：按 `seconds × 2–3` 字补口播；页数超了就砍背景页，不提高语速。

## 维度 5｜可交付与可复现

| 检查项 | 阈值 | 机检 id | 证据 |
|-|-|-|-|
| 规格落盘 | `deck_spec.json` 可被 `deck_plan.py` 直接读取 | `--spec` 载入 | `deck_spec.json` |
| Marp 源页数 | `# ` 标题数 = 页数 | `artifact.deck_pages`、`headings.deck` | `deck.md` |
| 讲稿页数 | `## 第 ` 小节数 = 页数 | `artifact.notes_pages` | `speaker_notes.md` |
| 文件齐全 | `deck.md`/`speaker_notes.md`/`timing.csv` 非空 | `artifact.deck_md` 等 | `selfcheck.json` |
| 导出记录 | pptx/pdf 路径与工具写进 `render_log` | `artifact.exports` | `result.json` |
| 降级诚实 | 缺依赖时 `status: partial` + `limits` | `render_log`、`limits` | `result.json` |
| 自检结论 | `verdict` 为 PASS 且 `errors` 为空 | 顶层字段 | `selfcheck.json` |

不合格信号：声称已渲染但目录无 pptx；Marp 源少一页；selfcheck 是 work/ 的旧文件。
修法：重跑 `deck_plan.py plan` 与 `selfcheck`，复制同一批文件到输出目录，核对页数。

## 交付前 60 秒清单

1. `deck_plan.py plan` 退出码 0，`selfcheck.json` 为 PASS。
2. `kernel.py check` PASS 且 `result.json` 含 `case_id`/`status`。
3. 随机抽 3 页：图号、数字、单位、图注逐字对回论文。
4. `paper.json.missing` 的每一项都能在 `uncertainty` 找到对应句。
5. 输出目录无 `/Users/` 路径、无令牌、无二进制粘贴、无 `..` 越界引用。
