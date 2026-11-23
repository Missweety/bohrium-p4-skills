# 示例说明（SYNTHETIC）

本目录内容全部为**合成演示数据**，不是平台正式案例，也不是任何真实论文、真实实验或真实文献。
仅用于说明输入格式、可复现的最小调用方式与示意输出。

## 目录

```
examples/
  README.md                       本文件
  synthetic_case/
    task.md                       演示任务说明（SYNTHETIC）
    case.json                     运行时契约（output_contract.required）
    organizer-edit-workorder.json 工单：2 处替换 + 1 处删除 + 1 处插入 + 引用同步
    manuscript.md                 演示稿：3 节正文 + 参考文献表（引用顺序为 [3][1][2]）
```

## 演示稿的初始状态（故意制造的真实问题）

- 正文引用顺序为 `[3] → [1] → [2]`，与参考文献表顺序不一致；
- 结论句使用绝对化表述"显著提升"；
- 方法节含一句与交付要求冲突的句子"本节数据尚未公开，仅作示例。"；
- 指令要求把"具体句子"扩为"具体句子与段落"。

## 最小调用

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --input  <本目录>/synthetic_case \
  --work   /app/work \
  --out    /app/output

python3 /skills/weekly-skill/scripts/run_case.py --check /app/output
```

## 示意输出（示例，非正式结果）

- `revision.docx`：10 条修订（2 替换 + 1 删除 + 1 插入 + 3 正文引用重编号 + 3 条文献条目重编号），
  每条都有唯一 `w:id/author/date`，可在 Word「审阅」中逐条接受或拒绝；
- `clean.docx`：全部接受后的干净稿，正文引用变为 `[1]→[2]→[3]`，参考文献表按新编号重排；
- `revisions.json`：逐条修订（段号/章节/锚点/改前/改后/依据/状态）；
- `versions.json`：v0（original.docx）→ v1（revision.docx）→ v1-clean（clean.docx），含 sha256 与回退说明；
- `preview.pdf`：装有 LibreOffice 时生成真实 PDF，否则写 `preview.html` 并说明原因。

> 上述条数由本示例内容决定，仅用于说明结构，不构成任何评分依据。
