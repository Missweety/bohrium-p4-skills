# 示意输入/输出（示例，非正式案例答案）

以下设备、价格、数据均为**虚构合成示例**，仅说明接口，不代表任何真实实验室、报价或安全结论。

## 1. 输入

`/input/case.json`（示意）：

```json
{"case_id": "demo-design-001",
 "task": "在 3 周、5000 CNY 预算与现有设备条件下，设计验证涂层疏水性提升的实验方案，给出三版候选",
 "materials": ["/input/materials/background.md", "/input/materials/equipment.md", "/input/materials/prices.csv"],
 "output_contract": {"plan": "object", "plan_versions": "array", "recommendation": "object",
                     "parameter_basis": "array", "resource_arithmetic": "object"}}
```

材料（示意）：`equipment.md` 写 "Hot plate HP-1: 40–120 C; fume hood available 14 h/week"；
`prices.csv` 写 `precursor_A,100mL,320`、`solvent_S,500mL,180`。

## 2. 中间文件 `work/plan.json`（示意，节选）

```json
{"goal": "验证循环浸涂能否在 3 次内把接触角提高到 >90 度",
 "hypothesis": {"statement": "3 次循环浸涂使接触角较未涂层提高 ≥30 度",
   "direction": "increase", "falsify_if": "处理组与 vehicle 组差值 <10 度且 CI 跨 0",
   "endpoint": "静态水接触角（度）"},
 "variables": {
   "independent": [{"name": "循环次数", "levels": [0, 1, 3], "operational": "浸涂 60 s 后 80 C 固化 10 min，重复 n 次"}],
   "dependent": [{"name": "接触角", "instrument": "接触角仪 CA-1", "unit": "deg", "sampling": "每片 3 点取均值"}],
   "confounders": [{"name": "批次", "control": "同日同批基片，随机分配处理顺序"}]},
 "controls": [
   {"type": "vehicle", "design": "同体积溶剂 S，同固化程序", "excludes": "溶剂与热处理本身的效应"},
   {"type": "positive", "design": "商用疏水涂层 P", "excludes": "检测体系无响应能力"}],
 "sample_size": {"n_per_group": 6, "groups": 3, "basis": "assumed", "inputs": {},
   "effect_size_source": "无材料内效应量，按 assumed 处理", "technical_replicates": 3, "biological_replicates": 6},
 "parameters": [
   {"name": "固化温度", "value": "80", "unit": "C", "range": "40-120", "basis": "equipment_spec",
    "source": "equipment.md: Hot plate HP-1 40-120 C", "action": ">90 C 改程序降温", "assumption": "", "sensitivity": ""},
   {"name": "固化时间", "value": "10", "unit": "min", "range": "5-20", "basis": "assumed",
    "source": "", "action": "低于 5 min 判为不合格批次", "assumption": "按同类工艺经验取 10 min", "sensitivity": "±5 min 时重测接触角"}],
 "resources": {
   "equipment": [{"name": "热板", "model": "HP-1", "needs_h": 9, "available_h": 14}],
   "consumables": [{"item": "precursor_A", "spec": "100mL", "qty": 3, "unit_price": 320, "currency": "CNY"},
                   {"item": "solvent_S", "spec": "500mL", "qty": 2, "unit_price": 180, "currency": "CNY"}]},
 "budget": {"total": 1320, "cap": 5000, "currency": "CNY"},
 "schedule": {"sessions": 3, "hours_per_session": 3, "total_hours": 9, "window_hours": 14},
 "risks": [{"mode": "无信号", "indicator": "阳性对照接触角 <80 度", "threshold": "连续 2 批",
   "stop_loss": "停批排查涂层液", "fallback": "换批号并重跑阳性对照"}],
 "versions": [
   {"id": "A", "label": "基线", "n_per_group": 6, "cost": 1320, "hours": 9, "changes": "无"},
   {"id": "B", "label": "省预算", "n_per_group": 4, "cost": 900, "hours": 7, "changes": "减少循环水平至 2 组"}],
 "recommendation": {"id": "A", "rationale": "预算与时间窗内保住阳性对照与 3 个水平", "sacrifice": "未增加生物学重复"},
 "confirmations": [{"item": "设备可用性", "owner": "实验室管理员", "why": "热板排期需确认"}]}
```

（示例为节选：实际方案需 3 条以上风险、3 版候选、≥3 个参数，否则校验会报错。）

## 3. 校验（示意）

```bash
python scripts/design_checklist.py --plan work/plan.json --corpus work/corpus.txt --out work
# verdict=review errors=2
#   ! versions < 3: need baseline/budget/power candidates
#   ! risks < 3: failure modes are not covered
```

算术行：耗材小计 3×320 + 2×180 = 1320 = budget.total ≤ cap 5000；总工时 3×3 = 9 ≤ 14。

## 4. `result.json`（示意，节选）

```json
{"case_id": "demo-design-001", "status": "partial",
 "plan": {"hypothesis": {"falsify_if": "处理组与 vehicle 组差值 <10 度且 CI 跨 0"}},
 "parameter_basis": [{"name": "固化温度", "value": "80", "unit": "C", "basis": "equipment_spec",
                      "source": "equipment.md", "assumed": false, "sensitivity": ""}],
 "resource_arithmetic": {"consumables_subtotal": 1320, "budget_total": 1320, "budget_cap": 5000,
                         "equipment_hours": 9, "window_hours": 14},
 "limits": "仅 2 版候选、1 条风险，未达交付线；缺设备排期原件",
 "uncertainty": ["固化时间为 assumed，±5 min 需复核", "无材料内效应量，样本量为假设"]}
```

注意：不存在的预实验、设备报价或安全批准一律不写；`assumed` 参数在 `uncertainty` 中有对应条目。
