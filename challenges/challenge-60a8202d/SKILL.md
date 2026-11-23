---
name: citation-tracing-graph
description: 从案例实际提供的引用边与论文元数据出发构建可回指的引文网络：校验方向与必填字段，计算入度出度与弱连通分量，在限深内给出种子到目标的最短引用路径，输出 DOI 与规范化标题加年份的身份合并候选，交付 graph.json、citations.csv、report.md、result.json；只使用快照内真实数据，不补造引用，不声称实时数据库或全球覆盖。
version: 1.0.0
---

# 引文追踪与关联文献发现：种子 → 方向感知扩展 → 逐跳路径 → 身份候选

本技能回答的是"这篇文献的来路和后续是什么、依据在哪"，不是"帮我搜一些相关论文"。
所有结论必须能落回输入文件中真实存在的引用边或真实存在的元数据；没有边就是没有边，
不靠常识补一条，不把共被引当作直接引用。

## 何时使用

触发：案例提供种子论文（DOI/标题/ID）以及引用边、参考文献表、施引文献表、论文元数据，
要求做前向/后向追踪、引用网络、路径解释、版本/身份去重、关联文献发现，或要求"顺藤摸瓜"
找到方法出处与后续改进。

不触发：只有主题词、没有种子也没有边表时，本技能不生成文献集；单篇全文精读、引文内容
语义分析、绕过权限抓取、普通关键词检索不在范围内。若案例只有标题列表，先说明缺少边或
标识符，只做可核对的元数据整理，并标记扩展不可执行。

## 输入

以 `/input` 下的实际文件为唯一事实依据，`/input/case.json` 只是索引入口与输出契约，不得
按文件名或领域标签假设内容。先读 `case.json` 与 `task.md`，再逐个打开真实边表与论文文件。

常见字段（大小写、下划线、连字符容错）：

| 用途 | 字段（含别名） |
|-|-|
| 案例标识 | `case_id` / `id` / `task_id` |
| 研究问题 | `research_question` / `question` / `topic` / `goal` |
| 种子 | `seeds` / `seed_papers` / `seed_ids` / `seed_dois` / `seed` |
| 引用边 | `citation_edges` / `edges` / `citations` / `references` |
| 论文元数据 | `papers` / `nodes` / `works` / `literature` |
| 边字段 | `source`、`target`、`direction`、`depth`、`source_db`、`evidence_file`、`evidence_locator` |
| 输出契约 | `output_contract` / `expected_output` / `schema` |

边表支持 CSV/TSV/JSON/JSONL。`direction` 只接受 `cites`（source 引用 target）与
`cited_by`（source 被 target 引用，即 target 引用 source）；其他写法按别名表归一，
无法归一的边丢弃并记入 issues，不得猜测方向。`depth` 是调用方给出的层级提示，
不是事实；实际可达性以 BFS 结果为准。

## 输出

工作目录 `/app/work`，最终产物 `/app/output`：

- `graph.json`：节点、去重后的引用边及逐条证据、弱连通分量、限深最短路径、
  身份合并候选、issues、统计。由脚本生成。
- `citations.csv`：每条唯一引用边 × 每条支撑证据一行，含方向、来源库、文件、定位符。
- `report.md`：研究问题与快照范围 → 种子 → 扩展与剪枝 → 路径解释 → 身份候选 →
  关联文献依据 → 空结果/冲突/缺口 → 停止条件 → 复现步骤。
- `result.json`：原样保留 `case_id`，并按 `/input/case.json` 的 `output_contract`
  逐字段映射真实结果。

`output_contract` 是动态契约，不是固定模板：逐项读取其字段名、类型、是否必需和说明；
即使字段名与本文档默认名不同，也按契约输出并保留原始键名。不得删除、改名或写死某题
字段；契约缺失时才使用本文档默认结构。禁止把 JSON Schema 描述本身当作答案。

## 六步工作流

1. **清点真实输入。** 运行 `source_index.py extract` 建立文件清单与文本定位，记录每个
   文件的哈希、可读性、边行数与论文条数。核对实际案例数与输入是否一致；缺失、损坏、
   无权限、PDF 无文字层分别记录，不假设"应该有 9 篇"或"应该有几条边"。
2. **确认种子论文。** 从 `case.json` 实际字段或 `task.md` 指定文献取种子，规范化 DOI；
   若种子只有标题，用实际元数据解析到节点，解析不到就标记 `seed_not_in_edges`。
   不得用相似标题顶替种子，不得把综述或任意高被引论文当种子。
3. **只用实际边做前向/后向多层扩展。** 前向沿 `cites` 找种子引用的方法与数据出处，
   后向沿 `cited_by` 找施引、改进与质疑；每层都保留原始记录。只按 `--max-depth` 限深、
   按 `--top-k` 截断输出路径，不按来源库或证据完整度做推断式剪枝；新预印本没有前向
   记录时如实写"快照内无前向边"，而不是推断"无人引用"。禁止从共被引凭空生成引用边。
4. **版本身份合并（只出候选）。** 先按规范化 DOI 分组，再按"规范化标题 + 年份"分组，
   输出重复/合并候选及成员证据（来源库、文件、定位符）；预印本、会议版、期刊版、
   增补版保持独立节点，由人确认，不自动合并。DOI 不同但标题年份相同，只提示复核，
   不宣告同一论文。
5. **逐跳解释路径。** 对每个种子，在限深内用 BFS 求最短路径，逐跳写明引用方向、
   来源库、`evidence_file` 与 `evidence_locator`，并区分直接引用（1 跳）与间接可达
   （≥2 跳）。同一对节点存在反向边时作为 `reciprocal_edges` 冲突报告，不自行选边。
   没有路径就写"快照内不可达"，不得拼接不同来源的边造链。
6. **关联文献只用实际信号，到边界停止。** 只有当输入确实提供共被引、文献耦合、作者/
   机构或数据集关联时，才据此给出平行工作，并逐条列出信号来源；没有信号就明确写
   "本快照无法做关联发现"。最后按 `output_contract` 生成 `result.json`，汇总状态、
   缺口、冲突、停止原因与复现命令；交付前逐项核对路径存在、计数闭合、引文可回指。

## 脚本命令

```bash
# 1) 索引实际输入，记录可读性与定位
python3 scripts/source_index.py extract --input /input --out /app/work/source-index.json

# 2) 构建引用图（种子可用逗号分隔，也可指向种子 CSV/JSON）
python3 scripts/citation_graph.py --input /input --out /app/work/graph \
  --seeds "<从 case.json 读取的真实种子>" --max-depth 3 --top-k 50

# 3) 需要时校验逐字引文（file / locator / quote 数组）
python3 scripts/source_index.py verify --index /app/work/source-index.json \
  --claims /app/work/claims.json --out /app/work/quote-check.json
```

脚本只读本地文件、只用 Python 3 标准库、不联网、输出确定（相同输入相同结果）。
`--out` 是目录，写 `graph.json`、`citations.csv`、`issues.csv`。退出码：0 正常；
2 存在 error 级 issue（边因缺字段/方向非法/缺 `evidence_locator` 被丢弃、坏 JSON/坏行、
文件不可读）、种子无邻接或图为空（仍产出并标注）；1 输入路径不存在或无任何可读文件。
报告与 `result.json` 由执行者按实际结果撰写，脚本不生成结论。

## 失败、空结果、权限与冲突

| 情况 | 处理 | `status` |
|-|-|-|
| 输入目录不存在 / 无 CSV/TSV/JSON/JSONL | 停止，说明实际检查了什么；不虚构图 | `blocked` |
| 有边但种子不在任何边中 | 保留种子节点，输出 `seed_not_in_edges`，路径为空并解释 | `partial` |
| 完全没有合法引用边 | 产出空图 + issues，明确"快照内无可用引用关系" | `partial` |
| 方向缺失或非法 | 丢弃该边并逐条记录，不用默认方向补齐 | `partial` |
| 缺少 `evidence_locator` | 丢弃该边并记 error `missing_evidence`；绝不用 `row:N`/`item.key[i]` 回填 | `partial` |
| 缺少 `source_db`/`evidence_file` | 边保留，`issues.csv` 标 warning `missing_evidence`，报告中降低证据等级 | `partial` |
| 同一对节点双向都有边 | 记 `reciprocal_edges`，两条都保留，交人工核验 | `partial` |
| DOI 缺失、标题大小写/副标题/作者顺序不一致 | 规范化后仍不一致就分列；只给合并候选，不合并 | `ok` |
| 预印本无前向引用、数据库限流或无权限 | 写"快照边界/权限缺口"，不推断他人引用情况 | `partial` |
| 撤稿、更正、增补版 | 作为独立版本节点 + 冲突/版本说明，不悄悄替换原记录 | `partial` |
| 同名不同文 | 用 DOI/年份/作者/来源定位拆分；无法判定则并列候选 | `ok` |

## 停止条件

满足任一即停止扩展：达到调用方 `--max-depth`；没有新的可回指边；输入文件读尽或达到
案例给定的时间/数量上限。停止时写明停在哪一层、路径是否被 `--top-k` 截断、还有哪些
方向未覆盖。不得声称"已穷尽全部引用""全球覆盖""实时检索"，
也不得声称经过人工双人复核，除非实际发生并留有记录。

## 禁止编造

不生成不存在的 DOI、标题、年份、作者、引用边或定位符；不把常识中的经典文献塞进图；
不把共被引/主题相似写成直接引用；不用摘要或标签替代实际边表；不伪造数据库状态、
接口返回、评审意见或运行统计。任何推断必须标注"推断"并给出所依据的实际字段。

## 自查

- `python3 scripts/citation_graph.py --input /input --out /app/work/graph --json`
  复跑结果一致；`citations.csv` 行数等于各边证据数之和。
- 每条保留边都有输入提供的 `evidence_locator`；缺 `source_db`/`evidence_file` 的边
  已在 `issues.csv` 标 `missing_evidence`（`graph.json` 本身不含该状态字段）。
- 每条路径的每一跳都能在 `citations.csv` 找到同一对节点及对应定位符。
- `result.json` 覆盖 `output_contract` 全部字段，`case_id` 原样，`status` 与实际相符。
- 详细规则见 [references/method.md](references/method.md)，字段映射见
  [references/output-contract.md](references/output-contract.md)，逐项自检见
  [references/checklist.md](references/checklist.md)，合成示例见
  [examples/example.md](examples/example.md)（非官方案例）。
