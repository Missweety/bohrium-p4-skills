# 最小调用示例（**示例数据，非正式案例结果**）

## 1. 输入

```
input/
  case.json          # 案例与论文标识 + 段落清单 + 问题清单
  task.md            # 题面
```

## 2. 调用

```bash
python3 scripts/lane_qa.py --input ./input --output ./output --work ./work
```

## 3. 产物

- `work/qa_context.json` —— 段落、问题、逐题候选
- `output/result.json` —— 契约结果（答案由模型复核后填写）

## 4. 示意输出（**示例数据，非正式案例结果**）

```json
{
  "case_id": "example-case-id",
  "paper_id": "example-paper-id",
  "material_version": "v1",
  "status": "partial",
  "answers": [
    {
      "question_id": "q1",
      "answer": "示例：该方法在示例材料中报告了 …",
      "conditions": ["示例：温度 25 °C，对照组为基线模型"],
      "status": "answered",
      "claims": [
        {
          "claim_id": "q1-c1",
          "text": "示例：方法在示例条件下优于基线",
          "kind": "reported",
          "evidence": [{"paragraph_id": "p12", "quote": "示例原文短引文"}]
        }
      ],
      "unanswered_parts": []
    }
  ],
  "coverage": {"read_sections": ["示例：Results"], "unread_sections": ["示例：Discussion"], "reasons": []},
  "sources": [{"file": "case.json", "locator": "paragraph_id=p12", "note": "示例用途"}],
  "uncertainty": {"level": "medium", "notes": ["示例：某问题材料未报告，按 insufficient_evidence 处理"], "unresolved": ["q2"]},
  "change_log": ["示例：发现段落、生成候选、逐题复核、运行独立复核"]
}
```
