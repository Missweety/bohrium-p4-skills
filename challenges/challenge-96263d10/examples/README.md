# SYNTHETIC 示例（非评测案例）

本目录全部是合成数据，用于验证工具行为，**不是**任何评测案例的答案。
`demo_input/manuscript.md` 没有真实实验、真实测量或真实文献。

## 文件

- `demo_input/case.json`：合成 `case_id` 与 `output_contract`。
- `demo_input/task.md`：中文格式要求（A4、页边距、字体字号、行距、标题、题注、
  三线表、GB/T 7714、页脚页码）。
- `demo_input/manuscript.md`：6 个标题、4 段正文、1 个三线表、2 条参考文献。

## 运行

```bash
cd /app/work
S=/skills/weekly-skill/scripts
python3 $S/parse_inputs.py --input /skills/weekly-skill/examples/demo_input --work demo_work
python3 $S/build_docx.py --work demo_work --output demo_out
python3 $S/verify_format.py --work demo_work --output demo_out
python3 $S/selfcheck.py --case /skills/weekly-skill/examples/demo_input/case.json \
  --work demo_work --output demo_out
```

## 本地实测结果（合成数据，macOS + LibreOffice）

- `parse_inputs.py`：`blocks=16`，`template=null`，`template_missing=false`
  （要求来自 `task.md`）。
- `build_docx.py`：`status=built`，`paragraphs=24`，`tables=1`，`drawings=0`，
  `page_count=1`，`missing_blocks=0`。
- `verify_format.py`：`applied=29`、`not_applicable=1`（稿件无图）、
  `partial=0`、`failed=0`。
- `selfcheck.py`：`verdict=PASS`、`status=success`、`unmapped_contract_fields=[]`。

## 预期产物

`demo_out/`：`manuscript_formatted.docx`、`format_report.json`、`build_meta.json`、
`spec.json`、`inputs.json`、`result.json`、`checks.json`，以及（本机有
`soffice` 时）`manuscript_formatted.pdf`。

## 如何逐项核验

1. 打开 `format_report.json`，每条需求都有 `expected`/`actual`/`status`/`location`。
2. `location` 指向 `word/document.xml`、`word/styles.xml`、`word/sectPr`、
   `word/numbering.xml` 或 `footer1.xml` 的具体元素。
3. `build_meta.json.reopen` 记录重开后段落、样式、表格、题注号、参考文献数量。
4. `checks.json` 记录每条自检的通过/失败与证据；`PASS` 仅表示声明与产物一致。

## 合成边界

- 表格数值、文献条目均为虚构，只用于排版流程演示。
- 没有图片文件，因此图注需求显示为 `not_applicable`。
- 页数来自本机真实 PDF 渲染；换环境可能不同，不构成评测结果。
