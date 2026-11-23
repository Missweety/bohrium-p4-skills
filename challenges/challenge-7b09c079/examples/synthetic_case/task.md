# 演示任务（SYNTHETIC）

> 本目录为合成的教学/演示用例，**不是**平台正式案例；文中数据、结论与文献均为虚构，
> 仅用于展示"按指令改稿 + 保留修订 + 同步引用 + 版本谱系 + 导出"的完整闭环。

## 任务

给定一份 Markdown 稿件 `manuscript.md` 与 `organizer-edit-workorder.json`，请：

1. 把修改指令落到**具体句子**，只改指定位置，不整段覆盖；
2. 每处改动都生成**可逐条接受/拒绝**的 Word 修订标记，并保留原文与改后对照；
3. 同步正文引用与参考文献表：按正文首次出现顺序重排编号并重排条目；
4. 保留版本谱系（原稿 v0 只读、修订稿 v1、全部接受的干净稿），可对比、可回退；
5. 导出可编辑 docx 与 PDF 预览。

## 预期输出

- `revision.docx`（含修订标记）、`clean.docx`（全部接受）、`revision.md`、`revision.diff`；
- `revisions.json`（逐条修订）、`versions.json`（sha256 谱系）、`citation_map`（old→new）；
- `preview.pdf`（无渲染器时 `preview.html`）；
- `result.json`（契约字段、来源、不确定性、变更记录、自检）。
