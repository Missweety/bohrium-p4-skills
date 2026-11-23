# 最小示例（全部为合成数据，不是官方评测案例）

目标：用一份 CSV + 一份 bib 写出 Results，并让每个数字可回溯。

## 材料

`/input/materials/exp.csv`

```csv
group,n,degradation_pct,sd
control,30,12.4,1.1
treated,30,21.7,1.3
```

`/input/materials/refs.bib`

```bibtex
@article{smith2020,
  author={Smith, Jane and Lee, Wei},
  year={2020},
  title={Catalytic degradation of model dyes},
  journal={Journal of Catalysis},
  volume={382},
  pages={45--53},
  doi={10.1016/j.jcat.2020.01.001}
}
```

`/input/case.json`

```json
{"case_id":"demo","task":"Write the Results section with a Figure 1 caption and references.",
 "language":"en","materials":["materials"],
 "output_contract":{"artifact_path":"manuscript.md","source_map":[],"uncertainty":[],
                    "changes":[],"limits":"","self_check":{}}}
```

## 命令

```bash
python scripts/kernel.py init --case /input/case.json --out work
python scripts/kernel.py index --case /input/case.json --out work
# 读 work/facts.json 后写 work/draft.json（见下）
python scripts/kernel.py build --draft work/draft.json --out work
python scripts/section_audit.py --draft work/manuscript.md --map work/source_map.json \
  --template work/section_template.json --corpus work/corpus.txt --plan work/draft.json \
  --references work/references.json work/references.auto.json --todo work/todo.md \
  --out work/audit.json
python scripts/kernel.py verify --text work/manuscript.md --evidence-dir work \
  --plan work/draft.json --out work
python scripts/kernel.py emit --draft work/draft.json --contract-dir work --work-dir work \
  --audit work/audit.json --source-map work/source_map.json --out /app/output
python scripts/kernel.py check --out /app/output --contract-dir work
```

## `work/draft.json` 关键片段

```json
{
  "case_id": "demo",
  "status": "ok",
  "title": "Catalytic degradation of a model dye",
  "sections": [
    {"heading": "Results", "paragraphs": [
      {"text": "Control degradation was 12.4% (SD 1.1, n = 30); treated degradation was 21.7% (SD 1.3, n = 30). Figure 1 shows the group means."}
    ]}
  ],
  "figures": [
    {"label": "Figure 1", "caption": "Group means with SD error bars (n = 30).",
     "section": "Results", "source_path": "/input/materials/fig1.png", "locator": "whole image"}
  ],
  "references": [
    {"key": "smith2020", "authors": "Smith, Jane and Lee, Wei", "year": "2020",
     "title": "Catalytic degradation of model dyes", "venue": "Journal of Catalysis",
     "volume": "382", "pages": "45-53", "doi": "10.1016/j.jcat.2020.01.001"}
  ],
  "source_map": [
    {"claim": "control degradation", "value": "12.4", "source_path": "/input/materials/exp.csv", "locator": "row 2, col degradation_pct"},
    {"claim": "control SD", "value": "1.1", "source_path": "/input/materials/exp.csv", "locator": "row 2, col sd"},
    {"claim": "sample size", "value": "30", "source_path": "/input/materials/exp.csv", "locator": "row 2, col n"},
    {"claim": "treated degradation", "value": "21.7", "source_path": "/input/materials/exp.csv", "locator": "row 3, col degradation_pct"},
    {"claim": "treated SD", "value": "1.3", "source_path": "/input/materials/exp.csv", "locator": "row 3, col sd"}
  ],
  "uncertainty": [],
  "limits": ""
}
```

## 期望

- `work/manuscript.md`：`## Results` 正文 + `Figure 1. Group means ...` + `## References`；
- `work/audit.json`：`verdict=pass`（若 DOI 缺失只会 WARN）；
- `/app/output/`：`result.json`、`manuscript.md`、`source_map.json/csv`、`audit.json`、`todo.md`；
- `kernel.py check` 输出 `PASS`。

## 缺数据与冲突的写法

```text
【待补：treated degradation value｜exp.csv row 3 is empty】
【待核：treated degradation 21.7 vs 18.2】
```

分别登记：

```json
{"type":"missing_material","where":"Results paragraph 1","what":"treated degradation value",
 "why":"exp.csv row 3 is empty","next_step":"作者补数"}
{"type":"conflict","where":"Results paragraph 1","what":"treated degradation 21.7 vs 18.2",
 "why":"exp.csv 与 notes.md 不一致","next_step":"作者确认权威记录"}
```

并在 `conflicts` 中保留 `values: ["18.2","21.7"]`。审计对未登记的占位/冲突判 FAIL。
