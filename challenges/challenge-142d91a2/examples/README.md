# 合成示例（SYNTHETIC）

本目录所有内容均为技能自测而虚构，**不代表任何真实课题、机构、人员或数据**。  
文件内已用 `SYNTHETIC` 标注，禁止把示例数字当作真实研究依据。

## 目录

```
synthetic_case/
  task.md                     任务说明（SYNTHETIC）
  case.json                   案例字段 + output_contract
  materials/
    01_project_guideline.md   背景、条件、缺口、伦理（SYNTHETIC）
    02_preliminary_data.csv   6 行虚构预实验数据（SYNTHETIC）
    03_group_notes.md         问题、方法、指标、成果、风险（SYNTHETIC）
```

## 用途

- 验证抽取、七要素、证据台账、对齐矩阵、里程碑、DOCX、自检的完整链路
- 验证缺失信息不会被编造：示例中的周期、经费、样本、人员、伦理均已给出，便于先验证 `success` 路径
- 验证 DOCX 重开：`proposal.docx` 必须能被 `zipfile` 打开，且 `word/document.xml` 可解析

## 运行

```bash
python3 scripts/run_case.py \
  --input examples/synthetic_case \
  --work /tmp/proposal_work \
  --output /tmp/proposal_out

python3 scripts/selfcheck.py \
  --case examples/synthetic_case/case.json \
  --sources /tmp/proposal_work/sources.json \
  --out /tmp/proposal_out
```

预期：`run_case.py` 打印 `status=success ... selfcheck=PASS`，退出码 0；`selfcheck.py` 首行 `PASS`，退出码 0。

## 注意

- 示例只用于结构验证，不证明真实研究的科学性。
- 若把示例替换为真实材料，请删除所有 `SYNTHETIC` 标注并重新核对数字、伦理与引用。
- 示例输出不应作为“标准答案”打包进提交；本目录只保留输入。
