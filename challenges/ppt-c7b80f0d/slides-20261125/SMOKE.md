# SMOKE：论文转学术 PPT 全流程实测

实测日期 2026-11-19｜环境 macOS + Python 3.13.13｜python-pptx 1.0.2｜pypdf 6.16.2｜
pdftotext 26.07.0｜LibreOffice（soffice）可用。

> 案例为**合成论文**：一篇 38 行的 Markdown，含 2 张图（Fig. 1 流程示意、Fig. 2a/2b 膜厚与耐磨）
> 与 1 张表（Table 1 接触角），所有数值均为编造，仅用于验证流水线。
> 仓库根记为 `$REPO`（clone 后自行 export），脚本目录为
> `$REPO/tracks/slides/challenges/ppt-c7b80f0d/05_skills/submission`。

## 1. 准备合成案例

```bash
mkdir -p /tmp/paper_deck_smoke/input/materials
# paper.md：标题/作者/摘要/引言/方法/3 结果/讨论/结论/局限 + 4 条图注（2 图 1 表）
# case.json：duration_min=10, max_slides=14, audience=课题组组会,
#            output_contract 含 artifact_path/slide_count/deck_outline/evidence_map/render_log
cd /tmp/paper_deck_smoke
SUB="$REPO/tracks/slides/challenges/ppt-c7b80f0d/05_skills/submission"
```

## 2. 主流程（标准库即可跑）

```bash
python3 "$SUB/scripts/kernel.py" init --case input/case.json --out work
python3 "$SUB/scripts/kernel.py" index --materials input/materials --out work
python3 "$SUB/scripts/paper_parse.py" --paper input/materials/paper.md --out work
python3 "$SUB/scripts/deck_plan.py" plan --spec work/deck_spec.json --case input/case.json \
    --paper work/paper.json --corpus work/corpus.txt --out work
```

真实输出：

```text
ok            960  input/materials/paper.md
paper: title=ok authors=ok abstract=ok figures=3 tables=1 conclusion=ok pages=-
plan: slides=10 total=09:30 errors=0 warnings=0 pptx=yes selfcheck=PASS
```

- 主讲页 10，逐页合计 570 秒，目标 600 秒，偏差 30 秒（容差 60）。
- `paper.json`：`missing: []`；图表 3 图 + 1 表，图注分别命中"示意 / n=3 / SD"。
- `deck.md`：160 行；`speaker_notes.md`：10 个 `## 第 N 页` 小节 + 时间分配表。
- 导出：`deck.pptx` 54,547 字节；`deck.pdf` 10 页（LibreOffice 转换）。

## 3. 交付与自检

```bash
python3 "$SUB/scripts/kernel.py" emit --draft work/draft.json --contract-dir work --out output
python3 "$SUB/scripts/deck_plan.py" finalize --work work --out output
cp work/deck_spec.json work/deck.md work/speaker_notes.md work/timing.csv work/timing.md \
   work/paper.json work/selfcheck.json work/deck.pptx work/deck.pdf output/
python3 "$SUB/scripts/kernel.py" check --out output
python3 "$SUB/scripts/deck_plan.py" selfcheck --work output --paper output/paper.json \
    --corpus work/corpus.txt
```

真实输出：

```text
PASS
finalize: 13 fields merged
SELFCHECK PASS verdict=PASS errors=0 warnings=0
```

`output/selfcheck.json` 摘要：

```json
{"verdict": "PASS", "pass": true,
 "summary": {"pages": 10, "content_pages": 10, "total_seconds": 570,
             "duration_seconds": 600, "errors": 0, "warnings": 0}}
```

共 **148 项检查**，0 error / 0 warning；`result.json` 19 个键，
`status=ok`、`artifact_path=deck.pptx`、`slide_count=10`、`evidence_map` 9 条（封面页无引文）、
`timing_table` 10 行。

关键检查实测值：

| 检查 | 实测 |
|-|-|
| `slides.window` | 主讲页 10，窗口 10–14 |
| `timing.total` | 合计 09:30 / 目标 10:00，偏差 30 秒（容差 60） |
| `slide6.bullet_len` | 2 条要点，最长 11 字 |
| `slide6.page_chars` | 41 字（上限 180） |
| `slide6.caption` | 图注含 `n=3` 与误差线含义 |
| `contrast.body` | #1A1A1A on #FFFFFF = 17.40（阈值 4.5） |
| `headings.deck` | H1=10（页数 10）、H2=0、H3=0 |

## 4. 反例：机器必须拦住虚构

把第 6 页图号改成原文不存在的 `Fig. 5`，并在第 7 页加一条 `累计 77 um`：

```bash
python3 "$SUB/scripts/deck_plan.py" check --spec work/neg_spec.json \
    --paper work/paper.json --corpus work/corpus.txt --out work/neg
```

```text
check: errors=2 warnings=1
  ! 第 6 页 图号 Fig. 5 在原文找不到
  ! 第 7 页 数字 77 在原文找不到
exit=1
```

警告为"编号不在解析清单（以原文文本为准再核）：Fig. 5"。
退出码 1 说明校验能区分"看起来像图号"和"原文真的有这张图"。

## 5. PDF 输入（文本层 + 页码）

```bash
soffice --headless -env:UserInstallation=file:///tmp/lo-smoke-profile \
    --convert-to pdf --outdir input/materials input/materials/paper.md
python3 "$SUB/scripts/paper_parse.py" --paper input/materials/paper.pdf --out work/pdf
python3 "$SUB/scripts/kernel.py" index --materials pdf_case --out work/pdf
python3 "$SUB/scripts/deck_plan.py" check --spec work/deck_spec.json \
    --paper work/pdf/paper.json --corpus work/pdf/corpus.txt --out work/pdf_check
```

```text
paper: title=ok authors=ok abstract=ok figures=3 tables=1 conclusion=ok pages=2
check: errors=0 warnings=0
```

说明：PDF 走 `pdftotext -layout`，页数=2；`locator.page` 有值。Markdown 无页码，
`paper.json.page_count=null`，页面 `source_pages` 用行号 `L31`，对齐规则见
`references/slide-narrative.md` 第 3 节。

### DOCX（无图表时显式 missing）

```bash
python3 "$SUB/scripts/paper_parse.py" --paper input/materials/paper.docx --out work/docx
```

```text
paper: title=ok authors=ok abstract=ok figures=0 tables=0 conclusion=ok pages=-
  missing: figures, tables, limitations - 页面不得补造这些内容
```

DOCX 走 OOXML 文本抽取，无页码（`page_count=null`）。这篇只保留标题/作者/摘要/结论，
解析器如实报 `figures`、`tables`、`limitations` 缺失；对应页要么不排，要么用真实章节文字，
**不用"通常会有一张示意图"来补**。

## 6. 降级：无 pptx 依赖不崩

```bash
python3 "$SUB/scripts/deck_plan.py" plan --spec work/deck_spec.json --case input/case.json \
    --paper work/paper.json --corpus work/corpus.txt --out work/deg --no-pptx
```

```text
plan: slides=10 total=09:30 errors=0 warnings=0 pptx=no selfcheck=PASS
status partial｜limits: 按 --no-pptx 跳过 pptx；无放映/预览导出件；需在有 python-pptx/LibreOffice 的环境复跑
```

同一分支覆盖 `python-pptx` 缺失与 LibreOffice 缺失：`try_pptx` / `try_pdf` 返回
`{"built": false, "reason": ...}`，不抛异常；只交付 `deck_spec.json` + `deck.md` + 讲稿，
`status=partial` 并写 `limits`。

## 7. 提交包校验

脚本运行会在 `scripts/` 下生成 `__pycache__`，打包前清理（或全程加
`PYTHONDONTWRITEBYTECODE=1`）：

```bash
find "$SUB" -name __pycache__ -prune -exec rm -rf {} +
find "$SUB" -name .DS_Store -delete
python3 validators/validate_submission.py \
    --outputs tracks/slides/challenges/ppt-c7b80f0d/05_skills
```

实际输出：

```text
PASS
stats: {"files": 12, "total_bytes": 128266, "largest": 30620}
```

12 个文本文件、合计 125 KB、单文件最大 30 KB；无 symlink、无二进制、无 `/Users/` 路径、
无令牌，满足 ≤50 文件 / 单文件 ≤500 KB / 合计 ≤2 MB 的上限。

## 8. 结论

- 主流程：10 页 / 9:30 / 148 项检查 0 error 0 warning / pptx 54,547 B / pdf 10 页。
- 反例：虚构图号与数字各拦 1 条，退出码 1。
- PDF 与 Markdown 两种输入都能跑通；无 pptx 依赖时降级且 selfcheck 仍 PASS。
- 提交包 validator：PASS（12 files / 128,266 B）。

## v2.1.0 增量冒烟（2026-11-22，`/tmp/papertest`）

> 上文历史段落的路径为 `05_skills`；本版实测目录为 `05_skills_codex`，包大小以本节
> validator 结果为准（历史字节数不改写）。

合成论文 3 页规格，非正式案例；重点回归 `output_contract` 字段规格数组。

| 场景 | 实际 |
|-|-|
| 旧缺陷 | 契约 `[{name,type},...]` 时 `emit` 只写 `fields: null`，13 个契约字段全部丢失 |
| 修复后 | `contract_fields=15 missing_contract_fields=none`；artifact_path/slide_count/deck_outline/evidence_map/notes_path/render_log/self_check/timing_table 等均有值 |
| 契约包裹形态 | `{"output_contract":[...]}`、裸数组、`{"contract":{"fields":[...]}}` 均不崩，字段名正确提取 |
| 主流程 | `init → paper_parse → deck_plan plan → emit → finalize → check` 跑通；`deck.pptx` 3 页、`deck.pdf` 3 页 |
| 负向 | 旧规格第 3 页引文过短、讲稿过短 → `selfcheck FAIL errors=5 warnings=6`，退出码 1，未被静默放过 |
| 渲染目检 | `pdftoppm` 后查看：中文标题/正文正常；本次合成规格未给 footer，故无页脚，不作为缺陷 |
| 跨目录 | 在 `/tmp` 用绝对路径调用脚本正常；相对路径仅在 skill 根目录有效，已在 SKILL.md 写明 |

已知边界：官方 case 的真实契约字段名不可见；本测试用脚本实际产出的字段名验证“有值不丢字段”，
不用臆造字段名充当官方契约。视觉审美不做判断。

### 追加：图表真实嵌入（2026-11-22，`/tmp/visualtest`、`/tmp/visualtest_neg`）

合成 4 页规格，非正式案例；重点回归 `visual.path` / `visual.table` 是否真的进入 pptx。

| 场景 | 实际 |
|-|-|
| 归一层缺陷 | `normalize_spec` 旧实现只留 `type/ref/caption`，丢弃 `path`/`table`，插入逻辑拿不到素材；已保留 `path`（别名 `file`/`image`）与 `table` |
| 第 2 页表格 | `visual.type=table` + header/rows → 原生 TABLE（3 列 4 行，7.33/1.95/5.33/3.75 in），正文缩至 6.4 in，不重叠；图注在 y=6.45 |
| 第 3 页图片 | `visual.path=fig1.png`（800×450）→ 等比 PICTURE（7.33/2.33/5.33/3.0 in），右半区居中，图注可见；`pdftoppm` 目检无越界/遮挡 |
| 缺图负向 | `path=missing_fig.png` → 不插入图片，正文恢复全宽 9.0 in，`uncertainty` 记录“第 3 页图表未找到图像文件（Fig. 2a）…”，不臆造 |
| 契约与状态 | emit 15/15；finalize `status=ok contract_missing=[]`；缺图时 status 仍 ok（契约完整），缺失图表以 uncertainty 呈现 |
| JPG 解析（`/tmp/vt2`） | `visual.path=fig1.jpg`（800×450）→ 等比 PICTURE 5.33×3.0 in；修正了 JPEG SOF 高度/宽度字节偏移（原解析把精度字节当高度） |
| 图号整词匹配（`/tmp/fuzzmatch`） | `ref="Fig. 1"` 且 materials 只有 `fig10.png` → 不误插，写入 `uncertainty`“未找到图像文件”，不臆造 |
| 子图号匹配（`/tmp/panel`） | `ref="Fig. 2b"` + `fig2a.png`/`fig2b.png` → 选中 `fig2b`（5.33×3.0）；只留 `fig2a` → 不误插并写 `uncertainty`；仅有整图 `fig2.png` 时接受整图 |
| 不规则表格行（`/tmp/vt2`） | `rows=[[...], 42, {"0":"固化","1":"80 C","2":"L15"}]` → 不崩溃；标量行转字符串，dict 行按表头取值/按自身顺序补格 |
| 单页失败隔离 | 图表插入/图注写入异常只写 `uncertainty`，不丢整册（try/except 包住单页图表逻辑） |
| validator | PASS（12 files；字节数随文档更新变化，以最终 validator 为准） |
