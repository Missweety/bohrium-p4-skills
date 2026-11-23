# 章节模板与审计口径

`kernel.py init` 会生成 `work/section_template.json`。优先级：

1. `case.json` 的 `task` / `instruction` 中明确点名的章节 → `source=task_detected`，`required=true`；
2. 只有 `task.md` 泛泛列出章节时 → `source=task_md_advisory`，全部 `required=false`，
   按真实指令把需要的章节改成 `required=true`；
3. 都没识别到 → `source=skill_default_advisory` 的 IMRaD 骨架，全部 advisory。

## 格式

```json
{
  "source": "task_detected",
  "genre": "journal article",
  "sections": [
    {"name": "Abstract", "canonical": "Abstract",
     "aliases": ["Abstract", "摘要"], "min_words": 80, "required": true},
    {"name": "Results", "canonical": "Results",
     "aliases": ["Results", "结果"], "min_words": 120, "required": true}
  ],
  "declarations": ["data_availability"],
  "require_references": true,
  "require_doi": false
}
```

- `name`：稿件中使用的标题；`aliases`：审计匹配用，大小写不敏感；
- 一级标题（`# Title`）不参与章节匹配，避免论文题目里的 "results" 被误认成章节；
- `required=true` 的章节缺失 → FAIL；`min_words` 不足 → WARN（review）；
- 章节顺序按模板数组，实际出现顺序倒置 → FAIL；
- `declarations` 支持 `data_availability`、`funding`、`conflict_of_interest`、`ethics`，
  缺失 → FAIL；
- `require_references` / `require_doi` 为提示位；当前审计对每条文献检查 authors/year/title/venue 与 DOI，
  缺 DOI 只 WARN 并明确"未核验"，不生成 DOI。

## 图表

- 图注行格式：`Figure 1. ...`、`Fig. 1. ...`、`Table 1. ...`、`图 1. ...`、`表 1. ...`（中英文冒号均可）；
- 正文必须出现同编号引用（`Figure 1` / `图 1`），否则 WARN "caption never cited"；
- 正文引用但无图注 → FAIL；
- `draft.json` 的 `figures[].label` 必须能在成稿中找到对应图注，否则 FAIL；
- 图注位置由 `figures[].section` 决定；未指定时放在首次引用它的章节之后。

## 数字与引用

- 正文数字（含 `%`、单位、样本量、p 值）必须命中 `source_map.value` 或 `corpus.txt`，按数字边界匹配：
  `12.4` 不会被 `12.45` 满足；`12.4%` 与 `12.4` 视为同一值；
- 参考文献章节之前的正文才参与数字/引用检查，文献表自身不参与；
- 编号引用 `[1]`/`[1,3-5]` 必须能在文献表找到对应编号；
- `\cite{key}` 必须命中 bib key；
- 作者-年份 `(Smith et al., 2020)` 必须能在文献表、结构化 references 或材料原文中找到姓氏+年份；
- 找不到 → FAIL；没有文献信息时不要从记忆补，写 `【待补：reference ...】` 并登记 `missing_citation`。
