---
name: experiment-plan-designer
description: 依据给定研究目标、材料与资源/预算/排期约束，生成并优化可执行的实验方案：可检验假设、变量操作定义、对照组合、设备与耗材、参数区间及依据、样本量依据、时间与成本算术、风险判据与备选路径，给出 3 个可比候选方案并推荐，用脚本核对六类要素齐备、参数依据与取值可回溯、预算/工时算术与冲突，输出方案正文、依据表、风险预案与待确认项。适用于有目标与约束的实验规划与方案评审；不适用于替代安全伦理审查、文献综述，也不允许伪造设备规格、报价或预实验结论。
version: 1.3.0
license: MIT
---

# 实验方案生成与优化：提出方案，也说明依据和风险

把"设计一个实验"拆成 **目标 → 可检验假设 → 变量操作化 → 对照 → 参数与依据 → 样本量与资源算术 →
风险预案 → 三版候选与择优**。
核心主张：方案里每个参数要么能指回材料/设备手册/组织方约束，要么明确标 `assumed` 并给出敏感性；
每个对照都要说清"排除哪一类混杂"；工时与预算必须能算平；**没做过的预实验不能写成做过**。

## 何时使用

触发：用户给出研究目标、体系/材料、可用设备与预算排期，要求"设计实验方案 / 优化实验设计 /
比较几套方案 / 补对照 / 估算样本量与成本 / 做风险预案 / 评审一份实验计划"；或题面带
`output_contract`、资源清单、价格表、设备排期。

不触发：要求代写论文、做统计分析建模、写文献综述；要求替代伦理/安全审查或签字；
要求编造设备报价、供应商货期或"已验证可行"的结论；纯试剂采购清单（无研究问题）。

## 输入

执行时读取 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`；
研究背景、设备清单、价格表、排期表、已有数据按 `materials`/`files`/`inputs` 定位。
**先打开真实文件**：设备量程、耗材规格、单价与可用时段都以文件为准。

开工前确认（缺失写 `uncertainty`，不许默认）：

1. **研究目标与判读终点**：要回答什么科学问题，什么结果算支持/否定假设。
2. **约束**：总预算与币种、可用设备与时段、人员与单次时长、样本来源与数量上限、截止时间。
3. **已有数据**：是否有历史批次、文献效应量可作样本量依据（没有就标 `assumed`）。
4. **输出契约**：`case.json.output_contract` 字段名逐个记录，`result.json` 全部回填。

## 真实工作单优先与数值审查（v1.2）

本题具体工作单提供真实科学资料、有限参数域、资源/价格/预约合同和三套已有版本：必须先打开原始资料和全部已有版本，逐版保留修订轨迹；依据实际合同修订三版，不能凭空重建或把预测响应写成实测。对每项参数、价格、排期、版本变化填写实际文档和位置。有限域内逐项检验、分别计算各版总价，按设备时间窗和互斥性核验预约冲突，记录不可行项与候选取舍。严格遵循案例的版本数、控制组、步骤及输出格式；示范数目不是一律适用的门槛。`design_checklist.py` 为历史辅助规则，不能用其固定5步骤、2对照等判断覆盖案例实际要求。

可用 `python scripts/scenario_audit.py --input work/scenarios.json --out work/scenario-audit.json` 复核：格式参见 `references/scenario-audit.md`。它仅检验Agent从材料录入的有限域、逐版价格和设备独占预约，不能核实录入值与来源一致，也无法证明实际可行性；缺价格/预约或统计依赖时为partial。两独立组等方差双侧t检验功效选项采用statsmodels，输出计算前提、效应及来源；不满足适用条件不得套用。统计库缺失时，使用环境可用工具手算/复核或如实标未验证。最后按案例输出契约字段实际写入 result.json，不以默认模板代替。


## 可核验的对照、敏感性和资源权衡（iter3 改进）

- 对每个适用对照说明要排除的混杂、如何观测其是否有效、材料支持的判据和失败时替代方案；材料无数值阈值时写待确认，不能编造仪器精度或判据，也不把每个对照固定要求数值。
- 对假设参数建立「取值变化 → 预期影响的比较量 → 何时改选方案」的敏感性表；仅在有模型或数据支持时计算数值变化，缺信息时标定性及待验证。不得把预测当测量结果。
- 对每个候选方案从实际预约合同、单次设备占用、样本可用量和并行约束计算关键路径及剩余时间；区分串行与并行，不确定依赖先标未验证，不凭空设可用资源。逐项标合同/表格位置，标出冲突与可行备选。
- 对三版保留统一比较表（预算、所需时段、判读能力与风险），推荐理由引用可复算的真实约束与取舍；无法计算功效时标未验证，不能为了凑理由编造效果量或功效。
- 本包 `design_checklist.py` 是历史辅助工具：它含固定步数和对照数量等规则，使用前对照当前实际任务；与真实执行契约相矛盾的项记为不适用，并人工复核，不以脚本PASS代替科学评估。`scenario_audit.py` 检查录入值的算术/约束，不自动验证来源。

## 执行流程

1. **契约**：`python scripts/kernel.py init --case /input/case.json --out work` → `work/contract.json`。
   **先读组织方契约件**：`/input` 下的 `execution-contract*`、`interface-example*`（含 json/md/yaml）
   逐条记录字段名、必交工件、单位与币种；与 `output_contract` 冲突时以题面/执行契约为准并写进 `changes`。
2. **材料索引**：`python scripts/kernel.py index --materials /input --out work`
   → `work/evidence.json` + `work/corpus.txt`；设备手册/价格表/排期表是否真读到要如实记录。
3. **目标 → 假设**：写 `work/plan.json` 的 `hypothesis`：`statement`（可检验）、`direction`
   （预期方向）、`falsify_if`（什么结果算否定）、`endpoint`（主判读指标）。
   假设必须能被一次实验否定；写不出 `falsify_if` 说明还没想清。
4. **变量操作化**：`variables.independent`（水平、如何设置）、`variables.dependent`
   （仪器、单位、采样方式）、`variables.confounders`（混杂 + 控制手段：区组/随机化/配对/归一化）。
   每个变量给**操作定义**（怎么设、怎么测、单位），不是只给名字。
5. **对照**：按现场任务和科学设计选择适用对照，每类写 `excludes`（排除哪一类混杂）：
   阴性/空白（排除基线与非特异信号）、阳性（证明体系有响应能力）、载体/溶剂（排除辅料效应）、
   剂量梯度（证明剂量依赖而非阈值偶然）。对照不足时具体解释哪些混杂无法排除，不把数量当成普遍规则。
6. **参数与依据**：`parameters` 逐项写 `name/value/unit/range/basis/source/action`。
   `basis` 只能取 `equipment_spec` / `organizer_contract` / `literature_in_material` / `assumed`。
   前三类必须给 `source` 定位且取值能在材料中找到；`assumed` 必须写依据假设 + 敏感性
   （取值±X% 时结论是否翻转）。**不存在"preexperiment"依据**：没做过就是没做过。
7. **可执行步骤**：`steps` 数量依真实任务确定，每步 `{id, action, params[], resources[], readout, duration_h}`。
   每步必须绑定第 6 步里的参数名、具体资源与一个判读动作；写不出判读的动作不是一步实验。
   **禁止**"准备样品—设置对照—检测分析—统计分析"式目录，动作里要含体系、对象与操作量。
8. **样本量与功效**：`sample_size` 给 `n_per_group`、`groups`、`basis`。
   `basis=power` 时必须列 `alpha/power/effect_size/sd` 与效应量来源；无来源则降级为 `assumed`
   并给区间与"最小可检出差异"含义。**不许声称"预实验确定 n"**。
9. **资源与算术**：`resources` 写设备（型号、单次占用 h、可用窗口 h）与耗材（规格、数量、单价）；
   `budget` 写 `total/cap/currency`；`schedule` 写 `sessions/hours_per_session/total_hours/window_hours`。
   算术必须自洽：耗材小计 = Σ(数量×单价)，`total ≤ cap`，设备占用 ≤ 窗口，总工时 ≤ 时间窗；
   价格与可用时段优先取组织方价格表/排期表原文，取不到才按 `assumed` 处理。
10. **风险与备选**：`risks` 按场景需要覆盖无信号、污染/批间差、重复性差、样本不足、设备不可用；
    每条写 `mode → indicator（早期可观测信号）→ threshold（判据）→ stop_loss（止损点）→ fallback（替代路径）`。
    材料提供具体阈值时写数值与单位及来源；未提供时标待确认，不得编造。只写“注意安全”不足以说明风险处理。
    写完后运行 `python scripts/failure_chain.py --plan work/plan.json --out work`：
    - 按步骤顺序计算失败影响面（阻塞后续哪些步骤）、早期信号、判据、止损与备选；
    - 无备选且阻塞后续的步骤标 `P0`，有备选标 `P1`，仅影响本步标 `P2`；
    - 汇总 P0/P1 各重试一次的总时长，与 `schedule.window_hours` 比对，超窗必须在方案里改步骤或砍范围，
      不能改数字凑平；未映射风险的步骤会列入 `unmapped_steps`，需补 failure mode 或说明为何无需。
    - 产物 `work/failure_chain.json` 与 `work/failure_chain.md`（表：步骤/信号/判据/止损/备选/阻塞/优先级）。
11. **三版候选与择优**：`versions` 给 A（基线）/B（预算约束版）/C（功效优先版），
    每版写 `n_per_group/cost/hours/changes`，用同一算口径比较；`changes` 要说清改了哪个设计量，
    三版不得只在措辞上不同；`recommendation` 给 id、理由与 `sacrifice`（牺牲了什么）。
12. **机器校验**：
    `python scripts/design_checklist.py --plan work/plan.json --corpus work/corpus.txt --plan-md work/plan.md --out work`
    检查六类要素、步骤绑定、依据标注与取值回溯（数字按原文/数值 token 容错）、算术、版本差异、
    通用话术与预实验措辞；退出码非 0 时逐项检查；不适用的固定数量规则仅标记为不适用，不改变合理方案以迎合脚本。
13. **成稿与产出**：写 `work/plan.md` 与 `work/draft.json`，
    `python scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output`
    → `result.json`；`plan.md`、`plan.json`、`checklist.md`、`basis_table.csv`、
    `failure_chain.md`（失败链与止损优先级）一并放 `/app/output/`。
14. **收尾**：`python scripts/kernel.py check --out /app/output --contract-dir work` 必须 PASS
    （逐项核对契约字段与必交工件，而不只是 case_id/status）；
    回读一遍预算与工时，确认与材料中的价格/排期一致。

## 六类要素的判定口径

| 要素 | 合格标准 | 反例 |
|-|-|-|
| 假设与变量 | 假设可证伪；变量有操作定义、单位、测量方式 | "考察不同条件的影响"（无条件、无水平） |
| 对照组 | ≥2 类，且每条说明排除哪类混杂 | 只有空白组，无阳性对照 |
| 设备材料 | 型号/量程/规格/数量落到可采购单位；标不可替代项 | "用离心机离心" |
| 时间成本 | 单次时长 × 批次 ≤ 时间窗；小计 = Σ 数量×单价 ≤ 预算 | 只写"约一天"、无币种 |
| 参数范围 | 值 + 单位 + 允许区间 + 越界处置 + 依据来源 | "温度 80 度左右"（无量程依据） |
| 风险与异常 | 失败模式 + 早期指标 + 判据 + 止损 + 备选 | "注意安全，严格操作" |

## 硬性禁止

- 不伪造设备型号、量程、供应商报价、货期、排期余量或耗材规格。
- 不声称做过预实验/试跑/已获伦理或安全批准；`basis` 中不得出现预实验。
- 不把 `assumed` 参数写成有依据；不在算术算不平的情况下交付（先改方案，不改数字）。
- 不删掉阴性/阳性对照来"省预算"而不说明牺牲了什么。
- 不跳过安全、伦理、设备可用性确认项；涉及人/动物样本时必须列伦理确认。
- 不把方案写成步骤目录：每一步必须绑定参数、资源与判读。
- 不提交预制答案；所有数值与建议必须由本次读取的材料与约束推导。

## 输出

`/app/output/`：`result.json`（契约字段全回填 + `case_id`；本 Skill 附加字段 `plan`、
`plan_versions`、`recommendation`、`parameter_basis`、`resource_arithmetic`、`risks`、
`confirmations`、`self_check`，见 `references/output-contract.md`）+ `plan.md`（可执行方案正文）+
`plan.json`（机器可读）+ `checklist.md`（要素/依据/算术校验）+ `basis_table.csv`（参数依据表）。

`status`：`ok` = 六类要素齐备、算术自洽、依据可回溯；`partial` = 缺设备/价格/排期信息导致部分
参数只能 `assumed`（必须在 `limits` 列出）；`blocked` = 目标或约束缺失无法成案；`refused` =
要求编造数据/替代伦理审查。

## 异常与降级

| 情况 | 处理 |
|-|-|
| 设备参数/价格缺失 | 参数标 `assumed` + 敏感性区间，`uncertainty` 列缺哪份材料；不编型号与报价 |
| 时间窗与样本量冲突 | 给两版方案（减 n / 加批次）并说明功效损失；不静默缩样本 |
| 试剂缺货/设备排期已满 | 给可替代项与不可替代项，改期或改设计写进 `versions` |
| 预算不足 | 按"保对照、保重复、砍辅助指标"的顺序裁剪，列被砍项及影响 |
| 目标本身不可检验 | `status: blocked`，指出缺哪个可测终点，不硬凑方案 |
| 涉及人/动物/生物安全 | 列伦理与安全确认项，方案标"待批"，不写成可立即执行 |
| 材料内部冲突（两份价格表不一致） | 两值都保留，标 `conflict`，按较高值做预算并注明 |
| 预算耗尽（64 请求/900s） | 先落盘一版可行方案，`status: partial` + `limits` |
| python 不可用 | 手工核对算术与要素，`limits` 注明降级 |

## 文件说明

- `scripts/kernel.py`：init / index / verify / emit / check，仅标准库，无网络。
- `scripts/design_checklist.py`：六类要素、依据标注、取值回溯、预算/工时算术、版本与措辞校验。
- `scripts/section_audit.py`：核对方案正文的章节完整性与数字绑定（审自己的成稿用）。
- `references/design-controls.md`：对照设计矩阵、参数依据分级、风险预案写法与反例。
- `references/output-contract.md`：默认输出字段；题面 `output_contract` 优先。
- `references/example.md`：示意输入/输出（示例，非正式案例答案）。

## 最小调用示例

```bash
python scripts/kernel.py init --case /input/case.json --out work
python scripts/kernel.py index --materials /input --out work
# 按 references/design-controls.md 生成 work/plan.json（示意见 references/example.md）
python scripts/design_checklist.py --plan work/plan.json --corpus work/corpus.txt --out work
python scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output
python scripts/kernel.py check --out /app/output
```

示意输出（示例）：3 版方案（A 基线 / B 省预算 / C 提功效），推荐 B；
校验 0 error、2 warning（2 个参数为 `assumed`、缺设备排期原件）；
预算 4,180 ≤ 5,000，总工时 12 h ≤ 14 h 时间窗。

## 改动记录

### v1.1.0（因 #89149 harbor_reward 0.40 迭代）

- **可机检项（主因）**：原 `kernel.py check` 只查 `case_id`/`status`，契约字段缺失、`plan.md`/`plan.json`/
  `checklist.md`/`basis_table.csv` 缺失都能“PASS”，与题面“结果可核验性”直接冲突。现逐项核对
  `contract.json` 承诺字段、四个必交工件与 `partial` 的 `limits`，任一缺失即 FAIL。
- **任务完成度**：原流程没有“步骤”这一层，方案容易退回目录式写法。现在 `plan.steps` 至少 5 步，
  每步必须绑定参数名、资源、判读动作与时长；`design_checklist.py` 校验参数引用存在性、时长与排期一致。
- **结果正确性**：`parameters` 强制 `range` + 越界 `action`，风险阈值要求可观测；三版候选必须真的改变
  `n/cost/hours`，`recommendation` 必须写 `sacrifice`，避免“三版同质”。
- **输入兼容性**：参数取值回溯改为原文命中 → 数值 token 容错 → 缺失告警三级，兼容 `40–120` 与 `40-120`、
  全角逗号等写法，减少把有依据的参数误判为 `assumed`；流程要求先读 `/input` 的
  `execution-contract*` 与 `interface-example*`。
- **降级路径**：缺契约件时退回默认契约并在报告里警告；缺价格/排期仍按 `assumed` + 敏感性处理，不编造。

## 改动记录

- 1.3.0 新增 `failure_chain.py`：把 `steps` 与 `risks` 编成失败链表，计算每一步失败对后续步骤的阻塞面、
  早期信号、判据、止损与备选，按有无备选给出 P0/P1/P2，并用"P0/P1 各重试一次"的时长与时间窗比对。
  只做编排与算术提示，不验证科学可行性，也不替代安全/伦理审查；超窗要求改方案而不是改数字。
