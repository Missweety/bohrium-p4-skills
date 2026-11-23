# 质量检查表（对齐 5 个评分维度）

## 1. 实际效果（40 分）

| 检查项 | 合格线 | 谁来查 |
|-|-|-|
| 版式槽位解析 | 能从 pptx/json 读出 title/body/caption/footer 与主题色、字体 | `template_fit probe` |
| 槽位映射 | 每页有 layout 与 title/body 映射；图表页尽量有 caption | `slot_map.md` + `evaluate` |
| 字号下限 | title ≥28、body ≥18、caption ≥12、footer ≥9 pt | `compliance.json`（硬错误） |
| 对比度 | 正文/背景 ≥4.5，强调色/背景 ≥3.0 | 同上（硬错误/警告） |
| 留白 | 槽位覆盖 ≤75%（警告）/≤90%（硬错误）；边距不过窄 | 同上 |
| 每页字数 | 标题+主张+要点 ≤380 字 | 同上（硬错误） |
| 页脚一致性 | 整册使用同一套页脚/页码槽位 | `layout_consistency` |
| 可放映 | pptx 由模板实际生成；无则如实 partial | `render_log.exports` |

## 2. 使用增益（25 分）

- 基础 Agent 常见失败：套模板时把内容塞进错误占位符、字号被母版吃掉、图表页没有图注位。
- 本包把“模板适配”变成**槽位映射表 + 合规清单**，返工从“逐页目测”变成“按行修正”。
- 同一 `spec + profile` 重复运行输出一致；模板换了只需重跑 probe + fit，不用重写内容。

## 3. 创新增益（15 分）

- **无需 python-pptx 的模板解析**：直接读 OOXML（`theme1.xml` + `slideLayout*.xml` + `clrMap`），
  在无第三方库环境也能给出可复核的槽位与主题色。
- **模板画像 → 映射 → 合规**三段式，中间产物 `template_profile.json` 可被其他工具复用。
- **按实际使用版式检查**：不因模板里未使用的版式误报字号不达标。

## 4. 可靠体验（10 分）

| 情况 | 处置 |
|-|-|
| 模板损坏/非 pptx | 降级默认 16:9 槽位，`warnings` + `uncertainty`，不崩溃 |
| 槽位缺字号 | 警告（不臆造字号），提示人工确认 |
| 无图注槽位 | 图表页警告，建议改用带图注版式 |
| 无页脚槽位 | 全局警告，不阻断 |
| 对比度无法计算 | 缺少主题色时警告，不假装通过 |
| 无 python-pptx | 交付槽位映射 + 合规报告 + Marp 源 + 讲稿，`partial` |
| 用户模板与内容冲突 | 以“内容完整 + 字号可读”为先，冲突写 `limits` |

## 5. 生态贡献（10 分）

- `template_profile.json` 是通用模板画像，可被生成/编辑包直接消费。
- `references/` 提供契约、检查表、合成模板示例；阈值集中在 `MIN_FONT` / `--min-fonts`。
- `scripts/spec_io.py` 与 `template_fit.py` 均仅用标准库，可独立复用。
