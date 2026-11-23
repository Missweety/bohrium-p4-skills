
## 1.3.0 失败链与止损优先级回归（2026-11-23，/tmp/expchain 合成方案）

| 用例 | 实跑结果 |
|-|-|
| 六步方案 + 3 条 risks + 窗口 14h | steps=6 risks=3 unmapped=3 p0=3 overrun=True |
| P 级判定 | S2/S3 有备选 → P1；S4 无备选且阻塞后续 → P0；S1/S5 无风险映射 → 列入 unmapped |
| 重试算术 | 计划 15.0h + P0/P1 各重试一次 9.0h = 24.0h > 14.0h，余量 -10.0h，明确判超窗 |
| 产物 | failure_chain.json + failure_chain.md（步骤/信号/判据/止损/备选/阻塞/优先级） |
