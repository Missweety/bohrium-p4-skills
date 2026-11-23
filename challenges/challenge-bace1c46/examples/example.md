# 最小调用示例

> **合成示例，非官方案例。** 下列文献、编号、引文、页码与等级全部为演示接口而虚构，
> 不代表任何真实研究或官方测试结果。真实运行时必须以 `/input` 中的原文与评价行为准。

## 1. 输入

`/input/case.json`

```json
{
  "case_id": "demo-appraisal-001",
  "output_contract": [
    "appraisal", "appraisal_table", "overall_summary",
    "domain_counts", "issues", "report", "limits", "status"
  ]
}
```

`/input/p1.pdf`、`/input/p2.pdf`（合成占位文献，非真实论文；本节正例引用 p1.pdf，
反例引用 p2.pdf。真实运行时替换为 `/input` 下实际存在的文献文件，否则会触发
`evidence_file_not_found` 警告）

`/input/appraisals.csv`（节选一项 RCT）

```csv
study_id,design,domain,judgement,evidence_file,evidence_locator,quote,note
S1,rct,randomization_process,low,p1.pdf,page:3,"Participants were randomised by a computer-generated sequence",adequate
S1,rct,deviations_from_intended_interventions,some_concerns,p1.pdf,page:4,"Two participants crossed over before week 4",open label
S1,rct,missing_outcome_data,low,p1.pdf,page:5,"Outcome data were available for 98% of participants",complete
S1,rct,measurement_of_outcome,low,p1.pdf,page:6,"Outcome assessors were blinded to allocation",blinded
S1,rct,selection_of_reported_result,high,p1.pdf,table:2,"The trial was stopped early for benefit",selective
```

## 2. 调用

```bash
python scripts/source_index.py extract --input /input --out /app/work/source-index.json
python scripts/quality_appraise.py --input /input --case /input/case.json --out /app/output
```

可选：带理由覆盖总体等级。

`/app/work/overrides.csv`

```csv
study_id,overall,reason
S1,high,提前终止与选择性报告使总体风险维持高风险
```

```bash
python scripts/quality_appraise.py --input /input --overrides /app/work/overrides.csv \
  --case /input/case.json --out /app/output
```

## 3. 示意输出（节选）

`appraisal.csv`

```csv
study_id,design,domain,judgement,evidence_file,evidence_locator,quote,evidence_ok,included_in_summary
S1,rct,randomization_process,low,p1.pdf,page:3,"Participants were randomised by a computer-generated sequence",true,true
S1,rct,deviations_from_intended_interventions,some_concerns,p1.pdf,page:4,"Two participants crossed over before week 4",true,true
S1,rct,missing_outcome_data,low,p1.pdf,page:5,"Outcome data were available for 98% of participants",true,true
S1,rct,measurement_of_outcome,low,p1.pdf,page:6,"Outcome assessors were blinded to allocation",true,true
S1,rct,selection_of_reported_result,high,p1.pdf,table:2,"The trial was stopped early for benefit",true,true
```

`result.json`（节选）

```json
{
 "case_id": "demo-appraisal-001",
 "status": "ok",
 "domain_counts": {
  "randomization_process": {"low": 1, "some_concerns": 0, "high": 0, "unclear": 0},
  "deviations_from_intended_interventions": {"low": 0, "some_concerns": 1, "high": 0, "unclear": 0},
  "selection_of_reported_result": {"low": 0, "some_concerns": 0, "high": 1, "unclear": 0}
 },
 "appraisal": [{
  "study_id": "S1",
  "design": "rct",
  "applicable_domains": ["randomization_process", "deviations_from_intended_interventions",
                         "missing_outcome_data", "measurement_of_outcome",
                         "selection_of_reported_result"],
  "present_domains": ["randomization_process", "deviations_from_intended_interventions",
                      "missing_outcome_data", "measurement_of_outcome",
                      "selection_of_reported_result"],
  "missing_domains": [],
  "counts": {"low": 3, "some_concerns": 1, "high": 1, "unclear": 0},
  "worst_domains": ["selection_of_reported_result"],
  "overall": "high",
  "overall_source": "worst_domain",
  "overall_reason": ""
 }],
 "issues": []
}
```

解读：

- 五个必填域齐全，每个非 `unclear` 判断都有页码/表格定位与逐字引文。
- 最差域是 `selection_of_reported_result=high`，因此 `overall=high`。
- `unclear` 若出现，不参与排序，也不会被当作 `low`。

## 4. 反例（错误做法）

输入：

```csv
study_id,design,domain,judgement,evidence_file,evidence_locator,quote,note
S2,rct,randomization_process,low,p2.pdf,3,"","not reported in abstract"
S2,rct,selection_of_reported_result,banana,p2.pdf,page:2,"All outcomes were reported",bad level
S2,observational,confounding,low,p2.pdf,page:1,"Age was adjusted",design conflict
```

预期问题：

```text
missing_quote             非 unclear 但引文为空
insufficient_evidence     非 unclear 但证据文件/定位/引文不全，不计入域计数与 overall
locator_without_unit      定位只有 3
short_quote               引文过短（若填写过短）
invalid_judgement         banana 不在词汇表
design_conflict           同一研究设计不一致
missing_domain            观察性研究缺 selection_of_participants 等必填域
```

S2 没有证据齐全的有效判断，`overall=unknown`，不会被补成一个等级。

错误写法：

```text
错误 1：因为摘要没写盲法，就把测量域判为 low → 应为 unclear。
错误 2：把"作者未报告盲法"写成 quote → 这是转述，不是原文。
错误 3：给 S2 填 overall=low 但不写理由 → 覆盖被拒绝，保留最差域。
错误 4：声称"已完成双人独立评价" → 实际只有一个人逐条核对。
```

## 5. 缺证据与设计不明

```bash
python scripts/quality_appraise.py --input /input --rows /app/work/appraisals.csv \
  --case /input/case.json --out /app/output
# 存在 missing_domain / missing_quote 等错误时：
# status=partial，issues.csv 列出每条问题，退出码 2
```

```bash
python scripts/quality_appraise.py --input /tmp/not-found --out /app/output
# error: input path not found: /tmp/not-found
# 同时写出 status=blocked 的 result.json（含已检查文件与原因）
# 退出码 1
```

## 6. 复跑

相同输入重复运行，`appraisal.json`、`appraisal.csv`、`issues.csv` 的行序、字段与计数一致
（不含时间戳）。修改原文证据或判断后，必须整表重跑，不能只改报告数字。
