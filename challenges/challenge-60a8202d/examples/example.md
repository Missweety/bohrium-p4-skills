# 最小调用示例（合成示例，非官方案例）

> 本页所有 DOI、标题、年份、来源库和数值均为虚构，仅用于说明接口与输出形状。
> 它们不是平台固定案例的答案，也不代表任何真实论文或真实数据库返回。

## 1. 输入

`/input/case.json`（合成）：

```json
{
  "case_id": "synthetic-example",
  "seeds": ["10.9999/example.seed"],
  "papers": [
    {"doi": "10.9999/example.seed", "title": "Synthetic Seed Paper", "year": 2020},
    {"doi": "10.9999/example.mid", "title": "A Synthetic Middle Work", "year": 2021},
    {"doi": "10.9999/example.far", "title": "A Synthetic Remote Work", "year": 2022}
  ],
  "citation_edges": [
    {"source": "10.9999/example.seed", "target": "10.9999/example.mid",
     "direction": "cites", "depth": 1, "source_db": "crossref",
     "evidence_file": "case.json", "evidence_locator": "item.citation_edges[0]"},
    {"source": "10.9999/example.far", "target": "10.9999/example.mid",
     "direction": "cited_by", "depth": 2, "source_db": "europepmc",
     "evidence_file": "case.json", "evidence_locator": "item.citation_edges[1]"}
  ],
  "output_contract": {"fields": ["case_id", "status", "paths", "citations", "limitations"]}
}
```

第二行的 `cited_by` 表示 far 被 mid 引用，规范化为 `mid → far`。

## 2. 调用

```bash
python3 scripts/source_index.py extract --input /input --out /app/work/source-index.json
python3 scripts/citation_graph.py --input /input --out /app/work/graph \
  --seeds 10.9999/example.seed --max-depth 3 --top-k 50
```

预期退出码 0，并在 `/app/work/graph/` 生成 `graph.json`、`citations.csv`、`issues.csv`。

## 3. 示意输出（节选，虚构）

`graph.json`：

```json
{
  "seeds": [{"raw": "10.9999/example.seed",
             "node_id": "doi:10.9999/example.seed", "present_in_edges": true}],
  "nodes": [
    {"node_id": "doi:10.9999/example.seed", "in_degree": 0, "out_degree": 1},
    {"node_id": "doi:10.9999/example.mid", "in_degree": 1, "out_degree": 1},
    {"node_id": "doi:10.9999/example.far", "in_degree": 1, "out_degree": 0}
  ],
  "edges": [
    {"edge_id": "E0001", "citer": "doi:10.9999/example.mid",
     "cited": "doi:10.9999/example.far", "evidence_count": 1},
    {"edge_id": "E0002", "citer": "doi:10.9999/example.seed",
     "cited": "doi:10.9999/example.mid", "evidence_count": 1}
  ],
  "paths": [
    {"seed": "doi:10.9999/example.seed", "target": "doi:10.9999/example.mid",
     "mode": "forward", "length": 1,
     "hops": [{"from": "doi:10.9999/example.seed", "to": "doi:10.9999/example.mid",
               "relation": "cites", "source_db": "crossref",
               "evidence_file": "case.json",
               "evidence_locator": "item.citation_edges[0]"}]},
    {"seed": "doi:10.9999/example.seed", "target": "doi:10.9999/example.far",
     "mode": "forward", "length": 2,
     "hops": [{"from": "doi:10.9999/example.seed", "to": "doi:10.9999/example.mid",
               "relation": "cites"},
              {"from": "doi:10.9999/example.mid", "to": "doi:10.9999/example.far",
               "relation": "cites", "source_db": "europepmc"}]}
  ],
  "merge_candidates": [],
  "stats": {"nodes": 3, "edges_unique": 2, "components": 1, "paths": 2,
            "merge_candidates": 0, "edges_dropped": 0}
}
```

`citations.csv`（节选）：

```csv
edge_id,citer,cited,relation,as_provided_source,as_provided_target,as_provided_direction,source_db,evidence_file,evidence_locator,depth
E0001,doi:10.9999/example.mid,doi:10.9999/example.far,cites,10.9999/example.far,10.9999/example.mid,cited_by,europepmc,case.json,item.citation_edges[1],2
E0002,doi:10.9999/example.seed,doi:10.9999/example.mid,cites,10.9999/example.seed,10.9999/example.mid,cites,crossref,case.json,item.citation_edges[0],1
```

按合成契约，`result.json` 至少包含：

```json
{"case_id": "synthetic-example", "status": "ok",
 "paths": ["<取自 graph.json.paths>"],
 "citations": {"artifact": "citations.csv", "edge_count": 2, "evidence_rows": 2},
 "limitations": ["合成示例仅含两条边，不代表真实覆盖"]}
```

## 4. 反例（同一脚本，坏输入）

```csv
source,target,direction,depth,source_db,evidence_file,evidence_locator
10.9999/a,,cites,1,db1,edges.csv,row:2
10.9999/a,10.9999/b,unknown,1,db1,edges.csv,row:3
10.9999/b,10.9999/d,cited_by,x,db2,,row:4
```

预期：退出码 2；前两行因缺 target / 方向非法被丢弃并写入 `issues.csv`；
第三行保留但报 `invalid_depth` 与 `missing_evidence`（缺 `evidence_file`）；
若某行 `evidence_locator` 为空，该边也会被丢弃并记 error `missing_evidence`，
脚本不会用 `row:N` 或 `item.key[i]` 回填。`graph.json` 仍生成，`status` 应为
`partial`，不得把丢弃的边补回来。

## 5. 说明

示例输出只证明接口、字段和可复现性。正式案例必须读取实际 `/input` 文件并按其
`output_contract` 生成 `result.json`；不得复制本页的虚构 DOI 或数值。
