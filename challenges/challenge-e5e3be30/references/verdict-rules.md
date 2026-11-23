# 四态判定规则（官方 v2 契约）

| 判定 | 含义 | 证据要求 | note 要求 | 允许强度 |
|-|-|-|-|-|
| supported | 材料原句直接支持整条论断（含比较方向、否定与条件） | ≥1 条 `relation=supports` 的逐字引文 | 可选 | strong / moderate |
| partially_supported | 只支持论断的一部分（范围/幅度/亚组/方向/条件），或来源间部分冲突 | ≥1 条支持性引文 | **必填**：哪一部分超出证据 | weak / moderate |
| contradicted | 材料原句直接否定该论断 | ≥1 条 `relation=contradicts` 的逐字引文 | **必填**：引文如何与论断相反 | strong / moderate / weak |
| insufficient_evidence | 材料范围内无法判断 | **必须为空** | **必填**：检索词、范围、为何不足 | none / weak |

## 判定顺序（避免误判）

1. 先确认论断的**全部成分**：主体、比较对象、方向、数值、时间窗、条件、否定。
2. 找直接证据：只有逐字引文才算；二手转述、标题、摘要中的模糊表述只算间接。
3. 逐成分匹配：
   - 全部匹配且无附加条件 → `supported`。
   - 只匹配部分 → `partially_supported`，note 写缺口。
   - 有原句与论断相反 → `contradicted`。
   - 找不到可判断的句子 → `insufficient_evidence`，写清找过什么。
4. 若材料明确说"未纳入/未测试/超出范围"，这是**证据不足**，不是反驳：
   - 例：论断"对 65 岁以上同样有效"，材料"65 岁以上未纳入" → `insufficient_evidence`。
5. 若论断含情态词（可能、或许、推测、有望、could、may、might），不得用 `contradicted`：
   - 最多 `partially_supported`（有部分支持）或 `insufficient_evidence`。
   - 若论断是可直接检验的事实断言（如"可直接推广"），材料原句直接否定时可以判 `contradicted`。

## 常见误判与反例

| 误判 | 正确做法 |
|-|-|
| 材料没提到 → contradicted | 改为 insufficient_evidence，并记录检索范围 |
| 只支持方向、不支持幅度 → supported | 改为 partially_supported，note 写"幅度无证据" |
| 摘要提到同一主题 → supported | 找正文原句；找不到则降级 |
| 只引对结论有利的一条 → supported | 并列相反证据；按强度判 partial/contradicted |
| 用未做过的实验"反驳"论断 | 改为 insufficient_evidence，说明该实验缺失 |
| 复合句中一半成立 → supported | 逐成分判；不成立部分写入 note，判 partially_supported |
| 页码/章节缺失 | 硬失败，回到材料重新定位 |
| 引文只在整份语料、不在所引文件 | 硬失败，修正 source 或引文 |

## 冲突处理

- 双方都要给 `source:locator` 与逐字引文，不得只留一方。
- 判定取限定态：若一方直接否定、另一方部分支持 → `contradicted` 并在 note 说明双方；
  若双方各支持一部分 → `partially_supported`。
- 在 `conflicts` 中写 `{claim, evidence_a, evidence_b, question}`，question 是交人工裁决的具体问题。
- 不得按"期刊影响因子"或"看起来更权威"静默择一。
