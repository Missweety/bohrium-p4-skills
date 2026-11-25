# Demo（合成材料，非真实论文）

本目录材料可复现一次真实运行：

```bash
mkdir -p /tmp/demo_repro/input/materials /tmp/demo_repro/out /tmp/demo_repro/work
cp examples/demo_case.json /tmp/demo_repro/input/case.json
cp examples/demo_paper.md /tmp/demo_repro/input/materials/paper.md
python3 scripts/run_case.py --input /tmp/demo_repro/input \
  --work /tmp/demo_repro/work --output /tmp/demo_repro/out
```

当前实现的实测结果（合成材料，非竞赛分数）：

- `status=success`
- 复算 `t(28)=2.45 → p=0.020797`，与报告 `p = 0.02` 在 0.005 容差内一致；
- 复算 `t(28)=1.10 → p=0.280702`，与报告 `p = 0.28` 一致；
- `82.4 → 79.1` 复算 `-4.0049%`，与报告 `4.0% reduction` 一致（按幅度比较）；
- 计划五类（data/environment/parameters/commands/code）均有原文依据；
- `audit.pass=true`。

反例（本目录不含，可自行构造）：把 `p = 0.02` 改成 `p = 0.20`，判定应变为
`recomputed_inconsistent` 并进入 `conflicts`，同时整体 `status=partial`。
