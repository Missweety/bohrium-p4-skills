# 最小调用示例（合成示例，非正式案例）

> 全部为合成数据，只说明接口，不代表任何真实实验室、供应商报价或实测结果。

## 输入

`case.json`（结构化候选 + 资源合同 + 参数域；也支持把方案写在 `plans.md`）

```json
{"case_id": "demo-cmp-001", "task": "比较三条提取路线并选择现在可执行的方案",
 "output_contract": [{"name": "selection", "type": "object"},
                     {"name": "comparison", "type": "array"},
                     {"name": "risk_register", "type": "array"}],
 "candidate_plans": [
   {"id": "A", "objective": "磁珠法提取", "parameters": {"离心转速": "15000 rpm"},
    "resources": ["台式高速离心机"], "cost": 2400, "time": 8,
    "risks": ["剪切损伤（缓解：降速）"], "evidence": ["设备手册：上限 12000 rpm"]},
   {"id": "B", "objective": "直接磁珠富集", "parameters": {"孵育温度": "4 ℃"},
    "resources": ["磁力架"], "cost": 500, "time": 3,
    "risks": ["非特异结合（缓解：增加洗涤）"], "evidence": ["预实验记录：回收率 74%"]},
   {"id": "C", "objective": "密度梯度+磁珠", "cost": 3600, "time": 6,
    "resources": ["密度梯度离心机"], "evidence": ["历史日志：纯度 96%"]}],
 "resource_contract": {"prices": [{"name": "磁珠试剂盒", "unit_price": 1200, "per": "盒", "currency": "元"}],
                       "equipment": [{"name": "台式高速离心机", "available": false, "status": "停机维修"}]},
 "budget": {"amount": 3000, "currency": "元"},
 "parameter_domains": [{"name": "离心转速", "min": 1000, "max": 12000, "unit": "rpm"}]}
```

也可只给 `plans.md`（`## 方案A/B/C` + 七字段）与 `price.md`（`磁珠试剂盒 1200 元/盒`、`预算 3000 元`）。

## 调用

```bash
python3 scripts/run_case.py --case case.json --materials . --work work --out out
```

## 示意输出（节选，来自合成用例实际运行）

```json
{"case_id":"demo-cmp-001","status":"ok","input_mode":"case.json:candidate_plans（3 个结构化候选）",
 "recommendation":{"choice":"selected","plan_id":"B",
   "rationale":"A 因设备停机与 15000 rpm 超上限淘汰；C 成本 3600 元超预算；B 通过全部硬约束"},
 "comparison_matrix":[
   {"plan":"A","feasible":false,"eliminated_by":["资源不可得","参数越界"],"cost_known":2400.0,"currency":"元"},
   {"plan":"B","feasible":true,"field_values":{"objective":["直接磁珠富集"],"parameters":["孵育温度 = 4 ℃"]},"weighted":4.571},
   {"plan":"C","feasible":false,"eliminated_by":["超预算"],"cost_known":3600.0,"currency":"元"}],
 "determinism":{"consistent":true,"runs":2},
 "validation":{"checks":[{"check":"矩阵含七字段实际取值","result":"PASS"},
                         {"check":"重跑一致性","result":"PASS"}]}}
```

`comparison_matrix.csv` 的七字段列保留实际取值，可直接作为评审对照表；成本下限、币种、
淘汰门控与加权分都在列。契约别名（`selection`/`comparison`/`risk_register`）同时回填。
