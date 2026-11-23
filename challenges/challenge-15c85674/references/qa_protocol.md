# 问答方法说明 · 文献智能问答

## 1. 处理链路

1. 读 `/input/case.json`，取 `case_id` / `paper_id` / `material_version`、段落清单与问题清单。
2. 运行 `scripts/lane_qa.py`，得到 `/app/work/qa_context.json`：段落、问题、逐题候选。
3. 逐题判断候选段落是否**真的**回答该问题，剔除词面沾边但不相关的段落。
4. 写出 `answer` 与 `conditions[]`；把主要论断拆成 `claims[]`，每条带 `kind` 与 `evidence[]`（`paragraph_id` + 逐字 `quote`）。
5. 材料未覆盖的部分写进 `unanswered_parts[]` 并说明原因；整题无依据则 `status=insufficient_evidence`，条目仍保留。
6. 写 `coverage`：已读章节、未读章节及原因。
7. 运行 `scripts/qa_review.py` 独立复核，把 errors 清零。

## 2. 候选与结论的分工

`lane_qa.py` 做的是**词面检索**：它按问题与段落的词元重合度排序，并从命中的段落里挑一句逐字引文。它保证「引文逐字来自原文」，**不保证「这句真的回答了这个问题」**。

因此每个候选都带 `needs_review: true`：

- 候选成立 → 用它的 `paragraph_id` 与 `quote` 写证据
- 候选不成立 → 换候选，或如实判定材料不足
- 段落里根本没有 → 不许编，写进 `unanswered_parts[]`

## 3. 独立复核项

`qa_review.py` 检查 Q01–Q11：契约齐备、逐题覆盖、状态合法、答案非空、论断结构完整、段落可定位、引文逐字命中、未完成部分有原因、阅读范围已写、数值不越界、候选标记已清理。

## 4. 迁移

本链路与学科无关：换领域只需换 `resources/qa_lexicon.json` 的`domain_keywords` 与题面自带的问题清单，候选生成、证据绑定与复核规则保持不变。

## 5. 依赖

- Python 3 标准库，无第三方依赖，无网络请求。
- 不做 PDF 解析、图像识别、联网检索（题面明确不要求）。
