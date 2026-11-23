---
name: patent-record-normalizer
description: 从公开号、申请号、优先权或技术主题出发，规范化专利号码，按显式 family_id 或共享优先权聚类可观测专利族，核验给定法律状态，记录权利要求版本与数据许可边界，并给出证据强度与人工复核建议。
version: 1.0.0
---

# 专利与技术文献检索：号码、同族、状态与授权边界

## 适用场景与触发

用户给出专利公开号/申请号/优先权号，或要求“查这个技术主题还有谁在做”“这几件是不是同一族”“现在是否有效”“这些数据能不能对外展示”时触发。典型输入是有限的专利记录集（CSV/JSON）加若干原始著录页，而不是可实时查询的商业专利库。

本 Skill 负责：检索对象识别、号码规范化、同族归并口径、主题检索式、法律状态核验、权利要求版本边界、数据许可分级与证据强度。不负责专利撰写、侵权判定、自由实施分析、专利价值评估，也不替代专利律师意见；不绕过付费墙、不上传受限数据、不对外展示受限库原文。

## 输入

必读 `/input/case.json`、`/input/task.md`，存在时读 `environment/resources.yaml`。先清点真实文件，再读实际著录页；PDF/OCR 以页面内容为准，不以文件名推断号码或状态。

**output_contract 必须动态读取**：从 `/input/case.json` 取 `output_contract`，建立“契约字段 → 本次实际产物”的映射，写入 `result.json`。不得写死案例 ID、号码或答案；字段名、类型、嵌套以契约为准。无法填出的必需字段保留 `null` 并在 `field_status`/`uncertainty` 说明。映射规则见 `references/output-contract.md`。

记录字段（脚本接受常见别名）：`number, jurisdiction, kind, application_no, priority, family_id, title, assignee, status, status_date, source_file, locator, legal_scope`。`number` 是公开号；`kind` 是文献种类代码（如 A1、B2）。`priority` 可用 `;` 或 `|` 分隔多个优先权号。`legal_scope` 描述该记录的展示/许可范围，不是法律状态。

## 输出

脚本产物（`/app/work/patent-normalize/`）：

- `normalized.csv`：逐记录规范化号码、申请号、优先权、族簇、状态分类、来源等级、证据强度、标记。
- `families.json`：可观测族簇、归并依据与口径、成员、冲突、问题清单。
- `issues.csv`：错误/警告/提示的逐条定位。

Agent 产物（`/app/output/`）：

- `normalized.csv`、`families.json`（可引用脚本结果并补充人工判定）。
- `claims.csv`：权利要求版本与边界，见第 5 步。
- `report.md`：检索对象、号码与族口径、主题检索式、状态来源与查询日期、许可分级、证据强度、人工复核建议。
- `result.json`：保留 `case_id`，按 `output_contract` 映射全部字段，附 `run_status`、`sources`、`uncertainty`、`change_log`。

## 六步工作流

### 1. 识别检索对象

先判断用户要的是：特定号码、特定族、还是技术主题。记录检索起点（公开号/申请号/优先权号/关键词/分类号）和预期范围。号码检索与主题检索的证据要求不同：前者要求号码与著录项逐项对上，后者要求检索式、分类组合和命中范围可解释。不要把“主题相关”当成“同一专利”。

### 2. 号码规范化与同族去重

用脚本把公开号规范为 `CC + 号码 + kind`：去空格、连字符、斜杠、逗号、点后大写；校验司法辖区与 kind；解析失败保留原值并标记。`application_no`、`priority` 同样去分隔符，但不强行拆出 kind。

同族按脚本可观测的两类依据聚类：显式 `family_id`（声明族）与共享 `priority`（优先权扩展族）。归并口径必须写明：显式族优先，优先权只连接“本批记录中实际共享”的号码；同一 `normalized` 公开号的重复记录先并入同一记录组（保留 `duplicate_record` 标记），不拆成多族；既无 `family_id` 又无优先权的记录为单例，标 `family_unknown`。同一优先权连接出多个声明族时标 `family_conflict`，不擅自合并或拆分。

### 3. 主题检索组合

主题检索式要写清组合逻辑：关键词（含同义词/缩写/本地语言写法）+ IPC/CPC 分类号 + 申请人/受让人 + 引证关系。记录每个检索式的来源库/导出、日期、字段、过滤条件、命中数、定位。区分专利文献与技术文献：前者按分类号和同族扩展，后者按论文数据库与引文追踪，不能混为一次检索。检索结果只来自有授权的来源，并标注库名、版本与查询日期。

### 4. 法律状态核验

法律状态只用给定记录或官方登记页，注明来源、查询日期和可能滞后。状态分类（有效/审中/失效/届满/撤回/驳回/未知）由脚本按文本归类，但结论必须回到原记录。状态缺失、状态日期缺失、状态文本无法归类、状态过期或同一号码状态冲突都要单列。不得把转载页、聚合站或旧网页当作官方登记依据；不得声称实时法律状态。

### 5. 权利要求版本与边界

从实际公开文本抄录权利要求版本：`record_id, claim_version, claim_no, claim_type, claim_text_locator, scope_note, source_file, locator, retrieved_date`。区分独立权利要求与从属权利要求，标明版本（申请公开/授权公告/修改后）。只描述文本实际覆盖的内容，不做侵权、有效性或自由实施结论；权利要求缺失时写 `unavailable`，不推测。

### 6. 许可分级、证据强度与人工复核

逐条记录数据源许可、字段可展示范围、留存期限和企业保密要求，形成绿/黄/红依赖分级：

- 绿：官方公开登记或明确允许展示的公开文献；
- 黄：有授权但字段/展示范围受限，需降级为摘要或统计；
- 红：需登录、付费墙、保密或禁止外传，只能给出“存在/不存在”级信息或明确拒绝。

无法访问时执行降级方案（改用摘要、分类号统计、公开同族），并记录降级原因。最后按来源等级、号码有效性、状态完整度给出证据强度（high/medium/low）和人工复核建议；证据不足的结论不得写成确定事实。

## 脚本

```sh
cd /skills/weekly-skill
python3 scripts/source_index.py extract --input /input --out /app/work/source-index.json
python3 scripts/patent_normalize.py --input /app/work/records.csv \
    --out /app/work/patent-normalize --as-of "$(date +%F)" --max-status-age-days 180
```

脚本以 Skill 根目录为工作目录，先 `cd /skills/weekly-skill` 再运行；若平台安装路径不同，以实际 Skill 根目录替换。`--as-of` 使用运行时当天日期（`date +%F`），不写死日期；报告中记录该日期、数据来源日期与状态滞后，说明“状态可能已变化”。

`--input` 支持 `.csv/.tsv/.json/.jsonl` 单文件，或按排序扫描的目录；目录中 `case.json`、`task.md`、`resources.yaml` 自动跳过。`--as-of` 可选：提供后才评估状态日期是否过期；不提供则明确记录“未评估时效”。`--max-status-age-days` 默认 180。

退出码：`0` 完成且无问题；`2` 完成但有问题（含空输入）；`1` 输入不可用（路径缺失、无可解析记录文件、`--as-of` 非法）。退出码 `2` 不是运行失败，需阅读 `issues.csv`。

逐字核对著录项或权利要求引文时：

```sh
python3 scripts/source_index.py verify --index /app/work/source-index.json \
    --claims /app/work/claims.json --out /app/work/quote-check.json
```

`claims.json` 形如 `{"evidence":[{"file":"USPTO-1.pdf","locator":"page:1","quote":"逐字片段"}]}`。该工具只验证逐字文本与文件哈希，不判断号码真实性、法律状态或权利要求范围。

## 失败、空结果、权限与冲突

- **空结果**：保留空数组和 `input_empty`，说明检索式、来源和未命中范围；不补造专利。
- **号码解析失败**：保留原值，标 `number_unparseable`/`jurisdiction_missing`/`kind_missing`，不猜补号码。
- **同族口径不明**：明确写“声明族/优先权扩展族/单例”，不声称完整同族；一个优先权连接多个声明族时标 `family_conflict`。
- **状态冲突/过期**：同一号码不同状态并保留全部来源，标 `status_conflict`；状态日期过旧标 `status_stale`，并注明查询日期与滞后可能。
- **非官方来源**：聚合站、转载页、博客标 `source_secondary`；只作线索，不作登记依据。
- **扫描件/无 OCR**：`source_index.py` 没有 OCR 兜底；WO 等扫描型 PDF 若无嵌入文本会标为不可提取。此时降级为公开著录项/摘要级信息，人工目视核对号码、kind、页码与状态，并在 `uncertainty` 写 `ocr_unavailable` 与核对方式；不得凭文件名或图像臆测正文。
- **鉴权失败/限流/付费墙**：记录服务、错误与时间，执行黄/红降级；不得绕过访问限制或上传受限数据。
- **字段缺失**：标 `status_missing`/`application_no_missing`/`legal_scope_missing` 等，不用默认值填充。

## 停止条件

- 检索对象（号码/族/主题）已有可核结果或明确无结果；
- 目标专利的同族、状态、权利要求版本和许可边界均有“已核/受限/缺失”状态；
- 新增检索不再改变候选集，或只剩无权限来源；
- 达到平台时限或请求上限前先落盘可核部分；
- 高风险结论已完成人工复核，或明确记录未完成。

停止不等于声称穷尽：报告写“已检索范围”“未覆盖来源”和后续核验建议。

## 禁止编造

不得编造专利号、申请号、优先权、同族关系、法律状态、权利要求、来源库、查询日期或人工复核。不得声称实时法律状态、完整同族或等同权利要求范围。不得把聚合站数据说成官方著录项。所有号码与状态必须回到当前输入文件或明确来源；文件变化后旧引文失效。

## 限制与维护

- 脚本只做号码规范化、可观测族聚类、状态文本分类与一致性检查，不访问官方登记库，不判断专利性、侵权或价值。
- 内置司法辖区表覆盖常见专利局代码，不是完整 ISO 3166 列表；未识别代码标 `jurisdiction_unverified`。
- `family_id` 与 `priority` 归并只反映本批记录中可观测的连接，不等于 DOCDB/INPADOC 完整族。
- `claims.csv` 与许可分级由 Agent 基于实际文本维护，脚本不生成、不补全。
