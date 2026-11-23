# result.json 输出契约

`result.json` 是唯一入口产物。没有直接产物的字段写 `null`，但**字段不能缺失**。

## 1. 契约字段的提取

`parse_inputs.py` / `selfcheck.py` 依次查找：
`output_contract`、`output_contracts`、`required_output_fields`、`expected_output`、
`expected_outputs`、`outputs`、`contract`、`output_fields`、`result_contract`、
`deliverable_fields`、`required_fields`、`result_fields`。

接受四种形态：

```json
["docx_path", "format_report", "page_count"]
```
```json
{"required": ["docx_path", "format_report"]}
```
```json
{"properties": {"docx_path": {"type": "string"}, "format_report": {"type": "string"}}}
```
```json
"docx_path, format_report, page_count"
```

- 字符串按 `,` `;` 空白切分；列表项为对象时取 `name`/`key`/`field`/`id`。
- 去重、保持原顺序；字段名大小写和连字符原样保留。
- 没有任何契约键时使用默认字段：
  `case_id, status, sources, uncertainty, change_log, issues, deliverables,
  contract_fields, format_report, docx, pdf, template_spec, metrics, limits, verification`。

## 2. 字段语义

| 字段 | 类型 | 说明 |
|-|-|-|
| `case_id` | string | 来自 `case_id`/`caseId`/`id`/`task_id`；缺失时用 `case.json` 内容短哈希，不编造 |
| `status` | enum | `success` / `partial` / `failed` |
| `docx` | string\|null | 格式化 DOCX 的绝对路径（真实存在）；`docx_path`/`docx_file` 等别名映射到同一字段 |
| `docx_info` | object | `{path, bytes, sha256, reopens, editable}` |
| `pdf` | string\|null | 仅当真的调用渲染器并成功时非空；`pdf_path` 映射到此字段 |
| `pdf_info` | object\|null | `{path, bytes, page_count, page_count_method}` |
| `page_count` | int\|null | 仅来自真实 PDF 的页数；无渲染器为 `null` |
| `format_report` | object | `{path, summary, requirements_path}`；`format_report_path` 别名映射到 `path` |
| `sources` | array | 每个输入 `{role, path, bytes, sha256}` |
| `uncertainty` | array[string] | 无法确认的点：缺模板、字体替换、多栏未目检、无 PDF、XML 级核验 |
| `change_log` | array | 实际改动：标题去重编号、参考文献去编号、题注重编号、规格来源 |
| `issues` | array | `{id, status, detail, source}`；来自报告、构建、解析与缺失内容 |
| `deliverables` | array | `{path, role, format, exists, bytes, sha256}` |
| `contract_fields` | array | 实际使用的契约字段名（原顺序） |
| `template_spec` | object | 规格摘要：页面、正文、标题、编号、题注、参考文献、页码、表格 |
| `metrics` | object | 段落/表格/图片/标题层级/题注号/参考文献/页数/需求计数 |
| `limits` | array[string] | 环境与实现限制 |
| `verification` | object | 重开、有效性、内容保留、占位符、PDF、需求计数、目检声明 |

## 3. status 判定

- `success`：全部硬检查通过，所有需求 `applied`，无开放 issue，且模板/规格已找到。
- `partial`：以下任一成立——模板缺失、需求 `partial`/`unsupported`、参考文献或对象缺失、
  多栏/目录/页数无法目检、无 PDF、字体替换、契约字段无产物（`null`）。
- `failed`：DOCX 不存在/不可重开、正文块丢失、无稿件内容、`result.json` 不完整。

`selfcheck.py` 的 `verdict=PASS` 只表示「声明与产物一致」，不表示视觉正确。

## 4. 诚实性约束

1. `sources[].sha256` 必须是实际读取文件的哈希；文件不存在时为 `null`。
2. `page_count` 只能来自真实 PDF；没有渲染器时不得写估计页数。
3. 缺模板/缺规格必须出现在 `uncertainty` 与 `change_log`，不能静默套默认值。
4. 稿件没有参考文献/图/表时，不补造条目；报告记 `partial` 或 `not_applicable`。
5. 任务要求生成器未实现时，记 `unsupported`，不得声称已满足。
6. 任何无法验证的内容进入 `uncertainty`/`limits`，不能删检查项或改数值来过检。
7. `success` 与开放 issue、失败检查、缺失交付物不能同时出现；`selfcheck.py` 会拒绝。

## 5. selfcheck 的硬/软检查

硬检查（任一失败 → `verdict=FAIL`、退出 1）：
`case.readable`、`contract.fields`、`inputs.readable`、`manuscript.blocks`、
`docx.exists/valid/reopens`、`report.exists/summary/statuses`、`deliverables.exist`、
`contract.keys_present`、`status.allowed/consistent`、`result.roundtrip`。

软检查（失败降低 status，不单独退出）：
`report.evidence`（applied 项须有 OOXML 位置）、`output.no_placeholder`。
