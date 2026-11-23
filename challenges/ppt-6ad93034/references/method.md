# 方法说明 · 学术 PPT 生成与编辑

## 1. 处理链路

1. 读 `/input/case.json`，取 `output_contract` 与 `case_id`。
2. 读 `/input/task.md` 与随案例提供的其它输入（字段表 / 工作单 / 断言清单）。
3. 对主材料做版面抽取，得到页、章节、句、数值、表格、图注的中间表示。
4. 按题面要求做字段级抽取（字段表 / 断言清单 / 工作单驱动）。
5. 按 `output_contract` 装配 `result.json`，逐字段带锚点与逐字引文。
6. 独立进程复核：契约齐备、锚点可定位、引文逐字命中、数值保真、状态诚实。

## 2. 中间表示

`/app/work/doc.json` 记录抽取到的一切，带以下键：

- `meta` —— 来源文件、抽取层级（`pdftotext` / `stdlib` / `plain-text` / `unreadable`）、字符数、页数
- `pages` —— 每页字符数
- `units` —— 章节单元，含标题、角色、起止页
- `numbers` —— 数值候选，含原值、数值、单位、锚点、上下文
- `tables` —— 表格，含行、单元格、锚点、版式
- `captions` —— 图注/表注

## 3. 抽取层级与降级

优先使用 poppler（`pdftotext -layout`）还原版面；缺失时降级到纯标准库 PDF 坐标抽取。
两档都拿不到文本层时输出 `extraction_failed` 并在 `uncertainty` 说明人工接管位置，不猜测内容。
实际使用的层级如实写入 `coverage.extraction.tier`，评审可直接看到证据来自哪一档。

## 4. 保守原则

- 找不到就写 `not_reported`，**不写 0、不写空串、不写 null 充数**。
- 同一字段多处给出互斥内容 → `source_conflict`，并列出冲突位置。
- 逐字引文命中只说明「有据可查」，不说明语义等价；语义判定留给上层复核。
- 数值不得换算、合并、跨字段移植；保留原值与单位。

## 5. 迁移到其它材料类型

本套链路与具体学科无关：换论文类型只需换 `resources/field_lexicon.json` 里的
`domain_keywords` 与 `status_vocabulary`，抽取内核与复核规则保持不变。

## 6. 依赖

- Python 3 标准库，无第三方依赖，无网络请求。
- 可选 poppler（`pdftotext` / `pdfinfo`），用于最佳版面还原；缺失自动降级。
