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
| audit | object | 否 | `work/audit.json` 的完整审计报告副本 |
| self_check | object | 否 | 守恒与一致性检查摘要（audit_verdict / problems / warnings） |

`output_contract` 若为列表、`{"fields":[...]}` 或 `{"字段名":"类型"}`，`emit`/`check` 都会归一化；
字段名是 `paper`/`report`/`text` 等别名时自动填入 `manuscript.md` 全文，`source_map` 别名填事实映射。

## draft.json（写作阶段的中间产物，由 `build` 渲染成 manuscript.md）

```json
{
  "case_id": "demo-paper-1",
  "status": "ok",
  "title": "Widget degradation",
  "sections": [{"name": "Results", "level": 2, "paragraphs": ["... 12.4% ..."]}],
  "figures": [{"label": "Figure 1", "caption": "Degradation by group", "section": "Results"}],
  "tables": [],
  "references": [{"authors": "Smith J.", "title": "Widgets", "year": "2020",
                  "journal": "J Widgets", "doi": "10.1000/abc"}],
  "source_map": [{"claim": "control degradation", "value": "12.4", "unit": "%",
                  "source_path": "/input/materials/exp.csv",
                  "locator": "row 2, col degradation_pct"}],
  "uncertainty": [],
  "declarations": {"data_availability": "..."},
  "limits": "",
  "fields": {"uncertainty": [], "limits": ""}
}
```

`emit` 会优先使用 `artifacts["manuscript.md"]`，缺失时使用 `work/manuscript.md`，再缺失则由
`sections` 渲染，保证 `manuscript.md` 一定存在且与 `result.json` 一致。
