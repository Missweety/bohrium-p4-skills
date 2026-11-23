---
name: academic-writing-client
description: 学术写作客户端：接收稿件与修改工单，把指令落到具体句子/段落生成可逐条接受或拒绝的 Word 修订标记（w:ins/w:del），同步正文引用与参考文献表编号，保留原稿/修订稿/干净稿版本谱系，导出可编辑 docx 与 PDF 预览，并输出逐条修订记录与自检结果。
version: 2.0.0
license: MIT
---

# 学术写作客户端：改得准、改得可追溯、格式不塌

把"按指令改稿"拆成 **读稿 → 解析工单 → 定点修订 → 引用同步 → 版本谱系 → 导出 → 独立复核**。

每条修订的价值 = 有 `段落号 + 逐字锚点 + 改前/改后 + 依据`，并能在 Word「审阅」里**逐条接受或拒绝**；
一次交付的价值 = 原稿、修订稿、干净稿齐全，可对比、可回退，导出的 docx 仍可继续编辑。

## 平台路径（务必按此执行）

本 Skill 评测时安装在 `/skills/weekly-skill`，工作目录通常是 `/app`，**两者不同**。
脚本一律用绝对路径调用：

```bash
SKILL_DIR=/skills/weekly-skill          # 若你确实在 skill 目录内，可写 SKILL_DIR=.
python3 "$SKILL_DIR/scripts/run_case.py" --input /input --work /app/work --out /app/output
python3 "$SKILL_DIR/scripts/run_case.py" --check /app/output
```

## 何时使用

触发（满足任一）：

- 用户给出**稿件 + 修改指令**（含"把某句改成…/删掉这句/统一术语/重排引用"），要求改到具体位置；
- 要求生成**可逐条接受/拒绝的修订**，而不是一段无法回填的改写文字；
- 要求正文引用与参考文献表**同步编号**，或要求保留**版本谱系/可回退**、导出可编辑 docx/PDF。

不触发：从零代写整篇论文；要求编造数据或文献；无稿件却要求"润色"；扫描件无文本层且要求自动改稿。

## 输入

| 输入 | 说明 |
|-|-|
| `case.json` | `case_id` + `output_contract.required`；稿件路径放在 `manuscript/materials/files/...` 任一键 |
| 稿件 | `.docx`（真实 OOXML）/ `.md` / `.txt` / 有文本层的 `.pdf`；多份按自然序合并 |
| `organizer-edit-workorder.json` | 工单，见下表；缺省时仍输出结构完整的 `failed/partial` 结果 |
| `task.md` | 题面，仅摘录进 `result.json.parsed`，不当作改写素材 |

### 工单字段（宽松解析，不认识的键记入 `change_log`）

```json
{
  "edits": [{"target_quote": "原句逐字片段", "replacement": "改后文字", "basis": "依据"}],
  "delete_sentences": [{"quote": "要删除的整句逐字片段", "basis": "依据"}],
  "insertions": [{"anchor": "插入点前的逐字片段", "text": "要插入的文字", "basis": "依据"}],
  "citation_sync": true,
  "instructions": ["统一术语：“A”改为“B”。", "把摘要写得更具感染力。"]
}
```

- `edits` / `delete_sentences` / `insertions` / `citation_sync` 为可机械落地指令；
- `instructions` 中的引号对（`“A”改为“B”`）自动转为 `edits`；
- 其余无法机械落地的**语义型指令**不猜改，记入 `pending_instructions` 与 `uncertainty`。

## 主流程

1. **读稿**：docx 走 OOXML 真实解析（段落、样式、表格单元格段落、run 分段）；md/txt 建 docx 后解析；
2. **定点修订**：只在**直接 `w:r` 子元素**里查找逐字锚点，命中处拆成
   `前段 + <w:del>旧</w:del> + <w:ins>新</w:ins> + 后段`，每条带唯一 `w:id`、`w:author`、`w:date`；
   已有 `w:ins/w:del` 内的文字不会被当作锚点，因此可**在已有修订上继续改而不互相污染**；
3. **引用同步**：按正文首次出现顺序计算 `old→new`，改写正文引用与参考文献条目前导编号，并按新顺序重排条目；
4. **双版本**：`revision.docx`（含修订标记）；`clean.docx` = 全部接受修订（删 `w:del`、解包 `w:ins`）；
5. **版本谱系**：`original.docx` 为 v0 只读副本，记录 sha256 与父版本，明确回退方式；
6. **导出**：`soffice --headless` 转 PDF 并校验 `%PDF` 与页对象；失败写 `preview.html` 并记录原因；
7. **独立复核**：重新打开修订稿与干净稿，校验可解析、可见文本一致、每处修订确实落进干净稿、锚点逐字可查。

## 输出

| 产物 | 内容 |
|-|-|
| `revision.docx` | 含 `w:ins/w:del` 的修订稿，Word「审阅」可逐条接受/拒绝 |
| `clean.docx` | 全部接受后的干净稿，可直接投稿 |
| `original.docx` | 原稿只读副本（v0） |
| `revision.md` / `revision.diff` | 干净稿 Markdown 与原稿逐行差异 |
| `revisions.json` | 逐条修订：类型/段号/章节/锚点/改前/改后/依据/状态/作者/日期 |
| `versions.json` | 版本谱系：v0 → v1 → v1-clean，sha256 与回退说明 |
| `preview.pdf` 或 `preview.html` | 真实渲染预览 |
| `result.json` | 契约字段 + `citation_map` + `version_history` + 来源 + 不确定性 + 变更记录 + 自检 |
| `revision_report.md` | 人读版修订报告 |

## 状态语义（诚实降级）

| status | 何时 |
|-|-|
| `success` | 所有指令命中并落地、无语义待办、修订标记存在、预览成功、自检通过 |
| `partial` | 有指令未命中原文 / 有语义型待办 / 无修订标记 / 预览降级 / 合并重建 —— 均写入 `limits` |
| `failed` | 没有任何可读稿件：仍写全 `result.json` 与逐文件失败原因，不猜测内容 |

`skipped_revisions` 记录未命中项及原因；`pending_instructions` 记录语义型待办。**不假装改了。**

## 异常与降级

| 情况 | 处理（已内置于 run_case） |
|-|-|
| `.doc`/RTF 伪装成 docx、zip 损坏 | 记 `unreadable` 与原因，继续处理其余材料 |
| 稿件有复杂域/超链接，锚点跨非直接 run | 该条记 `skipped`，说明原文结构不支持安全标记，绝不强行重建段落 |
| 工单锚点在原文找不到 | 记 `skipped`，不改相近句子 |
| 语义型指令（如"更有感染力"） | 不猜改，列入 `pending_instructions` 与 `uncertainty` |
| 已有修订的段落上再改 | 只在普通 run 内定位，保留并叠加新标记，`w:id` 全局唯一 |
| 参考文献条目非正文直接段落 | 只改编号不重排，`citation_sync.reordered.ok=false` 并说明 |
| 无 LibreOffice | 不谎报 PDF；写 `preview.html` 并在 `limits` 说明 |
| 多份稿件输入 | 合并重建为单一 docx，`limits` 声明不保留分页/页眉页脚 |

## 硬性禁止

- 不整段覆盖：删除/替换必须能指到逐字锚点；找不到就不改。
- 不新增、修改文献著录内容（作者/题名/年份），只改编号与顺序。
- 不生成"伪修订"：每条修订必须真实存在于 `revision.docx`，且能接受后出现在 `clean.docx`。
- 不覆盖原稿；`original.docx` 只读副本必须与输入一致（sha256 记录在 `versions.json`）。
- 不在产物中写入个人绝对路径、账号或 token。

## 文件说明

- `scripts/run_case.py`：一条命令端到端与 `--check` 自检。
- `scripts/docx_io.py`：纯标准库 OOXML 解析/保存/新建（段落、表格、样式、run 分段）。
- `scripts/track_changes.py`：`w:ins/w:del` 生成、唯一 id、「全部接受」干净稿。
- `scripts/citations.py`：正文引用与参考文献表抽取、`old→new` 映射、编号改写与条目重排。
- `scripts/lineage.py`：sha256、版本快照、逐行差异。
- `scripts/locate.py`：章节、句级切分、题注定位。
- `scripts/preview.py`：LibreOffice 转 PDF + 校验；失败降级 HTML。
- `references/output-contract.md`：契约字段、别名映射、状态与自检口径。
- `references/method.md`：修订锚定、修订标记结构、引用同步与版本管理方法。

## 最小示例

见 `examples/README.md`：`examples/synthetic_case/` 为**合成演示**（SYNTHETIC，非正式案例），
含 1 份稿件 + 工单（2 处替换、1 处删除、1 处插入、引用重排），可复现 10 条修订与完整版本谱系。
