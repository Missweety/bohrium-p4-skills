---
name: academic-format-adaptation
description: 把学术稿件套用目标期刊/学位论文模板或格式要求，生成真实可编辑的 DOCX（样式、页面、多级编号、题注、参考文献、页码域），并逐项核验输出、写出 format_report.json 与 result.json。Use for manuscript formatting, journal template adaptation, DOCX style application, format compliance checks.
version: 1.1.0
---

# academic-format-adaptation

把「稿件 + 模板/格式要求」变成：
1. 可编辑的 DOCX（真实 OOXML 样式，不是纯文本）；
2. 逐项核验报告 `format_report.json`（需求 → OOXML 位置 → applied/partial/unsupported）；
3. `result.json`（满足 `case.json` 的 `output_contract`）。

所有格式值来自运行输入（模板 DOCX、JSON/YAML 规格、任务文本或稿件自身样式），
脚本不预置答案；无法确认的内容写进 `uncertainty` / `issues`，不虚构渲染或页数。

## 什么时候用 / 不用

用：
- 输入是 DOCX / Markdown / TXT 稿件，要求套用期刊或学位论文格式。
- 提供模板 DOCX、`spec.json`/`spec.yaml`，或在 `task.md` 里写格式要求。
- 需要样式化标题、页边距、正文、题注、参考文献、页码，并核验是否真的写进了文档。

不用：
- 扫描版 PDF 的版面复刻、OCR、图片重绘。
- 需要 Word/LibreOffice 以外的排版引擎（LaTeX、InDesign）。
- 要求保证与模板视觉完全一致：本包只做 XML 级核验，不做人工目检。

## 运行时约定

- 案例：`/input/case.json`；材料目录 `/input`（`task.md`、模板、规格、稿件）。
- 工作目录：`/app/work`（中间产物，可写）。
- 交付目录：`/app/output`（最终 DOCX、报告、`result.json`）。
- 本 Skill 安装目录：`/skills/weekly-skill`；命令中的 `scripts/` 相对该目录。
- 只依赖 Python 3.9+ 标准库；`soffice` 存在时才渲染 PDF 并报告真实页数。

## 一条命令（首选）

```bash
S=/skills/weekly-skill/scripts
python3 $S/parse_inputs.py --input /input --work /app/work && \
python3 $S/build_docx.py --work /app/work --output /app/output && \
python3 $S/verify_format.py --work /app/work --output /app/output && \
python3 $S/selfcheck.py --case /input/case.json --work /app/work --output /app/output
```

退出码：
- `parse_inputs.py`：0 = 写出 `inputs.json`/`spec.json`（缺模板也算 0，用默认规格并记录 warning）。
- `build_docx.py`：0 = DOCX 已生成且重开成功；2 = 没有可格式化内容，拒绝伪造文档。
- `verify_format.py`：0 = 报告已写出；1 = DOCX 不存在/不可打开。
- `selfcheck.py`：0 = `checks.json.verdict=PASS`；1 = 硬检查失败（同时写出 `result.json`）。

## 分步命令

```bash
cd /app/work
S=/skills/weekly-skill/scripts
# 1) 解析输入：发现稿件/模板，抽取格式规格
python3 $S/parse_inputs.py --input /input --work /app/work
# 2) 生成 DOCX（有 soffice 则同时渲染 PDF）
python3 $S/build_docx.py --work /app/work --output /app/output [--no-render]
# 3) 逐项核验 DOCX
python3 $S/verify_format.py --work /app/work --output /app/output
# 4) 契约与一致性自检，组装 result.json
python3 $S/selfcheck.py --case /input/case.json --work /app/work --output /app/output
```

可选手工覆盖（仅在自动发现错误时）：

```bash
python3 $S/parse_inputs.py --input /input --work /app/work \
  --manuscript /input/paper.docx --template /input/template.docx
python3 $S/verify_format.py --work /app/work --output /app/output --docx path/to/file.docx
```

## 支持的输入与格式

稿件：`.docx`、`.md`、`.txt`；`.doc`/`.pdf` 需要本机 `textutil` 或 `soffice`/`pdftotext`，
转换结果会标注 `converted_by` 与保真度警告。

模板/规格：
- 模板 DOCX：读取 `styles.xml`（docDefaults、Normal、Heading 1-4、Caption、Bibliography）、
  `sectPr`（纸张、页边距、分栏、页码）、`numbering.xml`（多级标题编号）、页眉/页脚。
- 结构化规格：JSON / YAML，字段见 `references/format-spec.md`。
- 任务文本：`task.md` / 说明文件中的「纸张、页边距、字体、字号、行距、首行缩进、
  标题、题注、三线表、参考文献、页码、目录、分栏、导出 PDF」等要求。

可应用：页面尺寸与方向、页边距、正文/标题/题注/参考文献样式、多级标题编号（真实
`numbering.xml`）、图/表题注位置与编号、参考文献悬挂缩进、页脚 PAGE 域、页眉文本、
三线表边框、行距、缩进、对齐、目录域（需 Word 更新）。

部分支持 / 不支持：多栏只写 `sectPr` 栏属性，不宣称分栏平衡；目录页码需更新域；
公式、页眉复杂版式、脚注、水印、行号、上标引用等未实现，若任务明确要求会记为
`unsupported`，不会假装已满足。

## 核验规则

`verify_format.py` 对每条需求给出 `status` 与 OOXML 位置：
- `applied`：能从 XML 直接读到目标值（如 `w:pgMar`、`w:spacing`、`w:numPr`）。
- `partial`：写入了但无法完全确认（多栏平衡、目录页码、PDF 缺失时的页数）。
- `unsupported`：生成器没有对应实现，或任务要求无法在 DOCX 中核验。
- `not_applicable`：稿件里没有该对象（无图/无表/无参考文献）。
- `failed`：应当存在但实际缺失（例如文本块丢失）。

`selfcheck.py` 额外检查契约字段、文件存在、DOCX 重开、报告计数自洽、占位符、
`status` 与 `issues` 一致性。硬检查失败退出 1。

`verify_format.py` 新增 `media.relationships`：扫描 `document.xml` 中的
`r:embed/r:id/r:link`，逐个确认关系已在 `word/_rels/document.xml.rels` 声明，
且图片/页眉/页脚目标部件真实存在于包内；悬空关系记 `failed`，不再默认成功。

## 异常处理表

| 情况 | 行为 | status |
|-|-|-|
| 没有模板/规格，但有 `task.md` 要求 | 用任务文本抽取的规格；保留默认值并记录来源 | 有无法确认项则 `partial` |
| 完全没有模板或要求 | 使用内置默认规格（A4、2.54cm、12pt、1.5 行距）并写 warning | `partial` |
| `.doc` legacy 稿件 | 尝试 `textutil`/`soffice` 转 DOCX；失败则转文本并警告；无转换器则记录 unsupported | `partial` |
| 任务要求未实现（公式/页眉版式/行号等） | 写入 `meta.unmatched_requirements`，报告中记 `unsupported` | `partial` |
| 稿件缺参考文献/图/表 | 不虚构条目或对象；任务明确要求参考文献时记 `partial`，未要求时记 `not_applicable` | `partial`/`not_applicable` |
| 空输入 / 无稿件内容 | 不生成空文档；`build_meta.status=failed`，`result.json` 仍写全字段 | `failed` |
| 无 `soffice` | 不产出 PDF，不报页数；`export.pdf` 记 `partial` 并说明原因 | `partial` |
| 字体本机缺失 | DOCX 仍写目标字体；渲染可能替换，记 `uncertainty` | 通常不影响 status |

诚实 `partial` 规则：只要没有把全部需求确认写入 DOCX，或存在开放 issue、
模板缺失、多栏/目录/页数未目检，就不能写 `success`；绝不能为了通过而删检查、
改数值或补造内容。

## result.json 契约

默认字段与一致性约束见 `references/output-contract.md`。核心字段：
`case_id`、`status`（success/partial/failed）、`docx`、`format_report`、
`page_count`、`sources`、`uncertainty`、`change_log`、`issues`、`deliverables`、
`contract_fields`。`case.json` 的每个 `output_contract` 字段都会存在；
没有直接产物的字段写 `null` 并记入 `issues`，不会静默省略。

## 依赖与限制

- Python 3.9+ 标准库（必需）。
- LibreOffice `soffice`（可选）：真实 PDF 与页数；缺失时不宣称页数。
- 字体：`fc-match` 仅用于提示渲染替换，不用于证明视觉一致。
- 不访问网络，不读取凭据，不写绝对个人路径。
- XML 级核验不替代人工目检；复杂浮动对象、域更新后的分页、精确字距不在保证范围。

## 最小示例（SYNTHETIC，非评测答案）

```bash
python3 /skills/weekly-skill/scripts/parse_inputs.py \
  --input /skills/weekly-skill/examples/demo_input --work /app/work/demo
python3 /skills/weekly-skill/scripts/build_docx.py \
  --work /app/work/demo --output /app/output/demo
python3 /skills/weekly-skill/scripts/verify_format.py \
  --work /app/work/demo --output /app/output/demo
python3 /skills/weekly-skill/scripts/selfcheck.py \
  --case /skills/weekly-skill/examples/demo_input/case.json \
  --work /app/work/demo --output /app/output/demo
```

`examples/README.md` 说明合成数据、预期关键输出与逐项核验方法。

## 改动记录

### 1.1.0（基于 1.0.0 / 05_skills_iter1）

- 修复图片关系丢失：`package()` 先构建正文、再派生关系与 Content-Types，
  图片（DOCX 稿件、Markdown `![]()`、行内图）现在有 `rIdImg*` 关系、`word/media/*`
  实体与 png 等默认类型；此前引用的 `r:embed` 悬空，Word/渲染器不显示图片。
- 新增 XML 级 `media.relationships` 核验：悬空 `r:embed/r:id/r:link` 记 `failed`，
  避免「图片丢失但报告 success」。
- 保留稿件超链接：源 `w:hyperlink` 按外部关系（`TargetMode="External"`）复制，
  目标 URL 做 XML 转义；无法解析的对象关系记 `partial` issue。
- 修复规格来源判定：`provenance` 递归展开到叶子路径，`is_default` 支持祖先回退，
  不再把默认的 `references.heading`（References）当作用户要求，避免把中文
  「参考文献」改写成「References」、把「图 1」题注改写成「Figure 1」。
- 标题编号去重支持中文序号（`一、`、`（一）`、`第X章`），避免与 `numbering.xml`
  自动编号叠加成「1 一、引言」；年份开头的标题不误删。
- 无参考文献的稿件不再因默认 heading 被误判 `partial`；未要求参考文献时记
  `not_applicable`。
- 修正 Markdown 段落/题注的 `line` 归属（用段落起始行，而非 flush 行）。
- 测试用于合成夹具（非评测答案）：DOCX 稿件+模板、Markdown 图片、行内图、
  中文序号标题、超链接、空输入、GBK 字节、缺图、只有纸张要求等。
