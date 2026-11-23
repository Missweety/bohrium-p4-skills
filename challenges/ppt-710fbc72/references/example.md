# 示意输入/输出（示例，非正式案例答案）

模板、论文与数值均为**虚构合成**，只说明接口与字段，不是平台固定案例，也不是可提交答案。

## 1. 模板输入（`template.json`，也可换成 `.pptx`）

```json
{"name": "lab-16x9", "slide_size": {"w_in": 13.333, "h_in": 7.5},
 "theme": {"colors": {"dk1": "#1A1A1A", "lt1": "#FFFFFF", "accent1": "#0B5FFF"},
           "color_map": {"bg1": "lt1", "tx1": "dk1"},
           "fonts": {"major": {"ea": "Source Han Sans"}, "minor": {"ea": "Source Han Sans"}}},
 "layouts": [
  {"name": "Title Slide", "slots": {"title": {"placeholder": "ctrTitle", "font_pt": 40,
                                              "box": [1.0, 2.0, 11.3, 1.6]}}},
  {"name": "Title and Content", "slots": {
     "title": {"placeholder": "title", "font_pt": 30, "box": [0.8, 0.5, 11.7, 1.1]},
     "body": {"placeholder": "body", "font_pt": 20, "box": [0.8, 2.0, 11.7, 4.4]},
     "caption": {"placeholder": "caption", "font_pt": 12, "box": [0.8, 6.5, 11.7, 0.5]},
     "footer": {"placeholder": "ftr", "font_pt": 10, "box": [0.6, 7.0, 8.0, 0.3]}}}
 ]}
```

## 2. 探测

```bash
python3 scripts/template_fit.py probe --template /input/materials/template.json --out work
# probe: layouts=2 colors=3 warnings=0
```

`work/template_profile.md`（示意）：

```markdown
# 模板画像（template.json）

- 画布：13.33 × 7.50 in
- 颜色：dk1 #1A1A1A、lt1 #FFFFFF、accent1 #0B5FFF

## Title and Content

| 槽位 | 占位符 | 字号 | 位置 (in) |
|-|-|-|-|
| title | title | 30.0 | [0.8, 0.5, 11.7, 1.1] |
| body | body | 20.0 | [0.8, 2.0, 11.7, 4.4] |
| caption | caption | 12.0 | [0.8, 6.5, 11.7, 0.5] |
| footer | ftr | 10.0 | [0.6, 7.0, 8.0, 0.3] |
```

## 3. 适配

```bash
python3 scripts/template_fit.py fit --spec work/deck_spec.json \
    --profile work/template_profile.json --out work
# fit: slides=5 layouts=2 errors=0 warnings=0 pptx=yes
```

`work/compliance.md`（示意）：

```markdown
| 检查 | 级别 | 详情 |
|-|-|-|
| contrast | info | 正文/背景对比度 17.40 |

结论：PASS（硬错误 0，警告 0）
```

`work/slot_map.json`（节选）：

```json
{"template": "template_profile.json",
 "slot_map": [{"slide": 2, "kind": "problem", "layout": "Title and Content", "chars": 24,
               "slots": {"title": {"placeholder": "title", "font_pt": 30.0},
                         "body": {"placeholder": "body", "font_pt": 20.0},
                         "caption": {"placeholder": "caption", "font_pt": 12.0},
                         "footer": {"placeholder": "ftr", "font_pt": 10.0}}}]}
```

## 4. 不合规示例（示意）

把正文槽位改成 `14 pt`、背景改成 `#F2F2F2`：

```
fit: slides=5 layouts=2 errors=1 warnings=0 pptx=no
  ! 版式 Title and Content 的 body 字号 14 < 18 pt
```

`compliance.ok=false` 时 `status=partial`，`limits` 指向 `compliance.md`；
不会因为“模板要求”就删掉内容或压字号，而是提示换版式/拆页/调模板。

## 5. 无模板 / 模板损坏

```
probe: layouts=0 colors=0 warnings=2
  ~ 未解析到任何版式槽位
fit: ... template.source=default
```

此时使用内置 16:9 默认槽位（title 32 / body 20 / caption 12 / footer 10），
`uncertainty` 记录“模板解析失败，已降级为默认槽位”，产物仍可交付。
