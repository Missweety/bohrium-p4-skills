# 输出契约与自检口径

字段集合以运行时 `case.json` 的 `output_contract` 为准。本 Skill 按"必需字段 → payload"
做别名映射；映射不到时保留 `null` 并写入 `contract_gaps`，同时记入 `uncertainty`。

## 1. 字段与别名映射

| 契约常见字段 | 落点 | 说明 |
|-|-|-|
| `manuscript` / `draft` / `document` / `revision` / `revised_document` / `artifact` | `artifact`（`revision.docx`） | 主产物；`outputs` 给出全部文件 |
| `revisions` / `changes` / `edit_log` / `track_changes` | `revisions` | 逐条修订数组 |
| `citation_map` | `citation_map` | `[{old,new,first_paragraph,changed}]` |
| `versions` / `version_history` | `version_history` | 版本谱系（sha256、父版本、回退） |
| `evidence` | `evidence` | 每条修订的位置与锚点 |
| `coverage` | `coverage` | 指令总数/已应用/未命中/语义待办/引用重排数 |
| `status` | `status` | `success` / `partial` / `failed` |
| `sources` | `sources` | 每个输入文件 `kind/status/paragraphs/error` |
| `uncertainty` | `uncertainty` | 缺失材料、不可读、格式损失、语义待办、契约缺口 |
| `change_log` | `change_log` | 输入扫描、修订、版本快照 |

## 2. 修订条目结构

```json
{
  "revision_id": "R001",
  "type": "replace",
  "paragraph_id": "P0008",
  "section": "3",
  "anchor": "显著提升",
  "before": "显著提升",
  "after": "有明显提升",
  "char_start": 31,
  "char_end": 35,
  "basis": "避免无数据支撑的绝对化断言",
  "author": "academic-writing-client",
  "date": "2026-01-01T00:00:00Z",
  "status": "applied"
}
```

`type` 取值：`replace` / `delete` / `insert` / `citation_renumber` / `reference_renumber`。
`anchor` 必须是修订前该段文本的**逐字子串**（自检 `anchors_verbatim` 会核对）。

## 3. 修订标记（Word 层面）

| 指令 | 生成的 XML |
|-|-|
| 替换 | `<w:del w:id=".." w:author=".." w:date=".."><w:r><w:delText>旧</w:delText></w:r></w:del><w:ins ...><w:r><w:t>新</w:t></w:r></w:ins>` |
| 删除 | 仅 `<w:del>` 包裹 `w:delText` |
| 插入 | 仅 `<w:ins>` 包裹 `w:t` |

所有 `w:id` 全局唯一，`w:author` 与 `w:date` 固定可追溯；已有修订内的文字不参与锚点匹配。

## 4. 版本谱系

```json
{"versions":[
  {"version":"v0","file":"original.docx","role":"original","parent":null,"sha256":"..."},
  {"version":"v1","file":"revision.docx","role":"tracked_revision","parent":"v0","sha256":"..."},
  {"version":"v1-clean","file":"clean.docx","role":"accepted","parent":"v1","sha256":"..."}],
 "rollback":"把 v1 换回 v0（sha 前缀）即回到原稿；原稿未被改写。"}
```

## 5. 自检（`self_check`，写入 result.json）

| 检查项 | 通过条件 |
|-|-|
| `revision_openable` / `clean_openable` | 两个 docx 均可解析 |
| `revision_marks_present` | 修订稿中至少存在一条 `w:ins` 或 `w:del` |
| `revision_equals_clean` | 修订稿"接受全部修订后"的可见文本与 `clean.docx` 完全一致 |
| `edits_visible_in_clean` | 每处 replace/insert/citation 的 `after` 出现在干净稿；delete 的 `before` 不再出现 |
| `anchors_verbatim` | 每条修订的 `anchor` 能在原稿对应段落逐字找到 |
| `versions_linked` | v0/v1 的 sha256 存在，v1.parent = v0 |
| `preview` | `rendered` / `unavailable`，与 `limits` 一致 |
| `contract_fields_present` | 契约必需字段全部非 `null` |

`self_check.ok=true` 表示"修订真实存在、可接受、可复核"，**不表示**语义改写一定符合作者意图；
语义正确性仍需人工按 `revision_report.md` 复核。

## 6. 状态

- `success`：全部指令命中且预览成功、自检通过；
- `partial`：有未命中/语义待办/无修订标记/预览降级/合并重建；
- `failed`：无可读稿件，仍写全结构并逐文件说明原因。

`limits` 必须逐项说明上述情况，不得模糊表述。
