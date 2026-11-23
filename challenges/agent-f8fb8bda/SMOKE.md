# SMOKE — evidence-first-research（本地合成材料冒烟，非正式案例结果）

时间：2026-11-18。目的：验证 `kernel.py → evidence_rank.py → quote_check.py → emit → check`
在**证据冲突、单一来源、零命中空白、弱证据**并存的材料上一次跑通。材料为临时合成文本，不代表平台案例。

## 1. 合成材料（`/tmp/dr_smoke/`）

| 文件 | 内容 | 构造的测试点 |
|-|-|-|
| `materials/a_trial.md` | 试验：改善 32%（n=240）、M 表达下降 27%、随访 6 个月 | A 级直接证据 |
| `materials/b_cohort.md` | 队列：差异 3% 无获益、高 M 亚组改善 21%、随访 3 年 | 与 A 冲突；亚组单一来源 |
| `materials/c_review.md` | 综述：方向不一致、异质性高、12 项研究 | 二手综合，C/B 级 |
| `materials/d_report.md` | 模型预测 15%-20%，无直接测量 | 弱证据 |
| `case.json` | `case_id=smoke-dr-001` + 带 `output_contract` 的研究问题 | 契约回填 |

子问题：Q1 效应方向与幅度、Q2 机制、Q3 随访 ≥5 年、Q4 基线 M 高表达亚组。

## 2. 执行与结果

```bash
python3 scripts/kernel.py init --case case.json --out work
python3 scripts/kernel.py index --materials materials --out work
python3 scripts/evidence_rank.py --table work/evidence_table.json --out work/evidence_rank.json
python3 scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt --out work/quote_check.json
python3 scripts/kernel.py verify --text work/report_text.txt --evidence-dir work --out work
python3 scripts/kernel.py emit --draft work/draft.json --contract-dir work --out out
python3 scripts/kernel.py check --out out
```

| 步骤 | 观测结果 |
|-|-|
| `init` | `case_id=smoke-dr-001`，`output_contract` 5 个字段 |
| `index` | 4 个文件全部 ok（`files_readable=4`） |
| `evidence_rank` | `evidence=6 grades={A:4,B:2,C:0,X:0} covered=3/4 gaps=1 conflicts=1 inadmissible=0` |
| 分级明细 | E01/E02/E03/E04 = A（6.0–6.5）；E05/E06 = B（3.5，间接/模型 + 时效） |
| 覆盖 | Q1 covered（4 源，conflict=true）、Q2 covered（single_source）、Q3 **not_covered**、Q4 covered（single_source） |
| `quote_check` | `verdict=pass failed=0/6` |
| `verify` | `verdict=pass unsupported_numbers=0` |
| `emit` / `check` | `missing_contract_fields=none` / **PASS** |

产物事实：报告结论句写"材料间方向不一致"而非"一致表明有效"；E03（refute）同时出现在结论段与
"冲突与反证"节；Q3 空白由 3 条零命中检索式支撑（`5-year`、`long-term`、`5 年随访`）。

## 3. 负向用例

| 用例 | 操作 | 结果 |
|-|-|-|
| 缺 quote | 把 E01 的 `quote` 置空 | `verdict=review`、`X=1`、`inadmissible=1`，退出码 1 |
| 引文改写 | 同知识库题负向用例：quote 改为"去除率翻倍" | `quote_check` 报 `not_verbatim`，退出码 1 |

## 4. 边界与已知限制

- 分级是**规则化排序**（来源类型 3.0 + 直接性 2.0 + 设计 1.0 + 时效 0.5），不等于研究质量终评；
  `review` 与 `preprint` 同基础分，避免把"综述权威"当高质量证据。
- 单一来源子问题（Q2、Q4）只允许"一项材料报告"，已在报告措辞中体现；实际案例需人工复核措辞。
- 时效窗口默认 5 年、`as_of` 取材料内最大年份；材料年份缺失时该条不加分（`year=0`）。
- 执行期不联网，Q3 空白只代表"库内未覆盖"，不能写成"领域无研究"。
- 未覆盖真实 PDF（无文本层/双栏）、多语言材料、超预算截断的表现；正式案例需回归。
- 本次未使用平台正式案例与白板，分数不可据此推断。

## v1.1.0 复跑（/tmp/smoke_dr_v110）

新增：`report_audit.py`（正文↔证据表交叉核对）、`quote_check` 源归属、`check` 全量门禁。

样本：3 份材料（台架×2 冲突 + 综述），3 个子问题（Q3 湿度两检索式零命中）。

| 步骤 | 观测结果 |
|-|-|
| `index` | 3 文件全 ok（`files_readable=3`） |
| `evidence_rank` | `evidence=4 grades={A:0,B:2,C:2}`，`covered=2/3 gaps=Q3 conflicts=1` |
| `quote_check` | `pass 0/4`；负向把 E01 的 `source_path` 改成 review_c → `wrong_source`，退出 1 |
| `report_audit`（正向） | `verdict=pass sections=8/8 errors=0` |
| 负向①反证缺席 | 删掉「冲突与反证」段的 E02 | `refuting evidence E02 missing from conflict/counter section`，退出 1 |
| 负向②结论无锚点+过度断言+禁语 | 去掉 `[E01,E02,E04]`、改"研究普遍认为..."、"领域空白" | 3 条 error 同时命中，退出 1 |
| `verify` | `pass unsupported_numbers=0`（报告小节的数字编号已剥离） |
| `emit`/`check` | `missing_contract_fields=none` / `PASS`（`status=partial`） |
| 负向③证据不可回链 | `status=ok` 且 E01 `quote` 置空 | `FAIL`：`missing quote (not back-linkable)` + `status=ok but some evidence has no verbatim quote` |

结论：新增交叉核对能把「正文说得好但证据对不上」的问题在定稿前拦住；分级/覆盖语义未改动。

## v1.2.0 回归（/tmp/dr_v120，2026-11-23）

背景：v1.1.0 正式分 58.67 低于 v1.0 的 63.67。按可复现缺陷回修，重点验证
「按 SKILL 自带八段模板写报告能否通过 `--strict`」。

样本：3 份材料（试验 a_trial / 队列 b_cohort / 综述 c_review），3 个子问题
（Q1 效应、Q2 机制与亚组、Q3 五年以上随访零命中）。

| 步骤 | 观测结果 |
|-|-|
| `index` | 3 文件全 ok；另用 `[1] Smith 2021…` 编号参考文献与 JSON 数组复测，均判 `ok`（v1.1.0 会误判 `unreadable`） |
| `evidence_rank` | `evidence=4 grades={A:3,B:1}`，`covered=2/3 gaps=1 conflicts=2`；Q2 只有 support+mixed 时也判 `conflict=true` |
| `quote_check` | `pass 0/4`；负向①E01 声明源改成 c_review → `wrong_source` 退出 1；负向②声明源改成不存在的 `materials/nope.md` → `wrong_source`（v1.1.0 静默放行） |
| `report_audit`（正向） | 直接使用 SKILL 第 9 步的八段标题（含「证据矩阵（按子问题…）」「待验证清单（…结论…）」「[E01,E07]」占位）→ `verdict=pass sections=8/8 errors=0`；v1.1.0 会报 `missing section: matrix/todo` 与 `unknown evidence id: E07` |
| 负向③反证缺席 | 删掉「冲突与反证」段的 E02 → `refuting evidence E02 missing…`，退出 1 |
| 负向④无锚点+过度断言+禁语 | 去掉 `[E01]`、改「研究普遍认为…」「该领域空白」→ 4 条 error（无锚点、Q3 空白缺失、禁语、过度断言），退出 1 |
| 负向⑤结论列表句 | 结论段写 `- 该治疗可以推广。`（无锚点）→ 报 `conclusion sentence without [E..] anchor`，退出 1 |
| 负向⑥子标题截断 | 在「### 5.1」下写 E03、在「### 6.1」下写 Q3 → 不再误报 missing refute / gap |
| 负向⑦缺输入文件 | 不传 `--rank` → `evidence_rank missing`，退出 1（fail-closed） |
| `verify` | `pass unsupported_numbers=0`；v1.1.0 会把 `## 5.` 的章节号当数据；`2019. 该研究纳入…` 仍报 2019 |
| `emit`/`check` | `missing_contract_fields=none` / `PASS`（`status=partial`） |
| 负向⑧证据不可回链 | `status=ok` 且 E01 `quote` 置空 → `FAIL`，两条错误同时命中 |

边界：以上均为本地合成材料回归，不代表平台固定案例结果，也不能推断新分数。
