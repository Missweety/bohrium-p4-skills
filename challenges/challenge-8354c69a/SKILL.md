---
name: evidence-based-experiment-results
description: Interpret experimental measurements, compare computational estimators, and investigate anomalies using actual source files and reproducible calculations.
metadata:
  version: 2.1.0
---
# Interpret the actual experiment

Read `/input/case.json`, `/input/task.md`, `environment/resources.yaml` and all actual source files. Execute the case's exact analysis and output_contract; save `/app/output/result.json` with all required fields, case_id, source locations, status, limitations and paths to real outputs. Keep raw files unchanged and use `/app/work` for intermediate work. This skill applies to actual bending traces, a five-split/two-estimator Iris experiment, Cefixime multi-sheet workbooks, and other experimental results. The model must do scientific interpretation, not merely hand the user an inventory. Do not invent observations, units, quality-control thresholds, experimental replication, numerical outcomes or causes.

## One-command orchestration

```bash
python3 scripts/run_case.py --case /input/case.json --materials /input \
  --work /app/work --out /app/output
```

`run_case.py` is deterministic (no timestamps/random seeds) and needs only the Python standard library for curves/tables; `openpyxl` is used for workbooks and `scikit-learn` only for the explicit classification experiment. It:

1. inventories the material tree (sha256, size, suffix) and excludes its own `--work`/`--out` dirs plus previously written artifact names, so reruns cannot re-ingest their own output;
2. parses every CSV/TSV with delimiter sniffing, keeps real row numbers, infers or honours explicit x/y columns, and optionally splits grouped data (one group column → one trace per specimen);
3. computes per-trace first/last/peak, OLS slope, secant slope and normalized area, plus saturation and post-peak-drop notes;
4. flags point deviations with a **neighbourhood quadratic-fit residual** (robust z + ≥5% of range), not a global median on a rising trace, and flags cohort outliers only when |robust z| ≥ 3.5 **and** relative deviation ≥ 10%;
5. inspects workbooks with both `data_only=False/True`, counting formula cells and missing caches (unknown until recalculated, never zero);
6. reads the classification experiment (features/label/seeds/test_size/models) and delegates to `classify.py`; those data files are excluded from curve statistics;
7. writes `result.json` plus `curve_summary.csv`, `anomaly_list.csv`, `report.md` (relative paths in `artifacts`).

`result.json` fields: `case_id`, `status`, `analysis_type`, `trend`, `metrics`, `anomalies`, `causes`, `verification`, `next_experiments`, `classification`, `workbooks`, `tables`, `sources`, `inputs`, `uncertainty`, `limits`, `artifacts`, `changes`, `validation.checks`, `output_contract_fields` (plus any declared contract field, filled or set `null` with an explanation). Every anomaly carries `source`, `row` and `threshold` so it can be re-checked by hand.

Status semantics: `ok` = all requested analyses ran on parsed data; `partial` = usable results but at least one honest gap (unparsed file, invalid `case.json`, missing formula cache, missing optional dependency, unconfigured classification); `blocked` = no usable input at all. A missing `scikit-learn` yields `partial` with the dependency named — never invented metrics.

## Resolve the workorder and materials

Inventory every file and sheet; inspect headers, units, data dictionary, comments, case instructions and scripts before choosing columns or aggregation. Run `python3 scripts/inspect_data.py --input /input --out /app/work/inventory.json` for file SHA256, workbook sheet names/shape/cell previews, CSV header/shape, and MATLAB array names/shapes. It does not extract scientific meaning. Large spreadsheets may require sampling, then directly inspect all pertinent rows. Include unreadable/missing files in limitations. Do not use generated files as new input.

### Bending curves

Match each trace to its real sample workbook row and any MATLAB script by observed filenames/IDs; preserve unmatched, duplicate, missing and conflicting records. Verify 197 is expected only if the case says so; compute actual counts. Read the actual raw trace units, gauge geometry, calibration, specimen dimensions, sampling and any supplied original analysis script. Use each specified original method to calculate force, displacement, stress/strain or derived metrics as actually supported; do not convert machine displacement into strain or call a force slope modulus without the required geometry. Identify anomalies relative to appropriate controls, sample/batch and documented thresholds; a global MAD on a rising trace alone is not proof of an outlier. Check drift, saturation, break/slip, missing channels and transposition as competing hypotheses, not diagnoses. Save per-specimen CSV of reproducible metrics with source file and workbook row, exceptions with quantified values/threshold/basis, and a reviewable plot of representative original curves with axes and units. Verify at least one calculation independently, including unit factors. Use available SciPy to read real MAT arrays; v7.3 needs h5py or report partial.

### Explicit computational Iris experiment

When requested execute *the actual five train/test splits and two named estimators*, using the supplied source data, features, labels, seeds, split proportions and estimator parameters. If those are explicitly stratified random splits and the named models are KNN and logistic regression, `python3 scripts/classify.py --data /input/data.csv --plan /app/work/plan.json --out /app/work/classification.json` can execute the analysis. Its plan specifies features, label, five seeds, test_size, standardize and two models with sklearn parameters. It is a helper for this exact design, not a replacement for case-specific fixed assignments or other estimators. If absent, distinguish a clearly labeled exploratory configuration from missing required settings. Fit imputation/scaling on each training subset only using a pipeline. Use sklearn when present; report unavailable dependency as partial rather than inventing metrics. Record per split and model train/test row IDs, class counts, predictions, confusion matrix and per-class/macro/overall accuracy as requested; compute means and variation across five splits with the correct denominator. Compare the same split across models, check leakage, missing values, labels and class stratification; report that five splits are computational repeats, not five independent biological replicates. If task supplies fixed data or assignments use them rather than silently resplitting.

### Cefixime workbook and full paper

Enumerate and inspect **all actual sheets** plus the supplied full paper. Identify which sheets are raw observations, calculation tables, metadata, standards and summaries; retain exact sheet/cell/row references, units, treatment, time, replicates, blanks and formula-vs-cached-value distinction. Use openpyxl `data_only=False` and `data_only=True`; missing formula caches are unknown until legitimately recalculated, not zero. Map paper methods, calibration, thresholds and table/figure claims to workbook data; independently recompute specified transformations only when units, coefficients and denominator are present. Compare controls and replicates within the right group, preserve conflicting units, values or ambiguous thresholds and never substitute an invented value. Qualify explanations and record alternative causes/verification actions.

## General interpretation and outputs

Separate observations, derived values, candidate mechanisms, missing information and recommended checks. Use the case's actual test and thresholds when specified; avoid automatic global thresholds and fabricated confidence numbers. Every important conclusion must connect to raw file, sheet/cell or row, source figure/page, method, relevant grouping and uncertainty. Address trend, anomalies, plausible explanations and counterevidence, actionable verification and next step. If a necessary method, unit or source is missing, give useful partial results and clearly mark what remains unsupported. Use the helper scripts only for their intended scope; inspect their output, independently recalculate and perform missing work. Search/index output is not a final answer. Put real artifacts (summary tables, code, report, plots, result.json) in `/app/output` and verify result field names/types exactly against the runtime contract. Never use an old output after a failed command. Record dependencies/versions and any source changes in output. Do not claim platform score or hidden-case validation.

## Minimal invocation (synthetic example)

`python3 scripts/inspect_data.py --input /input --out /app/work/inventory.json` gives a factual materials inventory; read it and the actual data before calculations. `python3 scripts/curve_stats.py --csv /input/curve.csv --x displacement_mm --y force_N --out /app/work/curve.json` reports source-bound first/last, regression slope and peak for explicitly named numeric columns. This example is illustrative, not a formal case or a modulus calculation. For a synthetic or public Iris example plan: `{"features":["a","b","c","d"],"label":"target","seeds":[1,2,3,4,5],"test_size":0.2,"standardize":true,"models":[{"name":"knn","params":{"n_neighbors":5}},{"name":"logistic","params":{"max_iter":500}}]}`. This is not a formal case configuration. For any other requested design/estimators implement the actual method and inspect and save outputs rather than guessing model defaults.

## Change log

- **2.1.0** (2026-11-25) Reproduced against real fixtures and fixed:
  1. baseline had no end-to-end case driver — added deterministic `scripts/run_case.py` producing `result.json` + `curve_summary.csv` + `anomaly_list.csv` + `report.md` with trend / anomaly / cause / verification / next-experiment fields;
  2. rerunning inside the material tree re-ingested its own `out/` artifacts and broke determinism → exclude `--work`/`--out` and artifact names (verified identical sha256 across two runs);
  3. a rising trace fooled a global Hampel test and missed the injected spike → replaced with a neighbourhood quadratic-fit residual plus a σ floor (also removes `robust z=2.9e12` blow-ups);
  4. cohort MAD collapsed to 0 on a 2% peak difference, flagging a false outlier → require both |robust z| ≥ 3.5 and ≥10% relative deviation, with std fallback;
  5. a classification CSV was also parsed as a curve and the classifier could not find the file from another cwd → resolve paths to absolute and exclude the classification data from curve stats;
  6. missing `scikit-learn` produced a raw traceback as the note → report `partial` naming the missing optional dependency, no invented metrics;
  7. anomaly thresholds with `|...|` broke the Markdown table and duplicate verification steps were emitted → escaped cells and de-duplicated steps;
  8. non-UTF-8 CSV decoded silently into garbled headers → recorded an explicit encoding note per trace;
  9. commands documented as `python` → unified to `python3`.
- **2.0.0** prior baseline: inspection / curve / classification helper scripts and the interpretation contract.
