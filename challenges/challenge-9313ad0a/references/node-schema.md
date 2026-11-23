# plan.json 节点与关系规范

## 顶层

```json
{
  "case_id": "from case.json",
  "title": "导图标题",
  "purpose": "用途（理解/规划/写作准备/汇报）",
  "audience": "目标读者",
  "root": {"id": "r", "label": "整理对象", "type": "concept"},
  "nodes": [],
  "edges": [],
  "contract_fields": {},
  "uncertainty": [],
  "change_log": []
}
```

## 节点

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 唯一，建议 `n1`… |
| `label` | 是 | 4–40 字名词短语或明确命题 |
| `type` | 是 | `question` / `method` / `evidence` / `result` / `conclusion` / `task` / `risk` / `concept` |
| `parent` | 是（根除外） | 父节点 id |
| `confidence` | 是 | `fact` / `summary` / `inference` |
| `evidence.anchor` | fact/summary 必填 | 来自 `sources.json` 的锚点，如 `doc.1 p.2 sec.1 para.3` |
| `evidence.quote` | fact/summary 必填 | 原文逐字片段，10–200 字 |
| `basis` | inference 必填 | 推断依据：引用哪些锚点、做了什么归纳 |
| `aliases` | 否 | 同一概念的别名数组 |

## 关系

| 字段 | 必填 | 说明 |
|---|---|---|
| `from` / `to` | 是 | 节点 id |
| `relation` | 是 | `causes` / `depends_on` / `supports` / `contradicts` / `compares` / `precedes` / `cites` / `part_of` |
| `confidence` | 是 | `fact` / `inference` |
| `basis` | inference 必填 | 关系依据 |
| `evidence` | 否 | 支撑该关系的锚点与引文 |

## 自检规则

1. 节点 id 唯一，`parent` 必须存在，除根外全部可达。
2. 层级 3–5 层，单层同类不超过 9 个。
3. `fact` / `summary` 节点的引文必须能在 `sources.json` 对应锚点文本中找到（忽略空白与全半角差异后子串匹配）。
4. `inference` 必须有 `basis`，否则标为 `unverified`。
5. 关系两端存在；`causes` / `precedes` / `depends_on` 不允许成环。
6. 同一 `label` 不得重复；同义写进 `aliases`。
