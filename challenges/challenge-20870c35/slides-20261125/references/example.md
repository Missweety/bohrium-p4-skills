# 示意输入/输出（示例，非正式案例答案）

以下研究、图表与数值均为**虚构合成**，只说明接口与字段，不代表任何真实论文；也不是平台固定案例。

## 1. 输入

`/input/case.json`（示意，字段名可换；脚本按别名容错）：

```json
{"case": "demo-org-001",
 "task": "把论文整理成 8 分钟组会汇报，最多 8 页，每页 6 行以内",
 "audience": "同组跨方向同学",
 "minutes": 8,
 "max_pages": 8,
 "output_contract": {"artifact_path": "string", "slide_count": "int",
                     "timing_table": "array", "speaker_notes_path": "string"}}
```

`/input/materials/paper.md`（示意片段）：

```
## Results
After three cycles the film thickness rose from 12 um to 31 um (Fig. 2a).
The contact angle increased from 41 deg to 96 deg (Table 1).
## Methods
Samples were dip-coated for 60 s and cured at 80 C for 10 min.
```

## 2. 页级规格 `work/deck_spec.json`（节选）

```json
{"case_id": "demo-org-001",
 "audience": "同组跨方向同学",
 "duration_min": 8,
 "max_slides": 8,
 "mainline": {"problem": "旧涂层三次循环后失效", "approach": "浸涂加 80 C 固化",
              "results": "厚度 12→31 um，接触角 41→96 度",
              "conclusion": "低温工艺可得到稳定疏水表面",
              "limitations": "只测三次循环，未做磨损"},
 "slides": [
  {"index": 1, "kind": "title", "title": "低温浸涂制备疏水涂层",
   "bullets": ["示例作者｜示例单位", "组会汇报 2026-11"], "seconds": 40,
   "visual": {"type": "none"}, "evidence": [],
   "notes": {"say": "八分钟只讲三件事：为什么做、怎么做、关键两个数。", "why": "先定边界"}},
  {"index": 2, "kind": "result", "title": "三次循环把厚度提高到 31 um",
   "takeaway": "增厚可重复", "bullets": ["12 微米到 31 微米", "每次约增厚 6 微米"],
   "seconds": 55,
   "visual": {"type": "figure", "ref": "Fig. 2a", "caption": "厚度随循环次数变化；n=3"},
   "evidence": [{"ref": "Fig. 2a",
                 "quote": "After three cycles the film thickness rose from 12 um to 31 um",
                 "locator": "Results"}],
   "notes": {"say": "先看纵轴单位，再看第三次循环后的平台段。",
             "why": "上一页说旧涂层失效，这里给出本次的稳定性证据"}},
  {"index": 3, "kind": "conclusion", "title": "低温工艺在三次循环内可行",
   "takeaway": "耐久性仍未验证", "bullets": ["80 度固化即可疏水", "磨损未测"],
   "seconds": 50, "visual": {"type": "none"},
   "evidence": [{"ref": "Table 1", "quote": "The contact angle increased from 41 deg to 96 deg",
                 "locator": "Results"}],
   "notes": {"say": "结论只覆盖已测条件，别外推到长期使用。", "why": "收束回开场的失效问题"}}
 ]}
```

## 3. 校验（示意）

```bash
python3 scripts/deck_plan.py plan --spec work/deck_spec.json \
    --corpus work/corpus.txt --out work
# plan: slides=3 total=02:25 errors=0 warnings=1
# 警告：主讲页 3 少于 5：按 60 秒/页上限会讲不满 08:00
```

## 4. 产出（示意，节选）

`work/speaker_notes.md`：

```markdown
## 第 2 页｜三次循环把厚度提高到 31 um（55 秒，累计 01:35）

- 页型：result｜段落：结果与证据
- 本页主张：增厚可重复
- 口播（55 秒）：先看纵轴单位，再看第三次循环后的平台段。
- 过渡：上一页说旧涂层失效，这里给出本次的稳定性证据
```

`result.json`（由 `kernel.py emit` 生成，节选）：

```json
{"case_id": "demo-org-001", "status": "partial",
 "artifact_path": "deck.md", "artifact_format": "marp-md",
 "slide_count": 3, "duration_min": 8,
 "timing_table": [{"index": 1, "segment": "开场", "seconds": 40, "cumulative_mmss": "00:40"}],
 "speaker_notes_path": "speaker_notes.md",
 "limits": "本环境未产出 pptx；已交付幻灯片规格 JSON、Marp 源与逐页讲稿",
 "uncertainty": ["未生成 pptx：python-pptx unavailable"]}
```

注意：示例总时长 145 秒小于目标 480 秒，校验会报“讲不满”的警告——这正是本包要提前暴露的问题，
应补页或加长讲稿，而不是把警告藏起来。
