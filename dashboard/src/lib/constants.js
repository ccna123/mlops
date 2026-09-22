// Fixed order of the 9 real ml_pipeline task ids (brief §4.1). The API's
// `tasks` array does NOT preserve this order, so every screen that walks
// tasks must sort by this list instead of trusting the response order.
export const STAGE_ORDER = [
  "extract",
  "validate",
  "prepare_dataset_for_train",
  "train",
  "evaluate",
  "branch_on_gates",
  "register",
  "deploy",
  "stop_no_deploy",
];

export const STAGE_LABELS = {
  extract: "Trích xuất",
  validate: "Kiểm định",
  prepare_dataset_for_train: "Chuẩn bị dữ liệu train",
  train: "Train",
  evaluate: "Đánh giá",
  branch_on_gates: "Chọn nhánh (cổng)",
  register: "Đăng ký model",
  deploy: "Deploy",
  stop_no_deploy: "Dừng, không deploy",
};

// The four StatusBadge states (brief §2). insufficient_data must differ from
// ok on three axes at once (pattern, border style, label) — never color alone.
export const STATUS_META = {
  ok: { label: "ổn", icon: "check", badgeClass: "badge-ok" },
  warning: { label: "cảnh báo", icon: "alert-triangle", badgeClass: "badge-warning" },
  high: { label: "cao", icon: "x-circle", badgeClass: "badge-high" },
  insufficient_data: { label: "chưa đủ dữ liệu", icon: "circle-dashed", badgeClass: "badge-insufficient" },
};

// Airflow run/task vocabulary — a different set of words from STATUS_META,
// never mixed into the four-state badge (brief §2, last bullet).
export const TASK_STATE_META = {
  success: { label: "thành công", badgeClass: "badge-task-success" },
  failed: { label: "thất bại", badgeClass: "badge-task-failed" },
  running: { label: "đang chạy", badgeClass: "badge-task-running" },
  queued: { label: "đang chờ", badgeClass: "badge-task-queued" },
  // Not in the brief's list, but observed on the live system on 2026-09-21:
  // the scheduler has picked the task but the executor has not started it.
  scheduled: { label: "đã xếp lịch", badgeClass: "badge-task-queued" },
  skipped: { label: "bỏ qua", badgeClass: "badge-task-skipped" },
  upstream_failed: { label: "bị chặn", badgeClass: "badge-task-blocked" },
  up_for_retry: { label: "chờ thử lại", badgeClass: "badge-task-retry" },
  null: { label: "chưa chạy", badgeClass: "badge-task-null" },
};

export const SERVICE_ORDER = ["airflow", "mlflow", "minio", "serving", "postgres"];

export const SERVICE_LABELS = {
  airflow: "Airflow",
  mlflow: "MLflow",
  minio: "MinIO",
  serving: "Serving",
  postgres: "Postgres",
};

// Metric direction hints — NOT returned by the API, purely a UI convention
// (brief §4.4). Unknown metric keys render with no arrow.
export const LOWER_IS_BETTER = new Set(["rmse", "mae"]);
export const HIGHER_IS_BETTER = new Set(["r2", "accuracy", "auc", "f1"]);

// Upload constant not published by the API — the brief says to hardcode it
// with a comment (§4.3) so the client can block oversized files before the
// server writes the whole body to disk only to reject it afterward.
export const MAX_UPLOAD_BYTES = 524_288_000; // 500 MiB, matches the API's undocumented cap

export const DATASET_VERSION_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

// The three drift measurements, in the order the Drift screen shows them.
// The API speaks the monitor stage's vocabulary (feature / prediction /
// performance); these are the words a person reading the screen needs, plus
// the one line that says what each measurement actually compares. Keys stay
// the API's — nothing is renamed on the way in.
export const DRIFT_FACTORS = [
  {
    key: "feature",
    label: "Data drift",
    hint: "Dữ liệu đi vào model lệch so với dữ liệu lúc train.",
    color: "#2563EB",
  },
  {
    key: "prediction",
    label: "Model drift",
    hint: "Phân bố dự đoán của model lệch so với lúc train, dù dữ liệu vào có lệch hay không.",
    color: "#7C3AED",
  },
  {
    key: "performance",
    label: "Performance drift",
    hint: "Model dự đoán sai nhiều hơn trước. Chỉ đo được khi đã có kết quả thật gửi về.",
    color: "#DB2777",
  },
];

// What each agent scenario does, in words. The NAMES come from
// GET /api/scenarios — this map only labels them, so a scenario the backend
// drops simply stops being offered instead of rendering a dead option.
export const SCENARIO_META = {
  none: {
    label: "Traffic bình thường",
    hint: "Dữ liệu thật, không bóp méo. Chứng minh đường đi hoạt động; drift sẽ là “ổn”.",
  },
  price_inflation: {
    label: "Giá rao tăng 20%",
    hint: "list_price bị loại vì leakage nên model không hề nhìn thấy — cố ý không sinh drift.",
  },
  market_rally: {
    label: "Thị trường tăng thật 20%",
    hint: "Giá bán thật tăng còn model thì không biết → performance drift, data drift vẫn “ổn”.",
  },
  market_shift: {
    label: "Traffic dồn về Phoenix",
    hint: "city là feature thật → data drift, thường kéo theo model drift.",
  },
  new_segment: {
    label: "Loại bất động sản chưa từng thấy",
    hint: "property_type = “floating home”, chưa từng có lúc train → data drift.",
  },
};

// Airflow run states that mean the traffic batch is still going.
export const ACTIVE_TRAFFIC_STATES = new Set(["queued", "running"]);
