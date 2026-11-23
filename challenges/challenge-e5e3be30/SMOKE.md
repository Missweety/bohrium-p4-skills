# SMOKE - evidence-trace-verifier v2.0.0

说明：以下使用 `tests/fixtures/` 中的**合成教学样例**（两篇自造摘要，非真实文献、非平台案例）验证
脚本链路与判定门禁；不代表平台评分，也不作为评分依据。

## 正向链路（全部实际执行）

```
python3 scripts/kernel.py init   --case /tmp/smoke_e5/input/case.json --out /tmp/smoke_e5/work
python3 scripts/kernel.py claims --claims /tmp/smoke_e5/input/claims-to-verify.json --out /tmp/smoke_e5/work
python3 scripts/kernel.py index  --materials /tmp/smoke_e5/input --exclude claims-to-verify.json case.json --out /tmp/smoke_e5/work
python3 scripts/claim_evidence_matrix.py --matrix /tmp/smoke_e5/work/matrix.json --corpus /tmp/smoke_e5/work/corpus.txt \
    --out /tmp/smoke_e5/work/matrix_report.json --md /tmp/smoke_e5/out/claim_evidence.md \
    --base /tmp/smoke_e5/input --claims /tmp/smoke_e5/work/claims.json
python3 scripts/kernel.py emit  --draft /tmp/smoke_e5/work/draft.json --contract-dir /tmp/smoke_e5/work --out /tmp/smoke_e5/out
python3 scripts/kernel.py check --out /tmp/smoke_e5/out --contract /tmp/smoke_e5/work/contract.json
python3 scripts/kernel.py verify --text /tmp/smoke_e5/out/claim_evidence.md --evidence-dir /tmp/smoke_e5/work --out /tmp/smoke_e5/work
```

实测输出：

```
claims=5 multi_component=1
ok 585 paper_a.md / ok 184 paper_b.md
verdict=pass claims=5 supported=1 partially_supported=1 contradicted=1 insufficient_evidence=2 errors=0 warnings=0
result.json written; missing_contract_fields=none
PASS  = status=ok claims_ref=claim_evidence.md
verdict=pass unsupported_numbers=0 citations_not_in_sources=0
```

覆盖点：复合句拆分（C5）、比较方向（C1/C3/C5）、未纳入亚组判 insufficient（C2）、
外推未验证判 insufficient（C4）、无统计学意义判 contradicted（C3）、部分支持写缺口（C5）。

## 负向门禁（实际执行，均 exit=1）

| 注入缺陷 | 期望错误 | 实测 |
|-|-|-|
| 使用 v1 标签 `partial` | legacy_verdict | exit=1 ✓ |
| contradicted 但无 contradicts 证据 | contradicted_without_contradiction | exit=1 ✓ |
| insufficient_evidence 却带证据 | insufficient_with_evidence | exit=1 ✓ |
| 编造引文 | quote_not_in_cited_source + quote_not_verbatim | exit=1 ✓ |
| 遗漏 claims 中的 C5 | claim_not_verified | exit=1 ✓ |
| 把外推判成 contradicted | extrapolation_as_contradiction | exit=1 ✓ |
| gaps 指向 supported 论断 | gaps lists C1 but its verdict is not insufficient_evidence | exit=1 ✓ |
| metrics.claims 与 verdicts 行数不符 | metrics.claims=4 but verdicts has 5 rows | exit=1 ✓ |
| verdicts 使用旧标签 | verdicts[0] bad verdict 'partial' | exit=1 ✓ |
| claim_evidence.md 缺少对应行 | claim_evidence.md missing row for C9 | exit=1 ✓ |
| claims 文件为空 | blocked: no claims parsed | exit=2 ✓ |

## 默认契约与文件保护（实际执行）

- 删除 `case.json` 的 `output_contract` 后重跑：`init` 自动使用默认契约，最终 `check` 仍 `PASS`，
  `result.json` 包含全部 11 个默认字段。
- `kernel.py verify` 输出写入 `work/claims_numbers.json`，复跑后 `work/claims.json` 仍保留
  `count=5` 与原始 claims，未被覆盖。

## 未验证事项

- 未在平台真实案例上运行（平台案例仅评测期可访问），本文件不声明任何平台得分。
- PDF/扫描件走 `pdftotext`/`pypdf`，若环境缺失则按 `unreadable` 降级；该路径未在合成样例中覆盖。
