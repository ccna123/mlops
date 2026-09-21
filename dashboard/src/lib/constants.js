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
