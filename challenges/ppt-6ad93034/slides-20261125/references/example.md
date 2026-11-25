# 示意输入/输出（示例，非正式案例答案）

论文、图表与数值均为**虚构合成**，只说明接口与字段，不是平台固定案例，也不是可提交的答案。

## 1. 生成模式

`/input/case.json`（示意）：

```json
{"case": "demo-gen-002", "audience": "课题组组会", "duration_min": 6, "max_slides": 8,
 "output_contract": {"artifact_path": "string", "slide_count": "int",
                     "diff": "array", "notes_path": "string"}}
```

`work/deck_spec.json`（依据材料写，节选）：

```json
{"case_id": "demo-gen-002", "audience": "课题组组会", "duration_min": 6, "max_slides": 8,
 "mainline": {"problem": "旧涂层三次循环后失效", "approach": "浸涂加 80 C 固化",
              "results": "厚度 12→31 um", "conclusion": "低温工艺可行"},
 "slides": [
  {"kind": "title", "title": "低温浸涂制备疏水涂层",
   "bullets": ["示例作者｜示例单位", "组会汇报 2026-11"], "seconds": 40,
   "notes": {"say": "六分钟只讲三件事：为什么换工艺、怎么做、两个关键结果。"}},
  {"kind": "result", "title": "三次循环把厚度提高到 31 微米",
   "bullets": ["12→31 微米", "每次约增厚 6 微米"], "seconds": 65,
   "visual": {"type": "figure", "ref": "Fig. 2a", "caption": "厚度随循环次数变化；n=3"},
   "evidence": [{"ref": "Fig. 2a",
                 "quote": "After three cycles the film thickness rose from 12 um to 31 um",
                 "locator": "Results"}],
   "notes": {"say": "先看纵轴单位，再看第三次循环后的平台段。"}}
 ]}
```

```bash
python3 scripts/deck_build.py generate --spec work/deck_spec.json \
    --out work --corpus work/corpus.txt
# generate: slides=2 errors=0 warnings=0 pptx=yes
```

## 2. 编辑模式

`work/edits.json`（示意）：

```json
{"edits": [
  {"slide": 2, "op": "set_title", "value": "三次循环增厚到 31 微米", "reason": "标题改成判断句"},
  {"slide": 2, "op": "replace_text", "find": "31 微米", "replace": "31 微米厚", "reason": "避免歧义"},
  {"slide": 2, "op": "insert_after",
   "value": {"kind": "result", "title": "接触角升到 96 度", "bullets": ["41→96 度"],
             "seconds": 55, "notes": {"say": "补充第二类证据，但仍只代表已测条件。"}},
   "reason": "评审要求补接触角证据"}
]}
```

```bash
python3 scripts/deck_build.py edit --base work/deck_spec.json \
    --edits work/edits.json --out work_edit --corpus work/corpus.txt
# edit: changes=3 failures=0 slides=3 errors=0 warnings=0
```

`work_edit/diff.md`（示意）：

```markdown
| 页 | 操作 | 字段 | 之前 | 之后 | 原因 |
|-|-|-|-|-|-|
| 2 | set_title | title | 三次循环把厚度提高到 31 微米 | 三次循环增厚到 31 微米 | 标题改成判断句 |
| 2 | replace_text | title | 三次循环把厚度提高到 31 微米 | 三次循环把厚度提高到 31 微米厚 | 避免歧义 |
| 2 | insert_after | * | — | 接触角升到 96 度 | 评审要求补接触角证据 |
```

## 3. 未应用（示意）

```json
{"edits": [{"slide": 99, "op": "set_title", "value": "无此页"}]}
```

```
edit: changes=0 failures=2 slides=5 errors=0 warnings=1
  ? 99 set_title 目标页不存在
```

`diff.md` 的“未应用”表会列出页号、操作与原因；`result.json.uncertainty` 同步记录，
`status=partial`。**不会**把越界编辑当成成功。
