# 运行接口与适用范围

prepare 输入为实际材料目录，输出 evidence.json、source-index.md、review-template.json、preparation.json。
原文件路径和 SHA-256 与物理页/段绑定。纯文本的页仅为文本容器页，引用时优先使用行/段标识并说明文本来源。
PDF 每页换页符产生物理页定位，表格、公式和 OCR 需视觉核验。DOCX 读段落，不承诺保留版式。

render 接受 evidence.json 与 Agent 读原文后填写的 reviewed.json，输出审查报告、result.json 和 validation.json。缺字段、错源、改稿哈希、重复编号、未知类型都会记录。不得将模板未查项改成已查且省略证据。已查可以无问题。
缺材料时提交诚实 partial/failed 和具体原因。外部资源先按清单解析，再显式放入实际材料目录，记录其原始来源。
当前 case 的 output_contract 优先，Agent 应读取 schema 的全部字段与类型，针对实际任务完成最终 JSON。
机器核验通过只支持原文绑定与结构通过，语义、因果、统计适用条件由 Agent 核实。

`selfcheck` 子命令（`--result /app/output/result.json --case /input/case.json --evidence /app/work/audit/evidence.json --out /app/work`）在交付前检查：运行时 `output_contract` 的必填字段是否齐全、finding 引文是否仍逐字存在于所引段落、六个 facet 是否有覆盖记录。不通过时退出码 1，并在 `selfcheck.json` 列出原因；通过不代表语义正确。
