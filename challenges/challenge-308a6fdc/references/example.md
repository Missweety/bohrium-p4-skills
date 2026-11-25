# 最小调用示例（示意，不是正式案例答案）

## 输入（示意）

`case.json`

```json
{
  "case_id": "demo-paper-1",
  "task": "根据实验数据写 Results 与 Figure 1 图注，英文，250 词以内",
  "genre": "journal article",
  "audience": "peer reviewers",
  "output_contract": {"artifact_path": "string", "source_map": "array"}
}
```

`materials/exp.csv`

```csv
group,n,degradation_pct,sd
control,30,12.4,1.1
treated,30,15.8,1.3
```

## 调用（示意）

```bash
SKILL_DIR=/skills/weekly-skill
python3 "$SKILL_DIR/scripts/kernel.py" init --case /input/case.json --out /app/work
python3 "$SKILL_DIR/scripts/kernel.py" index --out /app/work
# 写 /app/work/draft.json（sections + source_map）
python3 "$SKILL_DIR/scripts/kernel.py" build --draft /app/work/draft.json --out /app/work
python3 "$SKILL_DIR/scripts/section_audit.py" --draft /app/work/manuscript.md \
  --map /app/work/source_map.json --corpus /app/work/corpus.txt --out /app/work/audit.json
python3 "$SKILL_DIR/scripts/kernel.py" verify --text /app/work/manuscript.md \
  --evidence-dir /app/work --out /app/work
python3 "$SKILL_DIR/scripts/kernel.py" emit --draft /app/work/draft.json \
  --contract-dir /app/work --work-dir /app/work --out /app/output
python3 "$SKILL_DIR/scripts/kernel.py" check --out /app/output --contract-dir /app/work
```

## 输出（示意）

`manuscript.md` 节选：

```
## Results

Catalytic degradation increased from 12.4% (SD 1.1, n = 30) in the control group to
15.8% (SD 1.3, n = 30) in the treated group under the tested conditions.

Figure 1. Degradation percentage by group. Bars show mean; error bars show SD (n = 30).
```

`source_map.json` 节选：

```json
[{"claim": "control degradation", "value": "12.4", "source_path": "materials/exp.csv", "locator": "row 2, col degradation_pct"},
 {"claim": "treated degradation", "value": "15.8", "source_path": "materials/exp.csv", "locator": "row 3, col degradation_pct"}]
```

说明：示例不含 p 值，因为材料未提供检验结果；若写作需要"显著"，必须先补统计或改写为描述性表述。
