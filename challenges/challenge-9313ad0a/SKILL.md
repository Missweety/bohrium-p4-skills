---
name: evidence-mindmap
description: Build an evidence-anchored, editable mind map from supplied scientific materials. Use for 思维导图 / mind map / knowledge map: extracts concepts, questions, methods, evidence, results, conclusions, tasks and risks, links them with typed directed relations, attaches a page/paragraph quote to every node, validates the tree, and exports editable Markdown, FreeMind (.mm) and a real rendered SVG plus result.json.
---

# 证据可溯源的思维导图

把给定科研材料整理成**可打开、可读、可继续编辑、每条节点都能回到原文**的思维导图，并输出结构化结果供复核。

## 适用与不适用

- 适用：论文、综述、技术报告、实验方案、会议纪要、项目材料的单篇或多篇整理；材料为带文本层的 PDF、DOCX、Markdown、TXT、TeX、CSV、HTML。
- 不适用：纯扫描图片且 OCR 不可用、材料为空、需要联网补造内容。遇到时如实降级为 `partial` 并写明缺口，不猜测。

## 调用方式

```bash
python3 /skills/weekly-skill/scripts/extract_sources.py --input /input --out /app/work/sources.json
python3 /skills/weekly-skill/scripts/build_mindmap.py \
  --plan /app/work/plan.json --sources /app/work/sources.json \
  --case /input/case.json --out /app/output --work /app/work
python3 /skills/weekly-skill/scripts/selfcheck.py \
  --case /input/case.json --out /app/output --plan /app/work/plan.json
```

执行顺序固定：**先抽取、再建图、最后自检**。`selfcheck.py` 退出码非 0 时必须修复后重跑，不得把失败结果当作完成。

## 完整流程

1. **读任务与材料**：读 `/input/case.json`、`/input/task.md` 和全部材料文件。从 `case.json` 的 `output_contract` 取出**全部字段名**；这些字段必须出现在 `result.json` 中。任务只要求一个子场景时，只建该子场景的图，不扩写无关领域。
2. **抽取原文**：运行 `extract_sources.py`。它给每个段落分配稳定锚点：`doc.N` 文档、`p.N` PDF 页、`sec.N` 章节、`para.K` 段；同时计算文件 sha256。不要跳过这一步手工编造锚点。
3. **写 plan.json**：这是本 Skill 的核心产物。按 `references/node-schema.md` 的字段写节点与关系，每个节点必须给 `evidence.quote`（原文逐字片段，10–200 字）和 `evidence.anchor`，并标注 `confidence`：
   - `fact`：原文直接陈述；
   - `summary`：对多段原文的归纳；
   - `inference`：材料支持的推断，必须写 `basis` 说明依据。
4. **建图导图**：运行 `build_mindmap.py`。它会校验树结构、关系端点、引文能否在原文找到，然后生成：
   - `/app/output/mindmap.md`：缩进大纲，含节点类型、置信度与锚点，可直接编辑；
   - `/app/output/mindmap.mm`：FreeMind/XMind 可打开的 XML；
   - `/app/output/mindmap.svg`：脚本实际布局渲染的矢量预览；
   - `/app/output/nodes.csv`：节点证据表，便于逐条核对；
   - `/app/output/result.json`：契约结果。
   引文校验不通过的节点会被标为 `unverified` 并写入 `issues`，不得静默通过。
5. **自检**：运行 `selfcheck.py`，检查契约字段、文件存在、XML 可解析、节点与关系完整性、引文核验率、占位文本。失败项修 plan 后重跑。
6. **诚实收尾**：`status` 只在 `success` / `partial` / `failed` 中取一个。材料缺口、无法读取的文件、互相矛盾的原文、需人工确认的判断，分别写入 `uncertainty` 与 `issues`。

## 节点与关系规则

- 根节点=整理对象；一级分支按用途取 3–7 个（例如 研究问题、方法、证据、结论、任务、风险）。
- 层级 3–5 层，单层同类节点不超过 9 个；超出时合并同类，避免节点爆炸。
- 节点标签 4–40 字，必须是名词短语或明确命题，不写装饰性标题。
- 关系类型：`causes`、`depends_on`、`supports`、`contradicts`、`compares`、`precedes`、`cites`、`part_of`。方向从因到果、从证据到结论、从前提依赖到后续步骤。
- 没有原文依据的连接不建；确需保留的推断连接必须在该边上标注 `"basis"` 并让 `confidence` 为 `inference`。
- 同一概念只保留一个节点，其他位置用 `aliases`。

## 异常处理

| 情况 | 处置 |
|---|---|
| 文件无文本层 / 解析失败 | 记录 `unreadable` 与原因；其他材料继续；整体 `partial` |
| 材料互相矛盾 | 两个节点都保留，关系用 `contradicts`，各自挂原文引文 |
| 节点超出上限 | 合并同类，保留信息量大的节点，合并记录写入 `change_log` |
| 引文找不到 | 节点标 `unverified`，写入 `issues`，不得当作事实 |
| 缺少 `output_contract` | 仍输出 `mindmap`、`nodes`、`edges`、`evidence`、`status`、`sources`、`uncertainty`、`change_log`，并说明契约缺失 |
| 无渲染工具 | SVG 由脚本自身生成，不依赖 graphviz；PNG 可选，缺失时如实说明 |

## 交付清单

- `mindmap.md`、`mindmap.mm`、`mindmap.svg`、`nodes.csv`、`result.json`、`checks.json`
- `result.json` 必含：`case_id`、`status`、`sources`、`uncertainty`、`change_log`、`mindmap`、`nodes`、`edges`、`evidence_index`，以及 `output_contract` 声明的全部字段。
- 节点与关系都带锚点或明确推断依据；未核验项显式列出。

最小调用示例见 `examples/README.md`（合成材料，仅演示接口，不是正式案例答案）。
