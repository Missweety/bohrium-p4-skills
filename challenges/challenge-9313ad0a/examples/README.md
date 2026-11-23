# 最小调用示例（合成材料，仅演示接口）

> 以下输入与输出均为**合成示例**，用于说明 plan.json 的结构和调用方式，不是任何正式案例的答案，也不代表平台得分。

## 输入

`/input/case.json`（节选）：

```json
{"case_id": "synthetic-demo", "output_contract": ["mindmap", "evidence_index"]}
```

`/input/notes.md`（合成）：

```
研究问题：低温保存后细胞回收率是否下降。
方法：将样本分为对照组与冷冻组，各 12 个样本，冷冻组在 -80 度保存 7 天。
结果：对照组回收率 92%，冷冻组 71%，差异 21 个百分点。
结论：冷冻保存与回收率下降相关，但样本量有限，不能推断因果。
```

## plan.json（节选）

```json
{
  "case_id": "synthetic-demo",
  "title": "低温保存对细胞回收率的影响",
  "purpose": "实验前快速理解材料",
  "audience": "课题组成员",
  "root": {"id": "r", "label": "低温保存与细胞回收率", "type": "concept"},
  "nodes": [
    {"id": "r", "label": "低温保存与细胞回收率", "type": "concept", "confidence": "summary",
     "parent": null, "evidence": {"anchor": "doc.1 p.1 sec.1 para.1",
     "quote": "低温保存后细胞回收率是否下降"}}
  ],
  "edges": []
}
```

完整示例需包含 8 个以上节点；实际运行时由 Agent 根据真实材料填写，引文必须逐字来自原文。

## 调用与示意输出

```bash
python3 /skills/weekly-skill/scripts/extract_sources.py --input /input --out /app/work/sources.json
python3 /skills/weekly-skill/scripts/build_mindmap.py --plan /app/work/plan.json \
  --sources /app/work/sources.json --case /input/case.json --out /app/output --work /app/work
python3 /skills/weekly-skill/scripts/selfcheck.py --case /input/case.json --out /app/output --plan /app/work/plan.json
```

示意输出（合成）：

```
{"status": "success", "nodes": 9, "edges": 7, "verification_rate": 1.0, "issues": 0}
```

生成文件：`/app/output/mindmap.md`、`mindmap.mm`、`mindmap.svg`、`nodes.csv`、`result.json`、`checks.json`。
