# 完整本地示例（合成）

全部材料为人工构造的接口与错误边界测试。

## 输入

### draft.md — p.1/para.1
Treatment causes better sleep in all adults [1].

### draft.md — p.1/para.2
The observed association was 12 percent.

### source.md — p.1/para.1
A cross-sectional survey observed an association between treatment exposure and self-reported sleep in students.

### source.md — p.1/para.2
The difference was 12 percent; causal effects were not established.

## 已执行的最终报告

# 科研审查报告

Synthetic local excerpt review. Source-bound findings and concrete revisions follow.

运行状态 success

|编号|检查面|结论|严重度|
|---|---|---|---|
|F1|citation_support|partial_support|major|

## F1

The source is a cross-sectional association in students. The manuscript changes association into causation and extends the population to all adults.

修改建议

Replace the claim with: In the surveyed students, exposure was associated with self-reported sleep; causal and broader-population effects remain unestablished.

draft.md — p.1/para.1

> Treatment causes better sleep in all adults [1].

draft.md — p.1/para.2

> The observed association was 12 percent.

source.md — p.1/para.1

> A cross-sectional survey observed an association between treatment exposure and self-reported sleep in students.

source.md — p.1/para.2

> The difference was 12 percent; causal effects were not established.

## 覆盖与待核

[
  {
    "facet": "facts",
    "status": "checked",
    "evidence": [
      {
        "source_id": "draft.md",
        "locator": "p.1/para.1",
        "quote": "Treatment causes better sleep in all adults [1].",
        "sha256": "b587d4182164571cc01272e03e0de096657eb6e6b34cc9f4bc886ff620571d20"
      }
    ],
    "reason": "Reviewed the supplied synthetic text"
  },
  {
    "facet": "citation_support",
    "status": "checked",
    "evidence": [
      {
        "source_id": "draft.md",
        "locator": "p.1/para.1",
        "quote": "Treatment causes better sleep in all adults [1].",
        "sha256": "b587d4182164571cc01272e03e0de096657eb6e6b34cc9f4bc886ff620571d20"
      }
    ],
    "reason": "Reviewed the supplied synthetic text"
  },
  {
    "facet": "methods",
    "status": "not_applicable",
    "reason": "Synthetic excerpt supplies no methods/protocol or normative claim to assess"
  },
  {
    "facet": "statistics",
    "status": "checked",
    "evidence": [
      {
        "source_id": "draft.md",
        "locator": "p.1/para.1",
        "quote": "Treatment causes better sleep in all adults [1].",
        "sha256": "b587d4182164571cc01272e03e0de096657eb6e6b34cc9f4bc886ff620571d20"
      }
    ],
    "reason": "Reviewed the supplied synthetic text"
  },
  {
    "facet": "logic",
    "status": "checked",
    "evidence": [
      {
        "source_id": "draft.md",
        "locator": "p.1/para.1",
        "quote": "Treatment causes better sleep in all adults [1].",
        "sha256": "b587d4182164571cc01272e03e0de096657eb6e6b34cc9f4bc886ff620571d20"
      }
    ],
    "reason": "Reviewed the supplied synthetic text"
  },
  {
    "facet": "academic_norms",
    "status": "not_applicable",
    "reason": "Synthetic excerpt supplies no methods/protocol or normative claim to assess"
  }
]

[]


## 本地对照

|本地规则|同一输入结果|说明|
|---|---|---|
|只检查“有原文、非空引用”|接受了伪造摘录|本地定义的弱校验器|
|本包逐文件逐段+哈希检查|拒绝 1 条伪造摘录和错版本，另保留有效条目|实跑结果|
|基线 Agent 与 Skill Agent 质量增益|not_run|官方同输入对照由平台提供|

上述对比仅衡量确定性证据绑定规则，未测人工耗时、语义召回或正式得分。
