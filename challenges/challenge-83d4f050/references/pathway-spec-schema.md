# 机制图 spec / 实体与边的数据模式

本文件描述 `work/spec.json`（自动抽取产物）与 `work/spec.manual.json`（人工/视觉补录）
共享的结构。自动路径由 `scripts/extract.py` 生成；手动路径通过
`run_case.py --spec ... --trust-evidence` 读入并由 `normalize_spec()` 归一。

## 1. 顶层对象

```json
{
  "mode": "create | edit",
  "case_id": "string",
  "title": "可选，图标题",
  "nodes": [ ... ],
  "edges": [ ... ],
  "conflicts": ["同名实体但 type/compartment 不一致的说明"],
  "isolated_entities": ["无任何边的实体 label"],
  "unresolved_edges": [{"source_text": "...", "target_text": "...", "kind_raw": "...", "reason": "..."}],
  "uncertainty": ["推断/歧义说明"],
  "limits": ["能力或环境限制"],
  "materials": [{"path": "...", "exists": true, "chars": 1234}]
}
```

`mode=edit` 时 `nodes/edges` 可以为空，编辑流程只读材料里的 SVG。

自动模式会先做**符号清单**：扫描每句话中的全大写符号（EGFR/PI3K/PTEN/AKT/EGF/BAX）、
含数字符号（FOXO3/PI3K/p53）、混合大小写符号（mTOR）与希腊字母符号（HIF-1α），
即使该句没有关系也建实体。`token_inventory` 记录清单，`token_recall` 必须 ≥0.8。
普通首字母大写散文词（Lab/The/Entity/Type/Compartment）会被过滤。

关系解析支持：`A 激活 B`、`A 抑制 B`、`A 结合 B 后激活 C`（A→C 激活，B 作为配体/
结合注释）、`A 被 B 激活后……并激活 C`（B→A 与 A→C）、`并/且/同时` 并列，
以及英文 `A is activated by B`。`A 与 B 的关系未说明` 进入 `unresolved_edges`，
不画边。

## 2. node

```json
{
  "id": "egfr",
  "label": "EGFR",
  "type": "receptor",
  "compartment": "membrane",
  "aliases": ["HER1", "ERBB1"],
  "status": "stated",
  "data_ref": "nodes[0]",
  "note": "",
  "evidence": [
    {"file": "paper.md", "locator": "line 12", "quote": "EGFR ...", "verified": true}
  ]
}
```

- `label` 必填；`id` 缺省时按 label 生成 slug。
- `type` 缺省时按名称启发式判断，最终默认 `protein`；`compartment` 缺省时推断，
  节点副标题加 `*` 并写入 `uncertainty`。
- 材料明确写 `位于细胞膜 / 在细胞质中 / 转位至细胞核 / translocated to the nucleus`
  时覆盖推断值；转位节点带 `translocation`（如 `cytoplasm -> nucleus`）。
- `aliases` 用于合并同名异写（基因/蛋白大小写、旧名、物种前缀）。合并后
  `element_map` 仍为每个节点一行，别名写入 `mechanism_graph.nodes[id].aliases`。
- `status`：`stated`（材料明确）/ `inferred`（由上下文推断）。
- `evidence` 可写成字符串；此时自动补 `file=材料首文件, locator=authored`。
  `--trust-evidence` 路径会把所有 `verified` 强制改为 `false`，但**不允许空 quote**。

## 3. edge

```json
{
  "id": "e1",
  "source": "egfr",
  "target": "akt1",
  "kind": "activation",
  "status": "stated",
  "data_ref": "relations[0]",
  "evidence": [
    {"file": "paper.md", "locator": "line 14",
     "quote": "EGFR activation promotes AKT phosphorylation.", "verified": true}
  ]
}
```

- `source` / `target` 必须是某个 node 的 `id`、`label` 或 alias；解析失败进入
  `unresolved_edges`，**不绘制**。
- `kind` 必须落在第 4 节词表内；解析失败同样进入 `unresolved_edges`。
- 去重键为 `(source, target, kind)`，重复关系只保留一条。

## 4. 词表（`scripts/graphlib.py`，唯一权威）

### 4.1 实体类型 `type`

| 值 | 中文 | 形状 | 颜色 |
|---|---|---|---|
| `gene` | 基因 | 方角框 | `#0072B2` |
| `protein` | 蛋白/酶 | 圆角框 | `#009E73` |
| `complex` | 复合物 | 椭圆 | `#CC79A7` |
| `receptor` | 受体/通道/整合素 | 圆角框 | `#56B4E9` |
| `compound` | 化合物/药物 | 六边形 | `#E69F00` |
| `organelle` | 细胞器 | 椭圆 | `#D55E00` |
| `cell` | 细胞 | 大圆角框 | `#F0E442` |
| `metabolite` | 代谢物/离子 | 六边形 | `#56B4E9` |
| `process` | 通路/过程 | 圆角框 | `#000000` |
| `other` | 其它 | 圆角框 | `#6B7280` |

别名（不区分大小写）：`gene/DNA/locus`、`protein/enzyme/kinase`、
`complex/complex_component`、`receptor/channel/integrin/GPCR`、
`compound/drug/inhibitor/chemical`、`organelle/mitochondria/lysosome`、
`cell/cell_type`、`metabolite/ion/molecule`、`process/pathway`。

### 4.2 区室 `compartment`（固定四条带，自上而下）

| 值 | 中文 | 同义词 |
|---|---|---|
| `extracellular` | 细胞外 | extracellular space, secreted, 胞外, 细胞外空间, 分泌 |
| `membrane` | 细胞膜 | plasma membrane, cell membrane, 质膜, 膜, 跨膜 |
| `cytoplasm` | 胞质 | cytosol, intracellular, 胞内, 细胞质, 胞浆 |
| `nucleus` | 核内 | nuclear, 细胞核, 核 |

### 4.3 关系极性 `kind`

| 值 | 语义 | 线型 | 头部 |
|---|---|---|---|
| `activation` | 激活/促进/上调/诱导 | 实线 | 实心三角 |
| `inhibition` | 抑制/阻断/下调/负调控 | 实线 | T 形端 |
| `binding` | 结合/募集/互作/形成复合物 | 实线 | 两端空心圆 |
| `modification` | 磷酸化/泛素化/乙酰化/切割 | 虚线 | 菱形 |
| `transport` | 转运/入核/出核/分泌/易位 | 点划线 | 空心箭头 |
| `flow` | 流向/转化/催化/代谢流 | 实线 | 细空心箭头 |

别名：`promote/activate/upregulate/促进/激活/上调 → activation`；
`inhibit/suppress/block/repress/抑制/阻断/下调 → inhibition`；
`bind/recruit/interact/结合/募集/互作 → binding`；
`phosphorylate/ubiquitinate/cleave/修饰/磷酸化 → modification`；
`transport/translocate/import/export/转运/入核 → transport`；
`flow/converts/catalyzes/流向/转化 → flow`。

## 5. 最小手动 spec 示例

```json
{
  "mode": "create",
  "title": "EGFR → AKT 通路（合成示例）",
  "nodes": [
    {"label": "EGF", "type": "compound", "compartment": "extracellular",
     "evidence": "EGF is secreted into the extracellular space."},
    {"label": "EGFR", "type": "receptor", "compartment": "membrane",
     "evidence": "EGFR spans the plasma membrane."},
    {"label": "AKT", "type": "protein", "compartment": "cytoplasm",
     "evidence": "AKT is phosphorylated in the cytoplasm."},
    {"label": "FOXO3", "type": "protein", "compartment": "nucleus",
     "evidence": "FOXO3 is retained in the nucleus."}
  ],
  "edges": [
    {"source": "EGF", "target": "EGFR", "kind": "binding", "evidence": "EGF binds EGFR."},
    {"source": "EGFR", "target": "AKT", "kind": "activation",
     "evidence": "EGFR activation promotes AKT phosphorylation."},
    {"source": "AKT", "target": "FOXO3", "kind": "inhibition", "status": "inferred",
     "evidence": "AKT phosphorylates and excludes FOXO3 from the nucleus."}
  ]
}
```

## 6. 边界规则

- 长 CJK 标签：布局按 `node_w-56` 自动换行，最多 3 行；超长仍以 `*`/省略号收尾，
  不越出节点。需要更宽的图时改 `layout.py` 的 `W`。
- 重名/别名：进入同一 `node_key` 的实体合并；若 `type` 或 `compartment` 不同，
  写入 `conflicts`，并在图上保留首个值、`uncertainty` 说明。
- 缺区室：按名称/类型推断并标 `*`；四带中空带写明“未提取到实体”，不画占位节点。
- 没有可用实体或关系：`nodes==0 || edges==0` → `status=blocked`，不生成图。
