---
name: systematic-review-evidence
description: 执行冻结协议下的两阶段纳排、逐研究质量评价与计数闭合，并生成带精确来源的系统性综述成稿。
---

# 系统性文献综述

版本 1.0.0

## 三种请求与首要成品

- “按预设问题做系统综述” → 检索协议、两轮纳排、质量评价、流程计数和可读综合结论。
- “核对筛选记录能否复跑” → 每题录唯一去向、排除理由条款、未取全文清单和闭合检查。
- “没有可合并数据怎么办” → 按设计/对象/结局做有依据的叙述综合，说明不能合并的原因。

## 五个环节

1. 拆研究问题为对象、暴露/干预、比较、结局、设计（按领域使用PICO/PECO/SPIDER等适用框架）。协议逐条给纳排定义和优先顺序。检索式按数据库、字段、布尔/短语/截词写可执行版本，记录平台、日期、时间/语言范围和实际返回量。仅给定资料集时只承诺该集覆盖，外部检索未运行写not_run，保留可执行策略，不伪造结果数。
2. 用实际记录表冻结输入身份。逐条题录筛选，再对合格报告做全文筛选，排除附具体criterion和原文依据。相同材料不同记录的重复可留标识关系，不把缺全文等同不相关。记录是否单人筛选，若确有独立第二遍则保留两套判断和分歧裁决。
3. 纳入研究按设计选合适质量/偏倚维度，逐维给依据。例如随机研究关注分配、偏离、缺失、结局测量、选择报告；观察研究关注混杂、选择和测量。不能在缺完整量表时宣称完成官方RoB评分。不以“质量高”代替依据。
4. 将结局定义、时间点、对照、效应量、区间、样本单位和偏倚整理到矩阵。合并前检查独立性、同试验多报告、效应方向和尺度；同数据不可重复计权。不满足条件时做分组叙述综合，列每组证据与不确定性。若计算合并效应，保存输入、模型、方差与敏感性分析的实际复算，不虚构统计量。
5. 成稿交代问题/协议、检索与筛选、质量结果、主题/结局综合、冲突与证据空白。流程区分records、reports、studies，脚本flow统计的是records与纳入reports；独立studies数须基于实际study映射另核。流图中的每个数必须来自台账。

assemble 加 --systematic，将强制核对纳入报告有逐维质量依据。无候选或未得全文时交空证据综述与限制，不写普遍无效的结论。

## 验收

协议早于筛选且版本一致；逐记录去向与两阶段计数闭合；排除可回查；质量影响综述措辞；成稿实质主张只用纳入证据，空白限定在当前范围。

## 真实材料与执行

读完整 /input/case.json、task.md 和 environment/resources.yaml（存在时）。按实际研究问题、输入清单和 output_contract 工作。先写可操作的 protocol.json，再开始筛选，包含 case_id、question 和 criteria（条款ID→具体定义）；记录检索范围、语言/年份/全文限制、版本、改动原因。已有组织方协议优先，修改条件须留记录并重筛受影响条目。

先从题录/记录表整理 records.json，为对象数组，每条含 id、source_id 和实际给定的题名/作者/年份/DOI等元数据。source_id 是相对于真实材料目录的源文件路径。一个文件可能关联多个题录，不能把文件数当研究数；没有题录表时才省略 --records，明确以每文件一记录作为本地口径。元数据未知留空，不按文件名补科学事实。

```sh
python3 /skills/weekly-skill/scripts/synthesis.py prepare --input ACTUAL_CORPUS_DIR --protocol /app/work/protocol.json --records /app/work/records.json --out /app/work/review-sources
```

依赖 Python 3.10+ 标准库；PDF可用已有pdftotext，DOCX按段提取。source-index.md 包含原文和文件/物理页/段，sources.json冻结每份源哈希、协议哈希和全部记录。纯文本定位标 text/para，不假称印刷页。扫描、图表、复杂公式回原页，失败单列；必要时用现场OCR或数据工具恢复，保留原始页/文件关联。资源相对路径从清单目录解析。

根据下面本题流程填写 synthesis-template.json 为 /app/work/synthesis.json。所有实质论断是Agent读原文后的判断，附evidence数组，每条包括source_id、locator、quote、sha256，从sources.json取得实际定位和版本哈希。摘要、全文、题录的可得性分别记录。被排除/未取得材料不用于最终实质结论。

```sh
python3 /skills/weekly-skill/scripts/synthesis.py assemble --sources /app/work/review-sources/sources.json --work /app/work/synthesis.json --systematic --out /app/output
```

输出 review.md、evidence-matrix.json、flow.json、validation.json 和 result.json。字段 decisions 指向每条 record_id，题录判定 title_abstract=include/exclude/duplicate/pending；只有include再做全文判定fulltext=include/exclude/unretrieved/pending，其余用not_applicable。排除给协议criterion和reason，重复给duplicate_of且不能成环。缺全文不自动当不相关排除。

sections 是 heading/claims 数组，claim含text、kind=finding/comparison/inference/conflict及evidence。比较与冲突至少两份纳入来源。gaps区分 author_stated 与 corpus_bounded_inference 并绑定原文。limitations写有限材料、偏倚与未知。quality逐研究记录domain/judgment/basis/evidence，不能因正文出现p值就判高质量。

所有可读产物先落盘，核对validation再完善。脚本校验只支持字面证据/结构/计数，科学可比性由Agent核对。最终按现场output_contract调整全部字段、嵌套、枚举、指定文件名、case_id，保留sources、uncertainty、change_log和实际可读成稿。输出引用应指向存在的附件或原始材料，避免只交工作流。900秒/64次模型请求内留出定稿时间。

## 改动记录

1.0.0 新建专项成稿流程、协议/来源冻结、逐记录去向及证据矩阵。详细接口和边界见references/output-contract.md，完整合成示例见references/example-output.md。
