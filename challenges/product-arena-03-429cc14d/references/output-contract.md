# 默认输出契约（writing）

case.json 若提供 `output_contract`，以题面为准；本文件只做补全。`result.json` 顶层字段：

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填输入案例标识 |
| status | enum | 是 | ok / partial / blocked / refused |
| artifact_path | string | 是 | 主产物相对路径（如 manuscript.md） |
| artifact_format | string | 否 | md / tex / docx 等 |
| source_map | array | 是 | `[{claim, value, source_path, locator}]` 逐条事实来源 |
| changes | array | 否 | 修改记录 `[{target, type, before, after, reason}]` |
| uncertainty | array | 是 | 无法确认项与原因；无则空数组 |
| limits | string | 否 | partial 时说明缺哪一段/为什么 |
| self_check | object | 否 | 守恒与一致性检查摘要（见 work/claims.json） |
