# 默认输出契约（学术汇报内容组织）

`case.json` 若给出 `output_contract`，**字段名、页数、时长、受众一律以题面为准**；本文件只补全
题面未列出的字段。`result.json` 必须回填 `case_id`，且与输入一致；不得改写题面要求的字段名。

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填 |
| status | enum | 是 | ok / partial / blocked / refused |
| artifact_path | string | 是 | 主产物相对路径（deck.pptx；无构建环境时 deck.md） |
| artifact_format | string | 是 | pptx / marp-md |
| slide_count | int | 是 | 主讲页数，不含 `kind=backup` |
| duration_min | number | 是 | 题面汇报时长；未给写 `null` 并在 uncertainty 说明 |
| outline | object | 是 | `{audience, mainline:{problem,approach,results,conclusion,limitations}}` |
| deck_outline | array | 是 | 页级大纲，元素见下表 |
| timing_table | array | 是 | `[{index, segment, title, seconds, cumulative_mmss}]` |
| speaker_notes_path | string | 是 | 逐页讲稿相对路径（speaker_notes.md） |
| evidence_map | array | 是 | `[{slide, ref, quote, locator}]`；无证据时为 `[]` |
| render_log | object | 是 | `{source, exports:[{path,format}], tool, template}` |
| changes | array | 否 | 相对输入大纲的改动 `[{slide, before, after, reason}]` |
| uncertainty | array | 是 | 无法确认的时长/受众/编号等；无则 `[]` |
| limits | string | 否 | partial 时说明缺哪些页、依赖或导出 |
| self_check | object | 否 | `deck_check.json` 摘要：ok/errors/warnings/slide_count/total_seconds |

## deck_outline 元素

| 字段 | 类型 | 必填 | 约束 |
|-|-|-|-|
| index | int | 是 | 从 1 连续编号 |
| kind | enum | 是 | title / problem / gap / method / result / limitation / conclusion / backup |
| title | string | 是 | 判断句，≤24 字，不写“结果二” |
| takeaway | string | 否 | 一句话结论，不得与 title 同义重复 |
| bullets | array | 是 | **≤6 条，每条 ≤14 个非空白字符** |
| visual.type | enum | 是 | figure / table / schematic / photo / none |
| visual.ref | string | 条件 | figure/table 必填，用论文原编号（Fig. 3 / Table 2） |
| visual.caption | string | 否 | 含条件、n、误差线含义；schematic 必须含“示意” |
| evidence | array | 否 | `{ref, quote, locator}`；quote 为原文逐字 |
| notes.say | string | 是 | 30–60 秒口播，不复述要点原文 |
| notes.why | string | 否 | 与前页的过渡、强调点 |
| notes.qa | array | 否 | 预设问答 `[{q,a}]` |
| seconds | int | 是 | 30–60 |

## 一致性约束

- `slide_count` = `kind != "backup"` 的页数；`slide_count ≤ max_slides`（题面给出时）。
- `sum(seconds)` 与 `duration_min × 60` 的差 ≤ max(30 秒, 10%)。
- 页面出现的每个数字、每个 `Fig./Table` 编号必须能在 `corpus.txt` 找到同源写法。
- `status=ok` 要求 `render_log.exports` 非空；仅交付 Markdown 源时为 `partial` 并在 `limits` 说明。
  有 pptx 且能转 PDF 时 `exports` 同时列出 `pptx` 与 `pdf`；无 LibreOffice 只列 pptx 并写 limits。
- `changes` 必须写原因；无改动写 `[]`，不是省略字段。
