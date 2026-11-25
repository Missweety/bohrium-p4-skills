---
name: reading-benchmark-builder
description: Build and run a source-conditioned reading benchmark with real hard items, gold answers, 0/1/2 rubrics, anti-leakage split, offline baselines, per-item scores and a re-runnable self-check. Use for 文献阅读 Benchmark / 题集 / 金标准 / 评测工具 / 评分锚点 / 防泄漏 / 基线与误差分析: given /input/case.json, task.md and the provided materials, it forges locatable items (numeric, table, absence, condition, definition, relation), enforces train/test separation, runs baselines, grades with rule-based rubrics and writes result.json, report.json and checks.json.
---

# 文献阅读 Benchmark 与评测工具（可判分 · 可复跑 · 可追溯）

版本 2.1.0

把一次真实的评测失败改成下一次可复核的对照：从**实际来源材料**构造难例，给出金标准与证据定位，固定评分规则，做训练/测试隔离，实跑基线并逐题记 0/1/2 分，最后给出可重算的报告与自检。**交付的是评测基础设施加真实产物，不是题单加截图。**

## 适用与不适用

- 适用：`/input` 下有 `case.json`、`task.md` 和真实材料（TXT/MD/CSV/TeX/HTML/DOCX/XLSX/PDF），题面要求文献阅读类基准、问答、提取、核验、题集或评测工具。
- 不适用：材料为空或全部无文本层（此时输出 `status=failed` 并说明）、需要联网补数据、需要把预制答案冒充运行结果。

## 调用方式

```bash
python3 /skills/weekly-skill/scripts/run_bench.py  --input /input --out /app/output --work /app/work
python3 /skills/weekly-skill/scripts/selfcheck.py  --input /input --out /app/output --work /app/work
```

脚本按自身绝对路径导入同目录模块，可在任意 cwd 执行；本地运行时把 `/skills/weekly-skill` 换成 `$SKILL_DIR`。`run_bench.py` 一条命令跑完：读入 → 建题 → 切分 → 基线作答 → 评分 → 报告 → `result.json`。`selfcheck.py` 独立复核，退出码非 0 必须修好后重跑，不得把失败结果当完成。

## 处理流程（顺序固定）

1. **读输入**：解析 `case.json` 的 `workorder`/`items`/`output_contract`；`questions` 只作为阅读问答（`readings`）逐条回答，不被当成建题工作单。读 `task.md`；扫描材料文件。每个来源记 `sha256`、可读性与抽取方式；读不出就记 `readable=false` 与原因，**不编造原文**。
2. **建单元**：段落与表格行都变成带定位的单元（`paragraph_id` / `table_id+row_index`，含字符偏移），这是后面所有定位的锚点体系。
3. **造难例**：`forge.py` 从单元生成 `numeric` / `table` / `absence` / `condition` / `definition` / `relation` 六类题。每题带：问题、金标准、可接受变体、证据引文与定位、0/1/2 锚点、难度与依据、数据授权。
   - 数值题只取句内**唯一**带单位量（含 `g`/`mg`/`%`/`°C` 等），且排除 `m-2`/`s-1` 这类指数片段，避免“gold=2 s”“问 22 °C 答 65%”这类不可判题。
   - `absence` 题的金标准是“未报告”，用来抓幻觉：编造数值必须判 0。
4. **防泄漏**：生成期先跑 `leak_check`（题干回显金标准/数值/证据长引文一律拒绝，拒绝记录写 `work/rejected_candidates.json`）；成品再跑一次终审。随后按 `sha256(unit_id)` 做 **dev/test 切分**：同一单元的全部题目整体落在同一侧，不丢题，同一引文不会跨两侧；`selfcheck.py` 重新计算并断言无交集。
5. **公开视图**：求解方只看到 `public_test_items.json`（`item_id`、问题、题型、字数上限），不含金标准、证据与评分锚点。
6. **跑基线**：`extractive`（带定位的检索式抽取）与 `naive`（无检索控制组）在测试集上作答，答案与运行配置分别落盘。
7. **规则评分**：`grade.py` 逐题给 0/1/2，必带 `rationale`、`failure_type`、命中锚点；缺金标准的题记 `ungradable` 并从汇总剔除，**不硬给分**。
8. **汇总与报告**：按题型/难度/Agent 汇总均分与 0/1/2 分布，列出失败样例；报告里每个数字都由本次评分记录重算得出。
9. **追溯**：`checks/trace.json` 记录 题目 → 答案文件(sha256) → 评分记录 的链条；`selfcheck.py` 校验哈希与重算一致性。

## 产物

| 文件 | 内容 |
|---|---|
| `/app/output/result.json` | 契约结果：`case_id`、`status`、`status_reason`、`benchmark`、`items`（题+金标准+证据+锚点）、`readings`、`evaluation`、`sources`、`uncertainty`、`change_log`、`checks`、`contract_fields`；运行时 `output_contract` 声明的额外字段同时写到**顶层**，未实现的置 `null` 并记入 `uncertainty` |
| `/app/output/report.json` | 各条件分数、对比、切分、覆盖率、泄漏审计、失败样例 |
| `/app/output/scores/<agent>.json` | 逐题 0/1/2 评分记录（含依据与失败类型） |
| `/app/output/runs/<agent>/` | 原始答案 + `run_config.json`（数据集哈希、单位哈希、预算） |
| `/app/output/checks/` | `rubric_selfcheck.json`、`trace.json` |
| `/app/output/checks.json` | `selfcheck.py` 的自检报告（PASS/FAIL 与逐项明细） |
| `/app/work/` | `dataset.json`（含金标准）、`split.json`、`public_test_items.json`、`rejected_candidates.json` |

## 评分口径（0/1/2）

| 分 | 含义 |
|---|---|
| 2 | 值与金标准一致（数值按值+单位等价比较），且定位命中证据单元/引文 |
| 1 | 值对但单位或定位缺失/不符；或核心内容部分覆盖 |
| 0 | 值错、空回答、超长不可判、复述题干、缺证据的拒绝回答、absence 题编造数值 |

`selfcheck.py` 会证明评分器非退化：金标准+自带定位必得 2，空回答必得 0，超长回答必得 0。

## 异常处理

| 情形 | 处置 |
|---|---|
| 无 `case.json` / 无可读材料 | `status=failed`，`uncertainty` 记 `case_file`，仍写 `result.json`，退出码 1 |
| 文件无文本层、损坏、超大 | 记 `unreadable_source` 与原因，其余材料继续，整体 `partial` |
| 材料可读但一题也造不出 | `status=partial` + `coverage_gap`，不伪造成 `failed`，也不拿模板题凑数 |
| 候选会泄漏答案 | 生成期拒绝并落盘；终审仍泄漏则丢弃该题 |
| 缺参考答案 | 记 `ungradable`，从汇总剔除，不静默补默认值 |
| 输出为空 / 超长 / 非对象 | 分别记 `empty_answer` / `answer_too_long` / `format_invalid`，得 0 |
| 案例声明了 `questions` 但检索无支持句 | 该问记 `status=unanswered` 并进 `uncertainty`，不编答案 |
| `output_contract` 有本包未实现的字段 | 输出 `null` 并列入 `uncertainty.unmapped_contract_fields`，不伪造内容 |

## 诚实规则（partial）

- `status` 只取 `success` / `partial` / `failed`；只有题量达标、来源全可读、五项检查全通过才可 `success`。
- 合成示例只用于演示接口，标的 `SYNTHETIC`，**不得当作正式测试集或官方案例结果**。
- 本包只报告本次实跑得到的分数；两条基线的差值只说明基线差异，**不是参赛者相对官方白板的增益**，也不代表官方评分。
- 不访问网络、不读 `.secrets`、不提交平台。

## 依赖与限制

- Python 3 标准库；可选 `pdftotext`（有则用，无则回退 zlib 文本流），无第三方依赖、无网络。
- 建题是规则驱动的，覆盖的是可定位、可判定的题型；开放式综述题不在范围内，遇到时如实说明不做。
- 版本：`dataset_version=reading-bench-v3`、`report_version=reading-report-v3`、技能版本 2.1.0。

最小调用示例见 `examples/README.md`（合成材料，仅演示接口）。

## 改动记录

- 2.0.0 建立六类建题、0/1/2 锚点、unit 级切分、离线基线、追溯链与独立 selfcheck。
- 2.1.0 修复三处真实缺陷：① 同单元多题时旧的切分逻辑会**静默丢题**并让 `split_disjoint=false`（一张表多列即触发）；改为整单元同侧、不丢题。② 数值题单位表漏 `g`，`1.42 g` 这类生物量从不建题；已补 `g`。③ `output_contract` 传 `{"fields": {...}}` 时只把 `fields` 当字段名、额外字段只落在 `contract_fields`；现递归识别并同时写顶层，未实现字段置 null 记入 uncertainty。另修正 `questions` 被误当建题工作单、absence 问句识别、可读但零题时的 `partial` 状态，以及文档统一 `python3` 与 `SKILL_DIR` 绝对路径。
