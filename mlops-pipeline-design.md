# Tài liệu Thiết kế — MLOps Full Pipeline (Offline → AWS)

> Phiên bản 2 — 2026-09-17. Đã chốt các quyết định còn treo ở v1 (xem mục 12 để biết đã đổi gì).

## 1. Mục tiêu

- Xây dựng một pipeline MLOps đầy đủ (data → train → evaluate → register → deploy → monitor) để học và thực hành.
- Giai đoạn 1: chạy **hoàn toàn offline** (local machine / Docker).
- Giai đoạn 2: **migrate dần lên AWS**, tận dụng SageMaker (đã có kinh nghiệm sẵn).
- Kiến trúc offline được thiết kế sao cho khi migrate, thay đổi code là **tối thiểu**.

---

## 2. Nguyên tắc thiết kế

1. **Mỗi stage nặng = 1 container độc lập.** Airflow không chứa business logic ML, chỉ đóng vai trò orchestration (gọi đúng container, đúng thứ tự, đúng lịch). Ngoại lệ: stage `deploy` chỉ là một lời gọi HTTP nên dùng operator sẵn có, không đóng gói image riêng.
2. **Tương thích S3 ngay từ đầu.** Dùng MinIO (S3-compatible) thay vì filesystem thường, để code đọc/ghi qua `boto3` không cần sửa khi chuyển sang S3 thật.
3. **Tách biệt orchestration – tracking – serving – monitoring.** Mỗi thành phần dùng đúng tool chuyên trách, không gộp chung.
4. **Idempotent & retryable.** Mỗi task chạy lại được mà không gây side-effect sai. Cụ thể: output ghi vào đường dẫn xác định theo input (content-addressed), chạy lại thì ghi đè chính nó hoặc skip nếu đã có.
5. **Một bản logic duy nhất cho data cleaning.** Logic làm sạch nằm trong package `common/`, được dùng bởi cả stage `preprocess` lẫn service serving. Không bao giờ có hai bản chép tay của cùng một phép biến đổi.
6. **Pipeline chạy khi người dùng bấm, không tự chạy.** Ngoại lệ duy nhất là `monitoring_dag` — monitoring bản chất là việc liên tục.

---

## 3. Tech Stack

### 3.1. Frontend (Dashboard / Control Room)

| Thành phần | Lựa chọn | Ghi chú |
| --- | --- | --- |
| Ngôn ngữ/nền tảng | ReactJS + TailwindCSS | Bản hiện tại đã build theo hướng này, không phụ thuộc framework |
| Biểu đồ | Chart.js | Vẽ histogram so sánh phân phối cho Drift Detection |
| Giao tiếp với backend | `axios` gọi REST API | Xem API contract ở mục 8.3 |
| State/lưu tạm phía client | `localStorage` | Chỉ dùng cho tiện ích cá nhân (theme, tab đang mở); dữ liệu pipeline thật phải lấy từ backend |
| Đóng gói/serve | nginx container cho offline | Không cần build step phức tạp |

### 3.2. Backend & hạ tầng

| Vai trò | Công nghệ | Ghi chú |
| --- | --- | --- |
| API layer cho Dashboard | FastAPI (Python) — `services/api/` | Đứng giữa Dashboard và Airflow/MLflow/MinIO, trả JSON, xử lý auth |
| Orchestration | Apache Airflow (LocalExecutor) | Điều phối các stage, expose REST API cho API layer gọi |
| Chạy từng stage | Docker container riêng (`DockerOperator`) | Mỗi stage 1 image, dễ migrate sang SageMaker Processing/Training Job |
| Logic ML dùng chung | Package `common/` (cài `pip install -e`) | Schema, transformer, storage wrapper, profiling — xem mục 7.1 |
| Object storage | MinIO (S3-compatible) | Raw/processed data, artifacts, inference log, report |
| Experiment tracking & Model Registry | MLflow (self-host, Postgres làm backend store) | API để API layer đọc/ghi model version |
| Model serving | FastAPI + Uvicorn — `services/serving/` | Load model từ MLflow Registry, expose `/predict`, `/feedback`, `/reload` |
| Sinh traffic mô phỏng | AI agent nghiệp vụ BĐS — `services/agent/` | Bắn request `/predict` và trả ground truth trễ qua `/feedback`; có tham số `drift_scenario` |
| Monitoring / Drift | Evidently AI | So inference log với baseline profile của model đang Production |
| Metadata DB | PostgreSQL | **Hai database tách biệt** trên cùng instance: `airflow` và `mlflow` |
| Auth | API key qua FastAPI | Chưa cần nếu chỉ chạy local 1 người dùng; bắt buộc trước khi expose ra ngoài |
| Containerize / hạ tầng offline | Docker Compose | Toàn bộ service trong 1 `docker-compose.yml` |
| Chất lượng code | `pre-commit` (ruff) + `pytest` chạy local | GitHub Actions chỉ bật khi repo đã push lên GitHub — xem mục 7.8 |

**Không dùng ở giai đoạn 1:** Feature Store (Feast). Lý do ở mục 11.

### 3.3. Tech stack tương ứng khi migrate lên AWS

| Offline | AWS |
| --- | --- |
| FastAPI (API layer riêng) | Giữ nguyên FastAPI, deploy trên ECS/Fargate hoặc Lambda |
| Airflow (LocalExecutor) | MWAA (Managed Workflows for Apache Airflow) |
| MinIO | S3 |
| MLflow self-host | MLflow trên EC2/ECS, hoặc chuyển sang SageMaker Experiments/Model Registry |
| FastAPI serving + `/reload` | SageMaker Endpoint (update endpoint thay cho `/reload`) |
| Inference log tự ghi lên MinIO | SageMaker Data Capture |
| Baseline profile tự tính | SageMaker Model Monitor baseline job |
| Evidently AI (DAG riêng có schedule) | SageMaker Model Monitor schedule |
| Docker Compose | ECS/EKS hoặc SageMaker managed containers |
| PostgreSQL tự host | Aurora |

---

## 4. Kiến trúc tổng quan (Offline)

```
┌──────────────────┐
│    Dashboard     │  React + Tailwind, nginx
│  (Control Room)  │
└────────┬─────────┘
         │ REST (mục 8.3)
         ▼
┌──────────────────┐     Airflow REST     ┌─────────────────────────────┐
│    API layer     │────────────────────▶│  Airflow (LocalExecutor)    │
│    (FastAPI)     │                      │                             │
│  services/api/   │──┐                   │  DAG: ml_pipeline           │
└──────────────────┘  │                   │    conf: task_type,         │
         │            │                   │          force_reprocess    │
         │            │                   │  DAG: monitoring_dag        │
         │            │                   └──────────────┬──────────────┘
         │            │                                  │ DockerOperator
         │            │                                  ▼
         │            │                   ┌─────────────────────────────┐
         │            └──────────────────▶│  MLflow (Tracking+Registry) │
         │                                └──────────────┬──────────────┘
         │                                               │
         └──────────────────┐                            │
                            ▼                            ▼
                   ┌──────────────────────────────────────────────┐
                   │              MinIO (S3-compatible)           │
                   │  raw / processed / artifacts / baseline /    │
                   │  inference-log / ground-truth / reports      │
                   └──────────────────────────────────────────────┘
                            ▲                            ▲
                            │ ghi log                    │ đọc log
                            │                            │
┌──────────────────┐   ┌────┴─────────────┐   ┌──────────┴──────────┐
│   Agent BĐS      │──▶│    Serving       │   │  monitor (Evidently)│
│ services/agent/  │   │   (FastAPI)      │   │  container          │
│  drift_scenario  │   │ /predict         │   └─────────────────────┘
└──────────────────┘   │ /feedback        │
                       │ /reload  ◀───────┼──── deploy task gọi vào
                       └──────────────────┘
```

**Lưu ý có hai service FastAPI khác nhau**, đừng nhầm làm một:
- `services/api/` — backend của Dashboard, không biết gì về model.
- `services/serving/` — phục vụ dự đoán, không biết gì về Dashboard.

### Bảng mapping Offline ↔ AWS

| Vai trò | Offline (giai đoạn 1) | AWS (giai đoạn 2) |
| --- | --- | --- |
| Dashboard / UI quản lý | Web app + API layer riêng | Giữ nguyên frontend, API trỏ sang AWS services |
| Object storage | MinIO | S3 |
| Orchestration | Airflow (Docker Compose, LocalExecutor) | MWAA (Managed Airflow) |
| Training | Container riêng (`DockerOperator`) | SageMaker Training Job |
| Experiment tracking | MLflow (self-host) | MLflow trên EC2/ECS, hoặc SageMaker Experiments |
| Model registry | MLflow Model Registry | SageMaker Model Registry |
| Serving | FastAPI + Docker | SageMaker Endpoint |
| Monitoring | Evidently AI (DAG riêng) | SageMaker Model Monitor |
| CI/CD trigger | Trigger thủ công từ Dashboard | CodePipeline + EventBridge |

---

## 5. Bài toán ML

Pipeline phục vụ **hai model** trên cùng một nguồn dữ liệu:

| Model | Loại | Target | Metric chính | Feature phải loại bỏ (leakage) |
| --- | --- | --- | --- | --- |
| `house_price_regressor` | Regression | `sale_price` | RMSE, MAE, R² | `price_category` |
| `house_sold_fast_classifier` | Classification (binary) | `sold_within_30_days` | F1, AUC, accuracy | `days_on_market`, `sale_price`, `price_category` |

Hai bài toán này đo hai thứ khác nhau (giá bán vs tốc độ bán) nên bổ sung cho nhau. `price_category` không được chọn làm target vì nó suy trực tiếp ra từ `sale_price`, tức là lặp lại bài regression.

**Cột `list_price` cần một quyết định riêng, không phải leakage.** Tại thời điểm dự đoán, giá rao bán đã biết — dùng nó là hợp lệ. Nhưng `sale_price ≈ list_price` với sai số nhỏ, nên đưa vào là bài toán trở nên tầm thường: model sẽ chỉ học một hệ số nhân và R² gần 1 mà không học được gì từ các feature còn lại. Giai đoạn 1 **loại `list_price` khỏi feature** của model regression để bài toán có nội dung thật; giữ lại cho model classification vì tương quan giữa giá rao và tốc độ bán là tín hiệu hữu ích chứ không tầm thường.

Với regression, train trên `log(sale_price)` để giảm skew, nhưng **metric báo cáo phải quy về thang gốc** (RMSE tính bằng đô la) — nếu không thì con số trên dashboard không đọc được, và so sánh champion/challenger cũng sai.

---

## 6. Cấu trúc DAG

### 6.1. `ml_pipeline` — train & deploy

`schedule=None`. Chỉ chạy khi người dùng bấm trên Dashboard.

**Tham số truyền qua `dag_run.conf`:**

| Tham số | Kiểu | Mô tả |
| --- | --- | --- |
| `task_type` | `"regression"` \| `"classification"` | Bắt buộc. Quyết định nhánh nào chạy. |
| `force_reprocess` | bool, mặc định `false` | Bỏ qua cache, chạy lại `preprocess` từ đầu. |
| `dataset_version` | string, mặc định `"latest"` | Chọn phiên bản raw data. |

```
Task 1: extract         → đọc raw data từ MinIO, ghi parquet
Task 2: validate        → check schema (common/schema.py), đếm missing/outlier, fail nếu vi phạm nghiêm trọng
Task 3: preprocess      → cache-aware: tính fingerprint của raw, skip nếu processed/{fingerprint}/ đã tồn tại
Task 4: train           → train theo task_type, log Pipeline + params + metrics vào MLflow
Task 5: evaluate        → hai cổng: threshold sàn + phải hơn model Production (mục 7.5)
Task 6: [branch]        → pass → register; fail → dừng (không deploy)
Task 7: register        → đẩy vào MLflow Registry stage Production + sinh baseline profile
Task 8: deploy          → POST /reload vào serving
```

Dependency:

```
extract → validate → preprocess → train → evaluate → branch ─┬─ register → deploy
                                                             └─ stop_no_deploy
```

`monitor` **không** nằm trong DAG này. Lý do: nó đo traffic production tích luỹ theo thời gian, không đo kết quả của lần train vừa rồi. Chạy nó ngay sau `deploy` thì model vừa lên chưa phục vụ request nào, report sẽ rỗng.

### 6.2. `monitoring_dag` — theo dõi drift

`schedule="@hourly"`. **Đây là DAG duy nhất chạy tự động.**

```
Task 1: collect_window  → đọc inference-log + ground-truth trong cửa sổ gần nhất
Task 2: run_evidently   → so với baseline profile của model đang Production
Task 3: publish_report  → ghi report + mức độ (ok/warning/high) lên MinIO
```

Không tự trigger retrain. Khi mức độ là `high`, Dashboard hiện cảnh báo kèm nút "Retrain ngay" đã điền sẵn `task_type` của model bị ảnh hưởng — người quyết định, không phải hệ thống.

---

## 7. Chi tiết từng thành phần

### 7.1. Package `common/` — nền của cả hệ thống

Đây là thành phần quan trọng nhất về mặt thiết kế. Nó ngăn **training/serving skew**: nếu logic làm sạch bị chép hai bản (một trong `preprocess.py`, một trong `serve/app.py`), chúng sẽ lệch nhau và model sẽ nhận đầu vào khác với lúc train mà không ai phát hiện.

| Module | Trách nhiệm |
| --- | --- |
| `schema.py` | Định nghĩa cột, dtype, ràng buộc hợp lệ (`year_built` ≤ năm hiện tại, `bedrooms` ≥ 0, `zipcode` khớp `^\d{5}$`...). Dùng bởi cả `validate` lẫn `/predict`. |
| `cleaning.py` | Các sklearn transformer cho từng loại dirty: parse `"$450,000"` → float, chuẩn hoá `has_pool` từ 8 cách biểu diễn, chuẩn hoá case/whitespace cho `city`/`state`/`property_type`/`condition`, parse 3 format `listing_date`, clip outlier, xử lý missing. |
| `features.py` | Dựng `sklearn.Pipeline(transformers + estimator)` theo `task_type`. |
| `storage.py` | Wrapper `boto3` + convention đường dẫn. **Đây là điểm duy nhất phải sửa khi migrate sang S3.** |
| `profiling.py` | Tính baseline profile từ một DataFrame. |

Cài bằng `pip install -e common/` vào image `stages/base/` và image serving. `train.py` log nguyên `Pipeline` vào MLflow qua `mlflow.sklearn.log_model` → model trong Registry tự chứa toàn bộ logic clean, và `/predict` nhận record **thô** (đúng như dữ liệu người dùng thật có trong tay).

### 7.2. Airflow

- Executor: `LocalExecutor` (đủ cho 1 máy, không cần Celery/Redis).
- Metadata DB: Postgres, database `airflow`.
- Mỗi task nặng dùng `DockerOperator` gọi image riêng của stage đó.
- Input/output giữa các task truyền qua **đường dẫn trên MinIO**, không qua XCom. XCom chỉ dùng cho giá trị nhỏ (fingerprint, metric, run_id).
- `task_type` đọc từ `dag_run.conf` và truyền xuống container qua biến môi trường.

### 7.3. MinIO — bố cục bucket

```
s3://ml-pipeline/
├── raw/{dataset_version}/data.parquet
├── processed/{raw_fingerprint}/
│   ├── train.parquet
│   └── test.parquet
├── artifacts/                                          # MLflow artifact store
├── monitoring-baseline/{model_name}/{version}/profile.json
├── inference-log/{model_name}/dt=YYYY-MM-DD/part-*.parquet
├── ground-truth/{model_name}/dt=YYYY-MM-DD/part-*.parquet
└── reports/{model_name}/{run_id}/evidently.{html,json}
```

**Dùng Parquet cho mọi thứ sau `extract`.** File CSV gốc 373MB / 2 triệu dòng xuống còn khoảng 60–80MB ở dạng parquet, đọc nhanh hơn nhiều lần, và giữ được dtype nên không phải parse lại mỗi stage. Với một máy local chạy đồng thời Airflow + Postgres + MinIO + MLflow + serving, đây không phải tối ưu sớm mà là điều kiện để chạy được.

**Test set cố định.** Split bằng seed cố định (`42`) và lưu lại `test.parquet`. Nếu test set đổi giữa các lần train thì phép so sánh champion/challenger ở mục 7.5 vô nghĩa.

Code dùng `boto3` với `endpoint_url` trỏ vào MinIO; khi migrate chỉ đổi endpoint sang S3 thật.

### 7.4. Cache của `preprocess`

`preprocess` tính fingerprint của raw data (hash nội dung hoặc `dataset_version` + etag của object) và ghi ra `processed/{fingerprint}/`. Đầu task kiểm tra: nếu prefix đó đã tồn tại và đủ file thì skip.

Lý do: mỗi lần đổi `task_type` để thử model khác, ba stage đầu sẽ cày lại 2 triệu dòng dù dữ liệu không đổi — đó là phần tốn thời gian nhất của cả pipeline. Có cache thì lần chạy thứ hai nhảy thẳng vào `train`.

Dashboard có checkbox **"Xử lý lại dữ liệu từ đầu"** map sang `force_reprocess=true`.

### 7.5. MLflow & cổng `evaluate`

- Tracking server + Model Registry self-host (container riêng), backend store là Postgres database `mlflow`, artifact store là MinIO.
- Mỗi lần train log: params, metrics, `Pipeline` đã fit, và fingerprint của processed data đã dùng.
- Hai model là hai registered model riêng: `house_price_regressor` và `house_sold_fast_classifier`.

`evaluate` có **hai cổng**, phải qua cả hai mới được promote:

1. **Threshold sàn** — chặn model rác.
   - Regression: R² ≥ 0.75
   - Classification: F1 ≥ 0.70
2. **Phải tốt hơn model đang Production** trên **cùng `test.parquet`** — chặn việc đẩy một model kém hơn bản đang chạy lên production chỉ vì nó vượt ngưỡng.

Chưa có model Production nào thì chỉ áp cổng (1).

Con số threshold ở trên là điểm khởi đầu, sẽ hiệu chỉnh sau lần train đầu tiên khi biết baseline thực tế của dataset.

### 7.6. Serving (`services/serving/`)

Image serving **không chứa model**. Lúc khởi động nó load bản `Production` mới nhất của cả hai model từ MLflow Registry vào bộ nhớ.

| Endpoint | Mô tả |
| --- | --- |
| `POST /predict/{model}` | `model` ∈ `regression` \| `classification`. Nhận record **thô** (chưa clean). Trả prediction + `request_id` + `model_version`. Ghi vào inference log. |
| `POST /feedback` | Nhận `{request_id, actual_value}` từ agent. Ghi vào `ground-truth/`. |
| `POST /reload` | Tải lại bản Production mới nhất và swap in-memory. Task `deploy` gọi endpoint này. |
| `GET /health` | Model nào đang load, version bao nhiêu. |

Một container duy nhất phục vụ cả hai model.

**Ghi inference log theo batch**, không ghi một object cho mỗi request: buffer trong bộ nhớ và flush khi đủ 500 record hoặc quá 30 giây. Agent bắn vài nghìn request mà ghi từng file thì MinIO đầy object rác và `monitoring_dag` đọc rất chậm.

Mỗi bản ghi gồm: `request_id`, `timestamp`, `raw_input`, `prediction`, `model_name`, `model_version`.

### 7.7. Agent mô phỏng nghiệp vụ BĐS (`services/agent/`)

Sinh traffic thật cho serving, thay cho việc giả lập drift bằng cách cắt dataset.

- Sinh listing mới theo phân phối mô phỏng thị trường, gọi `POST /predict/{model}`.
- Sau N ngày mô phỏng, báo kết quả thực tế về `POST /feedback` (giá bán thật, hoặc có bán trong 30 ngày không) — đây là nguồn ground truth, join với inference log qua `request_id`.
- **Tham số `drift_scenario`** — bắt buộc phải có:

| Scenario | Mô phỏng |
| --- | --- |
| `none` | Cùng phân phối với tập train — dùng để kiểm tra false positive |
| `price_inflation` | Đẩy mặt bằng giá lên ~20% |
| `market_shift` | Đổi tỉ lệ `city`, dồn giao dịch về thành phố khác |
| `new_segment` | Xuất hiện `property_type` model chưa từng thấy |

Nếu agent chỉ sinh dữ liệu từ đúng phân phối của tập train thì drift sẽ không bao giờ xảy ra, badge lúc nào cũng xanh, và không kiểm chứng được là hệ thống phát hiện đúng. Có scenario thì mới test được cả true positive lẫn false positive.

**Mồi dữ liệu ban đầu:** ngày đầu chưa có traffic thì dashboard trống. Lấy phần dữ liệu mới nhất theo `listing_date` trong CSV gốc, bắn qua `/predict` một lượt — vừa có dữ liệu để xem, vừa là smoke test cho serving.

### 7.8. Monitoring & Drift (Evidently)

**Baseline là profile thống kê gắn với một model version, không phải một dataset.**

Ở stage `register`, tính profile của đúng tập train đã dùng cho version đó — per-column mean/std/quantile, histogram bins, tỉ lệ missing, phân phối category — rồi ghi `monitoring-baseline/{model_name}/{version}/profile.json`.

Hai hệ quả quan trọng: baseline **tự sinh cùng lúc model được register**, không ai phải bấm "đặt làm baseline" thủ công; và không bao giờ có chuyện so model v3 với baseline của v1.

`monitoring_dag` so **ba loại drift**, không phải một:

| Loại | So cái gì | Khi nào có | Preset Evidently |
| --- | --- | --- | --- |
| **Feature drift** | Phân phối input trong log vs baseline profile | Ngay lập tức | `DataDriftPreset` |
| **Prediction drift** | Phân phối output `/predict` vs phân phối prediction lúc train | Ngay lập tức | `TargetDriftPreset` trên cột prediction |
| **Performance drift** | Prediction vs giá bán thật (join `request_id`) | Chỉ khi có ground truth | Metric hồi quy/phân loại trên cửa sổ |

Phân biệt ba loại này là phần đáng học nhất của cả dự án. Feature drift và prediction drift đo được ngay vì không cần nhãn. Performance drift mới là thứ thực sự quan trọng, nhưng nó **luôn đến trễ** — lúc agent hỏi giá một căn nhà, chưa ai biết nó bán được bao nhiêu.

Output: report HTML + JSON lên `reports/`, kèm mức độ tổng hợp `ok` / `warning` / `high` để Dashboard hiển thị badge.

### 7.9. Cấu hình & bí mật

- `.env.example` commit vào repo; `.env` thật thì gitignore.
- Biến chính: `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MLFLOW_TRACKING_URI`, `POSTGRES_*`, `SERVING_URL`, `API_KEY`.
- Trong Airflow, credential MinIO/MLflow khai báo qua **Airflow Connections**, không hardcode trong DAG.

### 7.10. Image dùng chung

`stages/base/Dockerfile` chứa Python + pandas + scikit-learn + `common/` đã cài. Bảy stage còn lại `FROM ml-base`. Không có bước này thì mỗi Dockerfile tự cài lại dependency: build rất lâu và version dễ lệch giữa các stage — mà version lệch giữa lúc train và lúc serve chính là kiểu bug khó tìm nhất.

### 7.11. Test

`tests/` tập trung vào `common/`, vì đó là chỗ bug sẽ âm thầm làm hỏng cả model lẫn serving.

- Mỗi loại dirty trong dataset (8 loại liệt kê ở `house_pricing_README.md`) có ít nhất một test khẳng định transformer xử lý đúng: `"$450,000"` → `450000.0`, `"Y"`/`"True"`/`"1"` → `True`, `"NEW YORK"`/`"new_york"`/`" New York "` → `"new york"`, cả 3 format ngày parse được, zipcode 4 số bị bắt.
- Test round-trip: cùng một record thô đi qua `preprocess` và đi qua `Pipeline` trong model phải ra kết quả giống nhau.
- Chạy bằng `pytest`, kèm `pre-commit` (ruff lint + format).
- GitHub Actions chỉ cấu hình khi repo đã push lên GitHub — nó là dịch vụ cloud, không chạy offline được.

---

## 8. Dashboard quản lý (Control Room)

Dashboard là **thành phần chính thức của hệ thống**, không phải công cụ minh hoạ tạm thời — đây là nơi thao tác chính với pipeline: chạy/theo dõi stage, xem log, upload data, quản model, theo dõi drift.

Bản frontend hiện tại: [MLOps Control Room](https://claude.ai/artifact/TamgADr7Xfmp6Ae8RE4RBG). Source cần được đưa về `dashboard/` trong repo.

### 8.1. Các màn hình

| Màn hình | Chức năng | Thay đổi so với bản frontend hiện tại |
| --- | --- | --- |
| Tổng quan | Chọn loại model (regression/classification) → trigger chạy pipeline; xem trạng thái + log gần đây từng stage | **Thêm dropdown chọn `task_type`** và checkbox "Xử lý lại dữ liệu từ đầu" |
| Stages & Logs | Lọc log theo stage / level / từ khoá | Đọc log thật từ Airflow |
| Dữ liệu | Upload CSV, xem preview + thống kê từng cột | Parse bằng pandas ở backend, không parse trong JS |
| Models | Xem model version (tên, version, metric, stage), promote lên production | **Cột metric động theo loại model**: rmse/mae/r2 cho regression, f1/auc/accuracy cho classification — không hardcode accuracy/f1 nữa |
| Drift Detection | Hiển thị report Evidently: 3 loại drift, badge ok/warning/high, histogram | Đọc report có sẵn, không tính drift bằng JS; **thêm nút "Retrain ngay"** khi mức độ là `high` |
| ~~Feature Store~~ | Bỏ khỏi giai đoạn 1 | Xem mục 11 |

### 8.2. Vì sao cần API layer

Frontend hiện tại tự tính toán/lưu mọi thứ phía client (localStorage, mô phỏng chạy pipeline bằng `setTimeout`, tính drift bằng JS thuần). Để dashboard thao tác trên pipeline **thật**, cần một lớp API đứng giữa dashboard và các thành phần trong kiến trúc.

Gọi thẳng Airflow/MLflow REST API từ browser không dùng được: credential sẽ lộ trong frontend, CORS phải mở cho nhiều service, và mỗi lần đổi backend (Airflow → MWAA, MLflow → SageMaker) là phải sửa frontend. API layer che toàn bộ những thứ đó — khi migrate chỉ sửa `services/api/`, frontend giữ nguyên.

### 8.3. API contract (Dashboard ↔ `services/api/`)

Đây là hợp đồng frontend gọi vào. Cột cuối là thứ API layer gọi tiếp ở phía sau.

| Method | Endpoint | Mô tả | Gọi xuống |
| --- | --- | --- | --- |
| `POST` | `/api/pipeline/run` | Body: `{task_type, force_reprocess}`. Trả `run_id` | Airflow `POST /dags/ml_pipeline/dagRuns` |
| `GET` | `/api/pipeline/runs` | Danh sách run gần đây + trạng thái | Airflow REST |
| `GET` | `/api/pipeline/runs/{run_id}` | Trạng thái từng task của một run | Airflow REST |
| `GET` | `/api/pipeline/runs/{run_id}/logs` | Query: `stage`, `level`, `q` | Airflow task log |
| `POST` | `/api/data/upload` | Upload CSV → MinIO `raw/`, trả `dataset_version` | MinIO |
| `GET` | `/api/data/{dataset_version}/preview` | Preview + thống kê cột (pandas ở backend) | MinIO |
| `GET` | `/api/models` | Danh sách registered model + version + metric + stage | MLflow REST |
| `POST` | `/api/models/{name}/{version}/promote` | Chuyển version sang Production | MLflow REST |
| `GET` | `/api/drift/latest` | Report mới nhất: mức độ, 3 loại drift, dữ liệu histogram | MinIO `reports/` |
| `GET` | `/api/drift/history` | Diễn biến mức độ drift theo thời gian | MinIO `reports/` |
| `GET` | `/api/health` | Trạng thái các service phụ thuộc | Tất cả |

---

## 9. Cấu trúc thư mục project

```
project/
├── common/                       # package dùng chung — mục 7.1
│   ├── pyproject.toml
│   └── ml_common/
│       ├── schema.py
│       ├── cleaning.py
│       ├── features.py
│       ├── storage.py
│       └── profiling.py
├── dags/
│   ├── ml_pipeline_dag.py        # train & deploy, schedule=None
│   └── monitoring_dag.py         # drift, @hourly
├── stages/
│   ├── base/Dockerfile           # python + pandas/sklearn + common/
│   ├── extract/
│   ├── validate/
│   ├── preprocess/
│   ├── train/
│   ├── evaluate/
│   ├── register/                 # promote + sinh baseline profile
│   └── monitor/                  # Evidently
├── services/
│   ├── serving/                  # /predict /feedback /reload
│   ├── api/                      # backend cho dashboard
│   └── agent/                    # agent mô phỏng BĐS
├── dashboard/                    # React + Tailwind, nginx
├── tests/
├── docker-compose.yml
├── .env.example
└── README.md
```

`stages/` không có thư mục `deploy/`: stage đó chỉ là một lời gọi HTTP `POST /reload` nên dùng operator sẵn có của Airflow, đóng gói cả một image để gửi một request là thừa. `register` thì vẫn giữ container vì nó phải tính baseline profile trên tập train.

---

## 10. Lộ trình triển khai

| Bước | Nội dung |
| --- | --- |
| 1 | Setup Docker Compose: Airflow + Postgres (2 DB) + MinIO + MLflow. Xác nhận 4 service nói chuyện được với nhau. |
| 2 | Viết `common/`: `schema.py`, `cleaning.py`, `storage.py` + test cho cả 8 loại dirty. **Làm trước mọi stage** — các stage chỉ là lớp vỏ mỏng quanh package này. |
| 3 | `stages/base/` + `extract`, `validate`, `preprocess` (có cache theo fingerprint). Test chạy tay từng container. |
| 4 | `train.py` cho regression, log `Pipeline` vào MLflow. Kiểm tra model load lại được và predict từ record thô. |
| 5 | `evaluate.py` (2 cổng) + `register.py` (promote + sinh baseline profile). |
| 6 | `services/serving/`: `/predict`, `/reload`, `/health` + ghi inference log theo batch. |
| 7 | Ghép thành `ml_pipeline` DAG, test full run cho regression. |
| 8 | Thêm nhánh classification (`sold_within_30_days`), test chạy cả hai `task_type`. |
| 9 | `services/agent/`: sinh traffic + `drift_scenario`. Mồi inference log từ dữ liệu theo `listing_date`. |
| 10 | `/feedback` + ghi ground truth; `monitor.py` với Evidently; `monitoring_dag`. Kiểm chứng: chạy `drift_scenario=none` phải ra `ok`, chạy `price_inflation` phải ra `high`. |
| 11 | `services/api/` theo contract mục 8.3. |
| 12 | Nối `dashboard/` vào API layer, bỏ toàn bộ phần mock trong JS. |
| 13 | (Nâng cao) Auto-retrain khi drift vượt ngưỡng, kèm cooldown. |
| 14 | **Migrate**: MinIO → S3 (sửa `common/storage.py`), Airflow → MWAA, serving → SageMaker Endpoint, inference log → Data Capture, Evidently → Model Monitor. |

Bước 2 đứng trước tất cả các stage là có chủ ý: nếu viết `preprocess.py` trước rồi sau đó mới tách ra `common/`, thì khả năng cao logic sẽ bị chép sang serving trước khi kịp tách.

---

## 11. Phạm vi bị cắt khỏi giai đoạn 1

**Feature Store (Feast).** Ở v1 nó có mặt trong tech stack và trong danh sách màn hình dashboard, nhưng không xuất hiện trong DAG, cấu trúc thư mục hay lộ trình — tức là chưa từng được thiết kế thật. Feast kéo theo một registry Postgres riêng và một job materialization, trong khi pipeline batch này chưa có nhu cầu online feature serving: giá trị thực tế của nó ở đây chỉ là một tab trên dashboard.

Cân nhắc lại sau khi pipeline chạy ổn. Khi đó nó sẽ đứng giữa `preprocess` và `train`, và map sang SageMaker Feature Store lúc migrate.

---

## 12. Thay đổi so với phiên bản 1

| Hạng mục | v1 | v2 |
| --- | --- | --- |
| Bài toán ML | Chưa chốt | 2 model: regression `sale_price` + classification `sold_within_30_days` |
| Cấu trúc DAG | 1 DAG 8 task | `ml_pipeline` (manual, có `task_type`) + `monitoring_dag` (@hourly) |
| Lịch chạy | Chưa chốt | Manual từ UI; chỉ `monitoring_dag` tự động |
| Preprocess | Chạy lại mỗi lần | Cache theo fingerprint của raw data |
| Logic cleaning | Không nói rõ | Package `common/`, đóng gói vào model qua sklearn Pipeline |
| `/predict` | Không định nghĩa input | Nhận record thô, model tự clean |
| Stage `deploy` | Build image + restart container | `POST /reload` vào serving |
| Drift | "So data mới vs baseline", không rõ nguồn | Inference log từ agent vs baseline profile gắn model version; 3 loại drift |
| Ground truth | Không có | `POST /feedback`, join qua `request_id` |
| Baseline | Thư mục rỗng `monitoring-baseline/` | Profile JSON sinh tự động ở stage `register` |
| Retrain | Câu hỏi mở | Cảnh báo + nút bấm, không tự động |
| `evaluate` | Threshold cố định | Threshold sàn **và** phải hơn model Production, trên test set cố định |
| Định dạng data | Không nói | Parquet sau `extract` |
| Postgres | "Có thể tách DB" | Tách `airflow` / `mlflow` |
| Feature Store | Trong stack | Cắt khỏi giai đoạn 1 |
| CI/CD | "GitHub Actions (offline)" | `pre-commit` + `pytest` local; GH Actions khi đã có remote |
| Cấu trúc thư mục | Thiếu register, common, services, tests, base | Đầy đủ (mục 9) |
| API dashboard | Liệt kê endpoint của Airflow | Contract riêng của API layer (mục 8.3) |

---

## 13. Câu hỏi còn mở

- [x] Dataset: **House Pricing** (giả lập, ~2 triệu dòng, dirty) — `house_pricing_dirty.csv` + mô tả ở `house_pricing_README.md`.
- [x] Bài toán, threshold, lịch chạy, chiến lược retrain, kiến trúc API dashboard — đã chốt ở v2.
- [ ] Con số threshold cụ thể (R² 0.75 / F1 0.70) cần hiệu chỉnh sau lần train đầu tiên, khi biết baseline thực tế của dataset.
- [ ] Khi migrate: giữ MLflow song song với SageMaker Registry, hay chuyển hẳn? Quyết ở giai đoạn 2, không ảnh hưởng việc build hiện tại.
- [ ] Cửa sổ thời gian của `monitoring_dag` (1 giờ gần nhất? 24 giờ trượt?) — phụ thuộc tốc độ agent sinh traffic, chốt sau bước 9.
