# 方法说明：写作评测怎样才算“判得动”

## 1. 为什么不能只交一篇稿

题面要四件事：目标产物、事实与来源映射、版本与边界、可复核的评测。只要稿子没有来源映射，审稿人只能凭感觉判断“写得像不像”；一旦数字或限定条件被改，没人能复算。因此本包把“写作”拆成四类**可观察**判据：

| 判据 | 观察点 | 失败类型 |
|---|---|---|
| 事实保真 | 数值/单位是否齐全、是否混入材料外数字、限定条件是否还在 | `number_dropped`、`invented_number`、`lost_condition` |
| 结构完整 | 必需小节是否在、每节是否有来源锚点 | `section_missing`、`section_incomplete` |
| 引用映射 | 指定主张是否落稿、锚点是否指向真正支持它的单元 | `citation_missing`、`citation_incomplete` |
| 不编造 | 未报告项是否被赋予数值/结论 | `invented_for_absent`、`absence_not_stated` |

另有质量闸：整段照搬 ≥30 词判 `verbatim_copy`，最高 1 分——**复制不等于改写**。

## 2. 一次真实失败如何被固化

写作评测最常见的两类“分数对不上”：

1. **把材料未报告的指标写出数值**：旧检查只看关键词，不问“来源是否有这个数”。现在 `absence_guard` 的金标准是“未报告”，同句出现数值即 0。
2. **把来源段落原样粘进稿子拿满分**：旧评分奖励“关键词重合”。现在加入最长同文检测（`difflib` 词级最长公共块），≥30 词不给满分；真改写的稿子才能得 2。

这两条都写进 `change_log` 与评分自检，版本升级时必须重跑。

## 3. 防泄漏与隔离

- 金标准只落在 `/app/work/dataset.json`；写稿视图 `work/public_items.json` 去掉 `gold/evidence/rubric`。
- `/input/draft.md` 是被评稿件，**不进入来源建题**（`run_case.ingest_filtered` 显式剔除），否则等于拿稿子给自己出题。
- 建题自检断言：任何题面都不得包含其金标准数值；违反即 `no_gold_in_task=false`，状态降为 `partial`。

## 4. 两个控制组的含义与边界

- `template`：只给小节标题、正文占位，无来源无锚点——代表“看起来完整但不可核”。
- `extractive_writer`：把来源句子逐句拼进小节并加锚点——代表“保真但不算改写”的上限；事实题因照搬被压到 1 分。
- `provided`：外部交付稿，评分只针对它。
- 三者差值只说明“锚点与改写是否发生”，**不是参赛者相对官方白板的增益**；报告 `interpretation` 字段已声明。

## 5. 版本与边界

- `dataset_version` 变更触发条件：题型集合、单位表、照搬阈值、0/1/2 口径任一改动。
- `change_log` 逐条记录改了什么、为什么改。
- 规则评分的已知短板：不评价文风、连贯性与读者适配；这些需要人工复核，报告中不得声称规则分等同人工评审。

## 6. 复现步骤

```bash
python3 scripts/run_case.py --input examples/synthetic --out /tmp/out --work /tmp/work
python3 scripts/selfcheck.py --input examples/synthetic --out /tmp/out --work /tmp/work
```

自检会用同一输入重建数据集并比对 `dataset_sha256`，再重评 `draft.md` 比对逐题分数。合成示例仅演示接口，不是正式案例结果。
