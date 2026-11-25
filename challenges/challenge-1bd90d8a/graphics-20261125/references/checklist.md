# 自检项与失败修法

`check_figure.py` 输出 `selfcheck.json`：

```json
{"verdict": "PASS|FAIL", "errors": ["..."], "warnings": ["..."],
 "checks": [{"id": "...", "ok": true, "detail": "..."}], "stats": {...}}
```

退出码 0 仅当 `verdict=PASS`。任何 FAIL 都必须先修图或降级 `status`，不能删除检查。

## 检查码

### spec 与坐标轴

| 检查 | 通过条件 | 常见失败原因 |
|-|-|-|
| `spec.version` | `spec_version=1.1` | 手工改过 spec 或用了旧模板 |
| `spec.chart_types` | 每个面板类型在白名单内 | 拼写错误（`groupedbar`） |
| `spec.panels` / `spec.panel_ids` | 面板非空、id 唯一且与 `A/B/...` 对齐 | 多面板 id 重复 |
| `spec.source` | `source.file/sha256/rows` 与规范化快照一致 | 换了数据文件却没重建 spec |
| `spec.title` | 非空，且与图上标题逐字一致 | 只改了 spec 没重渲染，或相反 |
| `axes.valid` | `min<max`、刻度递增且在范围内、柱状图含 0 | 手工写死范围；柱状图被截断且未标 `pinned` |
| `labels.rendered` | 轴标签/类别/图例/标题都能在 SVG 文本中找到 | 标签被省略、旋转后丢失、字体替换 |
| `labels.cjk_not_tofu` | 中文保留为 `<text>` | 后端把中文转成路径/方框 |
| `font.cjk` | 记录实际字体名，或明确 warning | 环境无 CJK 字体 |

### 数据与证据链

| 检查 | 通过条件 | 常见失败原因 |
|-|-|-|
| `element_map.present` | 非空，含 `elements`、`counts`、`sha256` | map 阶段未运行 |
| `element_map.complete` | 期望的元素 id 与实际完全一致（无缺无多） | spec 改了但 map 没重跑；渲染器多画了元素 |
| `element_map.unique_ids` | id 不重复 | 同名高亮/注记被追加两次 |
| `element_map.rows_in_source` | 数据元素的行号在 `[2, rows+1]`，列号 `< columns` | 行号用了 0 基或超出源表 |
| `element_map.traceable_fields` | 数据元素有 `field`/`column` | 手工拼元素 |
| `values.recomputed` | 每个柱/点/箱/格可由 `normalized.csv` 复算且一致（容差 1e-6） | 汇总口径错、用了未声明的合并、改了数值 |
| `missing.declared` / `missing.rows_bounded` | 缺失有 policy，行号合法 | 静默丢行 |
| `outliers.declared` | 声明方法与数量（可为 0） | 声明缺失或方法不明 |
| `significance.source_only` | 没有源证据就不出现显著性标记 | 自动加了 `*` / p 值 |

### 图注

| 检查 | 通过条件 | 常见失败原因 |
|-|-|-|
| `caption.present` | 非空 | 把文件名当图注 |
| `caption.complete` | 含图型、变量与单位、误差线口径、样本量、缺失/异常值、源文件与哈希、element_map、显著性说明 | 模板漏项；`n<3` 说明缺失 |

### 渲染

| 检查 | 通过条件 | 常见失败原因 |
|-|-|-|
| `render.png_nontrivial` | ≥ 600×400 且 ≥ 5000 字节 | 空白画布、dpi 过低、只画了坐标轴 |
| `render.pdf_valid` | 文件以 `%PDF` 开头且非空 | 伪 PDF、写了一半 |
| `render.svg` / `svg.text_nodes` | SVG 非空且文本节点 ≥ 类别数 | 文字被转成路径 |
| `render.svg_width` | SVG 宽度与 `style.width_in×dpi` 量级一致 | 视口被写死 |
| `render.raster_partial` | 无 matplotlib 时仅为 warning | 把它当 FAIL 会误判降级路径 |

### 编辑

| 检查 | 通过条件 | 常见失败原因 |
|-|-|-|
| `edit.log` | 有改图指令时存在 `edit_log.json` | 没跑 `edit_figure.py` |
| `edit.mode` | `spec` 或 `svg` | 手工写日志 |
| `edit.changes` | 至少一条 change 或一条 warning | 指令未命中且未记录 |
| `edit.before_hash` / `edit.after_hash` | 与 `chart_spec.original.json` / `chart_spec.json` 哈希一致 | 编辑后又手改了 spec |
| `edit.structure_preserved` | 文本类编辑要求数据值未动；结构性编辑（改图型/轴范围）必须声明 `structural_fields_touched`，数值再由 `values.recomputed` 复核 | 改了数值却声称结构保留 |

## 负向测试（应 FAIL 的例子）

```bash
# 把 y 轴上限压到低于最大值，应触发 axes.valid 或 values.recomputed
python3 scripts/edit_figure.py spec --spec /app/output/chart_spec.json \
  --out /tmp/neg --y-max 10
python3 scripts/check_figure.py --spec /tmp/neg/chart_spec.json \
  --work /app/work --out /tmp/neg
echo $?   # 1
```

```bash
# 删除 element_map 后自检应 FAIL（element_map.present）
rm /tmp/neg/element_map.json
python3 scripts/check_figure.py --spec /tmp/neg/chart_spec.json \
  --work /app/work --out /tmp/neg
echo $?   # 1
```

## 修法原则

1. 先看 `errors[0]`，它是最具体的失败；`warnings` 不阻断 PASS，但要写进 `limits`。
2. 数值不符：回到 `plan_figures.py`/`build_spec.py` 重算，不手改 spec 数值。
3. 元素缺失/多余：重跑 `map_elements.py` 后再渲染，保持 spec→map→render 顺序。
4. 标签丢失：检查字体与标签旋转；必要时减少刻度密度，但保留全部类别文本。
5. 实在无法核验：`status=partial`，把原因写入 `uncertainty`，保留检查结果。
