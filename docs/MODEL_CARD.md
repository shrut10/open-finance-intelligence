# CPI next-observation model card

## Purpose and status

An educational forecasting service estimating the **next monthly observation of UK annual CPI inflation**. At the initial snapshot, August 2026 CPI is observed and September 2026 is the target. Because the previous month's CPI is only released during the target month, this is a **current-month nowcast / next-observation forecast**, not a forecast issued before that month begins.

**The validation-selected gradient-boosting model fails to beat persistence on the test period. It is a research demonstration, not a decision-ready model.** The interface and API retain this result openly. No trading, investment or monetary-policy recommendation is made.

## Data and available information

Four official series: ONS CPI D7G7, ONS unemployment MGSX, BoE monthly Bank Rate IUMABEDR and M4 stock LPMAUYM. See [DATA.md](DATA.md) for source links, licence, coverage and revisions.

For target reference month `t`, features are:

- CPI lags 1, 2, 3, 6 and 12; lagged one-month change; mean of lags 1–3.
- Bank Rate at lag 2 and its change from lag 5.
- M4 12-month stock growth at lag 2 (lag-2 stock divided by lag-14 stock).
- Unemployment centre month at lag 4 and its change from lag 7.
- Target-month sine and cosine, which are calendar information known in advance.

There are 14 features. No imputation, backward fill, future observation or same-target CPI is used. A complete monthly grid is enforced before shifting so a missing month cannot silently shorten a lag. Missing next-forecast inputs stop the build. Rate/M4 lags and the longer labour lag approximate reporting delays. The snapshot nevertheless contains revised history; this is **not a vintage-correct backtest**. Tests establish feature causality, not historical release-time correctness.

## Fixed chronological experiment

| Stage | Reference months | Role |
|---|---|---|
| Training | Jan 1990–Dec 2018 | Fit all candidates, including training-only scaling |
| Validation | Jan 2019–Dec 2021 | Select lowest MAE; estimate empirical error interval |
| Test | Jan 2022–Aug 2026 | 56 untouched outcomes; no selection or calibration |

Candidates were fixed before examining results:

1. Persistence: repeat the previous CPI annual rate.
2. Seasonal naive: repeat the annual rate from twelve months earlier.
3. Ridge regression, alpha 10, StandardScaler fitted only on training observations.
4. Histogram gradient boosting, 150 iterations, learning rate 0.05, 7 leaf nodes, L2 10, no early stopping, seed 42.

Lowest validation MAE selects the served model. Candidates are then refitted once through December 2021 and evaluated with **rolling one-step inputs and fixed parameters** across the test. Each test prediction may use previously observed test-period CPI lags, which is appropriate for a one-step forecast. It is not an August-2026 multi-year projection from 2021. The final deployed estimate refits the selected family on all observed labelled rows, after the experiment is recorded. Serving reads precomputed JSON; it does not train or accept arbitrary forecast horizons on a web request.

## Measured results

Errors are **percentage points of annual CPI inflation**, not percentages of error. Results below are the initial committed snapshot; the API artifacts are authoritative after a refresh.

| Candidate | Validation MAE | Test MAE | Test RMSE |
|---|---:|---:|---:|
| Persistence | 0.347 | 0.405 | 0.602 |
| Seasonal naive | 1.297 | 3.554 | 4.395 |
| Ridge regression | 0.347 | 0.393 | 0.546 |
| Gradient boosting — validation selection | 0.343 | 1.054 | 1.671 |

Gradient boosting's validation advantage is very small. Its frozen post-2021 predictions underperform during a test period containing inflation outside much of the training distribution. Trees' inability to extrapolate far beyond their learned response range is one plausible explanation; the experiment alone does not identify a unique cause. The served family was **not retrospectively switched to ridge because ridge looked better on the test**. A later experiment would need a fresh evaluation protocol and genuinely unseen observations.

The September 2026 initial estimate is approximately **2.981% year on year** with a **1.819–4.143% empirical interval**. This is model output, not an official forecast. Do not report it as demonstrated forecasting skill.

## Uncertainty and interpretation

The interval radius is an upper empirical quantile of the selected model's 36 validation absolute errors, using a finite-sample quantile adjustment and `higher` quantile interpolation. The same frozen radius is applied across test predictions. Its nominal target is 90%, but measured test coverage is **71.4%**. Model refitting, non-exchangeable time-series errors and structural shifts prevent a coverage guarantee. This is an empirical residual interval, not a proven calibrated probabilistic distribution.

Permutation importance reports the increase in held-out MAE when a feature is shuffled in contiguous three-month blocks, repeated 30 times with seed 42. Negative values are retained rather than clipped. This preserves a little within-block structure but can still produce unrealistic combinations, particularly among highly correlated CPI lags. It measures prediction sensitivity, not economic causality. Both the selected model's importance and the best learned candidate's importance are stored (they coincide in this initial experiment).

## Reproducibility and boundaries

`python scripts/train.py` writes `artifacts/forecast.json`, `artifacts/model_evaluation.json` and `artifacts/model_manifest.json`. They include source snapshot identity, version, parameters, library versions, training-code hash, chronological split, all baseline metrics, test predictions, interval coverage and importance. No opaque pickle is served. Pinned dependencies plus the exact raw snapshot reproduce the experiment, subject to small platform-level floating-point differences.

Automated tests cover publication-lag arithmetic, the inability of future observations to change past features, missing-month handling, split order, selection based on validation, metric arithmetic and forecast/version consistency.

Next scientifically useful work would be true historical vintage retrieval, explicit release calendars, multiple prespecified expanding-window origins and monitoring of new post-launch observations. These are limitations, not implemented claims. No model retraining or data refresh occurs silently during an API request.
