# 交付验收清单

运行前：
- [ ] `case.json` 可解析；`output_contract` 为 list / `{"fields":[...]}` / `{"required":[...]}` 之一。
- [ ] `target-fields.json` 存在且每项有 `field_id`；重复 id 会被审计标记。
- [ ] 材料放在 `/input` 子目录；PDF 有文本层。

运行后逐项核对：
- [ ] `result.json` 存在且 `contract_check.missing` 为空。
- [ ] `status` 与 counts 一致：
  - 全部 reported 且审计通过 → `success`
  - 有 not_reported/conflict/failed → `partial`
  - 无可读材料 → `blocked`
- [ ] 每个请求字段恰好一行；`field_id` 不重复。
- [ ] 每个 `reported` 行：`value` 是 `quote` 的逐字子串；`quote` 能在 `doc.json` 全文检索到。
- [ ] 每个 `reported` 行：`paragraph_id` 能在 `doc.json` 的 paragraphs 或表格 anchor 中解析。
- [ ] `unit` 只来自原文；没有把 `participants` 之类词当单位。
- [ ] `not_reported`/`extraction_failed` 的 `value` 为 null。
- [ ] `limits` 覆盖：缺字段表、不可读材料、PDF 页数截断、case.json 解析失败。
- [ ] `evidence` 至少覆盖每个 reported 字段，且 `locator` 与行内 `paragraph_id` 一致。
- [ ] `work/audit.json` 的 `pass=true`。

禁止项：
- [ ] 包内无绝对机器路径、无 token/密钥、无符号链接。
- [ ] 未声称任何未真实运行的分数或通过率。
