# 输出契约（output contract）

本文件说明 `case.json` 的 `output_contract` 如何映射到实际产物。`scripts/common.py` 负责解析契约，`scripts/build_proposal.py` 负责填充，`scripts/selfcheck.py` 负责复查。

## 1. 契约的三种写法

`output_contract` 可以是：

1. **字段列表**：`["proposal_md", "proposal_docx", "elements", ...]`
2. **字段到说明的映射**：`{"proposal_md": "正文...", "proposal_docx": "Word...", ...}`
3. **嵌套声明**：`{"fields": {...}}`、`{"required": [...]}`、`{"outputs": {...}}`

解析时按以下优先级合并：

- 先取 `required` 中的字段；
- 再取 `fields` / `outputs` 中的键；
- 最后取顶层键。
- 若完全没有契约，使用 `DEFAULT_FIELDS`，并在 `contract_check.source` 标记 `default`。

契约里出现但本技能不认识的字段名，不会被丢弃：会以 `not_reported` + 说明写入 `result.json`，同时进入 `contract_check.missing`，以便人工补映射。

## 2. 字段映射

| 契约字段（别名） | result.json 键 | 内容 |
|---|---|---|
| `case_id` / `id` | `case_id` | 案例标识；缺失时用输入目录名 |
| `status` / `state` | `status` | `success` / `partial` / `failed` |
| `proposal` / `proposal_md` / `report` / `开题报告` | `proposal_md` | Markdown 正文全文 |
| `proposal_path` / `proposal_file` / `output_path` | `proposal_path` | Markdown 绝对路径 |
| `proposal_docx` / `docx` / `word` / `文档` | `proposal_docx` | DOCX 绝对路径 |
| `proposal_docx_path` / `docx_path` / `word_path` | `proposal_docx_path` | DOCX 绝对路径（同值） |
| `docx_check` / `document_check` | `docx_check` | 重开校验结果 |
| `elements` / `七要素` / `章节` | `elements` | 七要素结构化内容与状态 |
| `element_status` | `element_status` | 七要素状态映射 |
| `evidence` / `evidence_map` / `citations` | `evidence` | 证据台账（含锚点、逐字引文、核验） |
| `sources` | `sources` | 材料清单、角色、读取状态 |
| `constraints` / `inputs` | `constraints` | 周期、经费、样本、人员、数据、伦理 |
| `feasibility` | `feasibility` | 逐项可行性判断 |
| `alignment` / `matrix` | `alignment` | 问题—目标—路线—里程碑—成果对齐 |
| `concerns` | `concerns` | 立得住 / 对得上 / 排得开 / 说得清 |
| `numeric_audit` / `numbers` | `numeric_audit` | 数字追溯与推导记录 |
| `risks` | `risks` | 四类风险及触发/影响/备选/决策点 |
| `milestones` / `schedule` | `milestones` / `schedule` | 里程碑与阶段计划 |
| `questions` / `research_questions` | `questions` | 1–3 个研究问题 |
| `objectives` / `aims` | `objectives` | 目标、指标、样本、对照、时间点 |
| `route` / `methods` | `route` | 技术路线步骤、输入输出、依赖 |
| `outcomes` / `deliverables` | `outcomes` | 预期成果与验收方式 |
| `uncertainty` / `limitations` | `uncertainty` | 缺失、冲突、需人工确认 |
| `change_log` | `change_log` | 本次生成做了什么、哪些是草案 |
| `artifacts` | `artifacts` | 产物路径、角色、格式、字节数 |
| `preview` | `preview` | PDF/HTML 预览状态 |
| `coverage` | `coverage` | 元素计数、DOCX 状态、四项关注点 |

## 3. `result.json` 的硬性要求

- 顶层必须有 `case_id`，且与 `case.json` 一致（若可解析）。
- 契约声明的每个字段都必须出现；不得用空壳占位。
- `status` 必须是 `success` / `partial` / `failed` 之一。
- `status=success` 时：
  - `uncertainty.unresolved` 必须为空；
  - `numeric_audit.unresolved` 必须为空；
  - 七要素不得存在 `not_reported`；
  - `docx_check.ok` 必须为 `true`。
- `status=partial` 时：
  - `uncertainty.notes` 必须非空；
  - `uncertainty.unresolved` 必须列出至少一个未解决项；
  - 未追溯的数字必须保留在 `numeric_audit.unresolved`，不得写成事实。
- `status=failed` 时：
  - 必须给出失败原因；
  - 不得声称已生成完整正文或 DOCX。

## 4. DOCX 契约

`proposal.docx` 必须满足：

- 是一个合法的 ZIP 包，含 `[Content_Types].xml`、`_rels/.rels`、`word/document.xml`、`word/styles.xml`；
- `word/document.xml` 可被 XML 解析器重新打开；
- 含可读文本（`w:t` 非空）；
- 保留标题层级（`Heading1`–`Heading4`）与真实表格（`w:tbl`），不得把表格压成纯文本；
- `docx_check` 记录 `ok`、`paragraphs`、`tables`、`bytes`、`error`。

`scripts/docx_mini.py` 只使用标准库 `zipfile` 与 `xml.etree.ElementTree`，不依赖 `python-docx`。

## 5. 缺失与冲突

- 缺失：写 `status: not_reported`、`value: null`、`note: 材料未提供`，并进入 `uncertainty.unresolved`。
- 冲突：写 `status: source_conflict`，列出全部候选值与锚点，不擅自选值，并进入 `human_confirm`。
- 推断：只能由材料周期按阶段比例推导；写入 `numeric_audit.derived`，并标注公式。

## 6. 退出码

| 命令 | 0 | 非 0 |
|---|---|---|
| `build_proposal.py` | 产物已写出 | 无法写出 `result.json` |
| `selfcheck.py` | 所有硬检查通过（首行 `PASS`） | 任一硬检查失败（首行 `FAIL`） |
| `run_case.py` | `status` 为 `success` 或 `partial` | `status=failed` 或未捕获异常 |
