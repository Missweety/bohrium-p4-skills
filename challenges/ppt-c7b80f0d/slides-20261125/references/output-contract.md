# 默认输出契约（兼容入口）

`case.json` 若提供 `output_contract`，**以题面为准**（字段名、页数、时长、模板路径都以题面为准）；
本文件只补全题面未列出的字段。`result.json` 必须含 `case_id` 且与输入一致。

完整字段、页级结构与不变量见 `references/deck-contract.md`；两处不一致时以该文件为准。
本页保留旧字段名与阈值，便于已有调用方和校验器直接读取。

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填 |
| status | enum | 是 | ok / partial / blocked / refused |
| artifact_path | string | 是 | `deck.pptx`（降级时 `deck.md`） |
| artifact_format | string | 是 | pptx / md |
| slide_count | int | 是 | 主讲页数（不含 backup，10–14） |
| duration_min | number | 是 | 题面时长；未给写 `null` 并在 uncertainty 说明 |
| deck_outline | array | 是 | 页级规格，同 `deck_spec.json.slides` |
| narrative | object | 是 | `{problem, gap, approach, results, conclusion, limitations}`，各含 `text`+`locator` |
| mainline | object | 否 | `narrative` 的同义字段，二者内容一致 |
| timing_table | array | 是 | `[{index, seconds, cumulative, cumulative_mmss, segment}]` |
| notes_path | string | 是 | `speaker_notes.md` |
| evidence_map | array | 是 | `[{slide, ref, quote, locator}]` |
| render_log | object | 是 | `{source, exports:[{path,format}], tool, preview}` |
| changes | array | 否 | 在起始 deck 上改动时逐条记录 |
| uncertainty | array | 是 | 抽取缺失、字体替换、降级项 |
| limits | string | 否 | partial 时说明缺哪些依赖/导出 |
| self_check | object | 是 | `{verdict, errors, warnings, slide_count, total_seconds}` |

## deck_outline 元素

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| index | int | 是 | 从 1 连续编号 |
| kind | enum | 是 | title / problem / gap / method / result / limitation / conclusion / backup |
| title | string | 是 | 判断句，≤24 字 |
| takeaway | string | 条件 | 非 title/backup 页填写 |
| bullets | array | 是 | 直接投影用：≤6 条、每条 ≤14 字、单页 ≤180 字 |
| visual.type | enum | 是 | figure / table / schematic / photo / none |
| visual.ref | string | 条件 | figure/table 必填，用论文原编号 |
| visual.caption | string | 条件 | 含条件、n、误差线含义；schematic 必须含"示意" |
| evidence | array | 条件 | 非 title/backup 页 ≥1 条 `{ref, quote, locator}`，quote 原文逐字 |
| source_pages | string | 条件 | 非 title/backup 页必填；`p.3` 或 `L41` |
| seconds | int | 是 | 30–60 秒 |
| notes.say | string | 是 | 30–60 秒口播，≥60 字，不复述页面 |
| notes.why | string | 否 | 与前页的过渡、强调点 |
| notes.qa | array | 否 | 预设问答 `[{q, a}]` |

> 旧版 `bullets ≤5 条 / 每条 ≤110 字符 / 备注一句话` 已收紧为可直接投影的短句规格；
> 若题面仍按旧阈值出题，用 `--max-bullets 5 --max-bullet-chars 110` 兼容，不改进原文。

## 一致性约束

- `slide_count` = 大纲中 `kind != "backup"` 的页数；窗口 10–14，且不超过题面上限。
- `Σseconds` 与 `duration_min×60` 偏差 ≤max(30s, 10%)；`timing_table` 合计必须相等。
- 页面每个数值与每个 `Fig./Table` 编号都必须能在 `corpus.txt` 找到同源写法。
- `status=ok` 要求 `render_log.exports` 非空；无导出件只能是 `partial` 并在 `limits` 说明。
- `narrative`/`mainline` 六项齐全；`results` 每条挂到某个 result 页。
- 任何 `changes` 都必须写原因；无改动则空数组（不是缺字段）。
