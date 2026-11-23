# 交付契约（deck-contract）

本文件定义 `deck_spec.json`（输入规格 + 机检对象）与 `result.json`（对外交付）的字段。
`references/output-contract.md` 是兼容入口；两处冲突时以本文件为准。

## 1. 文件清单

| 文件 | 必需 | 说明 |
|-|-|-|
| `deck_spec.json` | 是 | 页级规格，`deck_plan.py` 的唯一输入 |
| `deck.md` | 是 | Marp 源；一页一个 `#` 标题，讲稿在 HTML 注释 |
| `speaker_notes.md` | 是 | 逐页口播 + 过渡 + 预设问答 + 时间分配表 |
| `timing.csv` / `timing.md` | 是 | 逐页秒数、累计、分段汇总 |
| `selfcheck.json` | 是 | `verdict: PASS/FAIL`，逐项检查与阈值 |
| `paper.json` | 是 | 抽取字段与 `missing`，页面内容的唯一事实源 |
| `deck.pptx` | 可选 | 有 python-pptx 时生成 |
| `deck.pdf` | 可选 | 有 LibreOffice 时由 pptx 转换 |
| `result.json` | 是 | 契约字段回填 + 技能附加字段 |

## 2. `deck_spec.json` 顶层

```json
{
  "case_id": "string",
  "audience": "string",
  "language": "zh|en",
  "duration_min": 10,
  "min_slides": 10,
  "max_slides": 14,
  "theme": {"bg": "#FFFFFF", "fg": "#1A1A1A", "accent": "#0B5FFF"},
  "mainline": {
    "problem": {"text": "...", "locator": "p.1"},
    "gap": {"text": "...", "locator": "p.1"},
    "approach": {"text": "...", "locator": "p.2"},
    "results": [{"text": "...", "locator": "Fig. 2a p.3"}],
    "conclusion": {"text": "...", "locator": "p.4"},
    "limitations": {"text": "...", "locator": "p.4"}
  },
  "slides": []
}
```

| 字段 | 类型 | 规则 | 缺省/降级 |
|-|-|-|-|
| `case_id` | string | 与题面一致 | 缺失时 `unknown`，并进 `uncertainty` |
| `duration_min` | number | 题面时长；0 表示未声明 | 未声明则只按逐页秒数反推 |
| `min_slides` / `max_slides` | int | 主讲页窗口，默认 10/14 | 题面更小上限时取更小值 |
| `theme.bg/fg/accent` | hex | 用于 Marp 与对比度检查 | 缺省白底 `#FFFFFF`/`#1A1A1A`/`#0B5FFF` |
| `mainline` | object | 六槽；`results` 3–5 条 | 缺 `problem/approach/conclusion` 判 error |

`mainline` 每槽只接受 `{text, locator}` 或字符串；字符串会自动补空 `locator`。

## 3. `slides[]` 页级字段

| 字段 | 类型 | 规则 |
|-|-|-|
| `index` | int | 由顺序生成，从 1 开始 |
| `kind` | enum | `title`/`problem`/`gap`/`method`/`result`/`limitation`/`conclusion`/`backup` |
| `title` | string | 判断句，非空，≤24 非空白字符；全文不重复 |
| `takeaway` | string | 一句话，与 `title` 不同措辞；可空 |
| `bullets` | string[] | ≤6 条，每条 ≤14 非空白字符；建议"名词短语 + 动作/数字" |
| `visual.type` | enum | `figure`/`table`/`schematic`/`photo`/`none` |
| `visual.ref` | string | `figure`/`table` 必填论文原编号（`Fig. 2a`、`Table 1`、`图 2`）；`schematic` 可空 |
| `visual.caption` | string | `figure`/`table` 必填，含条件/n/误差线含义；`schematic` 必须含"示意" |
| `evidence[]` | object[] | 非 title/backup 页 ≥1 条；每条 `ref` + `quote` + `locator` |
| `evidence[].quote` | string | 原文逐字，归一空白后必须命中 `corpus.txt`，长度 ≥12 字符 |
| `source_pages` | string | 非 title/backup 页必填；`p.3`/`pp.3-4`/`L41`，不得超出论文页数 |
| `seconds` | int | 30–60；`Σseconds ≈ duration_min × 60`（±max(30s,10%)） |
| `notes.say` | string | 30–60 秒口播，≥60 字；不得复述要点 |
| `notes.why` | string | 过渡句；可空 |
| `notes.qa` | object[] | `{q, a}`；建议 1–2 组 |

### 3.1 页型与预算

| 页型 | 页数配额 | 用途 |
|-|-|-|
| `title` | 1 | 题目、作者、单位、时长 |
| `problem` | 1–2 | 不解决会怎样 |
| `gap` | 1 | 前人边界，本研究的缺口 |
| `method` | 2–3 | 做法、关键设计、测量与样本量 |
| `result` | 3–5 | 一条结果一页，带原编号图表 |
| `limitation` | 1 | 作者自述边界 + 外推风险 |
| `conclusion` | 1 | 回到开场问题，给有条件答案 |
| `backup` | 任意 | 附录，不计入主讲页数 |

### 3.2 图表规则

- `ref` 必须能在 `corpus.txt` 命中；论文有 `paper.json.figures/tables` 清单时还要在清单中。
- 组合图写 panel（`Fig. 2b`）；跨页引用要在图注重述条件。
- 示意图：`type: "schematic"`，图注含"示意"，不与实测值同页比较。
- 图注至少包含：处理/条件、`n`、误差线或统计含义；原文未标注就写"原文未标注"。
- 数值、单位、百分比基数原样保留；页面出现的数字必须能在原文找到。

## 4. `paper.json` 字段

```json
{
  "source": "materials/paper.pdf",
  "format": "pdf",
  "page_count": 6,
  "title": {"status": "ok", "value": "...", "locator": {"page": 1, "line": 1}},
  "authors": {"status": "missing", "value": null, "reason": "作者行未识别"},
  "abstract": {"status": "ok", "value": "..."},
  "sections": [{"name": "Results", "locator": {"page": 3, "line": 41}}],
  "figures": [{"ref": "Fig. 2a", "caption": "...", "locator": {"page": 3, "line": 45}}],
  "tables": [{"ref": "Table 1", "caption": "...", "locator": {"page": 3, "line": 52}}],
  "conclusion": {"status": "ok", "value": "..."},
  "limitations": {"status": "missing", "value": null, "reason": "..."},
  "missing": ["authors", "limitations"]
}
```

规则：
- `status` 只有 `ok` / `missing` / `blocked`；`missing` 必须有 `reason`，页面不得补造。
- `page_count` 仅 PDF 有；docx/md/txt 为 `null`，`locator.page` 也为 `null`，只给 `line`。
- `missing` 数组同时写进 `result.json.uncertainty`（由 `deck_plan.py` 的 draft 传递）。
- 图表 `caption` 只取原文图注/表注；行内引用（"……（Fig. 2a），……"）不给 caption，
  避免把正文当图注。

## 5. `selfcheck.json`

```json
{
  "verdict": "PASS",
  "pass": true,
  "summary": {"pages": 10, "content_pages": 10, "total_seconds": 570,
              "duration_seconds": 600, "errors": 0, "warnings": 0},
  "checks": [{"id": "slides.window", "level": "error", "ok": true, "detail": "..."}],
  "errors": [],
  "warnings": []
}
```

- `verdict` 只由 error 级检查决定；warning 记录但不翻 FAIL。
- 每条 check 必须带 `id`、`level`、`ok`、`detail`（含实际值与阈值）。
- 交付目录的 `selfcheck.json` 由 `deck_plan.py selfcheck` 重跑生成，不沿用 work/ 的旧文件。

## 6. `result.json` 附加字段

| 字段 | 类型 | 说明 |
|-|-|-|
| `case_id` | string | 题面 id，必填 |
| `status` | enum | `ok`/`partial`/`blocked`/`refused` |
| `artifact_path` | string | 首选交付件（`deck.pptx`，降级时 `deck.md`） |
| `artifact_format` | string | `pptx`/`md`（Marp 源也是 Markdown） |
| `slide_count` | int | 主讲页数（不含 backup） |
| `duration_min` | number | 题面时长；逐页合计见 `self_check.total_seconds` |
| `mainline` | object | 与 `deck_spec.json.mainline` 同构 |
| `deck_outline` | array | 与 `deck_spec.json.slides` 同构 |
| `timing_table` | array | `index/seconds/cumulative/cumulative_mmss/segment` |
| `notes_path` | string | `speaker_notes.md` |
| `evidence_map` | array | `{slide, ref, quote, locator}` |
| `render_log` | object | `{source, exports[{path,format}], tool, preview}` |
| `self_check` | object | `{verdict, errors, warnings, slide_count, total_seconds}` |
| `uncertainty` | string[] | 未确认/已降级项 |
| `limits` | string | 一句环境与依赖限制 |
| `changes` | string[] | 在既有 deck 上改时的逐条改动 |

题面 `output_contract` 里的字段名优先；`kernel.py emit` 先按契约建骨架，
`deck_plan.py finalize` 只填空值，不覆盖已有内容，缺失字段写进 `uncertainty`。

## 7. 一致性不变量（机检）

1. `len(slides)` = `deck.md` 中 `# ` 标题数 = `speaker_notes.md` 中 `## 第 ` 小节数。
2. `Σseconds` = `timing.csv` 合计 = `result.json.duration_min × 60`（±容差）。
3. 每个 `visual.ref` ∈ `paper.json.figures/tables` ∪ `corpus.txt`。
4. 每条 `evidence.quote` ∈ `corpus.txt`（空白归一后）。
5. 每页 `title` 唯一；`kind` 首 title、末 conclusion。
6. `selfcheck.verdict = PASS` 时 `errors` 为空；`result.status` 只在有 pptx/pdf 时为 `ok`。
7. 交付目录不得引用 `/app/output` 之外的相对路径；不得含令牌、`/Users/` 路径或二进制粘贴。
