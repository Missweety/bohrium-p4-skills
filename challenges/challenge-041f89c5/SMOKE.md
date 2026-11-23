# SMOKE — proposal-novelty-auditor v1.0.0

本地合成案例双向冒烟（非正式案例，不代表平台分数）。2026-11-21。

## 环境

```bash
python3 /tmp/mk_smoke_b.py     # 合成材料：records.json（5 条，含相反结论/超窗/离题）、notes.md、case.json
cp -R tracks/research/challenges/challenge-041f89c5/05_skills/submission /tmp/smoke_pkg_b
PYTHONDONTWRITEBYTECODE=1 python3 /tmp/smoke_pkg_b/scripts/run_case.py \
  --case /tmp/smk_prop/mat/case.json --materials /tmp/smk_prop/mat \
  --work /tmp/smk_prop/work --out /tmp/smk_prop/out
```

## P1 正向（应 PASS）

输出：`PASS status=partial sources=6 matrix=5 novelty=2 feasibility=conditionally_feasible`

- 来源 6（5 条题录 + 1 篇 notes.md）→ 决定：include 3 / maybe 2 / exclude 1
  （`IN_TOPIC_MATCH`×3、`REV_YEAR_MISSING`×1、`REV_NO_TOPIC_MATCH`×1、`EX_YEAR_OUT_OF_WINDOW`×1）。
- 证据矩阵 5 行：comparable 3 / partially_comparable 1 / not_directly_comparable 1。
- 创新 2 条：cl01 `partially_covered`；cl02（医学影像标注场景迁移）`unknown` + needs_human，
  未出现"首次/尚无人研究"。
- 可行性 3 条前提：unknown / assumed / assumed → `conditionally_feasible` 并列出条件与风险。
- 冲突 1 条 `conclusion_conflict`（scope_difference 仲裁）。
- 机检 8/8 pass：every_source_screened、every_decision_has_reason_code、
  every_matrix_row_has_locator、novelty_has_scope、feasibility_premises_stated、
  conflicts_registered、sources_traceable、contract_fields_present。
- 产物：result.json、evidence_matrix.csv、novelty.csv、feasibility.csv、conflicts.csv、
  report.md、run_manifest.json。

## N1 负向：case.json 缺失（应 FAIL → blocked）

```bash
PYTHONDONTWRITEBYTECODE=1 python3 /tmp/smoke_pkg_b/scripts/run_case.py \
  --case /tmp/smk_prop/empty/case.json --materials /tmp/smk_prop/empty \
  --work /tmp/smk_prop/empty_work --out /tmp/smk_prop/empty_out
```

结果：`BLOCKED status=blocked sources=0 matrix=0 novelty=0 feasibility=unknown`，exit 0；
novelty/matrix 为空，未编造评估结论。

## N2 负向：题录为空（应 FAIL → blocked）

材料仅有 `{"records": []}`，结果同上 `BLOCKED ... novelty=0 matrix=0`；
limits 写明"没有可读来源，无法产出评估结论"。

## 未覆盖

真实 9 来源/10 记录案例的 PDF 版式与中英文混排，只能由平台固定案例检验；
证据抽取为线索句摘录，`not_reported` 不等于文献没有做。

---

# SMOKE — proposal-novelty-auditor v1.1.0（2026-11-23，合成用例）

均在 /tmp 合成材料上实跑，非平台正式案例，不代表分数。

## S1 标题含 `/` 的去重

- 输入 records.json 含两条不同记录：`COVID-19/SARS-CoV-2 imaging study` 与
  `SARS-CoV-2 imaging study`（同年）。
- v1.0.0：`sources=3`，两条被并成 1 条（provenance 合并 row1+row2），记录丢失。
- v1.1.0：`sources=4`，两条各自保留，筛选分别给出决定。
- 命令：`python scripts/run_case.py --case /tmp/probe041b/materials/case.json --materials /tmp/probe041b/materials --work /tmp/probe041b/work2 --out /tmp/probe041b/out2`

## S2 字符串型 novelty_claims

- 输入 `"novelty_claims": "首次将扩散模型合成样本用于跨域少样本分类；提出类别平衡重加权策略"`。
- v1.0.0：`novelty=1`，且内容是从 proposal 抽的整段句，用户给的两条主张被丢弃。
- v1.1.0：`novelty=2`，cl01 `data` / cl02 `method`，均 `unknown` + scope，无"首次"断言。

## S3 声明 supported 但无证据的前提

- 输入前提 `{"premise": "需要 8 张 A100 GPU 算力", "status": "supported"}`，材料中无对应可引用句。
- v1.0.0：`status=supported` 但 `source.file/locator/quote` 全为 null，8 项机检仍全 pass（漏检）。
- v1.1.0：降级 `status=unknown` + `status_note`，`needs_check=true`；
  新增机检 `supported_premises_cite_source` 保证 supported 必带文件与逐字片段。

## S4 仅 year_to 时缺年份

- 输入 `year_to=2024`，一条记录 year 缺失。
- v1.0.0：`include / IN_TOPIC_MATCH`（未默认"不在窗内"，与 SKILL 规则冲突）。
- v1.1.0：`maybe / REV_YEAR_MISSING / needs_human=true`。

## S5 字符串型 prerequisites

- 输入 `"prerequisites": "需要 3 个公开跨域数据集；需要伦理审批"`。
- v1.0.0：`premises` 为空（字符串被忽略，只用 proposal 兜底）。
- v1.1.0：`prerequisites=2` 条，分别 unknown / unknown，按分号切开。

## S6 中文句号切句与文档兜底标题

- 输入 `"novelty_claims": "首次用扩散模型合成样本；提出类别平衡重加权策略。另提出自适应阈值机制"`。
- 中间版本：cl02 仍把两句粘在一起（`策略。另提出…`）；`refs/note.md` 兜底标题输出 `refs/note.md`。
- v1.1.0：cl01/cl02/cl03 三条；md 兜底标题为 `Notes`（取 H1 优先，其次文件名 stem）。
- 复跑：`python scripts/run_case.py --case /tmp/probe041d/materials/case.json --materials /tmp/probe041d/materials --work /tmp/probe041d/work5 --out /tmp/probe041d/out5`

## N3 负向：只有不支持的二进制材料

- 材料仅 `blob.bin`：`BLOCKED status=blocked sources=0 novelty=0 feasibility=unknown`，exit 0，未编造结论。
