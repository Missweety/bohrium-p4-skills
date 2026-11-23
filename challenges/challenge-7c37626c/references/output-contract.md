# 默认输出契约（reading）

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填 |
| status | enum | 是 | ok / partial / blocked / refused |
| answer | string | 是 | 主答案（按题面语言） |
| structured | object | 否 | 题面要求的结构化字段 |
| evidence | array | 是 | `[{claim, source_path, locator, quote}]`，quote 必须是原文片段 |
| uncertainty | array | 是 | 未报告/无法判断项 |
| limits | string | 否 | partial 说明 |
