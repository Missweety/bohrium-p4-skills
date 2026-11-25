# 术语表格式、段号约定与双语对照产物

## 1. 术语表（`glossary.tsv`）

制表符分隔，UTF-8，`#` 开头为注释，首行可为表头：

```
source_term	target_term	code	banned_variants
sorption	吸附		absorbance|吸收
solid-phase extraction	固相萃取	SPE	固相提取
limit of detection	检出限	LOD	检测极限|检出极限
```

| 列 | 必填 | 说明 |
|-|-|-|
| `source_term` | 是 | 原文术语，保留原文大小写与连字符；多词短语整条写入 |
| `target_term` | 是 | **全篇唯一**锁定译名；同一概念只能有一行生效 |
| `code` | 否 | 缩写；首次出现写 `中文（English, ABBR）`，其后可用缩写 |
| `banned_variants` | 否 | 已知错译/旧译，`|` 分隔；出现在译文中即判 `variant_drift` |

来源标记写在 `glossary_source`（`given` = 材料/用户提供，`auto` = Skill 自行抽取）与 `uncertainty`。
自动抽取只允许从 `corpus.txt` 的实际文本取词，不得凭领域常识补术语。

**合并与冲突**：同义原文（`sorption` / `adsorption`）若原文确实混用，两种处理二选一并写进 `uncertainty`：
1. 合并为一行（`source_term` 取高频写法，另一种写入 `banned_variants` 之外的 `aliases` 备注）；
2. 各自保留但 `target_term` 必须不同，并在 `uncertainty` 说明原文是否区分机制。

## 2. 段号（`segment.id`）

| 前缀 | 对象 | 示例 |
|-|-|-|
| `P` | 正文段落 | `P001`、`P002` |
| `H` | 章节标题 | `H001`（`section` 记层级，如 `3.2`） |
| `C` | 图题 | `C001`（对应 `Figure 1`） |
| `T` | 表题/表注 | `T001`（对应 `Table 1`） |
| `N` | 脚注 | `N001` |
| `R` | 参考文献条目 | `R001`（不译正文，保留编号） |

规则：
- 编号按**阅读顺序**递增，连续、不跳号、不重复；同一 `id` 全篇唯一。
- 跨页/跨栏被折断的同一段合并为一条，`span` 写 `p.3-4`；不同小节即使相邻也不合并。
- 页面上的页眉、页脚、行号、DOI、期刊信息记入 `H`/`N` 或忽略，但必须在 `limits` 说明忽略范围。
- 切分完成后核对：`segment_alignment.csv` 行数 = `segments_total`；`kernel.py index` 的
  `total_chars` 与所有 `source` 字符数之和差异应可解释（图表/参考文献/页眉）。

## 3. 双语对照（`bilingual.json`）

```json
{"segments": [
  {"id": "P001", "section": "2.1", "locator": "p.3 para 2", "span": "p.3-4",
   "source": "Sorption of Pb(II) ... 12.4% ... [12].",
   "target": "Pb(II) 的吸附（sorption）…… 12.4% …… [12]。",
   "terms_used": ["sorption"], "status": "translated"}
]}
```

`status`：`translated` / `kept_original`（术语不确定或语言混杂）/ `image_placeholder`（公式表格为图）。

## 4. `translation.md` 版式

```markdown
### P001 · p.3 para 2 · 2.1

> Sorption of Pb(II) reached 12.4% at 25 °C [12].

Pb(II) 的吸附（sorption）在 25 °C 时达到 12.4% [12]。
```

- 原文用引用块，译文紧随其后；一段一块，不把多段塞进同一块。
- 术语首次出现加 `（English, ABBR）`；全文只在首次出现时加。
- 图表题注单独成块，编号与原文一致（`图 3` / `表 2`）。

## 5. 未译与待确认标注

| 场景 | 标注 | 同时写入 |
|-|-|-|
| 术语无把握 | `〔原文: sorption〕`，保留英文原词 | `uncertainty[{segment, term, reason}]` |
| 指代不唯一 | `〔指代待确认：A 或 B〕` | 同上 |
| 公式/表格为图片 | `〔公式图像：图 3 位置〕` | `uncertainty[{segment, type: image}]` |
| 原文残缺/不可读 | `〔原文缺失：p.5〕` | `limits` |
| 语言混杂段 | 整段保留原文，`status: kept_original` | `changes[{target, reason}]` |

**禁止**用"大意是……""似乎是……"这类模糊表述代替标注；不确定就必须可见。

## 6. `segment_alignment.csv`

```
id,kind,section,page,span,source_chars,target_chars,terms_used,sentences,status
P001,body,2.1,3,p.3-4,182,171,sorption,S1a|S1b,translated
```
