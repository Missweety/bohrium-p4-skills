# 语义复核协议 · 学术汇报内容组织

## 为什么需要这一步

`field_extract.py` 做的是**词面检索**：找出与字段描述共现的句子，并把句内数值连同逐字引文和锚点一起交出来。它保证「引文逐字来自原文」，但**不保证**「这句真的在报告这个字段」。

题面铁律：*A guessed value is not extraction, an absent field is not zero, and a literal quotation match alone does not establish semantic correctness.*

所以最终状态必须由你下结论，`review_fields.py` 只负责把结论确定性地落盘。

## 判定文件格式

```json
{
  "fields": {
    "f_bleu": {
      "status": "reported",
      "value": "34.81",
      "unit": "",
      "statistic": "BLEU",
      "experimental_condition": "WMT14 English-to-French, 80k vocab LSTM",
      "comparator": null,
      "paragraph_id": "p.5/sec.11/sent.3",
      "quote": "<逐字取自该锚点页的原文>"
    },
    "f_human_eval": {"status": "not_reported"},
    "f_x": {
      "status": "source_conflict",
      "conflicts": [
        {"paragraph_id": "p.4/sec.8/sent.2", "quote": "<逐字>"},
        {"paragraph_id": "p.7/sec.19/sent.5", "quote": "<逐字>"}
      ]
    }
  }
}
```

## 各状态的填写要求

| status | value | quote | paragraph_id | 额外 |
|--------|-------|-------|--------------|------|
| `reported` | 原文真实取值 | 必填，逐字 | 必填 | 填 unit/statistic/条件/比较对象 |
| `not_reported` | 必须为空 | 不填 | 不填 | 原文确实没报告 |
| `source_conflict` | 必须为空 | 不填 | 不填 | `conflicts` 至少两处 |
| `extraction_failed` | 必须为空 | 不填 | 不填 | 材料不可读 |

## `review_fields.py` 会强制什么

1. `reported` 的引文若未在锚点页逐字命中 → **拒绝写入**（防止编造引文）。
2. `not_reported` 若带 `value` → **拒绝写入**（缺失不等于 0）。
3. `source_conflict` 少于两处 → **拒绝写入**。
4. 写回后把 `needs_review` 置为 `false`，未复核的字段自动进 `uncertainty.unresolved`。
5. 写回后自动重跑 `audit_result.py` 复核。

## 复核顺序建议

1. 先读 `field_results.json` 里 `candidates` 最多的字段（信息量最大）。
2. 对每个候选只问一句：*这句话在报告这个字段吗？* 不在就跳过。
3. 命中的候选按 `paragraph_id` 回 `doc.json` 里核对上下文（前后句）。
4. 数值保留原文写法与单位，不换算、不四舍五入、不跨字段合并。
5. 全部候选都不命中 → 标 `not_reported`，并确认原文确实没有（可搜同义表述）。
