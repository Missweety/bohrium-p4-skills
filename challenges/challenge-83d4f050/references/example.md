# 最小示例（synthetic，非正式案例）

以下全部为**合成示例**，仅用于说明接口与预期输出，不是平台固定案例，
也不能当作正式案例答案。

## 1. 输入

`/tmp/mech-demo/pathway.md`：

```text
EGFR activation promotes AKT phosphorylation in the cytoplasm.
AKT inhibits FOXO3 in the cytoplasm.
AKT affects ERK in a manner that was not specified in this synthetic note.
The membrane receptor EGFR receives the growth signal.
```

`/tmp/mech-demo/case.json`：

```json
{
  "case_id": "synthetic-a-4entities",
  "task": "Draw a biological mechanism diagram from the supplied pathway note.",
  "output_contract": {"required": ["figure_svg","figure_png","figure_pdf","caption",
    "element_map","nodes","edges","compartments","selfcheck","sources","limits",
    "uncertainty","change_log"]},
  "materials": ["pathway.md"],
  "entities": [
    {"id":"egfr","label":"EGFR","type":"receptor","compartment":"membrane","aliases":["ERBB1"]},
    {"id":"akt","label":"AKT","type":"protein","compartment":"cytoplasm","aliases":["PKB"]},
    {"id":"foxo3","label":"FOXO3","type":"gene","compartment":"cytoplasm"},
    {"id":"erk","label":"ERK","type":"protein","compartment":"cytoplasm","aliases":["MAPK1"]}
  ],
  "relations": [
    {"source":"EGFR","target":"AKT","kind":"activation"},
    {"source":"AKT","target":"FOXO3","kind":"inhibition"},
    {"source":"AKT","target":"ERK","kind":"affects"}
  ]
}
```

设计点：4 个实体、2 个有内容的区室（membrane / cytoplasm）、
1 条 activation、1 条 inhibition，外加 1 条 `affects`（词表外）→ 未解决关系。

## 2. 运行

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --case /tmp/mech-demo/case.json --materials /tmp/mech-demo \
  --out /tmp/mech-demo/out --work /tmp/mech-demo/work
```

本机验证（matplotlib 回退渲染）实际输出：

```text
run: nodes=4 edges=2 kinds=activation,inhibition selfcheck=PASS export=True
emit: status=ok contract=13 deliverables=6 element_rows=11
kernel: PASS
```

- `edges=2`：`affects` 不在词表，进入 `unresolved_edges`，**不画**。
- `status=ok`：自检 PASS、SVG/PNG/PDF 均存在且 PNG 过质量门。
- `element_rows=11`：4 实体 + 2 边 + 4 区室 + 1 图例。
- `export=True`：本机无 libcairo 时自动改走 matplotlib，仍产出 PNG/PDF。

产物：`figure.svg`、`figure.png`、`figure.pdf`、`result.json`、
`element_map.json`、`caption.md`、`selfcheck.json`。

## 3. 预期语义

| 元素 | 预期 |
|---|---|
| EGFR | `receptor`，`membrane` 带，圆角框 |
| AKT | `protein`，`cytoplasm` 带；别名 PKB 合并 |
| FOXO3 | `gene`，`cytoplasm` 带 |
| ERK | `protein`，`cytoplasm` 带；因唯一关系未解决而列入 `isolated_entities` |
| EGFR → AKT | activation，实心三角箭头 |
| AKT ⊣ FOXO3 | inhibition，T 形端 |
| AKT → ERK（affects） | 不绘制，`unresolved_edges` 说明 kind 不受支持 |

## 4. 看图检查

用支持看图的工具打开 `out/figure.png`，确认：

1. 四条区室带（细胞外 / 细胞膜 / 胞质 / 核内）都在；空带写明“未提取到实体”；
2. activation 是实心三角、inhibition 是 T 形端，二者肉眼可分；
3. 节点文字未被裁剪、无重叠；ERK 只有节点、没有边；
4. 底部图例列出边类型与实体类型，标题存在。

## 5. 负例（不出图）

把 `pathway.md` 换成一段没有任何实体/关系的普通说明，并去掉 `case.json` 的
`entities/relations`，运行同一命令应得到：

```text
status=blocked
blocked_reason=empty_mechanism: entities=0 relations=0
```

`out/` 中**不会**出现 `figure.svg/png/pdf`，只保留 `result.json`、`selfcheck.json`
与来源记录；`caption` 明确写“withheld rather than drawing an empty placeholder”。

## 6. 编辑示例

材料中放一个已有 `input.svg`，任务写“把 AKT 改名为 AKT2，并高亮 FOXO3”，
`run_case.py` 会切到编辑模式：

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --case /tmp/mech-edit/case.json --materials /tmp/mech-edit \
  --out /tmp/mech-edit/out --work /tmp/mech-edit/work
```

预期：`edit: changes=2 applied=2 structure_preserved=True`，
`edit_log.json` 含 `before_sha256 / after_sha256 / removed_elements=0`，
并导出新的 `figure.svg/png/pdf`。

## 7. 手动/视觉补录示例

扫描图或纯图片 PDF 自动抽取为 0 时，按 `pathway-spec-schema.md` 手写 spec：

```json
{"mode":"create","nodes":[{"label":"EGFR","type":"receptor","compartment":"membrane",
 "evidence":"Fig.1 shows EGFR at the plasma membrane."}],
 "edges":[]}
```

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --case /tmp/mech-scan/case.json --materials /tmp/mech-scan \
  --out /tmp/mech-scan/out --work /tmp/mech-scan/work \
  --spec /tmp/mech-scan/manual_spec.json --trust-evidence
```

注意：只有 1 个实体、0 条边 → 仍按边界规则 `blocked`。手动 spec 至少要有
2 个实体和 1 条合法边才会出图；`verified` 为 `false`，并在 `limits` 说明
“机器引文比对已关闭”。
