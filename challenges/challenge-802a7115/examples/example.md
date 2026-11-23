# 最小调用示例（合成示例，非官方案例）

> 以下作品、版本、DOI、标题与路径全部为合成占位符，仅用于说明接口和流程。它们不是任何官方固定案例的数据，也不是预期答案。

## 1. 合成输入 `/app/work/records.csv`

```csv
work_id,version_id,language,version_type,doi,title,translated_from,source_file,locator
W-DEMO,V-PT,pt,original,10.0000/demo,Estudo sintetico,,demo_pt.pdf,page:1
W-DEMO,V-EN,en,translation,10.0000/demo,Synthetic study,V-PT,demo_en.pdf,page:1
W-DEMO,V-AB,en,abstract_only,10.0000/demo,Synthetic abstract,,demo_en.pdf,page:2
W-DEMO,V-EN,en,translation,10.0000/demo,Synthetic study,V-PT,demo_export.csv,row:2
```

## 2. 调用

```sh
cd /skills/weekly-skill
python3 scripts/source_index.py extract --input /input --out /app/work/source-index.json
python3 scripts/language_matrix.py --input /app/work/records.csv \
    --out /app/work/lang-matrix --expected-languages en,pt
```

退出码为 `2` 表示“完成但有问题”，不是运行失败；本次会因第二条 `V-EN` 记录与 `demo_en.pdf` 中的同名版本精确重复而产生 `duplicate_version` 警告。

## 3. 合成输出摘录

`/app/work/lang-matrix/matrix.json`（节选）：

```json
{
  "tool": "language_matrix.py",
  "schema_version": "1.0",
  "status": "issues",
  "counts": {"records_total": 4, "works": 1, "duplicates": 1},
  "works": [
    {
      "work_id": "W-DEMO",
      "full_text_languages": ["en", "pt"],
      "abstract_only_languages": ["en"],
      "has_original": true,
      "flags": ["duplicate_version", "duplicate_versions", "multilingual_work"],
      "languages": {
        "pt": {"original": ["V-PT"]},
        "en": {"translation": ["V-EN"], "abstract_only": ["V-AB"]}
      }
    }
  ]
}
```

`/app/work/lang-matrix/versions.csv`（节选）：

```csv
record_id,work_id,version_id,language,version_type,record_status,duplicate_of,flags
R0001,W-DEMO,V-AB,en,abstract_only,ok,,
R0002,W-DEMO,V-EN,en,translation,ok,,
R0003,W-DEMO,V-EN,en,translation,duplicate,R0002,duplicate_version
R0004,W-DEMO,V-PT,pt,original,ok,,
```

## 4. 合成 `result.json` 映射片段

```json
{
  "case_id": "<运行时从 /input/case.json 读取>",
  "status": "partial",
  "results": [
    {
      "work_id": "W-DEMO",
      "version_id": "V-PT",
      "language": "pt",
      "version_type": "original",
      "evidence": [{"source_file": "demo_pt.pdf", "locator": "page:1"}]
    }
  ],
  "counts": {"records_total": 4, "works": 1},
  "uncertainty": ["合成示例，无真实原文可核"],
  "report_path": "/app/output/report.md"
}
```

实际案例必须读取其 `output_contract`，按契约字段名和类型替换上述键；不得直接复用本示例的 `case_id`、条数或结论。
