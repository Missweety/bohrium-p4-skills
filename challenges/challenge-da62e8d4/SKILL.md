---
name: paper-reproduction-audit
description: 从论文材料中重建复现计划（数据/环境/参数/代码/命令），并对原文报告的 t、z、百分比变化做确定性复算，逐条给出可复现/部分复现/不可复现/不可核验判定与原文证据。适用于论文复现、方法验证、结果可复现性审查类任务。
---

# 论文复现与方法验证（paper-reproduction-audit）

目标不是“讲一遍论文”，而是回答：**这篇论文的结论，用纸面信息能独立复现到哪一步？**
每条判定必须附原文段落与引文；没有给出的数据/代码/参数，明确标 missing，绝不补默认值。

## 何时使用

- 要求“复现论文结果”“验证方法是否可复现”“检查报告数值是否自洽”。
- 输入是论文正文/方法段/结果段，可能附代码片段或数据说明。
- 需要区分“我们真算过”与“作者声称过”。

不适用：需要训练模型或下载外部数据（本 Skill 不联网、不训练）；需要原始数据重跑完整流水线。

## 一键运行

脚本任意 cwd 可用，默认路径与平台一致：

```bash
python3 scripts/run_case.py
python3 scripts/run_case.py --input /input --work /app/work --output /app/output
```

可选 `--case <case.json>`。退出码恒为 0（参数错误除外）；材料缺失、case.json 损坏也会写出
降级 `result.json`，原因写入 `limits`。

产物：

| 路径 | 内容 |
| --- | --- |
| `/app/output/result.json` | 契约全字段结果 |
| `/app/output/reproduction_report.md` | 人读版复现报告（计划 + 逐条判定 + 边界） |
| `/app/work/reproduction.json` | 计划、claims、checks、conflicts 原始结构 |
| `/app/work/checks.csv` | 每项复算的输入/计算值/报告值/判定/容差 |
| `/app/work/audit.json` | 独立复核报告 |

## 判定词表（互斥）

| status | 含义 |
| --- | --- |
| `recomputed_consistent` | 用原文给出的 t/df、z、前后值复算，与报告值在报告精度内一致，且数据/环境/参数/命令/代码均有原文依据 |
| `recomputed_inconsistent` | 复算与报告值超出容差；写入 conflicts |
| `partially_reproduced` | 统计关系复算一致，但缺少关键依赖（数据/代码/参数等） |
| `not_reproducible` | 无可复算关系且依赖缺失，无法独立复现 |
| `not_checkable` | 陈述存在但缺 df/p/数值，无法核验 |

复算方法（仅标准库，可逐行复算）：

- 双侧 t 检验 p 值：`p = I_{df/(df+t²)}(df/2, 1/2)`（不完全 Beta，连分式实现）；
- 双侧正态：`p = erfc(|z|/√2)`；
- 百分比变化：`(to - from)/from × 100`，原文若写“下降/减少”，按幅度比较；
- 容差取“报告值的小数精度”，例如 `p = 0.02` 容差 0.005，`p < 0.001` 按不等式判定。

## 计划抽取（只认原文）

| 类别 | 识别内容 | 缺失时 |
| --- | --- | --- |
| data | dataset / GSE 编号 / participants / samples | 标 missing |
| environment | Python/R 版本、框架、CUDA、软件版本 | 标 missing |
| parameters | learning rate、batch size、epochs、seed、α | 标 missing |
| commands | `$ ...`、`python x.py`、`Rscript`、运行命令 | 标 missing |
| code | 仓库 URL / “code is available at…” | “available on request” 也标 missing（未提供） |

## 交付要求

1. `result.json` 含 output_contract 每个字段（`contract_check.missing` 为空）。
2. 每条 claim 带 `paragraph_id` + `quote`；quote 必须能在材料中检索到。
3. 每条检查带 `inputs`、`computed_*`、`reported_*`、`tolerance`、`verdict`，可离线复算。
4. `conflicts` 与 `summary` 计数必须与列表长度一致。
5. `limits` 说明缺哪些依赖、哪些结论只能算部分复现。
6. 不写绝对机器路径、token；不联网；不声称未真实运行的复现结果。

## 异常处理

| 情况 | 行为 |
| --- | --- |
| 无可读材料 | `status=blocked`，不生成复现结论 |
| 无结果陈述 | `status=partial`，明确“未定位到可判定陈述” |
| t 有而 p 缺 | `not_checkable`，不替作者补 p |
| 报告 p 与复算冲突 | `recomputed_inconsistent`，列入 conflicts，不修改原文数字 |
| 数据/代码缺失 | `partially_reproduced` 或 `not_reproducible` |
| case.json 非法 | 回退默认契约，`partial`，`limits` 说明 |
| 内部异常 | `failed`，仍写出降级 result.json |

## 自检

```bash
python3 scripts/audit_result.py --result /app/output/result.json --doc /app/work/doc.json \
  --plan /app/work/reproduction.json --case /input/case.json
```

审计会**从存储的输入重新计算** t→p、z→p、百分比变化，与存储结果比对，防止手写数值；
同时检查契约字段、claim 状态、quote 逐字性与 summary 计数。详见 references/。
