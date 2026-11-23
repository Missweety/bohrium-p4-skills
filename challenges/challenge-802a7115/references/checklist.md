# 交付前逐项自检

运行前与提交 `result.json` 前逐项勾选；任何一项不满足都写入 `uncertainty` 或 `field_status`。

## 输入与契约

- [ ] 已读完整 `/input/case.json`、`/input/task.md`；存在 `environment/resources.yaml` 时已读。
- [ ] 已用 `scripts/source_index.py extract` 清点实际文件，并核对了文件数、可读性与哈希。
- [ ] 已解析 `output_contract`，列出字段路径、类型和必需性；没有写死案例或字段。
- [ ] 记录文件来自实际输入，不是示例或记忆中的内容。
- [ ] 已区分“实际执行的查询”和“建议但未执行的查询”。

## 语言与版本

- [ ] 每条记录的语言由真实原文判定，有文件与页/行依据。
- [ ] 标签与原文冲突时以原文为准，并记录冲突。
- [ ] 区分原文语言、译文目标语言、摘要语言；未把仅摘要计入全文覆盖。
- [ ] `version_type` 只使用 `original/translation/abstract_only/duplicate/bilingual`。

## 翻译与术语

- [ ] `translation-log.csv` 每行有 `method`、`service`（若用服务）、`service_version`、`date`、`uncertainty`。
- [ ] 未声称使用未实际使用的翻译服务；服务失败/限额已记录。
- [ ] 人工或模型翻译已标注，并对高风险术语做回译或人工抽检。
- [ ] 术语表覆盖同义词、缩写、音译、本地译名；缩写已消歧并给出依据。
- [ ] 术语扩展有边界，未把近义泛词无限制纳入。

## 检索与证据

- [ ] 每个目标语种都有独立查询式，记录语种、查询式、术语来源、来源库/导出、日期、命中数、定位。
- [ ] 每条命中保留 `source_file` 与 `locator`，能回到当前原文。
- [ ] 处理了词形变化、复合词、语序、中英混排标题；匹配依据可复核。
- [ ] 对高风险命中做了回译或人工抽检，假阳性有判定依据。
- [ ] 未把字符串相等当作语义相关。

## 去重与异常

- [ ] 同一 `work_id` 的多语版本已归并展示，但记录全部保留。
- [ ] 精确重复有 `duplicate_of`，仅标题相似未被判为重复。
- [ ] 仅摘要、重复版本、同作多语、缺失语种、孤立版本均已在矩阵或问题清单标出。
- [ ] 空结果、无权限、原文不可得、版本冲突、翻译失败分别说明，未补造。

## 脚本与产物

- [ ] 已运行 `language_matrix.py`，并解释退出码 `0/2/1`。
- [ ] `matrix.json`、`versions.csv`、`issues.csv` 存在于工作目录。
- [ ] `/app/output/` 下有 `matrix.json`、`versions.csv`、`translation-log.csv`、`report.md`、`result.json`。
- [ ] `result.json` 保留原始 `case_id`，覆盖 `output_contract` 的全部字段和类型。
- [ ] 无法填写的必需字段为 `null` 且有 `field_status`/`uncertainty` 说明。

## 诚实性与边界

- [ ] 未声称实时数据库覆盖、完整召回、未见语种结论或新研究结论。
- [ ] 未编造文献、DOI、语种、版本、翻译服务、人工复核或测评分数。
- [ ] 已写明已完成范围、未覆盖范围、停止理由和后续建议。
- [ ] 所有路径使用 `/input`、`/app/work`、`/app/output`，不含个人绝对路径或凭据。
