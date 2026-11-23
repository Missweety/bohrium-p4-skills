# 七族一致性规则与自动修订边界

每条规则都必须产出可复核锚点（`paragraph_id + sentence_index + char_start/end + anchor_quote`）。
判定信号写的是"脚本实际能看见的东西"，不是主观印象。

## 0. 文本与定位模型

- 可见文本 = `w:t` 文本 + `w:tab`→`\t` + `w:br`→`\n`；`w:del` / `w:moveFrom` 内的文本不计入；
- 段落号 `P0001` 按文档顺序（含表格单元格段落，单元格段落另带 `table_index/row_index`）；
- 修订只在"可见文本偏移"上替换，写入对应 `w:t` 并保留 `rPr`；不重建段落，不丢表格/页眉页脚/`sectPr`。

## 1. terminology（术语与缩写）

| 规则 | 判定信号 | 自动修？ |
|-|-|-|
| `terminology.abbr_conflict` | 同一缩写被展开成 ≥2 种全称（按空白/连字符归一后比较） | 否（需作者定唯一全称） |
| `terminology.abbr_used_before_definition` | 首次出现缩写的段落序号 < 定义段序号 | 否 |
| `terminology.abbr_undefined` | 缩写全文 ≥2 次且从未出现"全称（缩写）"定义 | 否 |
| `terminology.latin_variant` | 同一拉丁词出现 ≥2 种大小写/连字符写法；只统计**非句首**出现 | 仅当规范写法含大写时（升格到带大写形式） |
| `terminology.latin_plural_variant` | 仅单复数差异 | 否 |
| `terminology.cn_variant` | 已定义中文全称在别处被截短使用（长度差 ≤3） | 否 |
| `terminology.workorder_term` | 工单 `canonical_terms` 显式给出的 `旧→新` | 是（任务要求） |

去噪原则：跳过标题段落；跳过 `https://`、`@`、路径附近的 token；`tok.isupper()` 的纯大写照写不判变体。
**不允许**把小写写法当"规范"去改专名（如不得把 `Deep` 改成 `deep`）。

## 2. symbol（符号）

| 规则 | 判定信号 | 自动修？ |
|-|-|-|
| `symbol.conflict` | 同一符号有 ≥2 种含义（符号表单元格 + 正文"X 表示 Y"合并比较） | 否 |
| `symbol.used_before_definition` | 希腊字母在定义段之前已被使用 | 否 |

符号表识别：表头含"符号/变量/记号/symbol"，含义列含"含义/意义/说明/定义/mean"。
表格定义的锚点回填到单元格段落号，保证 `anchor_quote` 可逐字复核。

## 3. definition（重复定义）

| 规则 | 判定信号 | 自动修？ |
|-|-|-|
| `definition.duplicate` | 同一术语在 ≥2 个不同章节出现"X 是指/定义为/指的是/记作/称为……" | 否（保留首次，其余改回指） |

术语提取会剥掉"本文/文中/本节/此处/该处/本章/所称/所谓/的"等前缀。

## 4. numbering（编号）

| 规则 | 判定信号 | 自动修？ |
|-|-|-|
| `numbering.chapter_duplicate` | 顶级章号重复 | 否 |
| `numbering.chapter_gap` | 顶级章号不连续 | 否 |
| `numbering.heading_level_jump` | 相邻编号标题层级跳 >1 级 | 否 |
| `numbering.caption_duplicate` | 同"图/表 + 编号"题注重复 | 否 |
| `numbering.caption_chapter_mismatch` | 题注前缀 ≠ 所在章（如第 2 章出现"表3-1"） | 否 |
| `numbering.caption_gap` | 同章图表编号断号（如 2-1、2-3 缺 2-2） | 否 |
| `numbering.equation_duplicate` | 公式编号重复 | 否 |
| `numbering.equation_gap` | 同章公式编号断号 | 否 |

标题识别顺序：`第X章` → `n.n.n` → `n.n` → `n.`（单数字加负向断言，避免把 `1.1` 当一级）。

## 5. reference（图表/公式引用）

| 规则 | 判定信号 | 自动修？ |
|-|-|-|
| `reference.dangling` | 正文引用"图/表/式 + 编号"，但无对应题注/公式号 | 否（改引哪一处需作者判断） |
| `reference.uncited_caption` | 题注存在但正文从未引用 | 否 |

题注行自身的编号不计为"正文引用"（`m.start() < 12` 且整段是题注时跳过）。

## 6. citation（参考文献）

| 规则 | 判定信号 | 自动修？ |
|-|-|-|
| `citation.undefined_ref` | 正文 `[n]` 的 n 不在参考文献表编号集合内 | 否 |
| `citation.orphan_entry` | 参考文献表条目从未在正文被引用 | 否 |

参考文献区识别：标题含"参考文献/引用文献/references"；条目按 `[n] / n. / n)` 起始匹配；
正文引用支持 `[1,3]`、`[1-5]` 展开（跨度 ≤30）。

## 7. conclusion（跨章节结论）

| 规则 | 判定信号 | 自动修？ |
|-|-|-|
| `conclusion.cross_section_conflict` | 同一实体（缩写/关注术语）在**不同章节**分别出现肯定与否定结论 | 否 |
| `conclusion.similar_opposite` | 两处句子相似度 ≥0.62 或共同前缀 ≥6 字，方向相反且跨章节 | 否 |

极性判定：阳性词（显著提升/优于/提高了…）与否定词（未显著/未见提升/未观察到显著…）同时出现时，
若否定词起点早于阳性表述且两者之间无"但/然而/不过/却/反而"，判为否定。
这两条均为**候选**，需作者确认哪一处为准；脚本不改写。

## 8. 自动修订总边界（宁少不多）

允许自动改：
1. `terminology.latin_variant` 且规范写法含大写（排版级大小写统一）；
2. `terminology.workorder_term`（运行时工单显式指定）。

其余一律只报不改：符号多义、缩写不同全称、结论相反、编号重排、引用缺失、重复定义。
如两条规则命中同一区间，只应用一次替换（避免叠加污染）。

## 9. 为什么不做"智能润色"

本题的评分点在"可核验性"与"格式不塌"：任何语义改写都会引入无法自动验证的事实漂移风险。
本 Skill 用**可定位 + 可复核 + 最小侵入**换取可核验的一致性，而不是用整段重写换取"读起来更顺"。
