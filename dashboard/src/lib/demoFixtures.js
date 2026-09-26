// Demo/offline fixtures. Every block here is copied verbatim from real API
// responses captured in docs/superpowers/specs/2026-09-20-plan5b-ui-brief.md
// (Task 12 of Plan 5a) — used only when demo mode is on, so the dashboard
// can be reviewed without the full docker-compose stack running (brief §5.1
// explicitly suggests prototyping against these fixtures).

export const health = {
  status: "ok",
  services: { airflow: "ok", mlflow: "ok", minio: "ok", serving: "ok", postgres: "ok" },
};

// Mirrors GET /api/scenarios, which reads services.agent.scenarios directly.
export const scenarios = {
  scenarios: ["none", "price_inflation", "market_rally", "market_shift", "new_segment"],
};

// Mirrors GET /api/estimators, which reads ml_common.estimators directly.
// Narrowed to 3 names per task type on 2026-09-23; there is no more
// "diagnostic" group since the two names that only existed to exercise the
// promotion gates (hist_gradient_boosting_weak, dummy) were dropped with it.
export const estimators = {
  regression: ["ridge", "xgboost", "random_forest"],
  classification: ["xgboost", "svm", "random_forest"],
};

// The brief's literal `GET /pipeline/runs?limit=3` response, plus one
// synthetic "running" run in front so the demo has something live to show —
// that 4th entry is NOT captured API output, only the other three are.
export const runs = {
  runs: [
    {
      run_id: "manual__2026-09-21T03:53:17.127926+00:00",
      state: "running",
      task_type: "regression",
      started_at: "2026-09-21T03:53:17.127926+00:00",
      ended_at: null,
    },
    {
      run_id: "manual__2026-09-20T13:34:28+00:00",
      state: "success",
      task_type: "regression",
      started_at: "2026-09-20T13:38:01.213139+00:00",
      ended_at: "2026-09-20T13:38:44.575244+00:00",
    },
    {
      run_id: "manual__2026-09-19T00:00:00+00:00",
      state: "success",
      task_type: null,
      started_at: "2026-09-19T00:00:00+00:00",
      ended_at: "2026-09-19T10:54:50.443051+00:00",
    },
    {
      run_id: "manual__2026-09-18T00:00:00+00:00",
      state: "failed",
      task_type: null,
      started_at: "2026-09-18T00:00:00+00:00",
      ended_at: "2026-09-19T08:41:19.536365+00:00",
    },
  ],
};

// The brief's literal `GET /pipeline/runs/{run_id}` "running" response for
// manual__2026-09-21T03:53:17.127926+00:00, extract last and running.
const runningDetail = {
  run_id: "manual__2026-09-21T03:53:17.127926+00:00",
  state: "running",
  tasks: [
    { task_id: "validate", state: null, try_number: 0, duration: null },
    { task_id: "prepare_dataset_for_train", state: null, try_number: 0, duration: null },
    { task_id: "train", state: null, try_number: 0, duration: null },
    { task_id: "evaluate", state: null, try_number: 0, duration: null },
    { task_id: "branch_on_gates", state: null, try_number: 0, duration: null },
    { task_id: "register", state: null, try_number: 0, duration: null },
    { task_id: "stop_no_deploy", state: null, try_number: 0, duration: null },
    { task_id: "deploy", state: null, try_number: 0, duration: null },
    { task_id: "extract", state: "running", try_number: 1, duration: null },
  ],
};

// The brief's literal "failed" response (extract succeeded, the other 8
// skipped by the DAG's own skip semantics after a manual failure mark).
const failedDetail = {
  run_id: "manual__2026-09-18T00:00:00+00:00",
  state: "failed",
  tasks: [
    { task_id: "register", state: "skipped", try_number: 0, duration: 0.0 },
    { task_id: "extract", state: "success", try_number: 1, duration: 1.534837 },
    { task_id: "prepare_dataset_for_train", state: "skipped", try_number: 0, duration: 0.0 },
    { task_id: "train", state: "skipped", try_number: 0, duration: 0.0 },
    { task_id: "evaluate", state: "skipped", try_number: 0, duration: 0.0 },
    { task_id: "branch_on_gates", state: "skipped", try_number: 0, duration: 0.0 },
    { task_id: "stop_no_deploy", state: "skipped", try_number: 0, duration: 0.0 },
    { task_id: "deploy", state: "skipped", try_number: 0, duration: 0.0 },
    { task_id: "validate", state: "skipped", try_number: 1, duration: 0.0 },
  ],
};

// Not captured in the brief (only queued/running/failed examples exist for
// this DAG) — a plausible all-success run so the "success" row has detail
// to show. Clearly synthetic, unlike the two blocks above.
const successDetail = {
  run_id: "manual__2026-09-20T13:34:28+00:00",
  state: "success",
  tasks: [
    { task_id: "extract", state: "success", try_number: 1, duration: 1.5 },
    { task_id: "validate", state: "success", try_number: 1, duration: 2.1 },
    { task_id: "prepare_dataset_for_train", state: "success", try_number: 1, duration: 9.8 },
    { task_id: "train", state: "success", try_number: 1, duration: 14.2 },
    { task_id: "evaluate", state: "success", try_number: 1, duration: 3.4 },
    { task_id: "branch_on_gates", state: "success", try_number: 1, duration: 0.2 },
    { task_id: "register", state: "success", try_number: 1, duration: 4.9 },
    { task_id: "deploy", state: "success", try_number: 1, duration: 6.9 },
    { task_id: "stop_no_deploy", state: "skipped", try_number: 0, duration: 0.0 },
  ],
};

export const runDetails = {
  "manual__2026-09-21T03:53:17.127926+00:00": runningDetail,
  "manual__2026-09-20T13:34:28+00:00": successDetail,
  "manual__2026-09-18T00:00:00+00:00": failedDetail,
};

// Literal `GET /data/v1/preview?rows=2` response.
export const preview = {
  total_rows: 2012000,
  stats_rows: 200000,
  sample: [
    {
      property_id: "189380",
      listing_date: "10/18/2021",
      city: "Houston",
      state: "TX",
      zipcode: "16444",
      property_type: "CONDO",
      lot_size_sqft: "9632.620047925273",
      living_area_sqft: "620.0872753252422",
      bedrooms: "5.0",
      bathrooms: "3.0",
      year_built: "1941.0",
      stories: "2.0",
      garage_spaces: "2.0",
      has_pool: "0",
      hoa_fee_monthly: "442.1107181209878",
      school_rating: "3.0",
      crime_index: "1.7851112811668841",
      distance_to_city_center_km: "4.1892985681763815",
      condition: "Good",
      days_on_market: "11",
      list_price: "203474.7",
      sale_price: "175922.77",
      price_category: "Low",
      sold_within_30_days: "Yes",
    },
    {
      property_id: "48062",
      listing_date: "2024-06-03",
      city: "Philadelphia",
      state: "PA",
      zipcode: "19009",
      property_type: "Single_Family",
      lot_size_sqft: "9283.685180461389",
      living_area_sqft: "1736.0294929005188",
      bedrooms: "3.0",
      bathrooms: "2.5",
      year_built: "1900.0",
      stories: "2.0",
      garage_spaces: "2.0",
      has_pool: "False",
      hoa_fee_monthly: "",
      school_rating: "5.0",
      crime_index: "40.50933159238418",
      distance_to_city_center_km: "0.39896970698237505",
      condition: "Good",
      days_on_market: "7",
      list_price: "305872.61",
      sale_price: "325256.06",
      price_category: "Medium",
      sold_within_30_days: "Yes",
    },
  ],
  columns: [
    { name: "bathrooms", kind: "numeric", missing_rate: 0.02021, out_of_bounds: 332 },
    { name: "bedrooms", kind: "numeric", missing_rate: 0.0, out_of_bounds: 295 },
    { name: "city", kind: "categorical", missing_rate: 0.0, out_of_bounds: 0 },
    { name: "condition", kind: "categorical", missing_rate: 0.0, out_of_bounds: 0 },
    { name: "crime_index", kind: "numeric", missing_rate: 0.03978, out_of_bounds: 0 },
    { name: "days_on_market", kind: "numeric", missing_rate: 0.0, out_of_bounds: 0 },
    { name: "distance_to_city_center_km", kind: "numeric", missing_rate: 0.0, out_of_bounds: 384 },
    { name: "garage_spaces", kind: "numeric", missing_rate: 0.01978, out_of_bounds: 0 },
    { name: "has_pool", kind: "boolean", missing_rate: 0.019905, out_of_bounds: 0 },
    { name: "hoa_fee_monthly", kind: "numeric", missing_rate: 0.632155, out_of_bounds: 0 },
    { name: "list_price", kind: "money", missing_rate: 0.0, out_of_bounds: 0 },
    { name: "listing_date", kind: "date", missing_rate: 0.08055, out_of_bounds: 0 },
    { name: "living_area_sqft", kind: "numeric", missing_rate: 0.005165, out_of_bounds: 109 },
    { name: "lot_size_sqft", kind: "numeric", missing_rate: 0.01003, out_of_bounds: 0 },
    { name: "price_category", kind: "categorical", missing_rate: 0.0, out_of_bounds: 0 },
    { name: "property_id", kind: "id", missing_rate: 0.0, out_of_bounds: 0 },
    { name: "property_type", kind: "categorical", missing_rate: 0.0, out_of_bounds: 0 },
    { name: "sale_price", kind: "money", missing_rate: 0.0, out_of_bounds: 0 },
    { name: "school_rating", kind: "numeric", missing_rate: 0.058665, out_of_bounds: 0 },
    { name: "sold_within_30_days", kind: "boolean", missing_rate: 0.0, out_of_bounds: 0 },
    { name: "state", kind: "categorical", missing_rate: 0.0, out_of_bounds: 0 },
    { name: "stories", kind: "numeric", missing_rate: 0.0, out_of_bounds: 0 },
    { name: "year_built", kind: "numeric", missing_rate: 0.03956, out_of_bounds: 452 },
    { name: "zipcode", kind: "zipcode", missing_rate: 0.009295, out_of_bounds: 0 },
  ],
};

// Literal `GET /models` response, with one field added on top: `estimator`
// (added to the real API 2026-09-22) predates this capture, so its values
// below are NOT captured output — they are the algorithm each demo version
// would plausibly have been trained with, picked from
// ml_common.estimators.ESTIMATOR_NAMES for that task_type.
export const models = {
  models: [
    {
      name: "house_needs_renovation_classifier",
      task_type: "classification",
      versions: [
        {
          version: "1",
          metrics: { f1: 0.1046831955922865, accuracy: 0.756128064032016, auc: 0.6468311259876465 },
          estimator: "svm",
          is_champion: true,
          created_at: "2026-09-19T10:49:51.116000+00:00",
        },
      ],
    },
    {
      name: "house_price_regressor",
      task_type: "regression",
      versions: [
        {
          version: "3",
          metrics: { rmse: 98175.10328533906, mae: 64040.68658593348, r2: 0.9475422335571709 },
          estimator: "xgboost",
          is_champion: true,
          created_at: "2026-09-19T09:12:56.485000+00:00",
        },
        {
          version: "2",
          metrics: { rmse: 98175.10328533906, mae: 64040.68658593348, r2: 0.9475422335571709 },
          estimator: "xgboost",
          is_champion: false,
          created_at: "2026-09-19T08:55:40.454000+00:00",
        },
        {
          version: "1",
          metrics: { rmse: 204970.66113894654, mae: 147923.18956396583, r2: 0.7713398598310879 },
          estimator: "ridge",
          is_champion: false,
          created_at: "2026-09-19T08:55:05.143000+00:00",
        },
      ],
    },
  ],
};

// Literal `GET /drift/latest?model_name=house_price_regressor` response —
// feature ok while prediction and performance are high (brief's own example
// of why the three parts must never collapse into one badge).
export const driftLatest = {
  model_name: "house_price_regressor",
  model_version: "3",
  task_type: "regression",
  run_id: "20260920T075645",
  computed_at: "2026-09-20T07:56:45.249085+00:00",
  window_hours: 0.045,
  severity: "high",
  parts: { feature: "ok", prediction: "high", performance: "high", input_quality: "warning" },
  n_predictions: 500,
  n_ground_truth: 500,
  current_metrics: { rmse: 305791.86789740255, mae: 184188.3288157089, r2: 0.5677294118532599 },
  // NOT captured output: the real response predates these two fields (added
  // to the monitor stage on 2026-09-22). The values are this version's actual
  // test scores from the brief's own /models response, so the comparison
  // table has something real-shaped to show in demo mode.
  reference_metrics: { rmse: 98175.10328533906, mae: 64040.68658593348, r2: 0.9475422335571709 },
  reference_source: "test_metrics",
  report_key: "reports/house_price_regressor/20260920T075645/evidently.html",
  // NOT captured output either: the fields below arrived with 基本設計書 1.1
  // (data quality of the input, per-group metrics, flush result, warning
  // streaks). Shaped exactly as stages/monitor/main.py writes them.
  input_quality: {
    level: "warning",
    columns: [{ column: "listing_year", missing_increase_points: 9.4, unseen_share: null, level: "warning" }],
  },
  flush: { ok: true, written: 137, error: null },
  consecutive_warnings: { feature: 0, prediction: 0, performance: 0, input_quality: 1 },
  group_metrics: {
    current: {
      city: {
        phoenix: { n: 412, rmse: 318204.1, mae: 190331.4, r2: 0.52 },
        boston: { n: 51, rmse: 201337.9, mae: 120004.2, r2: 0.71 },
        tulsa: { n: 37, insufficient_data: true },
      },
      property_type: {
        "single family": { n: 301, rmse: 297331.0, mae: 181002.3, r2: 0.58 },
        condo: { n: 199, rmse: 309874.5, mae: 188118.8, r2: 0.55 },
      },
    },
    reference: {
      city: {
        phoenix: { n: 5120, rmse: 101223.4, mae: 66012.2, r2: 0.94 },
        boston: { n: 4987, rmse: 97002.1, mae: 63340.9, r2: 0.95 },
        tulsa: { n: 5230, rmse: 96550.0, mae: 62987.1, r2: 0.95 },
      },
      property_type: {
        "single family": { n: 16012, rmse: 99870.2, mae: 65001.4, r2: 0.95 },
        condo: { n: 9744, rmse: 95511.7, mae: 62110.0, r2: 0.94 },
      },
    },
  },
};

// Three literal elements out of the real 12-entry history (brief §4.5),
// newest first as the API returns it: the two above plus one
// insufficient_data example so the chart demo shows all three shapes.
export const driftHistory = {
  history: [
    driftLatest,
    {
      model_name: "house_price_regressor",
      model_version: "3",
      task_type: "regression",
      run_id: "20260920T075608",
      computed_at: "2026-09-20T07:56:08.134449+00:00",
      window_hours: 1.0,
      severity: "high",
      parts: { feature: "ok", prediction: "ok", performance: "high" },
      n_predictions: 3300,
      n_ground_truth: 3200,
      current_metrics: { rmse: 167855.74049911226, mae: 93692.52982905749, r2: 0.8800899177082595 },
      report_key: "reports/house_price_regressor/20260920T075608/evidently.html",
    },
    {
      model_name: "house_price_regressor",
      model_version: "3",
      task_type: "regression",
      run_id: "20260920T074759",
      computed_at: "2026-09-20T07:47:59.264677+00:00",
      window_hours: 0.029,
      severity: "high",
      parts: { feature: "warning", prediction: "high", performance: "insufficient_data" },
      n_predictions: 100,
      n_ground_truth: 0,
      current_metrics: {},
      report_key: "reports/house_price_regressor/20260920T074759/evidently.html",
    },
  ],
};

// Not captured API output (the brief only ever exercised the regressor) —
// synthesized so demo mode has a classification example too. Without this,
// switching the Drift screen's model dropdown to
// house_needs_renovation_classifier showed a 404 empty state and nobody
// could see what a classification report looks like without the real stack
// up. Metric names come from ml_common.metrics.compute_metrics
// ("classification" branch): f1, accuracy, auc — never rmse/mae/r2.
export const driftLatestClassification = {
  model_name: "house_needs_renovation_classifier",
  model_version: "1",
  task_type: "classification",
  run_id: "20260922T091500",
  computed_at: "2026-09-22T09:15:00.000000+00:00",
  window_hours: 1.0,
  severity: "warning",
  parts: { feature: "warning", prediction: "ok", performance: "warning" },
  n_predictions: 420,
  n_ground_truth: 300,
  current_metrics: { f1: 0.0812, accuracy: 0.7024, auc: 0.6012 },
  // The champion's own test scores, copied from the `models` fixture above
  // (version "1") so the comparison table has a real-shaped baseline.
  reference_metrics: { f1: 0.1046831955922865, accuracy: 0.756128064032016, auc: 0.6468311259876465 },
  reference_source: "test_metrics",
  report_key: "reports/house_needs_renovation_classifier/20260922T091500/evidently.html",
};

export const driftHistoryClassification = {
  history: [
    driftLatestClassification,
    {
      model_name: "house_needs_renovation_classifier",
      model_version: "1",
      task_type: "classification",
      run_id: "20260922T081500",
      computed_at: "2026-09-22T08:15:00.000000+00:00",
      window_hours: 1.0,
      severity: "ok",
      parts: { feature: "ok", prediction: "ok", performance: "ok" },
      n_predictions: 300,
      n_ground_truth: 280,
      current_metrics: { f1: 0.1012, accuracy: 0.7488, auc: 0.6390 },
      reference_metrics: { f1: 0.1046831955922865, accuracy: 0.756128064032016, auc: 0.6468311259876465 },
      reference_source: "test_metrics",
      report_key: "reports/house_needs_renovation_classifier/20260922T081500/evidently.html",
    },
    {
      model_name: "house_needs_renovation_classifier",
      model_version: "1",
      task_type: "classification",
      run_id: "20260922T071500",
      computed_at: "2026-09-22T07:15:00.000000+00:00",
      window_hours: 0.05,
      severity: "warning",
      parts: { feature: "warning", prediction: "ok", performance: "insufficient_data" },
      n_predictions: 60,
      n_ground_truth: 0,
      current_metrics: {},
      report_key: "reports/house_needs_renovation_classifier/20260922T071500/evidently.html",
    },
  ],
};

// Keyed lookup so demoApi can serve the right fixture for whichever model
// the dropdown has selected, instead of hard-coding the one regressor —
// that hard-coding is exactly what made every other model a 404 in demo
// mode, classification included.
export const driftFixturesByModel = {
  house_price_regressor: { latest: driftLatest, history: driftHistory },
  house_needs_renovation_classifier: {
    latest: driftLatestClassification,
    history: driftHistoryClassification,
  },
};

// Demo stand-ins for the feedback data pipeline (基本設計書 3.11).
export const feedbackPreview = {
  task_type: "regression",
  period_start: "2026-08-27T00:00:00+00:00",
  period_end: "2026-09-26T00:00:00+00:00",
  matched: 1480,
  minimum: 500,
  enough: true,
};

export const modelCard = {
  model_name: "house_price_regressor",
  version: "3",
  task_type: "regression",
  created_at: "2026-09-20T07:30:00+00:00",
  purpose: "Predicts the final sale price of a house, in US dollars.",
  algorithm: { estimator: "xgboost", tuned: "False", decision_threshold: null },
  data: {
    dataset_version: "v1",
    data_id: "3f0a9c1d5e2b7a48",
    split_points: '{"original": {"t1": "2023-11-02", "t2": "2024-10-15", "undated_test_share": 0.2}}',
    train_rows: "200000",
    sample_rows: "200000",
    seed: "42",
  },
  code: { git_commit: "a1b2c3d", image_digest: "sha256:9f2c…" },
  metrics: {
    test: { rmse: 98175.1, mae: 64040.7, r2: 0.9475 },
    by_group: { city: { phoenix: { n: 5120, rmse: 101223.4, mae: 66012.2, r2: 0.94 } } },
  },
  excluded_columns: ["property_id", "list_price", "sale_price", "price_category"],
  known_limitations: [
    "Trained on simulated data, not real transactions.",
    "Tree models cannot predict prices above the range they learned; a market that rises beyond it is underestimated.",
  ],
};
