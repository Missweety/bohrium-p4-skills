# 默认输出契约（学术 PPT 生成与编辑）

`case.json` 的 `output_contract` 优先：字段名、页数、模板、语言一律以题面为准。本文件只补全
题面未列出的字段；`result.json` 必须回填 `case_id` 且与输入一致。

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填 |
| status | enum | 是 | ok / partial / blocked / refused |
| mode | enum | 是 | generate / edit |
| artifact_path | string | 是 | 主产物相对路径（deck.pptx；无构建环境时 deck.md） |
| artifact_format | string | 是 | pptx / marp-md |
| slide_count | int | 是 | 主讲页数，不含 `kind=backup` |
| deck_outline | array | 是 | 最终页级大纲（编辑后版本），元素见下表 |
| notes_path | string | 是 | 逐页讲稿相对路径（speaker_notes.md） |
| diff | array | 是 | 编辑 diff：`[{slide, op, field, before, after, reason}]`；生成模式为 `[]` |
| changes | array | 是 | 与 `diff` 同源，供通用契约读取 |
| evidence_map | array | 是 | `[{slide, ref, quote, locator}]` |
| render_log | object | 是 | `{source, exports:[{path,format}], tool}` |
| self_check | object | 否 | `deck_check.json` 摘要 |
| uncertainty | array | 是 | 未应用的编辑、无法提取的图、缺字体等；无则 `[]` |
| limits | string | 否 | partial 时说明缺口 |

## deck_outline 元素

| 字段 | 类型 | 必填 | 约束 |
|-|-|-|-|
| index | int | 是 | 从 1 连续编号；编辑后重排 |
| kind | enum | 是 | title / problem / gap / method / result / limitation / conclusion / backup |
| title | string | 是 | 判断句，≤24 字 |
| takeaway | string | 否 | 一句话结论 |
| bullets | array | 是 | ≤6 条；默认每条 ≤40 字（`--max-bullet-chars` 可调） |
| visual.type | enum | 是 | figure / table / schematic / photo / none |
| visual.ref | string | 条件 | figure/table 必填，用论文原编号 |
| visual.caption | string | 否 | schematic 必须含“示意” |
| evidence | array | 否 | `{ref, quote, locator}` |
| notes.say | string | 是 | ≥20 字，不复述要点 |
| notes.why | string | 否 | 过渡/强调 |
| notes.qa | array | 否 | 预设问答 |
| seconds | int | 否 | 有值时用于时长核对 |

## edits.json（编辑指令）

```json
{"edits": [
  {"slide": 2, "op": "set_title", "value": "新标题", "reason": "导师要求"},
  {"page": 4, "op": "replace_text", "find": "31 um", "replace": "31 微米"},
  {"slide": 5, "op": "set_bullets", "value": ["要点一", "要点二"], "reason": "压缩"}
]}
```

- 页号别名：`slide` / `page` / `index`；值别名：`value` / `after` / `to`；
  原因别名：`reason` / `why`。`op` 必填，无 `op` 的条目进 `diff.md` 的“未应用”表。
- 支持：`set_title`、`set_takeaway`、`set_bullets`、`set_seconds`、`set_notes_say`、
  `set_notes_why`、`add_qa`、`set_visual`、`replace_text`、`insert_after`、`delete`、`move`。

## 一致性约束

- `diff` 的每条改动必须有 `reason`；未写原因的改动在 `diff.md` 标“（未写原因）”。
- `slide_count` = `kind != "backup"` 页数；页号必须与 `deck_outline.index` 对齐。
- 页面数字、`Fig./Table` 编号、证据引文都必须能在 `corpus.txt` 命中。
- `status=ok` 要求有导出件（pptx 或实际渲染件）；否则 `partial` + `limits`。
  有 pptx 且能转 PDF 时 `render_log.exports` 同时列出 pptx 与 pdf。
- `mode=edit` 且 diff 为空时，`status` 不得为 `ok`。
