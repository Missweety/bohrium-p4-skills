
## 1.2.0 一致性与增益对照回归（2026-11-23，同一中文合成论文）

| 用例 | 实跑结果 |
|-|-|
| consistency 正例 | 仅 1 条：最大吸附量 摘要 48.2 vs 正文 42.7 mg/g，delta 11.4%，两侧引文原样返回 |
| consistency 误报回归 | 去除率 41.2/88.6 与正文同值，视为摘要复述，不报警；修复"句内多指标时数字归属错位"后通过 |
| baseline | 同一 corpus 与请求：白板 entries=12/fields=1/anchored=0；本 Skill entries=12/fields=6/anchored=12，可检索与可比较均为是 |
| v1.1.0 回归 | emit missing=none、check PASS、search hits=3、compare 仍生成并排矩阵 |
