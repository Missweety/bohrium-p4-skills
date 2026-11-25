# 默认输出契约（学术 PPT 模板与格式适配）

`case.json` 的 `output_contract` 优先：字段名、模板路径、页数、语言一律以题面为准。
本文件只补全题面未列出的字段；`result.json` 必须回填 `case_id` 且与输入一致。

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填 |
| status | enum | 是 | ok / partial / blocked / refused |
| template | object | 是 | `{source, slide_size:{w_in,h_in}, theme:{colors,fonts}}` |
| artifact_path | string | 是 | 主产物相对路径（deck.pptx；无构建环境时 deck.md） |
| artifact_format | string | 是 | pptx / marp-md |
| slide_count | int | 是 | 主讲页数，不含 `kind=backup` |
| deck_outline | array | 是 | 页级大纲，每页附 `layout`（所用版式名） |
| slot_map | array | 是 | `[{slide, kind, layout, chars, slots:{title,body,caption,footer}}]` |
| evidence_map | array | 否 | 页级证据 `[{slide, ref, quote, locator}]`；非标题页缺证据写 warning |
| compliance | object | 是 | `{ok, errors, warnings, checks:[{check,level,detail}]}` |
| notes_path | string | 是 | 逐页讲稿相对路径（speaker_notes.md） |
| render_log | object | 是 | `{source, exports:[{path,format}], tool, template, pages:[{slide,layout,visual,caption,evidence,title,body}]}` |
| self_check | object | 否 | 合规摘要 |
| uncertainty | array | 是 | 模板解析失败、缺字号、缺槽位等；无则 `[]` |
| limits | string | 否 | partial 时说明缺口 |

## 槽位定义

| 槽位 | 语义 | 必需性 |
|-|-|-|
| title | 页标题占位符（`title` / `ctrTitle`） | 每页必需 |
| body | 正文占位符（`body` / `obj`） | 非标题页必需 |
| caption | 图注/表注（占位符名含 caption/图注） | 有图表页建议有 |
| footer | 页脚（`ftr`） | 建议整册统一 |
| date / number | 日期、页码 | 可选 |

字号下限默认：title 28 pt、body 18 pt、caption 12 pt、footer 9 pt（`--min-fonts` 可覆盖）。
留白：槽位总面积 / 画布面积 > 75% 警告、> 90% 硬错误；槽位左边距 < 0.3 in 或上边距 < 0.25 in 警告。
每页字数上限默认 380（标题 + 主张 + 要点，非空白字符；`--max-chars` 可覆盖）。
对比度：正文/背景 ≥ 4.5，强调色/背景 ≥ 3.0（WCAG AA）。

## 一致性约束

- `slot_map` 条数 = `deck_spec.json` 的页数；每页 `layout` 必须来自 `template.layouts`。
- `compliance.ok=false` 时 `status` 不得为 `ok`。
- 模板无 `footer` 槽位只警告，不阻断；但必须在 `uncertainty` 说明。
- 解析失败降级为默认槽位时，`template.source` 写 `default`，并写 `uncertainty`。
- `render_log.exports` 只列实际存在的文件；无 pptx 时 `artifact_format=marp-md`。
  有 pptx 且能转 PDF 时同时列出 pptx 与 pdf。
- `render_log.pages` 条数 = 页数；`tool` ∈ python-pptx / stdlib-pptx / none。
  标准库兜底时 `uncertainty` 必须写明未继承母版，不得声称已套模板。
- 图表页：`visual.type=figure` 需能定位图像或如实写缺图；`visual.type=table` 用原生表格。
  图注、页脚、页码写入真实占位符；没有占位符时用文本框补齐并在 `render_log.pages` 标注。
