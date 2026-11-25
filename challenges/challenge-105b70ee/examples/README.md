# Demo（合成材料，非真实论文）

`demo_case.json` 内含 `target_fields`，运行时不需要额外的 `target-fields.json`。
把下面的 `demo_paper.md` 放到临时输入目录，即可复现一次真实运行：

```bash
mkdir -p /tmp/demo_extract/input/materials /tmp/demo_extract/out /tmp/demo_extract/work
cp examples/demo_case.json /tmp/demo_extract/input/case.json
cp examples/demo_paper.md /tmp/demo_extract/input/materials/paper.md
python3 scripts/run_case.py --input /tmp/demo_extract/input \
  --work /tmp/demo_extract/work --output /tmp/demo_extract/out
```

预期（demo 材料下，由当前实现实际产生）：

- `status=success`
- `sample_size=240`（`¶2`）
- `mean_reduction=1.42`、`unit=mmol/L`（`¶4`）
- `ci_95=1.10-1.74`（`¶4`）
- `comparator=placebo`（`¶4`）
- `author_conclusion=the intervention was effective ...`（`¶6`）
- `audit.pass=true`

注意：以上是合成示例的实测行为，不代表任何竞赛得分或隐藏案例表现。
