# 复现协议与统计口径

## 1. 复现边界

本 Skill 的“复现”最多到**纸面可复算**：

1. 从原文抽取复现计划（数据、环境、参数、命令、代码）；
2. 对原文明确给出的统计关系做确定性复算（t/df→p、z→p、前后值→百分比变化）；
3. 逐条比较复算值与报告值；
4. 按依赖完整度与一致性给出判定。

不下载数据、不训练模型、不安装作者依赖、不重跑作者的完整流水线。因此即使
所有统计都一致，只要数据/代码/参数缺失，最多算 `partially_reproduced`。

## 2. 统计公式

设 `I_x(a,b)` 为正则化不完全 Beta 函数（Numerical Recipes 连分式，收敛阈值 3e-12）：

- 双侧 Student-t：`p = I_{df/(df+t²)}(df/2, 1/2)`；
- 双侧正态：`p = erfc(|z|/√2)`（`math.erfc`）；
- 百分比变化：`pct = (to - from) / from * 100`；
- 若原文写 “decreased / reduction / 降低”，比较幅度 `|pct|` 与 `|reported|`。

示例（可复算）：`t(28)=2.45 → p=0.0207965`；`t(28)=1.10 → p=0.280702`；
`82.4 → 79.1 → -4.0049%`。

## 3. 容差

容差取报告值的小数精度，避免把四舍五入误判为冲突：

| 报告写法 | 容差 |
| --- | --- |
| `p = 0.02` | 0.005 |
| `p = 0.001` | 0.0005 |
| `p < 0.001` | 按不等式：复算值必须 < 0.001 |
| `p > 0.05` | 按不等式：复算值必须 > 0.05 |
| `4.0%` | max(0.05, 0.05) |

## 4. 判定规则

```
存在 inconsistent                    -> recomputed_inconsistent
存在 consistent 且 五类依赖齐全        -> recomputed_consistent
存在 consistent 但依赖不全             -> partially_reproduced
无 check 且 无数据/代码                -> not_reproducible
无 check 但有依赖/仅有定性表述          -> not_checkable
有 check 但缺 p/df                    -> not_checkable
```

## 5. 计划抽取规则

- 只从句子中抽取，value 必须是原文片段（参数值为原文数字）；
- `available on request`、`应要求提供` 不算已提供，状态为 missing；
- 未出现某类别时，写入一条 missing 占位，note 说明“未按惯例补默认值”；
- 命令识别：`$ ...`、`python x.py`、`Rscript ...`、`bash ...`、`analysis script`。

## 6. 已知限制

- 只支持 t、z、百分比变化三类关系；F、χ²、回归系数、生存分析不自动复算（标 not_checkable）。
- PDF 需有文本层；扫描件不可读。
- 语言规则以英文/中文为主；复杂跨句指代不解析。
- 图片中的数值、补充材料中的表格无法读取时会标 missing，不猜测。
- 依赖完整性判断是文本级判断：作者给了仓库 URL 但没写版本，仍视为 code 已提供、
  environment 可能缺失；报告会如实列出缺失项。
