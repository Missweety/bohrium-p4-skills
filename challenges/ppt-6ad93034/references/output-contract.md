# result.json 契约

`/app/output/result.json` 必须包含 `case.json` 中 `output_contract` 声明的**全部**字段，
并额外提供下列基础字段；缺失字段不得静默省略，应写 `null` 并记入 `issues`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 与 `case.json` 的 `case_id` 一致 |
| `status` | enum | `success` / `partial` / `failed`，与 `issues` 一致 |
| `sources` | array | 读取的输入文件、解析方式、sha256；不可读项标注原因 |
| `deliverables` | array | 实际写出的文件路径与大小 |
| `uncertainty` | array | 需人工确认或无法自动核验的事项 |
| `change_log` | array | 读了什么、做了哪些核验、为何是该状态 |
| `issues` | array | 未通过项、级别与原因 |
| `contract_fields` | object | 契约字段名到实际值的映射 |

判定规则：

- `success`：契约字段齐全，无 error 级 issue，产物存在且可重开/可解析。
- `partial`：产物完整但存在开放 issue、无法核验项或材料缺口，须写清原因。
- `failed`：无可用输入或无法产出，不写占位内容，仍输出全部契约字段。

字段名以运行时 `output_contract` 为准，本 Skill 不硬编码具体业务字段。
