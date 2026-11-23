# 方法说明

## 1. 总体流程

```
/input
  case.json / task.md / 材料
        │
        ▼
extract_sources.py  →  sources.json（段落 + 锚点 + 角色）
        │
        ▼
build_proposal.py
  1. 读契约与案例字段
  2. 抽取背景、缺口、问题、目标、方法、指标、成果、风险
  3. 绑定证据（逐字引文 + 锚点 + 核验）
  4. 生成里程碑（按周期与阶段比例）
  5. 生成对齐矩阵、四项关注点、数字追溯
  6. 渲染 Markdown → 写 DOCX → 重开校验 → 再渲染
        │
        ▼
/ app/output
  proposal.md / proposal.docx / proposal.html
  evidence.csv / result.json / selfcheck.json
```

## 2. 锚点规则

- 材料按文件编号 `S1`、`S2`……；段落编号 `S1#p1.3`。
- 无分页信息的材料统一用 `p1`；有分页时用实际页号。
- `case.json` 字段用 `case.json:research_question` 形式。
- 引文必须是段落原文的连续子串；若材料是 CSV，一行视为一段。
- 无法定位的内容不得给锚点，必须标为 `draft` 或 `not_reported`。

## 3. 七要素生成策略

| 要素 | 选取依据 | 缺失时 |
|---|---|---|
| 研究背景 | 背景/引言段中的事实句 | 写“材料未提供背景”，不编造 |
| 问题定义 | 缺口标记（不足、缺乏、尚未、未解决） | 由问题句反推，标草案 |
| 研究目标 | 主要指标/阈值/结局句 + 方法句 | 目标标 `not_reported` |
| 技术路线 | 含动作动词的方法句，按设计→测量→结局→建模→对照→一致性→分析排序 | 生成“需补充技术路线”占位 |
| 阶段计划 | 材料周期 + 阶段比例 | 无周期则不排期 |
| 风险 | 四类模板 + 材料中的风险提示 | 标草案，注明需确认 |
| 预期成果 | 成果/交付/发表/数据集句 | 按常规交付物草拟，标草案 |

## 4. 目标的可考核性

每个目标必须回答四件事：

1. **指标/阈值**：来自材料的主要指标、判据、阈值或结局定义；没有就写“材料未提供”。
2. **对照/参照**：来自“对照/比较/相对”句；没有就写“材料未提供”。
3. **时间点**：优先取问题或指标中的“X 个月”；否则取项目周期末；都没有则写“待确认”。
4. **样本/数据范围**：取材料样本量；没有则写“材料未提供”。

目标措辞是计划草案，不是既有事实；正文以【草案】标注。

## 5. 对齐矩阵

对每个研究问题检查：

- 是否有对应目标（`objective_id`）；
- 是否有对应技术路线步骤（`linked_questions`）；
- 是否有对应里程碑（`linked_objectives`）；
- 是否有对应预期成果（`objective_id`）。

任一缺失即写入 `alignment.gaps`，`alignment.status=partial`。  
里程碑必须闭合：依赖指向已存在的阶段；末月必须等于声明周期。

## 6. 数字追溯

允许的数字来源：

1. 材料原文中的数字；
2. `case.json` 中的数字；
3. 由材料周期按阶段比例推导的起止月（写入 `numeric_audit.derived`）；
4. 由材料样本量直接复用的 `n=`。

任何结论句中的数字若不在上述集合，进入 `numeric_audit.unresolved`，并在 `uncertainty` 中列为需人工确认。

## 7. 四项关注点

- **立得住**：背景与缺口条数、问题数量（1–3）、每个问题是否有材料依据。
- **对得上**：对齐矩阵是否无缺口。
- **排得开**：周期是否已知、里程碑是否生成、经费是否已知。
- **说得清**：风险是否四类齐全且含触发/影响/备选/决策点；`reported` 断言是否全部核验。

四项全部 `pass` 才可能 `success`；否则 `partial` 并在正文 5.3 节列出。

## 8. DOCX 生成

`docx_mini.py` 直接写 WordprocessingML：

- 标题 → `Heading1`–`Heading4`，保留大纲级别；
- 列表 → `ListBullet` / `ListNumber`；
- Markdown 表格 → 真实 `w:tbl`，带边框与表头底纹；
- 加粗、行内代码 → 对应 `w:rPr`；
- 写入 `docProps/core.xml` 与 `app.xml`，便于 Word 识别；
- 写完后立即用 `zipfile` + `ElementTree` 重开，统计段落、表格、文本字符数。

若环境有 `soffice` / `libreoffice`，额外尝试转 PDF（45 秒超时）；没有则如实记录 `unavailable`，不伪造预览。

## 9. 自检

`selfcheck.py` 不改写产物，只重开并检查：

- 契约字段完整性；
- `status` 与 `uncertainty` / `numeric_audit` 是否自洽；
- `proposal.md` 七要素标题；
- `proposal.docx` 是否可重开、是否含关键中文标题与表格；
- `reported` 断言的锚点与逐字引文；
- 问题数量、对齐矩阵、里程碑末月、四类风险、预期成果；
- 元素状态在 `success` 下不得为 `not_reported`。

首行输出 `PASS` 或 `FAIL`，退出码 0/1。

## 10. 已知边界

- 不做 OCR；扫描件不可读时只能 `partial`/`failed`。
- 不做联网检索；文献、基金号、伦理批号一律不编造。
- 不判断研究想法的学术价值，只检查结构完整性与可追溯性。
- 阶段比例是启发式排期，必须由课题组按实际任务量调整。

## 11. 修复记录

**2026-11-23：selfcheck 误报 32 条 quote not found**

- 现象：在包根执行
  `python3 submission/scripts/selfcheck.py --case submission/examples/synthetic_case/case.json --out /tmp/p_out`
  退出码 1，首行 FAIL，报 C1–C32 的引文在 `S1#p1.4` 等锚点找不到。
- 根因：不是引文抄错，也不是锚点偏移。`selfcheck.py` 未传 `--sources` 时，默认拼成
  `<out>/../work/sources.json`，在 `/tmp/p_out` 场景下指向不存在的 `/tmp/work/sources.json`；
  于是 `sources` 为空字典，`para_index` 为空，所有 S 锚点都被判为找不到。
  旧逻辑把“数据源缺失”误报成“引文不匹配”，且逐条输出 32 条误导性错误。
- 修复：
  1. 新增 `resolve_sources()`，按优先级查找：显式 `--sources` → `result.json` 的
     `build.sources_path`（构建时已写入绝对路径）→ `<out>/sources.json` →
     `<out>/../work/sources.json` → `<out>_work/sources.json` → 案例目录 `work/` → 当前目录 `work/`。
  2. 找不到 `sources.json` 时只报一条明确错误 `sources.json not found; cannot verify claim anchors`，
     不再对每条 claim 输出“quote not found”；检查本身不放宽。
  3. `run_case.py` 增加 `--out` 作为 `--output` 的别名，匹配调用习惯。
- 回归：`/tmp/p_out2` + `/tmp/p_out2_work` 实跑，`run_case` 退出 0、`selfcheck` 首行 PASS 退出 0，
  `validate_submission.py` 首行 PASS。
