# 最小调用示例（SYNTHETIC，仅演示接口）

`examples/synthetic/` 是作者合成的演示材料（一项虚构的“街道树冠降温”试验），不是组织方案例，也不是真实论文；结果不构成对正式案例的评分。

## 输入

- `case.json`：`case_id=SYN-WRITE-001`、`audience`、`required_sections`、`max_chars`、`output_contract`。
- `task.md`：任务说明。
- `materials.md`：含 `15 %`、`35 %`、`12 m`、`3.2 °C`、`4.1 °C`、`33 °C`、`48 stations`、表 T1、`No data on night-time temperature…`、`only when … exceeded 12 m`。

## 调用

```bash
python3 scripts/run_case.py --input examples/synthetic --out /tmp/out --work /tmp/work
python3 scripts/selfcheck.py --input examples/synthetic --out /tmp/out --work /tmp/work
```

## 实测输出（本演示材料，示意）

```text
{
 "case_id": "SYN-WRITE-001",
 "status": "success",
 "items": 7,
 "by_type": {"fact_preserve": 2, "section_coverage": 1,
             "citation_map": 3, "absence_guard": 1},
 "extractive_writer": 0.9286,
 "template": 0.1429
}
PASS selfcheck: 25 checks, 0 failed
```

（示例目录实测时 `template` 得 0.1429＝2/14：来自“小节齐全但无锚点”的 1 分与“未报告项沉默未编造”的 1 分；`extractive_writer` 唯一失分是整段照搬被判 `verbatim_copy` 封顶 1 分。）

## 有外部稿时

1. 先跑一次，查看 `work/units.json` 的 `unit_id`（如 `materials.md#P4`）。
2. 把稿子写到 `/input/draft.md`，在每节末尾放 `[src: <unit_id>]`。
3. 再跑一次；`result.deliverable.source_of_draft` 应为 `provided`。

用真实改写稿（含全部数值、锚点、未报告表述）实测得到 `provided = 1.0`，说明评分器奖励的是“保真+改写”，而不是照搬或模板。

## 注意

- `/input/draft.md` 不会作为来源参与建题。
- 空目录测试：`--input` 指向空目录 → `status=failed`、退出码 1、`uncertainty` 写明缺 `case.json` 与无题可建。
