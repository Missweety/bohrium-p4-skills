# 输出契约与自检口径

本题的 `result.json` 字段集合以运行时 `case.json` 的 `output_contract` 为准。本 Skill
不硬编码字段名，而是按"必需字段 → 实际 payload"做**别名映射**；映射不到时保留 `null`
并写入 `contract_gaps`，同时在 `uncertainty` 记录，绝不臆造内容充数。

## 1. 字段与别名映射

| 契约常见字段 | 本 Skill 落点 | 说明 |
|-|-|-|
| `thesis` / `manuscript` / `draft` / `document` / `revision` / `revised_document` / `artifact` | `artifact`（`revision.docx`） | 主产物文件名，另有 `outputs` 明细 |
| `parsed` | `parsed` | 材料清单、段落数、章节、表格数、字符数、题面摘录 |
| `fields` / `term_table` | `term_table` + `fields.term_table` | 缩写/术语定义表 |
| `symbol_table` | `symbol_table` + `fields.symbol_table` | 符号表（含表格单元格锚点） |
| `inconsistencies` / `evidence` | `inconsistencies` + `evidence` | 不一致清单与逐条证据 |
| `numbering_report` | `numbering_report` | 标题/图表/公式编号汇总与编号类 finding id |
| `coverage` | `coverage` | 七族逐项 `checked/findings` 与统计 |
| `status` | `status` | `success` / `partial` / `failed` |
| `sources` | `sources` | 每个输入文件的 `kind/status/paragraphs/error` |
| `uncertainty` | `uncertainty` | 缺失材料、不可读、格式损失、语义型指令、契约缺口 |
| `change_log` | `change_log` | 输入扫描与自动修订记录 |

未识别的字段名一律进 `contract_gaps`（列表），`result.json` 中该字段为 `null`。
自检 `contract_fields_present` 要求全部必需字段非 `null`；若出现缺口，`status` 至少为 `partial`。

## 2. 不一致条目结构

```json
{
  "id": "C001",
  "rule": "terminology.abbr_conflict",
  "kind": "terminology",
  "severity": "high",
  "confidence": "high",
  "location": {
    "paragraph_id": "P0003",
    "section": "1",
    "section_title": "第1章 绪论",
    "sentence_index": 1,
    "char_start": 0,
    "char_end": 11,
    "anchor_quote": "深度卷积神经网络（CNN）",
    "sentence_quote": "……",
    "source_path": "chapter1.md"
  },
  "summary": "……",
  "why": "……",
  "evidence": [{"paragraph_id": "P0002", "section": "1", "quote": "CNN"}],
  "auto_fixable": false,
  "suggested_fix": "……",
  "needs_manual_confirmation": true
}
```

硬性要求：`id` 全局唯一；`anchor_quote` 必须是 `location.paragraph_id` 对应段落文本的**逐字子串**；
`why` 说明"为什么这是不一致"，不得只有"建议修改"。

## 3. 自动修订条目结构

```json
{
  "edit_id": "E001",
  "finding_id": "C003",
  "rule": "terminology.latin_variant",
  "paragraph_id": "P0004",
  "section": "1",
  "char_start": 27, "char_end": 38,
  "before": "transformer", "after": "Transformer",
  "context_before": "……[transformer]……",
  "context_after":  "……[Transformer]……",
  "basis": "同一英文术语存在 2 种写法……",
  "confidence": "high",
  "segments_written": 1
}
```

`skipped_edits` 记录定位失败或超出边界的条目及原因，不影响其余交付。
`deduped_edits` 记录"同段同词同目标"被更早条目覆盖而不再重复执行的命中（旧版静默丢弃）。

### 3.1 工单目标执行（`workorder_execution`）

工单里 `find/old/before` + `replace/new/after` 形式的条目逐条机械执行：

```json
{
  "target_id": "W001", "find": "多头注意力", "replace": "多头自注意力",
  "status": "applied", "scope": {"chapter": "2"},
  "paragraphs": [{"paragraph_id": "P0023", "section": "2.1",
                  "source_path": "chapter2.md", "occurrences": 1}],
  "occurrences": 1
}
```

未命中时 `status="not_found"`，附 `searched_paragraphs` 表示检索范围；不做模糊匹配。

### 3.2 改动影响面（`edit_impact`）

每条编辑后，同一旧写法仍出现在哪些段落：`edit_id / paragraph_id / section /
source_path / excerpt`。用于回答"改一处后受影响段落能否被找出来"。

## 4. 自检（`self_check`，写入 result.json）

| 检查项 | 通过条件 |
|-|-|
| `contract_declared` | `case.json` 是否声明了 `output_contract.required`（未声明时为 `false` 并写入 `uncertainty`） |
| `contract_fields_present` | 契约必需字段全部非 `null` |
| `finding_ids_unique` | finding id 无重复 |
| `anchors_verbatim` | 每条 finding 的 `anchor_quote` 能在**修订前**对应段落逐字找到 |
| `revision_verified` | 产物可解析；段落数不变；未命中段落逐字未变；每处 `after` 确实出现在目标段 |
| `preview` | `rendered` / `html_only` / `unavailable`，与 `limits` 一致 |
| `severity_counts` | 与清单一致 |

`self_check.ok=true` 仅表示"交付物内部自洽且可复核"，**不表示**语义判断全部正确；
语义正确性仍需人工按清单复核。

## 5. 状态与限制

- `success`：单 docx、无不可读、无跳过、预览成功；
- `partial`：合并重建 / 不可读 / 跳过修订 / 预览降级 / 语义指令未落地；
- `failed`：无可读材料，仍写全结构并逐文件说明原因。

`limits` 必须把上述每一项写成一句可核对的话，不得为空字符串或"无"以外的模糊表述。
