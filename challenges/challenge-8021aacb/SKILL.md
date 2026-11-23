---
name: structure-edit-planner
description: 对一篇完整稿件做结构级诊断（研究问题—方法—结果—结论对齐、章节权重与顺序、论证链断点、段落关系、跨节重复、结论越界），输出可逐条对照原文位置执行的移动/合并/拆分/补证据/收窄清单与修改后大纲；不改事实与数值，不交付无定位的重写稿。
version: 1.2.0
license: MIT
---

# 论文结构与逻辑优化：先定位，再给可执行动作

把"优化结构与逻辑"拆成 **读稿建图 → 六维定位 → 论点—论据映射 → 动作化 → 大纲重排 → 事实守卫**。
一条诊断的价值 = 能否指到 `章节 + 段落号 + 原句`；一条建议的价值 = 作者能否照做
（移哪段、并到哪、拆到哪句、补什么证据、哪句收窄）。**不重写全文，不改任何事实与数值。**

## 平台路径（务必按此执行）

本 Skill 在评测时安装于 `/skills/weekly-skill`，工作目录通常是 `/app`，**两者不同**。
所有脚本都用绝对路径调用，不依赖当前目录：

```bash
SKILL_DIR=/skills/weekly-skill          # 若你确实在 skill 目录内，可写 SKILL_DIR=.
python "$SKILL_DIR/scripts/run_case.py" --case /input/case.json --work /app/work --out /app/output
```

## 何时使用

触发（满足任一）：

- 用户给出**完整稿件**（或主要章节），要求检查结构、逻辑、论证链、章节顺序、篇幅分配、重复内容；
- 要求"为什么读起来散 / 结论站不住 / 引言与方法对不上"，并希望得到可执行的修改方案；
- 要求输出修改后大纲、段落去向表、审稿意见式的结构诊断。

不触发：只改语言/时态/用词（润色类）；没有稿件却要求"优化一篇论文"；只查参考文献格式；
要求代写缺失章节或补做实验（本 Skill 只指出证据缺口，不生成数据）。

## 主流程：一条命令保证完整交付（默认路径）

```bash
python "$SKILL_DIR/scripts/run_case.py" \
  --case /input/case.json --work /app/work --out /app/output
```

`run_case.py` 依次完成，并且**任何一步失败都会继续落盘**：

1. `init`：宽松读取 `case_id / task / output_contract`（支持 dict、字段名列表、嵌套 `fields`）；
2. `index`：递归发现 `/input` 与 `case.json` 中引用的材料，抽取 txt/md/docx/pdf/xlsx；也支持
   `case.json` 内联的 `source_text`；
3. `structure_probe` + `repetition_probe`：章节树与权重、`P001...` 段落（含行号）、论断候选、
   引用/数值/图表密度、跨节重复候选；
4. `baseline_plan`：**仅从本次实际稿件**推导六维诊断、动作、段落去向、大纲、论点—论据映射；
5. 若存在模型手写的 `work/plan.json`（或 `work/draft.json`），先严格门禁，再 `--sanitize`
   自动剔除无法逐字核验的条目，合格部分覆盖基线；
6. 逐条引文核验 + 数字/引用回溯，无法回溯的数值替换为“（数值待核）”并记入 `uncertainty`；
7. 写 `work/draft.json` → `result.json` + `structure_plan.md` + `diagnosis.csv` +
   `edit_plan.csv` + `outline.md`；
8. 末尾 `check` 的真实结果写入 `result.json.self_check.post_check`。

退出码 0 = 已写出诚实且结构完整的交付物（包括 `partial` / `blocked`）。不要因为门禁失败就
放弃产出；**先落盘，再在 `limits` 说明未完成项**。

## 可选增强：模型自己写方案

`run_case.py` 的规则基线覆盖机械可检部分。若时间允许，可在 `work/plan.json` 写：

```json
{"fields":{
  "diagnosis":[{"issue_id":"S01","dimension":"conclusion_boundary","severity":"high",
    "confidence":"medium","location":{"section":"5","paragraph_id":"P010","sentence_index":2,
    "anchor_quote":"原文逐字片段，≥12 字符"},"problem_type":"conclusion_overreach",
    "problem":"…","why":"…","evidence_refs":["P010"]}],
  "edit_plan":[{"edit_id":"E01","issue_id":"S01","action":"NARROW",
    "target":{"section":"5","paragraph_id":"P010","sentence_index":2},
    "instruction":"把该句的完全/所有收窄为在本实验条件下，并说明样本范围",
    "preserves":"数值、样本量、图表编号不变","expected_effect":"结论与数据范围一致",
    "risk":"作者可能另有未写入稿件的条件"}],
  "outline":[], "paragraph_map":[], "argument_map":[], "coverage":{}
}}
```

只写有把握的字段；缺失的数组/维度由基线补齐。`anchor_quote` 必须能在原文逐字找到，
否则会被拦截（`self_check.model_plan.dropped` 记录原因，条目本身不进入交付）。

## 六维规则表（每条都可复核）

| 维度 | 判定信号（须能指回原文） | 允许动作 | 反例（禁止） |
|-|-|-|-|
| 研究问题与贡献对齐 | RQ 只在引言出现一次、方法/结果不回指；贡献主张 > 实际完成工作 | NARROW、REWRITE_TRANSITION、FLAG_GAP | "贡献表述不够突出"（无位置、无对照） |
| 章节结构与叙事顺序 | 单节占比过高、结果/讨论被压缩、关键前提出现在结果之后 | MOVE、REORDER、MERGE、SPLIT | "建议调整章节顺序"而不说移到哪 |
| 论证链与论据对应 | 论断无证据、证据强度不足、跨节错位、结论未回应 RQ | ADD_EVIDENCE、NARROW、FLAG_GAP | 只列"逻辑不严密"清单 |
| 段落关系 | 一段多主题、指代跳跃、段间无过渡 | SPLIT、MERGE、REWRITE_TRANSITION | 把段落长度本身当问题 |
| 重复内容 | 同义重复、跨节重复；`repetition_pairs` 只是相似度候选 | MERGE、DELETE_REDUNDANCY、MOVE | 删除有独立信息量的段落 |
| 结论边界 | 相关写成因果、样本/条件外推、未写限制、普适断言 | NARROW、FLAG_GAP、ADD_LIMITATION | 要求作者"补充实验"却不说明支撑哪句 |

判定尺度：**结构问题**指信息的位置、顺序、依赖、范围；**风格偏好**（时态、语态、词汇、句长）
不进入诊断，除非造成指代歧义或论证断裂，并在 `why` 说明因果。

## 输出（`/app/output`）

| 文件/字段 | 内容 |
|-|-|
| `result.json` | 契约字段全量回填；含 `diagnosis / edit_plan / outline / paragraph_map / argument_map / fact_guard / coverage / source_map / changes / uncertainty / limits / self_check` |
| `structure_plan.md` | 人读版：诊断、动作、大纲、段落去向、论点—论据、事实守卫、限制 |
| `diagnosis.csv` / `edit_plan.csv` / `outline.md` | 可直接交给作者逐条执行的表格与大纲 |

`status` 语义：
- `ok`：模型方案通过严格门禁且确有诊断；
- `partial`：已交付完整结构诊断，但由规则基线产出、或存在被拦截/未核验项（`limits` 必写原因）；
- `blocked`：没有可读稿件或无法切分段落；仍写全四个工件，逐项说明缺失，不猜测内容；
- `refused`：请求超出边界（如要求代写实验/伪造数据）。

`coverage` 六维逐项写 `checked/findings`，并写 `read_sections/unread_sections`；无问题写
`findings: 0`，**不得静默跳过**。`coverage.no_issues_found` 仅在六维均已检查且确实零发现时为 true。

## 硬性禁止

- 不输出整篇重写稿替代原稿；不把"改后全文"当作交付物。
- 不新增、修改、删除任何数值、单位、样本量、p 值、图表编号、参考文献条目或实验条件。
- 不虚构缺陷：每条 issue 必须有 `anchor_quote` + 位置 + `why`；找不到原文依据就不写。
- 不做无定位建议（"优化逻辑""加强论证""精简篇幅"）；每条建议必须可执行、可驳回。
- 不把"未检出章节"判为"缺失章节"；不把未写限制说明当作学术不端。
- 不提交预制答案；所有诊断必须由本次实际读取的稿件推导。
- 不在产物中写入个人绝对路径、账号或 token。

## 异常与降级

| 情况 | 处理（均已内置于 run_case） |
|-|-|
| 稿件无标题/编号混乱 | 按段落聚类生成 `§A/§B`，`inferred_sections=true`；诊断降为段落级，`limits` 说明 |
| 无空行分段 | 按非空行聚合为候选段落，`structure.json.notes` 记录实际聚合行数 |
| 扫描 PDF 无文本层 | `blocked`；列不可读文件与缺失路径；不根据图注/标题猜测正文 |
| 只有部分章节 | 只诊断已读部分；`coverage.unread_sections` 标注，结论边界标为不可评估 |
| 图表缺失或只有编号 | 相关论断记 `FLAG_GAP`，不判"论证错误" |
| 多版本稿件 | 优先题面指定；否则取最新并在 `uncertainty.basis` 记录；不混合版本引用 |
| 预算不足（64 请求 / 900s） | 直接跑主流程；基线保底，`partial` + `limits` 列未完成项 |
| 模型方案门禁失败 | `--sanitize` 剔除不可核验条目后继续；全部被剔除则用基线，仍完整交付 |
| python 不可用 | 手工按同样字段落盘；`limits` 说明降级方式；仍给 `§/¶/原句` 定位 |

## 文件说明

- `scripts/run_case.py`：一条命令端到端（发现材料→探针→基线→可选模型方案→核验→交付→自检）。
- `scripts/kernel.py`：`init / index / verify / emit / check`；`emit` 无论 draft 是否提供工件，
  都会渲染 `structure_plan.md / diagnosis.csv / edit_plan.csv / outline.md`。
- `scripts/structure_probe.py`：章节权重、段落编号、论断/引用/数值/图表密度、规则告警。
- `scripts/repetition_probe.py`：跨节重复候选（英文词元 + 中文二字组）。
- `scripts/baseline_plan.py`：从 `structure.json` 推导完整方案（引文均为原文子串）。
- `scripts/quote_check.py`：`anchor_quote` 逐字核验（容忍换行、连字、软连字符）。
- `scripts/plan_check.py`：严格门禁 + `--sanitize` 降级修复。
- `references/argument-map.md` / `edit-actions.md` / `output-contract.md`：断点分类、动作词表、字段契约。

## 改动记录

### v1.2.0（修复 v1.1.0 attempt 91417 = 25.3333 的"无完整产出"）

- **根因 1（路径）**：v1.1.0 全部命令写 `python scripts/...` 且注明 cwd=`/app`，但 Skill 装在
  `/skills/weekly-skill`，脚本根本未被执行 → 无产物。现统一 `$SKILL_DIR` 绝对路径，脚本自身定位。
- **根因 2（门禁不可通过）**：v1.1.0 要求模型先手写 5 份 JSON，`plan_check` 退出码非 0 即
  "不得 emit"；任何一步缺失就完全没有 `result.json`。现引入 `baseline_plan.py` 保底 +
  `--sanitize` 剔除不可核验条目，异常输入也落盘 `blocked/partial`。
- **根因 3（契约/工件不一致）**：SKILL 承诺 `emit` 生成四个工件，实际只写 draft 里带的内容；
  缺工件 → `check` FAIL → 无交付。现 `emit` 无条件渲染四个工件；`check` 对空数组只告警。
- **根因 4（静默跳过）**：`index` 对不存在路径静默产出空 corpus；无空行时分段退化为 1 段；
  中文句号不分句；中文绝对化/因果词 `findall` 因捕获组返回空串。均已修复。
- **事实守卫**：`verify` 对数字做空白/千分位归一；方案叙述中无法回溯的数字替换为“（数值待核）”，
  不进入诊断引文；负向用例（编造 400% 结论）在严格门禁被拦截，sanitize 后该条被移除。
