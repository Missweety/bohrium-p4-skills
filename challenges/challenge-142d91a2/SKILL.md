---
name: research-proposal-plan
description: 从案例材料生成可提交的中文开题报告（research proposal），同时产出可编辑 Markdown 与真实可重开的 DOCX，并用证据台账、七要素对齐矩阵、周期里程碑、四类风险与自检脚本保证每条结论可回溯。适用于开题报告、研究计划书、课题申报书初稿、评审前自查；不适用于论文正文写作、实验数据分析或需要联网检索的综述。
---

# research-proposal-plan

把 `/input` 中的 `case.json`、`task.md` 与材料，转成一份可直接评审的 `proposal.md` 与 `proposal.docx`。  
本技能只使用 Python 3 标准库，不联网；不读取 `.secrets`，不打印任何凭据。

## 何时触发

用户或运行环境出现以下需求时使用：

- 开题报告 / 研究计划书 / research proposal / 课题申报书 / 研究方案
- 把零散材料整理成“研究问题—目标—方法—进度—风险—成果”的完整方案
- 评审前自查：缺口是否说清、目标是否可考核、进度是否排得开、风险是否有备选
- 需要同时交付可编辑 Markdown 与可被 Word 重新打开的 DOCX

## 适用与不适用

**适用**

- 有明确案例目录（`case.json` + `task.md` + 1 个以上材料文件）
- 材料以 Markdown、TXT、CSV、JSON 等文本形式存在
- 需要在给定周期、经费、样本、人员、伦理条件下排出可执行计划
- 需要逐条标注材料锚点，缺失信息必须如实标为“待确认”

**不适用**

- 要求代写论文正文、伪造参考文献、编造预实验数据或伦理批号
- 需要联网检索最新文献、调用外部数据库或统计软件
- 需要生成 PPT、海报、视频等非文档交付物
- 材料为扫描 PDF 且无可用文本层（本技能不做 OCR，应明确报 failed/partial）

## 固定调用顺序

必须按以下顺序执行，不要跳步：

1. **抽取**：`python3 scripts/extract_sources.py --input /input --work /app/work`  
   读取 `case.json`、`task.md` 与材料，生成 `sources.json`（段落、锚点、角色、可读性）。
2. **构建**：`python3 scripts/build_proposal.py --input /input --work /app/work --output /app/output`  
   生成 `proposal.md`、`proposal.docx`、`proposal.html`、`evidence.csv`、`result.json`。  
   若提供了人工确认的 `proposal_plan.json`，加 `--plan /app/work/proposal_plan.json`。
3. **自检**：`python3 scripts/selfcheck.py --case /input/case.json --sources /app/work/sources.json --out /app/output`  
   必须看到首行 `PASS`；出现 `FAIL` 时按问题逐条修复后重跑。
4. **一键入口**（推荐）：`python3 scripts/run_case.py --input /input --work /app/work --output /app/output`  
   等价于 1–3 步，并额外写出 `selfcheck.json`；构建成功但自检失败时仍保留产物，退出码只在无法产出结果时为 1。

脚本职责：

| 脚本 | 职责 |
|---|---|
| `scripts/common.py` | 路径、锚点、契约字段、JSON/CSV、文本规范化 |
| `scripts/extract_sources.py` | 材料发现、文本抽取、锚点编号、角色识别 |
| `scripts/build_proposal.py` | 七要素、证据台账、对齐矩阵、里程碑、风险、DOCX |
| `scripts/docx_mini.py` | 纯标准库写 WordprocessingML，含表格与重开校验 |
| `scripts/selfcheck.py` | 独立重开产物并检查契约、证据、数字、计划一致性 |
| `scripts/run_case.py` | 单命令编排与失败兜底 |

## 输出契约

完整字段与映射规则见 `references/output-contract.md`。最低要求：

- `proposal.md`：可继续编辑的正文
- `proposal.docx`：真实 OOXML 文档，标题层级与表格保留，可被 Word 重新打开
- `result.json`：包含 `case_id` 与 `case.json` 中 `output_contract` 声明的全部字段
- `evidence.csv`：每条事实性表述的锚点、逐字引文、核验状态
- `proposal.html`：可打印预览；若运行环境有 office renderer，额外生成 PDF

## 证据与数字规则

- 每条事实性表述必须带锚点：`S1#p1.3`（文件 S1 第 1 页第 3 段）或 `case.json:<key>`。
- 引文必须是材料原文的连续子串；改写句必须标为【草案】，不得冒充原文。
- 数字只允许来自材料、`case.json`，或由材料周期按阶段比例显式推导；推导过程写入 `numeric_audit.derived`。
- 材料未给出的样本量、经费、设备、伦理批号、参考文献等，一律写“材料未提供 / 待确认”，不得补造。
- 冲突数字（同一约束出现互斥值）标 `source_conflict`，并加入 `human_confirm`。

## 七要素与四项关注点

正文必须覆盖：研究背景、问题定义、研究目标、技术路线、阶段计划、风险、预期成果。  
同时用四项关注点自检：

| 关注点 | 检查问题 |
|---|---|
| 立得住 | 问题是否具体、可证伪，背景是否真的指向该缺口？ |
| 对得上 | 问题—目标—技术路线—里程碑—成果是否逐项对应？ |
| 排得开 | 阶段计划是否落在给定周期、经费、数据与人员条件内？ |
| 说得清 | 风险是否有触发信号、影响、备选方案、决策时点，论断是否可回溯？ |

## 异常处理

| 异常 | 处理 | 状态 |
|---|---|---|
| `/input/case.json` 缺失或不可解析 | 仍尝试读取材料；`case_id` 用目录名；在 `uncertainty` 说明 | `partial` |
| `output_contract` 缺失 | 输出默认全部字段，并标注 `contract_source=default` | `partial` |
| 材料为二进制/扫描件且不可读 | 记录 `readable=false`，不得编造内容 | `partial`；全部不可读则 `failed` |
| 周期缺失 | 不生成里程碑，说明缺少周期；目标时间点写“待确认” | `partial` |
| 周期与任务量明显不匹配（<3 或 >60 个月） | 保留材料原值，标可行性 `warn` 并列入人工确认 | `partial` |
| 样本量/经费/人员/伦理缺失 | 对应约束写“材料未提供”，可行性 `unknown` | `partial` |
| 同一约束出现互斥值 | 标 `source_conflict`，不擅自选值 | `partial` |
| 目标无法找到指标/阈值 | 目标状态 `not_reported`，正文写缺失项 | `partial` |
| 数字无法追溯 | 列入 `numeric_audit.unresolved`，不得写成事实 | `partial` |
| DOCX 生成或重开失败 | 保留 Markdown，记录 `docx_check.error` | `partial` |
| 任一必需产物为空/缺失 | 不谎报成功；写 `failed` 与原因 | `failed` |

原则：**能交付多少写多少，缺什么就标什么；不得用编造内容把 `partial` 伪装成 `success`。**

## 交付清单

- [ ] `SKILL.md` 存在且 frontmatter 含 `name`、`description`
- [ ] `references/output-contract.md` 存在
- [ ] `scripts/` 下六个脚本均可执行
- [ ] 合成案例已端到端跑通
- [ ] `proposal.md` 覆盖七要素与四项关注点
- [ ] `proposal.docx` 通过 `zipfile` + `word/document.xml` 解析
- [ ] `result.json` 含 `case_id` 与全部契约字段
- [ ] `evidence.csv` 中 `reported` 断言均有锚点且引文可查
- [ ] `selfcheck.py` 首行 `PASS`，退出码 0
- [ ] 无 `__pycache__`、无密钥、无绝对个人路径、无平台提交

## 诚实状态规则

- `success`：七要素齐全；`reported` 断言全部有锚点且引文可查；数字全部可追溯；DOCX 重开通过；无未解决项。
- `partial`：主体可读且可编辑，但存在缺失约束、待确认阈值、未追溯数字、无 PDF 预览或 DOCX 降级；`uncertainty.notes` 与 `unresolved` 必须非空。
- `failed`：没有可用的 `proposal.md` 或 `result.json`，或材料完全不可读；必须写清原因，不得输出空壳冒充成功。

禁止声称“官方评分”“已通过人工审查”；本技能只做本地可复核的自检。

## 示例

`examples/synthetic_case/` 是明确标注 **SYNTHETIC** 的合成案例，含 `task.md`、`case.json` 与 3 个材料文件，可直接用于端到端验证：

```bash
python3 scripts/run_case.py \
  --input examples/synthetic_case \
  --work /tmp/proposal_work \
  --output /tmp/proposal_out
python3 scripts/selfcheck.py \
  --case examples/synthetic_case/case.json \
  --sources /tmp/proposal_work/sources.json \
  --out /tmp/proposal_out
```
