# SMOKE - challenge-7be76e91（实验方案比较）

环境：本地合成夹具，**非平台正式案例/标准答案**；Python 3.13，仅标准库。

## 正向（结构化候选，/tmp/t2a）

用例见 `references/example.md`（3 方案 + 资源合同 + 预算 3000 元 + 参数域）。

```bash
python3 scripts/run_case.py --case /tmp/t2a/case.json --materials /tmp/t2a --work /tmp/t2a/w --out /tmp/t2a/o
```

实际结果：`status=ok`，`choice=selected`，`plan_id=B`，`weighted=4.571`；
A 淘汰（资源不可得 + 15000 rpm > 12000 rpm），C 淘汰（3600 元 > 3000 元）；
`determinism.consistent=true`（两次草稿/矩阵 sha1 相同）；契约别名 `selection/comparison/risk_register` 回填。

## 对抗夹具（均实跑）

| 夹具 | 输入 | 修复后期望/实际 |
|-|-|-|
| /tmp/t2b | 10 个结构化候选 | 10 个全部比较（原版静默截断到 8） |
| /tmp/t2h | 21 个候选 | 比较前 20，`status=partial`，`limits` 写明其余 1 个未纳入 |
| /tmp/t2c | `cost={amount:5000, items:[缺价]}` + 预算 3000 | 总额 5000 生效 → 超预算淘汰（原版丢总额放行） |
| /tmp/t2f | `cost=1 万元`、`time={value:2,unit:weeks}`、窗口 10 天 | 归一为 10000 元、14 天 → 超预算淘汰（原版按 1 天/0.29 天放行） |
| /tmp/t2d | 两方案成本/工期完全相同 | 同值同分 5.0/5.0、`weighted` 均 4.7，舍弃理由写"并列"（原版按顺序 5 vs 2） |
| /tmp/t2g | 重复 id + `available:"false"` | id 加 `#2`；设备 `"false"` 触发资源不可得 |
| /tmp/t2i | 空 materials、case 无候选 | `status=blocked`，不产出假选择 |
| /tmp/t2j | 文本 `总工期：2 周` / `5 天` | 14.0 / 5.0 天 |

## 校验

```bash
python3 validators/validate_submission.py --outputs tracks/experimental-design/challenges/challenge-7be76e91/05_skills_iter3 --json
```
