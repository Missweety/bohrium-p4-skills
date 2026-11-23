# 最小可运行示例（合成数据，不是评测答案）

下面所有数据都是为验证工具行为而临时编造的，**不是任何提交案例的答案**，
也不包含平台反馈或历史分数。示例展示：输入 → 命令 → 真实产物 → 如何逐项核验。

## 1. 合成输入

`example/data.csv`（23 行数据 + 表头；`length_mm` 有 1 个空值）：

```csv
treatment,body_weight_g,length_mm,sex
Control,22.1,41.2,M
Control,21.6,40.8,F
Control,22.4,,M
Control,20.9,39.9,F
Control,21.8,41.0,M
Control,22.0,40.5,F
Control,21.4,40.1,M
LowDose,23.4,42.0,M
...
HighDose,26.5,44.6,F
```

`example/case.json`：

```json
{
 "case_id": "example-bar",
 "task": "科研数据图表：请生成 treatment 与 body_weight_g 的柱状图，误差线使用 SD。",
 "title": "Body weight by treatment (SD)",
 "materials": ["data.csv"],
 "output_contract": {
  "required": ["figure_svg", "figure_png", "figure_pdf", "caption", "element_map",
               "data_profile", "selfcheck", "sources", "limits", "uncertainty",
               "change_log", "deliverables"]
 }
}
```

## 2. 运行

```bash
python3 scripts/run_case.py \
  --case example/case.json --materials example \
  --work /tmp/example_work --out /tmp/example_out
```

## 3. 真实结果（本地 Python 3.13 + matplotlib 3.10，Agg）

- `status=ok`，`selfcheck.verdict=PASS`，`unmapped_contract_fields=[]`。
- `figure.png`：1620×1110 px（300 dpi），58,637 字节，非空白。
- `figure.svg`：含真实 `<text>` 文本节点（标题、刻度、类别），可继续编辑。
- `figure.pdf`：以 `%PDF` 开头，可由阅读器打开。
- 面板 A：`bar`，x=`treatment`，y=`body_weight (g)`，误差线 `SD`。
- 复算值（脚本从源表计算，不是预置）：

| 组 | n | 均值 | SD | 源行号（表头=1） |
|-|-|-|-|-|
| Control | 7 | 21.742857 | 0.496176 | 2–8 |
| LowDose | 8 | 23.6375 | 0.373927 | 9–16 |
| HighDose | 8 | 26.4875 | 0.290012 | 17–24 |

- `element_map.json`：`counts={"total":7,"data":3}`；`bar:0|Control` 的
  `value=21.742857`、`error=0.496176`、`error_type=SD`、`n=7`、`source_rows=[2..8]`。
- `caption.md` 摘要：图型、x/y 与单位、误差线口径、每组 n、源文件 sha256 前缀、
  7 个图元/3 个数据图元、显著性与数据清洗声明。

## 4. 逐项核验

```bash
# 契约字段齐全
python3 - <<'PY'
import json
r = json.load(open('/tmp/example_out/result.json'))
need = ["figure_svg","figure_png","figure_pdf","caption","element_map",
        "data_profile","selfcheck","sources","limits","uncertainty",
        "change_log","deliverables"]
print("missing:", [k for k in need if k not in r])
print("status:", r["status"], "selfcheck:", r["selfcheck"]["verdict"])
PY
```

```bash
# 图元能回溯到真实行，并能复算
python3 - <<'PY'
import csv, json, statistics
em = json.load(open('/tmp/example_out/element_map.json'))
rows = list(csv.reader(open('/tmp/example_work/normalized.csv', newline='')))
head, body = rows[0], rows[1:]
yi = head.index("body_weight_g")
for e in em["elements"]:
    if e["kind"] != "bar":
        continue
    vals = [float(body[r-2][yi]) for r in e["source_rows"]
            if body[r-2][yi].strip()]
    print(e["label"], e["n"], e["value"], round(statistics.mean(vals), 6),
          round(statistics.stdev(vals), 6))
PY
```

```bash
# 机检与降级路径
python3 scripts/check_figure.py --spec /tmp/example_out/chart_spec.json \
  --work /tmp/example_work --out /tmp/example_out
echo $?    # 0

python3 scripts/svg_render.py --spec /tmp/example_out/chart_spec.json \
  --out /tmp/example_svg
head -c 120 /tmp/example_svg/figure.svg   # <svg ...>，含 <text>
```

## 5. 改图示例

```bash
python3 scripts/edit_figure.py spec --spec /tmp/example_out/chart_spec.json \
  --out /tmp/example_edit --title "Body weight (reviewed)" --y-max 30 \
  --annotate "revised after review" --highlight HighDose
python3 scripts/map_elements.py --spec /tmp/example_edit/chart_spec.json --out /tmp/example_edit
python3 scripts/render_figure.py --spec /tmp/example_edit/chart_spec.json --out /tmp/example_edit
python3 scripts/check_figure.py --spec /tmp/example_edit/chart_spec.json \
  --work /tmp/example_work --out /tmp/example_edit
```

`edit_log.json` 记录每条 `path/before/after`、`spec_sha256_before/after` 与
`structure_preserved=true`；`element_map` 中新增 `annotation:edit:*` 与
`highlight:HighDose`，原有柱的 `source_rows` 不变。

## 6. 不应期待的结果

- 不会生成显著性星号或 p 值（源表没有）。
- 不会填补 `length_mm` 的空值，也不会把它算进 `body_weight_g` 的 `n`。
- 无 matplotlib 时不会伪造 PNG/PDF；会输出 SVG 并置 `status=partial`。
