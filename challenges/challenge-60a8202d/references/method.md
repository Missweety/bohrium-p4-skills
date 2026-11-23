# 方法：方向感知的引文图与身份候选

本文只描述脚本 `scripts/citation_graph.py` 实际执行的规则。脚本不判断科学相关性，
也不补全缺失边；它把"输入里有什么"整理成可复核的结构。

## 1. 输入解析

- 接受 `--input` 为目录或单个文件；目录递归读取 `.csv/.tsv/.json/.jsonl`，按路径排序，
  保证确定性。隐藏文件跳过。单个 JSON 上限 20MB。
- JSON 对象优先识别数组键：边 `citation_edges/edges/citations/references/citation_records/
  edge_list/links`，论文 `papers/nodes/works/literature/paper_records/bibliography/paper_meta`，
  种子 `seeds/seed_papers/seed_ids/seed_dois/seed`。也接受顶层数组、单条边对象或单篇论文对象。
- 字段名归一：转小写，空格/连字符转下划线。边字段别名包括
  `from/citer/citing` → `source`，`to/cited/cited_paper` → `target`，
  `db/database/provider` → `source_db`，`file/source_file` → `evidence_file`，
  `locator/position` → `evidence_locator`。
- 文件内部定位符：CSV/TSV 为 `row:N`（含表头的物理行号），JSONL 为 `line:N`，
  JSON 为 `item.<key>[i]`，只用于 `issues` 与 `graph.json.input` 的排查，**不是**
  引用证据的 `evidence_locator`。证据定位符只采用输入记录自带的
  `evidence_locator`，缺失即丢弃该边，不把内部定位符回填进去。

## 2. 必填与方向校验

| 字段 | 要求 | 违规处理 |
|-|-|-|
| `source` | 非空 | 丢弃，`missing_required_field`（error） |
| `target` | 非空 | 丢弃，`missing_required_field`（error） |
| `direction` | 归一后 ∈ {cites, cited_by} | 丢弃，`invalid_direction`（error） |
| `depth` | 正整数；空则 1 | 非法值告警并用 1 |
| `source_db` | 建议必填 | 保留，`missing_evidence`（warning） |
| `evidence_file` | 建议必填 | 缺省回退到边所在文件（真实读取路径），`missing_evidence`（warning） |
| `evidence_locator` | 必填 | 缺失即丢弃，error `missing_evidence`；不用 `row:N`/`item.key[i]` 回填 |

方向语义固定如下，不做"按常识推断"：

| 输入 | 含义 | 规范化有向边 |
|-|-|-|
| `source=A,target=B,direction=cites` | A 引用 B | A → B |
| `source=A,target=B,direction=cited_by` | A 被 B 引用 | B → A |

同一对节点在两条记录里出现相反方向时，两条都保留并报 `reciprocal_edges`。
自环保留、度数为 0 并报 `self_loop`。

## 3. 标识符与身份键

- DOI：去 `https://doi.org/`、`http://dx.doi.org/`、`doi:` 前缀，去尾部标点，转小写；
  必须匹配 `^10\.\d{4,9}/\S+$` 才视为 DOI，否则当作普通引用串。
- 节点键：有 DOI 用 `doi:<doi>`；无 DOI 但有 id 用 `ref:<小写压缩串>`；只有标题用
  `title:<规范化标题>|<年份或 na>`。
- 标题规范化：NFKC、转小写、标点替换为空格、合并空白。用于别名解析与身份候选；
  原始标题始终保留在 `nodes[].title`。
- 别名：论文的 DOI、原始 id、标题都注册为节点别名；同名不同 id 冲突时只保留首个映射
  并报 `alias_collision`，不静默覆盖。

## 4. 图指标

- 唯一边：按规范化 `(citer, cited)` 合并，多个来源库/定位符的支撑证据全部保留在
  `edges[].evidence`。度数在唯一边上计算，不重复计同一关系。
- 出度 = 该文献在快照内引用了多少篇；入度 = 被快照内多少篇引用。两者都只是快照计数，
  不是真实世界被引量。
- 弱连通分量：把有向边当无向边做并查集，按成员最小节点键排序编号 `C001...`。
  分量大不代表重要，只说明快照内连成一片。

## 5. 路径与剪枝

- 对每个种子，分别在正向图（citer→cited）和反向图（cited→citer）上做 BFS，
  最大跳数 `--max-depth`（默认 3），每跳按邻接节点键排序，保证最短路径唯一且可复现。
- 只输出最短路径；同一 (seed,target,mode) 不输出次短路径。默认最多保留 `--top-k=50`
  条（按跳数、种子、目标排序），截断时记 `paths_truncated`。
- 每跳字段：`from`、`to`、`relation`（正向 `cites`，反向 `cited_by`）、`traversal`、
  `canonical_edge`、`source_db`、`evidence_file`、`evidence_locator`、
  `supporting_evidence`（该边有几条支撑记录）。
- 剪枝规则：仅由 `--max-depth` 限深、`--top-k` 截断路径；此外在节点无未访问邻居或
  输入文件读尽时自然停止。不按来源库或证据完整度做推断式剪枝，也不从共同作者、
  主题词或共被引生成新边。没有路径就输出空路径列表并说明原因。

## 6. 重复与身份合并候选

只输出候选，`action` 固定为 `review_only`，不改变图节点：

| 类型 | 条件 | 说明 |
|-|-|-|
| `doi_exact` | 多个节点共享同一规范化 DOI | 通常已被节点键合并；若出现说明别名/元数据冲突 |
| `title_year_exact` | 规范化标题相同且年份相同，但节点键不同 | 预印本/会议版/期刊版的典型候选 |

成员附带 `node_id/doi/title/year/source_dbs`。标题相同但年份不同不列为候选，仅在报告中
提示"可能为不同版本或不同工作，需人工判定"。合并证据必须能回到 `papers` 或 `edges`
的原始定位符；脚本不生成合并后的文献记录。

## 7. 关联文献信号

脚本不推断关联文献。只有当输入实际提供下列结构时，执行者才能在报告中逐条列出并标注
依据：共被引（两篇同时出现在某施引文献的参考文献表中）、文献耦合（两篇共享参考文献）、
作者/机构共现、数据集或任务共现。没有这些输入就写"本快照无关联信号"，不得用标题相似
替代方法相关。

## 8. `graph.json` 结构

```json
{
  "generated_by": "citation_graph.py",
  "scope_note": "Only supplied edges ...",
  "input": {"root": "...", "files": ["..."], "edge_records_read": 0},
  "seeds": [{"raw": "...", "node_id": "...", "present_in_edges": true}],
  "stats": {"nodes": 0, "edges_unique": 0, "components": 0, "paths": 0,
            "merge_candidates": 0, "edges_dropped": 0,
            "issues": {"error": 0, "warning": 0, "info": 0}},
  "nodes": [{"node_id": "...", "doi": "", "title": "", "year": null,
             "source_dbs": [], "is_seed": false,
             "in_degree": 0, "out_degree": 0, "degree": 0, "component_id": "C001"}],
  "edges": [{"edge_id": "E0001", "citer": "...", "cited": "...",
             "relation": "cites", "evidence_count": 1,
             "evidence": [{"source_db": "", "evidence_file": "", "evidence_locator": "",
                            "as_provided_source": "", "as_provided_target": "",
                            "as_provided_direction": "", "depth": 1}]}],
  "components": [{"component_id": "C001", "size": 1, "nodes": [], "seed_nodes": []}],
  "paths": [{"seed": "...", "target": "...", "mode": "forward", "length": 1,
             "hops": [{"from": "...", "to": "...", "relation": "cites"}]}],
  "merge_candidates": [{"type": "title_year_exact", "key": "...",
                        "action": "review_only", "members": []}],
  "issues": [{"severity": "warning", "code": "missing_evidence",
              "detail": "...", "file": "", "locator": ""}]
}
```

`citations.csv` 每行对应一条边的单条证据；同一边多来源时多行共享 `edge_id`。
`issues.csv` 与 `graph.json.issues` 内容一致，便于筛选。

## 9. 合成示例（非官方）

输入边（虚构标识符）：

```csv
source,target,direction,depth,source_db,evidence_file,evidence_locator
10.9999/example.seed,10.9999/example.mid,cites,1,crossref,edges.csv,row:2
10.9999/example.far,10.9999/example.mid,cited_by,2,europepmc,edges.csv,row:3
```

`direction=cited_by` 的第二行规范化为 `mid → far`。以 seed 为起点、深度 3，
可得到 `seed → mid`（1 跳）和 `seed → mid → far`（2 跳），每跳都带 row 定位符。
这里只演示方向与路径，不对应任何真实论文。

## 10. 已知限制

- 只覆盖输入快照；不连接实时数据库，不能据此判断"全球是否只有这些引用"。
- 无 DOI 且标题略有差异的论文可能保持为两个节点，需要人工判定。
- 作者顺序、副标题、翻译标题、撤稿/更正关系需要人工复核，脚本只给候选。
- 路径是图上的最短可达，不等于"学术上最可信的引用链"；可信度需结合证据完整度判断。
- CSV 的 `row:N` 是物理行号；引号内换行时逻辑记录与行号不对应，复核时应按定位符
  打开原文件确认。
