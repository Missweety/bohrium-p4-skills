# 输出契约（默认，题面 output_contract 优先）

题面给出 `output_contract` 时以题面为准（`kernel.py init` 自动读取并回填）；未给出时按下列字段交付：

| 字段 | 类型 | 要求 |
|-|-|-|
| case_id | string | 与输入 case 一致 |
| status | enum | ok / partial / blocked / refused |
| claim_evidence | path | 逐条证据表（Markdown），必须真实落盘 |
| verdicts | list | 每条 `{claim_id, verdict, strength, evidence_count, note}`，覆盖 claims 全部条目 |
| source_map | list | 每条 `{claim, value, source_path, locator}`，value 为判定或引文摘要 |
| conflicts | list | `{claim, evidence_a, evidence_b, question}`，无冲突时为 `[]` |
| gaps | list | 证据空白：`{claim, search_scope}`，与 insufficient_evidence 对应 |
| summary | string | 总体判断与四态计数 |
| metrics | object | 至少含 `claims`、`by_verdict`、`unreadable` |
| limits | string | 必填；无覆盖缺口时写"无" |
| uncertainty | list | 无法确认的项与原因 |

## 判定一致性（`kernel.py check` 实际校验）

- `status=ok`：全部 claims 均有四态判定、引文可定位、机检无硬失败。
- `status=partial`：材料可读性不足或部分论断只能给成分级粒度，`limits` 写明缺口。
- `status=blocked`：材料不可读、claims 文件缺失或为空，不得编造内容。
- `verdicts` 每行须含合法 `claim_id` 与四态 `verdict`；`metrics.claims` 必须等于 `verdicts` 行数。
- `verdicts` 中的 `claim_id` 必须在 `claim_evidence.md` 有对应行，且判定文字一致。
- `gaps` 只能指向判定为 `insufficient_evidence` 的论断。
