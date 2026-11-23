---
name: literature-synthesis-grounded
description: 在真实多文献集上先筛选再归纳证据主题，完成有逐条来源的综述正文、比较矩阵和有边界的研究空白。
---

# 文献综述生成

版本 1.0.0

## 三种请求与首要成品

- “用给定文献写可讨论的综述” → 有主题论证的综述成稿、文献/纳排表和证据矩阵。
- “不同研究为什么结论不一致” → 同一比较维度下并列方法条件与相反证据，说明可比性限制。
- “找本组文献支持的研究空白” → 原作者局限与当前证据集缺口分别列证据和范围。

## 从证据到综述

1. 依据研究问题定义对象、方法、结局及范围。逐条筛选保留理由，准确区分书目记录、报告与独立研究。相同题录/同一PDF别名可去重，预印本/正式版或同试验不同报告保留关系，不静默合并。
2. 对纳入文献建立实际证据行，含问题设置、研究对象/条件、设计、方法路线、样本量、结局/单位、结果、限制和原文位置。未报告字段标明，避免用关键词或篇幅估证据质量。
3. 从这些差异形成有解释力的主题。每个主题写连接性段落，明确不同研究在同一维度的取舍。先写主题判断，再给支撑和反面材料、适用条件及过渡。避免逐篇摘要拼接。
4. 相反方向先核对测量指标、实验条件、对象和时间窗；同一对象同一量仍冲突才称结论分歧。异条件分别解释，不能用一篇显著、一篇不显著直接证明结果不同。
5. 综述结构包含问题与范围、主题比较、冲突/互补证据、研究空白和限制。结论用“在本组材料中”限定范围，给能推进讨论的具体下一步，不声称全球首创。所有数字、术语和实质比较均绑定来源。

## 验收

成稿可直接阅读；所有记录筛选去向完整；主题来自实际证据；主张有原文支撑；负面材料和不确定性保留。

## 真实材料与执行

读完整 /input/case.json、task.md 和 environment/resources.yaml（存在时）。按实际研究问题、输入清单和 output_contract 工作。先写可操作的 protocol.json，再开始筛选，包含 case_id、question 和 criteria（条款ID→具体定义）；记录检索范围、语言/年份/全文限制、版本、改动原因。已有组织方协议优先，修改条件须留记录并重筛受影响条目。

先从题录/记录表整理 records.json，为对象数组，每条含 id、source_id 和实际给定的题名/作者/年份/DOI等元数据。source_id 是相对于真实材料目录的源文件路径。一个文件可能关联多个题录，不能把文件数当研究数；没有题录表时才省略 --records，明确以每文件一记录作为本地口径。元数据未知留空，不按文件名补科学事实。

```sh
python3 /skills/weekly-skill/scripts/synthesis.py prepare --input ACTUAL_CORPUS_DIR --protocol /app/work/protocol.json --records /app/work/records.json --out /app/work/review-sources
```

依赖 Python 3.10+ 标准库；PDF可用已有pdftotext，DOCX按段提取。source-index.md 包含原文和文件/物理页/段，sources.json冻结每份源哈希、协议哈希和全部记录。纯文本定位标 text/para，不假称印刷页。扫描、图表、复杂公式回原页，失败单列；必要时用现场OCR或数据工具恢复，保留原始页/文件关联。资源相对路径从清单目录解析。

根据下面本题流程填写 synthesis-template.json 为 /app/work/synthesis.json。所有实质论断是Agent读原文后的判断，附evidence数组，每条包括source_id、locator、quote、sha256，从sources.json取得实际定位和版本哈希。摘要、全文、题录的可得性分别记录。被排除/未取得材料不用于最终实质结论。

```sh
python3 /skills/weekly-skill/scripts/synthesis.py assemble --sources /app/work/review-sources/sources.json --work /app/work/synthesis.json  --out /app/output
```

输出 review.md、evidence-matrix.json、flow.json、validation.json 和 result.json。字段 decisions 指向每条 record_id，题录判定 title_abstract=include/exclude/duplicate/pending；只有include再做全文判定fulltext=include/exclude/unretrieved/pending，其余用not_applicable。排除给协议criterion和reason，重复给duplicate_of且不能成环。缺全文不自动当不相关排除。

sections 是 heading/claims 数组，claim含text、kind=finding/comparison/inference/conflict及evidence。比较与冲突至少两份纳入来源。gaps区分 author_stated 与 corpus_bounded_inference 并绑定原文。limitations写有限材料、偏倚与未知。quality逐研究记录domain/judgment/basis/evidence，不能因正文出现p值就判高质量。

所有可读产物先落盘，核对validation再完善。脚本校验只支持字面证据/结构/计数，科学可比性由Agent核对。最终按现场output_contract调整全部字段、嵌套、枚举、指定文件名、case_id，保留sources、uncertainty、change_log和实际可读成稿。输出引用应指向存在的附件或原始材料，避免只交工作流。900秒/64次模型请求内留出定稿时间。

## 改动记录

1.0.0 新建专项成稿流程、协议/来源冻结、逐记录去向及证据矩阵。详细接口和边界见references/output-contract.md，完整合成示例见references/example-output.md。
