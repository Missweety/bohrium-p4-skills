---
name: citation-fact-audit
description: 逐条核验论文事实与引用支持，绑定稿件和来源原句、版本与页段定位，生成有严重度及修订建议的审查报告。
---

# 引用与事实核验

版本 1.2.0

## 三种调用请求

- “核对稿件里数值和引用” → 双侧证据、数值与单位对照、问题清单。
- “这条引用支持因果结论吗” → 拆分论断，核对原研究设计和适用对象，给支持程度与修改句。
- “来源拿不到，能先审吗” → 交可核部分、缺材料清单及待核边界。

输入为稿件与可取得的引用原文、元数据或数据库记录。输出直接给逐项审查单，示例是“稿件称干预导致改善；被引文献为横断观察。建议改为关联表述并列明证据条件”。

## 核验次序与误报控制

1. 先通读真实全文与图表，拆出原子论断。每条记录对象/干预或暴露/比较/结局/方向/幅度/时间/适用范围及所引编号。保留原句与句内位置。用 citation ledger 记录哪些已核、缺原文、未查，避免只查摘要。
2. 用正文引用、文末书目和原始文件绑定被引条目。DOI、题名、作者、年份逐字核对；唯一 DOI 不证明当前作者题名正确。材料有多个版本时列版本日期和差异。网络可用且任务许可时查询出版商、更正或撤稿权威记录并保存访问日期与结果。查不到状态写未核验。
3. 将稿件句与所引来源中的真实主张逐分句比较。全文、摘要、题名的证据粒度分别记录。来源支持对象但未支持数字、因果或外推条件时是 partial_support。已有明确相反证据才判 unsupported；缺全文用 unable_to_determine。unsupported/partial_support 必须提供稿件与被引来源两侧证据，修订建议给出不超出原文的新句。
4. 做摘要—正文—图注—表格的数字对照，统一单位前保留原单位。相同数字但分母、亚组、时间点不同不判冲突。样本量、效应量、区间、显著性分别核对，不用关键词相似度代替语义支持。
5. 对方法、逻辑、规范补六类覆盖记录。缺声明只报报告缺失，不能推定伦理违规、造假或未开展实验。保留已支持的论断作为误报控制检查。

## 验收

- 每个关键结论回到原稿原句及被引来源的具体段/图表。
- 支持程度、问题类型和严重度分别给出，建议含可直接编辑的修订句。
- 文献版本、来源可用性及未完成检查有记录。

## 执行与交付

Python 3.10+，无必装 Python 第三方包。PDF 文本抽取使用已有 pdftotext，DOCX 用标准库，扫描页按现场工具渲染或 OCR 并核对数字。依赖不可用时记录具体文件、页和限制。读完整 /input/case.json、任务和 environment/resources.yaml（存在时），从实际声明找到稿件、被引原文、补充材料和数据。清单相对路径从清单目录解析。正式案例只在运行时取得。

用实际材料目录生成证据索引与待填审查单。初次命令产出的是输入证据和检查模板，随后由 Agent 阅读原文并写出本题科学判断。`prepare` 已按真实段落自动预填三类候选，一律标注“需语义确认”，Agent 必须保留、修正或说明不采纳的理由，不能把候选数量当作结论数量：

- 引用类：正文 [n] 缺失对应书目条目、或完全无可解析书目。
- 数值类：同段自称显著但 p≥0.05；同一来源出现多个样本量 n；同段互斥百分比合计超过 100%。
- 来源类：出现撤稿、勘误/更正或预印本标识，需核对出版状态与版本差异。

```sh
python3 /skills/weekly-skill/scripts/audit.py prepare --input /input --out /app/work/audit
# 阅读 source-index.md 与原图，核对自动候选，填写 review-template.json 为 /app/work/reviewed.json
python3 /skills/weekly-skill/scripts/audit.py render --evidence /app/work/audit/evidence.json --review /app/work/reviewed.json --out /app/output
python3 /skills/weekly-skill/scripts/audit.py selfcheck --result /app/output/result.json --case /input/case.json --evidence /app/work/audit/evidence.json --out /app/work
```

`selfcheck` 核验三件事：`result.json` 是否满足当前 `case.json` 的 `output_contract` 必填字段、每条 finding 的引文是否仍逐字存在于所引段落、六个 facet 是否都有覆盖记录；不通过时退出码为 1 并逐条列出原因。

交付前做完整性自检：六个 facet 都要有 `checked`（带真实证据）或写明原因的 `not_checked` / `not_applicable` / `unable_to_determine`；每条 finding 的 quote 必须逐字出现在所引段落；`validation.json` 的 rejected 要逐条修正后再交。若案例材料只有摘要或缺正文，明确写缺哪一文件、哪一页，不能把未读内容标成 checked。

每条 findings 包含 id、facet、judgment、severity、basis、action 和 evidence。每项证据包括 source_id、locator、quote、sha256，直接从 evidence.json 复制定位和哈希，摘录实际原文。quote 必须来自该文件该段，改变材料后重新建索引。judgment 可为 confirmed_error、evidence_gap、recommendation、supported、partial_support、unsupported、unable_to_determine；严重度 major/minor/informational。重要结论缺证据或影响核心结果为 major，局部可修报告问题为 minor，建议为 informational。具体解释后果，避免仅靠关键词或未发现某词就推定研究未执行该步骤。

checks 逐项覆盖 facts、citation_support、methods、statistics、logic、academic_norms。完成项用 checked 并带真实证据，not_applicable 写适用性原因；未读、资料缺失和无法判断分别用 not_checked 或 unable_to_determine 并说明。找不到问题时可 findings=[]，同时交有依据的检查覆盖记录。

第一成品为 /app/output/review-report.md 的可交办审查报告，并保存结构化 result.json 和实际引用的附件。核对 validation.json 的拒绝条目，修正来源绑定后再交。脚本原生 JSON 是通用审查格式；按当前 output_contract 调整所有字段、嵌套、枚举、指定文件名和 case_id，保留真实来源、状态、不确定性及修改记录。先保存诚实的部分结果，在 900 秒/64 请求内留时间完成成稿。遇到无正文、坏文件、缺引文或网络失败，用真实失败与待核项落盘。

references/output-contract.md 说明接口；references/example-output.md 给出合成示例，SMOKE.md 是已执行的本地回归。

## 改动记录

1.0.0 新建专项审查流程、双侧证据绑定、可读报告及异常回归。
1.1.0 增加基于真实段落的引用候选预填（缺书目/缺编号），并在 SKILL 中固化六 facet 完整性与逐字引用自检，降低“输出不完整”的风险；不改变人工语义判定边界。
1.2.0 增加数值一致性候选（显著性阈值、样本量冲突、互斥百分比超 100%）与来源状态候选（撤稿/勘误/预印本），新增 `selfcheck` 子命令按运行时 `output_contract`、逐字引文与六 facet 覆盖做交付前校验；所有自动候选仅作定位提示，语义判定仍由 Agent 完成。
