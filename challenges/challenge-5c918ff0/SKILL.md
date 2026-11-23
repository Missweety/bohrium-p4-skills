---
name: multi-database-record-merge
description: 把多个学术数据库实际返回的记录合并成一份可核对的联合结果：按库记录查询与字段能力，规范化 DOI、PMID、标题、作者与年份，先按精确标识符聚类再用标题 token Jaccard 加年份给出复核候选，按 priority 合并字段并保留每字段来源，明确缺失与未知、冲突与单库失败缺口，交付 merged.json、provenance.csv、conflicts.csv、report.md、result.json；只使用输入快照，不联网，不声称全局覆盖。
version: 1.0.0
---

# 多数据库联合检索：按库编排 → 字段映射 → 去重 → 冲突消解 → 逐条回溯

联合检索的成品不是"每个库都查过"的拼接清单，而是**一份每篇只出现一次、每个字段能说出
来自哪个库哪条原始记录的结果集**。本技能把"合并"拆成可复核的步骤，缺失就是缺失，
未知就是未知，单库失败就明说缺口。

## 何时使用

触发：案例提供两个及以上学术数据库的导出记录、原始响应或检索结果（CSV/TSV/JSON/JSONL），
要求联合检索、跨库去重、字段合并、覆盖比较、来源回溯，或要求说明"一共找到多少篇不同
论文、某字段由哪个库提供"。

不触发：只有一个库且不涉及合并；单库全文阅读；需要绕过访问限制、共享账号或向未授权
服务上传数据；没有实际记录、只有主题词时本技能不生成文献集。

## 输入

以 `/input` 下的实际文件为唯一事实依据；`/input/case.json` 提供案例说明、库清单、
查询记录与输出契约，不能替代打开原始响应。先读 `case.json` 与 `task.md`。

| 用途 | 字段（含别名） |
|-|-|
| 案例标识 | `case_id` / `id` / `task_id` |
| 研究问题 | `research_question` / `question` / `topic` |
| 库清单与状态 | `source_status` / `db_status` / `databases` / `sources` |
| 查询记录 | `queries` / `search_queries` / `query_log` |
| 记录列表 | `records` / `rows` / `data` / `works` / `items` / `results` |
| 单条记录 | `source_db`、`doi`、`pmid`、`title`、`authors`、`year`、`journal`、`type`、`raw_file`、`raw_locator`、`priority`、`query` |
| 输出契约 | `output_contract` / `expected_output` / `schema` |

记录可分散在多个文件；`raw_file`/`raw_locator` 缺失时脚本回退到实际读取的文件与
`row:N`、`line:N`、`item.key[i]`。没有任何身份字段（DOI/PMID/标题）的行会被丢弃、
记 error `missing_identity`、计入 `records_dropped`，并使退出码为 2。

## 输出

工作目录 `/app/work`，最终产物 `/app/output`：

- `merged.json`：合并后的唯一记录，逐字段含 `value/normalized/status/source_db/
  raw_file/raw_locator/source_record`，另含覆盖统计、库状态、缺口、issues。
- `provenance.csv`：每条"簇 × 字段 × 原始记录"一行，含库、查询、原始值、规范化值、
  定位符与是否被选为最终值，用于"库 → 查询 → 原始响应 → 映射 → 去重 → 合并"回溯。
- `conflicts.csv`：同一簇同一字段在不同库中规范化值不一致时，列出被选值与其余值。
- `duplicates.csv`：精确重复组与模糊重复候选（含 Jaccard、年份差、决策）。
- `report.md`：问题与库范围 → 按库查询与能力 → 字段映射 → 去重 → 冲突 → 覆盖与缺口
  → 逐条回溯示例 → 停止条件 → 复现步骤。
- `result.json`：原样保留 `case_id`，按 `/input/case.json` 的 `output_contract`
  逐字段映射真实结果。

`output_contract` 是动态契约：逐项读取字段名、类型、必填与说明，按实际契约输出并保留
原键名/层级；不得写死某题字段、不得删除契约字段、不得把 JSON Schema 描述当作答案。
契约缺失时才使用 `references/output-contract.md` 的默认结构。

## 六步工作流

1. **按库编排查询与字段能力。** 先列实际库集合，逐库记录：查询式、字段/语法限制、
   分页与额度、实际是否成功、返回多少条、原始响应在哪个文件哪一段。不同库不能机械
   复制同一查询；没有联网能力时明确写"使用组织方提供的快照/导出"，不声称实时调用。
2. **字段映射，区分缺失与未知。** 建立跨库映射：DOI、PMID、标题、作者、年份、期刊、
   文献类型、来源定位。空字符串表示"该库未提供"（缺失）；`unknown`/`N/A`/`null`
   等表示"库明确标记为未知"。两者在 `merged.json.fields.*.status` 中分别记为
   `missing` 与 `unknown`，不得互相替代，也不得用另一库的值伪装本库有该字段。
3. **精确去重，再给模糊候选。** 先按规范化 DOI、PMID 精确聚类；再对跨簇记录计算标题
   token Jaccard，仅当 `Jaccard >= 0.9` 且两边年份都存在、差值 `<= 1` 时列为
   `candidate_review`。默认只出候选，不自动合并；`--fuzzy-merge` 只有在案例契约或
   人工明确同意时才使用，并在报告中记录该决定。
4. **按 priority 合并并保留字段来源。** 同一簇内每个字段选择 priority 数值最小者
   （越小越优先）；并列时按 `source_db`、`raw_file`、`raw_locator`、`record_id` 排序，
   保证重跑一致。每个选中值都带来源库、文件、定位符与记录号；其余值写入
   `conflicts.csv`，不静默丢弃。
5. **逐条回溯。** 对每条合并记录，报告至少给出一个完整链路示例：
   `source_db → query → raw_file:raw_locator → 字段映射 → 所属簇/去重组 → 最终字段值`。
   `provenance.csv` 提供全量链路；摘要、结论和计数必须能沿链路核对。
6. **单库失败降级并说明缺口。** 某库超时、限流、无权限、字段变更或返回空时，继续用
   其余库产出，但在 `gaps` 与报告中写明：哪个库、什么状态、缺了哪些字段/记录、
   对合并结果的影响。不得用其他库的记录补造该库结果，也不得把"未覆盖"写成"无结果"。
   最后按契约生成 `result.json` 并核对计数闭合。

## 脚本命令

```bash
# 1) 索引实际输入，记录可读性与定位
python3 scripts/source_index.py extract --input /input --out /app/work/source-index.json

# 2) 合并多库记录（默认模糊只出候选，不自动合并）
python3 scripts/merge_records.py --input /input --out /app/work/merged \
  --fuzzy-threshold 0.9 --year-tolerance 1 \
  --priority-order "<从 case.json 读取的实际库优先级>"

# 3) 如需人工确认后合并模糊候选（必须记录理由）
python3 scripts/merge_records.py --input /input --out /app/work/merged --fuzzy-merge
```

脚本只用 Python 3 标准库、不联网、确定性输出。`--out` 是目录，写 `merged.json`、
`duplicates.csv`、`conflicts.csv`、`provenance.csv`、`issues.csv`。退出码：0 正常；
2 有记录被丢弃、文件不可读、没有任何可用记录，或某库明确不可用（仍产出并标注缺口）；
1 输入不可用。健康的库返回 0 条只记 `no_records`，不视为失败。
`report.md` 与 `result.json` 由执行者按实际结果撰写。

## 失败、空结果、权限与冲突

| 情况 | 处理 | `status` |
|-|-|-|
| 输入路径不存在 / 无 CSV/TSV/JSON/JSONL | 停止并说明实际检查；不生成空壳结论 | `blocked` |
| 某库超时、限流、无权限 | 其余库继续；`gaps` 记库名、状态、缺失字段；报告中说明影响 | `partial` |
| 某库返回 0 条 | 记为真实空结果（需有成功状态）；不与"未查询"混淆 | `partial` |
| 记录缺标题但有 DOI/PMID | 保留并用标识符聚类，标 `missing_title` | `partial` |
| 记录无 DOI/PMID/标题 | 丢弃并逐行记录 `missing_identity` | `partial` |
| 同一论文 DOI 大小写/前缀不同 | 规范化后精确合并 | `ok` |
| DOI 缺失，标题高度相似 | Jaccard≥0.9 且年份±1 才给候选；否则记 near_miss，不合并 | `ok` |
| 年份缺失或相差超过容差 | 不满足模糊条件，列入近失候选供复核 | `ok` |
| 字段值冲突（作者顺序、期刊名、类型、年份） | 按 priority 选值，其余写入 conflicts.csv | `ok` |
| 字段缺失 vs 明确 unknown | 分别记 `missing` 与 `unknown`，不互相填充 | `ok` |
| 编码异常/坏 JSON/坏 CSV | 跳过该文件或行并记录，其他文件继续 | `partial` |
| 撤稿、更正、预印本与正式版 | 保留为独立记录或用 DOI 精确合并；冲突与版本关系显式说明 | `partial` |

## 停止条件

满足任一即停止：案例列出的库都已记录成功或失败；所有实际文件已读取；新增记录不再
改变簇结构；达到案例给定的时间/额度/数量边界；`output_contract` 已全部填充且计数闭合。
停止时在报告中写：已覆盖库、失败库、未覆盖字段、仍待人工仲裁的模糊候选与冲突。

## 禁止编造

不生成不存在的记录、DOI、PMID、标题、作者、年份、期刊、类型或定位符；不把缺失字段填成
猜测值；不把模糊候选写成已确认重复；不伪造查询式、原始响应、库状态、额度或运行统计；
不声称实时多库检索或全球覆盖，除非实际执行并有记录。所有推断标注"推断"并给依据。

## 自查

- 重跑同一输入得到相同 `merged.json`；`records_valid + records_dropped = record_rows_read`。
- 每条合并记录的每个 `present` 字段都能在 `provenance.csv` 找到对应行和定位符。
- `conflicts.csv` 覆盖所有规范化值不一致的字段；`gaps` 覆盖所有失败/缺失库。
- `result.json` 覆盖 `output_contract` 全部字段，`case_id` 原样，`status` 与实际一致。
- 规则与阈值见 [references/method.md](references/method.md)，字段映射见
  [references/output-contract.md](references/output-contract.md)，逐项自检见
  [references/checklist.md](references/checklist.md)，合成示例见
  [examples/example.md](examples/example.md)（非官方案例）。
