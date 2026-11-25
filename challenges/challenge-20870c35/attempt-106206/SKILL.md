---
name: slides-03-presentation-content-planning
description: Organize research content for a presentation. Use for 学术汇报内容组织 / talk outline: builds the storyline, allocates content to sections with time budget, flags material that must be dropped, and keeps every claim traceable to the source.
version: 2.0.0
---

# 学术汇报内容组织

## 用途与适用条件

让 Agent 按指定听众与时长把研究材料组织成可直接上台的汇报稿：报告目标、听众、叙事顺序、逐页重点信息与问答准备形成闭环。

**适用条件**：输入目录含任务说明与科研材料；材料为可抽取文本的 PDF/TeX/DOCX/Markdown，或含可解析的表格与图注。

**不适用**：扫描件无文本层、材料缺失、需联网检索、或要求生成新数据。此类按「异常处理」如实降级，不猜测。

## 调用方式

```bash
python3 /skills/weekly-skill/scripts/run_case.py --input /input --output /app/output --work /app/work
```

**这一条命令即产出完整且已自检的结果**：每个请求字段都有一行、已带逐字引文与锚点、状态已判定，`output_contract` 声明的必填字段全部到位。**你不需要再手写判定文件。**

当 `output_contract` 要求 deck / slides / slide_evidence / render_log / deliverables 一类字段，或案例给了模板 / 起始稿时，`run_case.py` 会自动再跑一遍页级编排（等价于单独执行 `lane_slides.py`），把叙事页序与真实导出件合并进 `result.json`：`slides`（逐页标题/主张/要点/讲稿/证据）、`slide_evidence`（页级证据映射）、`render_log`、`artifacts`。`status` 只有在导出成功且无模板/PDF 降级时才是 `success`。

产物：`/app/output/result.json`（契约结果，含 `case_id`）、`/app/output/deck.md`（可编辑源）、`/app/output/slide_evidence.json`（页级证据）、`/app/output/deck.pptx`（可编辑演示稿）、`/app/output/deck.pdf` 与 `/app/output/preview/*.png`（渲染预览）、`/app/work/review_sheet.json`、`/app/work/doc.json`、`/app/work/field_results.json`、`/app/work/audit.json`、`/app/work/lane_slides.log`。

## 输入

/input/case.json —— case_id、源材料、目标模板、固定受众、讲述时长与幻灯片张数、任务要求; /input/task.md —— 题面原文; 源材料本体：论文或研究材料 PDF（真 PDF，无预抽取答案层），含图表、公式与引用编号; 组织方给定的母版/版式可编辑模板（actual master/layout-based editable template）; 需要编辑或改编的案例附带的起始演示稿（actual starting deck）; case.json 中固定的受众、时长与页数（fixed audience / time / slide count）; /app/work 工作区与 /app/output 交付区（含 result.json）; environment/resources.yaml —— office-renderer、pdf-text-tool、pdf-render-tool、ocr-tool、scientific-python、font-discovery

## 输出契约

`result.json` 必须包含 `case.json` 中 `output_contract` 声明的**全部**字段，外加 `case_id`、`status`、`sources`、`uncertainty`、`change_log`。字段集合以运行时契约为准，本 Skill 不硬编码字段名。

| 内容 | 本题落地 |
|---|---|
| 主结果 | 可编辑演示文件（母版/版式一致，页级可查） |
| 证据 | 每页主张到论文图表/正文的定位映射 |
| 边界 | 渲染与版本记录、跳过内容及原因 |

### 证据锚点规范

每个结论性字段都要带锚点，格式：

```
p.N            第 N 页（1-based，PDF 页序，非印刷页码）
sec.X          第 X 个章节单元
sent.K         该单元第 K 句
tab.M/row.K    第 M 张表第 K 行
cap.M          第 M 条图注/表注
```

锚点要细到**第二个人能独立抽查**：必须附**逐字引文**，且引文能在该锚点位置找到。

### 状态取值

`status` 只取 `success` / `partial` / `failed`。字段级状态区分：

- `reported` —— 原文确有对应内容，已附锚点与引文
- `not_reported` —— 原文未报告该字段。**不等于 0，不等于空字符串，不等于 null 充数**
- `source_conflict` —— 原文多处给出互斥内容，已列出冲突位置
- `extraction_failed` —— 材料不可读或抽取链路失败

### 可选抽检（默认不必做）

`/app/work/review_sheet.json` 是紧凑复核表：每个字段一行，附 ≤3 条候选引文。

- **不要通读 doc.json / 原文全文**（token 预算不够），只看这张表。
- 抽检只看两件事：该行 `value` 是否逐字出现在同一行 `quote` 里；`paragraph_id` 是否指向材料中真实存在的位置。
- 发现问题才改 `result.json` 里那一行，并在 `change_log` 记一笔。

### 交付纪律

- **每条 `reported` 的引文必须逐字包含 `value`**：value 不是引文的逐字片段就是错的。
- **不确定就判 `not_reported`**，不要用近似句凑数；**字段缺失不等于 0**。
- 铁律：**猜出来的值不算抽取；引文逐字命中不等于语义正确。**

## 抽取口径

### 必须做

- 其余 8 条见 `resources/extraction_protocol.md`

### 禁止

- 其余 5 条见 `resources/extraction_protocol.md`

完整口径清单见 `resources/extraction_protocol.md`。

### 证据粒度要求

页级 + 论断级：每页唯一主张回指源材料的具体位置，并附证据强度标注与问答准备对应页；取舍记录与页映射过程留档可复核。

## 异常处理

遇到材料缺失、无法判断、冲突、部分完成、运行失败等情形，按对应状态如实标注，不得静默跳过或用推测值填充；状态词表见 `resources/extraction_protocol.md`。

## 自查方法

```bash
python3 /skills/weekly-skill/scripts/audit_result.py --result /app/output/result.json \
    --case /input/case.json --doc /app/work/doc.json
```

确认契约齐备、锚点可定位、引文逐字命中、数值保真、状态诚实、边界三件套齐备。可核验指标与完整清单见 `resources/acceptance_checklist.md`。

## 限制与依赖

- 语义等价性脚本**无法**判定：脚本保证「有据可查」，是否答对由你抽检复核。
- 版式解析依赖 PDF 文本层；扫描件输出 `extraction_failed` 并说明人工接管位置。
- 跨页表格只能定位到「页 + 表 + 行」，续表行归属由模型判断并记入 `uncertainty`。
- 预算有限（64 次请求 / 900 秒），脚本一次成型，勿反复重跑全文抽取。
- 抽取与复核只用 Python 3 标准库；`deck.pptx` 优先用 python-pptx 继承组织方模板的母版/版式/占位符/主题，缺失时用内置 `pptx_mini` 纯标准库直出并如实标降级；`deck.pdf`/预览依赖 soffice（或 `lowriter`），缺失时跳过并在 `render_log.degraded` 与 `uncertainty.unresolved` 写明，`status` 随之为 `partial`。有 poppler 时 PDF 版面更佳，缺失自动降级并在 `coverage.extraction.tier` 标注。词表见 `resources/field_lexicon.json`，方法见 `references/method.md`。

## 改动记录（v2.0.0，2026-11-25）

本版只改可复现的真实缺陷，合成夹具实测（非官方案例）：

1. **只有字段、没有稿**：旧的 `run_case.py` 从不调用 `lane_slides.py`，本应交付的页序/讲稿/证据映射与 `deck.pptx` 全缺，`result.json` 仍报字段齐备。现按契约识别 deck 类任务并真实跑编排、合并页级结果与导出件。
2. **含 "id" 的字段被判成 case_id**：`contract_map.slot_of` 的子串兜底让 `slide_evidence`/`slide_count`/`validity` 全变 `case_id`，字段被填成案例名。现整词匹配并补齐 slide/render/artifact 槽位。
3. **降级了却报 success**：纯标准库直出 pptx、缺 soffice 无 PDF 时仍 `success`。现降级项进 `uncertainty.unresolved`，`status` 变 `partial`。
4. **模板被起始稿顶替 / 绝对路径外泄**：`find_template` 只取第一个 pptx；结果里写本机绝对路径。现优先 case 显式模板、按命名排序，结果只留文件名。
5. **GBK 材料读成乱码仍判 success**：现按 utf-8-sig → utf-8 → gb18030 → big5 → latin-1 解码并记录 `coverage.extraction.encoding`。
6. **case.json 非法仍判 success**：现直接 `failed` 并说明。
7. 页内“要点单薄/待复核”从 `unresolved` 移到 `uncertainty.notes`，只有“无带锚点证据的页”才进 `unresolved`。

实测（`/tmp/s2`，真实文本 PDF + 13.333×7.5in 模板 + 起始稿）：`status=success`，5 页、`deck.pptx` 继承模板版式且示例页清除、模板哈希不变，`deck.pdf` 5 页、`preview/` 5 张；起始稿与模板共存时选中 `template.pptx`；删 python-pptx / soffice 时降级为 `partial` 并写明原因。
