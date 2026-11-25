# 默认输出契约（writing / 证据驱动）

case.json 若提供 `output_contract`，**以题面为准**；本文件只补全。`result.json` 顶层：

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| case_id | string | 是 | 原样回填输入案例标识 |
| status | enum | 是 | ok / partial / blocked / refused |
| artifact_path | string | 是 | 成稿相对路径（如 `manuscript.md`） |
| artifact_format | string | 否 | `md` / `docx` |
| claim_evidence | string | 是 | claim-evidence 表路径（如 `claim_evidence.md`） |
| claims | array | 是 | `[{id, text, state, strength, note}]`，与表格逐行一致 |
| source_map | array | 是 | `[{claim, value, source_path, locator, quote}]`，quote 必须是原文逐字片段 |
| changes | array | 否 | `[{target, type, before, after, reason}]`：对初稿/材料的改动记录 |
| uncertainty | array | 是 | `not_covered` 论断、`conflict` 待核项、仅摘要/不可读条目；无则 `[]` |
| limits | string | 否 | partial 时说明缺哪些论断或章节 |
| self_check | object | 否 | `{verdict, errors, warnings}`（来自 `evidence_check.json`） |

## 三态取值

`state ∈ {supported, not_covered, conflict}`；`strength ∈ {strong, moderate, weak, none}`。
`not_covered` 的 `claims` 条目必须带 `note`（检索范围/关键词），`evidence` 为空。

## 文件落位

```text
/app/output/
  result.json
  manuscript.md        # 成稿，句末带 (C3) 论断编号
  claim_evidence.md    # 论断 / 三态 / 强度 / 引用+定位 / 待核
  claims.json          # 机器可读矩阵
/app/work/
  contract.json  evidence.json  corpus.txt  matrix.json  evidence_check.json  draft.md  draft.json
```

`result.json` 的 `claims` 必须是矩阵的真实投影，**不得只写汇总统计**。
