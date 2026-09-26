# Tài liệu Thiết kế — MLOps Full Pipeline (Offline → AWS)

> Phiên bản 4 — 26/09/2026. Mô tả hệ thống ở trạng thái hiện tại, sau năm giai đoạn xây dựng và giai đoạn 6 (đưa hệ thống khớp với 要件定義書 và 基本設計書 bản 1.3). Các thay đổi so với những phiên bản trước và lý do của từng thay đổi được gom ở mục 12; thay đổi của phiên bản 4 ở mục 12.3.

**Tài liệu liên quan**

| Tài liệu | Dành cho | Nội dung |
| --- | --- | --- |
| Tài liệu này | Người phát triển, người review kỹ thuật | Thiết kế kỹ thuật, có tên thành phần, đường dẫn, tham số. Là nguồn sự thật cho code. |
| `docs/01-requirements-definition.md` (要件定義書) | Bên thứ ba, không cần đọc code | Hệ thống phải làm gì. Mỗi yêu cầu có mã (CN-xx, PCN-xx). |
| `docs/02-basic-design.md` (基本設計書) | Bên thứ ba, không cần đọc code | Hệ thống được xây như thế nào, kèm các hạn chế đã biết. |
| `house_pricing_README.md` | Mọi người | Bộ dữ liệu và 8 loại lỗi dữ liệu |
| `docs/superpowers/specs/` | Người phát triển | Thiết kế chi tiết từng giai đoạn, kèm số đo đã dẫn tới các quyết định |

Ba tài liệu đầu phải nói cùng một điều. Khi tài liệu này thay đổi, hai tài liệu cho bên thứ ba phải được cập nhật theo.

---

## 1. Mục tiêu

- Xây dựng một pipeline MLOps đầy đủ (dữ liệu → huấn luyện → đánh giá → đăng ký → đưa vào sử dụng → giám sát) để học và thực hành.
- Giai đoạn 1: chạy **hoàn toàn offline** trên một máy, bằng Docker.
- Giai đoạn 2: **chuyển dần lên AWS**, tận dụng SageMaker.
- Kiến trúc giai đoạn 1 được thiết kế sao cho khi chuyển lên AWS, phần code phải sửa là **ít nhất có thể**.

---

## 2. Nguyên tắc thiết kế

1. **Mỗi bước xử lý nặng là một container độc lập.** Airflow chỉ điều phối (gọi đúng container, đúng thứ tự); nó không chứa logic học máy. Ngoại lệ: bước `deploy` chỉ là một lời gọi HTTP nên dùng operator có sẵn của Airflow, không đóng gói image riêng.
2. **Tương thích S3 ngay từ đầu.** Dữ liệu nằm trên MinIO (tương thích S3) thay vì hệ thống tệp thường, để phần đọc/ghi không phải sửa khi chuyển sang S3 thật.
3. **Tách biệt điều phối, quản lý mô hình, dự đoán và giám sát.** Mỗi phần dùng công cụ chuyên trách, không gộp chung.
4. **Chạy lại được mà không gây sai lệch.** Đầu ra của mỗi bước được ghi vào vị trí xác định hoàn toàn bởi đầu vào; chạy lại thì ghi đè chính nó hoặc bỏ qua nếu đã có.
5. **Chỉ một bản logic làm sạch dữ liệu.** Logic làm sạch nằm trong package `common/` và được **đóng gói bên trong mô hình**, nên lúc huấn luyện và lúc dự đoán dùng đúng một bản. Không bao giờ có hai bản chép tay của cùng một phép biến đổi.
6. **Không quy trình nào chạy theo lịch ở giai đoạn 1.** Huấn luyện, mô phỏng lưu lượng và giám sát đều chạy khi người vận hành yêu cầu, và mỗi quy trình chỉ chạy một lần tại một thời điểm. Lý do: máy 16 GB đã chật; một tác vụ nặng tự chạy trong nền là thứ người ta quên mất rồi không hiểu vì sao máy chậm. Khi chuyển lên AWS, giám sát trở lại chạy mỗi giờ.

---

## 3. Tech Stack

### 3.1. Frontend (Dashboard)

| Thành phần | Lựa chọn | Ghi chú |
| --- | --- | --- |
| Nền tảng | React 18 + Tailwind CSS 4, build bằng Vite 5; biểu tượng lucide-react | Mã nguồn ở `dashboard/` |
| Biểu đồ | Chart.js 4 (qua react-chartjs-2) | Diễn biến trôi, so sánh chỉ số |
| Gọi backend | `fetch` qua một hàm `api()` dùng chung, chỉ gọi đường dẫn tương đối `/api` | Dashboard **không bao giờ** gọi thẳng Airflow, MLflow hay MinIO (mục 8.2) |
| Chạy khi phát triển | Vite dev server ở cổng 5173, proxy `/api` → `http://localhost:8001` | Trình duyệt không gọi khác origin, nên không cần CORS |
| Chạy bản chính thức | **Chưa chọn** | Hoặc API tự phục vụ thư mục build, hoặc thêm CORS với danh sách origin cụ thể (mục 13) |
| Lưu phía trình duyệt | `localStorage`, chỉ cho tiện ích cá nhân | Dữ liệu nghiệp vụ luôn lấy từ backend |
| Chế độ minh hoạ | Công tắc ở thanh bên; dùng dữ liệu mẫu thay vì gọi API | Để xem giao diện khi hệ thống phía sau chưa chạy |

### 3.2. Backend & hạ tầng

| Vai trò | Công nghệ | Ghi chú |
| --- | --- | --- |
| API layer cho Dashboard | FastAPI — `services/api/`, cổng 8001 | 22 endpoint (mục 8.3). Đứng giữa Dashboard và Airflow / MLflow / MinIO / serving. |
| Điều phối | Apache Airflow 2.10, `LocalExecutor` | Bốn DAG (mục 6) |
| Chạy từng bước | Mỗi bước một image riêng, chạy bằng `DockerOperator` | Dễ chuyển sang SageMaker Processing / Training Job |
| Logic ML dùng chung | Package `common/` (`ml_common`) | Mục 7.1 |
| Thuật toán | scikit-learn, XGBoost | Mục 7.5 |
| Object storage | MinIO (tương thích S3) | Mục 7.3 |
| Theo dõi thí nghiệm & quản lý phiên bản mô hình | MLflow 2.x tự host; backend store là PostgreSQL, artifact store là MinIO | Registry dùng **alias `champion`** (mục 7.5) |
| Dịch vụ dự đoán | FastAPI + Uvicorn — `services/serving/` | Mục 7.6 |
| Sinh lưu lượng mô phỏng | Agent — `services/agent/` | Mục 7.7 |
| Giám sát trôi | Evidently 0.7 | Chỉ có trong image `ml-monitor` (mục 7.10). Evidently tính mọi con số; `ml_common` xếp mức (mục 7.8). |
| Metric theo thời gian | Prometheus 2.54 + Pushgateway 1.9 | Serving bị scrape; các bước batch push (mục 7.12). Giữ 15 ngày. |
| Dashboard theo dõi và alert | Grafana 11.2 | Datasource, dashboard, alert rule, contact point đều là file provisioning trong `docker/grafana/` (mục 7.12) |
| CSDL quản lý | PostgreSQL | **Hai database tách biệt** trên cùng instance: `airflow` và `mlflow` |
| Xác thực | **Chưa có** | Mọi endpoint của API layer đã khai báo sẵn một dependency rỗng `require_auth` (`services/api/deps.py`), nên thêm xác thực về sau là sửa **một hàm**, không phải từng route. Khi chưa có xác thực, mọi endpoint ghi — kể cả xoá mô hình — mở cho bất kỳ ai tới được cổng 8001. Chấp nhận được khi chạy local một người dùng; **bắt buộc** phải có trước khi mở ra ngoài. |
| Hạ tầng offline | Docker Compose | Toàn bộ service trong một `docker-compose.yml` |
| Chất lượng code | ruff (cấu hình ở `ruff.toml` tại gốc repo) qua `pre-commit`; `pytest` local | CI bằng GitHub Actions (`.github/workflows/ci.yml`, mục 7.11) |

**Không dùng ở giai đoạn 1:** Feature Store (Feast). Lý do ở mục 11.

### 3.3. Tech stack tương ứng khi chuyển lên AWS

| Offline | AWS |
| --- | --- |
| API layer (FastAPI) | Giữ nguyên, triển khai trên ECS/Fargate hoặc Lambda |
| Airflow (`LocalExecutor`) | MWAA (Managed Workflows for Apache Airflow) |
| MinIO | S3 |
| MLflow tự host | MLflow trên EC2/ECS, hoặc SageMaker Experiments / Model Registry |
| Serving + `/reload` | SageMaker Endpoint (cập nhật endpoint thay cho `/reload`) |
| Inference log do serving tự ghi | SageMaker Data Capture |
| Mốc giám sát tự tính | SageMaker Model Monitor baseline job |
| Evidently, chạy theo yêu cầu | SageMaker Model Monitor schedule, **chạy mỗi giờ** |
| Prometheus + Pushgateway | CloudWatch Metrics, hoặc Amazon Managed Service for Prometheus |
| Grafana alert | CloudWatch Alarms + SNS, hoặc Amazon Managed Grafana |
| Docker Compose | ECS/EKS hoặc container do SageMaker quản lý |
| PostgreSQL tự host | Aurora |

---

## 4. Kiến trúc tổng quan (Offline)

```
┌──────────────────┐
│    Dashboard     │  React + Tailwind (Vite)
└────────┬─────────┘
         │ /api (mục 8.3)
         ▼
┌──────────────────┐   Airflow REST (basic auth)  ┌─────────────────────────────────┐
│    API layer     │─────────────────────────────▶│  Airflow (LocalExecutor)        │
│    (FastAPI)     │                              │   DAG ml_pipeline   (mục 6.1)   │
│  services/api/   │──┐                           │   DAG monitoring_dag (mục 6.2)  │
└────────┬─────────┘  │                           │   DAG traffic_agent (mục 6.3)   │
         │            │                           │   DAG feedback_data_pipeline    │
         │            │                           └───────────────┬─────────────────┘
         │            │                                           │ DockerOperator
         │            │                                           ▼
         │            │                           ┌─────────────────────────────────┐
         │            └──────────────────────────▶│  MLflow (Tracking + Registry)   │
         │                                        └───────────────┬─────────────────┘
         │                                                        │
         ▼                                                        ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                           MinIO (tương thích S3)                               │
│  raw / extracted / processed / artifacts / monitoring-baseline /               │
│  inference-log / ground-truth / reports                                        │
└────────────────────────────────────────────────────────────────────────────────┘
         ▲ ghi log                                               ▲ đọc log
         │                                                       │
┌────────┴─────────┐   ┌──────────────────┐             ┌────────┴────────────┐
│  Agent           │──▶│    Serving       │             │  monitor            │
│  services/agent/ │   │   (FastAPI)      │             │  (Evidently)        │
│  5 kịch bản      │   │ /predict         │             │  container          │
└──────────────────┘   │ /feedback        │             └─────────────────────┘
                       │ /reload  ◀───────┼──── deploy (smoke test), API sau promote/xoá
                       │ /flush   ◀───────┼──── monitoring_dag, trước khi đo
                       │ /metrics ◀───────┼──── Prometheus scrape (mục 7.12)
                       └──────────────────┘
```

**Có hai service FastAPI khác nhau**, không được gộp làm một:

- `services/api/` — backend của Dashboard, không biết gì về mô hình.
- `services/serving/` — phục vụ dự đoán, không biết gì về Dashboard.

### Bảng mapping Offline ↔ AWS

| Vai trò | Offline (giai đoạn 1) | AWS (giai đoạn 2) |
| --- | --- | --- |
| Dashboard | Web app + API layer riêng | Giữ nguyên frontend, API layer trỏ sang dịch vụ AWS |
| Object storage | MinIO | S3 |
| Điều phối | Airflow (Docker Compose, `LocalExecutor`) | MWAA |
| Huấn luyện | Container riêng (`DockerOperator`) | SageMaker Training Job |
| Theo dõi thí nghiệm | MLflow tự host | MLflow trên EC2/ECS, hoặc SageMaker Experiments |
| Model registry | MLflow Model Registry | SageMaker Model Registry |
| Serving | FastAPI + Docker | SageMaker Endpoint |
| Giám sát | Evidently, chạy theo yêu cầu | SageMaker Model Monitor, chạy mỗi giờ |
| Khởi chạy huấn luyện | Thủ công từ Dashboard | CodePipeline + EventBridge |

---

## 5. Bài toán ML

Pipeline phục vụ **hai mô hình** trên cùng một nguồn dữ liệu:

| Registered model | Loại | Target | Metric dùng làm cổng | Metric báo cáo thêm | Feature bị loại |
| --- | --- | --- | --- | --- | --- |
| `house_price_regressor` | Regression | `sale_price` (đô la) | R² (sàn), RMSE (so champion) | MAE | `property_id`, `sale_price`, `price_category`, `list_price` |
| `house_needs_renovation_classifier` | Classification nhị phân | `needs_renovation` = `condition` ∈ {`poor`, `fair`} | AUC (sàn và so champion) | F1, accuracy | `property_id`, `condition`, `sale_price`, `days_on_market`, `sold_within_30_days`, `price_category` |

Danh sách feature bị loại là nguồn sự thật duy nhất ở `common/ml_common/schema.py`.

**Vì sao hai bài toán này.** Chúng đo hai điều khác nhau — giá bán và tình trạng tài sản — nên bổ sung cho nhau. `price_category` không được chọn làm target vì nó suy trực tiếp từ `sale_price`, tức là lặp lại bài regression.

**Vì sao target classification là `needs_renovation`.** Ba ứng viên đã được đo trên 48.000 dòng thật:

| Ứng viên | AUC (mô hình dạng cây, mọi feature hợp lệ) | Kết luận |
| --- | --- | --- |
| `sold_within_30_days` | 0,58 | Loại. Target suy trực tiếp từ `days_on_market`, cột bắt buộc phải loại; bỏ nó đi thì gần như không còn tín hiệu. |
| Bán cao hơn giá rao (`sale_price > list_price`) | 0,50 | Loại. Dữ liệu giả lập sinh mục này hoàn toàn ngẫu nhiên. |
| `needs_renovation` | **0,71** | **Chọn.** Tín hiệu phân tán thật: không cột đơn lẻ nào vượt 0,56. Tỉ lệ lớp dương khoảng 25%. |

`needs_renovation` không có trong dữ liệu thô; nó được sinh từ `condition` ở bước chuẩn bị dữ liệu (mục 6.1). Vì vậy `condition` là cột leakage của bài toán classification. Ý nghĩa nghiệp vụ: `condition` do người bán tự khai, hay bỏ trống hoặc khai lạc quan; dự đoán nó từ thuộc tính khách quan giúp nền tảng bất động sản gắn cờ tin cần thẩm định, ngân hàng đánh giá tài sản thế chấp, nhà đầu tư tìm nhà cần cải tạo.

**Cột `list_price` là một quyết định riêng, không phải leakage.** Lúc dự đoán, giá rao bán đã biết — dùng nó là hợp lệ. Nhưng `sale_price ≈ list_price` với sai số nhỏ, nên đưa vào mô hình regression thì bài toán trở nên tầm thường: mô hình chỉ học một hệ số nhân. Vì vậy `list_price` **bị loại khỏi regression** và **được giữ cho classification**, nơi nó là feature đơn lẻ mạnh nhất (AUC 0,56).

**Regression không biến đổi target.** Mô hình được huấn luyện thẳng trên `sale_price` và báo cáo metric bằng đô la. Huấn luyện trên `log(sale_price)` đã được thử và bỏ: đo trên 48.000 dòng thật, phép quy đổi ngược `expm1` khuếch đại sai số ở nhóm nhà giá cao tới mức Ridge ra R² −0,40 và dự đoán một căn 28,3 triệu đô (giá thật cao nhất là 2,39 triệu), trong khi mô hình dạng cây không đổi. Một test trong `common/tests/test_estimators.py` canh chừng để phép biến đổi không lặng lẽ quay lại.

---

## 6. Cấu trúc DAG

Cả bốn DAG đều `schedule=None` và `max_active_runs=1`, và được thiết kế để luôn ở trạng thái **unpaused**. Một lần chạy của DAG đang paused sẽ nằm `queued` vĩnh viễn mà không có tín hiệu nào trên API hay Dashboard cho biết vì sao. `traffic_agent` và `feedback_data_pipeline` tự đặt `is_paused_upon_creation=False`; hai DAG còn lại thì không, và `docker-compose.yml` đặt `AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: "true"`, nên **trên một máy mới phải unpause tay `ml_pipeline` và `monitoring_dag` một lần**.

`ml_pipeline` và `feedback_data_pipeline` báo kết quả mỗi lần chạy (thành công / bị cổng chặn / thất bại / smoke test thất bại) lên Pushgateway qua callback ở cấp DAG (`dags/run_outcome.py`), để alert rule "pipeline thất bại" đọc được (mục 7.12).

### 6.1. `ml_pipeline` — huấn luyện và đưa vào sử dụng

**Tham số** (gửi qua `conf` của lần trigger, Airflow gộp vào `params`):

| Tham số | Kiểu | Mặc định | Mô tả |
| --- | --- | --- | --- |
| `task_type` | `"regression"` \| `"classification"` | Bắt buộc | Quyết định nhánh nào chạy |
| `estimator_name` | chuỗi hoặc rỗng | Rỗng = `xgboost` cho cả hai bài toán | Thuật toán, phải thuộc danh sách của `task_type` (mục 7.5) |
| `tune_hyperparameters` | bool | `false` | Bật tìm tham số bằng Grid Search với time-based cross-validation (mục 7.5) |
| `sample_rows` | số nguyên > 0, hoặc rỗng | Rỗng = toàn bộ train set | Số dòng **lấy ngẫu nhiên từ train set** cho lần chạy này (seed cố định). Test set không đổi. Nằm trong data ID (mục 7.4). |
| `force_reprocess` | bool | `false` | Bỏ qua cache, chuẩn bị lại dữ liệu từ đầu |
| `dataset_version` | chuỗi | `"v1"` | Phiên bản dữ liệu thô. Giá trị được nối thẳng vào đường dẫn, nên không có khái niệm `"latest"`. |

`model_name` **không phải tham số**: DAG suy nó từ `task_type`, để không thể vô tình ghi một mô hình classification vào registered model của regression.

**Cảnh báo:** trigger từ Airflow UI mà không kèm `conf` sẽ train trên toàn bộ train set và có thể làm cạn RAM máy 16 GB. Dashboard luôn gửi `sample_rows`.

**Chín task:**

| Task | Loại | Việc làm |
| --- | --- | --- |
| `extract` | Docker | Đọc **toàn bộ** `raw/{dataset_version}/data.parquet`, ghi bản làm việc vào `extracted/{working_copy_id}/`; đọc split point trong manifest (tính và lưu một lần cho phiên bản cũ chưa có); tính data ID (mục 7.4) |
| `validate` | Docker | Đo chất lượng dữ liệu trên bản làm việc, ghi báo cáo. Chỉ fail khi dữ liệu **vô dụng** (xem dưới) |
| `prepare_dataset_for_train` | Docker | Sinh target, bỏ trùng, bỏ thiếu target, chia theo split point, lấy mẫu ngẫu nhiên train set. Có cache (mục 7.4) |
| `train` | Docker | Xếp train set theo thời gian, huấn luyện, log nguyên `Pipeline` và thông tin truy vết vào MLflow (mục 7.5) |
| `evaluate` | Docker | Chấm trên test set, áp hai cổng có biên độ, metric theo nhóm, đếm trùng với champion (mục 7.5). Luôn kết thúc thành công; kết quả đi qua XCom |
| `branch_on_gates` | Python | Đạt → `register`; không đạt → `stop_no_deploy` |
| `register` | Docker | Ghi lại champion cũ, đăng ký phiên bản, gắn alias `champion`, sinh `profile.json` và model card, lấy một record thô mẫu cho smoke test |
| `deploy` | Python | `POST /reload`, rồi **smoke test**: serving phải báo đúng version mới và trả lời được record mẫu bằng version đó. Không đạt thì **rollback** alias về champion cũ (hoặc gỡ alias), reload lại, và fail task (`dags/deploy_check.py`) |
| `stop_no_deploy` | Empty | Kết thúc, **không** đổi champion |

```
extract → validate → prepare_dataset_for_train → train → evaluate → branch_on_gates ─┬─ register → deploy
                                                                                     └─ stop_no_deploy
```

Ở mỗi lần chạy, một trong hai nhánh sau `branch_on_gates` ở trạng thái `skipped`. Đó là hành vi bình thường.

**Luật của `validate`.** Dataset cố tình dirty, nên `validate` **đo và báo cáo**, không chặn dữ liệu bẩn. Nó chỉ fail trong ba trường hợp:

1. Thiếu cột so với `schema.COLUMNS`.
2. Hơn 50% giá trị target bị thiếu. Với classification, kiểm trên cột nguồn `condition`, vì `needs_renovation` chưa tồn tại ở bước này.
3. Không có dòng nào.

Mọi thứ khác — tỉ lệ thiếu từng cột, giá trị ngoài biên, zipcode sai định dạng, dòng trùng — chỉ được đếm và ghi vào `reports/validation/{working_copy_id}.json`.

**`prepare_dataset_for_train` không làm sạch theo cột.** Nó chỉ sinh target, loại dòng trùng `property_id` (**trước khi chia**, để một căn nhà không thể vừa ở train vừa ở test), loại dòng thiếu target, xếp dòng vào train / test / simulation theo split point, rồi lấy mẫu train set. Dữ liệu trong `processed/` **vẫn thô ở mức cột** — vẫn còn `"$450,000"`, `"NEW YORK"`, zipcode 4 số. Toàn bộ việc làm sạch theo cột nằm trong `Pipeline` và được đóng gói cùng mô hình (mục 7.1). Tên `processed/` vì vậy chỉ có nghĩa "đã xử lý theo dòng và đã chia tập". Simulation set không bao giờ được ghi vào `processed/`.

Để vừa RAM khi số dòng nhỏ, bước này đọc hai lượt: lượt đầu chỉ vài cột nhẹ để quyết định dòng nào được chọn (`ml_common.preparation.plan_rows`), lượt sau chỉ giải mã đầy đủ những dòng được chọn (`Storage.read_parquet_rows`).

`monitor` **không** nằm trong DAG này: nó đo lưu lượng tích luỹ theo thời gian, không đo kết quả của lần huấn luyện vừa xong. Chạy ngay sau `deploy` thì mô hình mới chưa phục vụ request nào và báo cáo sẽ rỗng.

### 6.2. `monitoring_dag` — theo dõi trôi

- **Khởi chạy bởi:** task `compute_drift` của `traffic_agent` (mục 6.3), hoặc `POST /api/drift/run` (không có nút riêng trên Dashboard).
- **Task đầu tiên, `flush_prediction_log`**, gọi `POST /flush` của serving và chờ nó ghi xong bộ đệm nhật ký dự đoán. Không bao giờ fail: nếu flush lỗi, giám sát vẫn chạy và mỗi summary ghi rõ việc đó (trường `flush`), thay vì im lặng tính trên dữ liệu thiếu.
- **Hai task giám sát chạy song song** sau đó, `monitor_regression` và `monitor_classification`. Mỗi task là **một container `ml-monitor`** làm trọn việc: đọc cửa sổ dữ liệu, cho Evidently tính, xếp mức, ghi báo cáo, push mức lên Pushgateway (mục 7.8).
- Không tách thành ba task "thu thập / so sánh / công bố": XCom chỉ chở được giá trị nhỏ, nên ba task riêng sẽ phải tự đọc lại cửa sổ dữ liệu ba lần.
- **Không tự trigger huấn luyện lại.** Khi có mức `high`, Dashboard gợi ý tạo dữ liệu phản hồi rồi hiện nút "Retrain" đã điền sẵn `task_type` — người quyết định, không phải hệ thống.
- Khi chuyển lên MWAA, trả lại `schedule="@hourly"`.

### 6.3. `traffic_agent` — mô phỏng lưu lượng rồi tính trôi

Tồn tại vì trôi chỉ tính được từ dự đoán mà serving đã ghi. Trên máy phát triển không có người dùng thật, nên nếu không có DAG này mọi kết quả giám sát đều là `insufficient_data`.

| Tham số | Giá trị | Mặc định |
| --- | --- | --- |
| `scenario` | Một trong năm kịch bản (mục 7.7) | `none` |
| `task_type` | `regression` \| `classification` | `regression` (Dashboard gửi theo mô hình đang xem) |
| `count` | 1 – 5.000 (API giới hạn) | 300 |

```
send_traffic → compute_drift
```

- `send_traffic`: `DockerOperator` chạy image `ml-agent`, tham số truyền bằng dòng lệnh. Seed lấy theo thời điểm của lần chạy, để chạy lại cùng kịch bản thì mở rộng mẫu thay vì gửi trùng các căn nhà cũ.
- `compute_drift`: `TriggerDagRunOperator(wait_for_completion=True)` trigger `monitoring_dag` và chờ nó xong; `monitoring_dag` fail thì task này fail. Nhờ vậy trạng thái của một lần chạy `traffic_agent` trả lời trọn câu hỏi "đã xong hết chưa".
- Nối ở tầng DAG chứ không nối ở Dashboard, để người vận hành đóng trình duyệt giữa chừng thì trôi vẫn được tính.
- `max_active_runs=1` để lưu lượng của hai kịch bản không trộn vào cùng một cửa sổ — nếu trộn, báo cáo không quy được kết quả cho kịch bản nào.

Đo ngày 22/09/2026: cả chuỗi khoảng 40 giây (18,5 giây gửi lưu lượng, 20,6 giây tính trôi). Chưa đo lại sau khi thêm bước flush và mục data quality.

### 6.4. `feedback_data_pipeline` — tạo phiên bản dữ liệu từ lưu lượng thực tế

Thực hiện CN-42: những căn nhà đã được dự đoán **và** đã có ground truth trở thành dữ liệu huấn luyện trong một phiên bản dữ liệu mới. Huấn luyện lại trên đúng dữ liệu cũ thì mô hình mới học y hệt mô hình cũ, nên không sửa được trôi.

| Tham số | Giá trị | Mặc định |
| --- | --- | --- |
| `task_type` | `regression` \| `classification` | Bắt buộc |
| `new_version` | Tên phiên bản mới (cùng luật đặt tên của upload); tên đã có bị từ chối | Bắt buộc |
| `source_version` | Phiên bản dữ liệu nguồn | Rỗng = phiên bản mà champion đã học (tra qua MLflow) |
| `period_start`, `period_end` | Thời điểm ISO có múi giờ | Rỗng = 30 ngày gần nhất |

Một task, `build_feedback_dataset`, image `ml-build-feedback`; toàn bộ luật nằm ở `ml_common.feedback`:

1. Ghép nhật ký dự đoán và ground truth trong khoảng thời gian qua `request_id`, chỉ giữ dự đoán đã có kết quả.
2. Mỗi cặp thành một feedback record: `raw_input` đúng như đã gửi (mọi giá trị lưu dạng text như dữ liệu thô), kết quả thật ghi vào cột nhãn (`sale_price` hoặc `needs_renovation`), `record_source = "feedback"`, `predicted_at`. Một căn nhà được dự đoán nhiều lần thì giữ lần muộn nhất.
3. Dưới **500** feedback record thì dừng và báo lý do: test set sẽ quá nhỏ để tin được.
4. Dữ liệu mới = feedback record + dữ liệu của phiên bản nguồn, **trừ các record gốc cùng `property_id`** (hai nhãn mâu thuẫn cho một căn nhà).
5. Split point: test set = 20% feedback record có `predicted_at` muộn nhất; train set = toàn bộ train set và test set của nguồn cộng 80% feedback sớm hơn; simulation set = simulation set của nguồn trừ các căn đã thành feedback.
6. Ghi dữ liệu và manifest (split point + nguồn gốc: phiên bản nguồn, khoảng thời gian, số feedback record, số record gốc bị thay thế).

Test set là phần feedback mới nhất vì mô hình mới phải chứng minh nó dự đoán tốt **thị trường mới**, và champion chưa từng học các record đó nên cổng 2 so sánh công bằng.

---

## 7. Chi tiết từng thành phần

### 7.1. Package `common/` — nền của cả hệ thống

Đây là thành phần quan trọng nhất về mặt thiết kế. Nó ngăn **training/serving skew**: nếu logic làm sạch bị chép thành hai bản — một cho lúc huấn luyện, một cho serving — chúng sẽ lệch nhau và mô hình sẽ nhận đầu vào khác với lúc học mà không ai phát hiện.

| Module | Trách nhiệm |
| --- | --- |
| `schema.py` | Danh sách 24 cột, loại dữ liệu, khoảng giá trị hợp lệ, giá trị phân loại hợp lệ, target, danh sách cột leakage theo bài toán, tên registered model theo bài toán |
| `parsers.py` | Hàm parse thuần trên **một giá trị đơn lẻ**: `"$450,000"` → float, `has_pool` từ 8 cách biểu diễn, 3 định dạng `listing_date`, zipcode, chuẩn hoá text. Không biết gì về pandas. |
| `cleaning.py` | Transformer sklearn **theo cột**: `RawRecordCleaner`, `OutlierClipper`, `DateFeatures` |
| `rowops.py` | Thao tác **theo dòng**: `drop_duplicates`, `drop_rows_missing_target` |
| `splits.py` | Chia train / test / simulation theo thời gian: tính split point, xếp record vào tập, thứ tự thời gian cho cross-validation, random seed dùng chung |
| `datasets.py` | Tạo phiên bản dữ liệu **không ghi đè**, đọc và tạo manifest |
| `preparation.py` | Chọn dòng cho train set và test set (theo dòng — chỉ stage prepare dùng) |
| `feedback.py` | Dựng phiên bản dữ liệu từ lưu lượng thực tế (theo dòng — chỉ stage feedback dùng) |
| `features.py` | Dựng `Pipeline` (transformer + estimator) theo `task_type` |
| `targets.py` | Sinh cột target (parse `sale_price`, sinh `needs_renovation` từ `condition`, hoặc dùng nhãn có sẵn của feedback record) |
| `estimators.py` | Danh sách thuật toán, thuật toán mặc định, lưới tìm tham số, fold theo thời gian, bộ bọc decision threshold |
| `metrics.py` | Chỉ số dùng chung cho `train`, `evaluate`, giám sát; chỉ số theo nhóm |
| `gates.py` | Hai cổng quyết định promote, kèm biên độ |
| `validation.py` | Luật của `validate` |
| `fingerprint.py` | Working copy ID và data ID — khoá cache nối dữ liệu với dữ liệu thô sinh ra nó |
| `lineage.py` | Truy ngược model version → run → data ID → train set |
| `model_card.py` | Nội dung model card |
| `storage.py` | Wrapper `boto3` và **toàn bộ** quy ước đường dẫn trên object storage. **Điểm duy nhất phải sửa khi chuyển sang S3.** |
| `rawdata.py` | Chuyển CSV thô thành parquet (dùng chung cho upload qua API và script nạp dữ liệu ban đầu) |
| `profiling.py` | Tính hồ sơ thống kê cơ sở |
| `inference_log.py` | Bộ đệm nhật ký dự đoán: khi nào ghi, bỏ gì khi đầy. Không tự ghi MinIO. |
| `evidently_adapter.py` | Chỗ **duy nhất** biết định dạng kết quả của Evidently; đọc kết quả thành cấu trúc số cố định. Không import Evidently. |
| `drift.py` | Phần giám sát không cần Evidently: đọc cửa sổ, ghép ground truth, **luật xếp mức** của bốn mục, đếm cảnh báo liên tiếp |
| `pushgateway.py` | Đẩy metric của bước batch lên Pushgateway (chỉ thư viện chuẩn) |
| `stageio.py` | Cách một stage trả kết quả về Airflow |

**Ranh giới giữa `cleaning.py` và các module theo dòng (`rowops`, `preparation`, `feedback`) là ràng buộc kiến trúc, không phải cách tổ chức file.** Transformer trong `cleaning.py` nằm trong `Pipeline` và được đóng gói cùng mô hình, nên chúng chạy ở cả lúc huấn luyện (tới 2 triệu dòng) lẫn serving (một record). Một transformer xoá dòng sẽ chạy đúng suốt lúc huấn luyện rồi trả về DataFrame rỗng khi `/predict` gọi nó, làm serving sập. `features.py`, `estimators.py` và serving không bao giờ import các module theo dòng — CI kiểm tra điều này (mục 7.11).

`train` log nguyên `Pipeline` vào MLflow, nên mô hình trong Registry **tự chứa toàn bộ logic làm sạch** (và decision threshold, với classification), và `/predict` nhận record **thô** — đúng như dữ liệu người dùng thật có trong tay. Serving không import `cleaning` lẫn `rowops`.

**Thứ tự bên trong `Pipeline`:** `RawRecordCleaner` → `OutlierClipper` → `DateFeatures` → chọn cột theo bài toán → impute + scale / one-hot → estimator. Thứ tự này là ràng buộc: nếu `OutlierClipper` hay `DateFeatures` chạy trước `RawRecordCleaner`, giá dạng chuỗi và ngày ở ba định dạng sẽ **âm thầm** thành giá trị thiếu, không có lỗi nào xuất hiện.

**Xử lý giá trị lạ lúc dự đoán:** cột thiếu được thêm với giá trị thiếu; giá trị số thiếu điền trung vị của tập huấn luyện; giá trị phân loại thiếu điền giá trị phổ biến nhất; giá trị phân loại chiếm dưới 1% gộp vào nhóm "hiếm"; giá trị phân loại chưa từng gặp không gây lỗi.

### 7.2. Airflow

- `LocalExecutor` (đủ cho một máy, không cần Celery/Redis). Metadata DB là database `airflow` trên PostgreSQL.
- Mỗi task nặng dùng `DockerOperator` gọi image riêng. Chỉ `airflow-scheduler` được mount docker socket; webserver không cần và không được cấp.
- Dữ liệu giữa các task đi qua **đường dẫn trên MinIO**, không qua XCom. XCom chỉ chở giá trị nhỏ (ID, run_id, metric, version, split point, một record mẫu). Mỗi stage in đúng một dòng JSON có tiền tố ở stdout; dòng đó là giá trị XCom (`stageio.py`).
- Tham số của lần chạy đi vào container qua biến môi trường. Digest của image `ml-train` được DAG đọc qua Docker API ngay trước khi chạy và truyền vào (`IMAGE_DIGEST`), để ghi truy vết.
- Các module dùng chung của DAG chỉ dùng thư viện chuẩn (`deploy_check.py`, `run_outcome.py`), vì image Airflow không có `ml_common`. Chúng được test trong `common/tests/` bằng cách nạp theo đường dẫn.
- API layer gọi Airflow REST bằng basic auth. Airflow 2.10 mặc định chỉ nhận phiên đăng nhập của trình duyệt, nên `docker-compose.yml` bật thêm `AIRFLOW__API__AUTH_BACKENDS: "airflow.api.auth.backend.basic_auth,airflow.api.auth.backend.session"` cho mọi service Airflow. Thiếu dòng này, mọi lời gọi từ API layer bị `401` với thông báo không gợi ý đúng nguyên nhân.

### 7.3. MinIO — bố cục bucket

```
s3://ml-pipeline/
├── raw/{dataset_version}/
│   ├── data.parquet
│   └── manifest.json                                           # split point, nguồn gốc
├── extracted/{working_copy_id}/data.parquet                    # bản làm việc: TOÀN BỘ dữ liệu thô
├── processed/{data_id}/{task_type}/
│   ├── train.parquet
│   └── test.parquet
├── artifacts/                                                  # MLflow artifact store (có model_card.json, group_metrics.json)
├── monitoring-baseline/{model_name}/{version}/profile.json
├── inference-log/{model_name}/dt=YYYY-MM-DD/part-*.parquet
├── ground-truth/{model_name}/dt=YYYY-MM-DD/part-*.parquet
└── reports/
    ├── validation/{working_copy_id}.json                       # báo cáo của validate
    └── {model_name}/
        ├── latest.json                                         # bản sao tóm tắt mới nhất
        └── {run_id}/
            ├── summary.json                                    # tóm tắt một lần giám sát
            ├── evidently.html                                  # báo cáo chi tiết
            └── evidently.json                                  # kết quả data drift của Evidently
```

Mọi key được sinh bởi hàm `*_key()` / `*_prefix()` trong `storage.py`; không file nào khác tự nối đường dẫn — CI kiểm tra điều này.

**Parquet cho mọi dữ liệu dạng bảng.** CSV gốc 373 MB / 2 triệu dòng xuống khoảng 60–80 MB, đọc nhanh hơn nhiều lần, và giữ được kiểu dữ liệu.

**Dữ liệu thô vào MinIO bằng ba đường:** `scripts/seed_raw_data.py` nạp `house_pricing_dirty.csv` thành `raw/v1/` một lần lúc cài đặt; `POST /api/data/upload` cho các phiên bản sau; và `feedback_data_pipeline` (mục 6.4). Cả ba **từ chối tên đã tồn tại** (API trả 409): mô hình đã học từ một phiên bản phải truy ngược được về đúng dữ liệu đó. Cả ba ghi manifest cùng lúc với dữ liệu. `extract` chỉ đọc từ object storage.

**Versioning.** `minio-init` bật versioning cho bucket, kèm luật vòng đời xoá phiên bản cũ sau một ngày ở mọi vùng **trừ `raw/`**. Nhờ vậy dữ liệu thô bị xoá hay ghi đè bằng tay vẫn khôi phục được, còn các vùng hay bị ghi đè (`latest.json`, cache, nhật ký) không chiếm đĩa. MinIO chỉ bật versioning theo bucket, nên luật vòng đời là cách để giới hạn nó vào `raw/`.

**Tập test cố định theo thời gian.** Split point T1, T2 được tính **một lần** khi tạo phiên bản dữ liệu và lưu trong manifest (`ml_common.splits`):

| Tập | Gồm | Ai dùng |
| --- | --- | --- |
| Train | Đăng bán trước T1 | `train` (lấy mẫu được), mốc giám sát |
| Test | Đăng bán từ T1 đến trước T2 | `evaluate`, cổng 2, mốc chỉ số giám sát |
| Simulation | Đăng bán từ T2 | Chỉ agent |

T2 để lại khoảng 20.000 dòng cho simulation nhưng không quá 10% số dòng có ngày; T1 để lại khoảng 20% số dòng trước T2 cho test. Dòng không có ngày (khoảng 8%) vào train hoặc test theo một hash cố định của `property_id` (tỉ lệ 80/20), không bao giờ vào simulation. Split point là một luật **cho mỗi nguồn record**: record gốc xếp theo ngày đăng bán, feedback record theo **thời điểm dự đoán** chính xác tới giây (agent gửi cả lô trong vài phút, nên theo ngày thì không cắt được 80/20).

Vì split point không phụ thuộc số dòng train, mọi lần chạy trên cùng một phiên bản dữ liệu có **cùng một test set**. Phiên bản 3 chia ngẫu nhiên 80/20 *sau khi* đã cắt số dòng: lần chạy 200.000 dòng và lần chạy toàn bộ có hai test set khác nhau, và mô hình biết trước mặt bằng giá của chính những tháng nó bị chấm (temporal leakage). Phiên bản dữ liệu tạo trước phiên bản 4 chưa có manifest; `extract` tính và lưu cho nó ở lần chạy đầu, bằng đúng luật trên.

### 7.4. Working copy ID, data ID và cache

```
working_copy_id = sha256(dataset_version + ETag của raw object)[:16]
data_id         = sha256(working_copy_id + str(sample_rows) + seed)[:16]
```

- Dùng ETag thay vì băm nội dung: MinIO tự đổi ETag khi object đổi, nên không phải đọc 2 triệu dòng chỉ để biết dữ liệu có đổi hay không.
- Bản làm việc là **toàn bộ** dữ liệu thô, không phụ thuộc số dòng: mọi lần chạy trên cùng dữ liệu dùng chung. Phiên bản 3 lấy `sample_rows` **dòng đầu tệp** — không phải một mẫu ngẫu nhiên: tệp sắp theo ngày hay thành phố thì mô hình chỉ học một lát lệch mà không có lỗi nào báo ra.
- `sample_rows` và seed **bắt buộc** nằm trong data ID. Thiếu chúng, lần chạy 200.000 dòng sẽ dùng nhầm cache của lần chạy toàn bộ dòng.
- Data ID được gọi là `fingerprint` trong XCom và trong param MLflow, để mô hình đăng ký trước phiên bản 4 vẫn truy ngược về train set bằng đúng tên đó. Run mới log thêm param `data_id` cùng giá trị.

**Hai tầng cache:**

| Tầng | Vị trí | Dùng chung giữa hai bài toán? |
| --- | --- | --- |
| Bản làm việc (đọc raw — phần đắt nhất) | `extracted/{working_copy_id}/` | Có |
| Dữ liệu đã chuẩn bị | `processed/{data_id}/{task_type}/` | Không |

`task_type` phải nằm trong đường dẫn `processed/`: hai bài toán có target khác nhau và loại những dòng khác nhau vì thiếu target, nên dùng chung một đường dẫn thì bài toán này sẽ âm thầm dùng cache của bài toán kia.

`prepare_dataset_for_train` bỏ qua khi `train.parquet` và `test.parquet` đều đã có và `force_reprocess` là `false`. Dashboard có ô "Xử lý lại dữ liệu từ đầu" map sang `force_reprocess=true`.

### 7.5. MLflow, thuật toán và cổng `evaluate`

**MLflow.** Tracking server + Model Registry tự host trong container riêng; backend store là database `mlflow`, artifact store là MinIO. Hai registered model: `house_price_regressor` và `house_needs_renovation_classifier`.

**Phiên bản đang sử dụng được đánh dấu bằng alias `champion`**, không bằng model stage. MLflow 2.x đã deprecate stage và MLflow 3 bỏ hẳn. `evaluate` và serving nạp mô hình bằng `models:/{name}@champion`.

**Thứ được log mỗi lần huấn luyện (truy vết, NV-09):** tên và tham số estimator; `fingerprint` / `data_id`; `dataset_version`; `split_points`; `seed`; `sample_rows`; `git_commit` (được nướng vào `ml-base` lúc build, có hậu tố `-dirty` khi cây mã còn thay đổi chưa commit); `image_digest`; `decision_threshold` (classification); chỉ số `train_*`; nguyên `Pipeline` đã fit. `evaluate` ghi thêm vào cùng run: chỉ số `test_*` của mô hình mới, `champion_test_*` của champion trên cùng tập test, `group_metrics.json`, và tag `champion_overlap`. `register` ghi `model_card.json`.

**Thuật toán:**

| `task_type` | Estimator | Mặc định |
| --- | --- | --- |
| regression | `ridge`, `xgboost`, `random_forest` | `xgboost` |
| classification | `xgboost`, `svm`, `random_forest` | `xgboost` |

Mặc định của regression là `ridge` cho tới phiên bản 3; nhưng Ridge chỉ đạt R² 0,68 (48.000 dòng), dưới ngưỡng 0,75 của cổng 1, nên chạy với lựa chọn mặc định luôn "không đạt". Ridge được giữ làm baseline. Danh sách nằm ở `ESTIMATOR_NAMES`, mặc định ở `DEFAULT_ESTIMATOR` trong `estimators.py`; DAG giữ một bản sao mặc định và một test giữ hai bản bằng nhau. `svm` được bọc bằng `CalibratedClassifierCV` để có `predict_proba`.

**Tìm tham số (`tune_hyperparameters=true`).** Estimator được bọc bằng `GridSearchCV` trên lưới nhỏ ở `PARAM_GRIDS` (tối đa 8 tổ hợp mỗi thuật toán). Các fold là **fold theo thời gian** (`TimeOrderedSplit`): `train` xếp train set theo thời gian trước khi fit (dòng không có ngày đứng đầu và luôn ở phía học), và mỗi fold chỉ chấm trên dữ liệu nằm sau dữ liệu đã học. Cross-validation ngẫu nhiên ưu tiên những tổ hợp học thuộc mặt bằng giá từng tháng. Tiêu chí chọn là **đúng chỉ số mà cổng và giám sát dùng**: `neg_root_mean_squared_error` cho regression, `roc_auc` cho classification. Việc chuẩn hoá và one-hot trong `Pipeline` vẫn được fit một lần trên cả train set trước khi tìm tham số; phần rò rỉ nhỏ này có từ trước và được chấp nhận.

**Decision threshold (classification, CN-43).** Bước cuối của `Pipeline` classification là `ThresholdedClassifier` bọc quanh estimator (hoặc quanh `GridSearchCV`): fit mô hình cuối trên toàn train set; fit tạm một bản cùng tham số trên 80% đầu (theo thời gian) và lấy xác suất trên 20% cuối; giữ **threshold cao nhất mà vẫn đạt recall ≥ 70%**. Threshold nằm **trong mô hình**: serving gọi `predict` và nhận câu trả lời có/không đúng threshold mà không cần biết con số. Test set không bao giờ được dùng để chọn threshold. Lý do: chỉ khoảng 25% nhà cần cải tạo, nên ở threshold 0,5 một mô hình AUC 0,71 gần như không gắn cờ căn nào (F1 0,16).

**Hai cổng**, phải qua cả hai mới được promote:

| Cổng | Regression | Classification | Mục đích |
| --- | --- | --- | --- |
| 1. Ngưỡng sàn | R² ≥ 0,75 | AUC ≥ 0,55 | Chặn mô hình rác, kể cả mô hình đoán hằng số |
| 2. Tốt hơn champion **đủ nhiều** trên **cùng `test.parquet`** | RMSE thấp hơn ít nhất 1% | AUC cao hơn ít nhất 0,005 | Không thay champion bằng một mô hình kém hơn, cũng không thay vì một chênh lệch nhỏ chỉ là may rủi |

Chưa có champion thì chỉ áp cổng 1. Cổng và biên độ nằm ở `gates.py`.

**`evaluate` còn đo, chỉ để đọc:** chỉ số theo từng thành phố và từng loại bất động sản (nhóm có ít nhất 200 dòng trong test set; nhóm nhỏ hơn ghi "chưa đủ dữ liệu"); và số căn trong test set mà champion đã học. Con số này bằng 0 khi hai mô hình dùng cùng phiên bản dữ liệu hoặc phiên bản phản hồi dựng từ phiên bản của champion; khác 0 thì cổng 2 nghiêng về champion, và run được gắn tag cảnh báo.

**Vì sao classification dùng AUC, không dùng F1.** Ngưỡng F1 hỏng theo hai hướng ngược nhau, cả hai đều đo được trên dữ liệu thật: trên một target có 56% lớp dương, `DummyClassifier` luôn trả "có" đạt F1 0,72 — vượt ngưỡng 0,70 mà không nhìn dữ liệu; còn trên `needs_renovation` (25% lớp dương), một mô hình tốt với AUC 0,71 chỉ đạt F1 0,16 và sẽ bị chặn nhầm. AUC không phụ thuộc threshold hay tỉ lệ lớp, và mọi mô hình đoán hằng số đều cho đúng 0,5. F1, precision, recall và accuracy vẫn được tính **tại decision threshold của mô hình** để báo cáo.

**`evaluate` luôn exit 0**, kể cả khi mô hình không đạt: "không đạt" là một kết quả hợp lệ, được `branch_on_gates` đọc qua XCom, không phải lỗi của pipeline.

Các con số ngưỡng đặt khi test set còn chia ngẫu nhiên; chia theo thời gian gần như chắc chắn làm điểm thấp xuống, nên phải đo lại rồi đặt lại (mục 13).

### 7.6. Serving (`services/serving/`)

Image serving **không chứa mô hình**. Lúc khởi động nó nạp bản đang giữ alias `champion` của cả hai mô hình từ MLflow Registry vào bộ nhớ. Một container duy nhất phục vụ cả hai mô hình.

| Endpoint | Mô tả |
| --- | --- |
| `POST /predict/{task_type}` | `task_type` ∈ `regression` \| `classification`. Body là **một record thô**. Trả `request_id`, `prediction`, `model_name`, `model_version`; classification trả thêm `probability`, và `prediction` là câu trả lời tại decision threshold của mô hình. Ghi vào inference log. |
| `POST /feedback/{task_type}` | Body `{"outcomes": [{"request_id", "predicted_on", "actual"}, ...]}` — một **lô** kết quả thực tế. Ghi vào `ground-truth/`. |
| `POST /reload` | Nạp lại champion của cả hai mô hình và thay trong bộ nhớ, không khởi động lại. Task `deploy` gọi, và API layer gọi ngay sau khi người vận hành đổi champion hay xoá mô hình. Luôn trả 200 kèm trạng thái. |
| `POST /flush` | Ghi ngay bộ đệm inference log và chờ ghi xong. Trả `ok`, `written`, `buffered`, `error`; luôn 200. `monitoring_dag` gọi trước khi đo. |
| `GET /metrics` | Chỉ số vận hành theo định dạng Prometheus: số request theo endpoint, `task_type` và mã trạng thái; histogram thời gian phản hồi (từ đó ra trung vị, p95, p99); số bản ghi đang chờ ghi và đã bỏ; số lần ghi hỏng. Không tự đếm chính nó. |
| `GET /health` | Mô hình nào đang nạp, phiên bản bao nhiêu; `inference_log.buffered` và `inference_log.dropped` |

**Thiếu mô hình thì vẫn khởi động.** Mô hình nào nạp được thì phục vụ mô hình đó. `status` là `ok` khi nạp được ít nhất một mô hình, `degraded` khi không nạp được mô hình nào.

**Mã lỗi:**

| Mã | Khi nào |
| --- | --- |
| 503 | `task_type` hợp lệ nhưng chưa có champion (không phải lỗi hệ thống; alert tỉ lệ lỗi bỏ qua mã này) |
| 422 | `task_type` không hợp lệ, body không phải object, hoặc lô feedback rỗng |
| 500 | Mô hình đã nạp nhưng `predict` ném lỗi |

Record thiếu cột **không** phải lỗi 4xx: `Pipeline` tự bổ sung giá trị (mục 7.1).

**Inference log** — mỗi bản ghi gồm `request_id`, `timestamp`, `raw_input`, `prediction`, `probability` (classification), `model_name`, `model_version`. Ghi theo lô, với ba quy tắc theo thứ tự ưu tiên:

1. **`/predict` không bao giờ chậm hay lỗi vì chuyện ghi log.** Bản ghi vào bộ đệm trong bộ nhớ; việc ghi xuống MinIO diễn ra ở nền khi đủ **500 bản ghi** hoặc sau **30 giây**, hoặc ngay khi có yêu cầu `/flush`.
2. **Ghi hỏng thì giữ lại thử lần sau.**
3. **Bộ đệm có trần 5.000 bản ghi.** Vượt trần thì bỏ bản **cũ nhất** và tăng `dropped`, hiện ở `/health` và `/metrics` (có alert).

**Ground truth** — một lần gọi `/feedback` thành một tệp parquet. Mỗi phần tử mang `predicted_on`; serving phân mảnh `ground-truth/` theo **ngày đó**, không theo ngày nhận, để nó nằm cùng mảnh `dt=` với inference log tương ứng và ghép được. Ghi thẳng, không qua bộ đệm.

### 7.7. Agent mô phỏng thị trường (`services/agent/`)

Sinh lưu lượng thật cho serving. Chạy được bằng DAG `traffic_agent` (mục 6.3), bằng dòng lệnh (`python -m services.agent`), hoặc bằng service `agent` trong compose (profile `agent`, tắt mặc định).

Mỗi lần chạy:

1. Truy ngược champion của bài toán qua MLflow (`ml_common.lineage`) tới phiên bản dữ liệu và train set nó đã học. Nguồn là **simulation set** của phiên bản đó, **bỏ ra** mọi `property_id` có trong train set của champion. Không truy được (chưa có champion) thì dùng simulation set của `--dataset-version`, không bỏ gì. Phiên bản 3 lấy 20.000 dòng có `listing_date` mới nhất của cả tệp: khi mô hình học trên toàn bộ dữ liệu, phần lớn những căn đó đã nằm trong train set, và kịch bản `none` chỉ đo khả năng nhớ bài.
2. Rút ngẫu nhiên `count` dòng, biến đổi theo kịch bản.
3. Gọi `POST /predict/{task_type}` cho từng dòng.
4. Gọi `POST /feedback/{task_type}` một lần với kết quả thực tế của các dòng đó, mỗi phần tử kèm `predicted_on`. Mặc định gửi cho 100% request (`--feedback-ratio`).

Dự đoán và kết quả thực tế là **hai lời gọi tách rời**, đúng như trong thực tế: lúc hỏi giá chưa ai biết căn nhà bán được bao nhiêu.

**Năm kịch bản** (bắt buộc phải có):

| Kịch bản | Biến đổi đầu vào | Kết quả thực tế gửi về | Câu hỏi cần kiểm chứng |
| --- | --- | --- | --- |
| `none` | Không | Thật | Khi dữ liệu không đổi, hệ thống có báo động nhầm không? |
| `price_inflation` | `list_price` × 1,2 | Thật (không đổi) | Mô hình giá bán (không dùng `list_price`): có báo động nhầm không? Mô hình cải tạo (có dùng): có phát hiện data drift không? |
| `market_rally` | `list_price` × 1,2 | `sale_price` × 1,2 | Đầu vào không đổi nhưng giá thật tăng: có phát hiện performance drift không? |
| `market_shift` | Dồn `city` về một, hai thành phố | Thật | Có phát hiện data drift không? |
| `new_segment` | `property_type` giá trị chưa từng thấy | Thật | Serving có lỗi với giá trị lạ không? (Data quality của input nay cũng báo giá trị chưa từng gặp.) |

**Kết quả đo với mô hình regression (20/09/2026, cách chia và nguồn của phiên bản 3 — phải đo lại):**

| Kịch bản | Feature | Prediction | Performance | Kết luận |
| --- | --- | --- | --- | --- |
| `none` | `ok` | `ok` | `ok` | Không báo động nhầm |
| `price_inflation` | `ok` | `ok` | `ok` | Giống hệt `none`. `list_price` không phải feature của regression (mục 5). |
| `market_rally` | `ok` | `ok` | **`high`** (RMSE × 2,24) | **Hiệu năng sụp trong khi feature drift bằng không.** Bằng chứng mạnh nhất cho việc báo cáo ba loại trôi tách riêng. |
| `market_shift` | `warning` | `high` | `high` | Kịch bản duy nhất thật sự thử được feature drift của regression, vì `city` là một feature |
| `new_segment` | `warning` | `ok` | `warning` | Serving không trả HTTP 500 — điều kiện chính của kịch bản này |

Chưa có số đo cho mô hình cải tạo.

### 7.8. Giám sát (`stages/monitor/`)

**Chia việc (基本設計書 7.2).** Evidently **tính** mọi con số của bốn mục: kiểm định trôi từng cột, chỉ số hiệu năng, số giá trị thiếu, số giá trị ngoài danh sách đã biết. `ml_common.evidently_adapter` đọc kết quả của Evidently thành cấu trúc số cố định — là chỗ **duy nhất** biết định dạng kết quả của Evidently, không import Evidently, và được test trên kết quả thật đã lưu của Evidently 0.7.23 (`common/tests/fixtures/evidently_0_7/`). `ml_common.drift` **quyết định** mức. Không ngưỡng nào nằm ở stage hay ở Evidently: một bản ngưỡng duy nhất, test rẻ trên máy không có Evidently.

**Mốc so sánh gắn với phiên bản champion**, không gắn với một bộ dữ liệu cố định:

| Mốc | Nội dung | Nguồn |
| --- | --- | --- |
| Mẫu tập huấn luyện | Tối đa `MONITOR_REFERENCE_ROWS` (mặc định 10.000) dòng, seed cố định 42 | Truy ngược: model version → run → data ID → `processed/{data_id}/{task_type}/train.parquet` |
| Phân bố prediction lúc huấn luyện | Prediction của chính champion chạy lại trên mẫu ở trên | Tính tại thời điểm giám sát |
| Chỉ số trên tập test | `test_*` do `evaluate` ghi cho champion | MLflow |
| Mẫu tập huấn luyện sau làm sạch; mọi giá trị phân loại của **toàn bộ** train set | Qua ba bước làm sạch của chính `Pipeline` | Tính tại thời điểm giám sát; mốc của data quality |

**Vì sao mốc hiệu năng là chỉ số trên tập test, không phải trên tập huấn luyện.** Tập test là mốc duy nhất đo trên dữ liệu mô hình chưa thấy — đúng bản chất của lưu lượng thực tế. Đo ngày 22/09/2026: champion xgboost có RMSE 14.321 trên tập train nhưng 152.620 trên tập test; lưu lượng thực tế ở 203.809 cho tỉ lệ 14,2 lần (`high`) nếu so với train, nhưng 1,33 lần (`warning`) nếu so với test.

**`profile.json`** (sinh ở `register`) chứa với mỗi cột số: tỉ lệ thiếu, mean, std, min, max, phân vị 25/50/75, histogram 20 khoảng; với mỗi cột phân loại: tỉ lệ thiếu, số giá trị khác nhau, tỉ lệ từng giá trị. Evidently chỉ so hai DataFrame thật, nên `profile.json` **không** dùng để tính trôi.

**Cửa sổ:** `MONITOR_WINDOW_HOURS`, mặc định 24 giờ gần nhất. Dưới **50 dự đoán** trong cửa sổ thì cả bốn mục là `insufficient_data` và Evidently không chạy.

**Bốn mục** — Dashboard gọi ba loại trôi là Data / Prediction / Performance drift; khoá trong JSON là `feature` / `prediction` / `performance`, và mục thứ tư là `input_quality`:

| Mục | So cái gì | Evidently tính | Khi nào có |
| --- | --- | --- | --- |
| `feature` | Feature giải mã từ `raw_input` với mẫu tập huấn luyện, cả hai đã làm sạch | `DataDriftPreset` trên các cột feature: tỉ lệ cột trôi, mức lệch và ngưỡng từng cột | Ngay |
| `prediction` | Cột `prediction` trong log với phân bố prediction lúc huấn luyện | `DataDriftPreset` trên một cột | Ngay |
| `performance` | Prediction với kết quả thực tế, ghép qua `request_id` | RMSE/MAE/R²; hoặc AUC, và F1/precision/recall/accuracy **tại decision threshold của champion** (`probas_threshold`) | Chỉ khi có ground truth |
| `input_quality` | Lưu lượng sau làm sạch với mẫu tập huấn luyện sau làm sạch | `MissingValueCount` từng cột; `OutListValueCount` từng cột phân loại với danh sách giá trị của toàn bộ train set | Ngay |

Evidently chỉ trả kết quả của phía "current", nên mục data quality chạy hai lần: một lần trên lưu lượng, một lần trên mốc. Chỉ số hiệu năng Evidently tính **trùng khớp** với chỉ số `evaluate` tính trên cùng dữ liệu — một test kiểm tra điều này, vì chúng được chia cho nhau.

**Luật xếp mức** (ở `drift.py`):

| Mục | `ok` | `warning` | `high` |
| --- | --- | --- | --- |
| `feature` — luật tỉ lệ | Tỉ lệ cột trôi < 0,3 | 0,3 – 0,5 | > 0,5 |
| `feature` — luật độ lớn | Tổng (`value − threshold`) trên mọi cột < 0 | ≥ 0 | — |
| `prediction` | Không trôi | — | Có trôi |
| `performance` — regression | RMSE hiện tại / RMSE test < 1,2 | 1,2 – 1,5 | > 1,5 |
| `performance` — classification | AUC giảm < 0,05 | 0,05 – 0,10 | > 0,10 |
| `input_quality` (mỗi cột, lấy cột nặng nhất) | Tỉ lệ thiếu tăng < 5 điểm % và giá trị chưa từng gặp < 5% | 5 – 20 | > 20 |

`feature` lấy mức nặng hơn giữa hai luật. Luật tỉ lệ một mình mù trước trôi dồn vào một, hai cột: ở `market_shift`, `city` lệch Jensen-Shannon 0,78 so với ngưỡng 0,1, nhưng chỉ 2/22 cột vượt ngưỡng — đúng bằng tỉ lệ đo được ở `none`. Luật độ lớn bắt được trường hợp đó.

Data quality dùng dữ liệu **sau** các bước làm sạch của chính mô hình: Evidently trên dữ liệu thô sẽ coi `"$450,000"` hay `"NEW YORK"` là hợp lệ. Nó bắt được loại lỗi mà trôi không bắt: bên gửi đổi định dạng ngày, cả cột ngày âm thầm thành giá trị thiếu, mô hình vẫn trả lời vì tự điền giá trị.

**`insufficient_data`.** Khi số dòng ghép được với ground truth dưới `MONITOR_MIN_GROUND_TRUTH` (50), `performance` là `insufficient_data`, **không bao giờ** là `ok` — kể cả khi Evidently vẫn trả về một con số. Champion không có `test_*` cũng cho `insufficient_data`.

**Mức tổng hợp** (`severity`) là mức nặng nhất trong bốn mục, **bỏ qua** `insufficient_data`; nếu tất cả đều `insufficient_data` thì mức tổng hợp là `insufficient_data`.

**Đầu ra mỗi lần chạy, cho mỗi mô hình:**

| Object | Nội dung |
| --- | --- |
| `reports/{model}/{run_id}/summary.json` | `model_name`, `model_version`, `task_type`, `run_id`, `computed_at`, `window_hours`, `severity`, `parts` (bốn mục), `input_quality` (mức và các cột vi phạm), `n_predictions`, `n_ground_truth`, `current_metrics`, `reference_metrics`, `reference_source`, `decision_threshold`, `group_metrics` (`current`: theo thành phố và loại nhà trên lưu lượng, nhóm ≥ 50 cặp; `reference`: của champion trên tập test), `flush` (kết quả ghi log trước khi đo), `consecutive_warnings` (số lần liên tiếp ở `warning` của từng mục, bắt đầu lại khi đổi champion), `report_key` |
| `reports/{model}/latest.json` | Bản sao của summary mới nhất, ghi đè mỗi lần |
| `reports/{model}/{run_id}/evidently.html` | Báo cáo chi tiết data drift của Evidently, khoảng 5 MB |

Mọi nơi đọc summary phải chịu được việc thiếu trường: summary trước 22/09/2026 không có `reference_metrics`/`reference_source`; summary trước phiên bản 4 không có `input_quality`, `group_metrics`, `flush`, `consecutive_warnings`, `decision_threshold`.

**Sau khi ghi summary**, stage push lên Pushgateway: mức của từng mục (`ok` 0, `warning` 1, `high` 2, `insufficient_data` −1 — để nó không bao giờ khớp một alert rule), số lần cảnh báo liên tiếp, tỉ lệ RMSE hoặc mức giảm AUC, số dự đoán và số cặp ghép được (mục 7.12). Không có `PUSHGATEWAY_URL` hay push lỗi thì chỉ ghi log, không làm hỏng lần giám sát.

**Evidently không vào `ml-base`.** Nó kéo theo khoảng 500 MB thư viện vẽ biểu đồ; `ml-monitor` là `FROM ml-base` rồi cài thêm Evidently. Lưu ý thứ tự tham số của Evidently 0.7: `report.run(current, reference)` — gọi ngược vẫn chạy và ra báo cáo, chỉ là đảo vai hai tập, không có exception nào báo.

### 7.9. Cấu hình & bí mật

- `.env.example` được commit; `.env` thật thì gitignore.
- Biến chính: `MINIO_ENDPOINT`, `MINIO_ENDPOINT_INTERNAL`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `ML_BUCKET`, `POSTGRES_*`, `MLFLOW_TRACKING_URI`, `AIRFLOW_ADMIN_USER`, `AIRFLOW_ADMIN_PASSWORD`, `SERVING_URL`, `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`, `ALERT_WEBHOOK_URL` (kênh nhận alert; để trống thì alert chỉ hiện trên Grafana). `PUSHGATEWAY_URL` do compose đặt cho Airflow.
- Docker Compose đưa các biến này vào môi trường của scheduler; DAG chuyển tiếp chúng vào từng container stage qua tham số `environment` của `DockerOperator`. Airflow Connections **không** được dùng. Không thông tin xác thực nào được viết cứng trong DAG hay trong code.
- Giới hạn số dòng train khi phát triển đặt **theo từng lần chạy** qua `sample_rows` (mục 6.1); biến `SAMPLE_ROWS` trong `.env` không còn tác dụng.

### 7.10. Image dùng chung

`ml-base` (`stages/base/Dockerfile`) là `python:3.12-slim` cộng `common/` đã cài (kéo theo pandas, numpy, scikit-learn, xgboost, pyarrow, boto3) và MLflow client. Nó mang biến `GIT_COMMIT` — commit mà image được build từ, do `scripts/build_base_image.ps1` truyền vào (`-dirty` khi cây mã còn thay đổi chưa commit). Mọi image khác `FROM ml-base:latest`:

| Nhóm | Image |
| --- | --- |
| Stage | `extract`, `validate`, `prepare_dataset_for_train`, `train`, `evaluate`, `register`, `ml-monitor` (+ Evidently), `ml-build-feedback` |
| Service | `ml-serving` (+ `prometheus-client`), `ml-agent`, `ml-api` |

Không có image nền chung thì mỗi image tự cài lại thư viện: build rất lâu và phiên bản dễ lệch — mà phiên bản lệch giữa lúc huấn luyện và lúc serve là loại bug khó tìm nhất. Mô hình pickle bởi scikit-learn chỉ nạp lại được bởi cùng minor version Python và cùng version scikit-learn, nên **huấn luyện và serve đều diễn ra trong container** (Python 3.12). Ví dụ đã gặp: thêm xgboost vào `common/` thì `ml-serving` cũng phải build lại, nếu không nó không unpickle được mô hình xgboost.

**Khi `common/` thay đổi phải build lại cả năm tầng, theo thứ tự:** `ml-base` → tám stage image → `ml-serving` → `ml-agent` → `ml-api`. Chỉ build `ml-base` là chưa đủ: các image dựa trên nó vẫn giữ bản `ml_common` cũ bên trong cho tới khi được build lại.

### 7.11. Kiểm thử và CI

- Test nằm ở `common/tests/` và `services/*/tests/`, chạy bằng `pytest`. Đo ngày 26/09/2026: 804 test pass (Python 3.11 trong môi trường phát triển của giai đoạn 6; CI chạy Python 3.12). Trong container `ml-base` chỉ có `common/`, nên test cần `stages/`, `dags/`, `docker/` hoặc `services/` được skip có chủ ý ở đó; test của `services/api/` chỉ chạy ngoài container.
- Mỗi loại dirty trong `house_pricing_README.md` có ít nhất một test khẳng định xử lý đúng.
- Những bảo đảm kiến trúc có test riêng: `Pipeline` không bao giờ bỏ dòng và dự đoán được cho đúng một record (kể cả với bộ bọc decision threshold); mô hình nhận dữ liệu thô; cột leakage không ảnh hưởng dự đoán; cổng chặn được mô hình đoán hằng số và mô hình chỉ hơn trong phạm vi biên độ; luật xếp mức giám sát, kể cả `insufficient_data`.
- Chia theo thời gian: mọi dòng có ngày của test set đăng sau mọi dòng có ngày của train set; không căn nào ở cả hai tập; test set không đổi khi đổi số dòng train; fold tuning chỉ chấm dữ liệu sau dữ liệu đã học; threshold đạt recall mục tiêu và sống sót qua pickle.
- Adapter Evidently được test trên kết quả thật đã lưu; chỉ số hiệu năng Evidently tính trùng với `evaluate`; stage `monitor` chạy trọn một lần với Evidently thật, MLflow file store và S3 giả lập (moto).
- Pipeline dữ liệu phản hồi, deploy có smoke test và rollback, đẩy metric, cấu hình alert đều có test.
- **Round-trip:** cùng một record thô qua `Pipeline` vừa fit và qua `Pipeline` nạp lại từ MLflow phải ra cùng kết quả (`scripts/smoke_round_trip.py`).
- Mỗi giai đoạn từ 1 tới 5a có một script kiểm tra trên hệ thống thật (`scripts/verify_*.ps1`). Giai đoạn 6 **chưa** có script và **chưa** chạy trên hệ thống thật (mục 13). Dashboard được kiểm tra bằng trình duyệt ở chế độ minh hoạ.
- Lint: ruff, cấu hình ở `ruff.toml` tại gốc repo, rule `E`, `F`, `I`, `UP`, `B`, `D`.

**CI** (`.github/workflows/ci.yml`, chạy mỗi lần push và pull request):

| Bước | Nội dung |
| --- | --- |
| 1. Lint | `ruff check .` |
| 2. Test | Toàn bộ `pytest common/ services/`, Python 3.12, có Evidently |
| 3. Ranh giới | `common/tests/test_boundaries.py`: Dashboard không gọi thẳng Airflow/MLflow/MinIO; `features`, `cleaning`, `estimators` và serving không import module theo dòng; serving không import `cleaning`; chỉ `storage.py` dựng key object storage |
| 4. Build image | `ml-base` (kèm commit) rồi mọi image dựa trên nó, đúng thứ tự |
| 5. Cấu hình alert | `promtool` kiểm `prometheus.yml` và mọi câu PromQL của alert rule và dashboard (`scripts/check_alert_config.py`); test kiểm alert rule khớp datasource, metric tồn tại trong code, `$` đã escape |

Ngoài ra một job build Dashboard (`npm ci && npm run build`). Việc **cấm merge vào main khi CI đỏ** là cài đặt branch protection trên GitHub (Settings → Branches), không nằm trong repo.

### 7.12. Metric theo thời gian và alert (`docker/prometheus/`, `docker/grafana/`)

Báo cáo giám sát trả lời "chuyện gì đang xảy ra" khi có người mở ra xem; phần này trả lời "làm sao người vận hành biết mà mở ra xem" (NV-10).

| Nguồn | Metric | Cách đưa vào |
| --- | --- | --- |
| Stage `monitor` | `ml_monitoring_level{model_name, model_version, part}`, `ml_monitoring_consecutive_warnings`, `ml_monitoring_rmse_ratio`, `ml_monitoring_auc_drop`, `ml_monitoring_predictions`, `ml_monitoring_ground_truth_pairs` | Push lên Pushgateway (job `monitoring`, nhóm theo `model_name`) sau khi ghi summary |
| `ml_pipeline`, `feedback_data_pipeline` | `ml_pipeline_last_run_status{pipeline, task_type, status}` (1 cho kết quả vừa xảy ra: `success`, `blocked`, `failed`, `smoke_test_failed`), `ml_pipeline_last_run_finished_seconds` | Callback ở cấp DAG push lên Pushgateway |
| Serving | `serving_requests_total`, `serving_request_latency_seconds`, `serving_inference_log_buffered`, `serving_inference_log_dropped`, `serving_inference_log_flush_failures_total` | Prometheus scrape `/metrics` mỗi 30 giây |

Các bước batch kết thúc trước khi Prometheus kịp scrape, nên phải chủ động push; serving chạy liên tục nên để Prometheus scrape. Pushgateway lưu xuống đĩa, để mức cuối cùng của mỗi mô hình còn sau khi khởi động lại và một vấn đề đang diễn ra vẫn tiếp tục cảnh báo. Prometheus giữ 15 ngày.

**Alert rule** (`docker/grafana/provisioning/alerting/rules.yml`, lưu cùng mã nguồn, CI kiểm):

| Rule | Điều kiện |
| --- | --- |
| Mức Cao | `ml_monitoring_level` = 2 |
| Cảnh báo kéo dài | `ml_monitoring_consecutive_warnings` ≥ 3 |
| Pipeline thất bại | `ml_pipeline_last_run_status{status=~"failed\|smoke_test_failed"}` = 1 |
| Serving lỗi | Tỉ lệ request 5xx (trừ 503 "chưa có champion") trên 1% trong 5 phút |
| Mất log | `serving_inference_log_dropped` tăng trong 5 phút |

Số lần liên tiếp được tính ở `monitor` (`drift.consecutive_warnings`), không ở Grafana: ngưỡng và luật thuộc về `ml_common`, Grafana chỉ so một con số với một giá trị cố định. `insufficient_data` được push là −1 nên không bao giờ khớp rule nào; không có dữ liệu (`noDataState: OK`) cũng không phải alert.

**Gửi đi:** một contact point webhook tên `operator`, URL lấy từ `ALERT_WEBHOOK_URL` (Slack, Discord hoặc bất kỳ URL nhận JSON). Chính sách thông báo nhắc lại một vấn đề đang diễn ra **tối đa mỗi 24 giờ**. Không cấu hình kênh thì webhook trỏ vào một cổng không ai nghe: alert vẫn hiện trên Grafana, không gửi đi đâu. Nội dung alert: mô hình và version, loại vấn đề, mức, đường dẫn tới màn hình liên quan, mục tương ứng trong 運用手順書 (tài liệu này chưa viết). Grafana cũng có một dashboard `MLOps` (mức giám sát, request theo mã trạng thái, p50/p95/p99, bộ đệm log, tỉ lệ hiệu năng).

Prometheus (`127.0.0.1:9090`), Pushgateway (`9091`) và Grafana (`3000`, đăng nhập theo `.env`) chỉ mở trên máy cục bộ, có giới hạn RAM (512 MB / 128 MB / 512 MB). Dashboard của hệ thống không gọi vào Grafana; Grafana là công cụ người vận hành mở riêng, giống Airflow UI.

---

## 8. Dashboard

Dashboard là **thành phần chính thức của hệ thống**, không phải công cụ minh hoạ: đây là nơi chạy và theo dõi pipeline, tải dữ liệu, quản lý mô hình, mô phỏng lưu lượng và theo dõi trôi.

### 8.1. Các màn hình

| Màn hình | Chức năng |
| --- | --- |
| Tổng quan | Form khởi chạy `ml_pipeline`: `task_type`, thuật toán (danh sách từ `/api/estimators`, bỏ trống là mặc định), tìm tham số, số dòng train lấy ngẫu nhiên hoặc toàn bộ train set, xử lý lại dữ liệu từ đầu, `dataset_version`. Bảng các lần chạy gần đây; dải chín task của lần chạy đang chọn. |
| Dữ liệu | Tải CSV (tối đa 500 MiB; tên phiên bản đã có bị **từ chối**, báo ngay khi bấm tải lên; báo split point sau khi tạo); xem tối đa 200 dòng thô và thống kê từng cột; **tạo phiên bản dữ liệu từ lưu lượng thực tế**: chọn bài toán, phiên bản nguồn, khoảng thời gian, tên mới; đếm trước số cặp dự đoán / ground truth, dưới 500 thì khoá nút và nói vì sao; xác nhận; theo dõi tiến trình |
| Models | Mỗi mô hình một khối; bảng phiên bản với **cột chỉ số sinh từ dữ liệu thật** (RMSE/MAE/R² cho regression, AUC/F1/precision/recall/accuracy cho classification); **model card** của từng phiên bản; đổi champion (báo rõ serving đã chuyển theo hay chưa); xoá một phiên bản (bị chặn nếu là champion); xoá cả mô hình |
| Drift | Chọn mô hình; khối mô phỏng lưu lượng (kịch bản, số request, tiến trình hai chặng, tự tải lại khi xong); **ba ô trôi riêng** (Data / Prediction / Performance drift) với bốn trạng thái và số lần cảnh báo liên tiếp; **ô thứ tư data quality của input**, tách khỏi ba ô trôi, liệt kê cột vi phạm; cảnh báo khi flush trước lúc đo thất bại; bảng so chỉ số trên tập test với trên lưu lượng thực tế; bảng chỉ số theo nhóm cạnh cùng nhóm trên tập test; biểu đồ diễn biến; báo cáo Evidently nhúng khi bấm xem; khi có mức `high`: gợi ý tạo dữ liệu phản hồi trước, rồi nút "Retrain" |

Màn "Stages & Logs" và endpoint đọc log đã bị bỏ: log chi tiết của từng task xem trên Airflow UI. Feature Store không có ở giai đoạn 1 (mục 11).

**Quy tắc chung cho mọi màn hình:**

- **`insufficient_data` phải trông khác `ok`** ở ba trục cùng lúc: nền xám gạch chéo, viền nét đứt, chữ "chưa đủ dữ liệu". Không bao giờ dùng màu xanh hay dấu tích cho nó.
- **Ba loại trôi hiện riêng**, không gộp thành một badge: ở `market_rally`, feature `ok` trong khi performance `high`, nên một badge tổng hợp màu xanh sẽ nói dối.
- Phân biệt ba tình huống: **chưa có dữ liệu** (không phải lỗi), **không tìm thấy**, **hệ thống đang hỏng**.
- Mọi thao tác ghi thật (khởi chạy huấn luyện, đổi champion, xoá, tạo phiên bản dữ liệu từ lưu lượng) đều qua hộp xác nhận. Sau thao tác, luôn tải lại dữ liệu thật thay vì tự cập nhật trước.
- Thanh trạng thái đọc `/api/health` không nhanh hơn mỗi 10 giây và không gửi yêu cầu mới khi yêu cầu trước chưa trả lời.
- Giao diện **không tự đặt ngưỡng nào**: biểu đồ và dòng kết luận chỉ hiển thị mức do stage `monitor` tính. Chép ngưỡng sang frontend là tạo một bản thứ hai sẽ lệch.

### 8.2. Vì sao cần API layer

Gọi thẳng Airflow / MLflow / MinIO từ trình duyệt không dùng được: thông tin xác thực sẽ lộ ở frontend, mỗi service phải mở quyền truy cập từ trình duyệt riêng, và mỗi lần thay backend (Airflow → MWAA, MLflow → SageMaker) là phải sửa frontend. API layer che toàn bộ những thứ đó — khi chuyển lên AWS chỉ sửa `services/api/`, frontend giữ nguyên.

Ranh giới này được CI kiểm tra (`common/tests/test_boundaries.py`): không địa chỉ Airflow, MLflow, MinIO, Prometheus hay Grafana nào trong `dashboard/src`.

Mọi collaborator của API được inject (`create_app(airflow, registry, reports, probes, storage, serving)`). Client nào không dựng được vì thiếu biến môi trường thì là `None`: app vẫn khởi động và `/api/health` báo dependency đó `down`, thay vì crash-loop.

### 8.3. API contract (Dashboard ↔ `services/api/`)

Mọi đường dẫn có tiền tố `/api`. Lỗi trả `{"detail": ...}` theo chuẩn FastAPI (riêng lỗi 500 là văn bản thuần).

| Method | Endpoint | Mô tả | Gọi xuống |
| --- | --- | --- | --- |
| `POST` | `/pipeline/run` | Khởi chạy `ml_pipeline` (body dưới). Trả ngay `{run_id, dag_id, state}`, không chờ chạy xong. | Airflow |
| `GET` | `/pipeline/runs` | Các lần chạy gần đây và trạng thái | Airflow |
| `GET` | `/pipeline/runs/{run_id}` | Trạng thái từng task của một lần chạy | Airflow |
| `GET` | `/estimators` | Thuật toán theo `task_type` | `ml_common.estimators` |
| `POST` | `/data/upload` | Tải CSV (multipart), lưu thành `raw/{dataset_version}/` kèm manifest; trả thêm `split_points`. Tên phiên bản khớp `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`; **409** nếu phiên bản đã có (kiểm cả trước khi chép body); 422 nếu không dòng nào có `listing_date` đọc được; trần 500 MiB (413 khi vượt). | MinIO |
| `GET` | `/data/{dataset_version}/preview` | Tối đa 200 dòng thô và thống kê cột trên 200.000 dòng đầu; `total_rows` là của cả tệp | MinIO |
| `GET` | `/models` | Registered model, phiên bản, chỉ số test, `is_champion` | MLflow |
| `POST` | `/models/{name}/{version}/promote` | Chuyển alias `champion` sang phiên bản này, rồi yêu cầu serving `/reload`; trả thêm `serving: {switched, version, error}` | MLflow, serving |
| `GET` | `/models/{name}/{version}/card` | Model card của phiên bản; 404 nếu phiên bản không có (đăng ký trước khi có model card) | MLflow |
| `DELETE` | `/models/{name}/{version}` | Xoá một phiên bản; **409** nếu đó là champion | MLflow |
| `DELETE` | `/models/{name}` | Xoá cả mô hình, kể cả champion, rồi yêu cầu serving `/reload`. **Không hoàn tác được.** | MLflow, serving |
| `GET` | `/feedback/preview` | `?task_type=&period_start=&period_end=` → số căn nhà có dự đoán và ground truth trong khoảng, tối thiểu 500 | MinIO |
| `POST` | `/feedback/run` | Khởi chạy `feedback_data_pipeline` với `{task_type, new_version, source_version?, period_start?, period_end?}`; 409 nếu tên đã có | MinIO, Airflow |
| `GET` | `/feedback/status` | Trạng thái lần tạo gần nhất, kèm task | Airflow |
| `GET` | `/scenarios` | Năm kịch bản của agent | `services.agent.scenarios` |
| `POST` | `/simulate` | Khởi chạy `traffic_agent` với `{scenario, task_type, count}` | Airflow |
| `GET` | `/simulate/status` | Trạng thái lần mô phỏng gần nhất, kèm trạng thái hai task | Airflow |
| `POST` | `/drift/run` | Khởi chạy `monitoring_dag` trực tiếp | Airflow |
| `GET` | `/drift/latest` | `?model_name=` → nguyên `latest.json`; 404 nếu chưa từng giám sát (Dashboard coi là "chưa có dữ liệu") | MinIO |
| `GET` | `/drift/history` | `?model_name=&limit=` → các summary, mới nhất trước | MinIO |
| `GET` | `/drift/report` | `?model_name=&run_id=` → tệp HTML của Evidently. Dashboard nhúng trong khung `sandbox="allow-scripts"`, chỉ tải khi bấm xem. | MinIO |
| `GET` | `/health` | Trạng thái `airflow`, `mlflow`, `minio`, `serving`, `postgres`; luôn HTTP 200, `status` là `ok` hoặc `degraded` | Tất cả |

**Body của `POST /pipeline/run`:**

| Trường | Luật |
| --- | --- |
| `task_type` | Bắt buộc, `regression` hoặc `classification` |
| `estimator_name` | Tuỳ chọn; phải thuộc danh sách của `task_type`, nếu không trả 422 ngay (thay vì để `train` chết sau vài phút) |
| `tune_hyperparameters` | Mặc định `false` |
| `sample_rows` | Số dòng train lấy ngẫu nhiên. Số nguyên > 0, hoặc vắng/`null` = toàn bộ train set. `0` và số âm bị từ chối bằng 422 — không được hiểu thầm thành "tất cả", nếu không một máy chỉ đủ RAM cho lần chạy nhỏ sẽ nhận một lần chạy 2 triệu dòng. |
| `force_reprocess` | Mặc định `false` |
| `dataset_version` | Mặc định `v1`. **Không được kiểm**: phiên bản không tồn tại vẫn được xếp hàng và chỉ hỏng ở `extract`. |

---

## 9. Cấu trúc thư mục project

```
.
├── common/                          # package ml_common — mục 7.1
│   ├── pyproject.toml
│   ├── ml_common/
│   └── tests/
├── dags/
│   ├── ml_pipeline_dag.py           # huấn luyện & đưa vào sử dụng — mục 6.1
│   ├── monitoring_dag.py            # giám sát — mục 6.2
│   ├── traffic_agent_dag.py         # mô phỏng lưu lượng rồi giám sát — mục 6.3
│   ├── feedback_data_dag.py         # dữ liệu phản hồi — mục 6.4
│   ├── deploy_check.py              # smoke test + rollback (chỉ thư viện chuẩn)
│   └── run_outcome.py               # báo kết quả lần chạy lên Pushgateway
├── stages/
│   ├── base/                        # image ml-base — mục 7.10
│   ├── extract/
│   ├── validate/
│   ├── prepare_dataset_for_train/
│   ├── train/
│   ├── evaluate/
│   ├── register/                    # alias champion + profile.json + model card
│   ├── monitor/                     # Evidently
│   └── build_feedback/              # dữ liệu phản hồi
├── services/
│   ├── serving/                     # /predict /feedback /reload /flush /metrics /health
│   ├── api/                         # backend của Dashboard
│   └── agent/                       # agent mô phỏng thị trường
├── dashboard/                       # React + Tailwind (Vite)
├── docker/                          # cấu hình riêng của Postgres, MLflow, Prometheus, Grafana
├── .github/workflows/ci.yml         # CI — mục 7.11
├── scripts/                         # build image, nạp dữ liệu, smoke test, verify_*
├── docs/
│   ├── 01-requirements-definition.md
│   ├── 02-basic-design.md
│   └── superpowers/                 # spec và plan của từng giai đoạn
├── docker-compose.yml
├── ruff.toml
├── .env.example
└── README.md
```

`stages/` không có `deploy/`: bước đó chỉ là vài lời gọi HTTP (reload, smoke test, và khi cần là rollback qua REST của MLflow), nên dùng `PythonOperator` với `dags/deploy_check.py`; đóng gói cả một image để gửi vài request là thừa. `register` vẫn có container riêng vì nó phải tính `profile.json` trên toàn bộ tập huấn luyện.

---

## 10. Lộ trình triển khai

| Bước | Nội dung | Trạng thái |
| --- | --- | --- |
| 1 | Docker Compose: Airflow + PostgreSQL (2 DB) + MinIO + MLflow | Xong (giai đoạn 1) |
| 2 | `common/` với test cho cả 8 loại dirty. **Làm trước mọi stage** — các stage chỉ là lớp vỏ mỏng quanh package này. | Xong (giai đoạn 1) |
| 3 | `ml-base` + `extract`, `validate`, `prepare_dataset_for_train` (có cache) | Xong (giai đoạn 2) |
| 4 | `train`, log `Pipeline` vào MLflow; kiểm tra mô hình nạp lại và dự đoán từ record thô | Xong (giai đoạn 2) |
| 5 | `evaluate` (hai cổng) + `register` (alias champion + `profile.json`) | Xong (giai đoạn 2) |
| 6 | Serving: `/predict`, `/reload`, `/health`, inference log theo lô | Xong (giai đoạn 3) |
| 7 | Ghép DAG `ml_pipeline`, chạy trọn cho regression | Xong (giai đoạn 2–3) |
| 8 | Nhánh classification (`needs_renovation`) | Xong (giai đoạn 3) |
| 9 | Agent + năm kịch bản | Xong (giai đoạn 4) |
| 10 | `/feedback`, ground truth, `monitor` với Evidently, `monitoring_dag`. Kiểm chứng theo bảng đo ở mục 7.7. | Xong (giai đoạn 4) |
| 11 | API layer theo mục 8.3 | Xong (giai đoạn 5a) |
| 12 | Dashboard nối vào API layer | Xong (giai đoạn 5b) |
| 13 | Giai đoạn 6 — khớp 要件定義書 / 基本設計書 1.3: chia theo thời gian, không ghi đè dữ liệu, dữ liệu phản hồi, decision threshold, biên độ cổng 2, smoke test + rollback, reload sau thao tác tay, flush trước giám sát, data quality của input, chỉ số theo nhóm, model card, truy vết, Prometheus/Grafana/alert, CI | Xong về mã và test (26/09/2026); **chưa chạy trên hệ thống thật** (mục 13) |
| 14 | (Nâng cao) Tự huấn luyện lại khi trôi vượt ngưỡng, kèm thời gian chờ giữa hai lần | Chưa làm |
| 15 | **Chuyển lên AWS**: MinIO → S3 (sửa `storage.py`), Airflow → MWAA, serving → SageMaker Endpoint, inference log → Data Capture, Evidently → Model Monitor | Chưa làm |

Bước 2 đứng trước mọi stage là có chủ ý: nếu viết stage trước rồi mới tách ra `common/`, khả năng cao logic sẽ bị chép sang serving trước khi kịp tách.

---

## 11. Phạm vi bị cắt khỏi giai đoạn 1

**Feature Store (Feast).** Nó kéo theo một registry PostgreSQL riêng và một job materialization, trong khi pipeline xử lý theo lô này chưa có nhu cầu cung cấp feature theo thời gian thực. Xem xét lại khi pipeline chạy ổn; khi đó nó sẽ đứng giữa `prepare_dataset_for_train` và `train`, và map sang SageMaker Feature Store lúc chuyển lên AWS.

**Tự huấn luyện lại.** Hệ thống cảnh báo, con người quyết định (mục 6.2). Có thể làm ở bước 14 của lộ trình.

**Xem log trên Dashboard.** Đã có rồi bỏ; log xem trên Airflow UI.

**Liệt kê, xoá, đổi tên phiên bản dữ liệu.** API không có endpoint cho việc này; người vận hành nhập tên phiên bản bằng tay.

---

## 12. Thay đổi so với các phiên bản trước

### 12.1. So với phiên bản 1

| Hạng mục | v1 | Hiện tại |
| --- | --- | --- |
| Bài toán ML | Chưa chốt | Regression `sale_price` + classification `needs_renovation` |
| Cấu trúc DAG | 1 DAG 8 task | Ba DAG: `ml_pipeline`, `monitoring_dag`, `traffic_agent` |
| Lịch chạy | Chưa chốt | Không DAG nào chạy theo lịch; tất cả chạy theo yêu cầu |
| Preprocess | Chạy lại mỗi lần | Cache theo fingerprint, hai tầng |
| Logic làm sạch | Không nói rõ | Package `common/`, đóng gói vào mô hình qua sklearn `Pipeline` |
| `/predict` | Không định nghĩa input | Nhận record thô, mô hình tự làm sạch |
| Bước `deploy` | Build image + restart container | `POST /reload` vào serving |
| Trôi | "So data mới với baseline", không rõ nguồn | Inference log với mốc gắn phiên bản champion; ba loại trôi, bốn trạng thái |
| Ground truth | Không có | `POST /feedback/{task_type}` theo lô, ghép qua `request_id` |
| Baseline | Thư mục rỗng | Mẫu tập huấn luyện + chỉ số test + `profile.json` |
| Huấn luyện lại | Câu hỏi mở | Cảnh báo + nút bấm, không tự động |
| `evaluate` | Ngưỡng cố định | Ngưỡng sàn **và** phải hơn champion, trên tập test cố định |
| Định dạng dữ liệu | Không nói | Parquet |
| PostgreSQL | "Có thể tách DB" | Tách `airflow` / `mlflow` |
| Feature Store | Trong stack | Cắt khỏi giai đoạn 1 |
| CI/CD | "GitHub Actions (offline)" | `pre-commit` + `pytest` local; chưa có CI |
| API cho Dashboard | Liệt kê endpoint của Airflow | API layer riêng, 18 endpoint |

### 12.2. Thay đổi trong quá trình xây dựng (sau phiên bản 2)

Phiên bản 2 (17/09/2026) là thiết kế trước khi xây. Các quyết định dưới đây được đưa ra khi xây, phần lớn sau khi đo trên dữ liệu thật; chi tiết và số đo nằm trong spec của từng giai đoạn ở `docs/superpowers/specs/`.

| Hạng mục | Phiên bản 2 | Hiện tại | Lý do |
| --- | --- | --- | --- |
| Tên stage chuẩn bị dữ liệu | `preprocess` | `prepare_dataset_for_train` | Tên cũ gợi ý nó làm sạch dữ liệu — đúng việc nó không làm |
| Model Registry | Stage `Production` | Alias `champion` | MLflow deprecate stage |
| `dataset_version` mặc định | `"latest"` | `"v1"` | Giá trị được nối thẳng vào đường dẫn; không có cơ chế phân giải "latest" |
| Nơi tính fingerprint | `preprocess` | `extract`, gồm cả `sample_rows` | `validate` cũng cần fingerprint; `sample_rows` phải tách cache |
| Đường dẫn `processed/` | `processed/{fp}/` | `processed/{fp}/{task_type}/` | Hai bài toán có tập đã chuẩn bị khác nhau |
| Target regression | `log(sale_price)` | `sale_price` | Quy đổi ngược làm Ridge ra R² âm (mục 5) |
| Target classification | `sold_within_30_days` | `needs_renovation` | Target cũ chỉ đạt AUC 0,58 sau khi loại leakage (mục 5) |
| Cổng classification | F1 ≥ 0,70 | AUC ≥ 0,55, so champion bằng AUC | F1 cho mô hình đoán hằng số lọt và chặn nhầm mô hình tốt (mục 7.5) |
| Serving thiếu mô hình | Không nói | Khởi động `degraded`, `/predict` trả 503 | Tránh vòng khởi động lại |
| Bộ đệm inference log | 500 bản ghi / 30 giây | Thêm trần 5.000 và đếm số bỏ | Spec không nói ghi hỏng thì làm gì |
| Inference log | Không có xác suất | Thêm `probability` | Performance drift của classification chấm bằng AUC |
| `/feedback` | `{request_id, actual_value}` | Lô `outcomes` kèm `predicted_on` | Tránh tệp vụn; ghép đúng mảnh ngày |
| Agent báo kết quả | Sau "N ngày mô phỏng" | Theo lệnh, ngay sau lô dự đoán | Độ trễ thật không minh hoạ được |
| Kịch bản agent | 4 | 5, thêm `market_rally` | Cần một ca hiệu năng sụp mà feature không đổi (mục 7.7) |
| Mốc cho Evidently | `profile.json` | Mẫu tập huấn luyện đọc lại | Evidently chỉ nhận hai DataFrame thật |
| Mốc hiệu năng | Không nói | Chỉ số `test_*` | Chỉ số `train_*` làm cảnh báo vô dụng khi overfit (mục 7.8) |
| Mức trôi | `ok` / `warning` / `high` | Thêm `insufficient_data` | Không báo xanh khi chưa đo |
| Luật feature drift | Tỉ lệ cột trôi | Tỉ lệ cột **và** độ lớn | Luật tỉ lệ mù trước trôi dồn vào một cột (mục 7.8) |
| `monitoring_dag` | Ba task, `@hourly` | Một task mỗi mô hình, `schedule=None` | XCom không chở được DataFrame; máy 16 GB |
| Mô phỏng lưu lượng | Chỉ qua dòng lệnh | Thêm DAG `traffic_agent` và nút trên Dashboard | Không có lưu lượng thì mọi kết quả giám sát là `insufficient_data` |
| `sample_rows` | Biến môi trường của scheduler | Tham số của từng lần chạy | Dashboard phải chọn được số dòng |
| Thuật toán | Không chỉ định | Ba thuật toán mỗi bài toán, chọn trên Dashboard; tìm tham số tuỳ chọn | Để thử và so sánh từ giao diện |
| Xác thực API layer | API key | Hoãn; dependency rỗng `require_auth` | Chấp nhận được khi chạy local một người dùng |
| Airflow REST | Không nói | Bật `basic_auth` backend | Không có thì mọi lời gọi từ API layer bị 401 |
| Thông tin xác thực trong Airflow | Airflow Connections | Biến môi trường từ `.env`, chuyển vào container qua `DockerOperator` | Cách đang được dùng thật |
| Frontend | React + Tailwind qua nginx | React + Tailwind build bằng Vite; cách phục vụ bản chính thức chưa chọn | Chọn khi dựng Dashboard |
| Màn hình | Tổng quan, Stages & Logs, Dữ liệu, Models, Drift | Tổng quan, Dữ liệu, Models, Drift | Log xem trên Airflow UI |
| Quản lý mô hình | Xem, promote | Thêm xoá phiên bản và xoá cả mô hình | Yêu cầu của chủ dự án |

### 12.3. Thay đổi ở phiên bản 4 (giai đoạn 6, theo 要件定義書 / 基本設計書 v1.3)

Phiên bản 4 đưa hệ thống về khớp với `docs/01-requirements-definition.md` và `docs/02-basic-design.md` bản 1.3. Mã tương ứng nằm trên nhánh `claude/gifted-euler-4cyh8a`.

| Hạng mục | Phiên bản 3 | Phiên bản 4 | Lý do |
| --- | --- | --- | --- |
| Chia train/test | Ngẫu nhiên trên `sample_rows` dòng đầu tệp | Theo thời gian, split point T1/T2 ghi trong manifest của data version; record không có ngày chia bằng hash `property_id` 80/20 | Ngẫu nhiên làm test lạc quan và làm `scenario=none` không còn là mốc sạch (mục 7.3) |
| Simulation set | Không có | Phần sau T2, tối đa 20.000 dòng và 10% dữ liệu | Agent phải gửi dữ liệu model chưa từng thấy |
| Data version | Ghi đè được | Không ghi đè; tên đã có trả 409 | Truy vết được model nào học data nào |
| Fingerprint | Một mã gộp | Working copy ID (version + ETag) và data ID (+ `sample_rows` + seed); XCom và MLflow vẫn gọi là `fingerprint` | Tách “dữ liệu nào” khỏi “lấy bao nhiêu dòng” |
| `prepare_dataset_for_train` | Đọc cả tệp một lượt | Hai lượt: cột nhẹ để lập kế hoạch, rồi chỉ đọc các dòng được chọn | Máy 16 GB |
| Cross-validation khi tuning | KFold ngẫu nhiên | `TimeOrderedSplit` theo thứ tự thời gian | Không để fold sau rò vào fold trước |
| Thuật toán mặc định | `ridge` / `xgboost` | `xgboost` cho cả hai bài toán | Theo 基本設計書 v1.3 |
| Classification | Ngưỡng 0,5 | `ThresholdedClassifier`: ngưỡng cao nhất đạt recall ≥ 0,70 trên 20% dữ liệu mới nhất của tập train | Bỏ sót nhà cần cải tạo đắt hơn báo nhầm |
| Cổng 2 | Chỉ cần tốt hơn champion | Phải hơn một khoảng: RMSE thấp hơn ≥ 1%, AUC cao hơn ≥ 0,005 | Chênh lệch nhỏ hơn nhiễu thì không đổi champion |
| Metric theo nhóm | Không có | Theo `property_type` và `state`; nhóm < 200 dòng (evaluate) / < 50 dòng (giám sát) không chấm | Model tốt trung bình vẫn có thể hỏng ở một nhóm |
| Model card | Không có | `model_card.json` log cùng version; Dashboard có nút xem | 要件定義書 CN-12 |
| Truy vết | Chỉ fingerprint | Thêm git commit, image digest, split point, seed, số dòng train | Tái tạo được một model |
| Deploy | Chỉ gọi `/reload` | Smoke test sau `/reload`; hỏng thì trả alias `champion` về version trước | Không để serving phục vụ model hỏng |
| Promote / xoá qua API | Không báo serving | API gọi `/reload` của serving và trả trạng thái serving trong response | Đóng hạn chế cũ ở mục 13 |
| Serving | `/predict`, `/reload`, `/health` | Thêm `/flush` và `/metrics` (Prometheus) | Giám sát đọc đủ log; đo latency và lỗi |
| Giám sát | 3 phần | 4 phần, thêm `input_quality`; tối thiểu 50 dự đoán; đếm số lần `warning` liên tiếp | 基本設計書 7.4 |
| Evidently | Vừa tính vừa kết luận | Evidently chỉ tính (đọc qua `evidently_adapter`); `ml_common.drift` kết luận | Một nơi giữ ngưỡng |
| Mốc giám sát của agent | Dòng mới nhất theo `listing_date` | Simulation set của champion trừ các `property_id` champion đã học | Mốc `none` sạch |
| Feedback | Chỉ dùng để đo | DAG `feedback_data_pipeline` tạo data version mới từ feedback (≥ 500 record, thay record cùng `property_id`, 20% feedback mới nhất làm test) | Retrain trên data cũ không sửa được drift |
| Cảnh báo | Chỉ trên Dashboard | Prometheus + Pushgateway + Grafana, luật cảnh báo, webhook `ALERT_WEBHOOK_URL`, nhắc lại mỗi 24 giờ | 要件定義書 CN-46 |
| MinIO | Không versioning | Bật versioning; ILM xoá bản cũ, trừ `raw/` | Khôi phục được khi ghi nhầm |
| Kiểm tra tự động | Chỉ pytest ở máy dev | GitHub Actions: ruff, pytest, build các image; test ranh giới giữa các thành phần | Ranh giới trước đây chỉ giữ bằng quy ước |

---

## 13. Câu hỏi còn mở và hạn chế đã biết

**Câu hỏi còn mở**

- [X] Dataset: House Pricing (giả lập, ~2 triệu dòng, dirty).
- [X] Bài toán, cổng, lịch chạy, chiến lược huấn luyện lại, kiến trúc API.
- [X] Cửa sổ giám sát: mặc định 24 giờ (`MONITOR_WINDOW_HOURS`).
- [X] Cột mà `price_inflation` / `market_rally` biến đổi: giữ nguyên (基本設計書 v1.3).
- [ ] Ngưỡng sàn (R² 0,75 / AUC 0,55), ngưỡng giám sát, ngưỡng input quality và luật cảnh báo phải **đo lại theo cách chia theo thời gian**: mọi con số cũ đo trên cách chia ngẫu nhiên.
- [ ] Cách phục vụ Dashboard bản chính thức: API tự phục vụ thư mục build, hay thêm CORS với danh sách origin cụ thể. Lựa chọn thứ hai là một quyết định bảo mật vì chưa có xác thực.
- [ ] Cơ chế xác thực cho API layer — bắt buộc trước khi mở ra ngoài máy local.
- [ ] Khi chuyển lên AWS: giữ MLflow song song với SageMaker Registry hay chuyển hẳn.
- [ ] Thời gian phản hồi mục tiêu của serving, thời gian lưu giữ dữ liệu, sao lưu.

**Hạn chế đã biết**

| Hạn chế | Ảnh hưởng |
| --- | --- |
| Phiên bản 4 **chưa chạy trên hệ thống thật**: chỉ kiểm bằng pytest (moto, MLflow file store, Evidently thật, promtool) và CI build image | Có thể còn lỗi chỉ lộ ra khi các container nói chuyện với nhau |
| Tài liệu vận hành (運用手順書) chưa viết | Khôi phục sự cố vẫn dựa vào CLAUDE.md và các script verify |
| Preview feedback chỉ đếm số cặp, không báo trước số record gốc sẽ bị thay thế | Con số chính xác chỉ có trong manifest sau khi tạo |
| Feedback record giữ `listing_date` gốc; chia theo `predicted_at` | Hai loại record có hai trục thời gian riêng trong cùng manifest |
| Simulation set nhỏ dần khi champion được huấn luyện trên data version có feedback | Agent có thể không còn đủ dòng cho một kịch bản dài |
| RAM của Prometheus, Pushgateway, Grafana trên máy 16 GB chưa đo (đã đặt `mem_limit`) | Có thể phải tắt bớt khi chạy cả pipeline |
| `extract` và `validate` vẫn đọc toàn bộ working copy | Đỉnh RAM của hai stage này không giảm như `prepare_dataset_for_train` |
| Khi tuning, bước tiền xử lý được fit trên cả tập train trước khi chia fold | Điểm CV hơi lạc quan; không ảnh hưởng tập test |
| Luật độ lớn của feature drift dựa trên đúng hai lần đo và phụ thuộc số cột | Có thể báo sai khi số feature thay đổi |
| Báo cáo Evidently kết luận theo luật tỉ lệ riêng (ngưỡng 0,5) | Có thể ghi "không phát hiện trôi" trong khi badge Data drift báo `warning`; khung báo cáo có dòng giải thích |
| Giám sát phụ thuộc `processed/{fp}/`; xoá nó thì mất mốc | `monitoring_dag` fail với `FileNotFoundError` nêu rõ key |
| `zipcode` là cột phân loại với hàng chục nghìn giá trị; quy tắc gộp dưới 1% đưa gần như mọi giá trị vào nhóm "hiếm" | Cột này gần như không đóng góp; vô hại nhưng lãng phí |
| Định dạng ngày `15-Jul-2023` phụ thuộc locale của container | Locale khác tiếng Anh sẽ biến toàn bộ ngày định dạng này thành giá trị thiếu |
| Preview tải nguyên object vào bộ nhớ mỗi lần gọi | Mỗi lần 1,4–2 giây và 0,9–1,3 GB RAM ở process API (đo 21/09/2026) |
| Trần upload 500 MiB chỉ kiểm sau khi FastAPI đã nhận xong body | Tệp vượt trần vẫn chiếm đĩa tạm (tối đa khoảng ba bản) trước khi bị từ chối; Dashboard chặn ở trình duyệt |
| Hai request `/api/health` chồng lên nhau có thể báo cả năm dịch vụ `down`; `postgres` được suy ra qua Airflow | Báo động giả; Dashboard không gửi chồng |
| `/api/health` báo serving `ok` cả khi serving `degraded` (chưa có mô hình) | Màn Models và Drift có trạng thái "chưa có mô hình" riêng |
