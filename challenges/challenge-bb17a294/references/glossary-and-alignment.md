# 双向术语表、段号与双语对齐

本文件规定三件事：术语表怎么建、段号怎么编、双语稿怎么交付给作者继续改。

## 1. 术语表格式（5 列 TSV）

```
# zh_term	en_term	code	banned_zh	banned_en
吸附	sorption		吸着|吸收	absorption
固相萃取	solid-phase extraction	SPE	固相提取	SPE extraction
检出限	limit of detection	LOD	检测极限	detection limit
```

- 第 1、2 列是中英双向锁定的两个译名，顺序固定；脚本按实际语向取"目标侧"核对。
- 第 3 列缩写可空；英文目标侧允许用缩写代替全称。
- 第 4、5 列是**禁用变体**，用 `|` 分隔；只在该术语出现在原文时检查。
- 4 列文件（无 `banned_en`）按"变体只约束目标侧"处理，兼容旧表。
- 一行一个概念。同形异义必须拆行并用 `banned` 互相排除，例如：
  `cell	细胞		池|电解池	cell stack` 与 `electrolytic cell	电解池		细胞	cell` 不能同时存在，
  应按本题学科只保留一个，另一个写进 `uncertainty`。

### 1.1 自动抽取规则（无给定术语表时）

1. 只从 `corpus.txt` 抽，不从模型记忆抽。
2. 优先多词复合名词（`solid-phase extraction`、`limit of detection`），再抽单词术语。
3. 排除通用词（`study`、`method`、`result`、`sample`）与纯统计词（`mean`、`SD`、`p`）。
4. 每个术语至少出现 1 次；只出现 1 次的标 `low_frequency: true`，提示人工复核。
5. 术语来源写进 `glossary.tsv` 注释行：`# source: given | auto | auto+human`。

### 1.2 学科歧义处理

同一个英文词在不同学科译法不同，必须按本题材料定一条并在 `uncertainty` 说明：

| 英文 | 学科 | 本 Skill 的选择依据 |
|-|-|-|
| `cell` | 生物学 → 细胞；电化学 → 电解池/电池 | 看同段共现词（`membrane`/`culture` vs `electrode`/`voltage`） |
| `resolution` | 影像 → 分辨率；化学 → 分离度 | 看单位（`µm`/`nm` vs 无单位）与动词（`resolve`） |
| `significant` | 统计 → 显著（须有 p 值）；一般 → 明显 | 无 p 值时不写"显著"，写"明显/较大" |

## 2. 段号规则

| 前缀 | 用途 | 示例 |
|-|-|-|
| `H` | 章节标题 | `H001 1 引言` |
| `P` | 正文段落 | `P001` |
| `C` | 图注 | `C001`（对应 Figure 1） |
| `T` | 表注/表头 | `T001`（对应 Table 1） |
| `N` | 脚注 | `N001` |
| `R` | 参考文献条目 | `R001` |

- 编号按阅读顺序连续，不跳号；新增段只能追加在所属章节末尾，不能插入改变既有编号。
- 跨页/跨栏被折断的同一段合并为一条，`span` 写 `p.3-4`；不同小节即使在同一页也不合并。
- 标题、图注、表注、脚注各自独立成段，不并入正文段。
- 段号一旦确定，`segments.json`、`bilingual.json`、`bilingual.csv`、`translation.md` 四处必须一致。

## 3. 双语对齐文件

`work/bilingual.json`：

```json
{"segments":[
  {"id":"P001","section":"Abstract","locator":"p.1 para 1",
   "source":"Sorption of Pb(II) reached 12.4% at 25 °C [12].",
   "target":"Pb(II) 的吸附（sorption）在 25 °C 时达到 12.4% [12]。",
   "terms_used":["sorption"],"source_sentence":"S1"},
  {"id":"C001","section":"Figure 1","locator":"p.2 caption",
   "source":"Figure 1. Effect of pH on sorption (mean ± SD, n = 3).",
   "target":"图 1. pH 对吸附的影响（mean ± SD, n = 3）。",
   "terms_used":["sorption"]}
]}
```

`work/bilingual.csv` 直接由 JSON 导出，列固定为
`id,section,span,source,target,terms_used`，供 CAT 工具或人工逐行修改。

`translation.md` 排版：

```markdown
### P001 · p.1 para 1 · Abstract
> Sorption of Pb(II) reached 12.4% at 25 °C [12].

Pb(II) 的吸附（sorption）在 25 °C 时达到 12.4% [12]。
```

## 4. 不确定与未译的标注

| 情况 | 正文写法 | 同步动作 |
|-|-|-|
| 术语没把握 | `译名〔原文: term〕` | `uncertainty` 记 `{segment, term, candidates}` |
| 句子结构歧义 | 保留原句并标 `〔原句待确认〕` | `uncertainty` 记两种可能的指代 |
| 公式/表格是图片 | `〔公式图像: 图 3 位置〕` | `uncertainty` 记无法还原 |
| 原文缺页/乱码 | `〔缺页: p.5〕` | `limits` 写缺页范围 |
| 未译完 | 不写占位符冒充译文 | `status: partial`，`limits` 列未译段号 |

禁止用"其""该过程""相关机制"等模糊词掩盖不确定；宁可留原文＋标注，也不要编一个通顺但错误的译法。

## 5. 交付前对齐自检

1. `segments.json` 与 `bilingual.json` 的 `id` 集合、数量、顺序完全一致。
2. 每个 `target` 非空；未译段必须在 `limits` 列出，不能悄悄留空。
3. `bilingual.csv` 行数 = 段数；`terms_used` 里的术语都能在 `glossary.tsv` 找到。
4. `translation.md` 的每段都能按 `id` 回指原文，图表题注位置未被移动。
5. `glossary_unused` 中的术语要么补进译文，要么在 `uncertainty` 说明为何未用。
