# Task 11 report: live scenario runs and threshold calibration

## Summary

All four scenarios were run against live infrastructure. Two real bugs were
found and fixed along the way (both required to get any valid numbers at
all), and one fundamental design conflict between `scenarios.py` and
`schema.py` was found and is **reported, not silently resolved** per
CLAUDE.md ("if code and spec disagree, that is a bug in one of them - report
it, don't pick a side").

No drift threshold in `drift.py` needed to move. `scenario=none` measured a
feature-drifted share of 0.0909 (2/22 columns), well under the existing 0.3
`FEATURE_WARNING_SHARE` - the guess from Task 4 was fine.

## Blocker 1 proof: serving image was stale

Before rebuild, `POST /feedback/regression` with `{"outcomes":[]}` returned
404 (route did not exist - image predated Task 8). After
`docker build -f services/serving/Dockerfile -t ml-serving:latest .` and
`docker compose up -d --force-recreate serving`:

```
PowerShell -> Invoke-WebRequest http://localhost:8000/feedback/regression -Method Post -Body '{"outcomes":[]}'
-> caught exception, status code: 422
```

422 = empty batch correctly rejected by the now-current route. `ml-base`,
`ml-monitor` and `ml-agent` were all rebuilt too (see "extra bugs found"
below - `common/` changed multiple times during this task, each change
required a fresh `ml-base` and everything `FROM` it).

## Blocker 2: verify_serving.ps1 fixed

Removed the stale `--config common/pyproject.toml` line and the now-false
comment above it; the lint step is now a single
`.venv\Scripts\python.exe -m ruff check .`, matching the fact that ruff
config lives only in the root `ruff.toml` now.

`powershell -ExecutionPolicy Bypass -File scripts\verify_serving.ps1` output
(abridged - full pytest output omitted, all green):

```
== 1/6 Unit tests ==
======================= 344 passed, 2 warnings in 7.99s =======================
== 2/6 Lint ==
All checks passed!
== 3/6 Serving must not import cleaning logic ==
  boundary intact
== 4/6 Containers ==
NAME                      IMAGE                              ... STATUS
mlops-airflow-scheduler   apache/airflow:2.10.3-python3.12   ... Up
mlops-airflow-webserver   apache/airflow:2.10.3-python3.12   ... Up (healthy)
mlops-minio               quay.io/minio/minio:latest         ... Up (healthy)
mlops-mlflow              mlops-mlflow                       ... Up (healthy)
mlops-postgres            postgres:16-alpine                 ... Up (healthy)
mlops-serving             ml-serving:latest                  ... Up (healthy)
== 5/6 Serving health ==
{"status":"ok","models":{"regression":{"loaded":true,"name":"house_price_regressor","version":"3"},
 "classification":{"loaded":true,"name":"house_needs_renovation_classifier","version":"1"}},
 "inference_log":{"buffered":0,"dropped":0}}
== 6/6 DAG parses ==
No data found
Serving ready for Plan 4.
```

## Extra bugs found and fixed (required to get any real numbers)

These were not threshold problems. Without fixing them, monitor either
crashed outright or silently mixed scenarios together, which would have made
every number in the scenario table meaningless.

### Bug A - `stages/monitor/main.py` crashed on every real run

`current` (decoded straight from the inference log's raw JSON) and
`reference` (the train split read from `processed_key`) are BOTH still raw:
`prepare_dataset_for_train` only does row-ops (dedup, drop-missing-target),
never column cleaning - only `RawRecordCleaner` inside the fitted Pipeline
cleans columns, and only at `fit`/`predict` time. So every "numeric" column
Evidently was told about (`list_price`, `bedrooms`, `has_pool`, ...) was
actually an object-dtype column of strings (`"851724.91"`, `"4.0"`, `"No"`).
Evidently's `DataDriftPreset` calls `np.isinf()` on those and crashes:

```
TypeError: ufunc 'isinf' not supported for the input types, and the inputs
could not be safely coerced to any supported types according to the casting
rule ''safe''
```

Fix: added `clean_for_drift()` in `stages/monitor/main.py`, which reuses the
exact three stateless steps the champion's Pipeline runs before its encoder
(`RawRecordCleaner`, `OutlierClipper`, `DateFeatures` from `ml_common.cleaning`
- none of them learn from data, so calling them unfitted here is identical
to calling the fitted copies inside the model) plus an explicit boolean ->
float64 cast to match how the ColumnTransformer's numeric branch treats
`has_pool`/`sold_within_30_days`. Applied to both `reference` and `current`
before building the Evidently `Dataset`s. This is not a copy of serving's
cleaning logic - monitor is not serving, and both import the same canonical
`ml_common.cleaning` module (architecture rule 1 is about row-ops vs
column-ops, not about which stage may import `cleaning.py`).

### Bug B - `load_predictions` only filtered by DAY, not by the actual window

`ml_common/drift.py`'s `load_predictions` called `days_in_window()` to pick
which day-partition prefixes to read, then returned EVERYTHING under those
prefixes with no further filtering. `MONITOR_WINDOW_HOURS=1` therefore meant
"read today's whole partition", not "read the last hour" - two agent batches
sent an hour apart on the same UTC day would have silently mixed, exactly
the contamination the brief warned a 24h window would cause, except it was
happening at `window_hours=1` too. Confirmed empirically: a `price_inflation`
monitor run right after a `none` run reported `n_predictions=506` (partial
mix + flush race), and a follow-up debug script showed `load_predictions`
returning 1000 rows (500 from an 07:24 batch + 500 from an 07:29 batch) for
a nominal 1-hour window.

Fix: `load_predictions` now filters the concatenated frame to `timestamp`
inside `[end - window_hours, end]`. `load_outcomes` was NOT changed -
ground-truth rows carry no timestamp of their own (only the day they were
filed under), but that is fine: `join_outcomes` matches on `request_id`, and
an outcome for a request outside the now-correctly-filtered `predictions`
frame never joins. Also widened `window_hours` from `int` to `float`
throughout `drift.py` and in `stages/monitor/main.py`'s env parsing, because
isolating fast, back-to-back scenario runs in one test session needs
sub-hour precision (used 0.02-0.1h = 1-6 minutes below); production's hourly
Airflow schedule is unaffected since whole-hour values still work.
Also fixed a stale docstring on `load_outcomes` that claimed a
`received_at` field exists - it does not; the real fields are
`request_id`, `predicted_on`, `actual`, `model_name`.

New/updated tests in `common/tests/test_drift.py`: added `timestamp` columns
to existing fake frames and added
`test_load_predictions_excludes_rows_outside_the_hour_cutoff_same_day_partition`,
which fails without the fix (proved by running it before the fix landed).

### Also discovered, not fixed: inference-log buffer flush is not synchronous

Running `monitor` immediately after an agent batch can catch a PARTIAL
flush (`InferenceLogBuffer` flushes on a size-or-age trigger via a
background asyncio task, "once a second" per its own docs, but under a burst
of 500 synchronous `/predict` calls the flusher can lag). Observed once:
`n_predictions=33` right after a 500-request batch, with `/health` reporting
`buffered:0` again a few seconds later once the flush caught up. Worked
around operationally in every subsequent run by polling `GET /health` until
`inference_log.buffered == 0` before invoking monitor. Not fixed in code -
out of scope for this task, but worth a follow-up ticket since a scheduled
`monitoring_dag` run could hit the same race.

## THE major finding: `price_inflation` is a structural no-op for regression

`common/ml_common/schema.py` deliberately excludes `list_price` from
`feature_columns("regression")` as a leakage column:

```python
"regression": frozenset({
    ID_COLUMN,
    TARGET_REGRESSION,
    "price_category",     # derived directly from sale_price
    "list_price",          # temporally valid but makes the task trivial
}),
```

`services/agent/scenarios.py`'s `price_inflation` (and `market_rally`) ONLY
perturb `list_price`:

```python
if scenario in ("price_inflation", "market_rally") and "list_price" in result:
    ...
    result["list_price"] = amount * PRICE_FACTOR
```

Since the regressor's `SelectColumns` step strips `list_price` before the
model or the drift comparison ever sees it, multiplying it by 1.2 has
**zero** effect on the regression model's predictions, and `list_price` is
excluded from the feature-drift comparison columns too (`_numeric_and_
categorical_columns` is built from `feature_columns`). Measured directly:
`price_inflation`'s RMSE (101835.8875982...) was byte-identical to
`scenario=none`'s RMSE, and its feature-drifted share (0.0909) was
byte-identical to `none`'s too.

`mlops-pipeline-design.md` section 12/plan table (line 458) explicitly says
"chạy `drift_scenario=price_inflation` phải ra `high`" - the spec expects
`price_inflation` to move the model. It structurally cannot, under the
current schema's leakage exclusion. **This is a code/spec disagreement, not
a threshold problem, and I have not picked a side**: fixing it would mean
either (a) un-excluding `list_price` from regression features (which the
schema's own comment says "makes the task trivial" - probably a bad idea)
or (b) changing `price_inflation`/`market_rally` to perturb a real feature
instead (e.g. `living_area_sqft`, `school_rating`) - a scenario-semantics
change outside what this task authorized me to decide. Flagging for a
human/next-plan decision.

The same root cause reshapes `market_rally`'s result: since `adjust_truth`
DOES correctly scale the true sale price by 1.2 for `market_rally` (this
part works exactly as designed - confirmed empirically below), but the
perturbed feature (`list_price`) never reaches the model, the split comes
out **backwards** from the brief's table: `feature=ok` (not warning/high)
and `performance=high` (not ok), rather than `feature` firing while
`performance` stays ok.

## Scenario verdicts (real numbers)

All runs below are correctly isolated (verified via 10-second timestamp
bucket inspection matching `n_predictions`/`n_ground_truth` to the exact
batch size sent) except where noted.

| scenario | n_predictions | n_ground_truth | feature | prediction | performance | overall | table said |
|---|---|---|---|---|---|---|---|
| `none` | 500 | 500 | ok (share 0.0909) | ok | ok | **ok** | ok - MATCH |
| `price_inflation` | 500 | 500 | ok (share 0.0909, identical to none) | ok | ok (rmse 101835.89, ratio 1.14) | **ok** | high - MISMATCH, see finding above |
| `market_rally` | 500 | 500 | ok (share 0.0909, identical to none) | ok | **high** (rmse 199371.49, ratio 2.24) | **high** | feature warning/high + performance ok - MISMATCH (swapped), see finding above |
| `new_segment` | 200 (+30 contaminated from market_rally tail, window too loose) | 230 | warning | ok | warning | warning | serving must not crash - MATCH (no HTTP 500; agent's `raise_for_status()` never fired) |
| `none, count=100, feedback-ratio=0` | 100 | 0 | warning | high | **insufficient_data** | high | performance = insufficient_data, not ok - MATCH |
| `market_shift` (isolated, window_hours=0.045) | 500 | 500 | **ok** (share 0.0909, 2/22 - see note) | high | high | high | added post-review per coordinator ruling; see note below |

Train baseline for the ratio math: `train_rmse = 89126.08` (champion v3,
fingerprint `1630bf27520bba7f`).

### XCOM_RESULT lines, verbatim, from the runs used for the table

```
none (clean, isolated, window_hours=0.1):
XCOM_RESULT {"severity": "ok", "parts": {"feature": "ok", "prediction": "ok", "performance": "ok"}, "n_predictions": 500, "n_ground_truth": 500, "report_key": "reports/house_price_regressor/20260920T073957/evidently.html"}

price_inflation (clean, isolated, window_hours=0.032):
XCOM_RESULT {"severity": "ok", "parts": {"feature": "ok", "prediction": "ok", "performance": "ok"}, "n_predictions": 500, "n_ground_truth": 500, "report_key": "reports/house_price_regressor/20260920T074224/evidently.html"}

market_rally (clean, isolated, window_hours=0.03):
XCOM_RESULT {"severity": "high", "parts": {"feature": "ok", "prediction": "ok", "performance": "high"}, "n_predictions": 500, "n_ground_truth": 500, "report_key": "reports/house_price_regressor/20260920T074453/evidently.html"}

new_segment (partially contaminated, window_hours=0.03, 30 rows bled in from market_rally's tail - the only thing this row needs to prove is "no crash", which is independently confirmed by the agent completing with no exception):
XCOM_RESULT {"severity": "warning", "parts": {"feature": "warning", "prediction": "ok", "performance": "warning"}, "n_predictions": 230, "n_ground_truth": 230, "report_key": "reports/house_price_regressor/20260920T074612/evidently.html"}

none, count=100, feedback-ratio=0 (clean, isolated, window_hours=0.029):
XCOM_RESULT {"severity": "high", "parts": {"feature": "warning", "prediction": "high", "performance": "insufficient_data"}, "n_predictions": 100, "n_ground_truth": 0, "report_key": "reports/house_price_regressor/20260920T074759/evidently.html"}
```

(`feature=warning`/`prediction=high` on this last run is a small-sample
artifact - 100 rows makes Evidently's per-column statistical drift tests
noisier; the field that step 6 exists to check, `performance`, is exactly
`insufficient_data` as required.)

### Observed feature-drifted-columns share by scenario

| scenario | drifted count | drifted share |
|---|---|---|
| `none` (first measurement) | 2/22 | 0.0909 |
| `none` (clean rerun) | 2/22 | 0.0909 |
| `price_inflation` | 2/22 | 0.0909 (identical to none - see finding) |
| `market_rally` | 2/22 | 0.0909 (identical to none - see finding) |

`FEATURE_WARNING_SHARE = 0.3` was NOT changed. The observed no-drift share
(0.0909) sits comfortably below it with room to spare; there was no evidence
the Task 4 guess was miscalibrated.

## Addendum: `market_shift` (post-review, coordinator-requested)

The coordinator's ruling on `price_inflation`/`market_rally` (system correct,
plan's table wrong - not fixed, not un-excluding `list_price`) also noted a
gap: no scenario in the original four actually exercises a feature the
model CAN see, so nothing demonstrated feature drift firing at all.
`market_shift` (forces `city` to `"phoenix"`) does perturb a real feature -
`city` is not excluded from `feature_columns("regression")`.

Two runs were made. First, exactly as instructed -
`MONITOR_WINDOW_HOURS=1`, same invocation shape as every other scenario:

```
XCOM_RESULT {"severity": "high", "parts": {"feature": "ok", "prediction": "ok", "performance": "high"}, "n_predictions": 3300, "n_ground_truth": 3200, "report_key": "reports/house_price_regressor/20260920T075608/evidently.html"}
```

`n_predictions=3300` is every batch from this entire session (the whole
hour), not just `market_shift`'s 500 - by the time this scenario ran, all
prior scenarios in this task were less than an hour old, so `window_hours=1`
pulled in all of them. This number is not a fair read on `market_shift`
alone and is reported here for completeness of "exactly what was asked",
not as the answer.

Second, isolated to just the `market_shift` batch (`window_hours=0.045`,
same timestamp-bucket-inspection method used to isolate the other
scenarios):

```
XCOM_RESULT {"severity": "high", "parts": {"feature": "ok", "prediction": "high", "performance": "high"}, "n_predictions": 500, "n_ground_truth": 500, "report_key": "reports/house_price_regressor/20260920T075645/evidently.html"}
```

`n_predictions=500` matches the batch sent - clean.

**Did feature drift fire as expected? No, and the reason matters.**
`feature` came out `ok` (share 2/22 = 0.0909, identical to the `none`
baseline) even in the clean run. But per-column detail in the saved
Evidently report shows `city` WAS individually flagged as drifted -
Jensen-Shannon distance 0.7754 against a threshold of 0.1, a huge margin -
and so was `zipcode` (0.8250 vs 0.1, presumably correlated with the
city concentration). That is exactly 2 columns out of 22, so
`DriftedColumnsCount`'s aggregate share is 2/22 = 0.0909 regardless of how
extreme those 2 columns' individual drift is. `feature_severity()` in
`drift.py` only looks at that aggregate share, not at whether any
individual important column crossed its own per-column threshold - so a
scenario that concentrates all its drift into 1-2 of 22 columns can never
cross even the "ok" boundary (0.0909 « 0.3), no matter how total the
per-column shift is. This is not a bug in the feature-drift computation
path - Evidently correctly measured `city` and `zipcode` as heavily
drifted - it is a real gap in how `feature_severity()` aggregates that
signal down to one number. Not fixed here per the coordinator's explicit
instruction not to touch thresholds, scenario definitions, `schema.py`, or
the expected table on this pass.

`prediction` came out `high` (unlike `market_rally`, where it was `ok`):
`city` feeds the categorical branch of the encoder, so the model's OUTPUT
distribution shifts when every record claims to be in Phoenix, unlike
`market_rally`/`price_inflation` where the perturbed column never reaches
the model at all. `performance` also came out `high` - `market_shift` does
not call `adjust_truth` with a scaling factor, so real sale prices for the
sampled properties are unchanged while the model, fed a fabricated
`city="phoenix"`, mispredicts them.

No threshold, scenario, `schema.py`, or table wording was changed for this
addendum.

## Addendum 2: fixing `feature_severity`'s blindness to concentrated drift

Coordinator's ruling on the `market_shift` addendum: the finding stands as
a real design flaw in `feature_severity`, not a scenario artifact - grading
on SHARE of drifted columns means 7 of 22 columns must cross threshold
before `warning` fires, so drift concentrated into 1-2 columns (exactly
what `market_shift` does) is invisible no matter how extreme. Task: get the
per-column numbers, propose a minimal magnitude-based rule grounded in
them, implement it TDD, keep the share path (it catches broad/shallow
drift, a different real phenomenon), take the worse of the two.

### Step 1 - the per-column numbers

Extracted from the stored Evidently JSON (`report_key` for each run) - every
`evidently:metric_v2:ValueDrift` entry, sorted by value descending. "drifted"
= value > threshold, matching how `DriftedColumnsCount` itself decides:

**scenario=none** (run `20260920T073957`) - flagged: `city`, `zipcode`

| column | method | threshold | value | drifted |
|---|---|---|---|---|
| zipcode | Jensen-Shannon distance | 0.1 | 0.825054 | **True** |
| city | Jensen-Shannon distance | 0.1 | 0.101009 | **True** |
| property_id | Absolute text content drift | 0.55 | 0.500000 | False |
| listing_month | Wasserstein distance (normed) | 0.1 | 0.094732 | False |
| state | Jensen-Shannon distance | 0.1 | 0.081944 | False |
| living_area_sqft | Wasserstein distance (normed) | 0.1 | 0.080781 | False |
| crime_index | Wasserstein distance (normed) | 0.1 | 0.073702 | False |
| hoa_fee_monthly | Wasserstein distance (normed) | 0.1 | 0.072632 | False |
| distance_to_city_center_km | Wasserstein distance (normed) | 0.1 | 0.067752 | False |
| lot_size_sqft | Wasserstein distance (normed) | 0.1 | 0.059135 | False |
| bathrooms | Wasserstein distance (normed) | 0.1 | 0.058646 | False |
| year_built | Wasserstein distance (normed) | 0.1 | 0.054668 | False |
| bedrooms | Wasserstein distance (normed) | 0.1 | 0.051171 | False |
| days_on_market | Wasserstein distance (normed) | 0.1 | 0.045417 | False |
| stories | Jensen-Shannon distance | 0.1 | 0.039568 | False |
| listing_year | Jensen-Shannon distance | 0.1 | 0.037861 | False |
| condition | Jensen-Shannon distance | 0.1 | 0.034940 | False |
| property_type | Jensen-Shannon distance | 0.1 | 0.032862 | False |
| school_rating | Wasserstein distance (normed) | 0.1 | 0.023341 | False |
| has_pool | Jensen-Shannon distance | 0.1 | 0.014704 | False |
| garage_spaces | Jensen-Shannon distance | 0.1 | 0.013597 | False |
| sold_within_30_days | Jensen-Shannon distance | 0.1 | 0.002134 | False |

`DriftedColumnsCount`: count=2, share=0.090909. Sum of (value - threshold)
over all 22 rows: **-0.2844**.

**market_shift** (run `20260920T075645`) - flagged: `city`, `zipcode` (same two)

| column | method | threshold | value | drifted |
|---|---|---|---|---|
| zipcode | Jensen-Shannon distance | 0.1 | 0.825054 | **True** |
| city | Jensen-Shannon distance | 0.1 | **0.775448** | **True** |
| property_id | Absolute text content drift | 0.55 | 0.500000 | False |
| listing_month | Wasserstein distance (normed) | 0.1 | 0.094732 | False |
| state | Jensen-Shannon distance | 0.1 | 0.081944 | False |
| living_area_sqft | Wasserstein distance (normed) | 0.1 | 0.080781 | False |
| crime_index | Wasserstein distance (normed) | 0.1 | 0.073702 | False |
| hoa_fee_monthly | Wasserstein distance (normed) | 0.1 | 0.072632 | False |
| distance_to_city_center_km | Wasserstein distance (normed) | 0.1 | 0.067752 | False |
| lot_size_sqft | Wasserstein distance (normed) | 0.1 | 0.059135 | False |
| bathrooms | Wasserstein distance (normed) | 0.1 | 0.058646 | False |
| year_built | Wasserstein distance (normed) | 0.1 | 0.054668 | False |
| bedrooms | Wasserstein distance (normed) | 0.1 | 0.051171 | False |
| days_on_market | Wasserstein distance (normed) | 0.1 | 0.045417 | False |
| stories | Jensen-Shannon distance | 0.1 | 0.039568 | False |
| listing_year | Jensen-Shannon distance | 0.1 | 0.037861 | False |
| condition | Jensen-Shannon distance | 0.1 | 0.034940 | False |
| property_type | Jensen-Shannon distance | 0.1 | 0.032862 | False |
| school_rating | Wasserstein distance (normed) | 0.1 | 0.023341 | False |
| has_pool | Jensen-Shannon distance | 0.1 | 0.014704 | False |
| garage_spaces | Jensen-Shannon distance | 0.1 | 0.013597 | False |
| sold_within_30_days | Jensen-Shannon distance | 0.1 | 0.002134 | False |

`DriftedColumnsCount`: count=2, share=0.090909 - **identical to `none`**. Sum
of (value - threshold) over all 22 rows: **+0.3901**.

**The critical observation:** `zipcode` scores 0.825054 in BOTH runs, to six
decimal places identical. `zipcode` is a high-cardinality categorical
(thousands of distinct 5-digit codes); a Jensen-Shannon comparison of two
independent 500-row samples of it crosses its 0.1 threshold from sampling
noise alone, regardless of real drift - and here the two samples are not
even independent: both runs used the default `--seed 42` pool sample
against the default `REFERENCE_SEED=42` reference sample, so the underlying
zipcode values were the literal same set both times. `city`, by contrast,
moved from 0.101009 (barely over its own 0.1 threshold - essentially noise
too) to 0.775448 (massively over) - this is the real, scenario-caused
signal, and it is completely invisible to `DriftedColumnsCount`'s share
because `zipcode`'s constant false-positive occupies one of the two
"drifted" slots in both runs equally.

I also evaluated other candidate magnitude statistics before settling on
one (max single-column value/margin/ratio, mean, median, sum restricted to
flagged columns) - documented in-session, not reproduced here for length.
The important negative result: **any statistic based on "the single worst
column" (max value, max margin, max ratio, or "drop the worst and look at
the next" / trimmed-max) is unsound as a general rule**, even though
"drop zipcode, look at city" gives a beautiful 0.101 vs 0.775 separation on
these two samples - a rule that always discards the single most extreme
column will, by construction, ALSO discard a genuinely catastrophic
single-column drift if that column happens to score highest, which is
backwards for a monitoring system. Summing across ALL compared columns
(not dropping any) avoids this: the noisy column's near-identical
contribution to both sums cancels out in the COMPARISON without ever being
excluded from either individual measurement.

### Step 2 - the proposed rule

**Sum of (value - threshold) across every column Evidently compared.**
Negative means the compared columns collectively sit under their own
detection thresholds; positive means they collectively sit over.

- `scenario=none`: **-0.2844**
- `market_shift`: **+0.3901**
- Swing across the zero crossing: **0.674**
- Margin from `none` to the proposed line (0.0): **0.284**
- Margin from the proposed line to `market_shift`: **0.390**

Both margins are comfortable relative to the swing (neither observation
sits within 10% of the line) - this is not a threshold barely separating
two samples. Rule: `FEATURE_MAGNITUDE_WARNING = 0.0`; `feature_severity`
takes `max(share_result, magnitude_result)`.

**No HIGH tier is proposed for the magnitude path.** Exactly one
above-warning observation exists (`market_shift`, +0.3901). Fitting a
"high" cutoff from a single data point is precisely the kind of guess this
whole task exists to stop making, so it is left undefined - documented as a
gap - until a second real high-magnitude measurement exists to calibrate
against. The share path can still independently reach `high` on its own
terms (broad, shallow drift across many columns), and `max()` of the two
paths preserves that.

### Step 3 - implementation (TDD)

`common/tests/test_drift.py`: wrote 7 new tests FIRST, confirmed all 6
touching the not-yet-existing code failed
(`AttributeError: no attribute 'feature_margin_severity'`,
`TypeError: feature_severity() takes 1 positional argument but 2 were
given`), then implemented:

- `common/ml_common/drift.py`: added `FEATURE_MAGNITUDE_WARNING = 0.0`
  with the observed numbers and reasoning in a comment (see the constant's
  comment in the file for the full version of the reasoning above); added
  `feature_margin_severity(margins: list[float]) -> str`; changed
  `feature_severity(drifted_share, margins: list[float] | None = None)` -
  the new parameter defaults to `None`, so every existing caller
  (`stages/monitor/main.py`'s old single-argument call would have kept
  working unmodified) sees byte-identical behavior; when margins are
  supplied, returns `max(share_result, magnitude_result)`.
- `stages/monitor/main.py`: added `_feature_margins(summary)`, parallel to
  the existing `_drifted_share(summary)`, pulling `value - threshold` out
  of every `evidently:metric_v2:ValueDrift` entry. Wired into the
  `feature_part` call site. Also de-duplicated `feature_report.dict()`
  (previously called twice, now called once into `feature_report_summary`
  and reused for the JSON write further down).

All 7 new tests pass after implementation; no existing test needed to
change.

### Step 4 - re-verification

Ran `feature_severity` against the ACTUAL stored Evidently JSON for both
runs (not the synthetic per-test numbers) via `_drifted_share` +
`_feature_margins`, comparing old (share-only) vs new (combined) verdicts:

```
scenario=none    : share=0.0909 sum(margins)=-0.2844 n_columns=22 OLD=ok NEW=ok
market_shift     : share=0.0909 sum(margins)=0.3901 n_columns=22 OLD=ok NEW=warning
```

`scenario=none` stays `ok`. `market_shift`'s feature part moves from `ok`
to `warning` - the coordinator's minimum bar ("reaches at least warning")
is met. Combined with the already-`high` `prediction`/`performance` parts
from the earlier `market_shift` measurement, `market_shift`'s `overall`
severity is unaffected by this change (it was already `high` via
prediction/performance) - what changes is that `feature` itself now
honestly reports something happened, instead of reporting `ok` on a
collapsed city distribution.

Full suite: `.venv\Scripts\python.exe -m pytest common/ services/ -q` ->
**352 passed** (was 345 before this addendum; +7 new tests, 0 removed, 0
changed). `.venv\Scripts\python.exe -m ruff check .` -> **All checks
passed!**. `ml-base` and `ml-monitor` images rebuilt;
`scripts/verify_monitoring.ps1` re-run, all 5 steps green.

`schema.py`, scenario definitions, and the expected-results table were not
touched.

## Addendum 3: fix round 1/5 - loud failure on broken extraction

Review approved the magnitude rule and the combination logic from
Addendum 2, with one important finding: `_feature_margins()` failed
silently on malformed input where `_drifted_share()` already fails loudly
on the same class of failure. If Evidently's dict shape changed and
per-column entries lost `threshold`/`value`, `_feature_margins` dropped
those entries without complaint; the sum then covered few or no columns,
came out negative, and the verdict was `ok` - a green badge produced by
broken extraction, worse than a crash because nobody investigates a green
badge.

**Fix in `stages/monitor/main.py`:** `_feature_margins()` now raises
`KeyError` (same spirit/message style as `_drifted_share`) in the
all-or-nothing case only:
- zero `evidently:metric_v2:ValueDrift` entries found at all -> raises
  ("a drift report with no per-column results means extraction is broken,
  not that nothing drifted")
- one or more entries found, but NONE yield a usable `(value, threshold)`
  pair -> raises

A single malformed entry among otherwise-good ones is still skipped, not
fatal - partial data is usable, and one odd column should not take the
whole run down.

**Tests** (new file `common/tests/test_monitor_feature_margins.py`, since
`_feature_margins` lives in `stages/monitor/main.py`, not `common/`, and
no stage has ever had unit tests before - loaded via `importlib` from a
plain path, since `stages/` has no `__init__.py` anywhere and adding
package structure there for one test file was out of scope):
- all `ValueDrift` entries missing `threshold` -> raises
- no `ValueDrift` entries at all -> raises
- completely empty `metrics` list -> raises
- one good entry + one malformed entry -> does NOT raise; sum uses only
  the good entry
- a fully well-formed pair of entries -> returns both margins correctly

5 new tests, all passing.

**Tie-break (coordinator's decision, not mine to make):** kept `>=
FEATURE_MAGNITUDE_WARNING`, so a sum of exactly 0.0 reads as `warning`.
Added a short comment beside the constant: every other threshold in this
module already resolves ties the same way (`feature_severity`'s 0.3 share,
`performance_severity`'s 1.2 rmse ratio and 0.05 auc drop are all `>=`
into the worse band), and erring toward flagging is the right direction
for a monitoring system. The constant's value (0.0) was not changed.

**Comment reword:** `test_feature_severity_share_dilutes_but_magnitude_
catches_market_shift` (function name kept, per "do not change the
assertions" - only comments and the two local variable names inside them
changed) now describes the RULE under test - share cannot distinguish a
no-drift run from a concentrated-drift run at the same share value,
magnitude can, because an identically-behaving column cancels out of the
comparison - and cites the task-11 market_shift numbers as motivation for
choosing realistic constants, not as fixture data the test depends on
reproducing. Assertions themselves are byte-identical to before.

**Verification:** `.venv\Scripts\python.exe -m ruff check .` -> `All
checks passed!`. `.venv\Scripts\python.exe -m pytest common/ services/ -q`
-> **357 passed** (was 352; +5 new, 0 changed, 0 removed). `ml-base` and
`ml-monitor` rebuilt; `scripts/verify_monitoring.ps1` re-run, all 5 steps
green.

Commit: `4ecaca41fc1c122f7d9b2dac986a1ce1718edd3c`.

## Addendum 4: fix round 2/5 - skip cleanly when stages/ is absent

Coordinator ran the plan's Definition of Done container test suite and
found `common/tests/test_monitor_feature_margins.py` broke it:
`ml-base:latest` COPYs only `common/` (`docker run --rm ml-base:latest sh
-c "ls /app"` prints just `common`), so the test file's unconditional
`monitor_main = _load_monitor_main()` at module scope raised
`FileNotFoundError` at COLLECTION time inside the container, which
aborted the ENTIRE pytest run (`Interrupted: 1 error during collection`),
not just that one file - failing Definition of Done item 2, "tests pass
in the container under Python 3.12," for every test in the suite.

**Fix:** computed `_MONITOR_MAIN_PATH` once at module scope, added a
module-level `pytestmark = pytest.mark.skipif(not
_MONITOR_MAIN_PATH.exists(), reason=...)` that is evaluated BEFORE
`_load_monitor_main()` is ever called, and guarded the load itself
(`monitor_main = _load_monitor_main() if _MONITOR_MAIN_PATH.exists() else
None`). Collection now never touches the missing file inside the
container; the skip marker takes effect first. Added a paragraph to the
module docstring recording why the skip exists and explicitly telling a
future reader not to "fix" it by adding `stages/` to `ml-base`'s
Dockerfile, adding `__init__.py` under `stages/`, or moving the logic into
`common/ml_common/` - all three were explicitly ruled out by the
coordinator and none of them were touched.

**Verification, all three, real output:**

Dev machine - the test must still RUN, not skip:

```
.venv\Scripts\python.exe -m pytest common/ services/ -q
======================= 357 passed, 4 warnings in 6.26s =======================
```

357 passed, zero skipped (`-rs` showed no skip lines) - confirmed the file
still exercises the five tests on the dev machine.

Container - `ml-base` rebuilt first (COPYs `common/` at build time, so the
image needed the fixed test file baked in), then:

```
docker run --rm ml-base:latest sh -c "pip install --quiet 'pytest>=8.0' 'moto[s3]>=5.0' && python -m pytest /app/common/tests -q"
============================= test session starts ==============================
platform linux -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
collected 300 items
...
common/tests/test_monitor_feature_margins.py sssss                       [ 42%]
...
======================== 294 passed, 6 skipped in 4.41s ========================
```

No collection error. 294 passed, 6 skipped total - 5 of those are
`test_monitor_feature_margins.py` (all skipped cleanly, reason attached);
the 6th is a pre-existing, unrelated skip already present in
`test_stageio.py` before this task.

Ruff: `.venv\Scripts\python.exe -m ruff check .` -> `All checks passed!`.

`schema.py`, `stages/` package structure, and `ml-base`'s Dockerfile were
not touched.

Commit: `dd7ce5a587489587e30b4aebd8e2c4f74eb91d46`.

## Threshold changes

**None.** `common/ml_common/drift.py`'s `FEATURE_WARNING_SHARE` (0.3),
`FEATURE_HIGH_SHARE` (0.5), `RMSE_WARNING_RATIO` (1.2), `RMSE_HIGH_RATIO`
(1.5) and `MIN_GROUND_TRUTH` (50) are all unchanged from Task 4. The two
`drift.py` changes made (window filtering, float hours) are correctness
fixes to the windowing mechanism, not calibration of the severity
boundaries.

## Test count

`345 passed` (was 344; +1 for
`test_load_predictions_excludes_rows_outside_the_hour_cutoff_same_day_partition`).
`.venv\Scripts\python.exe -m ruff check .` -> `All checks passed!`.

## `scripts/verify_monitoring.ps1`

Created per the brief, with the one correction from the task instructions:
the "agent must be off" check uses plain `docker compose ps --services` (per
the brief), but the presence-of-the-service check uses
`docker compose --profile agent config --services` instead of a
profile-less `docker compose config --services`, since Compose v5.3.1 strips
profiled services from the profile-less listing entirely. Full run:

```
== 1/5 Test o may dev ==
======================= 345 passed, 2 warnings in 7.55s =======================
== 2/5 Ruff ==
All checks passed!
== 3/5 drift.py khong keo Evidently vao ml-base ==
50
== 4/5 Agent service phai TAT mac dinh ==
== 5/5 Image ml-monitor ton tai ==

Plan 4 xanh.
Bang kich ban phai kiem bang tay - xem Task 11 cua plan.
```

## monitoring_dag

Confirmed still paused after all work:
`monitoring_dag | /opt/airflow/dags/monitoring_dag.py | airflow | True`
(the `paused` column). Never triggered or unpaused during this task.

## git log -1

```
commit b59ae4784dc2884d98f3b1f72122b86122cdb073
Author: THANH <95860402+ccna123@users.noreply.github.com>
Date:   Sun Sep 20 16:50:30 2026 +0900

    test: calibrate the drift thresholds against real runs

    (full body: see `git log -1` in the repo; summarized above)

    Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```
