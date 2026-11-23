# 最小调用示例（合成示例，非官方案例）

> 以下专利号、申请号、优先权、申请人、状态与路径全部为合成占位符，仅用于说明接口和流程。它们不是任何官方固定案例的数据，也不是预期答案。

## 1. 合成输入 `/app/work/records.csv`

```csv
number,jurisdiction,kind,application_no,priority,family_id,title,assignee,status,status_date,source_file,locator,legal_scope
"US 10,123,456 B2",US,B2,16/123456,US 15/111,111,Synthetic widget,Acme,Active,2024-01-01,uspto.pdf,page:1,official
US10123456B2,US,B2,16/123456,US 15/111,111,Synthetic widget,Acme,Expired,2020-01-01,google-patents.html,page:1,secondary
EP1234567A1,EP,A1,EP21123456,EP21123456,EP-FAM,Synthetic method,Beta,Granted,2023/05/06,epo.pdf,page:2,official
```

## 2. 调用

```sh
cd /skills/weekly-skill
python3 scripts/source_index.py extract --input /input --out /app/work/source-index.json
python3 scripts/patent_normalize.py --input /app/work/records.csv \
    --out /app/work/patent-normalize --as-of "$(date +%F)" --max-status-age-days 180
```

退出码为 `2` 表示“完成但有问题”，不是运行失败；本次因同一号码的 `Active`/`Expired` 冲突、聚合站来源和状态日期过旧而产生警告。

## 3. 合成输出摘录

`/app/work/patent-normalize/normalized.csv`（节选列）：

```csv
record_id,number_input,normalized,jurisdiction,kind,priorities,family_cluster,status_class,source_class,evidence_strength,duplicate_of,flags
R0001,EP1234567A1,EP1234567A1,EP,A1,EP21123456,FAM-001,active,official,high,,status_stale
R0002,US10123456B2,US10123456B2,US,B2,US15111,FAM-002,expired,secondary,medium,R0003,duplicate_record;source_secondary;status_conflict;status_inactive;status_stale
R0003,"US 10,123,456 B2",US10123456B2,US,B2,US15111,FAM-002,active,official,high,,status_conflict;status_stale
```

`/app/work/patent-normalize/families.json`（节选）：

```json
{
  "status": "issues",
  "as_of": "YYYY-MM-DD（运行时 date +%F）",
  "counts": {"records_total": 3, "families": 2, "duplicates": 1,
             "official_sources": 2, "secondary_sources": 1},
  "families": [
    {"family_id": "FAM-001", "scope": "declared_family",
     "declared_family_ids": ["EP-FAM"], "priority_numbers": ["EP21123456"],
     "member_count": 1, "distinct_publications": 1},
    {"family_id": "FAM-002", "scope": "declared_family",
     "declared_family_ids": ["111"], "priority_numbers": ["US15111"],
     "member_count": 2, "distinct_publications": 1}
  ]
}
```

注意：`FAM-002` 有两条记录但只有 1 件不同公开物，因为其中一条是同一号码的重复导出。族编号 `FAM-00x` 是本次运行的确定性编号，不是官方族号。示例中 `families.json` 的 `status` 是脚本运行状态，映射到 `result.json` 时写作 `run_status`；记录级法律状态写作 `legal_status`。

## 4. 合成 `claims.csv`

```csv
record_id,claim_version,claim_no,claim_type,claim_text_locator,scope_note,source_file,locator,retrieved_date
R0003,application_publication,1,independent,"page:3, col.1, para.2","仅记录公开文本表述，未作范围解释","uspto.pdf","page:3","YYYY-MM-DD（运行时）"
```

## 5. 合成 `result.json` 映射片段

```json
{
  "case_id": "<运行时从 /input/case.json 读取>",
  "run_status": "partial",
  "results": [
    {"record_id": "R0003", "normalized": "US10123456B2", "jurisdiction": "US",
     "kind": "B2", "legal_status": "Active", "status_class": "active",
     "source_class": "official", "evidence_strength": "high",
     "evidence": [{"source_file": "uspto.pdf", "locator": "page:1"}]}
  ],
  "families": [{"family_id": "FAM-001", "scope": "declared_family"}],
  "claims": [],
  "counts": {"records_total": 3, "families": 2},
  "uncertainty": ["合成示例，未访问任何官方登记库", "状态时效仅按 as-of 估算"],
  "report_path": "/app/output/report.md"
}
```

实际案例必须读取其 `output_contract`，按契约字段名和类型替换上述键；不得直接复用本示例的号码、族号、状态或结论。
