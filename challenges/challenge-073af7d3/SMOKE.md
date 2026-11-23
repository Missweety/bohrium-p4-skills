# SMOKE（challenge-073af7d3 研究前沿与趋势分析 v1.1.1）

所有用例均为**本地合成数据**，仅验证接口与失败门控，不代表平台固定案例答案或得分。

## 正向用例（均为合成语料）

| 用例 | 输入 | 实测结果 |
|-|-|-|
| P1 题录 CSV 3 行 | 2019/2022 各 1 条 + 1 条无年份；`output_contract` 为 `[{name,type}]` 数组 | 纳入 3、矩阵 3 行；三行结果句互不串行；`missing_year=['S03']`；`status=partial`；`checks 12/12`；`report`/`research_product` 均回填，无 `fields:null` |
| P2 Markdown 2 篇 | 摘要后接 `## Results` 标题 | 两篇摘要均解析（修复前误报缺摘要）；`checks 12/12`；`status=partial`（2 篇 <5） |
| P3 BibTeX 2 条 | 同一 `.bib` 两条 | 每条只用本条题名+摘要；`checks 12/12`；`status=partial` |
| P4 重复题录 | 3 行中 1 行重复 DOI | 纳入 2、`duplicates=1`，报告写"排除 1 条（含重复 1 条）"；`checks 12/12` |
| P5 6 篇 2017–2022 | 题录 CSV | 年度 6 行、阶段 3 段；把 "transformer" 加入 2021/2022 两篇后 `emerging_terms=[transformer,2021-2022,2]`；`checks 12/12`；`status=ok` |
| P6 全部排除 | `exclusion_criteria` 命中全部 | 纳入 0，`reasons={exclusion_term:2}` 且报告列出排除原因；仍产出 `report.md`/`matrix.csv`；`status=partial` |
| P7 空行题录 | CSV 含 1 条有效记录 + 1 行全空 | 空行被丢弃（`found=1`），不借用整份文件文本；`checks 12/12` |
| P8 全部缺年份 | 3 条题录均无年份，指定 `year_from` | 3 条全部保留并标 `missing_year`；年度表为空并在 `limits` 说明；`checks 11/11`、`status=partial`，kernel PASS |
| P9 未知契约字段 | `output_contract={"custom_output":...,"report":...}` | `custom_output` 置 null 且写入 `limits`，不静默丢弃 |

## 反向门控

| 用例 | 操作 | 实测 |
|-|-|-|
| N1 缺 case.json | 指向不存在文件 | 退出码 1，`status=blocked`，`failures=[kernel.py init exited 1]` |
| N2 材料目录为空 | 空目录 | 退出码 1，`status=blocked`，无年度分布 |
| N3 引文篡改（首段） | 替换整句为原文不存在内容 | `quotes_verbatim FAIL` |
| N4 引文篡改（80 字符后） | 在真实引文后追加伪造尾句 | `quotes_verbatim FAIL`（已改为全文比对） |
| N5 年度计数篡改 | 修改 `trends.json` 某年 count | `year_counts_recomputable FAIL` |
| N6 题录跨行污染 | v1.0.0 对照：两行得到同一批 findings/quotes | v1.1.x 每行独立，`row_scoped_text=true` |
| N7 缺年份被丢弃 | v1.0.0 对照：`year_from` 时无年份行进 `excluded` | v1.1.x 保留并单列 `missing_year` |
| N8 契约数组丢失 | v1.0.0 对照：数组契约输出 `fields:null` | v1.1.x 按名字回填 |

## 降级路径核对（v1.1.x 实测）

- 年份跨度 <3：`status=partial`，`limits` 含"年份跨度 N 年(<3)，未强行三阶段"。
- 样本 <5：`emerging_terms=[]`，`emerging_suppressed=true`，`status=partial`。
- 缺年份：保留记录、标 `year_missing`，不进入年度表与阶段划分；全部缺年份时 kernel 不判失败。
- 纳入 0 篇：空矩阵 + 排除原因统计 + `status=partial`，不放宽标准。

## 结论

正向 PASS、反向门控可真实失败；`status=ok` 仅代表机检通过，不代表趋势判断已被人工评审认可。
