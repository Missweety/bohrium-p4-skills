# 示例说明（SYNTHETIC）

本目录内容全部为**合成演示数据**，不是平台正式案例，也不是任何真实论文、真实实验或真实文献。
仅用于说明输入格式、可复现的最小调用方式与示意输出。

## 目录

```
examples/
  README.md                      本文件
  synthetic_case/
    task.md                      演示任务说明（SYNTHETIC）
    case.json                    运行时契约（output_contract.required）
    organizer-edit-workorder.json 工单：规范术语 + 1 条 find/replace 目标 + 指令（含 1 条语义型指令）
    chapters/chapter1.md         第 1 章：缩写先用后定义、拉丁术语变体、符号表、术语定义、图1-1/表1-1
    chapters/chapter2.md         第 2 章：缩写冲突、符号多义、重复定义、图2-2 断裂/悬空、表3-1 章前缀不符、式(2-1)/(2-3) 断号、[3] 未定义
    chapters/chapter3.md         第 3 章：结论与第 2 章相反、[2] 未被引用
```

## 最小调用

```bash
python3 /skills/weekly-skill/scripts/run_case.py \
  --input  <本目录>/synthetic_case \
  --work   /app/work \
  --out    /app/output

python3 /skills/weekly-skill/scripts/run_case.py --check /app/output
```

## 示意输出（示例，非正式结果）

- `result.json`：`status=partial`（多份 md 已被合并重建为单一 docx，格式损失已如实写入 `limits`）；
- `inconsistencies.csv`：约 15~20 条不一致，覆盖 terminology / symbol / definition / numbering /
  reference / citation / conclusion 七类；
- `revision.docx`：只改写命中 run 的修订稿（本用例约 3 处自动修订：`transformer`→`Transformer`、
  `卷积网络`→`卷积神经网络`，以及工单目标 `多头注意力`→`多头自注意力`）；
- `result.json.workorder_execution`：逐条列出工单目标的状态（`applied` 含段落/章节/次数，
  `not_found` 含检索范围），本用例为 W001 `applied`；
- `result.json.edit_impact`：同一旧写法仍出现在哪些段落，便于作者继续跟进；
- `preview.pdf`：装有 LibreOffice 时生成真实 PDF，否则写 `preview.html` 并在 `limits` 说明原因。

> 上述条数随输入内容变化，仅用于说明结构，不构成任何评分依据。
