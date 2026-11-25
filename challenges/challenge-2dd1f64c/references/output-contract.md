# 输出契约（output-contract）

`result.json` 顶层字段。若 `case.json.output_contract` 给出字段名，以它为准；本表为兜底与含义说明。

| 字段 | 类型 | 含义 / 复核点 |
|-|-|-|
| case_id | string | 输入 `case.json` 的 id 或文件名；必填 |
| status | string | `ok` / `partial` / `blocked`；partial/blocked 必须有 limits |
| summary | string | 一句话结论：输入条数、合并后条数、三层计数 |
| query_terms | object | `blocks`（概念块）与 `source`（case.concepts / query_tokens） |
| retrieval_scope | object | 使用的材料文件、记录数、合并数；`live_database=false` |
| relevance_rubric | object | 打分公式、三层阈值、k 值、并列规则 |
| dedup_summary | object | 输入/合并后条数、每次合并的保留项与被合并项 |
| ranked_candidates | array | 每条：rank、title、year、doi、score、score_parts、decision、confidence、matched、evidence、source{file,row}、reason、merged_from |
| screening_decisions | array | 每条：title、decision、reason、evidence |
| conflict_resolution | array | 标注分歧项：双方决定、升级理由 |
| recall_check | object | k、known_total、hit_at_k、recall_at_k、missed[{known,reason}] |
| stability_check | object | k、weight_variants、min_overlap、stable、tie_rule |
| exclusions | array | 被排除项与具体规则/阈值 |
| evidence_map | array | title → file/row/命中块 |
| assumptions / uncertainty / limits | array/string | 假设、未知、适用范围 |
| validation.checks | array | 每项 {check, pass, detail} |
| changes | array | 与上一版差异；首版为空数组 |

硬性规则：

1. `ranked_candidates` 必须覆盖全部合并后记录，不能只列前 k。
2. 每个 `source.row` 必须对应真实文件行号；不得用"某数据库"代替。
3. `score_parts` 之和必须等于 `score`（保留 1 位小数）。
4. 无 `known_relevant` 时 `recall_at_k=null` 并说明，不得用候选集自身当分母。
