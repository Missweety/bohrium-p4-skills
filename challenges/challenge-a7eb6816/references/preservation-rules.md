# 保全规则与判定口径（Preservation Rules）

本文件把“改写不走样”拆成可执行的判断规则。所有阈值与 `scripts/build_transform.py`、`scripts/selfcheck.py` 的实现一致；文中示例均为**合成示例（SYNTHETIC）**，不代表任何真实研究。

## 1. 先建“保全清单”

写 plan 之前，逐段读 `sources.json`，把以下五类内容标出来：

| 类别 | 识别线索 | 去向 |
|---|---|---|
| 结论/主张 | 摘要、结果、结论段；“表明/提示/发现/associated/suggests” | `claim_evidence.kind=conclusion` 或 `claim` |
| 关键数字 | 百分比、样本量、区间、p 值、倍数、时间、温度 | `claim_evidence.kind=number`；必要时 `numbers[]` |
| 范围/局限 | 样本、单中心、单细胞系、初步、相关非因果、不能外推 | `kind=limitation|scope`；正文“边界”段 |
| 术语/缩写 | mRNA、置信区间、trypan blue、AUC… | `glossary` |
| 图表/引用 | Fig. 3、Table 2、[12]、(Smith et al., 2020) | `kind=citation`；正文保留编号含义 |

原则：**先决定保留什么，再决定删什么；删什么必须留痕。**

## 2. claim_evidence 的写法

一条 claim 只承载一个可核验的事实/判断：

```json
{"id": "c1", "kind": "number",
 "claim": "对照组回收率为 92%，冷却组降至 71%，相差 21 个百分点。",
 "anchor": "doc.3 p.1 sec.2 para.2",
 "quote": "Recovery was 92% in the control group and 71% in the cooled group (difference 21 percentage points, n = 24 per group).",
 "section": "s3", "strength": "association", "source_strength": "association"}
```

- `claim` 要尽量使用正文里的原句或紧密片段，`build_transform` 会在正文中定位它；定位失败会报 `claim_not_in_output`。
- `quote` 建议直接从 `sources.json` 复制。核验会忽略空白、大小写、弯引号/破折号差异，但**不会**容忍同义词替换或数字改动。
- 数字类 claim 的 `quote` 必须包含该数字的源文写法。
- 局限类 claim 单独列出；不要把“样本小、不能外推”和“主要发现”塞进同一条。

### 定位与锚点

- 锚点格式：`doc.N p.N sec.N para.K`，来自 `sources.json`。
- 锚点写错但引文能在别处找到：脚本会校正并在 `change_log` 留痕；仍建议写对，便于作者复核。
- 引文跨 PDF 分页/分段：会被标为 `(spanning paragraphs)`，仍算通过，但定位精度下降。

## 3. 断言强度：不许把“可能”写成“证明”

`strength`（输出）与 `source_strength`（源文）取：

`fact` > `association` > `preliminary` > `hypothesis`（`inference`/`recommendation` 用于推断与建议）

弱证据线索（出现在 **quote** 中，或 `source_strength` 属于弱档）：

> 相关、关联、可能、提示、初步、尚需、有待、不能排除、不能推断、无法证明、有限、不足以、谨慎；limited、preliminary、associated、correlat、suggests、may、might、could、potential、not proof、cannot、small sample

强断言措辞（出现在 claim 或其正文段落）：

> 证明、证实、确定、必然、导致、决定了、确凿；proves、demonstrates、confirms、causes、establishes、conclusively、definitively、shows that

规则：

- 源文弱 + 输出 `strength=fact` → `claim_strength_upgrade`（error）。
- 源文弱 + 正文使用强断言且同段没有任何弱化词 → `claim_strength_upgrade`（error）。
- 局限类 claim 的正文段落若完全没有“仅/不能/初步/相关”等限定 → `limitation_under_preserved`（warn）。

正例：“冷却与更低回收率**相关**，但样本量小、只测了一种细胞系，**不能证明**因果。”
反例：“冷却**导致**回收率下降 21%。”（源文只说 association）

## 4. 数字：逐字或给推导

- 输出数字必须在源文出现（按数字部分匹配），或在 `numbers[]` 给出 `basis`。
- 不做四舍五入、不换单位、不把 0.71 写成 71%、不把“21 个百分点”写成“21%”而不留痕。
- `0.71` 与 `71` 是两个不同 token；`1,000` 归一为 `1000`。
- 标题、列表编号、URL、DOI、`[12]` 引用编号不参与检查。
- 交叉表/正文重复的数字只算一次，但仍需在正文出现或登记删除。

需要换算时：

```json
"numbers": [{"value": "71%", "anchor": "doc.3 p.1 sec.2 para.2",
             "basis": "源文给出 71/100 的比例，按百分比表述；未重算"}]
```

正例：源文 `8 to 34 percentage points` → 正文“8 至 34 个百分点”。
反例：源文 `n = 24 per group` → 正文“每组约 25 个样本”（改写数字）。

## 5. 术语：expand / replace / keep

| 动作 | 适用 | 正文要求 | 示例（SYNTHETIC） |
|---|---|---|---|
| `expand` | 非专业读者、术语首次出现 | 首次出现处就地解释，括号或同位语 | `mRNA（信使核糖核酸，把基因信息带到蛋白合成现场的分子）` |
| `replace` | 有准确日常说法 | 正文不再出现原术语（术语表可保留） | `置信区间` → `结果可能波动的范围` |
| `keep` | 专业读者或无法替换 | 保留术语，靠 `## 术语与缩写` 解释 | `AUC` 保留，附录解释 |

- `plain` 不能为空；`expand` 项首次出现附近必须出现 `plain` 的实质内容，否则 `glossary_not_expanded`（error）。
- 面向非专业读者时，正文所有缩写都应进术语表（PDF/DOI/URL/DNA/RNA 等常用白名单除外），否则 `unglossed_jargon`（error）。
- 无法直译的术语：保留原文 + 解释，并写入 `uncertainty`；不要硬造中文名。
- 术语密度 > 15/千字符、平均句长 > 70 字符（非专业读者）会产生可读性警告。

## 6. 删除与遗漏：必须留痕

脚本会检查源文段落（≥ 60 字符，排除参考文献/致谢/短标题）是否被正文覆盖：

- 覆盖率 = 该段 token 出现在正文中的比例；**≥ 0.12 视为已覆盖**（允许改写）。
- **跨语言例外**：若存在一条已核验、已定位、且 `anchor` 指向该段落的 claim，同样视为已覆盖。否则英文源 → 中文稿时任何译文都会因 token 不重合被判遗漏。
- 覆盖率低且未被 anchor 覆盖、但命中 `removals` → `status=logged`。
- 未命中 → `status=unlogged`；若该段含数字或局限表述，记 **error**；否则 warn。
- 任一未登记遗漏都会使 `status=partial`。

`removals` 粒度：

- 精确：`"source_anchor": "doc.1 p.3 sec.2 para.9"`；
- 整页：`"source_anchor": "doc.1 p.3"`（匹配该页所有段落）；
- 文本：`"removed": "方法参数扫描与附表 2"`（与源文片段高重叠时匹配）。

每条必须有 `reason` 与 `risk`：

| risk | 含义 | 处理 |
|---|---|---|
| `none` | 纯重复/格式信息 | 直接删 |
| `low` | 背景细节、方法细节 | 删，保留一句概括 |
| `medium` | 次要结果、补充材料 | 删，正文提示“另见原文” |
| `high` | 与主要结论/局限相关 | 删需人工确认，脚本写入 uncertainty |

**不能删的东西**：主要结论、关键数字、范围/局限、与结论相反的发现。篇幅不够时，先删重复背景和方法细节。

## 7. 局限与范围

以下句型会被识别为“必须处理”的局限（长度 20–400 字符）：

> 局限、限制、不足、仅、只能、尚不能、不能、无法、未、有待、尚需、初步、样本量、相关而非、相关不等于、不能推断、不宜、风险、谨慎、单中心、单一、外推；limited、small sample、preliminary、suggests、associated、correlat、not prove/cause/establish、cannot、unable、only one、single、future work、warrant、caution

处理方式（任一即可）：

1. 用 `kind=limitation|scope` 的 claim 引用该句，并在正文保留对应表述；
2. 在 `removals` 登记该段并说明理由；
3. 正文中有明显同义改写（token 覆盖率 ≥ 0.45）。

若源文有局限句但正文/claim/removals 完全没有处理 → `limitations_absent`（error）。部分未覆盖 → 最多 5 条 warn。

正例：“这是一项**初步**研究，只测试了**一种细胞系**，样本量**较小**，**不能**确立因果，也**不能排除**批次效应。”
反例：只写“研究发现冷却降低回收率”，把局限全部删掉。

## 8. 引用、图表与引语

- 正文提到 `图 3 / Fig. 3 / 表 2 / Table 2` 时，编号必须与源文一致；不能把 Fig. 3 写成 Fig. 2。
- 不得新增源文没有的参考文献编号；不得改变引用支撑的命题（源文用 [12] 支持 A，不能拿来支持 B）。
- 直接引语只用源文确有、可核验的句子；否则写入 `plan.quoted_material` 并提供锚点。
- 带归属的引号（后接“表示/指出/said/according to”）但源文找不到 → `fabricated_quote`（error）；无归属的修辞性引号 → warn。

## 9. 不得编造经历与数据

以下模式会被检查（片段需在源文中有 ≥ 70% token 支持，否则报错）：

> 我们/笔者/课题组 + 开展/进行/组织/完成/走访/采访/调查/试用 + 实验/调查/访谈/采访/试用/测试/用户研究；
> in/during our survey/interview/trial/user study/field study；
> 我们/笔者 + 采访/走访/咨询 + 专家/用户/患者/企业/医生；
> 专家/用户/患者/客户 + 表示/反馈/反映。

因此：

- 不要为了“生动”添加“我们采访了 3 位医生”“用户反馈很好”；
- 不要把“计划开展”写成“已完成”；
- 不要给新闻稿编造机构或专家引语；
- 需要新的经验材料时，返回 `partial`，在 `uncertainty` 说明缺口。

## 10. 源文冲突

检测方式：同文档中两段（≥ 80 字符）token Jaccard ≥ 0.55，且两边数字集合不同（最多比较 160 段，最多报 8 处）。

处理：

- 两处都保留，正文写“不同批次/站点给出不同数值（A：92%；B：87%）”；
- 在 `uncertainty` 写“需作者确认哪一口径为准”，`needs_human=true`；
- 不要静默选择一个数字，也不要把两数平均。

## 11. 体裁要素检查（内置模板）

`popular_science` 建议含：hook、background、finding、evidence、significance、limitations；
`press_release`：lead、finding、context、significance、reference、limitations；
`project_application`：problem、objective、approach、preliminary_results、feasibility、risks、plan；
`policy_brief`：problem、finding、evidence、implications、limitations；
`technical_summary`：problem、method、results、limitations、conclusion。

章节的 `role` 或标题关键词命中即算具备。缺失 → `genre_element_missing`（warn）+ uncertainty；**不要为了凑要素编内容**，缺什么就如实标什么。

## 12. 成稿前检查清单

- [ ] 每个结论/数字/局限都有 claim 行，`quote` 能在 `sources.json` 找到。
- [ ] 正文所有数字都能在源文找到，换算项有 `basis`。
- [ ] 局限段保留了“样本/范围/初步/相关非因果”中适用的限定。
- [ ] 弱证据没有升级为“证明/导致/必然”。
- [ ] 非专业读者的术语已解释；缩写全部入表。
- [ ] 删除项有理由和风险；含数字/局限的段落没有静默消失。
- [ ] 没有编造的采访、反馈、专家表态、用户研究。
- [ ] 图表编号与源文一致；引语可核验。
- [ ] 篇幅在目标上限内；超限时先删重复背景。
- [ ] `selfcheck.py` 退出码为 0，`checks.json.ok=true`。
