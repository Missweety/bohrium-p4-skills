# 抽取协议（可复核优先）

本文件描述 `scripts/field_extract.py` 的真实规则，便于评审复算；不是宣传材料。

## 1. 索引

1. 遍历 `/input`（跳过 `case.json`、`task.md`、`target-fields.json`、隐藏文件）。
2. PDF 用 `pdftotext -layout -f 1 -l 40`，按换页符切页，再按空行切段；无文本层直接标 unreadable。
3. JATS XML 按 `<p>` 取正文与真实 `id`，并回溯所属 `<title>` 作为 section。
4. Markdown/TXT 按空行切块；表格块按行保存，锚点为 `<文件>/tab.M/row.K`。
5. DOCX 读取 `word/document.xml` 的 `<w:t>`；其他二进制类型标 unsupported。

## 2. 字段行定位

1. 字段关键词 = `field_id` + `description` + `aliases`，去掉停用词、去复数。
2. 段落分 = 命中词次数加权；句分 = 命中的字段词数。
3. 数值字段：句内出现数字加 2 分。
4. CI / 对照 / 结论类字段：句中出现对应线索（`95% CI`、`compared with`、`conclude that`）加 8 分，
   且允许在低词分的段落中检索，避免“有线索但没字段词”被漏掉。
5. 每字段取最高分句子；无匹配句 → `not_reported`。

## 3. 取值

- **数值**：按“与字段词的字面距离 + 单位匹配”选数字，而非取句内第一个数字；
  年份减分；时间单位误配（把 follow-up 的 3 years 当成样本量）减分。
  数字后的单位必须是可识别单位（`mg/g`、`mmol/L`、`%`、`years` 等），
  否则 `unit=null`（例如 `240 participants` 不把 participants 当单位）。
- **95% CI**：字段名/描述含 `CI`/`confidence interval` 时，取 `1.10-1.74` 这样的原区间，
  `statistic="95% CI"`，不折叠为点估计。
- **对照**：取 `compared with/to/versus/对照` 之后的对象原文（如 `placebo`）。
- **结论**：取 `conclude that` / `结论` 之后的原句片段，不升级为确定事实。
- **表格**：若表头与字段高度匹配（≥2 个关键词命中），表格单元格优先于正文邻近数字；
  表格若为计数列而字段问“率”，保留单元格原文并在 note 说明“未换算为率”。

## 4. 诚实性约束

- `value` 必须是 `quote` 的逐字子串（归一化空白后），运行器逐行自检。
- `quote` 必须是材料中的逐字句（审计用全文检索复核）。
- `experimental_condition` / `comparator` 必须能在 quote 中逐字找到。
- 同一字段命中多段但无法判定时，优先报告最高分句，并把其他候选写入 note；
  只有同句出现互斥表述才标 `source_conflict`。

## 5. 已知限制

- 纯扫描 PDF、加密 PDF 无法读取，会标 unreadable 并降级。
- `pdftotext` 不存在时 PDF 不可读；Markdown/TXT/XML 不受影响。
- 只处理前 40 页 PDF；超出部分不索引（写入 limits）。
- 英文/中文规则式抽取，对复杂指代（“该指标”“上述剂量”）不做消解。
- 不合并多篇文献做元分析；跨文献冲突只记录，不下结论。
- 表格仅支持 Markdown 管道表；图片表格需外部 OCR。
