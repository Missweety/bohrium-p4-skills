# 最小调用示例（合成数据，非正式案例结果）

> 文献与年份均为本地合成，仅说明接口与输出形状，**不是**平台固定案例答案。

## 输入

```bash
mkdir -p /tmp/trend_demo/materials /tmp/trend_demo/case
cat > /tmp/trend_demo/materials/records.csv <<'EOF'
title,year,doi,abstract
Single-cell atlas of tissue X,2019,10.1000/d.2019.1,"We found 12 cell types in tissue X (n=8)."
Single-cell atlas replication,2021,10.1000/d.2021.2,"Results show 11 cell types; no significant difference from prior atlas (p=0.3)."
Spatial transcriptomics of tissue X,2022,10.1000/d.2022.3,"We found spatial domains correlated with cell types (p<0.01)."
Benchmark of cell type annotation,2023,10.1000/d.2023.4,"We found annotation accuracy improved to 0.91 (n=30)."
EOF
```

```json
{"case_id": "demo-trends-001",
 "research_question": "组织 X 的单细胞研究趋势",
 "materials": ["/tmp/trend_demo/materials"],
 "year_from": 2010, "year_to": 2024,
 "output_contract": {"research_product": null, "evidence_matrix": null,
                     "uncertainty": null, "status": null}}
```

## 调用

```bash
python3 scripts/run_case.py --case /tmp/trend_demo/case/case.json \
  --work /tmp/trend_demo/work --out /tmp/trend_demo/output --mode trends
```

## 示意输出（示例）

`report.md` 片段：

```markdown
## 2. 年度产出与阶段
| 年份 | 篇数 | 来源 |
|-|-|-|
| 2019 | 1 | S01 |
| 2021 | 1 | S02 |
| 2022 | 1 | S03 |
| 2023 | 1 | S04 |

## 3. 主题演化
- 阶段1（2019-2021，2 篇）：主题词 cell / tissue；代表作 `[S01]` Single-cell atlas...、`[S02]` ...
- 阶段2（2022-2023，2 篇）：主题词 spatial / annotation；代表作 `[S03]`、`[S04]`。
- 候选新兴词：spatial(1)、annotation(1)（不满足≥2 篇，未列为新兴主题）。

## 5. 代表性工作口径
- 按"有全文 > 年份更早 > 结果句更多"选取，不按被引数（材料未提供）。
```

`result.json` 摘要：

```json
{"case_id": "demo-trends-001", "status": "partial",
 "research_product": {"question": "组织 X 的单细胞研究趋势",
                      "trends": {"distribution": [{"year": 2019, "count": 1, "sources": ["S01"]}],
                                 "stages": [{"stage": "阶段1", "years": [2019, 2021], "count": 2,
                                             "top_terms": ["cell", "tissue"]}]}},
 "counts": {"included": 4, "themes": 2, "years": 4},
 "limits": "4 篇、4 个年份；样本量小，未做新兴/衰退判断；3 篇缺全文，证据强度下调"}
```

该示例 `status=partial` 是因为样本小且缺全文，不是运行失败。
