# Plan 5a — API layer: Thiết kế

Ngày: 2026-09-20. Tiếp sau Plan 4 (Monitoring & Drift).

Tương ứng bước 11 của lộ trình ở `mlops-pipeline-design.md` mục 10. Bước 12
(nối dashboard) là Plan 5b.

---

## 1. Phạm vi

Plan 5a dựng `services/api/` — lớp đứng giữa dashboard và phần còn lại của hệ
thống. Sau plan này, **toàn bộ pipeline điều khiển được qua HTTP** mà không cần
mở Airflow UI hay chạy script.

Vào:

- `services/api/` — FastAPI, 11 endpoint theo mục 8.3, đóng gói thành image riêng.
- `AIRFLOW__API__AUTH_BACKENDS` trong compose — bắt buộc, xem 2.1.
- `sample_rows` thành param của DAG `ml_pipeline` — xem 2.3.
- `scripts/verify_api.ps1`.

Không vào:

- `dashboard/` — Plan 5b. Plan này chỉ dựng thứ dashboard sẽ gọi.
- Auth bằng API key — xem 2.5.
- Auto-retrain. §6.2 đã chốt từ Plan 4: cảnh báo, người quyết định.
- Sửa `services/serving/` hay `stages/monitor/`. API chỉ **đọc** thứ chúng ghi ra.

Tách khỏi 5b vì API layer tự chứng minh được giá trị: `curl` được, test được
bằng pytest, và dựng xong thì dashboard có một nền đã chạy thật để bám vào thay
vì dữ liệu giả — đúng lỗi mà mục 8.2 đang phê phán ở bản frontend hiện tại.

---

## 2. Quyết định kiến trúc

### 2.1. Airflow REST đang trả 401 — phải bật basic auth trước mọi thứ khác

**Đây là việc chặn đường, đo được, không phải suy đoán.** Kiểm ngày 2026-09-20:

```
curl -u admin:admin http://localhost:8080/api/v1/dags
-> HTTP 401 Unauthorized

airflow config get-value api auth_backends
-> airflow.api.auth.backend.session
```

Airflow 2.10 mặc định chỉ bật `session` backend, tức là chỉ nhận cookie phiên
từ trình duyệt. Một service gọi bằng basic auth **luôn** bị từ chối, và thông
điệp 401 không hề gợi ý nguyên nhân là thiếu backend chứ không phải sai mật
khẩu.

Phải thêm vào cả `airflow-webserver` lẫn `airflow-scheduler` trong compose:

```yaml
AIRFLOW__API__AUTH_BACKENDS: "airflow.api.auth.backend.basic_auth,airflow.api.auth.backend.session"
```

Giữ `session` phía sau để Airflow UI trong trình duyệt vẫn đăng nhập được như cũ.

Task đầu của implementation plan là bật cờ này và **chứng minh bằng một lần
`curl` trả 200**, trước khi viết bất kỳ dòng route nào. Nếu không, mọi endpoint
gọi xuống Airflow sẽ hỏng cùng một kiểu và rất dễ bị chẩn đoán nhầm thành lỗi
code.

### 2.2. Mọi collaborator được inject, giống hệt serving

`create_app()` nhận `airflow_client`, `mlflow_client`, `storage` — mặc định là
bản thật, nhưng test truyền bản giả. Đây là khuôn đã chứng minh hiệu quả ở
`services/serving/`: 20 test chạy trong 4 giây, không cần MLflow, không cần
MinIO, không cần container.

Hệ quả cho cấu trúc file: mỗi nhóm endpoint có một **client** riêng lo việc nói
chuyện với hệ thống phía sau, và route chỉ lo HTTP. Ranh giới: client **biết
Airflow/MLflow/MinIO trả về gì**, route **biết dashboard cần thấy gì**.

Không gộp tất cả vào một `app.py`. Plan 3 đã tách `model_registry.py` khỏi
`app.py` vì đúng lý do này, và điều đó làm cả hai test được độc lập.

### 2.3. `sample_rows` phải thành param của DAG

Hiện tại `dags/ml_pipeline_dag.py:226` đọc:

```python
"SAMPLE_ROWS": os.environ.get("SAMPLE_ROWS", ""),
```

Tức là lấy từ **môi trường của scheduler**, cố định cho mọi lần chạy. Dashboard
không có cách nào chọn số dòng, vì giá trị đã bị đóng băng lúc container
scheduler khởi động.

Đổi thành param của DAG, giống cách `task_type` và `force_reprocess` đang làm,
với mặc định lấy từ môi trường để hành vi CLI hiện tại không đổi:

```python
params={
    "task_type": "regression",
    "force_reprocess": False,
    "dataset_version": "v1",
    "estimator_name": None,
    "sample_rows": None,        # None = dùng toàn bộ dòng
},
```

**Không có rủi ro dữ liệu.** `compute_fingerprint(dataset_version, etag,
sample_rows)` đã tính `sample_rows` vào fingerprint ngay từ Plan 1, chính vì lý
do này: một lần chạy 200k dòng không bao giờ được dùng lại tập processed dựng
từ 2 triệu dòng. Đổi số dòng sinh fingerprint khác, và cache tự phân tách.

### 2.4. Upload đọc theo luồng, không nạp vào bộ nhớ

Ổ C còn ~17GB và máy 16GB RAM đang chạy 7 container. `POST /api/data/upload`
nhận file CSV hàng trăm MB, nên:

- Ghi thẳng xuống đĩa tạm theo từng chunk rồi mới đẩy lên MinIO qua
  `storage.upload_file()` — hàm này đã có từ Plan 1 và tồn tại đúng vì lý do
  này ("materializing it as a DataFrame just to upload it would not fit").
- Có trần kích thước, trả `413` khi vượt, thay vì để máy hết RAM.
- Xoá file tạm trong `finally`, kể cả khi upload hỏng.

`seed_raw_data.py` đã giải đúng bài toán này bằng `pd.read_csv(chunksize=...)`.
API đi theo cùng nguyên tắc, không phát minh lại.

### 2.5. Không auth ở giai đoạn này, nhưng gom vào đúng một chỗ

Mục 3.2 viết: *"Chưa cần nếu chỉ chạy local 1 người dùng; bắt buộc trước khi
expose ra ngoài."* Giữ nguyên quyết định đó.

Nhưng mọi endpoint khai báo một FastAPI dependency rỗng `require_auth()` ngay từ
đầu. Hôm nay nó không làm gì. Khi cần API key, sửa **một hàm** thay vì sửa 11
route và chắc chắn bỏ sót một cái.

Đây là cái giá rẻ nhất có thể trả cho một quyết định đã biết trước là sẽ phải
đảo ngược.

### 2.6. Dashboard chỉ được nói chuyện với API layer

Ràng buộc kiến trúc, không phải gợi ý. Dashboard **không** gọi thẳng Airflow,
MLflow hay MinIO. Lý do ở mục 8.2: credential sẽ lộ trong frontend, CORS phải
mở cho nhiều service, và mỗi lần đổi backend là phải sửa frontend.

Hệ quả cụ thể khi migrate: MinIO → S3, Airflow → MWAA, MLflow → SageMaker đều
chỉ phải sửa `services/api/`. Dashboard không biết chúng tồn tại.

Plan 5b sẽ có một bước kiểm grep frontend tìm `localhost:8080`, `localhost:5000`,
`localhost:9000` — giống cách `verify_serving.ps1` grep tìm import `cleaning`/
`rowops`. Ranh giới nào đáng có thì đáng được kiểm tự động.

---

## 3. API contract

Tất cả đường dẫn có tiền tố `/api`. Mọi lỗi trả `{"detail": "..."}` theo chuẩn
FastAPI.

### Pipeline

| Method | Path | Body / Query | Trả về |
| --- | --- | --- | --- |
| `POST` | `/pipeline/run` | `{task_type, force_reprocess, sample_rows, dataset_version}` | `{run_id, dag_id, state}` |
| `GET` | `/pipeline/runs` | `?limit=20` | danh sách `{run_id, state, task_type, started_at, ended_at}` |
| `GET` | `/pipeline/runs/{run_id}` | — | `{run_id, state, tasks: [{task_id, state, try_number, duration}]}` |
| `GET` | `/pipeline/runs/{run_id}/logs` | `?stage=&level=&q=` | `{lines: [...], truncated: bool}` |

`sample_rows` là `int | None`; `None` nghĩa là dùng toàn bộ dòng. Giá trị âm
hoặc 0 trả `422`.

Log lấy **khi người dùng bấm xem**, không stream. Lọc `level` và `q` làm ở
backend để không đẩy hàng nghìn dòng qua mạng rồi mới lọc bằng JS — đúng lỗi
mục 8.1 đang sửa. `truncated` cho biết đã cắt bớt, để UI nói thật thay vì im
lặng hiển thị thiếu.

### Dữ liệu

| Method | Path | Body / Query | Trả về |
| --- | --- | --- | --- |
| `POST` | `/data/upload` | multipart CSV | `{dataset_version, rows, size_mb}` |
| `GET` | `/data/{dataset_version}/preview` | `?rows=50` | `{columns: [...], sample: [...], total_rows}` |

`preview` trả cho mỗi cột: tên, kiểu theo schema, `missing_rate`,
`out_of_bounds` — tính bằng `ml_common.validation`, **không tính lại bằng tay**.
`rows` chỉ giới hạn số dòng mẫu hiển thị; nó không liên quan tới `sample_rows`
của lần train, và UI phải nói rõ hai thứ đó khác nhau.

### Models

| Method | Path | Trả về |
| --- | --- | --- |
| `GET` | `/models` | mỗi model: `{name, task_type, versions: [{version, metrics, is_champion, created_at}]}` |
| `POST` | `/models/{name}/{version}/promote` | `{name, version, alias: "champion"}` |

`metrics` là **những khoá có thật** của model đó, không phải bộ cố định:
regression có `rmse`/`mae`/`r2`, classification có `auc`/`f1`/`accuracy`. Mục
8.1 nêu đích danh lỗi hardcode `accuracy`/`f1` ở bản frontend cũ. API trả đúng
những gì MLflow có, và UI đọc khoá động.

`promote` chuyển alias `champion`, **không** dùng stage — MLflow deprecate
stages ở 2.x và bỏ ở 3.x. Trả `404` khi version không tồn tại.

### Drift

| Method | Path | Trả về |
| --- | --- | --- |
| `GET` | `/drift/latest` | `?model_name=` → nguyên `summary.json` Plan 4 ghi |
| `GET` | `/drift/history` | `?model_name=&limit=20` → danh sách summary, mới nhất trước |

`latest` đọc đúng một object qua `drift_latest_key()` — Plan 4 ghi đè nó mỗi lần
chạy chính vì mục đích này. `history` liệt kê `reports/{model}/` rồi đọc từng
`summary.json`, bỏ qua object nào không phải summary.

Trường `report_key` trong summary trỏ tới file HTML của Evidently. API **không**
proxy file đó; Plan 5b quyết định hiển thị thế nào.

### Health

`GET /health` trả trạng thái từng phụ thuộc:

```json
{"status": "degraded",
 "services": {"airflow": "ok", "mlflow": "ok", "minio": "ok",
              "serving": "down", "postgres": "ok"}}
```

Luôn HTTP 200. `degraded` là trạng thái để đọc, không phải request hỏng — cùng
nguyên tắc `/health` của serving từ Plan 3.

---

## 4. Danh sách component UI

Phác ở đây để **kiểm chứng contract ở mục 3**: nếu một component không có
endpoint nào nuôi nó, hoặc một endpoint không component nào dùng, thì một trong
hai chỗ sai. Bản đầy đủ kèm trạng thái và tương tác sẽ nằm trong spec 5b — đây
là đầu vào cho Claude design.

**Dùng chung**

| Component | Dữ liệu từ | Ghi chú |
| --- | --- | --- |
| `AppShell` | — | sidebar 5 mục + topbar có `HealthPill` |
| `StatusBadge` | mọi nơi | **4 trạng thái**: `ok`, `warning`, `high`, `insufficient_data` |
| `MetricTile` | `/models`, `/drift/latest` | số lớn + nhãn + hướng tốt/xấu |
| `DataTable` | nhiều | sort, filter, phân trang |
| `EmptyState` | mọi màn hình | ngày đầu chưa có traffic thì mọi màn đều trống |
| `ErrorState` | mọi màn hình | phân biệt "service chết" với "chưa có dữ liệu" |
| `LoadingSkeleton` | mọi màn hình | pipeline chạy ~10 phút, không được để màn trắng |
| `ConfirmDialog` | promote, retrain | thao tác ghi thật, phải xác nhận |
| `Toast` | mọi thao tác ghi | báo thành công/thất bại |
| `RelativeTime` | mọi nơi | "3 phút trước", kèm tooltip giờ tuyệt đối |

**Tổng quan** — `TaskTypeSelector` · `RunTriggerForm` (task_type, force_reprocess, **sample_rows**, dataset_version) · `PipelineStageStrip` (7 stage theo trạng thái) · `RecentRunsTable`

**Stages & Logs** — `StageTabs` · `LogFilterBar` (stage / level / từ khoá) · `LogViewer` (mono, tô theo level, báo khi `truncated`)

**Dữ liệu** — `DatasetUploader` (drag-drop, tiến độ, báo lỗi khi vượt trần) · `DataPreviewTable` · `ColumnStatsTable` (missing %, out-of-bounds) · `RowLimitPicker`

**Models** — `ModelVersionTable` (**cột metric đổi theo task_type**) · `ChampionBadge` · `PromoteButton`

**Drift** — `SeverityOverview` (**tách 3 loại**: feature / prediction / performance) · `DriftHistoryChart` · `EvidentlyReportFrame` · `RetrainCTA` (hiện khi `high`, điền sẵn task_type) · `InsufficientDataNotice`

**Hai điều Claude design phải làm đúng, vì chúng là bài học đắt nhất của Plan 4:**

1. **`insufficient_data` phải trông khác `ok`.** Chưa đo được không phải là ổn.
   Vẽ nó thành dấu xanh là dựng lại đúng lời nói dối mà Plan 4 mục 2.6 dựng ra
   để tránh.
2. **Ba loại drift phải hiện riêng, không gộp thành một badge.** Plan 4 đo được
   `market_rally`: feature drift `ok` trong khi performance `high`. Một badge
   tổng hợp màu xanh ở đó sẽ nói dối. Xem
   `docs/superpowers/specs/2026-09-20-plan4-monitoring-measurements.md`.

---

## 5. Cấu trúc thư mục mới

```
services/api/
  __init__.py
  app.py                    # create_app + wiring, khong chua logic
  clients/
    __init__.py
    airflow.py              # goi Airflow REST, tra dict da chuan hoa
    registry.py             # goi MLflow, tra version + metric
    reports.py              # doc drift summary tu object storage
  routes/
    __init__.py
    pipeline.py
    data.py
    models.py
    drift.py
    health.py
  deps.py                   # require_auth() rong, cho tuong lai
  Dockerfile
  tests/
    __init__.py
    test_pipeline.py
    test_data.py
    test_models.py
    test_drift.py
    test_health.py

scripts/verify_api.ps1
```

`clients/` biết hệ thống phía sau trả gì; `routes/` biết dashboard cần gì. Tách
ra thì test được client bằng HTTP giả mà không cần FastAPI, và test được route
bằng client giả mà không cần Airflow.

---

## 6. Thay đổi trong code đã có

| File | Thay đổi | Vì sao |
| --- | --- | --- |
| `docker-compose.yml` | Thêm `AIRFLOW__API__AUTH_BACKENDS` cho webserver + scheduler; thêm service `api` | Xem 2.1 |
| `dags/ml_pipeline_dag.py` | Thêm param `sample_rows`, đọc từ param thay vì env | Xem 2.3 |
| `scripts/build_stage_images.ps1` | Không đổi | `api` là service, không phải stage |
| `CLAUDE.md` | Lệnh build/verify + trạng thái | Đã có tiền lệ |

`services/serving/`, `stages/`, `common/ml_common/` **không đổi**. API chỉ đọc
thứ chúng đã ghi ra, và dùng `ml_common.storage` cho mọi key.

---

## 7. Test

| Tầng | Test gì | Chạy ở đâu |
| --- | --- | --- |
| `clients/` | Chuẩn hoá phản hồi Airflow/MLflow; xử lý 404, 401, timeout | Máy dev, HTTP giả |
| `routes/` | Mã trạng thái, validate body, hình dạng phản hồi | Máy dev, client giả |
| `test_data.py` | Trần kích thước trả 413; file tạm bị xoá kể cả khi hỏng | Máy dev |
| `test_models.py` | Cột metric đổi theo task_type; promote 404 khi thiếu version | Máy dev |
| `test_drift.py` | `latest` khi chưa có report; `history` bỏ qua object lạ | Máy dev |
| `verify_api.ps1` | 11 endpoint trả đúng mã trên hạ tầng thật | Cần stack chạy |

Không test nào được cần Airflow/MLflow/MinIO thật, trừ `verify_api.ps1`.

---

## 8. Definition of Done

1. `pytest common/ services/` xanh ở cả 3.13 (máy) lẫn 3.12 (container).
2. `ruff check .` sạch.
3. `ml-api:latest` build được; service `api` lên trong compose.
4. **`curl -u admin:admin http://localhost:8080/api/v1/dags` trả 200** — điều
   kiện tiên quyết, hiện đang 401.
5. `POST /api/pipeline/run` với `sample_rows=1000` khởi động được một DAG run
   thật, và run đó **thực sự dùng 1000 dòng** (kiểm bằng fingerprint trong
   MLflow params, không phải bằng lời).
6. `GET /api/drift/latest` trả đúng nội dung `summary.json` Plan 4 đã ghi.
7. `GET /api/models` trả `rmse`/`mae`/`r2` cho regression và `auc`/`f1`/
   `accuracy` cho classification — **khoá khác nhau**, không phải bộ cố định.
8. `POST /api/models/{name}/{version}/promote` chuyển được alias, và
   `GET /api/models` phản ánh ngay sau đó.
9. `scripts\verify_api.ps1` xanh.

Điểm 5 và 7 là chỗ plan này chứng minh mình có giá trị: một API trả dữ liệu
tĩnh trông giống hệt một API trả dữ liệu thật, cho tới khi bạn đổi tham số và
kiểm xem phía sau có đổi theo không.

---

## 9. Chỗ tài liệu này lệch khỏi `mlops-pipeline-design.md`

| Chỗ | Tài liệu gốc | Plan 5a | Lý do |
| --- | --- | --- | --- |
| §8.3 | `POST /api/pipeline/run` nhận `{task_type, force_reprocess}` | Thêm `sample_rows` và `dataset_version` | Yêu cầu chọn số dòng train — xem 2.3 |
| §8.3 | Không nói về auth của Airflow REST | Bắt buộc thêm `AIRFLOW__API__AUTH_BACKENDS` | Đo được 401 — xem 2.1 |
| §8.1 | Màn Drift hiện "badge ok/warning/high" | Bốn trạng thái, và tách 3 loại drift | Kết quả đo của Plan 4 — xem mục 4 |
| §3.2 | Auth bằng API key qua FastAPI | Hoãn, nhưng đặt sẵn dependency rỗng | Mục 3.2 tự nói "chưa cần nếu chạy local" |

Vá ngược vào `mlops-pipeline-design.md` sau khi Plan 5a chạy xong, cùng cách
Plan 3 và Plan 4 đã làm.

---

## 10. Câu hỏi còn mở

- **Trần kích thước upload chưa chốt.** Đề xuất 500MB (`house_pricing_dirty.csv`
  là 373MB), nhưng phải đo dung lượng trống thật trước khi cố định.
- **Phân trang `/pipeline/runs`** dùng `limit` đơn giản. Nếu số run lớn lên thì
  cần cursor; chưa cần bây giờ.
- **`/pipeline/runs/{id}/logs` cắt ở bao nhiêu dòng** chưa chốt. Phải xem log
  thật của một run dài rồi mới quyết, thay vì đoán.
- **Plan 4 còn nợ race flush buffer** — khi dashboard bắn traffic rồi xem drift
  ngay, nó sẽ gặp đúng race đó. Plan 5b cần biết, có thể phải hiện "đang ghi".
