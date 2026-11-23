# 最小调用示例（合成示例，非官方案例）

> 本页 DOI、PMID、标题、作者、库名和数值全部虚构，只用于说明接口与输出形状，
> 不是平台固定案例的答案，也不代表任何真实数据库返回或真实论文。

## 1. 输入

`/input/case.json`（合成）：

```json
{
  "case_id": "synthetic-merge-example",
  "queries": [
    {"source_db": "crossref", "query": "synthetic widget study"},
    {"source_db": "europepmc", "query": "widget"}
  ],
  "source_status": [
    {"source_db": "crossref", "status": "ok"},
    {"source_db": "europepmc", "status": "ok"},
    {"source_db": "pubmed", "status": "timeout", "error": "synthetic timeout"}
  ],
  "records": [
    {"source_db": "crossref", "doi": "https://doi.org/10.9999/ABC.1",
     "title": "A Synthetic Widget Study", "authors": "Smith, John",
     "year": 2020, "journal": "Journal of Widgets", "type": "journal-article",
     "priority": 1, "raw_file": "crossref.json", "raw_locator": "records[0]",
     "query": "synthetic widget study"},
    {"source_db": "europepmc", "doi": "doi:10.9999/abc.1", "pmid": "12345678",
     "title": "A synthetic widget study.", "authors": "John Smith",
     "year": "2020", "journal": "Journal of Widget Studies",
     "type": "Journal Article", "priority": 2,
     "raw_file": "europepmc.json", "raw_locator": "records[0]"},
    {"source_db": "crossref", "doi": "10.9999/xyz.2",
     "title": "Parallel Widget Methods", "authors": "Lee, Kim",
     "year": 2019, "journal": "unknown", "type": "preprint", "priority": 1}
  ],
  "output_contract": {"fields": ["case_id", "status", "merged_result",
                                 "conflicts", "coverage", "limitations"]}
}
```

`europepmc` 的 DOI 带 `doi:` 前缀和大写，`crossref` 的 DOI 带 URL 前缀；两者规范化后相同。
`journal` 的 `unknown` 是"库明确未知"，不是"缺失"。

## 2. 调用

```bash
python3 scripts/source_index.py extract --input /input --out /app/work/source-index.json
python3 scripts/merge_records.py --input /input --out /app/work/merged \
  --fuzzy-threshold 0.9 --year-tolerance 1 --priority-order crossref,europepmc
```

预期退出码 2（存在 `pubmed` 实质缺口），仍生成全部产物。

## 3. 示意输出（节选，虚构）

`merged.json`：

```json
{
  "stats": {"record_rows_read": 3, "records_valid": 3, "records_dropped": 0,
            "clusters": 2, "multi_record_clusters": 1, "exact_groups": 1,
            "fuzzy_candidates": 0, "conflicts": 2, "sources": 2, "gaps": 1},
  "gaps": [{"source_db": "pubmed", "gap": "source_unavailable_or_incomplete",
            "detail": "synthetic timeout"}],
  "records": [
    {"cluster_id": "M0001", "record_ids": ["R00001", "R00002"],
     "source_dbs": ["crossref", "europepmc"], "record_count": 2,
     "identity": {"doi": "10.9999/abc.1", "pmid": "12345678",
                  "title": "A Synthetic Widget Study", "year": 2020},
     "fields": {
       "doi": {"value": "10.9999/abc.1", "status": "present",
               "source_db": "crossref", "raw_locator": "records[0]",
               "source_record": "R00001"},
       "pmid": {"value": "12345678", "status": "present",
                "source_db": "europepmc", "raw_locator": "records[0]",
                "source_record": "R00002"},
       "journal": {"value": "Journal of Widgets", "status": "present",
                   "source_db": "crossref"}
     },
     "conflicts": [
       {"field": "journal", "chosen_value": "Journal of Widgets",
        "other_value": "Journal of Widget Studies", "other_sources": "europepmc"}
     ]},
    {"cluster_id": "M0002", "record_ids": ["R00003"],
     "source_dbs": ["crossref"], "record_count": 1,
     "fields": {"journal": {"value": null, "status": "unknown"}}}
  ]
}
```

`duplicates.csv`（节选）：

```csv
group_type,key,cluster_id,record_ids,jaccard,year_delta,decision,reason
doi_exact,10.9999/abc.1,M0001,R00001;R00002,,,merged,shared exact normalized identifier
```

`conflicts.csv`（节选）：

```csv
cluster_id,field,chosen_value,chosen_source,chosen_normalized,other_value,other_normalized,other_sources,reason
M0001,journal,Journal of Widgets,crossref,journal of widgets,Journal of Widget Studies,journal of widget studies,europepmc,normalised values differ across sources
```

`provenance.csv`（节选）：

```csv
cluster_id,field,record_id,source_db,raw_value,normalized_value,status,raw_file,raw_locator,query,selected
M0001,doi,R00001,crossref,10.9999/abc.1,10.9999/abc.1,present,crossref.json,records[0],synthetic widget study,yes
M0001,doi,R00002,europepmc,10.9999/abc.1,10.9999/abc.1,present,europepmc.json,records[0],widget,no
M0001,pmid,R00002,europepmc,12345678,12345678,present,europepmc.json,records[0],widget,yes
```

按合成契约，`result.json` 至少包含：

```json
{"case_id": "synthetic-merge-example", "status": "partial",
 "merged_result": {"record_count": 2, "multi_source_clusters": 1},
 "conflicts": {"count": 2},
 "coverage": {"gaps": ["pubmed: synthetic timeout"]},
 "limitations": ["合成示例故意让 pubmed 失败，不代表真实库状态"]}
```

## 4. 反例（坏输入，同一脚本）

```csv
source_db,doi,pmid,title,authors,year,journal,type,priority
db1,,,,Smith,2020,Journal,article,1
db1,10.9999/z1,,A Valid Synthetic Title,Smith,not-a-year,Journal,article,abc
db2,not-a-doi,abc,A Second Synthetic Title,Doe,2021,Journal,article,2
```

预期：`record_rows_read=3`、`records_valid=2`、`records_dropped=1`；第一行因无
DOI/PMID/标题被丢弃并记 error `missing_identity`，同时计入 dropped；第二行保留但
`year=missing`、priority 非法回退；第三行 DOI/PMID 非法但标题有效，保留为独立记录。
退出码 2，`status` 为 `partial`，不得把丢弃行补回来，也不得把 `unknown` 写成空值。

## 5. 说明

示例只证明调用方式、字段形状与回溯链。正式案例必须读取实际 `/input` 响应，按
`output_contract` 生成 `result.json`，不得复制本页的虚构标识符或数值。
