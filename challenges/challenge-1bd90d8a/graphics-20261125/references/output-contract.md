# result.json 输出契约

`result.json` 是唯一入口产物。它必须同时满足：
1. 原案例 `output_contract` 中的每个字段都存在，值来自真实计算或明确为 `null`；
2. 核心字段（`case_id`、`status`、`deliverables`、`element_map`、`caption`、`selfcheck`、
   `sources`、`limits`、`uncertainty`、`change_log`）齐全，**永不为空对象**；
3. `status` 与产物一致：验收不过就不能写 `ok`。

## 1. 契约字段的提取

`kernel.py init` 依次查找这些键：
`output_contract`、`output_contracts`、`required_output_fields`、`expected_output`、
`expected_outputs`、`outputs`、`contract`、`output_fields`、`result_contract`、
`deliverable_fields`、`required_fields`、`result_fields`。

接受四种形态：

```json
["figure_svg", "caption", "element_map"]
```
```json
{"required": ["figure_svg", "caption"]}
```
```json
{"properties": {"figure_svg": {"type": "string"}, "caption": {"type": "string"}}}
```
```json
"figure_svg, caption, element_map"
```

- 字符串按 `,` `;` 空白切分。
- 嵌套对象取第一层的字段名；`properties` / `fields` / `required` 均被识别。
- 列表项若为对象，取 `name` / `key` / `field` / `id`。
- 去重、保持原顺序；字段名原样保留（大小写、连字符都不改）。

若所有键都不存在、值非法或为空，使用默认契约：

```
case_id, status, figure_svg, figure_png, figure_pdf, caption, element_map,
data_profile, selfcheck, deliverables, sources, limits, uncertainty,
change_log, metrics
```

`kernel.py init` 会把结果写入 `work/case.json` 的 `contract_fields` 与
`contract_raw_type`（`list` / `dict` / `string` / `default` / `cli`），便于审计。

## 2. 字段语义

| 字段 | 类型 | 说明 |
|-|-|-|
| `case_id` | string | 来自 `case_id`/`caseId`/`id`/`task_id` 等；缺失时用案例路径/内容的短哈希，绝不编造 |
| `status` | enum | `ok` / `partial` / `blocked` / `failed` / `refused` |
| `figure_svg` | string\|null | 相对 `/app/output` 的文件名；`figure.svg` |
| `figure_png` | string\|null | `figure.png`；无 matplotlib 且无转换器时为 `null` |
| `figure_pdf` | string\|null | `figure.pdf`；同上 |
| `caption` | string | 图注正文（不是文件名） |
| `caption_file` | string | `caption.md` |
| `element_map` | object | `{file, counts, sha256, sample[]}`；完整内容在 `element_map.json` |
| `element_map_file` | string | `element_map.json` |
| `data_profile` | object | `{file, rows, columns, sha256, warnings[]}` |
| `data_snapshot` | object | 源表/规范化表的哈希、行列数、编码、分隔符、sheet |
| `selfcheck` | object | `{verdict, errors[], warnings[], stats}` |
| `selfcheck_file` | string | `selfcheck.json` |
| `deliverables` | array | 每个产物 `{path, role, format, exists, bytes, sha256}` |
| `sources` | array | 数据与规范化快照的来源记录 |
| `limits` | array[string] | 能力/环境限制，例如缺 matplotlib、CJK 字体、无 PNG/PDF |
| `uncertainty` | array[string] | 无法核验或存在歧义的点，例如多数据表、列名单位缺失、自检失败原因 |
| `change_log` | string | 一句话变更摘要；首次生成也要有 |
| `change_details` | object | `{mode, changes[], warnings[]}`；改图时与 `edit_log.json` 一致 |
| `metrics` | object | 行数、列数、图型、面板数、图元数、PNG 尺寸/字节、自检项数 |
| `sample_sizes` | object | 每个面板的真实 `n`；柱状图为 `{series: {系列: {组: n}}, missing_by_group: {组: 缺失行数}}` |
| `error_semantics` | object | `{code, label, text, plan_text}` |
| `chart_spec` | object | `{file, chart_type, panels[]}` |
| `chart_spec_file` | string | `chart_spec.json` |
| `exports` | array | 产物路径列表 |
| `input_files` | array | 扫描到的输入与选择原因（多数据表时包含候选） |
| `unmapped_contract_fields` | array | 契约中无标准生产者的字段；这些字段在结果里为 `null`，并写入 `uncertainty` |
| `case_doc` | object | `work/case.json` 的内容摘要（可选） |

## 3. status 判定

- `ok`：自检 `PASS`，且 `figure.svg`、`figure.png`、`figure.pdf` 均存在且非空。
- `partial`：图已生成但至少一项不完整——缺 PNG/PDF（例如仅 stdlib SVG）、自检有
  warning/FAIL、改图只做了结构编辑、契约字段被降级为 `null`。
- `blocked`：无可用数据且无可编辑 SVG，或图型无法映射；仍写全部契约字段与原因。
- `failed`：脚本内部异常导致没有可用图件（`run_case.py` 只在极端情况返回 2）。
- `refused`：请求违反约束（例如要求编造 p 值、要求读取凭据），明确拒绝并说明。

## 4. 诚实性约束

1. `sources[].sha256` 必须等于实际读取文件的哈希；`data_snapshot` 同时给出规范化快照哈希。
2. 图上每个数据图元都能在 `element_map.json` 找到 `source_rows`（1 基，表头为第 1 行），
   且 `value` 可由 `normalized.csv` + 行号/列号复算。
3. `caption` 必须写清图型、变量与单位、误差线口径、样本量、缺失/异常值/重复行处理、
   源文件名与哈希前缀；显著性未提供时明确写“未提供”，不虚构。
4. 误差线 `n<3` 时置 `null`，不画。
5. 自检 FAIL 时 `status` 不能是 `ok`；`kernel.py check` 会拒绝这种组合。
6. 任何无法验证的内容进入 `limits` / `uncertainty`，不能删除检查项或改写数值来“过检”。

## 5. kernel.py check 的判定

FAIL 条件（任一）：
- 缺少 `case_id` 或 `status`；
- `status=ok` 但 `selfcheck.verdict != PASS`；
- `status=ok` 但 `deliverables` 中有声明存在却缺失的文件；
- `status=ok` 但 `element_map` 为空 / `caption` 为空；
- 契约字段缺失（应当全部存在，值可为 `null`）。

PASS 只表示“声明与产物一致”，不替代 `check_figure.py` 的图件层面校验；两者都要跑。
