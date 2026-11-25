# 示例：论文摘要 → 公众科普（**SYNTHETIC / 合成示例**）

> **本目录全部内容为人工合成的演示数据，不对应任何真实论文、机构或比赛隐藏用例；数值与结论均为虚构，仅用于说明流程。** 不构成任何官方评分或效果声明。

下方所有命令与输出均为在本 Skill 包上真实运行的结果（2026-11-25，macOS，Python 3 标准库）。复现时把示例目录复制到 `/tmp`：

```bash
SKILL_DIR="/skills/weekly-skill"        # 本地复现时改为本包 submission/ 的绝对路径
cp -R examples/synthetic /tmp/transform-demo
mkdir -p /tmp/transform-demo/out
```

## 1. 夹具

`examples/synthetic/input/`（3 个可读文档 + 2 个跳过文件）：

- `case.json`：`output_contract` 为对象，含 `title` / `audience` / `genre` / `target_length` 等键；
- `task.md`（extract 会跳过）：科普改写要求；
- `study.md`（→ `doc.2`）：摘要 + 结果 + 局限；
- `note.txt`（→ `doc.1`）：批次说明；
- `table.csv`（→ `doc.3`）：与正文重复的分组统计。

`doc.N` 按文件名字母序编号，增删文件编号会变，一律以当次 `sources.json` 为准。代码支持 PDF/DOCX/HTML 抽取，但提交包只放 UTF-8 文本（`.md`/`.txt`/`.csv`/`.json`/`.tex`），二进制与 HTML 夹具不随包分发。

`examples/synthetic/work/plan.json` 给出 4 条 claim、3 条术语、1 条删除记录。

## 2. 命令（真实执行）

```bash
python3 "$SKILL_DIR/scripts/extract_sources.py" \
  --input /tmp/transform-demo/input --out /tmp/transform-demo/work/sources.json
python3 "$SKILL_DIR/scripts/build_transform.py" \
  --plan /tmp/transform-demo/work/plan.json --sources /tmp/transform-demo/work/sources.json \
  --case /tmp/transform-demo/input/case.json --out /tmp/transform-demo/out --work /tmp/transform-demo/work
python3 "$SKILL_DIR/scripts/selfcheck.py" \
  --case /tmp/transform-demo/input/case.json --out /tmp/transform-demo/out \
  --sources /tmp/transform-demo/work/sources.json
```

## 3. 真实输出

```text
extract: {"documents": 3, "readable": 3, "paragraphs": 10, "skipped": 2, "out": ".../sources.json"}   exit=0
build:   {"case_id": "syn-transform-demo", "status": "success", "genre": "popular_science",
          "claims": 4, "verified": 4, "numbers": 7, "unsupported_numbers": 0,
          "errors": 0, "warnings": 2, "out": ".../out"}   exit=0
selfcheck: {"ok": true, "passed": 29, "failed": 0, "warnings": 0}   exit=0
```

`transform.md`（节选）：

```markdown
# 更冷的保存，真的能保住更多细胞吗？

## 关键结果

对照组回收率为 92%，冷却组降至 71%，两者相差 21 个百分点；每组各 24 个样本。

## 需要保留的边界

作者提醒，这只是一项初步结果：只测试了一种细胞系，样本量较小，无法确立因果关系，也不能排除批次效应。补充说明还提到，有一个批次被排除在主分析之外。
```

`result.json` 摘要（当次实际值）：

- `status=success`，2 条 warn（`genre_element_missing`：科普模板建议的 background / significance 要素未识别），无 error；
- `preservation.verification_rate=1.0`（4/4 引文命中），`numbers` 7 个 token 全部可追溯；
- `metrics`：`chars=235`、`words=190`、`sentences=11`、`avg_sentence_chars=21.4`、`jargon_per_1000_chars=12.8`；
- `contract_fields` 8 个键全部有值（`title`/`audience`/`genre`/`target_length` 取自 `result.transform`）；
- `omissions` 为空：`doc.3`（表格）已在 `removals` 登记，`doc.2` 的局限段由 claim `c2` 覆盖。

字符/词数随文本微调变化，以当次 `result.json` 与 `checks.json` 为准。

## 4. 异常探针（真实运行过）

| 探针 | 构造 | 实际观察（v2.0） |
|---|---|---|
| 契约键含 title/genre/audience | `output_contract` 列表 `["transform_md","title","genre","audience","target_length"]` | 修复前这 4 个键为 `null`、`selfcheck` 硬失败；修复后全部有值，`ok=true` |
| 空材料 | `/input` 只有 `case.json` + `task.md` | `extract` 退出码 2；`build` 记 `no_readable_sources`(error)，`status=failed`，`transform.md` 首行带“未核验、不可发布”横幅，退出码 1；`selfcheck` `{"ok": true, "passed": 25, "failed": 0, "warnings": 3}` |
| 缺 `output_contract` | 删除该键 | `contract_declared` warn，默认结构字段照常输出；`selfcheck` `{"ok": true, "passed": 21, "failed": 0, "warnings": 2}` |
| 数字无来源 | 正文加“另有 3 个样本未纳入分析” | `unsupported_number` error → `partial`；`selfcheck` `{"ok": false, "failed": 1}`（`numbers_traceable`），退出码 1 |
| 引文被改（`92%`→`99%`） | claim 引文改数字 | `quote_unverified` error → `partial`，`preservation_map` 该行标 `False`；`selfcheck` `{"ok": true, "passed": 27, "warnings": 1}`，状态一致即通过 |
| 无登记覆盖的源段落 | 只改写部分段落 | `omission_unlogged_number` error → `partial`（设计如此，提示补 claim 或登记删除） |

## 5. 注意

- 示例只演示字段与流程；真实任务必须使用 `/input` 的材料，逐字复制引文与锚点。
- `status=success` 只说明该合成样例通过脚本核验，不代表官方 rubric 得分。
