# 最小调用示例（合成示例，非正式案例结果）

## 1. 目录

```
input/
  case.json          # 案例元数据 + output_contract
  task.md            # 题面
  <材料文件>          # 论文 / 工作单 / 目标字段表
```

## 2. 调用

```bash
python3 scripts/run_case.py --input ./input --output ./output --work ./work
```

## 3. 产物

- `output/result.json` —— 契约要求的结构化结果
- `work/doc.json` —— 抽取中间表示
- `work/audit.json` —— 独立复核报告

## 4. 示意输出（**示例数据，非正式案例结果**）

```json
{
  "case_id": "<示例-case-id>",
  "status": "partial",
  "sources": [
    {"file": "<示例材料>", "locator": "p.1/sec.1/sent.1", "note": "<用途>"}
  ],
  "uncertainty": {
    "level": "medium",
    "notes": ["示例：某字段原文未报告，按 not_reported 处理"],
    "unresolved": []
  },
  "change_log": ["示例：抽取正文、装配契约字段、运行独立复核"]
}
```
