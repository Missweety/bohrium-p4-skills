# 验收清单与风险处置

## 1. 提交前验收清单

| 项 | 检查方法 | 通过标准 |
|---|---|---|
| 目录结构 | `find submission -type f` | `SKILL.md`、`references/output-contract.md`、`scripts/`、`examples/` 齐全 |
| frontmatter | 人工/解析 | 含 `name`、`description` |
| 脚本可执行 | `python3 -m py_compile scripts/*.py` | 无语法错误 |
| 合成端到端 | `run_case.py --input examples/synthetic_case ...` | 退出码 0，`selfcheck=PASS` |
| Markdown | 打开 `proposal.md` | 七要素齐全，锚点与引文可查 |
| DOCX | `zipfile` 打开并解析 `word/document.xml` | 有文本、有表格、可重开 |
| 契约 | 对比 `case.json.output_contract` 与 `result.json` | 字段无缺失 |
| 证据 | 检查 `evidence.csv` | `reported` 均有锚点与逐字引文 |
| 数字 | 检查 `numeric_audit` | 结论数字可追溯；未追溯项已标出 |
| 自检 | `selfcheck.py` | 首行 `PASS`，退出码 0 |
| 清洁 | 查找 `__pycache__`、密钥、绝对个人路径 | 均为空 |
| 平台 | 不提交 | 本技能不做平台提交 |

## 2. 常见失败与处置

| 现象 | 原因 | 处置 |
|---|---|---|
| `FAIL: proposal.docx is not a valid ...` | DOCX 写入中断或 ZIP 损坏 | 删除重生成；检查磁盘空间；确认 `docx_mini.py` 未被改动 |
| `FAIL: claim Cx quote not found` | 引文被改写或锚点错位 | 用材料原文替换；重新抽取 `sources.json` |
| `FAIL: alignment gaps` | 某问题缺少目标/步骤/里程碑/成果 | 补目标或调整里程碑关联；不要删除问题来“过关” |
| `FAIL: last milestone end_month != period` | 阶段比例与周期不一致 | 重算阶段长度，末月必须等于周期 |
| `FAIL: risk categories` | 缺少数据/方法/进度/伦理之一 | 补齐四类；每类含触发、影响、备选、决策点 |
| `status=partial` 但无 unresolved | 状态与缺失不一致 | 补 `uncertainty.unresolved`，或修复缺失后改回 success |
| 无 PDF 预览 | 环境无 office renderer | 保留 HTML 预览，`preview.status=unavailable`，不影响 PASS |

## 3. 风险处置矩阵

| 风险 | 触发信号 | 首选处置 | 决策时点 |
|---|---|---|---|
| 数据/样本延迟 | 首个数据里程碑未产出清单；有效样本低于下限 | 启用备选数据源；缩小样本并重算功效 | 第 2 个里程碑 |
| 方法不可行 | 核心指标未达阈值；复现失败 | 切换备选方法；增加对照/敏感性分析 | 第 3 个里程碑 |
| 进度延期 | 任一里程碑延期 ≥4 周；关键岗位空缺 | 压缩非关键分析；并行化；申请周期调整 | 每个里程碑 |
| 伦理/合规未过 | 首个里程碑前未获批准 | 暂缓涉人步骤；调整设计；如实延期 | 第 1 个里程碑 |

## 4. 诚实性红线

- 不得编造样本量、经费、伦理批号、参考文献、预实验数据。
- 不得把草案写成“已有结果”。
- 不得在 `status=success` 下保留未解决项或未追溯数字。
- 不得声称官方评分或人工审查通过。
