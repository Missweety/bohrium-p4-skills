# 演示文稿赛道方法说明

## 1. 本赛道做什么

把连续叙事的论文重写成**有主线、能上台讲、每页挂得住论文证据**的演示稿，交付三行契约：可编辑演示文件、页级证据映射、渲染与版本记录。

核心原则：**脚本做确定性抽取与装配，模型负责判断与改写**。`scripts/lane_slides.py` 从共享层 `doc.json` 抽出「论文主线候选」（章节序列、每节关键结论句、图表清单与编号交叉核对、核心数值）并排好页序；每页主张与讲稿备注取自论文原句（逐字），**须由模型复核改写后定稿**。脚本不生成论文里没有的论断或数字。

## 2. 输入与产物

### 2.1 输入

| 输入 | 说明 |
|---|---|
| `case.json` | 取 `case_id`、固定受众、时长、`max_slides` 页数上限 |
| `task.md` | 题面原文 |
| 论文本体 | PDF/TEX/DOCX/MD，真论文、无预抽取答案层 |
| `doc.json` | 共享层 `doc_extract.py` 产出的带锚点中间表示 |
| 模板 pptx | 可选，组织方给定的母版/版式，含占位符、主题字体与主题色 |

### 2.2 产物结构定义

| 产物 | 路径 | kind | 必需 |
|---|---|---|---|
| 可编辑演示大纲 | `<output>/deck.md` | `editable_source` | **是**（主产物） |
| 页级证据映射 | `<output>/slide_evidence.json` | `evidence_map` | **是** |
| 产物清单+边界三件套 | `<output>/lane_slides.json` | `lane_manifest` | **是** |
| 可编辑演示稿 | `<output>/deck.pptx` | `editable_deck` | 否（缺 python-pptx 即降级） |
| 导出 PDF / 逐页预览 | `<output>/deck.pdf`、`preview/slide-NN.png` | `export` / `render_preview` | 否（缺 soffice / pdftoppm 即降级） |
| 运行日志 | `<work>/lane_slides.log` | — | 是（中间件） |

`deck.md` 页块结构固定：`## 第 N 页｜页面标题` → 叙事角色 → 主张 → 要点 → 讲稿备注（过渡 / 强调 / 被问到时）→ 图表引用 → 本页证据锚点；首部有页面索引表与主线候选表，末尾有定稿自检清单。

### 2.3 字段语义

`slide_evidence.json` 的 `slides[]` 每项：`slide_no` 页序号（从 1 起连续）；`title` 页面标题；`claim` 该页唯一主张（模型复核后定稿）；`evidence[]` 该页全部证据；`needs_review` 是否存在真实缺口（`true` 的页在复核前不算讲对了）；`review_reasons[]` 需人工确认的具体原因。

`evidence[]` 每条：`locator` 锚点；`quote` 论文**逐字**引文（不得改写、换算或补标点）；`kind` 该证据在页内的角色（`claim`/`bullet`/`caption`）；`figure_ref`/`table_ref` 图表编号，无则 `null`；`verbatim_checked` 该引文是否在锚点段落逐字命中。

`lane_slides.json` 另含 `spine`（主线候选与关键句锚点）、`figures`（图注清单及正文引用位置）、`appendix_candidates`（未成页的小节，供问答备用）、`coverage`（页数/有证据页数/覆盖率/待复核页数/图表引用数）、`degraded`（降级项清单）。

### 2.4 锚点要求

统一用共享层锚点规范：`p.N` 页码、`sec.X` 章节单元、`sent.K` 句序号、`tab.M`/`row.K` 表格与表行、`cap.M` 图注。复合写法 `p.6/sec.12/sent.14` 表示第 6 页、第 12 节、第 14 句。每条证据**必须**带锚点 + 逐字引文，正文里"提到过"不算证据。

`sent.K` 必须与共享层 `doc_extract.split_sentences` 完全同源（本脚本内实现与之逐字一致），否则会与 `numbers[]` 锚点整体错位。

## 3. 执行步骤（模型照此执行）

1. **抽论文**：跑 `doc_extract.py --input <论文文件路径> --outdir <工作目录>` 得 `doc.json`。`--input` 必须是**文件**路径，传目录会得到 `tier=unreadable`。
2. **装配初稿**：跑 `python3 scripts/lane_slides.py --input /input --output /app/output --work /app/work [--doc /app/work/doc.json]`。
3. **读主线**：看 `deck.md` 的主线候选表与 `lane_slides.json` 的 `spine`，判断抽取的章节序列是否就是这篇论文的真实主线。
4. **逐页复核改写**：改主张（一句可讲的结论）、压要点（每点一行）、改写备注（不复述页面文字）。
5. **核对图表**：逐页核对 `figure_ref`/`table_ref` 与图注编号、正文引用位置；对不上标 `needs_review`。
6. **消解待复核**：逐条处理 `needs_review` 与 `uncertainty.unresolved`；消解不了就保留标记并说明，不要静默跳过。
7. **回写与装配**：定稿后的页级结构与逐字引文写回 `deck.md` 与 `slide_evidence.json`，再把三件产物填进 `result.json` 的 `output_contract`。

### 3.1 模型在什么情况下该否决脚本候选

脚本给的是**候选**，不是结论。以下情况必须否决并重写：

1. **章节角色判错**——角色由标题关键词推断；标题含糊或论文结构非标准时会判错，应按正文实际内容重判、必要时合并或拆页。
2. **主线与论文贡献不一致**——页序是"抽取顺序 + 角色优先级"的机械结果；若真正贡献集中在某几节而参考文献、致谢排进正文页序，应重排。
3. **主张句不是结论**——`claim` 取自打分最高的句子，可能是过程描述、铺垫句，或跨栏截断的半句（以 `,` 或数字开头），须换掉。
4. **图表张冠李戴**——同编号图注跨节出现、或该图实为示意图而非实验数据时，解开错挂并记明。
5. **数值不是论据**——若"强调"挑到的是年份、引用序号、图表编号或不支撑主张的数字，应换成真正的结论指标或撤掉。
6. **讲稿与页面重复**——"被问到时"须来自页面**没用过**的原句；高度重合就换一句。
7. **单页过载或过薄**——要点超 4 条，或整页只有抽象话而无证据，应拆页或补证据。
8. **页面缺证据**——无带锚点引文的页不能讲，应删页、降为备用页，或补真实锚点（**不得编造引文凑覆盖率**）。

一句话：**引文命中 ≠ 语义正确**。脚本保证"这句话确实在论文里"，模型负责保证"这句话确实在讲这页该讲的事"。

## 4. 质量标准（可自检的逐条判据）

- 每页有且只有一个主张，且是结论句而非"本章介绍……"
- 单页要点 ≤ 4 条、每条一行；长句留在备注
- 每页至少一条带锚点的逐字引文（证据覆盖率 = 100%）
- 每条 `quote` 能在论文里原样搜到（按 `canon()` 口径：智能引号、破折号归一 + 折行空白折叠后仍逐字命中）
- 页面图表编号与论文图注编号、正文引用位置三者对得上
- 页数不超过 `case.json` 给的上限
- 讲稿备注写过渡、强调点与补充证据，不复述页面文字
- 待复核项已逐条处理，未处理的保留标记并写明原因
- 渲染核对：pptx 能打开能播放、占位符与主题字体未被覆盖、文本无溢出

## 5. 常见失败与降级

| 情形 | 处理 |
|---|---|
| 无 `doc.json` 且无法抽取 | 退出码 1，`lane_slides.json` 写 `status=failed`，不产出半成品 |
| python-pptx 缺失 | 跳过 `deck.pptx`，`degraded` 记明，主产物不受影响 |
| 缺 soffice / pdftoppm | 跳过 PDF / PNG，`degraded` 如实标注 |
| PDF 加密、抽取层级非 `pdftotext` | `uncertainty` 升级为 `medium/high`，注明版面还原与图表归属不确定 |
| 公式是图片、正文编号与图注对不上 | 相关页标 `needs_review` 并写明不一致处，`uncertainty.unresolved` 记一条 |
| 表格正文未自动切分 | `chart_refs[].body_table` 为 `null`，页标待复核，说明行数据需人工核对 |
| 页数超限 | 先合并相邻同角色页，再把低优先级页降为 `appendix_candidates`，`change_log` 写明合并次数 |
| 某节无成句正文（整节表格碎片） | 不强行成页，标 `no_prose` 降为备用页 |

**降级第一原则**：主产物（`deck.md` + `slide_evidence.json`）任何时候不能缺；可选导出件缺失只降级、不阻塞。

## 6. 与共享层的接口

- 输入依赖 `doc_extract.py` 的 `doc.json`；未拿到时脚本自行调 `doc_extract.build_doc()` 兜底抽取，写到 `<work>/doc.json`。
- 引文逐字比对口径与 `audit_result.py` 的 `canon()` 一致。
- `doc.json` 的 `numbers[]` 自带 `anchor`/`section`/`sentence`，与本脚本的 `sent.K` 指向同一套切分，可交叉引用。
- 输出满足 LANE_SPEC §2.3 七字段（`lane`/`case_id`/`status`/`artifacts`/`sources`/`uncertainty`/`change_log`），`sources[].locator` 一律用共享层锚点规范。
- 共享层 6 个脚本只读，本赛道不改、不 fork；"改写"全部落在产物里，脚本保持确定性。
