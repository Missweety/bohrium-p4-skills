# 默认输出契约（writing：论文结构与逻辑优化）

`case.json` 若提供 `output_contract`，以题面为准；本文件只做补全，并规定领域字段的最小结构。
`emit` 会写入契约字段，同时保留契约之外的领域字段。

## 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填输入案例标识 |
| status | enum | 是 | ok / partial / blocked / refused（含义见下） |
| artifact_path | string | 是 | 主产物相对路径，默认 `structure_plan.md` |
| artifact_format | string | 否 | 默认 `md` |
| diagnosis | array | 是 | 结构问题清单，见下；无问题时为 `[]` 且 `coverage.no_issues_found=true` |
| edit_plan | array | 是 | 可执行动作清单，见下；无问题时为 `[]` |
| outline | array | 是 | 修改后大纲；`blocked` 时为空但文件仍生成 |
| paragraph_map | array | 是 | 原段落去向，保证无遗漏 |
| argument_map | array | 是 | 论点—论据映射 |
| fact_guard | object | 是 | `{numbers_unbound, citations_not_in_sources, quotes_checked, verdict}` |
| coverage | object | 是 | 六维逐项 `{checked, findings}`；`read_sections` / `unread_sections` |
| source_map | array | 是 | `[{claim, value, source_path, locator}]` 诊断依据定位 |
| changes | array | 否 | `[{target, type, before, after, reason}]`，记录对原稿建议动作 |
| uncertainty | array | 是 | 无法确认项与原因；无则空数组 |
| limits | string | 是 | `partial/blocked` 必须写清未覆盖内容与原因，不得为空 |
| self_check | object | 否 | 基线与模型方案来源、引文核验、数字守卫、最终 `check` 结果 |
| contract_gaps | array | 否 | 题面契约中语义未知、无法填写的字段名（值保留 null，不臆造） |

`status` 语义：
- `ok`：模型手写方案通过严格门禁且确有诊断；
- `partial`：已交付完整结构诊断，但来自规则基线，或存在被拦截/未核验项；
- `blocked`：没有可读稿件或无法切分段落；四个工件仍写出并说明缺失；
- `refused`：请求超出边界（如要求代造数据）。

空数组是合法值（例如无重复段落时 `repetition.findings=0` 且无对应 issue）。只有字段缺失或
`null` 才视为未交付；`check` 对空数组给 warning，不判 FAIL。

## diagnosis[] 条目

```json
{"issue_id":"S03","dimension":"argument_chain","severity":"high",
 "location":{"section":"3.2","paragraph_id":"P014","sentence_index":2,"anchor_quote":"..."},
 "problem_type":"claim_without_evidence","problem":"...","why":"...",
 "evidence_refs":["P012","Fig.2"],"confidence":"high"}
```

`dimension` 枚举：`rq_alignment` / `section_structure` / `argument_chain` / `paragraph_relation` /
`repetition` / `conclusion_boundary`。
`severity`：`high` / `medium` / `low`。`confidence`：`high` / `medium` / `low`。

## edit_plan[] 条目

```json
{"edit_id":"E03","issue_id":"S03","action":"NARROW",
 "target":{"section":"5","paragraph_id":"P041","sentence_index":1},
 "destination":null,"instruction":"...","preserves":"...",
 "expected_effect":"...","risk":"..."}
```

`action` 枚举：`MOVE / MERGE / SPLIT / REORDER / ADD_EVIDENCE / NARROW / DELETE_REDUNDANCY /
REWRITE_TRANSITION / FLAG_GAP`。每条 edit 必须能关联到一条 issue；一条 issue 至少一条 edit。

## outline[] / paragraph_map[]

```json
{"section":"4","role":"呈现主结果","order":3,"paragraphs_from":["P019","P020"],
 "merge_of":["P021"],"split_into":[],"note":"将 Table 2 的对比段前置"}
{"paragraph_id":"P021","status":"merged","into":"P020","reason":"同述同一对照组"}
```

`status` 枚举：`kept / moved / merged / split / removed / added_placeholder`。

## coverage 对象

```json
{"rq_alignment":{"checked":true,"findings":1},
 "section_structure":{"checked":true,"findings":2},
 "argument_chain":{"checked":true,"findings":3},
 "paragraph_relation":{"checked":true,"findings":0},
 "repetition":{"checked":true,"findings":1},
 "conclusion_boundary":{"checked":true,"findings":2},
 "read_sections":["1","2","3","4","5"],"unread_sections":[],
 "no_issues_found":false}
```

六个维度必须全部 `checked: true`；`findings: 0` 表示已检查无问题，不是未检查。
`no_issues_found` 仅在六维均已检查且 `diagnosis` 确实为空时为 true；此时允许 `edit_plan` 为空，
但必须有非空 `argument_map` 或段落覆盖，证明方案确由本次稿件推导。
