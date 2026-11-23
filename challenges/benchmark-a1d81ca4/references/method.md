# 方法说明：从一次评测失败到可复核对照

## 1. 本题为什么不能只交题单

题面要求四件事：判得动、跑得一致、查得回、改得动。对应的最小可持续闭环是：

| 口径 | 本包实现 |
|---|---|
| 判得动 | 题卡必填字段校验 + 0/1/2 锚点 + 规则评分器 |
| 跑得一致 | 固定输入/工具/预算；`dataset_sha256` 可重算；确定性切分 |
| 查得回 | `checks/trace.json` 的 题目→答案→评分 链 + 哈希校验 |
| 改得动 | `dataset_version`、`change_log`、拒题记录、按题型/难度分桶 |

## 2. 一次真实失败如何被固化

本包针对的失败是“分数对不上、题判不了”：

1. **问 22 °C 答 65 %**：数值题原先取句内任意数字，题目主体含别的数值 → 不可判。现在只取句内唯一测量值，并跳过指数片段，生成期直接不产出这类题。
2. **gold=2 s**：`120 µmol m-2 s-1` 里的指数 `2 s` 被当成测量值。现在 `is_exponent_number` 过滤 `m-2`/`s-1`/`^` 形态。
3. **模板题冒充难例**：旧的“基准工具”只有题单与空壳检查。现在金标准全部来自原文单元，且每题必须带定位；没有可定位证据的候选不入库。

## 3. 防泄漏与训练/测试分离

- **生成期**：题干不得包含金标准、金标准中的数值或证据长引文（8-gram 重叠 ≥0.6 判为回显）。
- **终审**：成品逐题再跑一次，泄漏即丢弃并落盘。
- **切分**：`sha256(unit_id) mod 100 < 30` 进 dev，其余进 test；同一单元与同一引文哈希不会跨两侧。`selfcheck.py` 重算断言 `shared_units` 与 `shared_quote_hashes` 为空。
- 求解方只拿到 `public_test_items.json`，金标准、证据、评分锚点留在 `/app/work`。

## 4. 基线对照的意义与边界

- `extractive`：按题型检索证据句并抽取答案，带定位；`naive`：无检索控制组。
- 两者差值只说明“检索与定位是否有效”，**不是**参赛者相对官方白板的增益；报告里用 `interpretation` 字段显式声明。
- 基线分数低不是缺陷：它给的是可复算的下限与失败分布，用于归因（题型短板、定位缺失、数值误读）。

## 5. 失败归因

`failure_type` 覆盖：`wrong_value`、`wrong_content`、`partial_value`、`missing_or_wrong_anchor`、`partial_without_anchor`、`empty_answer`、`answer_too_long`、`format_invalid`、`question_echo`、`refusal_mismatch`、`gold_missing`。报告按题型/难度分桶统计，失败样例带题目、答案与判据，可直接转为下一版专项题。

## 6. 复现步骤

```bash
python3 scripts/run_bench.py --input examples/synthetic --out /tmp/out --work /tmp/work
python3 scripts/selfcheck.py --input examples/synthetic --out /tmp/out --work /tmp/work
```

两次运行 `dataset_sha256` 相同；`selfcheck.py` 会重建一次并断言一致。合成示例仅演示接口，不是正式案例结果。

## 7. 已知边界

- 规则建题只覆盖可定位题型；综述式、跨图推理题不在范围内。
- 词面匹配对长改写的召回有限，`token_coverage` 阈值（0.9/0.6）是显式口径，改动须升 `dataset_version`。
- PDF 无文本层时只记录不可读，不做 OCR 猜测；需 OCR 的案例应交给带 OCR 工具的执行环境并如实标注。
