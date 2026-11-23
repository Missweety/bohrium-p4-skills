---
name: research-output-transform
description: 科研成果转化写作。把论文摘要、技术报告、实验结果改写成面向另一类读者/体裁的稿子（论文摘要→公众科普、技术报告→项目申报、成果→新闻稿/政策简报/执行摘要），逐条保留结论、关键数字、范围与局限、术语和引用含义；用锚点核验引文与数值来源，登记删除项，标出不可直译术语、遗漏与源文冲突，产出 transform.md、preservation_map.csv、glossary.csv、result.json。
---

# 科研成果转化写作（Research Output Transform）

把“作者写给同行看的研究材料”改写为“另一群人愿意读、读得懂、且没有走样的稿子”。
本 Skill 的核心不是润色，而是**可核验的改写**：每一句结论能回到源文锚点，每一个数字能在源文找到，每一处删改有理由，每一处不确定都写在台面上。

## 什么时候用 / 不用

适用：

- 论文摘要 / 结果段 → 公众科普文章、新闻简讯、博客；
- 技术报告 / 结题材料 → 项目申报书、执行摘要、政策简报、利益相关方简报；
- 同一成果面向投资人、管理者、媒体、公众的版本改写；
- 需要“逐段对照 + 数字/引文核验”的成果转化稿。

不适用：

- 从零创作虚构故事、营销软文；
- 需要补做实验、补采数据、补访谈才能完成的申报材料（本 Skill 只做“有来源的改写”，不补事实）；
- 纯翻译（可做，但请把它当作一种体裁 `technical_summary` 处理并保留术语）。

## 三条命令（固定流程）

在部署目录（下称 `$SKILL`，通常为 `/skills/weekly-skill`）执行：

```bash
# 1) 抽取：跳过 case.json / task.md，按 doc.N p.N sec.N para.K 建锚点
python3 $SKILL/scripts/extract_sources.py --input /input --out /app/work/sources.json

# 2) 生成：读取你写的 plan.json，产出并核验
python3 $SKILL/scripts/build_transform.py \
  --plan /app/work/plan.json --sources /app/work/sources.json \
  --case /input/case.json --out /app/output --work /app/work

# 3) 自检：独立复算，有硬错误则非零退出
python3 $SKILL/scripts/selfcheck.py \
  --case /input/case.json --out /app/output --sources /app/work/sources.json
```

三个脚本只依赖 Python 标准库；PDF 优先用 `pdftotext`，缺失时自动退回内置解析器；仍无法读取时如实报告，不猜测内容。

## 执行步骤（不要跳步）

1. **读任务**：读 `/input/case.json` 的 `output_contract`、`/input/task.md` 的体裁/读者/篇幅要求。
2. **抽来源**：运行命令 1；打开 `sources.json`，记下每个段落的 `anchor` 与原文。`doc.N` 按文件名字母序编号，不要假设 `doc.1` 就是论文。
3. **列保全清单**：先从源文摘出结论、关键数字、范围/局限、术语、图表/引用编号，再决定哪些必须保留、哪些可以删（删必须登记）。
4. **写 plan.json**：按下方模板写到 `/app/work/plan.json`。正文用目标语言直接写成 `sections[].paragraphs`；`claim_evidence[]` 逐条给出“改写后的说法 + 源文引文 + 锚点”；术语、删除项、冲突/不确定全部列全。
5. **生成**：运行命令 2。脚本会核验引文、数值、术语、遗漏、断言强度、编造迹象与篇幅，并写出四个交付物。
6. **修**：看 `result.json` 的 `issues` 与 `status`。`error` 必须修（引文抄错、数字无来源、局限丢失、过度断言、删除无理由等）；`warn` 视情况修。改 plan 后重跑命令 2。
7. **自检**：运行命令 3；`checks.json.ok=true` 才算完成。不要手改 `result.json` 的状态或指标，重跑生成即可。

## plan.json 模板

```json
{
  "case_id": "来自 case.json",
  "title": "成稿标题",
  "audience": {
    "who": "读者是谁（如：对生命科学感兴趣的普通公众）",
    "prior_knowledge": "none|lay|general|professional",
    "purpose": "读者读完要获得什么",
    "reading_level": "高中/大学/专业"
  },
  "genre": "popular_science",
  "target_length": {"max_words": 800, "max_chars": 1600},
  "lead": "可选：导语/开场（press_release 常用）",
  "sections": [
    {"id": "s1", "heading": "章节标题", "role": "hook|background|finding|evidence|significance|limitations",
     "paragraphs": ["最终正文段落 1", "最终正文段落 2"]}
  ],
  "claim_evidence": [
    {"id": "c1", "kind": "claim|conclusion|number|limitation|scope|method|citation|definition",
     "claim": "正文中表达该事实的原句（尽量与 paragraphs 用词一致，便于定位）",
     "anchor": "doc.1 p.2 sec.3 para.7",
     "quote": "源文原句，逐字复制（空白差异可容忍）",
     "section": "s1",
     "strength": "fact|association|preliminary|inference|recommendation",
     "source_strength": "fact|association|preliminary",
     "output_text": "可选：若正文由脚本按 claim 组装，填该句"}
  ],
  "glossary": [
    {"term": "mRNA", "plain": "信使核糖核酸，把基因信息带到蛋白合成现场的分子",
     "action": "expand|replace|keep", "aliases": [], "source_note": "可选锚点"}
  ],
  "removals": [
    {"removed": "删掉的内容（可写概括）", "source_anchor": "doc.1 p.3",
     "reason": "为什么删（与目标读者/体裁无关、重复、超出篇幅）",
     "risk": "none|low|medium|high"}
  ],
  "numbers": [
    {"value": "71%", "anchor": "doc.1 p.2", "basis": "仅当源文没有该写法时填写推导依据，如 71/100 由源文两数相除"}
  ],
  "uncertainty": ["无法直译的术语、口径差异、外推风险、需作者确认的事项"],
  "quoted_material": ["可选：源文确有、但不在正文段落里的直接引语"],
  "contract_fields": {"契约里出现的自定义字段名": "对应内容"},
  "change_log": ["可选：你希望额外记录的改动"]
}
```

要点：

- `sections[].paragraphs` 是你真正要交付的成稿；脚本不会替你编句子。若只给了 `claim_evidence[].output_text`，脚本会按 `section` 组装。
- `claim` 是“正文里的说法”，`quote` 是“源文里的证据”。两者不要混用；`quote` 必须能在 `sources.json` 中找到。
- 一个结论/数字/局限一条 claim；不要把所有内容塞进一条。
- 源文没有的数字一律不要写；确需换算时在 `numbers[]` 写明 `basis`。
- 面向非专业读者时，正文出现的缩写/术语必须进 `glossary`，且 `expand` 项要在首次出现处就地解释。

## 保全契约（P1–P9）

- **P1 结论**：源文的每条结论/主要发现，要么在正文中有对应表述，要么在 `removals` 中登记理由与风险。不得把“未证实”写成“已证实”。
- **P2 数字**：正文每个数字必须逐字出现在源文，或在 `numbers[]` 中给出推导依据。不得四舍五入、换单位或重算后不留痕。
- **P3 范围与局限**：样本量、对象范围、单中心、初步性、“相关不等于因果”等限定必须保留或登记删除；弱证据不得升级为强断言。
- **P4 术语**：专业术语/缩写按读者处理——`expand`（就地解释）、`replace`（换成日常说法）、`keep`（保留但入术语表）。不可直译的术语保留原文并加解释，同时写入 `uncertainty`。
- **P5 引用含义**：图/表编号、参考文献编号的含义不得改变；不得制造源文没有的引语、专家表态、采访或用户反馈。
- **P6 读者/体裁适配**：可以调整顺序、增补仅来自源文的背景、改语气与标题；不得添加源文没有的经历、案例、数据、因果解释。
- **P7 删除留痕**：每处删除写 `reason` 与 `risk`；`risk=high` 会在不确定性中提示人工确认。
- **P8 冲突不合并**：源文两处说法/数值冲突时，保留并标出（脚本会检测近似段落的不同数值），不要静默选一个。
- **P9 可追溯**：`preservation_map.csv` 每行给出 claim → 文档/锚点/引文 → 输出位置，供原作者逐段复核。

## 受众与体裁改编规则

| 体裁 `genre` | 典型读者 | 必须保留 | 可以调整 | 禁止 |
|---|---|---|---|---|
| `popular_science` 公众科普 | 非专业公众 | 主要发现、效应量/关键数字、证据强度、局限 | 加生活化开场、解释术语、重排为“问题—发现—证据—意义—边界” | “科学家震惊”、无来源类比、把相关写成因果 |
| `press_release` 新闻稿 | 媒体/公众 | 核心发现、数字、来源、局限 | 导语前置、加背景、给原文出处 | 编造机构/专家引语、夸大“首次/突破” |
| `project_application` 项目申报 | 评审专家 | 问题、目标、方法、前期结果、可行性、风险 | 按申报结构重排、把方法写成路线 | 编造预实验、虚报指标、把计划写成已完成 |
| `policy_brief` 政策简报 | 决策者 | 结论、证据强度、适用范围、局限 | 先给建议相关发现、压缩方法 | 给源文没有的政策建议、隐去不确定性 |
| `executive_summary` 执行摘要 | 管理者 | 背景、发现、意义、局限 | 极简结构、要点化 | 删掉限定、只留好消息 |
| `technical_summary` 技术摘要 | 同行/技术管理者 | 方法、结果、精度、条件、局限 | 压缩背景、统一术语 | 丢失实验条件、混淆指标口径 |
| `grant_abstract` 基金摘要 | 评审 | 问题、目标、方法、前期结果、意义 | 按摘要字数压缩 | 把“将开展”写成“已完成” |
| 其他/自定义 | 按 plan | 结论、数字、局限、术语 | 通用结构 | 假装套用了不存在的体裁规范（会标 `unsupported_genre` 并转 partial） |

读者适配检查：非专业读者下，平均句长 > 70 字符、术语密度 > 15/千字符、正文出现未入术语表的缩写，都会产生警告或错误。

## 异常处理表

| 情况 | 脚本行为 | 你应该怎么做 |
|---|---|---|
| 体裁不在内置模板 | `unsupported_genre` 警告，`status=partial` | 用通用结构交付；在 `uncertainty` 说明体裁假设，或改用最接近的内置体裁 |
| 正文数字源文没有 | `unsupported_number`（error）→ partial | 删掉该数字，或在 `numbers[]` 写清推导依据；不要改源文引文迁就 |
| 引文核验失败 | `quote_unverified`（error）→ partial | 从 `sources.json` 重新逐字复制；不要删 claim 掩盖 |
| 删除未登记 | `omission_unlogged_*`（error）→ partial | 在 `removals` 用页级锚点（如 `doc.1 p.3`）或原文片段登记 |
| 源文数值/表述冲突 | `source_conflict` 警告 + uncertainty → partial | 两处都保留，正文注明“不同来源/批次给出不同数值”，交作者确认 |
| 弱证据被写成强断言 | `claim_strength_upgrade`（error） | 改回“相关/提示/初步/可能”，或把 `strength` 标为 `association`/`preliminary` |
| 编造经历/引语 | `fabricated_experience` / `fabricated_quote`（error） | 删除；只保留源文可核验的引语（必要时登记 `quoted_material`） |
| 术语缺解释 | `glossary_not_expanded` / `unglossed_jargon`（error，非专业读者） | 首次出现处加括号解释；或 `replace` 成日常说法 |
| 篇幅超限 | 超上限 110% 为 error，略超为 warn | 删重复背景或方法细节；优先保留结论、数字、局限 |
| 空输入/无文本层 PDF | `extract_sources.py` 退出码 2；`build_transform` 写 failed 说明 | 不要编造内容；在 result 中如实说明无法读取的文件 |
| `output_contract` 缺失/自定义键 | 缺契约时警告；自定义键从 `plan.contract_fields` 或同名 plan 字段取值 | 在 `plan.contract_fields` 显式补齐 |
| 计划缺失/正文为空 | `status=failed`，写失败说明，不写假文章 | 补 plan 或补 `sections.paragraphs` |
| 篇幅目标为字符串 | 取第一个数字作 `max_words`，并视为上限 | 尽量写成 `{"max_words": N}` 的对象 |

## 诚实降级（partial / failed）规则

- `success` 仅当：无 error 级 issue、全部 claim 引文通过、全部数字可追溯、无未登记遗漏、无源文冲突待判、篇幅在上限 110% 以内、无占位符、契约键齐全。
- `partial`：仍产出完整可编辑稿，但存在上述任一问题。必须在 `issues` 说明原因，把需要人判断的事项写入 `uncertainty`，并在 `status_reason` 写清楚。**不要把 partial 改成 success。**
- `failed`：没有可读来源、plan 缺失、或正文为空。`transform.md` 只写简短失败说明，`result.json` 保留契约字段与失败原因；不生成占位正文。
- 三种状态都要留下 `change_log`，说明读了哪些来源、做了哪些核验、为什么是这个状态。

## 交付物

`/app/output/` 下：

- `transform.md`：成稿（标题 + 章节；术语表附录可选）；
- `preservation_map.csv`：claim → 文档/锚点/引文 → 输出位置；
- `glossary.csv`：术语、通俗解释、处理方式、出现次数、是否就地解释；
- `result.json`：`case_id`、`status`、`sources`、`uncertainty`、`change_log`、`issues`、`deliverables`、`contract_fields`，以及 `case.json` 中 `output_contract` 的每个键；
- `checks.json`：由 `selfcheck.py` 生成的独立复算结果。

字段定义、CSV 列名、指标公式、契约键解析规则见 `references/output-contract.md`；判定阈值与正反例见 `references/preservation-rules.md`。

## 局限

- 不补做实验、不补采数据、不生成真实引语；需要新事实时应返回 `partial` 并说明缺口。
- 扫描版 PDF 无文本层时无法可靠抽取，只能如实报告；可请任务方提供文本版。
- 中文/英文混合文本的句长、词数为近似统计，用于相对比较，不作为语言学结论。
- 内置体裁模板是写作检查清单，不是期刊/基金委的官方格式；以任务给出的格式要求为准。
