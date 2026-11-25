---
name: thesis-consistency-auditor
description: 面向学位论文/长篇综述的跨章节一致性巡检与可定位修订。真实解析 DOCX（含表格单元格、样式与编号），抽取术语、符号、章节/图表/公式编号、正文引用与参考文献表，产出带“段落号+句号+逐字引文”的不一致清单，并只对排版级/工单显式术语做最小侵入修订，交付可继续编辑的 docx、Markdown、diff、CSV 与预览。
version: 3.0.0
license: MIT
---

# 学位论文长文档一致性：先定位，再最小修订

把"检查长文档一致性"拆成 **读稿建模 → 七族巡检 → 可定位清单 → 最小侵入修订 → 独立复核 → 预览**。

一条检查的价值 = 能否指到 `段号 + 句号 + 逐字引文`；
一条修订的价值 = 作者能否逐条接受/拒绝，且**未被命中的段落逐字未变**。
**不改事实与数值，不做整段重写，语义级问题只报不改。**

## 平台路径（务必按此执行）

本 Skill 评测时安装在 `/skills/weekly-skill`，工作目录通常是 `/app`，**两者不同**。
脚本一律用绝对路径调用，不依赖当前目录：

```bash
SKILL_DIR=/skills/weekly-skill          # 若你确实在 skill 目录内，可写 SKILL_DIR=.
python3 "$SKILL_DIR/scripts/run_case.py" --input /input --work /app/work --out /app/output
python3 "$SKILL_DIR/scripts/run_case.py" --check /app/output      # 交付前自检
```

## 何时使用

触发（满足任一）：

- 用户给出**分章或多文件的学位论文 / 长篇综述**，要求检查术语、符号、编号、图表引用、参考文献是否一致；
- 要求"帮我找出前后矛盾/图表编号乱/引用对不上"，并希望得到能逐条定位的清单；
- 要求在不破坏原格式的前提下产出**修订稿**（docx 可继续编辑），并保留修改记录。

不触发：单句润色/摘要生成；需要联网查文献真伪；要求补写整章或生成实验数据；
纯 PDF 扫描件（无文本层）要求"自动校对"（会如实降级为不可读，不猜测内容）。

## 主流程：一条命令保证完整交付

`run_case.py` 依次执行，**任何一步失败都继续落盘**：

1. **输入发现**：读 `case.json`（`materials/chapters/files` 等键）、`task.md`、
   `organizer-edit-workorder.json`；`materials` 缺失时递归扫描 `/input` 下的
   `.docx/.md/.txt/.pdf`；按工单 `chapter_order` 或自然序稳定排序（重名文件用相对路径区分）；
2. **抽取**：docx 走真实 OOXML 解析（`word/document.xml` + `styles.xml` + `numbering.xml`，
   表格单元格段落单独编号）；md/txt 按 UTF-8 → GB18030 → UTF-16 严格解码后转为 docx 再解析，
   发生编码回退会写入 `sources[].encoding` 与 `uncertainty`；pdf 走 `pdftotext`，无文本层如实报错；
3. **合并**：多份来源按原顺序合并为单一 docx（表格保持原位置），每个 block 记录来源文件，
   重建后回填到段落，使 `location.source_path` 指回原章节；并在 `limits` 声明格式损失；
4. **七族巡检**（见 `references/consistency-rules.md`）：terminology / symbol / definition /
   numbering / reference / citation / conclusion；
5. **修订**：先执行工单 `find/replace` 形式的显式改稿目标（逐条回报 `applied/not_found`），
   再对 `auto_fixable` 条目（拉丁术语变体升格、工单显式术语）在原地改命中 run；
   同段同词同目标的重复命中只执行一次并记入 `deduped_edits`，不再静默丢弃；
6. **独立复核**：重新打开产物，校验可解析、段落数不变、未命中段落逐字未变、每处编辑确实落地；
   并输出 `edit_impact`：同一旧写法还残留在哪些段落（供作者继续跟进）；
7. **预览**：优先 `soffice --headless` 转 PDF 并校验 `%PDF` 与页对象；失败则写 `preview.html` 并记录原因；
8. **交付**：写 `result.json` / `revision.docx` / `revision.md` / `revision.diff` /
   `inconsistencies.csv` / `consistency_report.md` / 预览。

退出码 0 = 已写出结构完整且诚实的交付物（`success` / `partial` / `failed` 都写全并说明原因）。

## 输出契约

`result.json` 必须包含 `case.json` 中 `output_contract` 声明的**全部**字段，外加
`case_id / status / sources / uncertainty / change_log`。字段语义与别名映射见
`references/output-contract.md`（本 Skill 不硬编码字段名，未知字段保留 `null` 并记入 `contract_gaps`）。

| 产物 | 内容 |
|-|-|
| `revision.docx` | 修订稿；单 docx 输入时原位只改命中 run，不重建段落、不丢 rPr/表格/页眉页脚 |
| `revision.md` | 同一稿的 Markdown 版（便于人读与 diff） |
| `revision.diff` | 逐行差异 |
| `inconsistencies.csv` | 可逐条复核：id / rule / 位置 / 逐字引文 / 建议 / 是否自动可修 |
| `consistency_report.md` | 人读版报告：覆盖、清单、已自动修订、来源 |
| `preview.pdf` 或 `preview.html` | 真实渲染预览（无渲染器则如实记录原因） |
| `work/doc.json` | 段落模型（段号/章节/样式/表格标记/文本） |
| `work/findings.json` | 全部检查结果与覆盖统计 |
| `work/self_check.json` | 自检结果（原样写入 `result.json.self_check`） |

### 定位规范（第二个人能独立抽查）

```
P0001            文档顺序第 1 个段落（1-based，含表格单元格段落）
§2.1             所属章节键（无编号时为 §A/§B…）
sent.3           该段第 3 句
char_start/end   段落可见文本偏移（可见文本 = w:t，w:tab→\t，w:br→\n，跳过 w:del）
anchor_quote     必须能在原稿该段逐字找到的引文
```

## 状态语义（诚实降级）

| status | 何时 |
|-|-|
| `success` | 单一可编辑 docx、无不可读材料、无跳过修订、预览成功 |
| `partial` | 有多源合并重建 / 部分材料不可读 / 有修订被跳过 / 预览不可用 / 工单语义型指令未落地 —— 均已在 `limits` 与 `uncertainty` 说明 |
| `failed` | 没有任何可读材料：仍写全 `result.json` 与逐文件失败原因，不猜测内容 |

`partial` / `failed` 不是错误，而是**如实上报**；严禁把未检查的检查族写成"无问题"。
`coverage` 七族逐项写 `checked/findings` 与关键统计。

## 硬性禁止

- 不输出整篇重写稿代替原稿；不把"改后全文"当交付物。
- 不新增/删除/修改任何数值、单位、样本量、图表编号、参考文献条目或实验条件。
- 不虚构缺陷：每条 finding 必须有 `paragraph_id + anchor_quote + why`，找不到原文依据就不写。
- 不把"未检出"说成"不存在"；不把"跨章节结论相反候选"直接判定谁对谁错。
- 不在产物中写入个人绝对路径、账号或 token。

## 异常与降级

| 情况 | 处理（已内置于 run_case） |
|-|-|
| `.doc`/RTF 伪装成 docx / zip 损坏 | 记 `unreadable` 与原因（只保留文件名，不写绝对路径），继续处理其余材料；全部不可读则 `failed` |
| md/txt 非 UTF-8（如 GBK） | 依次尝试 UTF-8/GB18030/UTF-16；回退时写 `sources[].encoding` 与 `uncertainty`，不静默产出空串/乱码 |
| case.json 未声明 `output_contract` | 仍按内置字段集输出，`self_check.contract_declared=false`，并在 `uncertainty`/`limits` 说明无法核对字段清单 |
| PDF 无文本层 | 如实报"需要 OCR"，不根据图注猜测正文 |
| 多份 md 合并 | 重建为单一 docx，保留标题层级/正文/表格顺序；`limits` 声明不保留分页/页眉页脚 |
| 多个来源同名（如两处 chapter1.md） | 用相对路径作为来源标识，finding 仍能指回具体文件 |
| 无标题/编号混乱 | 按段落聚类生成 `§A/§B`，诊断降为段落级 |
| 符号定义位于表格单元格 | 用单元格段落号回填锚点，仍可逐字复核 |
| 工单含 `find/replace`（或 old/new、before/after）目标 | 机械执行，逐条记 `workorder_execution`：`applied`（含段落/章节/出现次数）或 `not_found`（含检索范围），不做模糊匹配 |
| 工单语义型指令（如"改写这段更严谨"） | 不自动改写，列入 `uncertainty`，交由模型/人工 |
| 无 LibreOffice | 不谎报 PDF；写 `preview.html` 并在 `limits` 说明 |
| 自动修订定位不到原文 | 记入 `skipped_edits`，不影响其余交付 |

## 文件说明

- `scripts/run_case.py`：一条命令端到端（发现→抽取→合并→巡检→修订→复核→预览→交付）与 `--check`。
- `scripts/docx_io.py`：纯标准库 OOXML 读写；`load_docx / patch_paragraph / save_docx / build_docx / docx_text / docx_info`。
- `scripts/locate.py`：章节树、句级切分、题注与编号定位。
- `scripts/consistency.py`：七族一致性规则（每条都返回可复核锚点与覆盖统计）。
- `scripts/revise.py`：自动修订边界、原地替换、独立复核、Markdown 与 diff 渲染。
- `scripts/preview.py`：LibreOffice 转 PDF + 校验；失败降级 HTML。
- `references/output-contract.md`：契约字段、别名映射、状态与自检口径。
- `references/consistency-rules.md`：七族规则表、判定信号、自动修边界与反例。

## 最小示例

见 `examples/README.md`：`examples/synthetic_case/` 为**合成演示**（SYNTHETIC，非正式案例），
含 3 章 md + 工单（术语表、语义型指令、1 条 find/replace 目标），可复现七族检查与 3 处自动修订。

## 改动记录

### 3.0.0（2026-11-25）

- 修复：md/txt 非 UTF-8 时旧版 `read_text` 吞掉解码异常返回空串，导致 GBK 材料被误报
  "PDF 无可提取文本层"；现按 UTF-8→GB18030→UTF-16 严格解码，回退写入 `sources[].encoding`
  与 `uncertainty`。
- 新增：解析并机械执行工单 `find/old/before + replace/new/after` 形式的显式改稿目标，
  `result.json.workorder_execution` 逐条回报 `applied`（段落/章节/次数）或 `not_found`（检索范围）。
  旧版会把这类 dict 当成自然语言指令，命中 `find` 字段后整条落入"语义型未落地"，目标从未执行。
- 修复：同段同词同目标被多条规则命中时，旧版第二处被 `taken` 静默跳过、无任何记录；
  现记入 `deduped_edits`。
- 修复：多源合并后 `location.source_path` 一律为 `merged_base`，无法指回原章节；
  现按 block 回填来源，同名文件用相对路径区分。
- 修复：产物中写入运行环境绝对路径（`preview.pdf`、workorder 路径、错误信息）；
  现统一为文件名/相对路径，错误信息经 `scrub_paths` 处理。
- 修复：公式断号/编号重复的 `anchor_quote` 在编号为全角括号时退回段首 6 字（与结论不符）；
  现锚点直接取编号本身。
- 新增：`edit_impact` 列出"改了这处后同一旧写法还残留在哪些段落"，便于作者继续跟进。
- 新增：`self_check.contract_declared`；case.json 未声明 `output_contract` 时在
  `uncertainty/limits` 明示无法核对字段清单。
- 打包：移除 `__pycache__`，示例命令统一使用绝对 `SKILL_DIR`，可在任意 cwd 执行。
