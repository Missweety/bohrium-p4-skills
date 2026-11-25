# 图谱构建协议（可逐条复核）

本文件说明 `scripts/graph_build.py` 的实际处理顺序。所有步骤都可用输出文件复核，
不含需要联网或需要外部模型的隐式步骤。

## 1. 读取与论文身份

1. 先读 `corpus-manifest.json`，得到每篇论文的 `source_id`、`doi`、`title`、`authors`、
   `license`、`file`，顺序即论文顺序。
2. 再读除 `case.json`/`task.md`/`corpus-manifest.json` 之外的 JSON：
   - 列表或 `paragraphs/passages/blocks/items/sections/materials/data` 数组 → 段落；
   - 段落自带 `doi`/`source_id`/`paper` 时**按该字段分组**，避免把两篇合成一篇；
   - `{id: text}` 形式按段落处理。
3. 用 DOI、文件名或段落内 DOI 文本把文档对到 manifest 条目；对不上的材料保留中性
   `source_id` 并写 warning，**不借用其他论文的 DOI/title**。
4. 文本文件（Markdown/TXT）只在没有任何 JSON 段落时启用。

## 2. 同篇去重

对每两篇文档计算段落签名集合（每段前 300 字符、小写、去空白），
`重叠数 / 较小集合大小 ≥ 0.6` 判为同一篇论文的另一种格式或汇总索引：

- 保留段落更多的一份，另一份只贡献 `formats`；
- 记录“已合并，未当作两篇跨篇证据”；
- 典型场景：`material.json` 汇总索引 vs `primary-material.json` / `secondary-material.json`。

## 3. 实体候选

逐句（`。！？` 与 `.?!` 切分，长度 ≥15）匹配：

| 来源 | 正则/线索 | 类型倾向 |
| --- | --- | --- |
| 大写短语 | 连续大写词（≤4 个词） | 按后缀判定 method/material/metric/dataset |
| 类型后缀 | model、method、analysis、capacity、spectroscopy… | 对应类型 |
| 介词短语 | `of/than + 小写短语` | concept |
| 线索词 | using / based on / compared with / adsorption of / 采用 / 基于 | concept |
| 材料线索 | `on/onto/into/with + 名词` | material |
| 数值条件 | `pH 7`、`25 C`、`0.5 h`、`50 min` | condition |

过滤：停用词、>5 词、纯缩写、词内停用词（`at/in/on/with…`）、
`mg/%/mmol` 测量值、同句中被更长标签包含的短标签（`Langmuir` vs `Langmuir model`）。

## 4. 边

- 只对同句内 ≥2 个节点建边；
- 谓词仅两类显式关系：`compared_with`（compared with/to、versus、higher/lower than、相比、高于、低于）、
  `based_on`（based on、derived from、trained on、基于、根据）；
- 其余一律 `co_occurs`，**不把共现升级为使用、因果或支持关系**；
- 同一 (source, target, predicate, paragraph) 去重。

## 5. 跨篇对齐

- 归一化：小写、去标点、去除复数词尾 `s`；
- 同一规范化标签出现于不同论文 → `alias_candidates` 中 `not_merged`，
  理由写明“实验对象/条件可能不同”；
- 同篇重复标签才允许 `merged`；
- 审计禁止 `sources` 长度 >1 的 `merged` 决策。

## 6. 四类查询

| ID | 实现 | 空结果处理 |
| --- | --- | --- |
| Q1 | 统计节点度（边数），降序取前 5 | `no_hit` + 图为空原因 |
| Q2 | 按 `normalized` 分组，找跨 `source_id` 出现的标签 | 单篇/无同名时 `no_hit` + 原因 |
| Q3 | 列出 `type=condition` 节点 | 无条件表达时 `no_hit` |
| Q4 | 全语料扫描“指标 + 数值 + 单位”，同指标跨论文不同值 | 无冲突时 `no_hit` + 可比较篇数 |

冲突检查扫描原始段落而不是只扫描节点，避免漏检未被抽成节点的指标。

## 7. 完整性

| 检查 | 是否 blocking | 说明 |
| --- | --- | --- |
| `dangling_edges` | 是 | 边端点必须存在于 nodes |
| `duplicate_paragraph_ids` | 是 | 同篇同 ID 但正文不同 |
| `nodes_without_quote` | 是 | 节点必须有逐字引文 |
| `orphan_nodes` | 否 | 孤立点如实报告，不删除 |

## 8. 独立审计

`scripts/audit_result.py` 在独立进程运行，重新读取 `/input` 语料，检查：

- 契约字段齐全；
- 节点 ID 唯一、`source_id` 存在、引文逐字可检索、锚点可解析；
- 边端点存在、谓词非空、引文逐字；
- ≥3 条查询已执行，且有结果、答案；证据或 `no_hit`+`empty_reason` 二选一；
- 别名决策合法、无跨文献合并；
- `metrics.nodes`/`metrics.edges` 与实际长度一致；
- 完整性无 blocking。

审计不通过 → 运行器降级 `status` 并记录错误数，不隐藏问题。

## 9. 资源边界

本包不读取 PDF 像素、图片、补充附件或底层实验数据；材料只按文本段落处理。
正文行内公式/上下标可能被线性化，保留原始 XML 供人工核对，但不据此推断数值。
