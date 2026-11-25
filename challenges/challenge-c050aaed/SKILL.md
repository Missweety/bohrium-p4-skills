---
name: anchored-annotation-notes
description: 把科研阅读材料整理成可回溯的知识沉淀：从 PDF 原生批注对象、Adobe/Zotero 导出、Word 批注与高亮、网页剪藏中抽取批注并区分类型，保留页码/坐标/颜色/标签；用逐字引文在原文文本层做锚点校验（精确/归一化/失败不猜测），再生成带来源定位的结构化笔记、带依据的知识关联与可过滤检索索引；同时交付哈希清单、跳过与冲突记录、审计报告，供他人复跑核对。
version: 1.1.0
license: MIT
---

# 阅读批注与知识沉淀：每条批注回得到原文，每条笔记指得到证据

交付物不是"抽出来的一堆句子"，而是一条可复核的链路：

文件清单（哈希/权限/元数据）→ 批注（类型/页/坐标/颜色/标签/逐字引文）→ 锚点校验
→ 结构化笔记（每条论断有支撑引文）→ 可解释关联（有依据，控制过度连接）→ 检索入口。

三条硬原则：

1. **不猜锚点**：引文在当前页文本层中找不到，就标 `quote_not_found`/`low_fidelity_text` 并升级人工，
   绝不挂到"相邻段落"或按页序凑一个页码。
2. **不猜语义**：颜色只记色值，含义只来自案例给出的图例；批注类型只按原生 subtype/导出字段分类，
   未识别的类型记 `unknown` 并列入人工复核。
3. **不猜关系**：关联必须有依据（同版本族、显式标签、词表实体、同页邻接）；
   仅关键词重合默认不连边，并记录被拒绝的候选与原因。

## 何时使用

触发：给定一个包含 PDF/扫描件/Word/网页剪藏与批注导出的材料目录，要求
"抽批注 / 整理成笔记 / 建立关联 / 做可检索沉淀 / 给出可复核清单与过程记录"。

不触发：文献检索与推荐；对论文内容做科学判断或写作；目录治理与长期归档制度建设；
要求提供人工金标准答案或声称抽全了未提供文件中的批注。

## 输入

运行时读取 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`。
材料按 `case.json` 的 `materials`/`files`/`inputs` 或材料目录实际文件发现。支持的载体：

| 载体 | 读取内容 | 批注来源 |
|-|-|-|
| `.pdf` | 页对象、内容流文本层（FlateDecode）、Info 标题、`/Encrypt` 标记 | 页面 `/Annots` 指向的批注对象：Subtype、Rect/QuadPoints、`/C` 颜色、`/T` 作者、`/Contents` 备注、`/M` 时间 |
| 批注导出 `.json/.jsonl/.csv/.tsv/.xfdf` | 逐条记录（Zotero/Adobe 常见字段别名） | 类型、页、坐标、颜色、标签、引文、备注、作者、时间、来源文件 |
| `.docx` | 段落文本、core 元数据 | `w:commentRangeStart/End` 区间内文字 + `comments.xml`；`w:highlight` 高亮 run |
| `.html/.htm` | 标题与可见文本 | `<mark>` 或 class/id 含 highlight/annotation/note 的元素内文字 |
| `.md/.txt` | 标题与正文 | Markdown `==高亮==` |
| 其他/不可读 | 只登记，不猜内容 | 无 |

常见字段别名（大小写、下划线、连字符不敏感）见 `references/output-contract.md`。
PDF 批注对象与导出记录若同页且坐标 IoU≥0.3，会合并为一条：几何取自 PDF，引文取自导出，
`merged_from` 保留双来源。加密 PDF、无文本层扫描件只登记可读部分，不伪造引文。

## 执行流程

### 0. 一键端到端

```bash
python3 /skills/weekly-skill/scripts/run_case.py --case /input/case.json --materials /input \
  --work /app/work --out /app/output
```

依次：契约 → 材料索引（sha256/权限）→ 文档解析 → 批注抽取与合并 → 锚点校验
→ 版本族/重复识别 → 笔记结构化 → 关联与拒绝记录 → 检索索引 → 契约回填与自检。

### 1. 清单与权限

每个文件登记：相对路径、sha256、字节数、扩展名、可读性、是否加密、是否符号链接。
不可读/不支持的载体写入 `failures_recovery.skipped`，不按文件名猜内容。

### 2. 批注抽取与类型区分

类型归一：`highlight` / `underline` / `strikethrough` / `wavy_underline` / `note` /
`marginal_note` / `free_text` / `handwriting` / `comment` / `web_clip` / `unknown`。
颜色输出 `#rrggbb`；`color_meaning` 仅当案例提供 `color_legend` 时填写，否则为 `null`。
手写/涂鸦（Ink）只有坐标没有引文时，锚点状态为 `coordinate_only`，不编造文字。

### 3. 锚点校验（核心）

对每条有引文的批注，只在该批注所属文件的实际文本层内查找：

1. 原文精确匹配 → `exact`，记录字符区间；
2. 去空白与标点后匹配 → `normalized`，区间映射回原文；
3. 引文在当前页出现多次 → 仍记录首个区间，但 `ambiguous=true` 并升级人工；
4. 找不到且文本层保真度低 → `low_fidelity_text`（扫描件/CID 字体），升级人工；
5. 找不到且文本层正常 → `quote_not_found`，写入冲突清单；
6. 无页码 → `page_unknown`；无文本层 → `text_layer_unavailable`；仅来自导出 → `export_only`。

任何未校验通过的批注都保留原样并标 `needs_review=true`，不调整页码或坐标。

### 4. 版本与重复

- 相同 sha256 → 同一文件重复，`duplicates_of` 指向首份；
- 归一化标题（去版本标记/副本后缀）相同但 sha 不同 → 同一版本族，记录合并依据；
- 同族不同版本对同一引文给出不同页码 → 写 `page_drift_between_versions` 冲突，不取平均；
- 家族内批注不跨版本自动合并引文；只在关联中标注"同族不同版本"。

### 5. 笔记结构化

按"显式标签"或"同文件同页"聚合批注。笔记字段：`note_type`（question/method/conclusion/
reusable/todo/excerpt）、`claim`、`support`（批注 ID + 逐字引文 + 锚点状态）、来源定位。
`claim` 优先取作者备注（作者的判断），无备注时才用引文并标 `excerpt`；不生成原文没有的论断。
无任何已验证支撑的笔记标 `support_status=unverified`，仍保留但不冒充完成。

### 6. 关联与过度连接控制

依据优先级：`same_version_family` > `shared_label` > `shared_entity`（案例词表或大写缩写）
> `same_page_adjacent`（同页间距≤80 字符）。仅词面 Jaccard≥0.5 的候选默认**拒绝**，
写入 `links.csv` 的 `accepted=false` 与原因；每条笔记最多保留 3 条接受关联，超出降级为拒绝。

### 7. 检索

生成 `search_index.json`（CJK 二元组 + 拉丁词元的倒排索引，按笔记标题/论断/标签/引文建项），
`scripts/search.py` 支持按词、标签、来源文件、时间过滤；零命中时返回放宽建议并记录，
不把"没检索到"说成"不存在"。

### 8. 交付与自检

```bash
python3 /skills/weekly-skill/scripts/run_case.py --case /input/case.json --materials /input \
  --work /app/work --out /app/output      # 产出 result.json 与全部附件
python3 /skills/weekly-skill/scripts/search.py \
  --index /app/output/search_index.json --query "关键结论"
```

自检项：每条批注有来源定位；已验证锚点必有字符区间；每条笔记有支撑批注；
接受关联必有依据；版本/重复已登记；契约字段齐全；不可读文件未被静默丢弃。

## 输出

- `result.json`：`case_id`、`status`、`summary`、`input_inventory`、`documents`、
  `metadata_summary`、`version_relations`、`annotations`、`anchor_quality`、`notes`、`links`、
  `search_index_meta`、`search_results`、`operations_log`、`conflicts`、`failures_recovery`、
  `uncertainty`、`limits`、`validation`、`changes`，以及 `output_contract` 的全部字段。
- `annotations.csv`、`notes.csv`、`links.csv`、`search_results.csv`（有检索问题时）、
  `search_index.json`、`audit_report.md`、`run_manifest.json`。

字段与机检口径见 `references/output-contract.md`。

## 异常处理

| 情况 | 处置 |
|-|-|
| 材料目录为空/不可读 | `status=blocked`，不产出伪清单 |
| 输入含符号链接 | 不跟随（防目录逃逸），登记可读性=false 并写入 `failures_recovery.skipped` |
| PDF 文件头损坏 / 非 PDF | 判 `pdf_invalid_header`，文档记为不可读，`status=partial` |
| 文本编码为 GBK/UTF-16 | 按 UTF-8→GB18030→UTF-16 解码，引文保持原文，不乱码 |
| `output_contract` 为 `{required:[...]}` | 按 required 列表回填字段，不生成多余字段 |
| PDF 加密或无文本层 | 只登记元数据与导出批注；锚点 `text_layer_unavailable`，不 OCR 编造 |
| 扫描件文本层乱码 | 保真度<0.55 → `low_fidelity_text`，升级人工 |
| 批注类型未识别 | `unknown` + `needs_review`，不并入其他类型 |
| 引文多页重复 | 记录首处 + `ambiguous`，升级人工 |
| 同一文件重复下载 | `duplicates_of` 合并元数据，批注只保留一份并记来源 |
| 同族版本页码漂移 | 写冲突，不覆盖、不取平均 |
| 导出缺少页码/坐标 | 锚点 `export_only`/`page_unknown`，不猜 |
| 检索零命中 | 返回放宽建议并记录，不声称资料不存在 |

## 最小调用示例（合成示例，非正式案例）

随包 `examples/` 自带可直接运行的合成材料：`case.json`（`output_contract.required` 为列表、
颜色图例、2 个检索问题、词表）、`paper.md`（3 处 `==高亮==`）、`paper_export.json`
（1 条同页高亮 + 1 条引文不存在的脏锚点）、`task.md`。

在任意 cwd 用绝对路径运行：

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --case /skills/weekly-skill/examples/case.json --materials /skills/weekly-skill/examples \
  --work /tmp/annot_work --out /tmp/annot_out
python3 /skills/weekly-skill/scripts/search.py \
  --index /tmp/annot_out/search_index.json --query "待验证"
```

本机实测（示例材料，非正式案例）：1 份文档、4 条批注、4 条笔记；锚点 `exact` 3 /
`quote_not_found` 1；`status=partial`；8 项自检全通过；检索"待验证"命中 2 条结果记录。
原生 md 高亮与导出记录按"同文档 + 归一化引文"合并，补齐页码与作者备注；脏锚点保留并升级人工。
以上数字只说明链路可跑通，不代表正式案例结果或分数。

## 限制

- PDF 文本层由标准库解码，CID/CJK 字体可能无法还原，此时只做导出引文校验并明确标注；
  不做 OCR，不补造扫描件文字。
- 原生 PDF 批注仅解析可直接读取的对象；批注存放在压缩对象流中的 PDF 会退回导出记录，
  并写入 `failures_recovery`。
- 笔记类型与关联为规则判定，不替代研究者的内容判断；`unknown`/`unverified` 项需人工确认。
- 只对提供的材料负责，不声称覆盖未提供文件、云端账户或批注历史。

## 改动记录

- **1.1.0**（2026-11-25）工程修复：文档命令统一 `python3` 与 `$SKILL_DIR` 绝对路径（平台仅有
  python3）；新增可运行 `examples/`；`output_contract` 支持 `{required:[...]}`；文本/导出按
  UTF-8→GB18030→UTF-16 解码；符号链接不跟随并登记；损坏 PDF 判 `pdf_invalid_header` 且
  `status=partial`；原生批注与导出改为"同文档+归一化引文"合并（补页码/备注），笔记按空行分段
  分组、claim 优先取已验证批注；无文本层文档也计入 partial；复用输出目录时删除上轮遗留
  `search_results.csv`。
- **1.0.0**（2026-11-21）首版：四类载体批注抽取与类型/颜色/标签保留；原生 PDF 批注与导出按
  页+坐标 IoU 合并；逐字引文锚点校验（exact/normalized/多义/低保真/失败不猜测）；
  sha256+版本族+重复与页码漂移冲突；带支撑的结构化笔记；四类依据的可解释关联与过度连接拒绝；
  CJK 二元组倒排索引与过滤检索；哈希清单、跳过/恢复记录与 8 项机检。
