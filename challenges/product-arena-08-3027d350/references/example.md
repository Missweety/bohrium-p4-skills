# 最小调用示例（示意，不是正式案例答案）

## 输入（示意）

`/input/case.json`

```json
{
  "case_id": "demo-doc-001",
  "task": "解析给定 PDF：输出章节树、表格 CSV、图注与参考文献，并给出页码定位",
  "materials": ["materials/paper.pdf"],
  "output_contract": {"answer": "string", "structured": "object", "evidence": "array"}
}
```

`materials/paper.pdf`（示意为两页，`\f` 表示分页）

```
1 Introduction
Deep learning has changed ... (第 1 页正文)
\f
2 Methods
2.1 Dataset
We used 1,024 samples.   Table 1. Dataset summary
sample  n   age
A       512  32.1 ± 4.0
```

## 调用（示意）

```bash
python scripts/kernel.py init --case /input/case.json --out work
python scripts/kernel.py index --materials /input/materials --out work
python scripts/doc_structure.py --input work/corpus.txt --out work
python scripts/quote_check.py --evidence work/quotes.json --corpus work/corpus.txt --out work/quote_check.json
python scripts/kernel.py emit --draft work/draft.json --contract-dir work --out /app/output
python scripts/kernel.py check --out /app/output
```

`work/draft.json`（示意）

```json
{
  "status": "ok",
  "fields": {
    "answer": "全文 2 页，含 2 个一级章节与 1 个二级章节、1 张表；文本层完整，无不可读页。",
    "structured": {
      "document": {"file": "materials/paper.pdf", "page_count": 2, "text_layer": true, "layout": "single"},
      "sections": [{"section_id": "S000", "number": "1", "title": "Introduction", "level": 1, "page_start": 1}],
      "tables": [{"table_id": "table_1", "caption": "Table 1. Dataset summary", "page_start": 2,
                  "header_rows": 1, "csv_path": "tables/table_1.csv"}],
      "unreadable_pages": []
    }
  },
  "sources": [{"path": "materials/paper.pdf", "sha1": "…"}],
  "uncertainty": [],
  "limits": ""
}
```

`/app/output/tables/table_1.csv`（示意）

```csv
sample,n,age
A,512,32.1 ± 4.0
```

## 说明

- 示例中的 `n`、`32.1 ± 4.0` 来自示意材料，仅演示字段结构，**不是任何正式案例的结果**。
- 若示例 PDF 为扫描件（无文本层），正确输出应为 `status: partial`、`unreadable_pages: [1, 2]`，
  且 `answer` 说明"无可抽取文本层，需可读版或 OCR 结果"，而不是编造章节树。
