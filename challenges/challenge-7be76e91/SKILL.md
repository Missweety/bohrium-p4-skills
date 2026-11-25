---
name: multi-plan-comparator
description: 把 3–5 条候选实验路线摆到同一张可比矩阵上：优先读取 case.json 的结构化候选（candidate_plans/plans）与资源合同，其次切分材料文件；固定七类字段（目标/变量/对照/步骤/参数/资源/判读）→ 逐方案填表 → 硬约束淘汰（设备不可得、超预算、参数越界、超时间窗口）→ 透明权重评分 → 选择与逐条舍弃理由 → 权重敏感性。适用于方案选型、评审前的横向对照、资源受限下的路线取舍；不替评审拍板，不编造单价、工期或设备能力，缺证据的维度不参与归一。
version: 1.2.0
license: MIT
---

# 实验方案比较与选择：同一把尺子量所有候选

比较失败通常不是"不会写方案"，而是**每个方案各用一套结构**：读完三段描述，仍然无法回答
"为什么选它、为什么不选另外两个"。本技能先固定字段与权重，再填表、淘汰、打分、给舍弃理由。

核心主张：**同一字段、同一单位、同一权重；算不出的维度留空并缩小归一范围，而不是给 0 分。**

## 何时使用

触发：用户给出多个候选方案/路线/版本，要求"比较并选一个 / 哪个更划算 / 评审前对照 /
在预算与档期内选型"；或题面带 `output_contract`、候选方案与资源/价格/档期合同。

不触发：只有一个方案（应做可行性评估）；要求原创设计新方案；要求文献综述或统计分析；
要求替代设备、安全、伦理审批。

## 输入

读取 `/input/case.json` 与同目录 `task.md`；材料按 `materials`/`files`/`inputs`/`resources`
定位（txt/md/csv/tsv/json/yaml/docx/xlsx/pdf）。**先打开真实文件**：设备能力、单价、货期、
预算、时间窗口都以文件为准。`case.json` 允许一层嵌套（`input`/`data`/`payload`），字段按别名表归一。

候选有两条通道，**结构化优先**：

1. `candidate_plans` / `plans` / `candidates` / `variants`（组织方常见格式，每项含
   `objective/variables/controls/procedure/parameters/resources/readout/cost/time/risks/evidence`）。
   直接按字段读取并保留 `case.json#候选路径` 作为证据定位，不要求另有材料文件。
2. 材料文件中的 `方案A/B/C`、`Plan 1/2/3`、`variant` 或按候选文件分组。

同一案例同时提供两者时，以结构化候选为准，并在 `input_mode` 写明来源。
`resource_contract`（价格/档期/可用性）与 `parameter_domains`（有限参数域）优先于文本报价与
`≤/max` 行；文本只作回退。输入 sha1 写入 `input_versions`，重复运行可核对版本。

开工前确认（缺失写进 `uncertainty`，不得默认）：

1. **候选清单**：几个方案、版本标识、各自在哪个文件或 case.json 路径。
2. **统一字段**：目标/假设、变量（自变量/因变量）、对照、步骤、参数（区间+来源）、资源、判读标准。
3. **硬约束**：设备可用性与档期、耗材可得性与货期、预算、时间窗口、安全/伦理审批。
4. **成本口径**：单价（元/盒、元/小时、元/人日）、机时费、人力工日、一次性 vs 按次、币种。
5. **输出契约**：`output_contract` 逐个记录（支持 `["field"]`、`[{name,type}]`、`{fields:[...]}`），
   `result.json` 全部回填。

## 执行流程

### 0. 一键端到端

```bash
python3 scripts/run_case.py --case /input/case.json --materials /input \
  --work /app/work --out /app/output
```

自动完成：契约归一化 → 材料索引 → 候选识别（结构化优先）→ 七字段填表 → 硬门控 →
加权评分与排名 → 选择/舍弃理由/敏感性 → `result.json` + `comparison_matrix.csv` +
`comparison_report.md`；同一输入跑两次并记录 `determinism`（草稿与矩阵哈希一致）。
材料与结构化候选都为空/不可读 → `status=blocked`，不产出"看起来合理"的选择。

### 1. 契约与索引

`python3 scripts/kernel.py init ...` → `work/contract.json`（含 `case_sha1`、`structured_candidates`）；
`kernel.py index ...` → `work/evidence.json`（每文件 sha1/字符数/可读性）。
未知字段名按别名表归一（`comparison`/`matrix` → `comparison_matrix`，`selection` → `recommendation`，
`risk_register` → `risks` 等）；契约字段对象里的 `type` 会写入缺失项说明。

### 2. 统一字段

`scripts/plan_compare.py` 先读 `candidate_plans`/`plans` 等结构化候选，按字段名别名填七字段；
没有结构化候选时再按方案头（`方案A/B/C`、`Plan 1/2/3`、`variant`、文件级 `plan_v1.md`）切块。
文本行先看行首标签（`目标：`、`资源：`、`风险：`…）决定字段，标签决定后不再因句中
"低成本""设备"等词改判；无标签时才按关键词优先级归类，仍无命中则进 evidence。
缺哪类就记 `missing_fields`，**不用通用流程文本填充**；`comparison_matrix` 的 `field_values`
保留每方案七字段的实际取值（CSV 同名列截断），不是只有"字段存在"标记。

### 3. 硬约束淘汰（先于打分）

| 门控 | 判定 |
|-|-|
| 资源不可得 | 结构化 `available=false`/停机/已满，或材料出现"缺货/未到货/无法预约"且资源名出现在该方案（方案自身风险叙述里的"已满"不当作全局合同） |
| 超预算 | 成本（优先用材料明确总额；无总额时用已知项之和）> 预算；`万元/千元/$` 先归一为 `元/USD` 再比较 |
| 参数越界 | 方案参数与 case.json 有限参数域按**参数名**比较；无域时回退材料 `参数 ≤/max` 同名上限 |
| 超时间窗口 | 方案总工期 > 材料/case.json 给出的窗口/截止 |

被淘汰方案不参与排名，但仍输出淘汰原因与替代路径。

### 4. 评分（透明、可复算）

默认权重：目标 0.20、可行性 0.25、成本 0.15、时间 0.15、风险 0.15、证据 0.10。
- 可行性：硬门控 → 0；成本完全无可解析数据 → 2；有缺价/未定域 → 3；全部核实 → 5。
- 成本/时间：**只在通过门控的幸存者内**做相对位次（最优 5，最差 2，数值相同者同名次且同分）；
  可比幸存者 <2 或成本币种不一致 → `null`，不跨币种排名，并在 `uncertainty` 说明。
- 风险：按"未缓解风险条数"扣分；无风险条目 → `null`（不当作满分）。
- 证据：带文件行号或 `case.json` 路径的来源条数，1+N 封顶 5。
- 加权分 = Σ(权重×得分) / Σ(可用权重)；公式与每项得分写入 `scoring`。

### 5. 选择与敏感性

选择通过门控且加权分最高者；对每个未选方案给出量化理由（硬约束明细或与最高分的差值）。
敏感性：给出次优反超所需的条件（权重变化或证据补强），两方案打平则要求补一条判别性证据。
全部淘汰 → `choice=no_feasible_plan`，`status=partial`，不硬选。

### 6. 输出与自检

`kernel.py emit` → `result.json`；`kernel.py check` 校验契约字段与工件（`comparison_report.md`、
`comparison_matrix.csv` 非空）。`validation.checks` 复算候选数、门控、成本、时间与加权分。

## 输出

`result.json`：`recommendation`、`comparison_matrix`、`plans`、`criteria`、`scoring`、`cost_model`、
`risks`、`exceptions`、`confirmations`、`evidence_map`、`assumptions`、`variables`、`controls`、
`procedure`、`parameters`、`resources`、`readout`、`validation`、`uncertainty`、`limits`、`changes`；
附带 `input_mode`、`input_versions`（case/材料 sha1）、`determinism`（两次运行哈希与一致性）、
`contract_source`。契约要求的别名字段（`selection`/`comparison`/`risk_register` 等）同时回填。

## 异常处理

| 情况 | 处置 |
|-|-|
| 无材料文件但有结构化候选 | 直接用 case.json 候选，`input_mode` 写明；不误判 blocked |
| 候选少于 2 个 | `status=partial`，说明无法横向比较，改走可行性评估 |
| 候选全部不可行 | `status=partial`、`choice=no_feasible_plan`，输出淘汰原因与放宽建议，不硬选 |
| 缺单价/工期 | 对应维度 `null` 且不参与归一，缺价时成本标"下限"；有明确总额则用总额 |
| 候选超过 20 个 | 只比较前 20 个，`status=partial` 并在 `limits/uncertainty` 写明未纳入数量 |
| 方案字段不全 | 记 `missing_fields`，对应维度不评分，不用模板文字凑数 |
| 设备不可得/档期冲突 | 该方案硬淘汰，附最近可预约替代或缩减版建议 |
| 成本币种不一致 | 不做跨币种位次，成本维度 `null` 并写入 `uncertainty` |
| 指标口径不一致 | 并列两个口径并标 `uncertainty`，不合并成单一分数 |
| 重复运行不一致 | 记录输入 sha1、运行参数与两次哈希；检查材料版本是否变化 |

## 最小调用示例（合成示例，非正式案例）

`case.json`（`output_contract` 含 `comparison`、`selection`，`candidate_plans` 三条 + 预算/参数域）
+ `plans.md`（方案A/B/C） + `price.md`（`磁珠试剂盒 1200 元/盒`、`预算 3000 元`）：

```bash
python3 scripts/run_case.py --case case.json --materials . --work work --out out
```

示意输出（节选，合成示例）：方案A 因"高速离心机停机"与"15000 rpm > 12000 rpm 上限"淘汰；
方案C 成本 3600 元 > 预算 3000 元淘汰；方案B 通过门控被选，`determinism.consistent=true`；
`input_mode=case.json:candidate_plans（3 个结构化候选）`。

## 限制

- 结构化候选按常见字段名读取；完全自定义字段名会落入 `missing_fields`，需在别名表补映射。
- 非结构化长文按"方案/Plan/版本"标题切分，可能漏切，需人工确认候选数。
- 成本只汇总写入的数量×单价；有明确总额时以总额为准（明细缺价不改变总额）；缺价且无总额才标下限，
  不做市场询价，不换算"管↔盒"这类未知包装关系。
- 工期只汇总写明的分步天数或总工期；**周→天按 ×7 换算**；未写明的排队/返工时间不计入。
- 金额单位 `万元/千元` 与 `元`、`$/USD` 先归一后再比较；不换算汇率（元↔USD 仍视为不可比）。
- 评分权重是显式默认值，不是领域真理；评审可按课题改权重，但必须写进 `scoring.weights`。
- 不判断科学假设真伪，不替代设备、安全、伦理审批。

## 改动记录

- **1.0.0**（2026-11-20）首版：七字段统一模板、四类硬门控、透明权重评分与权重归一、
  选择/逐条舍弃理由/敏感性；成本-工期复算与"总工期优先"去重；契约别名归一，未知字段不臆造。
- **1.2.0**（2026-11-25）实跑复现并修复：①`万元` 与 `元` 被当成不同币种而跳过预算门控 → 先归一金额；
  ②`{"value":2,"unit":"weeks"}` 与文本"2 周"按 ÷7 误算成 0.29 天 → 改为 ×7；
  ③成本给出明确总额但明细有缺价项时总额被丢弃 → 总额优先；
  ④相对位次对完全相同的成本/工期按枚举顺序给出 5 分 vs 2 分 → 同值同名次同分；
  ⑤候选超过 8 个被静默截断 → 上限 20 并写 `limits/uncertainty`（`status=partial`）；
  ⑥`available:"false"` 字符串不触发不可用门控 → 兼容字符串假值；
  ⑦重复方案 id 冲突 → 加 `#n` 后缀并记 `uncertainty`；⑧打平方案被写"低于" → 改为并列理由。
- **1.1.1**（2026-11-23）独立审查后的修正：已知成本已超预算时即使还有缺价项也淘汰；
  文本"资源："归入 resources 且每行只归一个字段；`cost:"4000 元"` 字符串可解析；
  blocked 也回填契约别名字段与 `determinism`；单候选改 `single_candidate`，不再宣称"最优"；
  成本未知时可行性不判 5；无幸存者/缺字段时校验结果改 `N/A`/`PARTIAL`。
- **1.1.0**（2026-11-22）读 case.json 结构化候选（`candidate_plans/plans`）与嵌套 case；
  矩阵输出七字段实际取值；成本/时间相对位次只在幸存者内，处理币种不一致；
  参数域按参数名匹配 case.json 全局域；支持 `[{name,type}]`/`{fields:[...]}` 契约；
  记录输入 sha1 与两次运行哈希；无材料但有结构化候选不再误判 blocked；单候选/全淘汰返回 partial。
