# 合成示例（example）

> 下面的论文、作者、数值均为**合成示例**，用于演示规格写法，不是任何真实研究。
> 目标是"看一遍就能仿写"，因此只展示关键片段，不追求 10 页全文。

## 1. 输入片段：`/input/materials/paper.md`

```markdown
# 低温循环浸涂构建稳定疏水涂层

作者：示例作者甲，示例作者乙（合成示例，非真实研究）

## 摘要

低温浸涂是低成本制备疏水涂层的可行路线，但现有工艺在多次循环后易开裂。本文提出前驱体 A
浸涂结合 80 C 固化的三步循环工艺……三次循环后膜厚由 12 um 增至 31 um，水接触角由 41° 升至 96°。

## 1 引言

户外玻璃与光学窗口需要疏水涂层以抑制雾化与污染。高温烧结可获得致密薄膜，但不适用于塑料基底。
现有低温方法在第三次循环后出现微裂纹，良率下降。

## 2 方法

将清洗后的玻璃基底浸入前驱体 A 中 60 s，以 2 mm/s 提拉，随后在 80 C 固化 10 min，记为一次循环。
膜厚用台阶仪测量，接触角用座滴法测量，每个样品测 5 点取平均（n=3 批次）。

## 3 结果

三次循环后膜厚由 12 um 增至 31 um（Fig. 2a），每次循环约增厚 6 um。
水接触角由 41° 升至 96°（Table 1）。经 10 次线性磨损后，接触角仍为 92°（Fig. 2b）。

## 5 结论

本文证明低温循环浸涂可在三次循环内制备疏水涂层，膜厚与接触角均可重复。

## 局限

本研究仅测试三次循环与 10 次磨损，未开展户外暴露与化学腐蚀实验；样本批次为 3。

图 1 三步循环浸涂工艺流程示意（示意图，非实验数据）。
Fig. 2a 膜厚随循环次数的变化；n=3，误差线为 SD。
Fig. 2b 10 次磨损后的接触角；n=3。
Table 1 不同循环次数下的水接触角（n=3，±SD）。
```

这篇输入含 **2 张图**（Fig. 1 流程示意、Fig. 2a/2b 膜厚与耐磨）与 **1 张表**（Table 1 接触角）。

## 2. 抽取结果：`work/paper.json`（节选）

```json
{
  "title": {"status": "ok", "value": "低温循环浸涂构建稳定疏水涂层",
            "locator": {"page": null, "line": 1}},
  "authors": {"status": "ok", "value": "示例作者甲，示例作者乙（合成示例，非真实研究）",
              "locator": {"page": null, "line": 3}},
  "abstract": {"status": "ok", "value": "低温浸涂是低成本……长期稳定性尚需验证。"},
  "figures": [
    {"ref": "图 1", "caption": "三步循环浸涂工艺流程示意（示意图，非实验数据）"},
    {"ref": "Fig. 2a", "caption": "膜厚随循环次数的变化；n=3，误差线为 SD"},
    {"ref": "Fig. 2b", "caption": "10 次磨损后的接触角；n=3"}
  ],
  "tables": [{"ref": "Table 1", "caption": "不同循环次数下的水接触角（n=3，±SD）"}],
  "conclusion": {"status": "ok", "value": "本文证明低温循环浸涂可在三次循环内制备疏水涂层……"},
  "missing": []
}
```

字段抽取失败时的形态（**不许补造**）：

```json
{
  "authors": {"status": "missing", "value": null,
              "reason": "作者行未识别（可能为扫描版或无作者信息）"},
  "missing": ["authors"]
}
```

此时封面只写标题与单位，`result.json.uncertainty` 加一句"作者未解析，需人工确认"。

## 3. 页级骨架（10 页 / 570 秒 / 目标 600 秒）

| # | kind | 标题 | 要点 | 秒 |
|-|-|-|-|-|
| 1 | title | 低温循环浸涂构建疏水涂层 | 2 | 30 |
| 2 | problem | 户外玻璃需要疏水涂层 | 3 | 60 |
| 3 | gap | 现有低温工艺第三次循环开裂 | 3 | 60 |
| 4 | method | 前驱体A浸涂加低温固化 | 3 | 60 |
| 5 | method | 线性增厚依赖稳定吸附 | 3 | 60 |
| 6 | result | 三次循环膜厚增至31 um | 2 | 60 |
| 7 | result | 接触角升至96度转为疏水 | 2 | 60 |
| 8 | result | 十次磨损后仍保持92度 | 2 | 60 |
| 9 | limitation | 结论仅覆盖三次循环条件 | 3 | 60 |
| 10 | conclusion | 低温工艺在三次循环内可行 | 3 | 60 |

合计 570 秒，与 600 秒目标差 30 秒（容差 60 秒），主讲页 10 页在 10–14 窗口内。

## 4. 一页完整规格（第 6 页）

```json
{
  "kind": "result",
  "title": "三次循环膜厚增至31 um",
  "takeaway": "厚度增长接近线性",
  "bullets": ["由 12 um 增至 31 um", "每次循环增厚约 6 um"],
  "visual": {"type": "figure", "ref": "Fig. 2a",
             "caption": "膜厚随循环次数变化；n=3，误差线为 SD"},
  "evidence": [{"ref": "Fig. 2a",
                "quote": "三次循环后膜厚由 12 um 增至 31 um",
                "locator": "L31"}],
  "source_pages": "L31",
  "seconds": 60,
  "notes": {
    "say": "第一个结果看膜厚。三次循环把厚度从十二微米推到三十一微米，平均下来每次循环加六微米左右，增长接近线性。这里提醒两点：纵轴单位是微米，不要读成纳米；误差线是三个批次的标准差，说明增厚过程在批间是稳的。",
    "why": "先读轴和单位，再给数字与解释"
  }
}
```

要点 2 条、每条 ≤14 字、页面 41 字；口播 124 字，60 秒可讲完。
图注带 `n=3` 与误差线含义；`quote` 与原文逐字一致（空白归一后比对）。

## 5. 运行命令与真实结果

```bash
python3 scripts/kernel.py init --case /input/case.json --out work
python3 scripts/kernel.py index --materials work/materials --out work
python3 scripts/paper_parse.py --paper work/materials/paper.md --out work
python3 scripts/deck_plan.py plan --spec work/deck_spec.json --case /input/case.json \
    --paper work/paper.json --corpus work/corpus.txt --out work
```

实际输出（本仓库 SMOKE 同款案例）：

```text
paper: title=ok authors=ok abstract=ok figures=3 tables=1 conclusion=ok pages=-
plan: slides=10 total=09:30 errors=0 warnings=0 pptx=yes selfcheck=PASS
```

反面样例（把图号改成不存在的 `Fig. 5`，并在要点里加 `累计 77 um`）：

```text
check: errors=2 warnings=1
  ! 第 6 页 图号 Fig. 5 在原文找不到
  ! 第 7 页 数字 77 在原文找不到
```

## 6. `selfcheck.json`（节选）

```json
{
  "verdict": "PASS",
  "summary": {"pages": 10, "content_pages": 10, "total_seconds": 570,
              "duration_seconds": 600, "errors": 0, "warnings": 0},
  "checks": [
    {"id": "slides.window", "level": "error", "ok": true,
     "detail": "主讲页 10，窗口 10–14（含备份页共 10）"},
    {"id": "timing.total", "level": "error", "ok": true,
     "detail": "逐页合计 09:30，目标 10:00，偏差 30 秒（容差 60 秒）"},
    {"id": "contrast.body", "level": "error", "ok": true,
     "detail": "正文/背景对比度 17.40（阈值 4.5）"}
  ]
}
```

148 项检查全过时 `verdict=PASS`；任一 error 项失败即 `FAIL`，warning 只记录不翻结论。
