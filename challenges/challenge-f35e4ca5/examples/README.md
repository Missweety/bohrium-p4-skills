# 最小调用示例（合成示例，非正式案例结果）

## 1. 文件

```
examples/
  case.json           # case_id + output_contract.required
  paper.md            # 图注、样本量、坐标轴声明（无像素内容）
  table_dose.csv      # 4 行原表：Dose / Viability / SEM / Significance
  target-fields.json  # 7 个待抽字段（轴类型、单位、n、单元格、显著性、误差）
```

本目录不含图片二进制：验证器只允许文本资源。真实案例的图片由平台提供，脚本会登记
文件名、格式、宽高、sha256，并明确 `pixel_reading=not_performed`。

## 2. 调用（任意 cwd，绝对路径）

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --input /skills/weekly-skill/examples --output /tmp/fig_out --work /tmp/fig_work
```

## 3. 产物

- `output/result.json` —— 契约要求的结构化结果
- `work/doc.json` —— 抽取中间表示（页/节/句/数值/表/图注/轴/图片）
- `work/field_results.json` —— 字段逐条结果
- `work/audit.json` —— 独立复核报告

## 4. 本机实测输出摘要（示例材料，非正式案例）

`status=success`，`tier=plain-text`；表格 1 张 4 行，坐标轴 2，图注 1；7 个字段全部
`reported`；16 条证据、4 个来源；`audit.pass=true`（113 个数值可回溯）。
具体数值只用于说明链路，**不代表正式案例结果或分数**。
