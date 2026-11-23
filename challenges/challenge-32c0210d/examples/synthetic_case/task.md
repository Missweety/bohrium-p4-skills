# 演示任务（SYNTHETIC）

> 本文件为合成的教学/演示用例，**不是**平台正式案例；文中数据、结论与文献均为虚构，仅用于展示
> 本 Skill 的输入格式与输出结构。

## 任务

给定一篇分章撰写的学位论文稿件（`chapters/chapter1.md` ~ `chapter3.md`）与一份
`organizer-edit-workorder.json`，请：

1. 统一术语与符号，指出缩写冲突、先用后定义、重复定义、符号多义；
2. 检查图表与公式编号（重复、断号、章前缀不符）与正文引用（悬空引用、未被引用）；
3. 检查正文引用编号与参考文献表是否同步；
4. 找出跨章节方向相反的结论候选；
5. 只对"排版级 / 工单显式指定"的条目做自动修订，产出可继续编辑的修订稿。

## 交付

- 修订稿 `revision.docx` 与 `revision.md`；
- 可逐条复核的不一致清单 `inconsistencies.csv`；
- 巡检报告 `consistency_report.md`；
- 预览 `preview.pdf`（无渲染器时为 `preview.html`）；
- `result.json`（含契约字段、来源、不确定性、变更记录、自检）。
