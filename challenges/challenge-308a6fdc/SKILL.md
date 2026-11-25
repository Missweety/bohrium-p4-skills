---
name: manuscript-evidence-writer
description: 从给定科研材料（实验记录、数据表、图表、参考文献、补充材料）生成可编辑的论文稿件章节，并把每一条事实性陈述绑定到具体材料位置，产出章节稿、事实—来源映射表与一致性审计报告。适用于按学科模板撰写摘要/引言/方法/结果/讨论/结论，或补齐缺失章节；不适用于无材料的自由创作、代写数据或纯语言润色。
version: 1.1.0
license: MIT
---

# 学术论文写作：完成产物，也保留来源

把"写一篇论文"拆成 **材料索引 → 章节契约 → 逐段写作（每句可回溯）→ 机器审计 → 可编辑交付**。
核心主张：稿件里的每个数字、单位、样本量、图注编号、引用都必须指回材料；指不回去的，
只能删掉、降级为一般性陈述，或明确写进"待人工确认"。

## 何时使用

触发：用户给出研究材料（csv/xlsx/docx/pdf/图片/实验记录/参考文献）并要求产出论文的某个章节
或整篇初稿，或要求"按期刊模板补齐章节"、"把结果写成正文"、"结果段 + 图注"。

不触发：没有任何材料、要求凭空生成研究结论；纯语言润色（改用 polish 类 Skill）；
纯文献检索。遇到这类请求，先说明缺少什么材料再决定是否降级执行。

## 输入

`/input/case.json`（回退 `./case.json`、`/app/input/case.json`）与同目录 `task.md`；材料由题面提供，
也可能以 `materials: [{"path","content"}]` 内联在 case.json 里。字段名不固定，**不要凭标签猜内容**，
先跑 `init` 做宽松识别，再确认体裁、受众、语言与字数/格式约束。

`output_contract` 支持三种写法并统一归一化为字段名列表：
`["paper","source_map"]`、`{"fields": [...]}`、`{"paper": "string", ...}`。

## 执行流程

```bash
SKILL_DIR=/skills/weekly-skill          # 绝对路径；任意 cwd 均可运行
mkdir -p /app/work
```

1. **契约**：`python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out /app/work`
   → `contract.json`（case_id、contract_fields、任务原文、task.md 文本、材料声明）。
2. **证据索引**：`python3 "$SKILL_DIR/scripts/kernel.py" index --out /app/work`
   自动使用 case.json 的 materials / 内联 content，缺省时找 `materials/ input/ data/ resources/`；
   也可显式 `--materials <路径...>`。
   → `evidence.json`（文件清单、字符数、sha1、可读性）+ `corpus.txt`（统一文本）。
   docx/xlsx/pdf 内置抽取；扫描版 PDF 抽不出文字标 `[unreadable:`，**不得凭领域常识补内容**。
3. **材料→事实卡**：为每个可引用事实建一条 `source_map` 记录：
   `{"claim","value","unit","source_path","locator"}`。冲突（同一指标两处数值不同）**两边都保留**
   并写进 `uncertainty`，不擅自选一个。
4. **章节契约**：按 task.md/学科模板写 `work/section_template.json`（章节名、min_words、
   必须包含的声明字段）。模板缺项要显式补 `missing: true`，不要静默省略。
5. **逐段写作**：输出 `work/draft.json`（schema 见 `references/output-contract.md`）：
   每个段落先列"本段要用的事实卡编号"，再写句子；含事实的句子登记 `source_map`。
   没有事实卡支撑的内容只能写成方法性或过渡性表述，且不得出现具体数值。
6. **渲染**：`python3 "$SKILL_DIR/scripts/kernel.py" build --draft /app/work/draft.json --out /app/work`
   → `manuscript.md`（可编辑正文，章节/图表题注/参考文献由 plan 渲染）。
7. **审计**：
   `python3 "$SKILL_DIR/scripts/section_audit.py" --draft /app/work/manuscript.md --map /app/work/source_map.json --template /app/work/section_template.json --corpus /app/work/corpus.txt --plan /app/work/draft.json --out /app/work/audit.json`
   `verdict=fail` 只用于**证据造假**（数字在材料中查无此值、引用无法解析、source_map 指向不存在的
   文件）；章节偏短、缺声明、未登记占位符/冲突、图表题注不全只记 warning，不阻断交付。
8. **数值/引用守恒**：`python3 "$SKILL_DIR/scripts/kernel.py" verify --text /app/work/manuscript.md --evidence-dir /app/work --out /app/work`
   → `claims.json`；`unsupported_numbers` 与 `citations_not_in_sources` 为 0 才可交付。
   数字按**数值相等**比较（`12.40` = `12.4`，带 `%` 不影响），不做子串匹配。
9. **产出**：`python3 "$SKILL_DIR/scripts/kernel.py" emit --draft /app/work/draft.json --contract-dir /app/work --work-dir /app/work --out /app/output`
   写 `result.json`，并落盘 `manuscript.md`、`source_map.json`、`audit.json`、`claims.json`。
   契约字段缺失时自动补 `null`、`status=partial` 并在 `limits` 说明，退出码 1（不谎报成功）。
10. **自查**：`python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract-dir /app/work`
    校验契约字段、产物存在且非空、source_map 结构、status/limits 一致；必须 PASS。

## 写作规则（按评分维度对齐）

| 维度 | 规则 |
|-|-|
| 写得实 | 结果段只描述材料里有的数值与趋势；不把相关写成因果，不补做未做的实验 |
| 引得对 | 每条引用必须支撑它所在的句子；作者/年份/DOI 只能来自材料，缺就标 `missing_citation` |
| 全得起来 | 按模板检查章节、图表、参考文献、数据可得性声明；缺项写 `missing: true` 并在正文标注 |
| 改得动 | 使用 Markdown 标题层级；图注用 `Figure N.` / `图 N`；不把正文压成一段 |

句式约束：方法段用过去时被动/主动均可但全篇统一；结果段避免 `significant` 除非材料给了检验
结果与 p 值；讨论段区分"本研究观察到"与"文献报告"。

## 硬性禁止

- 不新增材料外的数字、样本量、p 值、图表或参考文献。
- 不伪造"已运行实验/已统计分析/已获得伦理批准"等状态。
- 不把缺失章节写成占位符号而不说明；不提交预制答案。
- 不使用模型记忆里的具体文献条目充数。

## 输出

`/app/output/result.json` + `manuscript.md` + `source_map.json` + `audit.json`；
未完成部分在 `limits` 说明，无法确认项进 `uncertainty`。契约见 `references/output-contract.md`。

## 异常与降级

| 情况 | 处理 |
|-|-|
| case.json 缺失/非法 JSON | `init` 退出 1，写 `contract.json` 标 blocked；不猜任务 |
| 无材料文件 | `index` 退出 1 并说明缺什么；不生成无来源正文 |
| 材料缺失/不可读 | `status: partial` 或 `blocked`，列出缺哪个文件、影响哪一章 |
| 数据与图注冲突 | 保留两值，标 `conflict`，正文中立表述 + 待核清单 |
| 契约字段无法产出 | 补 `null` + `status=partial` + `limits`，`emit` 退出 1 |
| 材料超长 | 先按章节建索引，只抽取与本章相关的事实卡 |
| 无法判断 | 写 `uncertainty`，不猜 |

## 文件说明

- `scripts/kernel.py`：契约识别、材料抽取/内联、渲染、数值/引用守恒、产出与自查（仅标准库）。
- `scripts/section_audit.py`：章节完整性 + 数值绑定 + 证据审计。
- `references/output-contract.md`：默认输出字段与 draft.json schema；题面契约优先。
- `references/section-template.md`：常见学科章节模板与最低要素。
- `references/example.md`：示意输入/输出（示例，非正式案例答案）。

## 最小调用示例

```bash
SKILL_DIR=/skills/weekly-skill
python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out /app/work
python3 "$SKILL_DIR/scripts/kernel.py" index --out /app/work
python3 "$SKILL_DIR/scripts/kernel.py" build --draft /app/work/draft.json --out /app/work
python3 "$SKILL_DIR/scripts/section_audit.py" --draft /app/work/manuscript.md \
  --map /app/work/source_map.json --corpus /app/work/corpus.txt --out /app/work/audit.json
python3 "$SKILL_DIR/scripts/kernel.py" emit --draft /app/work/draft.json \
  --contract-dir /app/work --work-dir /app/work --out /app/output
python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract-dir /app/work
```

## 改动记录

### 1.1.0（以 05_skills 为基线；05_skills_v2 仅吸收经实测确认的改动）

比较结论（合成夹具实跑，见 `07_submissions/iter_1.1.0_report.md`）：

- **吸收** v2 的数字数值比较：v1 用字面子串判断（`n not in corpus`），draft 写 `12.45%`
  而材料是 `12.45` 时被误报 1 条（假阳性），也无法区分 `12.4%` 与 `12.45%`；
  v3 按数值相等比较并忽略 `%`，实测 A 夹具 `[]`、B 夹具 `["12.4%"]`（与 v2 一致）。
- **吸收** v2 的可读性判定：v1 以 `text.startswith("[")` 判 unreadable，材料以 `[` 开头即被误判；
  v3 用 `[unreadable:` 前缀，实测 C 夹具未读文件从 1 个降为 0。
- **吸收** v2 的自动材料发现、内联材料、`build` 渲染、`manuscript.md` 兜底、契约字段缺失返回非 0，
  以及 v3 延续的按章节自身正文计算字数（实测 D 夹具 Introduction=96）。
- **吸收** v2 的审计驱动状态：v1 `emit` 直接沿用 draft 的 `status=ok`，即使 separate verify 已判
  `review`；v3 在 audit fail 时把状态降为 `partial` 并在 `limits` 写明不可回溯的数字（实测 B 夹具）。
- **不吸收** v2 的 fail-closed 审计：v2 把缺声明、未登记占位符/冲突、图表题注不全、
  章节顺序变化都归入 `problems` 并判 fail（实测缺 `data_availability` 时 `verdict=fail`、rc=1）；
  v3 只把**证据造假**判 fail，其余记 warning（同一夹具 `verdict=review`、rc=0）。
- **不吸收** v2 的列表契约处理：`output_contract` 为列表时 v2 `emit` 输出
  `missing_contract_fields=['fields']`、`check` 返回 1（内容完整也被判失败）；v3 统一归一化三种写法。
- v2 的 `index` 在 case.json 显式给出 materials 时仍追加基础目录，同一文件被索引两次
  （实测 3 个文件记 6 条）；v3 按 realpath 去重。
- v3 不声称任何正式案例分数；仅报告本地夹具与 validator 结果。
