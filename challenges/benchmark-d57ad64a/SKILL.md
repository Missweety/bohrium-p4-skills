---
name: writing-benchmark-builder
description: Build, judge and report a source-conditioned academic writing benchmark. Use for 学术写作 Benchmark / 写作评测 / 改写保真 / 引用映射 / 结构完整 / 事实与来源映射 / 版本与边界: read /input/case.json, task.md, materials and an optional draft.md, build judgeable writing items (fact preservation, section coverage, citation mapping, absence guard), score any draft with a rule rubric (0/1/2 + rationale + failure type), and write draft.md, facts.csv, citation_map.json, report.json, result.json and a re-runnable self-check.
---

# 学术写作 Benchmark 与评测工具（保真 · 可判 · 可追溯）

写作最容易的作弊是“读起来像论文”，最难的是“每个数字和限定条件都对得上来源”。本包把这一步变成可判分、可复跑、可复核的流程：**写作题来自真实材料，评分只认可观察证据，报告里的每个数字都能重算。**

## 适用与不适用

- 适用：`/input` 有 `case.json`、`task.md` 与真实材料（MD/TXT/CSV/TeX/HTML/DOCX/XLSX/PDF），题面要求改写、结构化成稿、引用映射、学术写作评测；或 `/input/draft.md` 已存在需要评分。
- 不适用：纯文风润色（无来源可核）、无材料可锚定的自由创作、需要联网补数据。

## 调用方式

```bash
# 第一次：建题并生成单位索引（供写稿时放锚点）
python3 scripts/run_case.py --input /input --out /app/output --work /app/work
# 写完稿后：把稿子放到 /input/draft.md 或 --draft 指定，重跑
python3 scripts/run_case.py --input /input --out /app/output --work /app/work --draft /input/draft.md
# 独立复核
python3 scripts/selfcheck.py --input /input --out /app/output --work /app/work
```

`work/units.json` 给出每个来源单元的 `unit_id`（如 `materials.md#P4`）与内容，写稿时据此放 `[src: <unit_id>]`；`work/public_items.json` 是去掉金标准的题面视图。

## 处理流程（顺序固定）

1. **读输入**：解析 `case.json`（`audience`、`required_sections`、`max_chars`、`output_contract`）、`task.md`、材料；每个来源记 `sha256`、可读性与抽取方式。`/input/draft.md` **不作为来源**（否则等于拿稿子给自己判分）。
2. **建单元**：段落、表格行都带定位（`paragraph_id` / `table_id+row_index`），作为全部锚点。
3. **建写作题**（`build_dataset.py`，四族）：
   - `fact_preserve`：改写指定段落，必须保留全部数值、单位与限定条件，不得出现材料外数字，不得整段照搬；
   - `section_coverage`：按必需小节成稿，每节至少一条带锚点的事实；
   - `citation_map`：指定主张必须出现，且锚点指向支持它的单元；
   - `absence_guard`：材料未报告的结果不得编造，须明确写出未报告并给否定证据锚点。
4. **金标准**：全部取自来源原文；数值按“值+单位”规范化比较；`document_numbers` 记录全文数值集合，用来判定“材料外数字”。
5. **写稿/收稿**：无外部稿时用 `source-anchored extractive writer` 产出可编辑的 `draft.md`（底线稿），并同时跑 `template` 控制组；有外部稿则只评分该稿（仍保留两控制组做对照）。
6. **评分**（`grade.py`）：逐题 0/1/2，必带 `rationale`、`failure_type`、`matched_anchor`；缺金标准的题记 `ungradable` 并从汇总剔除。
7. **产物与报告**：`draft.md`、`facts.csv`（每条必需事实→来源定位→是否在稿中）、`citation_map.json`（主张→锚点→是否落稿）、`report.json`（各条件分数、对比、失败样例）、`result.json`（契约字段、`uncertainty`、`change_log`）。
8. **自检**（`selfcheck.py`）：重建数据集比对哈希、重评稿子比对分数、重算报告聚合、检查事实映射与锚点真实存在。

## 评分口径（0/1/2）

| 题型 | 2 分 | 1 分 | 0 分 |
|---|---|---|---|
| 事实保真 | 数值/单位全保留、无限定条件丢失、无材料外数字、非整段照搬 | ≥2/3 保留；或保留但混入材料外数字/丢条件/照搬 ≥30 词 | 保留 <2/3、超长、空稿 |
| 结构完整 | 小节全在且过半带有效锚点 | 覆盖 ≥1/2，或全在但无锚点 | 覆盖 <1/2 |
| 引用映射 | 每条主张都在且锚点正确 | 覆盖率 ≥50% | 覆盖率 <50% |
| 未报告项 | 明确写出未报告并带否定锚点 | 没编造但没说明 | 为该主题编造数值/结论 |

`selfcheck.py` 用“仅由金标准构造的完美稿”验证评分器非退化：完美稿必得 2，空稿必得 0。

## 产物

| 文件 | 内容 |
|---|---|
| `draft.md` | 可编辑交付稿（外部稿原样落地，或溯源底线稿） |
| `facts.csv` | 必需事实、值/单位、来源定位、`present_in_draft` |
| `citation_map.json` | 主张→`unit_id`/locator/quote、`anchored_in_draft` |
| `result.json` | `case_id`、`status`、`deliverable`、`fact_source_map`、`citation_map`、`benchmark`、`evaluation`、`sources`、`uncertainty`、`change_log`、`checks`、`contract_fields` |
| `report.json` | 各条件分数、对比、覆盖、泄漏检查、失败样例 |
| `scores/<condition>.json` | 逐题 0/1/2 记录（含依据与失败类型） |
| `runs/<condition>/draft.json` | 每个条件的稿子与其 sha256 |
| `checks/` | `rubric_selfcheck.json`、`trace.json` |
| `checks.json` | 自检报告（PASS/FAIL 与逐项明细） |
| `work/` | `dataset.json`（含金标准）、`units.json`、`public_items.json` |

## 异常处理

| 情形 | 处置 |
|---|---|
| 无 `case.json`/材料 | `status=failed`，`uncertainty` 记 `case_file`/`no_items`，仍写 `result.json`，退出码 1 |
| 声明了 `draft_path` 但文件不存在/为空 | 记 `empty_provided_draft`，退回溯源底线稿并如实标注 |
| 材料无文本层/损坏 | 记 `unreadable_source`，其余继续，整体 `partial` |
| 来源无可用测量值 | 少建事实题，`by_type` 如实反映，不编造数值题 |
| 数值单位写法不同 | 走单位规范化表比较；表外单位按字面比较，并记入方法边界 |
| 稿件整段照搬 | 记 `verbatim_copy`，最高 1 分 |
| 缺金标准 | 记 `ungradable`，从汇总剔除，不默认给分 |
| `output_contract` 有未实现字段 | 输出 `null` 并列入 `uncertainty.unmapped_contract_fields` |

## 诚实规则（partial）

- `status` 只取 `success`/`partial`/`failed`；只有题量达标、来源全可读、六项检查全通过且事实全部落稿才 `success`。
- 本包只报告本次实跑分数。`extractive_writer` 与 `template` 的差值只说明“带锚点/无锚点”的差别，**不是参赛者相对官方白板的增益**。
- 规则评分只管保真、结构、引用与不编造，**不评价文风与可读性**；需要文风判断时在报告里声明并由人工复核。
- 合成示例标 `SYNTHETIC`，不得冒充正式测试集或官方案例结果。
- 不访问网络、不读 `.secrets`、不提交平台。

## 依赖与限制

- Python 3 标准库；可选 `pdftotext`。无第三方依赖、无网络。
- 版本：`dataset_version=writing-bench-v2`、`report_version=writing-report-v2`。

最小示例见 `examples/README.md`（合成材料）。
