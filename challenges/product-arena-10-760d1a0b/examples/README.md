# 示例（合成数据，非正式案例）

这里的三份文件只用来演示调用方式，**不是平台正式案例，也不是任何真实论文**。

| 文件 | 作用 |
| --- | --- |
| `demo_case.json` | case.json 示例：case_id + output_contract |
| `demo_manifest.json` | corpus-manifest.json 示例：两篇“论文”的 DOI/title/license |
| `demo_material.json` | material.json 示例：两篇段落，段落自带 `doi` |

## 运行方式

把三份文件复制到一个输入目录，按平台文件名放置后运行：

```bash
mkdir -p /tmp/demo_kg/input
cp demo_case.json       /tmp/demo_kg/input/case.json
cp demo_manifest.json   /tmp/demo_kg/input/corpus-manifest.json
cp demo_material.json   /tmp/demo_kg/input/material.json
python3 scripts/run_case.py --input /tmp/demo_kg/input \
  --work /tmp/demo_kg/work --output /tmp/demo_kg/output
```

预期（合成数据，仅供核对流程，不代表任何评分）：

- `documents=2`：两篇按 `doi` 分开，没有被合成一篇；
- 出现两个独立的 `Langmuir model` 节点，`alias_decisions` 为 `not_merged`；
- Q2 列出跨篇同名标签，Q4 报告 `maximum adsorption capacity` 的 88 vs 132 mg/g 差异；
- 每个节点/边带 `paragraph_id` 与逐字原文，`audit.pass=true`。

示例输出请以实际运行文件为准，本文不预置结果。
