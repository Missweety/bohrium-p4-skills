# SMOKE - challenge-2dd1f64c（文献筛选与智能排序）

环境：本地合成夹具，**非平台正式案例/标准答案**；脚本仅标准库，Python 3.13。

## 正向 + 对抗夹具（同一批）

夹具 `/tmp/t1/mat`：`case.json`（概念块 3 个、年份/类型/语言/排除词、`known_relevant` 含标题/DOI/对象）、
`records.csv`（7 行：同 DOI 预印本+正式版、1 行无标题、越界年份、`fr` 语种、排除词）、
`extra.jsonl`（1 行合法 + 1 行坏 JSON）、`broken.json`（非法 JSON）。

```bash
python3 scripts/run_case.py --case /tmp/t1/mat/case.json \
  --materials /tmp/t1/mat --work /tmp/t1/work --out /tmp/t1/out
```

实际结果：`PASS`；`status=ok`；输入 7 → 合并 6；保留 3 / 待定 0 / 排除 3；
预印本并入正式版（`merged_from` 只记被合并版本，长度 1）；
`known_relevant` 4 条命中 3 条（`recall_at_k=0.75`），对象形式的已知项不再误报 `not_in_corpus`；
`uncertainty` 记录 1 条缺摘要、`broken.json` 不可读、`extra.jsonl` 第 2 行坏、CSV 1 行无标题；
`validation.checks` 全部 pass（含 `rank_monotonic_by_decision`、`no_silent_drops`）；
排除项 rank 整体大于保留/待定项，未出现“位次更靠后但分数更高”。

## 负向（PASS，按预期）

```bash
mkdir -p /tmp/t1c/empty
python3 scripts/run_case.py --case /tmp/t1/mat/case.json \
  --materials /tmp/t1c/empty --work /tmp/t1c/work --out /tmp/t1c/out
```

实际结果：`status=blocked`，`limits=候选集为空：只能说明未完成，不补造文献。`，未产出排序。

## 无概念块（PASS，按预期 partial）

`/tmp/t1b/mat/case.json` 只给 `case_id` 与空已知集、1 条记录：
`status=partial`；记录 `decision=maybe`、`reason=no_query_terms_defined`；
`uncertainty` 说明“相关性分数不可计算”，未把 0 分当“不相关”。

## 校验

```bash
python3 validators/validate_submission.py --outputs tracks/literature-search/challenges/challenge-2dd1f64c/05_skills_iter2 --json
```
