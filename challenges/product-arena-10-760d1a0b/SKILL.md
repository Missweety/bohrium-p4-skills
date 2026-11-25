---
name: literature-knowledge-graph
description: 从两篇（或多篇）论文材料抽取带原文证据的实体与关系，保留每篇独立 source_id、段落锚点与逐字引文；跨篇同名标签默认不合并并记录合并依据，实际执行度排序、跨篇同名、条件清单、数值冲突四类查询，并输出完整性检查。适用于文献知识图谱、实体关系抽取、跨篇对齐与证据绑定类任务。
---

# 文献知识图谱构建（literature-knowledge-graph）

本 Skill 把一批论文材料变成**可回查的节点与边**，并对它真实执行查询。
判断标准只有一条：每个节点、每条边、每个查询答案，都能回到某一篇论文的具体段落和原文片段。

## 何时使用

- 任务要求“从论文抽取实体/关系，绑定证据，支持查询”。
- 输入包含两篇及以上论文正文（JSON 段落索引、JATS/Markdown/TXT），或一篇论文的多种文件格式。
- 需要记录跨篇同名概念的合并/不合并依据，而不是直接合并成一个节点。

不适用：需要图像像素、补充附件或底层临床/实验数据的任务（本包不推断这些内容）；
需要联网抓取论文的任务。

## 一键运行

脚本不依赖工作目录，任意 cwd 均可运行；默认路径与平台一致：

```bash
python3 scripts/run_case.py
python3 scripts/run_case.py --input /input --work /app/work --output /app/output
```

可选 `--case <case.json>` 指定案例文件。退出码恒为 0（参数错误除外）：
材料缺失、JSON 损坏也会写出降级 `result.json`，原因写入 `limits` / `uncertainty`。

产物：

| 路径 | 内容 |
| --- | --- |
| `/app/output/result.json` | 契约全字段结果 + metrics + conflicts + audit |
| `/app/output/knowledge_graph.json` | 图谱导出（docs/nodes/edges/alias_candidates） |
| `/app/output/nodes.csv` | 节点表（含 paragraph_id、quote） |
| `/app/output/edges.csv` | 边表（含 predicate、paragraph_id、quote） |
| `/app/work/graph.json` | 构建中间结构（含完整性检查） |
| `/app/work/audit.json` | 独立进程复核报告 |

## 输入约定

- `/input/case.json`：`case_id`、`output_contract`（支持 list / `{"fields":[...]}` / `{"required":[...]}`）。
- `/input/corpus-manifest.json`（推荐）：逐篇列出 `doi`、`title`、`authors`、`license`、
  `source_id`/`file`。**根级 DOI/title 只属于第一篇，绝不套到第二篇。**
- 论文正文：`material.json`（两篇段落的汇总索引，段落可带 `doi`/`source_id`）、
  `primary-material.json`、`secondary-material.json`，或任意含段落数组的 JSON。
  段落字段支持 `text`/`content`/`paragraph`/`body`，锚点支持 `paragraph_id`/`pid`/`id`。
- 也兼容 Markdown/TXT（仅在没有任何 JSON 段落时启用）。
- 同一篇论文的多种格式/汇总索引会按段落内容去重合并，**不当作跨篇证据**；
  合并记录写入 `notes` 与 `change_log`。

段落锚点：沿用材料真实 `paragraph_id`（JATS 用 `<p id>`）。本包不提供 PDF 页码，
不把自建页序称原 PDF 页。

## 图谱规则

| 规则 | 行为 |
| --- | --- |
| 节点范围 | 材料中真实出现的实体短语（材料、方法、指标、概念、数值条件）；不凭常识补全 |
| 数值节点 | `210 mg/g` 这类测量值不作为实体节点，只保留在边/查询的原文引文里 |
| 边 | 只建同句共现或原文明确关系（`compared_with`、`based_on`），其余为 `co_occurs` |
| 跨篇同名 | 默认 `not_merged`，`alias_decisions` 写明理由；跨文献合并被审计禁止 |
| 证据 | 每个节点/边带 `source_id` + `paragraph_id` + 逐字 `quote` |
| 完整性 | 悬空边、重复段落 ID、无引文节点为 blocking；孤立点只报告不隐藏 |

## 实际执行的查询（≥3）

| ID | 类型 | 内容 |
| --- | --- | --- |
| Q1 | `degree_ranking` | 单篇内度最高的实体（不跨篇合并） |
| Q2 | `cross_source_shared_labels` | 两篇中规范化后相同的标签，以及是否合并 |
| Q3 | `condition_listing` | 各篇报告的 pH/温度/时间/容量等条件 |
| Q4 | `conflict_check` | 跨篇同名指标的不同取值；只报告，不合成结论 |

查询结果为空时写 `no_hit=true` + `empty_reason`，不伪造引文；审计接受这种诚实空结果。
单篇输入时 `status=partial`，明确“不假装做了双篇对照”。

## 状态词表

| status | 含义 |
| --- | --- |
| `success` | ≥2 篇有效材料、≥3 条查询执行、完整性无 blocking、审计通过 |
| `partial` | 单篇材料 / 查询不足 / 完整性或审计有问题；`limits` 说明原因 |
| `blocked` | 没有任何可读段落，未构建图谱，未编造节点 |
| `failed` | 运行器内部异常；仍写出降级 `result.json` |

## 异常处理

| 情况 | 行为 |
| --- | --- |
| 缺少 corpus-manifest | 用文件名/段落自带 id 作 source_id，并提示无法核对 DOI 归属 |
| 只有一篇材料 | `partial`，跨篇查询如实为空 |
| material.json 与 primary/secondary 重复 | 按内容去重，保留段落更全的一份，记录合并 |
| JSON 无法解析 | 跳过该文件并记录 warning，不中断其他材料 |
| case.json 非法 | 回退默认契约，`partial`，`limits` 说明 |
| 查询无结果 | `no_hit` + `empty_reason`，不补造证据 |

## 自检

```bash
python3 scripts/audit_result.py --result /app/output/result.json \
  --graph /app/work/graph.json --input /input --case /input/case.json
```

审计独立重载语料，逐条检查：契约字段、节点 ID 唯一、source/引文、引文逐字性、
边端点、查询执行与证据、别名决策（禁止跨文献合并）、metrics 计数、完整性 blocking。
不通过时运行器把 `status` 从 `success` 降为 `partial`。

字段与状态细节见 `references/output-contract.md`，构建规则见 `references/graph-protocol.md`。
示例见 `examples/`（合成数据，非正式案例）。
