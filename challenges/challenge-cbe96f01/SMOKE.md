# 已执行的正负冒烟

2026-11-21 使用 Python 3，合成稿件运行 prepare → 读原文形成 reviewed.json → render。

|检查|实跑结果|
|---|---|
|有效证据与完整覆盖记录|PASS，生成可读 report 与 result.json|
|伪造摘录|PASS，拒绝对应条目|
|错文件版本哈希|PASS，校验失败|
|重复 finding 编号|PASS，校验失败|
|case_id 不一致|PASS，校验失败|
|无材料|PASS，结构化 failed|
|坏 case.json|PASS，结构化 failed|


成品片段及本地确定性对照见 references/example-output.md。官方固定案例与正式对照待平台运行。

## 1.1.0 引用候选回归（2026-11-22，/tmp 合成材料）

|用例|输入|实跑结果|
|---|---|---|
|A|正文 [1]、[2]，书目含 [1]、[2]|findings=[]，无假阳性|
|B|正文 [3]，无书目|AUTO-CIT-1 evidence_gap major|
|C|无数字引用|findings=[]|
|D|正文 [1]、[4]，书目仅 [1]、[2]|AUTO-CIT-4 evidence_gap minor；render 后 accepted=1、rejected=0、validation passed=true、missing_facets=[]|

命令：`python3 scripts/audit.py prepare --input /tmp/smoke_cit/{a,b,c,d} --out .../out`，D 填写 reviewed.json 后 `render` 生成 result.json / validation.json / review-report.md。

## 1.2.0 数值/来源候选与 selfcheck 回归（2026-11-23，/tmp/cbe2_in 合成材料）

输入：稿件含“显著改善（p=0.21），n=24”、另一段“n=28”、同段“60% 与 45%”，参考文献标注 Retracted；sources/smith2021.md 含撤稿说明。

|用例|实跑结果|
|---|---|
|数值候选|NUM-P-1（自称显著但 p=0.21，major）、NUM-N-2（同源 n=24/28，minor）、NUM-PCT-3（合计 105.0%，minor）|
|来源候选|SOURCE-META-RETRACT-1（撤稿标记，major）|
|render|accepted=4、rejected=0、validation_passed=true、status=success|
|selfcheck 正例|passed=true、errors=[]、missing_facets=[]、findings=4、checks=6，exit 0|
|selfcheck 缺契约字段|`method_matrix` 缺失 → passed=false、exit 1|
|selfcheck 伪造引文|finding NUM-P-1 quote 不在原文 → passed=false、exit 1|
