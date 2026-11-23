---
name: coverage-audit-and-gap-analysis
description: 对题面给定的已知文献参考集与检索导出记录做逐条覆盖审计：先冻结参考集，再按 DOI 精确或标题+年份+作者 Jaccard 规则判定 hit/miss/uncertain，输出覆盖率、遗漏率、可按证据分类的漏检清单、补检模板与残余遗漏。适用于检索覆盖率核查、系统综述补检、检索策略复盘；不声称全球召回，不把未执行补检写成已执行，不编造文献或命中数。
version: 1.0.0
license: MIT
---

# 检索覆盖率与遗漏分析：算得清、指得出、补得回

交付物不是"检索到很多文献"的叙述，而是一份**可复算的覆盖审计**：

参考集（分母）→ 匹配规则 → 逐条状态 → 覆盖率/遗漏率 → 漏检分类 → 补检与边际收益 → 残余遗漏。

核心主张：**分母只能来自可核对的参考集；每条遗漏要能指到具体查询/字段/来源/时间窗；
补检是否减少遗漏必须由新增命中与参考集对齐来证明。** 题面未给的证据一律不补。

## 何时使用

触发：用户给出研究问题、参考集（综述/指南/专家清单/已有系统综述的纳入文献）与检索导出记录，
要求"算覆盖率"、"找漏了哪些文献"、"分析漏检原因"、"设计补充检索"、"复盘检索策略"；
或题面带 `output_contract`、`reference_set`、`hits`/`records`、`miss_category` 等字段。

不触发：只要求做主题综述或翻译；要求替代数据库检索接口或购买全文；
要求给出"全球/某库完整召回"结论；输入没有可核对参考集却要求一个覆盖率数字。

## 输入

执行时先读 `/input/case.json`（回退 `./case.json`、`/app/input/case.json`）、同目录 `task.md`，
再按实际文件读取材料；工作目录 `/app/work`，最终产物写 `/app/output`。

| 语义 | 常见字段/文件 |
|-|-|
| 案例标识 | `case_id` |
| 参考集 | `reference_set`、`references`、`refs`、`gold_set`、`known_set`，或 `*ref*.csv/json` |
| 命中记录 | `hits`、`records`、`results`、`candidates`、`search_results`，或 `*hit*.csv/json` |
| 漏检类别（可选） | `miss_category`、`category` |
| 补检记录（可选） | `supplements`、`supplemental_search` |
| 输出契约 | `output_contract`（字段逐个回填，不写死） |

参考集最小字段：`ref_id, doi, title, authors, year, include_reason, unavailable, miss_category`。
命中记录最小字段：`record_id, doi, title, authors, year, query_id, source`。

若 `reference_set` 与 `hits` 直接以数组嵌在 `case.json` 中，脚本会优先读取；
否则在 `/input` 目录内按文件名与列名自动发现，识别不了时用 `--refs/--hits` 显式指定。
字段名大小写、空格、连字符不敏感；中英文列名均可识别。缺列按空值处理并在 `limits` 说明，
**不得用推测值补齐**。

## 输出契约（动态）

`/input/case.json` 的 `output_contract` 是权威字段表。执行步骤：

1. 读取 `output_contract`，记录字段名与要求的类型/含义；不要套用固定模板。
2. 运行 `python scripts/coverage_audit.py --input /input --case /input/case.json --out /app/output`，
   脚本会按别名把核心结果映射到契约字段。
3. 打开 `/app/output/result.json` 检查：每个契约字段是否存在；`contract_mapping.unresolved_fields`
   中列出的字段是本次没有证据支持的内容，保持 `null` 并在 `limits`/`uncertainty` 说明，
   **不得编造内容填满**。
4. 契约字段名与默认字段差异较大时，按 `references/output-contract.md` 的别名表补充映射；
   仍无法对应时，在 `changes` 记录差异，不改变事实。

默认交付：`coverage.csv`、`misses.csv`、`report.md`、`result.json`，以及结构化 `audit.json`。

## 六步工作流（严格按序）

### 第 1 步：冻结参考集版本

```bash
python scripts/source_index.py extract --input /input --out /app/work/source-index.json
```

- 记录每个输入文件的路径、sha256、可读性；确认参考集条数、命中记录条数、去重前数量。
- 逐条核对 `ref_id`、DOI、标题、作者、年份；`unavailable`（撤稿、无法获取全文、重复）单独列出，
  **不静默删除**，从覆盖率分母中排除时写明理由。
- 把冻结结果写入 `/app/work/reference-frozen.json`：文件名、sha256、条数、不可用清单。
- 同一条记录出现多个版本（预印本/正式版）时保留并链接，不按"名字像"合并。

### 第 2 步：定义并记录匹配规则

固定规则（脚本内置，禁止临时放宽）：

1. **DOI 精确**：去前缀、统一小写后完全相等 → `hit`（`match_method=doi`）。
2. 否则 **规范化标题完全相同 + 年份相同 + 作者姓氏集合 Jaccard ≥ 0.85** → `hit`
   （`match_method=title_year_author`）。标题规范化只保留字母与数字，忽略大小写、空格、标点。
3. 标题相同但年份/作者缺失、年份冲突、作者 Jaccard 不足、标题近似（字符二元组 Jaccard ≥ 0.90）
   且年份相同 → `uncertain`，**不计入命中分子**。
4. 其余 → `miss`。

把规则、阈值、执行时间、输入哈希写入 `/app/work/matching-rule.json`。规则一旦用于正式比对，
不得在看到结果后修改；确需修改则整批重跑并记录 `changes`。

### 第 3 步：逐条比对

```bash
python scripts/coverage_audit.py --input /input --case /input/case.json --out /app/output
```

- 每条参考记录必须得到且只得到一个状态：`hit` / `miss` / `uncertain`。
- `uncertain` 单独报告，不允许"算作命中"来提高覆盖率。
- 输出分子、分母、覆盖率、遗漏率、不确定率与公式；同时给出"含全部参考集"的覆盖率以便复核。
- 参考集重复候选只标记、不自动合并；DOI 冲突单独标记。

### 第 4 步：漏检分类只用证据可支持的类别

- 类别只能来自：参考集自带 `miss_category`，或依据检索导出中的**可核对事实**做出的分类
  （查询词未覆盖同义表达、检索字段过窄、时间窗截断、来源库未收录、记录标识异常、不可用）。
- 每条分类必须带证据：`query_id`、检索式原文、字段、时间窗或来源库；没有证据就写 `unlabeled`。
- 需要补充分类时，写 `/app/work/classify.csv`（`ref_id,miss_category,evidence,note`），再重跑：

```bash
python scripts/coverage_audit.py --input /input --classify /app/work/classify.csv \
  --case /input/case.json --out /app/output
```

- 禁止使用"数据库覆盖不足""关键词不好"这类无法落到查询式的泛泛归因。
- 不因为"没找到"就判定"不相关"；遗漏与不相关是两件事。

### 第 5 步：补检查询与边际收益

- 按遗漏类别设计新查询或新来源，记录：`miss_category, proposed_query, executed, new_hits, yield, stop_reason`。
- **只有实际执行过的查询才能写 `executed=true`**；新增命中必须来自真实导出。
- 新增命中能用 `recovers_ref_ids` 映射回参考集时，才计算残余遗漏；只有数量没有映射时，
  残余遗漏记为不可计算并说明原因。
- 输出模板（`executed=false`）表示"拟定但未执行"，报告中必须保持这一语义。

```bash
python scripts/coverage_audit.py --input /input --supplements /app/work/supplements.csv \
  --case /input/case.json --out /app/output
```

### 第 6 步：闭环抽检与残余遗漏，然后停止

- 对 `miss` 与 `uncertain` 做人工抽检（建议全查；量大时至少 10% 且不少于 5 条），
  复核匹配判定与分类证据，记录抽检数、一致数、不一致项及裁决。
- 说明残余遗漏的规模与原因；不能计算时明确写"不可计算"。
- 更新 `report.md` 与 `result.json` 的 `uncertainty`、`limits`、`changes`。

## 脚本

| 命令 | 作用 |
|-|-|
| `python scripts/source_index.py extract --input /input --out /app/work/source-index.json` | 建立文件索引（哈希、可读性、文本定位），不做相关性判断 |
| `python scripts/source_index.py verify --index ... --claims ... --out ...` | 校验证据引文与位置（可选，用于人工复核记录） |
| `python scripts/coverage_audit.py --input /input --out /app/output` | 自动发现参考集/命中记录，输出覆盖矩阵与报告 |
| `... --refs FILE --hits FILE` | 文件无法自动区分时显式指定 |
| `... --classify FILE` | 合并有证据的漏检分类（未提供类别的保持 `unlabeled`） |
| `... --supplements FILE` | 合并已执行/拟定的补检记录 |
| `... --case /input/case.json` | 读取 `case_id` 与 `output_contract`，生成映射后的 `result.json` |

脚本只用 Python 3 标准库、无网络、不修改输入；相同输入重复运行得到相同结果（不含时间戳）。
退出码：`0` 完成；`1` 输入无效；`2` 完成但数据不完整（缺命中文件、部分文件不可读等）。

## 异常与边界处理

| 情况 | 处置 |
|-|-|
| 参考集为空或无法识别 | `status=blocked`，不计算覆盖率；列出已检查的文件与原因 |
| 命中记录缺失 | `status=partial`，覆盖率记 `null`（不是 0）；所有参考记 `uncertain` 并说明 |
| 命中记录存在但为空 | 覆盖率按 0 计算，并注明"导出为空"而非"未提供" |
| 参考集含撤稿/无法获取全文 | 进入 `unavailable_records`，从分母排除并写明理由 |
| 参考集重复 | `duplicate_groups` 标记，不自动合并；报告提示人工裁决 |
| DOI 冲突但标题/年/作者一致 | 判 `hit` 并标 `doi_conflict=true`，提示版本/元数据冲突 |
| 年份缺失 | 判 `uncertain`，不猜年份 |
| 作者字段缺失或缩写异常 | 判 `uncertain`，不按标题单独命中 |
| 文件不可读/PDF 无文本 | 进入 `limits`；需要全文判断的条目标 `uncertain` |
| 权限不足或来源超时 | 记录为限制，不用推测结果替代；补检标 `executed=false` |
| 契约字段未知 | 保持 `null`，写入 `contract_mapping.unresolved_fields` 与 `limits` |
| 补检未执行 | 只输出模板，禁止写成已执行或遗漏已下降 |

## 停止条件

满足以下全部条件即可停止并交付：

1. 参考集版本已冻结，条数与不可用清单可核对；
2. 每个纳入分母的参考记录都有 `hit`/`miss`/`uncertain` 状态；
3. 每条 `miss` 有类别（含 `unlabeled`）与来源说明；
4. 补检记录区分 `proposed` 与 `executed`，边际收益与残余遗漏有结论或明确"不可计算"；
5. `coverage.csv`、`misses.csv`、`report.md`、`result.json` 已写入 `/app/output`，路径存在。

达到时间/请求预算上限仍未完成时，保存 `status=partial` 与已完成部分，写明未完成项，
不得用推测补全。

## 禁止编造

- 不得用检索结果反推参考集或分母；
- 不得把未命中文献当作不相关而移出清单；
- 不得编造 DOI、标题、作者、年份、查询式、命中数或数据库响应；
- 不得声称"全球召回""该库已穷尽"或"两位独立评审"（除非确有其事）；
- 不得把摘要、领域标签或文件名当作全文证据；
- 不得把未执行的补检写成已执行，不得在新增命中未对齐参考集时宣称覆盖率提升。

## 最小调用示例

见 [examples/example.md](examples/example.md)（**合成示例，非官方案例**）。方法细节、字段说明与
判定阈值见 [references/method.md](references/method.md)，契约映射见
[references/output-contract.md](references/output-contract.md)，交付前逐项核对
[references/checklist.md](references/checklist.md)。

## 限制

- 覆盖率只相对于题面给定的参考集，不代表任何数据库的全局召回。
- 匹配基于元数据，无法替代全文核对；标题/作者/年份缺失时只能给 `uncertain`。
- 作者姓氏集合对复姓、机构作者、全名与缩写混排的处理是启发式的，需人工抽检。
- PDF 文本抽取依赖 `pdftotext` 或 `pypdf`；扫描件需 OCR/人工查看，脚本不代替视觉核对。
- 漏检分类只复述输入或可核对证据，不推断未记录的检索策略。
- 不替代系统综述的正式纳排、质量评价或统计合并。

## 版本记录

- **1.0.0**（2026-11-23）首版：参考集冻结、DOI/标题+年份+作者匹配、覆盖矩阵、
  漏检分类、补检模板与残余遗漏、契约动态映射。
