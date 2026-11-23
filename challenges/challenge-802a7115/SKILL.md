---
name: cross-language-literature-matrix
description: 对真实多语文献记录判定语种与版本类型，建立逐作品语言/版本矩阵，维护受控翻译日志与术语表，按语种检索并把命中对齐到原文证据；显式报告仅摘要、重复版本、同作多语、缺失语种与孤立版本。
version: 1.0.0
---

# 跨语言文献检索：语言/版本矩阵与逐语种证据

## 适用场景与触发

用户提出“同一研究在不同语种里怎么找”“非英语原文是否漏检”“这篇是原文还是译文”“同一论文的多语版本是否重复计数”等跨语言检索任务时触发。典型输入是研究问题加若干作品/版本记录（CSV 或 JSON），不是可直接全文检索的数据库快照。

本 Skill 负责：语种与版本判定、受控翻译记录、术语表、逐语种查询设计、跨语言匹配、回译/人工抽检与跨版本去重，并交付可复核的证据。不负责整篇翻译、写作润色、绕过付费墙或跨境抓取。

## 输入

必读 `/input/case.json`、`/input/task.md`，存在时读 `environment/resources.yaml`。先清点真实文件，再读实际原文；PDF/图片以页面内容为准，不以文件名或领域标签推断语种。

**output_contract 必须动态读取**：从 `/input/case.json` 取出 `output_contract`（字段名、类型、是否必需、嵌套结构），建立“契约字段 → 本次实际产物”的映射，写入 `result.json`。不得写死案例 ID、字段名或答案；契约与默认模板冲突时以契约为准。无法填出的必需字段保留 `null` 并在 `field_status`/`uncertainty` 说明，不能编造。映射细节见 `references/output-contract.md`。

记录文件字段（脚本接受常见别名）：`work_id, version_id, language, version_type, doi, title, translated_from, source_file, locator`。`version_type` 仅接受 `original | translation | abstract_only | duplicate | bilingual`。`language` 支持单值、JSON 数组，或用 `; , | /` 分隔的多值；脚本归一（含 `por→pt`、`eng→en`、`中文→zh`）后去重，多语记录同时进入各语种矩阵。真实原文是判定语言与版本的唯一依据，标签只作待核线索。

## 输出

脚本产物（`/app/work/lang-matrix/`）：

- `matrix.json`：逐作品语言/版本矩阵、计数、问题清单。
- `versions.csv`：逐记录规范化字段、状态、重复指向与标记。
- `issues.csv`：错误/警告/提示的逐条定位。

Agent 产物（`/app/output/`）：

- `matrix.json`、`versions.csv`（可复制或引用脚本结果并补充人工判定）。
- `translation-log.csv`：受控翻译日志，见第 2 步。
- `report.md`：研究问题、语种与版本判定依据、术语表、逐语种查询、匹配与假阳性复核、去重和缺口。
- `result.json`：保留 `case_id`，按 `output_contract` 映射全部字段，附 `status`、`sources`、`uncertainty`、`change_log`。

## 六步工作流

### 1. 从真实原文判定语言与版本

逐条读实际原文（标题、摘要、正文起始段、版权页），判断：正文语言、是否原文/译文/双语刊、是否只有摘要。记录判定证据位置（文件 + 页/行）。不要仅凭 `language` 字段或文件名下结论；标签与原文冲突时以原文为准，并把冲突写入 `issues`。区分“原文语言”“译文目标语言”“摘要语言”，不要把摘要语言当作全文语言。

### 2. 受控翻译日志

为每次查询/术语翻译记录一行：`item_id, source_text, source_language, target_language, translated_text, method, service, service_version, date, human_reviewed, uncertainty, source_file, locator`。

- 使用机器翻译时写清服务与版本、日期；不得声称未使用的服务。
- 无翻译服务时，明确写 `method=manual` 或 `method=model`，并标注不确定性；模型翻译须人工抽检高风险术语。
- 不把译文当原文引用；引用原文时保留源语言原句和定位。

### 3. 术语表

建立 `term_id, concept, source_term, language, term_type, variants, evidence, confidence` 表。覆盖同义词、缩写、上下位概念、音译、本地译名和学科惯用语（如中文“细胞焦亡”对应英文 pyroptosis、日文片假名转写、德文复合词）。缩写必须消歧：同一缩写在不同语种可能指不同概念，记录消歧依据。术语扩展要有边界，避免把近义泛词全部纳入。

### 4. 逐语种查询

按目标语种分别生成查询式，而不是把整句机翻后只查一次。每条查询记录：语种、查询式、术语来源（term_id）、数据库/导出文件、日期（若有）、过滤条件、命中数、输入定位。区分“实际执行的查询”和“建议但未执行的查询”；有限快照必须明说。

### 5. 跨语言匹配与词形/复合词处理

处理译文用词与论文原文用词不一致：词形变化、复合词拆分、语序、中英混排标题、连字符断行。匹配时同时看原文词与译文词，记录匹配依据；不能只靠字符串相等。对每条候选保留来源文件、语种、版本类型和相关证据位置。

### 6. 回译/人工抽检与跨版本去重

对高风险命中做回译或人工抽检，判定“词面对应、语义不同”的假阳性，记录判定依据。随后按 `work_id` 汇总语言与版本：同一论文的原文、译文、双语版、仅摘要、重复导出分别标注；重复版本只计一次覆盖，但保留全部记录和指向。仅摘要不得计入全文覆盖；孤立版本（`translated_from` 指向不存在版本、缺 `version_id`）单独列出。

## 脚本

```sh
cd /skills/weekly-skill
python3 scripts/source_index.py extract --input /input --out /app/work/source-index.json
python3 scripts/language_matrix.py --input /app/work/records.csv --out /app/work/lang-matrix \
    --expected-languages en,pt
```

脚本以 Skill 根目录为工作目录，先 `cd /skills/weekly-skill` 再运行；若平台安装路径不同，以实际 Skill 根目录替换。

`--input` 支持 `.csv/.tsv/.json/.jsonl` 单文件，或按排序扫描的目录；目录中 `case.json`、`task.md`、`resources.yaml` 自动跳过。`--expected-languages` 可选，仅在案例明确声明目标语种时使用；不传则只做“缺原文/孤立版本”检查，不臆测缺失语种。

退出码：`0` 完成且无问题；`2` 完成但有问题（含空输入）；`1` 输入不可用（路径缺失、无可解析记录文件、参数非法）。退出码 `2` 不是运行失败，需阅读 `issues.csv`。

需要逐字核对引文时：

```sh
python3 scripts/source_index.py verify --index /app/work/source-index.json \
    --claims /app/work/claims.json --out /app/work/quote-check.json
```

`claims.json` 形如 `{"evidence":[{"file":"paper.pdf","locator":"page:3","quote":"原文逐字片段"}]}`。该工具只验证逐字文本与文件哈希，不判断相关性、语种正确性或科学结论。

## 失败、空结果、权限与冲突

- **空结果**：保留空数组和 `input_empty`，说明扫描了哪些文件、哪些未解析；不补造文献。
- **语言标签与原文冲突**：以原文为准，记录 `language_invalid`/`language_unverified` 或人工判定，二者都写入报告。
- **翻译服务失败/限额**：记录服务名、错误类型、时间；改用人工或模型翻译并标注不确定性，不假装翻译成功。
- **原文不可得/无权限**：标为 `unavailable` 或 `permission_denied`，该条不作为已核证据；不得绕过权限读取。
- **版本冲突**：同一 `version_id` 出现不同语言/类型/DOI，保留全部记录并标 `version_conflict`，交人工判定，不按修改时间猜“最新”。
- **重复版本**：按 `work_id+version_id+language+version_type+DOI` 判精确重复；仅标题相似不算重复。
- **孤立版本**：`translated_from` 找不到目标时标 `orphan_version`；跨作品引用标 `orphan_cross_work`。

## 停止条件

- 每个案例的每个子问题都有“已找到证据 / 明确无结果 / 明确受限”三种状态之一，计数闭合；
- 新增查询不再改变候选集，或只剩无法访问的来源；
- 达到平台时限或请求上限前，先落盘可核部分；
- 高风险术语已完成回译或人工抽检，或已明确记录未完成。

停止不等于声称穷尽：报告写“已完成范围”和“未覆盖范围”。

## 禁止编造

不得编造文献、DOI、语种、版本类型、翻译服务、查询结果或人工复核。不得声称实时数据库覆盖、未见语种的结论或新的研究结论。不得把合成示例、标签或推测当作事实证据。所有数字与引文必须回到当前输入文件的实际内容；文件变化后旧引文失效。

## 限制与维护

- 脚本只做记录规范化与一致性检查，不做翻译、语种识别或语义相关性判定；这些由 Agent 基于原文完成。
- 内置语种表用于标签校验与常见名称映射，不等于完整 ISO 639 注册表；未识别代码会标 `language_unverified`，需人工确认。
- `versions.csv` 的 `row:`/`record:` 定位基于解析顺序，含引号换行的 CSV 物理行号可能与逻辑行不同；以 `container_locator` 与原文核对为准。
- 术语表与翻译日志由 Agent 维护，脚本不生成、不补全。
