# 最小调用示例（SYNTHETIC，仅演示接口）

`examples/synthetic/` 下的材料是**作者合成的演示文本**，不是组织方案例，也不是任何论文；结果不构成对正式案例的评分。

## 输入

- `examples/synthetic/case.json`：含 `case_id=SYN-READ-001`、4 条 `workorder`（数值/表格/未报告/条件）、`output_contract` 字段列表。
- `examples/synthetic/task.md`：任务说明。
- `examples/synthetic/materials.md`：合成材料（含 22 °C、120 µmol m-2 s-1、1.42 g、表 T1、“No data on root elongation”、定义句、only when 限定句）。

## 调用

```bash
python3 scripts/run_bench.py --input examples/synthetic --out /tmp/out --work /tmp/work
python3 scripts/selfcheck.py --input examples/synthetic --out /tmp/out --work /tmp/work
```

## 预期（实测输出，示意）

```text
{
 "case_id": "SYN-READ-001",
 "status": "success",
 "items": 4,
 "by_type": {"numeric": 1, "table": 1, "absence": 1, "condition": 1},
 "extractive": 0.5,
 "naive": 0.0
}
PASS selfcheck: 25 checks, 0 failed
```

4 道题的实际形态（示意，非正式答案）：

| item | 题型 | 问题（节选） | 金标准 |
|---|---|---|---|
| B01 | numeric | …what value (with unit) is reported for red-dominant condition? | `45 %` |
| B02 | table | In Table T1, what is the "Replicates" value for Red-dominant? | `6` |
| B03 | absence | Does the source report a result or value for "root elongation"? | `not reported` |
| B04 | condition | What condition or scope does the source set for "The red-dominant spectrum was applied"? | `only when the culture density exceeded 0.8 g L-1; …` |

两个基线在测试集上的分数（0.5 / 0.0）是**本演示材料的实跑值**，只说明接口可用，不代表正式案例表现。

## 注意

- 示例目录只放 `case.json`、`task.md`、`materials.md` 三个文件；额外文件会被当成材料一起读入。
- 想复现异常路径：给 `--input` 一个空目录，会得到 `status=failed`、退出码 1、`uncertainty` 写明缺 `case.json`。
