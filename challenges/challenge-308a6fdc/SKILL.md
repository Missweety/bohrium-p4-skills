---
name: manuscript-evidence-writer
description: 从给定科研材料（实验记录、数据表、图表、参考文献、补充材料、或 case.json 内嵌原文）生成可编辑的论文稿件，并把每个数字、样本量、图注编号和引用绑定到具体材料位置；产出 manuscript.md、事实—来源映射、离线一致性审计与待核清单，缺数据/冲突显式落盘而不是编造。适用于按模板撰写摘要/引言/方法/结果/讨论/结论或补齐章节；不适用于无材料自由创作、代写数据或纯语言润色。
version: 2.0.0
license: MIT
---

# 学术论文写作：先证据，后成稿

流水线：**契约 → 材料索引 → 事实卡 → 逐段写作 → 本地渲染成稿 → 失败即拦截的审计 → 交付**。
v2 的关键变化：入口脚本真的渲染 `manuscript.md`；`audit` 对未登记占位、未登记冲突、无来源数字、悬空引用直接 FAIL；
不再只是"给模板让模型自己保证"。

## 何时使用

触发：给出研究材料并要求论文的某个章节/整篇初稿、结果段 + 图注、按期刊模板补齐章节、
把表格/图/实验记录写成正文、核对稿件数字与引用。

不触发：没有任何材料却要求生成研究结论；纯语言润色；纯文献检索。遇到这类请求先说明缺什么，
再按"blocked"降级，**不要用领域常识补实验数据**。

## 输入与路径

平台会把 Skill 装在 `/skills/weekly-skill`，工作目录 `/app`，输入 `/input`，输出 `/app/output`。
本文件中的命令均使用相对路径 `scripts/...`，在 `/app` 下执行。

输入来源按优先级：

1. `--case` 指定的 `case.json`（默认依次尝试 `/input/case.json`、`./case.json`、`/app/input/case.json`）；
2. `case.json` 同目录的 `task.md`（只用于发现章节与约束，**不作为数字来源**）；
3. 材料目录：`case.json` 的 `materials` 字段，或同目录 `materials/ input/ data/ attachments/ supplementary/`；
4. 运行时内嵌输入：`case.json` 的 `source_text`/`input_text` 字段，或 `materials: [{name, content}]`。
   `init`/`index` 会把它落盘到 `work/inline/` 再索引，禁止跳过。

`case.json` 字段名不固定；`init` 会做宽松识别并把原始键写到 `work/contract.json` 的 `raw_keys`。
题面若给出 `output_contract`，**字段一个都不能少**；缺失时按本文件末尾默认契约补齐。

## 产物

| 文件 | 作用 |
|-|-|
| `work/contract.json` | case_id、任务原文、题面契约、默认契约、材料发现结果 |
| `work/section_template.json` | 章节模板（从 case 任务识别；未识别时给 advisory IMRaD） |
| `work/evidence.json` / `corpus.txt` | 材料清单、sha1、可读性、统一文本 |
| `work/facts.json` | 自动抽取的**候选**事实（值/单位/文件/行号/上下文），供建 source_map 用 |
| `work/references.auto.json` | 从 `.bib` 解析出的候选文献条目 |
| `work/draft.json` | 你写的唯一结构化稿：章节、图注、文献、来源映射、待核项 |
| `work/manuscript.md` | 脚本渲染出的可编辑成稿（不是模板段） |
| `work/source_map.json/.csv` | 事实—来源映射（人可核对） |
| `work/audit.json` | 审计结果：verdict / problems / conflicts / todo |
| `work/todo.md` | 待补、待核、冲突清单 |
| `work/claims.json` | 数字/引用守恒检查（verify） |
| `/app/output/result.json` | 平台输出契约 |
| `/app/output/manuscript.md` | 主产物（与 `artifact_path` 一致） |

## 执行流程（按顺序，命令与脚本一致）

```bash
# 1) 契约 + 章节模板 + 内嵌输入落盘
python scripts/kernel.py init --case /input/case.json --out work

# 2) 索引材料（无 --materials 时自动发现；也可显式传目录/文件）
python scripts/kernel.py index --case /input/case.json --out work
# 或：python scripts/kernel.py index --materials /input/materials --out work

# 3) 读 work/facts.json、work/references.auto.json、corpus.txt，写 work/draft.json
#    这是唯一需要模型写内容的一步；格式见下节。没有证据的句子不要写。

# 4) 渲染成稿 + 来源映射 + 待核清单
python scripts/kernel.py build --draft work/draft.json --out work

# 5) 离线审计（FAIL 必须修，不能靠改 status 绕过）
python scripts/section_audit.py \
  --draft work/manuscript.md \
  --map work/source_map.json \
  --template work/section_template.json \
  --corpus work/corpus.txt \
  --plan work/draft.json \
  --references work/references.json work/references.auto.json \
  --todo work/todo.md \
  --out work/audit.json

# 6) 数字/引用守恒（辅助定位，不替代 audit）
python scripts/kernel.py verify \
  --text work/manuscript.md --evidence-dir work --plan work/draft.json --out work

# 7) 组装输出契约并复制产物
python scripts/kernel.py emit \
  --draft work/draft.json --contract-dir work --work-dir work \
  --audit work/audit.json --source-map work/source_map.json \
  --out /app/output

# 8) 严格交付门禁（失败则根据报错回到 3/5）
python scripts/kernel.py check --out /app/output --contract-dir work
```

`--references` 允许传入不存在的文件（自动跳过）；如果你自己整理了 `work/references.json`，一并传入。

## `work/draft.json` 格式

```json
{
  "case_id": "string",
  "status": "ok|partial|blocked|refused",
  "language": "en|zh",
  "title": "可选标题",
  "reference_style": "numbered|author-year",
  "sections": [
    {"heading": "Results", "level": 2, "paragraphs": [
      {"text": "正文……（Figure 1）……", "fact_ids": ["C0003"]},
      {"text": "此处缺处理组数值。", "placeholder": "treated degradation value"}
    ]}
  ],
  "figures": [
    {"label": "Figure 1", "caption": "图注正文。", "section": "Results",
     "source_path": "/input/materials/fig1.png", "locator": "whole image"}
  ],
  "tables": [],
  "references": [
    {"key": "smith2020", "authors": "Smith, Jane and Lee, Wei", "year": "2020",
     "title": "……", "venue": "Journal of Catalysis", "volume": "382",
     "pages": "45-53", "doi": "10.1016/j.jcat.2020.01.001"}
  ],
  "declarations": {
    "data_availability": "……", "funding": "……",
    "conflict_of_interest": "……", "ethics": "……"
  },
  "source_map": [
    {"claim": "treated degradation", "metric": "treated degradation", "value": "21.7",
     "source_path": "/input/materials/exp.csv", "locator": "row 3, col degradation_pct",
     "fact_id": "C0007"}
  ],
  "changes": [{"target": "Results", "type": "created", "before": "", "after": "……", "reason": "……"}],
  "uncertainty": [
    {"id": "U01", "type": "missing_material|unverifiable|conflict|missing_citation|ambiguous_instruction",
     "where": "Results paragraph 1", "what": "treated degradation value",
     "why": "exp.csv row 3 is empty", "next_step": "作者补数或确认未采集"}
  ],
  "conflicts": [
    {"where": "exp.csv row 3 / notes.md line 1", "what": "treated degradation",
     "values": ["18.2", "21.7"], "sources": ["..."], "why": "两份材料不一致"}
  ],
  "limits": "status=partial 时必填"
}
```

规则：

- `source_map` 必须覆盖正文中每个数字、单位、样本量、p 值、温度/剂量；同一 `claim`/`metric` 出现不同值即为冲突。
- `fact_ids` 可选，但建议填 `work/facts.json` 的 `candidate_id`，便于回查。
- 图注必须写成 `Figure 1. ...` / `Table 1. ...`（中文 `图 1.` / `表 1.`），正文必须出现 `Figure 1` 引用；
  `figures[].section` 决定图注放在哪一节之后。
- 文献：每条至少 authors/year/title/venue；有 DOI 才写 DOI，**没有就留空并在 limits 或 uncertainty 说明未核验**。
  不允许凭记忆补文献；材料里没有的引用，要么不引，要么写 `【待补：reference for ...】` 并登记 `missing_citation`。
- 缺数据：正文写 `【待补：<what>｜<why>】`，并在 `uncertainty` 写一条 `what` 或 `where` 能对上的记录。
- 冲突：正文保留两个值并写 `【待核：<what> <A> vs <B>】`，`uncertainty` 写 `type=conflict`，同时填 `conflicts`。
- 不要用"约/大概/可能"掩盖缺失数字；不要在 `limits` 为空时声明 `partial`。

## 审计门禁（`section_audit.py`）

| 检查 | FAIL（必须修） | WARN（review） |
|-|-|-|
| 章节 | 模板 required 章节缺失、顺序错 | advisory 章节缺失、字数不足 |
| 数字 | 正文数字无法在 source_map 或 corpus 中找到，且未被 uncertainty 覆盖 | 只被 uncertainty 覆盖 |
| 引用 | 编号/`\cite{}`/作者-年份无法在文献表、bib 或材料原文中解析 | — |
| 文献 | 结构化条目缺 authors/year/title/venue | 缺 DOI（标记未核验，不补造）、条目未被引用 |
| 图表 | 正文引用 `Figure N` 但无图注；模板图中的 label 无图注 | 图注未被正文引用 |
| 占位 | `【待补/待核：…】` 没有对应 uncertainty 记录 | — |
| 冲突 | source_map 同一 metric 多值但未登记 conflict | 材料中发现疑似冲突候选（待人核） |
| 声明 | 模板要求的 data availability/funding/COI/ethics 缺失 | — |
| 绝对化 | — | "证明/显著优于/proves" 附近无引用 |

`verdict=fail` 时 `emit` 会把 status 降为 `partial` 并写清 limits；**不要手工改回 ok**。
`emit` 遇到题面契约字段缺失会返回非零，`check` 会再次拦截。

## 输出契约（`result.json`）

题面 `output_contract` 优先；未提供时使用以下默认字段：

| 字段 | 类型 | 说明 |
|-|-|-|
| case_id | string | 原样回填 |
| status | enum | ok / partial / blocked / refused |
| artifact_path | string | 主产物相对路径，默认 `manuscript.md` |
| artifact_format | string | md/tex/docx |
| source_map | array | `[{claim,value,source_path,locator}]`，partial 时也保留已有映射 |
| changes | array | `[{target,type,before,after,reason}]` |
| uncertainty | array | 缺材料/不可核验/冲突等，无则 `[]` |
| limits | string | partial/blocked 时必填 |
| self_check | object | 至少含 `audit_verdict` 与各类计数 |
| conflicts | array | 已保留并登记的矛盾值 |
| todo | array | 待补/待核清单 |
| references | array | 文献条目 |
| figures / tables | array | 图表 label、caption、来源 |

## 失败与降级

| 情况 | 动作 |
|-|-|
| 找不到 `case.json` | `init` 返回 1；写 `status=blocked`、`limits="case.json not found"`，不要猜任务 |
| 材料目录为空 | `index` 返回 1；检查 `--materials` 或 `source_text`；`status=blocked` |
| PDF 无文本层 | `evidence.json.unreadable` 记录；只引用可读文本，图像内容标记 `unverifiable` |
| CSV 单元格为空 | `【待补：…】` + `uncertainty type=missing_material`，不得估算 |
| 两份材料数字冲突 | 保留两值 + `conflicts` + `uncertainty type=conflict`，不下结论 |
| 文献信息不全 | 只写已有字段；缺 DOI 标记未核验；不得生成 DOI |
| 任务要求超出材料 | 在 `limits` 说明；`status=partial`，不要虚构实验 |

## 最小调用示例（合成，非官方案例）

```text
/input/case.json          {"case_id":"demo","task":"Write Results","materials":["materials"]}
materials/exp.csv         group,n,degradation_pct\ncontrol,30,12.4\ntreated,30,21.7
materials/refs.bib        @article{smith2020,...}
```

`work/draft.json` 写一个 Results 段 + 两个 source_map 条目 + 一条文献；
依次执行上节 1–8 步，应得到：

- `work/manuscript.md`：`## Results`、正文含 `12.4`/`21.7`、`## References`；
- `work/audit.json`：`verdict=pass`（或仅 DOI/字数类 warning）；
- `/app/output/result.json`：契约字段齐全，`check` 输出 `PASS`。

## 已知边界

- 审计是离线的：不联网核对 DOI/作者，只做"能否在材料/文献表中解析"的检查；DOI 真实性仍需人工。
- 抽取质量取决于源文件：扫描 PDF、无表头的 CSV、合并单元格的 xlsx 可能只得到部分数值，需在 `limits` 说明。
- 不判断学科结论是否成立，只保证"写出来的每个事实都能回到材料，回不去的被显式标出"。
