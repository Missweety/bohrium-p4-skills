# 示例：单篇材料 → 证据可溯源思维导图（**SYNTHETIC / 合成示例**）

> **本目录全部内容为人工合成的演示数据，不对应任何真实论文、机构或比赛隐藏用例。** 文中数值与结论均为虚构，仅用于说明接口与流程，不构成任何官方评分或效果声明。

所有命令与输出均为在本包上真实运行的结果（2026-11-25，macOS，Python 3 标准库）。

## 1. 夹具

`examples/synthetic/`：

- `input/case.json`：`output_contract` 含 `mindmap`/`nodes`/`edges`/`evidence_index`/`status`/`sources`/`uncertainty`/`change_log` 8 个字段；
- `input/task.md`：extract 会跳过；
- `input/notes.md` → `doc.1`，10 个段落（5 个小标题 + 5 段正文）；
- `work/plan.json`：9 个节点、7 条关系，其中 3 条为 `inference`（带 `basis`）。

## 2. 命令（真实执行）

```bash
SKILL_DIR="/skills/weekly-skill"      # 本地复现时改为本包 submission/ 的绝对路径
cp -R examples/synthetic /tmp/mindmap-demo
mkdir -p /tmp/mindmap-demo/out

python3 "$SKILL_DIR/scripts/extract_sources.py" \
  --input /tmp/mindmap-demo/input --out /tmp/mindmap-demo/work/sources.json
python3 "$SKILL_DIR/scripts/build_mindmap.py" \
  --plan /tmp/mindmap-demo/work/plan.json --sources /tmp/mindmap-demo/work/sources.json \
  --case /tmp/mindmap-demo/input/case.json --out /tmp/mindmap-demo/out --work /tmp/mindmap-demo/work
python3 "$SKILL_DIR/scripts/selfcheck.py" \
  --case /tmp/mindmap-demo/input/case.json --out /tmp/mindmap-demo/out \
  --plan /tmp/mindmap-demo/work/plan.json --sources /tmp/mindmap-demo/work/sources.json
```

## 3. 真实输出

```text
extract: {"documents": 1, "readable": 1, "paragraphs": 10, "skipped": 0}   exit=0
build:   {"status": "success", "reason": "树结构、关系端点与引文核验全部通过",
          "nodes": 9, "edges": 7, "verification_rate": 1.0,
          "issues": 0, "warnings": 1, "png": "none"}   exit=0
selfcheck: {"ok": true, "passed": 37, "failed": 0, "warnings": 1}   exit=0
```

- `stats`：`node_count=9`、`edge_count=7`、`verified_nodes=8`、`checked_nodes=8`、`verification_rate=1.0`、`max_depth=3`；
- 唯一 warning 是 `png_preview_missing`（本机没有 `rsvg-convert`/`cairosvg`），同时写入 `uncertainty`；`mindmap.svg` 是脚本实际布局渲染的矢量图；
- `mindmap.mm` 的 `<node>` 数与 `result.nodes` 一致（9），`nodes.csv` 数据行 9 行；
- `contract_fields` 8 个键全部有值。

`mindmap.md`（节选）：

```markdown
# 低温保存对细胞回收率的影响

- 用途：实验前快速理解材料
- 读者：课题组成员
- 状态：success

- **低温保存与细胞回收率** [concept/summary] {anchor: doc.1 p.1 sec.1 para.2}
  > 研究问题：低温保存后细胞回收率是否下降。
  - **分组与保存条件** [method/summary] {anchor: doc.1 p.1 sec.2 para.4}
    > 将样本分为对照组与冷冻组，各 12 个样本，冷冻组在 -80 度保存 7 天。
    - **每组 12 个样本** [evidence/summary] {anchor: doc.1 p.1 sec.2 para.4}
```

## 4. 异常探针（真实运行过）

| 探针 | 构造 | 实际观察（v2.0） |
|---|---|---|
| 只有提示、没有问题 | 一个超长 label + 一个重复 label | 修复前：`status=success` 但 `issues` 非空 → `selfcheck` 报 `status_consistent` 硬失败、退出码 1；修复后：`issues=[]`、`warnings=3`、`status=success`、`selfcheck {"ok": true, "passed": 37, "failed": 0, "warnings": 1}` |
| `plan.json` 缺失 | 删除 plan | 修复前：只打印一行 `plan.json missing or invalid` 并以 SysExit 结束，输出目录**没有** `result.json`；修复后：`status=failed` + `plan_missing`(error)，仍写出 md/mm/svg/csv 与完整契约字段，退出码 1；`selfcheck {"ok": true, "passed": 35, "failed": 0, "warnings": 3}` |
| 空材料 | `/input` 只有 `case.json` + `task.md` | `extract` 退出码 2；`build` `failed`（`no_readable_sources` + 8 条证据错误），退出码 1；`selfcheck {"ok": true, "passed": 37, "failed": 0, "warnings": 1}` |
| 根节点不在 `nodes` 中 | 删掉 `id=r` 的节点 | 修复前：补出的根不参与校验，`node_count=8` 但 `mindmap.mm` 有 9 个节点；修复后：先补根再校验计数，`node_count=9`、`change_log` 记录补根，`selfcheck` 通过 |
| 多文件 + GB18030 | Markdown(GBK) + CSV + HTML 子目录 | 3 个文档全部 `readable`，GBK 自动回退解码；`sources[].path` 为相对输入目录的 `legacy_gbk.md`、`table.csv`、`sub/page.html`（修复前是相对写死的 `/input` 的 `../tmp/...`） |
| `checks.json` 字段 | — | 现含 `ok`/`passed`/`failed`/`warnings`/`issues`/`warnings_detail`/`checks`，与 `references/output-contract.md` 一致 |

## 5. 注意

- 示例只演示接口与流程；真实任务必须使用 `/input` 的材料，`evidence.quote` 要逐字复制。
- 节点/关系数量阈值（≥8 节点、≥5 关系）是提示项，不是硬门槛：材料短时应如实少建，不得凑节点。
