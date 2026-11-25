# 双语学术语域与期刊体例

本文件约束"译得像论文"，而不是"译得通顺"。术语与段号规则见 `glossary-and-alignment.md`，
情态/否定规则见 SKILL.md 第 4.3 节。

## 1. 中英双向的默认体例

材料未给具体期刊模板时，按下面两套默认体例执行；材料给了 `journal_style` 或投稿须知时，
以材料为准，并在 `translation.md` 开头用一行声明实际采用的体例。

| 项目 | 中文期刊（默认） | 英文期刊（默认） |
|-|-|-|
| 摘要 | 目的—方法—结果—结论，200–300 字，不出现图表与文献引用 | Background–Methods–Results–Conclusions，150–250 words |
| 标题层级 | 1 引言 / 2 材料与方法 / 3 结果 / 4 讨论 / 5 结论 | 1 Introduction / 2 Materials and Methods / 3 Results / 4 Discussion / 5 Conclusions |
| 人称 | 正文避免"我们"，用"本研究""本文"；致谢除外 | 可用 `we`，但避免 `we feel`、`we believe` 这类主观表达 |
| 时态 | 用"已/将/了"区分完成与计划 | 方法与结果过去时；结论与普遍事实现在时；全篇统一 |
| 标点 | 全角 `，。；：（）`；数字与单位间半角空格 | 半角 `, . ; : ()`；`Fig. 3`、`et al.` 用句点 |
| 数字 | 正文数字用阿拉伯数字；`1.2 万` 可用，首次出现括注 `12 000` | `12,000`；`1.2 × 10^4` 合法；不写 `12 thousands` |
| 缩写 | 首次"中文全称（English full name, ABBR）" | 首次 `full name (ABBR)` |

反例：
- 中文摘要写"我们做了一个特别棒的实验，结果挺明显" → 口语化，且无量化。
- 英文摘要写 `This world-leading study fills the gap in the field.` → 宣传语，无比较对象、无引用。
- 中文正文写"Figure 3 显示…" → 中文体例应写"图 3 显示…"（图表标签必须本地化，编号不变）。
- 英文正文写"如图 3 所示" → 英文体例应写 `as shown in Fig. 3`。

## 2. 句式：去直译腔，但不丢限定

### 2.1 英译中

| 问题 | 改法 | 反例 |
|-|-|-|
| 长定语从句堆叠 | 拆成两到三个短句，主干先行 | `A method that uses X to measure Y under Z conditions was developed.` → "开发了一种方法，该方法在 Z 条件下用 X 测量 Y。"（不是"一种在 Z 条件下使用 X 来测量 Y 的方法被开发了"） |
| 被动语态直搬 | 中文可用"对……进行了……""结果表明……" | `Samples were analyzed by GC-MS.` → "采用 GC-MS 对样品进行了分析。" |
| `respectively` 硬译 | 用"分别为"并把两列表述对齐 | `A and B were 3 and 5 mg/L, respectively.` → "A 与 B 分别为 3 和 5 mg/L。" |
| `It is worth noting that` | 可省，但不能省掉其后的限制条件 | 删除该短语时保留 `however/only/under ... conditions` |

### 2.2 中译英

| 问题 | 改法 | 反例 |
|-|-|-|
| 流水句 | 按逻辑切分为主句＋从句，一句一个主要断言 | 一句话里塞进四个"并/且/同时" |
| "进行了研究" | 用具体动词：`investigated / measured / compared` | `We conducted a study on...`（空泛） |
| "取得了良好效果" | 换成可核验表述：`improved X by 12.4% (P < 0.05)` | `achieved good results` |
| "众所周知" | 删除或改为带引用的具体陈述 | `As is well known, ...` 后无引用 |

## 3. 语域红线

以下词在学术正文中出现即视为语域失真，必须替换或删除（脚本 `modality_register.py` 会报
`promotional` / `colloquial`）：

| 类型 | 禁止 | 替换 |
|-|-|-|
| 宣传语 | 国际领先、填补空白、世界首创、重大突破、颠覆性、完美解决 | 与具体工作对比后的差异描述＋引用 |
| 英文宣传语 | world-leading, fill the gap, first ever, groundbreaking, revolutionary | `to our knowledge, the first ... (see [12])` 且必须真有检索依据 |
| 口语 | 很多、挺、特别棒、大家、搞定、东西 | 大量（给出数量）、较为、显著、研究者、样品/材料 |
| 英文口语 | a lot of, huge, big time, tons of | `a large number of`（给 n）、`substantial`（给幅度） |

注意：`首次` / `first` 不是绝对禁用，但必须满足两个条件——有检索范围说明（"在给定材料/截至 2025 年
的文献中"）和可核对的比较对象。做不到就改成"本文首次在 X 条件下观察到 Y"这类有边界的表述。

## 4. 引用与归属

- 引用标记随语向保持不变：中文稿可用 `[12]` 或 `(Smith 等, 2020)`；英文稿用 `[12]` 或
  `(Smith et al., 2020)`。姓氏不译、编号不重排、`et al.` 在中文里写"等"。
- `as reported by Smith et al. [12]` 译成"如 Smith 等 [12] 所报道"，不能写成"研究表明"而丢掉归属。
- 作者自己的判断与文献结论必须分开：`We speculate that ...` → "我们推测……"（不是"研究表明……"）。
- 转引要标明：材料只给二手引用时写"（转引自 [12]）"，不假装读过原文。

## 5. 图表、公式与脚注

- 图注结构保留：`Figure 3. (a) ... (b) ...` → `图 3. (a)…… (b)……`；分图编号、比例尺、
  误差线说明（`mean ± SD, n = 3`）原样保留。
- 表注与表头逐列翻译，列序不变；单位行（`Units: mg/L`）单独保留。
- 公式不译变量；公式编号 `(1)`、`Eq. (1)` 与正文引用同步。
- 脚注独立成段（`N001` 起），与正文上标编号一一对应；脚注里的文献同样保留原格式。

## 6. 交付前语域自检

1. 通读译文，凡出现"国际领先/填补空白/world-leading/fill the gap"必须删除或改为有比较对象的表述。
2. 抽查 5 处长句：是否一句多个断言、是否丢了 `only/under ... conditions/except` 等限定。
3. 中英标点是否混用；图表标签是否本地化且编号未变。
4. 摘要是否出现文献引用或图表引用（默认体例下不应出现）。
5. 时态/体是否全篇统一；"已完成"与"拟开展"是否分清。
