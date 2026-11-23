---
name: mechanism-pathway-diagram
description: Build editable, evidence-traced biological mechanism / pathway diagrams (SVG + PNG + PDF) from case materials, or edit an existing SVG in place. Inventories every symbol token (EGFR, PI3K, mTOR, p53, BAX), parses active/passive and conjunction relations, applies explicit compartment/translocation statements, and draws activation/inhibition/binding/modification arrowheads with per-element source quotes, isolated entities and unresolved relations.
metadata:
  version: "2.1.0"
---

# 生物机制图 / 通路图 Skill

面向 `biological_mechanism_pathway` 任务：把论文正文、PDF、表格或已有 SVG 转成**可编辑、可追溯、可检查**的机制图。核心原则是**宁可不画，也不画错**：没有证据的机制不出现；实体/关系为零时返回 `status=blocked`，绝不生成空图或占位图。

## 1. 一键运行（首选）

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --case /input/case.json --materials /input \
  --out /app/output --work /app/work
```

若 Skill 被安装到 `/app/submission`，把 `/skills/weekly-skill` 换成 `/app/submission` 即可。命令会依次完成：契约读取 → 材料抽取 → 区室布局 → SVG → PNG/PDF → 自检 → `result.json`，最后打印 `PASS ...`。

**必须做的一步**：用支持看图的工具打开 `/app/output/figure.png`，逐项确认
① 箭头头部可区分（实心箭头 / T 形端 / 空心圆 / 虚线菱形）；
② 节点文字没有被裁切、没有互相压住；
③ 四个区室带、图例、标题都在；
④ 推断项是虚线轮廓或虚线箭头。
如不满足，先调 `scripts/layout.py` 顶部的 `W/NODE_H/ROW_H/BOTTOM` 常量或改用第 7 节的手动 spec 重跑；不要提交有重叠的图。

## 2. 输入

| 输入 | 说明 |
|---|---|
| `/input/case.json` | 任务、`output_contract`、实体/关系（可选）、材料路径。字段名容错（`entities/nodes`、`relations/edges`、`kind/polarity/type` 等）。损坏时自动降级并记录。 |
| `/input/task.md` | 任务说明；`kernel.py` 会并入 `task_text`，用于编辑意图识别。 |
| 其他材料 | `.md/.txt/.csv/.tsv/.json/.xlsx/.docx/.pdf` 自动抽文本；图片/扫描件交给第 7 节人工读图。可多份。 |

## 3. 输出（`/app/output`）

| 文件 | 作用 |
|---|---|
| `figure.svg` | 可编辑矢量图，**真实 `<text>`**，每个节点/边是带 `<title>/<desc>` 的 `<g>`，含 `data-*` 语义属性。 |
| `figure.png` | 非平凡预览（≥800×600、颜色数>1500、非白像素>1%），用于人工检查。 |
| `figure.pdf` | 打印/投稿用矢量 PDF。 |
| `result.json` | 完整契约结果（见 `references/output-contract.md`）。 |
| `element_map.json` | 逐实体、逐边的来源行：`file / page / section / quote / data_ref / status`。 |
| `caption.md` | 图注（中文为主，含箭头语义、证据覆盖、推断/冲突/未解决项）。 |
| `selfcheck.json` | 机器自检结果（PASS/FAIL、errors、warnings、stats）。 |

`result.json` 同时包含 `case_id, status, deliverables, element_map, caption, selfcheck, limits, uncertainty, sources, change_log, nodes, edges, compartments, mechanism_graph, metrics`。契约里的每个字段都会被映射填充；未知字段置 `null` 并写入 `unmapped_contract_fields`，**不会**额外包一层 `fields`。

## 4. 机制语义（写死在同一份词表里）

### 4.1 实体类型

| type | 中文 | 颜色（Okabe–Ito） | 形状 |
|---|---|---|---|
| gene | 基因 | `#0072B2` | 方角框 |
| protein | 蛋白/酶 | `#009E73` | 圆角框 |
| complex | 复合物 | `#CC79A7` | 椭圆 |
| receptor | 受体/通道/整合素 | `#56B4E9` | 圆角框 |
| compound | 化合物/药物/抑制剂 | `#E69F00` | 六边形 |
| organelle | 细胞器 | `#D55E00` | 椭圆 |
| cell | 细胞 | `#F0E442` | 圆角框 |
| metabolite | 代谢物/离子 | `#56B4E9` | 六边形 |
| process | 通路/过程 | `#000000` | 圆角框 |
| other | 其它 | `#6B7280` | 圆角框 |

未给 type 时按名称启发式判断，**默认 protein**（机制图里最常见），并在 `uncertainty` 标注。

### 4.2 区室（固定四条带，自上而下）

`extracellular` 细胞外 → `membrane` 细胞膜 → `cytoplasm` 胞质 → `nucleus` 核内。
同义词（`cytosol/intracellular/胞内`、`plasma membrane/质膜`、`nuclear/核内` 等）会归一。缺区室时按名称/类型推断，节点副标题加 `*`，并写入 `uncertainty`；不伪造定位。
材料明确写 “位于细胞膜 / 在细胞质中 / 转位至细胞核 / translocated to the nucleus” 时以材料为准，覆盖推断值；转位会写入 `translocation`（如 `cytoplasm -> nucleus`）并在图注/`uncertainty` 说明。

### 4.3 关系极性（箭头头部必须不同）

| kind | 语义 | 线型 | 头部 |
|---|---|---|---|
| activation | 激活/促进/上调 | 实线 | 实心三角箭头 |
| inhibition | 抑制/阻断/下调 | 实线 | T 形端 |
| binding | 结合/募集/互作 | 实线 | 两端空心圆 |
| modification | 磷酸化/泛素化等修饰 | 虚线 | 菱形 |
| transport | 转运/入核/分泌 | 点划线 | 空心箭头 |
| flow | 流向/转化/催化 | 实线 | 细空心箭头 |

**推断**（方向靠就近实体推断、只有结构化关系没有原句）用虚线箭头，并在 `uncertainty` 明说；**未解决**（端点缺失、极性词缺失/歧义）不绘制，写入 `unresolved_edges`。绝不为了让图好看补一个端点。

## 5. 证据链

每个实体、每条边都必须有一行 `element_map`：

```json
{"element":"node:egfr","label":"EGFR","kind":"entity","type":"receptor",
 "compartment":"membrane","source":"paper.md#line 12","file":"paper.md",
 "page":null,"section":"line 12","quote":"EGFR activation promotes AKT ...",
 "quote_verified":true,"data_ref":"nodes[0]","status":"stated"}
```

- `quote` 必须是材料中真实出现的句子；`check.py` 会把引文与重新抽取的材料文本做归一化子串比对，找不到就报错。
- 结构化关系若在材料中没有同时提到两端点的句子，则引 `case.json#relations[i]` 的原始 JSON 作为来源，状态降为 `inferred`。
- 同名实体合并别名；同名但类型/区室冲突写入 `conflicts`；无边实体写入 `isolated_entities`；都同时进入 `uncertainty`。

**符号清单与硬门**：`extract.py` 会扫描每句话中的符号型 token（全大写 `EGFR/PI3K/PTEN/AKT/EGF/BAX`、含数字 `FOXO3/PI3K/p53`、混合大小写 `mTOR`、希腊字母 `HIF-1α`），不要求该 token 出现在关系句里；没有关系的符号仍是实体（`status=stated`），并进入 `isolated_entities` 或 `unresolved_edges`。普通首字母大写散文词（Lab/The/Entity/Type）会被过滤，避免把标题或表头当实体。抽取结果写入 `token_inventory` 与 `token_recall`。

`check.py` 的硬门（任一失败 → 自检 FAIL → `status=blocked`，不出图）：
1. `token_recall < 80%`（符号清单中未落到实体的比例过高）；
2. `missing_relations` 非空（已识别的陈述关系没有画出来）；
3. 任一边的端点在实体表中不存在（`edge_endpoint_errors`）。

## 6. 编辑模式（已有 SVG）

材料中出现 `.svg`，或 `task.md` 含 编辑/修改/标注/高亮/rename/change 等词时自动进入编辑：

```bash
python3 /skills/weekly-skill/scripts/edit.py   # 由 run_case.py 自动调用
```

支持 `case.json` 的 `edits`（优先级最高）或从任务文本解析：
`{"op":"rename","old":"AKT","new":"AKT2"}`、`{"op":"highlight","target":"FOXO3"}`、`{"op":"set_title","value":"..."}`、`{"op":"add_note","text":"..."}`。

编辑是**就地改文本节点 + 追加注释层**，不重建图形；输出 `edit_log.json` 含
`before_sha256 / after_sha256 / changes[] / removed_elements / changed_text_elements / structure_preserved`。未触及元素保持原字节；`removed_elements=0` 即结构保持。

## 7. 自动抽取失败时：人工/视觉补录（重要）

如果材料是扫描图、纯图片 PDF，或自动抽取返回 `blocked`，**不要放弃**。用看图工具阅读材料，然后按 `references/pathway-spec-schema.md` 手写 `work/spec.manual.json`，再运行：

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --case /input/case.json --materials /input \
  --out /app/output --work /app/work \
  --spec /app/work/spec.manual.json --trust-evidence
```

`--trust-evidence` 表示引文来自人工读图/读 PDF，关闭机器引文比对；仍强制要求每条实体/边有 `file + locator + quote`，且 `verified` 会被标为 false、写入 `limits`。这是有意的降级：**可读图，但不假装机器已核验**。

## 8. 分步回退（一键失败时）

```bash
export MECH_WORK=/app/work MECH_OUT=/app/output
python3 scripts/kernel.py init --case /input/case.json --materials /input --work $MECH_WORK
python3 scripts/extract.py
python3 scripts/layout.py
python3 scripts/render.py
python3 scripts/export.py
python3 scripts/check.py
python3 scripts/emit_result.py --work $MECH_WORK --out $MECH_OUT
python3 scripts/kernel.py check --result $MECH_OUT/result.json --work $MECH_WORK
```

- 只改排版：编辑 `layout.json` 后重跑 `render.py → export.py → check.py → emit_result.py`。
- 只改语义：编辑 `spec.json`（或手动 spec）后重跑全链。
- 渲染器缺失：`export.py` 依次尝试 cairosvg → rsvg-convert → inkscape → matplotlib（按 `layout.json` 重画）；全部缺失时保留 SVG，`status=partial` 并在 `limits` 说明，绝不谎报 PNG/PDF。

## 9. 状态

| status | 条件 |
|---|---|
| `ok` | 自检 PASS、SVG/PNG/PDF 均存在、PNG 通过质量门；编辑模式还要求有实际改动且结构保持。 |
| `partial` | 有图但自检有 warning/导出不完整（如缺栅格器、标签截断、存在冲突/未解决关系）。 |
| `blocked` | 实体=0、关系=0，或硬门失败（符号召回<80%、陈述关系缺失、边端点不在实体表）；**不出图**，给出证据与原因。 |
| `failed` | 管线异常；仍写完整 `result.json` 与异常说明。 |

## 10. 已知限制

- 不联网、不查数据库；不推断膜拓扑、化学计量、动力学、时间顺序。
- 文本解析按标点与 `并/且/同时/后` 分句，支持主动句、`A 被 B 激活` 被动句、`A 结合 B 后激活 C` 与英文 `A is activated by B`；复杂嵌套从句仍可能漏检，漏检会进入 `missing_relations` 并硬门 blocked，而不是静默少画。
- 图片/扫描 PDF 不做 OCR；需要第 7 节人工读图。
- matplotlib 回退的字体覆盖可能不同于 cairo；SVG 与 `element_map` 才是权威。
- 所有推断项必须虚线 + `uncertainty`；若评审需要“只画有引文的”，把推断边从 `spec.json` 删除即可。

## 11. 文件

```
SKILL.md
scripts/run_case.py     一键编排（推荐入口）
scripts/kernel.py       契约归一化 / 案例与材料读取 / 最终契约校验
scripts/extract.py      结构化+文本抽取、别名合并、证据、冲突、孤立、未解决
scripts/graphlib.py     类型/区室/极性词表、文本度量、几何工具
scripts/layout.py       四区室带布局、换行、碰撞规避路由
scripts/render.py       SVG（真实 text）、图例、graph.json、element_map.json
scripts/export.py       PNG/PDF 多级回退 + PNG 质量门
scripts/check.py        图形/语义/证据/几何自检
scripts/edit.py         SVG 就地编辑 + 前后哈希 + 变更清单
scripts/emit_result.py  组装 result.json（契约全覆盖，无 fields 包装）
references/output-contract.md
references/pathway-spec-schema.md
references/quality-rubric.md
references/example.md
```

## 12. 改动记录

- 2.1.0（2026-11-22）：题面/工单文字不再并入证据语料（此前会把“EGFR/PI3K/AKT/mTOR”这类
  指令列表和“标明亚细胞”这类散文片段抽成伪实体，并因引文无法在材料中核验而误判自检 FAIL）；
  斜杠列表拆分为多个实体；补充指令式中文前缀过滤；契约字段精确映射（`missing_relations`、
  `edge_endpoint_errors` 不再被子串误映射成 `edges`），`token_inventory/token_recall/
  binding_annotations` 按文档输出。回归：8 实体/6 关系为 `status=ok`、`selfcheck=PASS`；
  空材料为 `status=blocked` 且不出图；SVG 就地改名保留嵌套 `tspan` 与结构；契约 11 字段
  `unmapped=0`。
- 2.0.0（2026-11-22）：实体类型/区室/边极性驱动不同箭头，逐条引文核验，编辑双哈希，
  契约归一，`blocked` 硬门。
