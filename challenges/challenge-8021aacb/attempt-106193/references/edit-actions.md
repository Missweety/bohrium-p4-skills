# 编辑动作词表（writing）

每条诊断必须落成**作者可照做**的动作。判断标准：作者读完能否不问一句"具体怎么改"就开始动手。

## 1. 动作与必填字段

| action | 含义 | 必填 | 前置条件 |
|-|-|-|-|
| `MOVE` | 整段或整句移动 | `target`、`destination`（§/¶ 之后）、`instruction` | 目标位置不破坏依赖顺序；移动后原位置需过渡句时并列 `REWRITE_TRANSITION` |
| `MERGE` | 两段/两句合并 | `target[]`（≥2）、`keep`（保留哪段主题句）、`instruction` | 内容确实重复或同属一论点；不得合并唯一数据来源 |
| `SPLIT` | 一段拆成两段 | `target`、`split_at`（第 k 句）、`instruction` | 段内存在两个独立主题；拆分后每段有主题句 |
| `REORDER` | 章节/小节换序 | `target[]`、`new_order`、`instruction` | 依赖关系允许；涉及图表编号时**不改编号**，只改引用位置 |
| `ADD_EVIDENCE` | 要求补某类证据 | `target`（支撑哪句）、`evidence_needed`（图/表/对照/统计量）、`instruction` | 只描述缺口，不代造数据或文献 |
| `NARROW` | 收窄论断/结论 | `target`（句）、`before_phrase`、`after_phrase`（或改写要点） | 保留原数值与条件，只改范围/强度 |
| `DELETE_REDUNDANCY` | 删除重复内容 | `target`、`redundant_with`（与哪处重复）、`instruction` | 被删内容无独有数据/条件；在 `paragraph_map` 标 `removed` |
| `REWRITE_TRANSITION` | 补/改衔接 | `target`（段首/段尾）、`relation`（因果/对照/递进/回指）、`instruction` | 不引入新事实，只表达已有内容之间的关系 |
| `FLAG_GAP` | 标记材料缺口 | `target`、`missing`（缺什么）、`impact`（影响哪条结论） | 无法通过改结构解决，交作者补材料 |

## 2. 可执行 vs 不可执行

| 不可执行（禁止） | 可执行（示例） |
|-|-|
| "建议优化引言逻辑" | "把 §1 ¶3 第 2–4 句（P006）移到 §1 ¶1 之后，作为研究背景；原位置补一句回指 §1.2 的过渡" |
| "结论过度推广" | "把 §5 ¶1 第 1 句 caused 收窄为 was associated with；保留 38% 与 n=3，并补'未设干预对照'" |
| "精简重复内容" | "§2.3 ¶2（P018）与 §3.1 ¶1（P023）都描述退火流程；保留 P018，P023 改为回指 §2.3，删除重复 3 句" |
| "加强论证" | "P014 的因果结论缺对照：在 P014 后插入 FLAG_GAP，要求补充空白对照组数据；在此之前该句改为相关性表述" |

## 3. 动作粒度

- 句子级：给 `sentence_index`（段内第 k 句，按句号/问号/分号切分）与 `anchor_quote`；
- 段落级：给 `paragraph_id`（沿用输入编号）与段首 12 词；
- 章节级：给章节编号与原标题（不改标题时注明"标题不变"）。

## 4. 段落去向（paragraph_map）

每个原段落必须且只能有一种去向：

```json
{"paragraph_id":"P014","status":"moved","to":"§4.1 ¶1","reason":"该段是对比结果，应紧随结果表"}
{"paragraph_id":"P018","status":"merged","into":"P017","reason":"两段同述退火流程，保留 P017 的条件细节"}
{"paragraph_id":"P023","status":"removed","reason":"与 P018 重复，无独有数据"}
{"paragraph_id":"P031","status":"kept","reason":"局限性说明，位置正确"}
```

规则：
- `removed` 必须写 `redundant_with` 或 `reason`，且不得是唯一数据/条件来源；
- 新增段落 `status: "added_placeholder"`，并写 `needs`（作者需补什么），不得含具体数值；
- 合并后原段落号保留在 `merged` 记录中，便于作者对照旧稿。

## 5. 事实守卫清单

交付前逐项确认：

- [ ] 所有数值、单位、样本量、p 值、图表编号与原文一致；
- [ ] `NARROW` 只改范围/强度词，不改数值与实验条件；
- [ ] `ADD_EVIDENCE` / `FLAG_GAP` 没有写成"已补数据"；
- [ ] 新增过渡句不含原文没有的事实；
- [ ] `verify` 的 `unsupported_numbers` 为 0，或逐条写入 `uncertainty` 并说明来源；
- [ ] 引用编号/作者年份未被改动或新增。

## 6. 常见反例

1. 把"时态不统一""被动语态过多"写成结构问题 —— 属语言润色。
2. 以"章节不符合 IMRaD"为由要求重排 —— 先看体裁；短通讯、方法学论文可不按 IMRaD。
3. 建议"删掉一半篇幅" —— 未说明删哪段、为什么该段无信息量。
4. 建议"补充实验验证机理"却不指出支撑哪一句、缺哪类证据 —— 作者无法执行。
5. 诊断写"讨论与结果不一致"但不给两处原文 —— 不可复核。
