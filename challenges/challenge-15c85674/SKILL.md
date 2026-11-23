---
name: reading-02-literature-question-answering
description: Answer questions about a paper with per-claim evidence. Use for 文献智能问答 / literature QA: each answer carries the paper id, paragraph id and a short verbatim quote, distinguishes reported results from inference, and states which questions remain unanswered or lack evidence.
---

# 文献智能问答

## 用途与适用条件

让 Agent 在 3 个固定论文案例、9 个中文问题上完成“读取论文与问题 → 整合证据 → 逐题回答并标明依据”，每个主要论断都带论文标识、段落编号和短引文，可与原文一一核对。

**适用条件**：输入含案例与论文标识、材料版本、**带段落编号的段落清单**与问题清单。段落编号是原文既有编号，必须原样保留。

**不适用**：需要 PDF 版面还原、图像像素识别、联网检索或补充附件的场景。遇到这类输入按「异常处理」降级，不猜内容。

## 调用方式

```bash
python3 /skills/literature-qa/scripts/run_case.py --input /input --output /app/output --work /app/work
```

一键入口。它只做**机器该做的部分**：读 `/input` 的段落清单与问题清单，为每题检索候选段落、给出逐字句子引文，写出骨架 `result.json`；若检测到你已写入答案，会顺带跑一次独立复核。

**答案文本与结论必须由你逐题填写**——脚本只给候选，不下结论。

产物：

- `/app/work/qa_context.json` —— 段落清单、问题清单、逐题候选（你的工作底稿）
- `/app/output/result.json` —— 契约结果

填完答案后独立复核：

```bash
python3 /skills/literature-qa/scripts/qa_review.py --result /app/output/result.json \
    --context /app/work/qa_context.json --out /app/work/qa_review.json
```

## 输入

- `/input/case.json` —— 案例与论文标识（`case_id`/`paper_id`/`material_version`）、段落清单、任务说明、问题清单
- `/input/task.md` —— 题面

段落清单字段名随平台适配。脚本对多种形态做兼容发现（`paragraph_id`/`para_id`/`id` × `text`/`content`/`body`），但**引用时必须用材料里的真实段落编号**。

## 输出契约

`/app/output/result.json` 顶层字段：

| 字段 | 要求 |
|---|---|
| `case_id` / `paper_id` / `material_version` | 与本次输入一致 |
| `answers[]` | **每个问题一项**，不得省略无法回答的问题 |
| `coverage` | 已读章节、未读章节及原因 |
| `status` | `success` / `partial` / `failed` |
| `sources` / `uncertainty` / `change_log` | 来源定位、未决项、实际动作记录 |

每个 `answers[]` 元素：

| 字段 | 要求 |
|---|---|
| `question_id` | 与问题清单一致 |
| `answer` | 回答文本 |
| `conditions[]` | 成立条件：数值、单位、比较对象、实验条件、结论范围 |
| `status` | `answered` / `partial` / `insufficient_evidence` / `input_error` |
| `claims[]` | `claim_id`、`text`、`kind`、`evidence[]` |
| `evidence[]` | `paragraph_id` + 原文短引文 `quote` |
| `unanswered_parts[]` | 未回答部分及原因；没有则为空列表 |

`claims[].kind` 只取 `reported`（论文实测/原文报告）或 `inferred`（推断）。

### 证据规范

```
paragraph_id   材料中的真实段落编号，原样保留，不自造
quote          该段落的连续原文片段，逐字复制，不改写不省略
```

引文必须能被第二个人在原文里原样搜到。**引文存在不等于它支撑这条论断**——这层语义判定由你负责。

## 执行步骤

1. 运行 `run_case.py`，读 `/app/work/qa_context.json` 拿到段落与候选。
2. 逐题读候选段落，判断**哪一段真的回答了这个问题**；只看词面共现会选错段。
3. 写出 `answer`（回答完整才用 `answered`，部分则 `partial`），把数值、单位、比较对象、实验条件、结论范围放进 `conditions[]`。
4. 拆出主要论断写进 `claims[]`，每条带 `kind` 与 `evidence[]`；`quote` 从段落原文逐字复制。
5. 材料没写的部分写进 `unanswered_parts[]` 并给原因，整个问题都无依据则 `status=insufficient_evidence`，**仍然要保留这个 answer 条目**。
6. 写 `coverage`：已读哪些章节、未读哪些及原因。
7. 运行 `qa_review.py`，把 errors 清零再收工。

### 候选只是候选

`run_case.py` 给的 `candidates[]` 是**词面检索结果**，带 `needs_review: true`。它保证「引文逐字来自原文」，**不保证「这句真的回答了这个问题」**。候选不成立时不要硬套；材料确实没写就如实说材料不足。

## 异常处理

| 情形 | 处理 |
|---|---|
| 材料未报告该内容 | 写进 `unanswered_parts[]`，说明「材料未报告」 |
| 只能部分回答 | `status=partial`，列出缺口 |
| 原文互斥表述 | 两处都给出证据，并在答案中指出冲突 |
| 输入读取失败 | `status=input_error`，写明失败原因 |
| 全文无依据 | `status=insufficient_evidence`，答案文本说明无法确定 |

**有依据地说明「材料未报告」也是有效回答。**编造答案或引用是本题最严重的失分点，检出即相关项记 0 分。

## 自查方法

`qa_review.py` 会检查：契约齐备、**每题都有回答项**、状态合法、论断结构完整、段落编号可定位、引文逐字命中该段原文、未完成部分有原因、阅读范围已写。

完整清单见 `/skills/literature-qa/references/qa_protocol.md`。

## 限制与依赖

- Python 3 标准库，无第三方依赖，无网络请求。
- 只读材料，不做 PDF 解析、图像识别、联网检索。
- 语义等价性脚本无法判定：脚本保证「有据可查」，答案对错由你逐条负责。

