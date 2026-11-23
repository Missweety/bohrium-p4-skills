# 最小调用示例

> **合成示例，非官方案例。** 下列文献、编号、查询式与数字全部为演示接口而虚构，
> 不代表任何真实研究、数据库响应或官方测试结果。真实运行时必须以 `/input` 中的文件为准。

## 1. 输入

`/input/case.json`

```json
{
  "case_id": "demo-coverage-001",
  "output_contract": [
    "reference_set", "coverage", "matches", "misses",
    "miss_categories", "supplemental_search", "report", "limits", "status"
  ]
}
```

`/input/references.csv`

```csv
ref_id,doi,title,authors,year,include_reason,unavailable,miss_category
R1,10.1000/abc,Alpha Trial of X,Smith J; Doe A,2020,systematic review,,
R2,,Beta Study of Y,Brown K; Lee M,2021,guideline,,
R3,,Gamma Analysis,Zhao L,2019,review,retracted,
R4,10.1000/def,Delta Cohort,Wang H; Chen R,2022,review,,field_limit
R5,,Epsilon Review,Kim S,2023,expert list,,
R6,,Zeta Survey,Novak P,2018,review,,time_window
```

`/input/hits.csv`

```csv
record_id,doi,title,authors,year,query_id,source
H1,https://doi.org/10.1000/ABC,Alpha Trial of X,Smith John; Doe Alice,2020,Q1,crossref
H2,,Beta study of Y!!,Brown K; Lee M,2021,Q1,europepmc
H3,,Gamma Analysis,Zhao L,2019,Q2,pubmed
H4,,Delta Cohort Study,Wang H; Chen R,2022,Q2,pubmed
H5,,Epsilon Review,Kims S,2023,Q3,pubmed
```

## 2. 调用

```bash
python scripts/source_index.py extract --input /input --out /app/work/source-index.json
python scripts/coverage_audit.py --input /input --case /input/case.json --out /app/output
```

可选：把有证据的漏检分类与补检记录并入。

`/app/work/supplements.csv`

```csv
miss_category,proposed_query,executed,new_hits,yield,stop_reason,recovers_ref_ids
field_limit,"TI=delta AND AB=cohort",true,3,3,new hits exhausted,R4
time_window,"2017-2019",false,,,,
```

```bash
python scripts/coverage_audit.py --input /input --classify /app/work/classify.csv \
  --supplements /app/work/supplements.csv --case /input/case.json --out /app/output
```

## 3. 示意输出（节选）

`coverage.csv`

```csv
ref_id,status,match_method,matched_record_ids,match_reason,miss_category
R1,hit,doi,H1,exact normalised DOI match,
R2,hit,title_year_author,H2,normalised title + equal year + author jaccard 1.000 >= 0.85,
R4,miss,none,,no DOI match and no title+year+author match in supplied records,field_limit
R5,uncertain,none,,title and year match but author jaccard 0.000 < 0.85,
R6,miss,none,,no DOI match and no title+year+author match in supplied records,time_window
```

`result.json`（节选）

```json
{
 "case_id": "demo-coverage-001",
 "status": "ok",
 "coverage": {
  "denominator": 5,
  "hits": 2,
  "misses": 2,
  "uncertain": 1,
  "unavailable": 1,
  "coverage_rate": 0.4,
  "miss_rate": 0.4,
  "uncertain_rate": 0.2,
  "computable": true
 },
 "reference_set": {
  "total": 6,
  "included": 5,
  "unavailable_records": [
   {"ref_id": "R3", "reason": "retracted"}
  ]
 },
 "supplemental_search": {
  "executed_rounds": 1,
  "new_hits_total": 3,
  "residual_misses": ["R6"],
  "template_only": false
 }
}
```

解读：

- R1 通过 DOI 命中；R2 通过"标题+年份+作者"命中（标点与大小写差异已被规范化）。
- R3 为撤稿记录，单独列出并从分母排除，没有静默删除。
- R4、R6 为确认遗漏，分别归入 `field_limit` 与 `time_window`。
- R5 标题与年份相同但作者姓氏不一致（`Kims` vs `Kim`），判 `uncertain`，不计入命中。
- `field_limit` 补检已执行并补回 R4；`time_window` 补检只给出拟定查询式，因此 `executed=false`。

## 4. 反例（错误做法）

```text
错误 1：把 R5 算作命中 → 覆盖率被抬高到 60%，但作者并不一致。
错误 2：把 R3 从参考集中删掉且不说明 → 分母从 5 变成 4，复核时无法还原。
错误 3：撰写"已通过补充检索将遗漏降至 0" → 实际只执行了一轮补检，R6 仍未补回。
```

正确写法是保留 `uncertain` 与 `unavailable`，分别报告，并把未执行的补检标为拟定。

## 5. 空结果与缺文件

```bash
python scripts/coverage_audit.py --input /input --out /app/output
# 未识别到命中记录时：
# status=partial, coverage_rate=null, 每条参考记 uncertain 并说明原因
# 退出码 2
```

```bash
python scripts/coverage_audit.py --input /tmp/missing --out /app/output
# error: input path not found: /tmp/missing
# 退出码 1
```

## 6. 复跑

相同输入重复运行，`coverage.csv` 与 `audit.json` 的排序、字段和数值一致（不含时间戳）。
若输入变化，旧的 `contract_mapping` 与人工分类需要重新核对。
