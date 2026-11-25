# output_contract 与 result.json 字段说明

`result.json` 的字段集合由 `/input/case.json` 的 `output_contract` 决定，运行器支持三种常见写法：

```json
["case_id", "status", "answer", "fields", "evidence", "limits"]
{"fields": ["case_id", "status", "answer", "fields", "evidence", "limits"]}
{"required": ["case_id", "status", "answer", "fields", "evidence", "limits"]}
```

字段名通过别名表归一到内部槽位（大小写、连字符、下划线不敏感），例如
`field_results`/`results`/`items`/`records`/`extractions`/`rows` → `fields`；
`summary`/`conclusion` → `answer`；`citations`/`quotes` → `evidence`；
`limitations` → `limits`。无法识别的字段名会用 `structured` 填充，并在值内写
`_contract_field` 与 `_note`，便于人工发现，而不是留 null。

## 必填字段（默认契约）

| 字段 | 类型 | 含义 | 复核方式 |
| --- | --- | --- | --- |
| `case_id` | string | 案例标识，取自 case.json；缺失时用文件名 | 与 `/input/case.json` 对照 |
| `status` | enum | `success` / `partial` / `blocked` / `failed` | 状态与 counts 一致 |
| `answer` | string | 覆盖情况摘要（requested/reported/not_reported 等） | 数字与 `fields` 统计一致 |
| `fields` | array | 逐字段行，见下表 | 每字段一行 |
| `evidence` | array | 证据条目 `{claim, source_path, locator, quote, field_id}` | quote 可在材料中检索 |
| `sources` | array | 材料清单与可读性 | 与 doc.json materials 一致 |
| `uncertainty` | array | 开放问题 | 与 not_reported/conflict 对应 |
| `limits` | string | 边界与失败原因，成功时可为空串 | 与状态一致 |
| `change_log` | array | 真实执行步骤 | 与工作目录产物对应 |

附加键（不替代契约字段）：`structured`（fields/counts/coverage/protocol/artifacts）、
`coverage`、`metrics`、`protocol`、`artifacts`、`audit`、`contract_check`。

## fields[] 行结构

| 键 | 类型 | 说明 |
| --- | --- | --- |
| `field_id` | string | 来自目标字段表，唯一 |
| `description` | string | 原字段描述 |
| `status` | enum | `reported` / `not_reported` / `source_conflict` / `extraction_failed` |
| `value` | string/null | reported 时为原文逐字值；其余为 null |
| `unit` | string/null | 仅在原文写出单位时填写 |
| `statistic` | string/null | 如 `95% CI`、`±`、`p < 0.05`，原文片段 |
| `experimental_condition` | string/null | 实验条件原文短语（须为 quote 子串） |
| `comparator` | string/null | 对照组原文表述（须为 quote 子串） |
| `paragraph_id` | string/null | 段落锚点；表格行为 `<文件>/tab.M/row.K` |
| `quote` | string/null | 逐字原句（≤400 字符） |
| `note` | string | 取值口径或缺失原因 |

## 证据与定位

- `paragraph_id` 必须能在 `work/doc.json` 的 `paragraphs[].paragraph_id` 或
  表格 `anchor` 中找到。
- `quote` 必须能在 `work/doc.json` 的全文（归一化空白/连字后）中检索到。
- `value` 必须能在 `quote` 中找到（大小写与空白归一化后）。
- 审计不通过时运行器把 `status` 从 `success` 降为 `partial` 并记录错误数。

## 状态判定

```
无任何可读材料/段落                      -> blocked
有材料但未提供目标字段表                  -> partial
全部字段 reported 且审计通过              -> success
存在 not_reported / conflict / failed   -> partial
全部字段 extraction_failed               -> failed
运行器内部异常                           -> failed（仍写 result.json）
```

## 禁止

- 不写绝对机器路径（如 `/Users/...`）、token、密钥。
- 不把 `not_reported` 写成 0、空对象或编造区间。
- 不合并不同条件下的数值来“凑”一个结论。
- 不声称任何未真实运行的分数或验证结果。
