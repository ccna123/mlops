# Tài liệu Thiết kế — MLOps Full Pipeline (Offline → AWS)

> Phiên bản 3 — 24/09/2026. Mô tả hệ thống ở trạng thái hiện tại, sau khi năm giai đoạn xây dựng hoàn tất. Các thay đổi so với những phiên bản trước và lý do của từng thay đổi được gom ở mục 12.

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
| API layer cho Dashboard | FastAPI — `services/api/`, cổng 8001 | 18 endpoint (mục 8.3). Đứng giữa Dashboard và Airflow / MLflow / MinIO. |
| Điều phối | Apache Airflow 2.10, `LocalExecutor` | Ba DAG (mục 6) |
| Chạy từng bước | Mỗi bước một image riêng, chạy bằng `DockerOperator` | Dễ chuyển sang SageMaker Processing / Training Job |
| Logic ML dùng chung | Package `common/` (`ml_common`) | Mục 7.1 |
| Thuật toán | scikit-learn, XGBoost | Mục 7.5 |
| Object storage | MinIO (tương thích S3) | Mục 7.3 |
| Theo dõi thí nghiệm & quản lý phiên bản mô hình | MLflow 2.x tự host; backend store là PostgreSQL, artifact store là MinIO | Registry dùng **alias `champion`** (mục 7.5) |
| Dịch vụ dự đoán | FastAPI + Uvicorn — `services/serving/` | Mục 7.6 |
| Sinh lưu lượng mô phỏng | Agent — `services/agent/` | Mục 7.7 |
| Giám sát trôi | Evidently 0.7 | Chỉ có trong image `ml-monitor` (mục 7.10) |
| CSDL quản lý | PostgreSQL | **Hai database tách biệt** trên cùng instance: `airflow` và `mlflow` |
| Xác thực | **Chưa có** | Mọi endpoint của API layer đã khai báo sẵn một dependency rỗng `require_auth` (`services/api/deps.py`), nên thêm xác thực về sau là sửa **một hàm**, không phải từng route. Khi chưa có xác thực, mọi endpoint ghi — kể cả xoá mô hình — mở cho bất kỳ ai tới được cổng 8001. Chấp nhận được khi chạy local một người dùng; **bắt buộc** phải có trước khi mở ra ngoài. |
| Hạ tầng offline | Docker Compose | Toàn bộ service trong một `docker-compose.yml` |
| Chất lượng code | ruff (cấu hình ở `ruff.toml` tại gốc repo) qua `pre-commit`, và `pytest` chạy local | Chưa có CI (mục 7.11) |

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
                       │ /reload  ◀───────┼──── task deploy gọi vào
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

Cả ba DAG đều `schedule=None` và `max_active_runs=1`, và được thiết kế để luôn ở trạng thái **unpaused**. Một lần chạy của DAG đang paused sẽ nằm `queued` vĩnh viễn mà không có tín hiệu nào trên API hay Dashboard cho biết vì sao. `traffic_agent` tự đặt `is_paused_upon_creation=False`; hai DAG còn lại thì không, và `docker-compose.yml` đặt `AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: "true"`, nên **trên một máy mới phải unpause tay `ml_pipeline` và `monitoring_dag` một lần**.

### 6.1. `ml_pipeline` — huấn luyện và đưa vào sử dụng

**Tham số** (gửi qua `conf` của lần trigger, Airflow gộp vào `params`):

| Tham số | Kiểu | Mặc định | Mô tả |
| --- | --- | --- | --- |
| `task_type` | `"regression"` \| `"classification"` | Bắt buộc | Quyết định nhánh nào chạy |
| `estimator_name` | chuỗi hoặc rỗng | Rỗng = `ridge` (regression) / `xgboost` (classification) | Thuật toán, phải thuộc danh sách của `task_type` (mục 7.5) |
| `tune_hyperparameters` | bool | `false` | Bật tìm tham số bằng Grid Search (mục 7.5) |
| `sample_rows` | số nguyên > 0, hoặc rỗng | Rỗng = toàn bộ dòng | Số dòng đầu của dữ liệu thô dùng cho lần chạy này. Nằm trong fingerprint (mục 7.4). |
| `force_reprocess` | bool | `false` | Bỏ qua cache, chuẩn bị lại dữ liệu từ đầu |
| `dataset_version` | chuỗi | `"v1"` | Phiên bản dữ liệu thô. Giá trị được nối thẳng vào đường dẫn, nên không có khái niệm `"latest"`. |

`model_name` **không phải tham số**: DAG suy nó từ `task_type`, để không thể vô tình ghi một mô hình classification vào registered model của regression.

**Cảnh báo:** trigger từ Airflow UI mà không kèm `conf` sẽ chạy toàn bộ ~2 triệu dòng và có thể làm cạn RAM máy 16 GB. Dashboard luôn gửi `sample_rows`.

**Chín task:**

| Task | Loại | Việc làm |
| --- | --- | --- |
| `extract` | Docker | Đọc `raw/{dataset_version}/data.parquet`, lấy `sample_rows` dòng đầu, tính fingerprint (mục 7.4), ghi bản làm việc vào `extracted/{fp}/` |
| `validate` | Docker | Đo chất lượng dữ liệu, ghi báo cáo. Chỉ fail khi dữ liệu **vô dụng** (xem dưới) |
| `prepare_dataset_for_train` | Docker | Sinh target (classification), thao tác theo dòng, chia 80/20. Có cache (mục 7.4) |
| `train` | Docker | Huấn luyện, log nguyên `Pipeline` vào MLflow (mục 7.5) |
| `evaluate` | Docker | Chấm trên tập test, áp hai cổng (mục 7.5). Luôn kết thúc thành công; kết quả đạt/không đạt đi qua XCom |
| `branch_on_gates` | Python | Đạt → `register`; không đạt → `stop_no_deploy` |
| `register` | Docker | Đăng ký phiên bản, gắn alias `champion`, sinh `profile.json` (mục 7.8) |
| `deploy` | Python | `POST /reload` vào serving |
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

Mọi thứ khác — tỉ lệ thiếu từng cột, giá trị ngoài biên, zipcode sai định dạng, dòng trùng — chỉ được đếm và ghi vào `reports/validation/{fp}.json`.

**`prepare_dataset_for_train` không làm sạch theo cột.** Nó chỉ sinh target, loại dòng trùng `property_id`, loại dòng thiếu target, rồi chia tập. Dữ liệu trong `processed/` **vẫn thô ở mức cột** — vẫn còn `"$450,000"`, `"NEW YORK"`, zipcode 4 số. Toàn bộ việc làm sạch theo cột nằm trong `Pipeline` và được đóng gói cùng mô hình (mục 7.1). Nếu bước này làm sạch rồi lưu, mô hình sẽ học trên dữ liệu sạch trong khi `/predict` nhận dữ liệu thô — đúng training/serving skew mà cả thiết kế này tránh. Tên `processed/` vì vậy chỉ có nghĩa "đã xử lý theo dòng và đã chia tập".

`monitor` **không** nằm trong DAG này: nó đo lưu lượng tích luỹ theo thời gian, không đo kết quả của lần huấn luyện vừa xong. Chạy ngay sau `deploy` thì mô hình mới chưa phục vụ request nào và báo cáo sẽ rỗng.

### 6.2. `monitoring_dag` — theo dõi trôi

- **Khởi chạy bởi:** task `compute_drift` của `traffic_agent` (mục 6.3), hoặc `POST /api/drift/run` (không có nút riêng trên Dashboard).
- **Hai task chạy song song**, `monitor_regression` và `monitor_classification`. Mỗi task là **một container `ml-monitor`** làm trọn việc: đọc cửa sổ dữ liệu, so bằng Evidently, ghi báo cáo (mục 7.8).
- Không tách thành ba task "thu thập / so sánh / công bố": XCom chỉ chở được giá trị nhỏ, nên ba task riêng sẽ phải tự đọc lại cửa sổ dữ liệu ba lần.
- **Không tự trigger huấn luyện lại.** Khi có mức `high`, Dashboard hiện nút "Huấn luyện lại" đã điền sẵn `task_type` — người quyết định, không phải hệ thống.
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

Đo ngày 22/09/2026: cả chuỗi khoảng 40 giây (18,5 giây gửi lưu lượng, 20,6 giây tính trôi).

---

## 7. Chi tiết từng thành phần

### 7.1. Package `common/` — nền của cả hệ thống

Đây là thành phần quan trọng nhất về mặt thiết kế. Nó ngăn **training/serving skew**: nếu logic làm sạch bị chép thành hai bản — một cho lúc huấn luyện, một cho serving — chúng sẽ lệch nhau và mô hình sẽ nhận đầu vào khác với lúc học mà không ai phát hiện.

| Module | Trách nhiệm |
| --- | --- |
| `schema.py` | Danh sách 24 cột, loại dữ liệu, khoảng giá trị hợp lệ, giá trị phân loại hợp lệ, target và danh sách cột leakage theo bài toán |
| `parsers.py` | Hàm parse thuần trên **một giá trị đơn lẻ**: `"$450,000"` → float, `has_pool` từ 8 cách biểu diễn, 3 định dạng `listing_date`, zipcode, chuẩn hoá text. Không biết gì về pandas. |
| `cleaning.py` | Transformer sklearn **theo cột**: `RawRecordCleaner`, `OutlierClipper`, `DateFeatures` |
| `rowops.py` | Thao tác **theo dòng**: `drop_duplicates`, `drop_rows_missing_target` |
| `features.py` | Dựng `Pipeline` (transformer + estimator) theo `task_type` |
| `targets.py` | Sinh cột target (parse `sale_price`, hoặc sinh `needs_renovation` từ `condition`) |
| `estimators.py` | Danh sách thuật toán theo bài toán, tham số mặc định, lưới tìm tham số |
| `metrics.py` | Chỉ số dùng chung cho `train` và `evaluate` |
| `gates.py` | Hai cổng quyết định promote |
| `validation.py` | Luật của `validate` |
| `fingerprint.py` | Tính fingerprint — khoá cache nối dữ liệu đã xử lý với dữ liệu thô sinh ra nó |
| `storage.py` | Wrapper `boto3` và **toàn bộ** quy ước đường dẫn trên object storage. **Điểm duy nhất phải sửa khi chuyển sang S3.** |
| `rawdata.py` | Chuyển CSV thô thành parquet (dùng chung cho upload qua API và script nạp dữ liệu ban đầu) |
| `profiling.py` | Tính hồ sơ thống kê cơ sở |
| `inference_log.py` | Bộ đệm nhật ký dự đoán: khi nào ghi, bỏ gì khi đầy. Không tự ghi MinIO. |
| `drift.py` | Phần giám sát không cần Evidently: đọc cửa sổ, ghép ground truth, **luật xếp mức** |
| `stageio.py` | Cách một stage trả kết quả về Airflow |

**Ranh giới giữa `cleaning.py` và `rowops.py` là ràng buộc kiến trúc, không phải cách tổ chức file.** Transformer trong `cleaning.py` nằm trong `Pipeline` và được đóng gói cùng mô hình, nên chúng chạy ở cả lúc huấn luyện (tới 2 triệu dòng) lẫn serving (một record). Một transformer xoá dòng sẽ chạy đúng suốt lúc huấn luyện rồi trả về DataFrame rỗng khi `/predict` gọi nó, làm serving sập. `rowops` chỉ được gọi từ `prepare_dataset_for_train`; `features.py` và serving không bao giờ import nó.

`train` log nguyên `Pipeline` vào MLflow, nên mô hình trong Registry **tự chứa toàn bộ logic làm sạch**, và `/predict` nhận record **thô** — đúng như dữ liệu người dùng thật có trong tay. Serving không import `cleaning` lẫn `rowops`.

**Thứ tự bên trong `Pipeline`:** `RawRecordCleaner` → `OutlierClipper` → `DateFeatures` → chọn cột theo bài toán → impute + scale / one-hot → estimator. Thứ tự này là ràng buộc: nếu `OutlierClipper` hay `DateFeatures` chạy trước `RawRecordCleaner`, giá dạng chuỗi và ngày ở ba định dạng sẽ **âm thầm** thành giá trị thiếu, không có lỗi nào xuất hiện.

**Xử lý giá trị lạ lúc dự đoán:** cột thiếu được thêm với giá trị thiếu; giá trị số thiếu điền trung vị của tập huấn luyện; giá trị phân loại thiếu điền giá trị phổ biến nhất; giá trị phân loại chiếm dưới 1% gộp vào nhóm "hiếm"; giá trị phân loại chưa từng gặp không gây lỗi.

### 7.2. Airflow

- `LocalExecutor` (đủ cho một máy, không cần Celery/Redis). Metadata DB là database `airflow` trên PostgreSQL.
- Mỗi task nặng dùng `DockerOperator` gọi image riêng. Chỉ `airflow-scheduler` được mount docker socket; webserver không cần và không được cấp.
- Dữ liệu giữa các task đi qua **đường dẫn trên MinIO**, không qua XCom. XCom chỉ chở giá trị nhỏ (fingerprint, run_id, metric, version). Mỗi stage in đúng một dòng JSON ở cuối stdout; dòng đó là giá trị XCom (`stageio.py`).
- Tham số của lần chạy đi vào container qua biến môi trường.
- API layer gọi Airflow REST bằng basic auth. Airflow 2.10 mặc định chỉ nhận phiên đăng nhập của trình duyệt, nên `docker-compose.yml` bật thêm `AIRFLOW__API__AUTH_BACKENDS: "airflow.api.auth.backend.basic_auth,airflow.api.auth.backend.session"` cho mọi service Airflow. Thiếu dòng này, mọi lời gọi từ API layer bị `401` với thông báo không gợi ý đúng nguyên nhân.

### 7.3. MinIO — bố cục bucket

```
s3://ml-pipeline/
├── raw/{dataset_version}/data.parquet
├── extracted/{fingerprint}/data.parquet                        # bản làm việc của extract
├── processed/{fingerprint}/{task_type}/
│   ├── train.parquet
│   └── test.parquet
├── artifacts/                                                  # MLflow artifact store
├── monitoring-baseline/{model_name}/{version}/profile.json
├── inference-log/{model_name}/dt=YYYY-MM-DD/part-*.parquet
├── ground-truth/{model_name}/dt=YYYY-MM-DD/part-*.parquet
└── reports/
    ├── validation/{fingerprint}.json                           # báo cáo của validate
    └── {model_name}/
        ├── latest.json                                         # bản sao tóm tắt mới nhất
        └── {run_id}/
            ├── summary.json                                    # tóm tắt một lần giám sát
            └── evidently.html                                  # báo cáo chi tiết
```

Mọi key được sinh bởi hàm `*_key()` / `*_prefix()` trong `storage.py`; không file nào khác tự nối đường dẫn.

**Parquet cho mọi dữ liệu dạng bảng.** CSV gốc 373 MB / 2 triệu dòng xuống khoảng 60–80 MB, đọc nhanh hơn nhiều lần, và giữ được kiểu dữ liệu. Với một máy chạy đồng thời Airflow + PostgreSQL + MinIO + MLflow + serving, đây là điều kiện để chạy được, không phải tối ưu sớm.

**Dữ liệu thô vào MinIO bằng hai đường:** `scripts/seed_raw_data.py` nạp `house_pricing_dirty.csv` thành `raw/v1/` một lần lúc cài đặt; và `POST /api/data/upload` cho các phiên bản sau. `extract` chỉ đọc từ object storage, không đọc tệp local — giống hệ thống thật, nơi dữ liệu thô do hệ thống khác đổ vào.

**Tập test cố định.** Chia 80/20 bằng seed cố định (`42`) và lưu lại `test.parquet`. Nếu tập test đổi giữa các lần huấn luyện thì phép so với champion ở mục 7.5 vô nghĩa.

### 7.4. Fingerprint và cache

**`extract` tính fingerprint** và chuyển nó cho các task sau qua XCom:

```
fingerprint = sha256(dataset_version + ETag của raw object + str(sample_rows))
```

- Dùng ETag thay vì băm nội dung: MinIO tự đổi ETag khi object đổi, nên không phải đọc 2 triệu dòng chỉ để biết dữ liệu có đổi hay không.
- `sample_rows` **bắt buộc** nằm trong fingerprint. Thiếu nó, lần chạy 200.000 dòng sẽ dùng nhầm cache của lần chạy toàn bộ dòng — sai kiểu này không báo lỗi, mô hình được huấn luyện trên một tập khác tập người chạy tưởng.
- Tính ở `extract` (chứ không ở `prepare_dataset_for_train`) vì `validate` cũng cần fingerprint để đặt tên báo cáo; một chỗ tính thì không có hai cách tính để lệch nhau.

**Hai tầng cache:**

| Tầng | Vị trí | Dùng chung giữa hai bài toán? |
| --- | --- | --- |
| Bản làm việc (đọc raw, lấy mẫu — phần đắt nhất) | `extracted/{fp}/` | Có |
| Dữ liệu đã chuẩn bị | `processed/{fp}/{task_type}/` | Không |

`task_type` phải nằm trong đường dẫn `processed/`: hai bài toán có target khác nhau và loại những dòng khác nhau vì thiếu target, nên dùng chung một đường dẫn thì bài toán này sẽ âm thầm dùng cache của bài toán kia.

`prepare_dataset_for_train` bỏ qua khi `train.parquet` và `test.parquet` đều đã có và `force_reprocess` là `false`. Dashboard có ô "Xử lý lại dữ liệu từ đầu" map sang `force_reprocess=true`.

Lý do có cache: mỗi lần đổi thuật toán để thử, nếu phải xử lý lại 2 triệu dòng thì phần lớn thời gian chạy bị lãng phí.

### 7.5. MLflow, thuật toán và cổng `evaluate`

**MLflow.** Tracking server + Model Registry tự host trong container riêng; backend store là database `mlflow`, artifact store là MinIO. Hai registered model: `house_price_regressor` và `house_needs_renovation_classifier`.

**Phiên bản đang sử dụng được đánh dấu bằng alias `champion`**, không bằng model stage. MLflow 2.x đã deprecate stage và MLflow 3 bỏ hẳn; alias cũng khớp với từ vựng champion/challenger của cổng thứ hai. `evaluate` và serving nạp mô hình bằng `models:/{name}@champion`.

**Thứ được log mỗi lần huấn luyện:** tên và tham số estimator, `fingerprint` đã dùng, chỉ số `train_*`, và nguyên `Pipeline` đã fit. `evaluate` ghi thêm vào cùng run: chỉ số `test_*` của mô hình mới và `champion_test_*` của champion trên cùng tập test — để về sau đọc lại được vì sao một mô hình bị chặn.

**Thuật toán:**

| `task_type` | Estimator | Mặc định |
| --- | --- | --- |
| regression | `ridge`, `xgboost`, `random_forest` | `ridge` |
| classification | `xgboost`, `svm`, `random_forest` | `xgboost` |

Danh sách này nằm ở `ESTIMATOR_NAMES` trong `estimators.py`; API và Dashboard đọc thẳng từ đó, không chép lại. `svm` được bọc bằng `CalibratedClassifierCV` để có `predict_proba` (không dùng `SVC(probability=True)`, đã bị deprecate); thiếu nó thì không tính được AUC và cổng sẽ fail ngay.

**Tìm tham số (`tune_hyperparameters=true`).** Estimator được bọc bằng `GridSearchCV(cv=5)` trên lưới nhỏ ở `PARAM_GRIDS` (tối đa 8 tổ hợp mỗi thuật toán — máy 16 GB). Tiêu chí chọn là **đúng chỉ số mà cổng và giám sát dùng**: `neg_root_mean_squared_error` cho regression, `roc_auc` cho classification — để "tốt nhất khi tìm tham số" và "tốt nhất khi đánh giá" là cùng một thước đo. `GridSearchCV` là một estimator hợp lệ, nên các bước sau (`evaluate`, `register`, serving) không cần biết việc tìm tham số có xảy ra hay không.

**Hai cổng**, phải qua cả hai mới được promote:

| Cổng | Regression | Classification | Mục đích |
| --- | --- | --- | --- |
| 1. Ngưỡng sàn | R² ≥ 0,75 | AUC ≥ 0,55 | Chặn mô hình rác, kể cả mô hình đoán hằng số |
| 2. Tốt hơn champion trên **cùng `test.parquet`** | RMSE thấp hơn | AUC cao hơn | Chặn việc thay champion bằng một mô hình kém hơn chỉ vì nó vượt ngưỡng. Hoà thì không thắng. |

Chưa có champion thì chỉ áp cổng 1. Cổng nằm ở `gates.py`.

**Vì sao classification dùng AUC, không dùng F1.** Ngưỡng F1 hỏng theo hai hướng ngược nhau, cả hai đều đo được trên dữ liệu thật: trên một target có 56% lớp dương, `DummyClassifier` luôn trả "có" đạt F1 0,72 — vượt ngưỡng 0,70 mà không nhìn dữ liệu; còn trên `needs_renovation` (25% lớp dương), một mô hình tốt với AUC 0,71 chỉ đạt F1 0,16 và sẽ bị chặn nhầm. F1 phụ thuộc ngưỡng quyết định và tỉ lệ lớp, nên một ngưỡng F1 cố định chỉ đúng cho đúng một phân bố dữ liệu. AUC không phụ thuộc hai yếu tố đó, và mọi mô hình đoán hằng số đều cho đúng 0,5. F1 và accuracy vẫn được tính và log để báo cáo.

**`evaluate` luôn exit 0**, kể cả khi mô hình không đạt: "không đạt" là một kết quả hợp lệ, được `branch_on_gates` đọc qua XCom, không phải lỗi của pipeline.

Các con số ngưỡng là điểm khởi đầu, có thể hiệu chỉnh khi có thêm kết quả huấn luyện thực tế.

### 7.6. Serving (`services/serving/`)

Image serving **không chứa mô hình**. Lúc khởi động nó nạp bản đang giữ alias `champion` của cả hai mô hình từ MLflow Registry vào bộ nhớ. Một container duy nhất phục vụ cả hai mô hình.

| Endpoint | Mô tả |
| --- | --- |
| `POST /predict/{task_type}` | `task_type` ∈ `regression` \| `classification`. Body là **một record thô**. Trả `request_id`, `prediction`, `model_name`, `model_version`; classification trả thêm `probability`. Ghi vào inference log. |
| `POST /feedback/{task_type}` | Body `{"outcomes": [{"request_id", "predicted_on", "actual"}, ...]}` — một **lô** kết quả thực tế. Ghi vào `ground-truth/`. |
| `POST /reload` | Nạp lại champion của cả hai mô hình và thay trong bộ nhớ, không khởi động lại. Task `deploy` gọi endpoint này. Luôn trả 200 kèm trạng thái. |
| `GET /health` | Mô hình nào đang nạp, phiên bản bao nhiêu; `inference_log.buffered` và `inference_log.dropped` |

**Thiếu mô hình thì vẫn khởi động.** Mô hình nào nạp được thì phục vụ mô hình đó. `status` là `ok` khi nạp được ít nhất một mô hình, `degraded` khi không nạp được mô hình nào. Từ chối khởi động sẽ biến registry trống thành vòng khởi động lại liên tục, và không dựng được serving trước khi có đủ mô hình.

**Mã lỗi:**

| Mã | Khi nào |
| --- | --- |
| 503 | `task_type` hợp lệ nhưng chưa có champion |
| 422 | `task_type` không hợp lệ, body không phải object, hoặc lô feedback rỗng |
| 500 | Mô hình đã nạp nhưng `predict` ném lỗi |

Record thiếu cột **không** phải lỗi 4xx: `Pipeline` tự bổ sung giá trị (mục 7.1).

**Inference log** — mỗi bản ghi gồm `request_id`, `timestamp`, `raw_input`, `prediction`, `probability` (classification; cần vì giám sát chấm classification bằng AUC, không tính được từ một bool), `model_name`, `model_version`. Ghi theo lô, với ba quy tắc theo thứ tự ưu tiên:

1. **`/predict` không bao giờ chậm hay lỗi vì chuyện ghi log.** Bản ghi vào bộ đệm trong bộ nhớ; việc ghi xuống MinIO diễn ra ở nền khi đủ **500 bản ghi** hoặc sau **30 giây**.
2. **Ghi hỏng thì giữ lại thử lần sau.** MinIO khởi động lại vài giây không được làm mất dữ liệu giám sát.
3. **Bộ đệm có trần 5.000 bản ghi.** Vượt trần thì bỏ bản **cũ nhất** và tăng `dropped`, hiện ở `/health`. Trần tồn tại vì quy tắc 2: giữ lại vô hạn khi MinIO hỏng lâu trong lúc agent đang gửi sẽ làm hết RAM.

Ghi theo lô vì agent gửi hàng nghìn request; một object cho mỗi request sẽ làm MinIO đầy object vụn và giám sát đọc rất chậm.

**Ground truth** — một lần gọi `/feedback` thành một tệp parquet (cùng lý do với inference log). Mỗi phần tử mang `predicted_on`, ngày agent đã gọi `/predict`; serving phân mảnh `ground-truth/` theo **ngày đó**, không theo ngày nhận, để nó nằm cùng mảnh `dt=` với inference log tương ứng và ghép được. Serving không tự tra ngày vì nó không giữ bảng `request_id → ngày`. Ghi thẳng, không qua bộ đệm.

**Hạn chế đã biết:** đổi champion bằng `POST /api/models/{name}/{version}/promote` hoặc xoá mô hình **không** làm serving nạp lại. Serving tiếp tục phục vụ mô hình đang nằm trong RAM cho tới lần khởi động lại hoặc lần `/reload` kế tiếp (tức lần huấn luyện kế tiếp đi tới `deploy`). Xem mục 13.

### 7.7. Agent mô phỏng thị trường (`services/agent/`)

Sinh lưu lượng thật cho serving, thay cho cách giả lập trôi bằng cách cắt bộ dữ liệu gốc. Chạy được bằng DAG `traffic_agent` (mục 6.3), bằng dòng lệnh (`python -m services.agent`), hoặc bằng service `agent` trong compose (profile `agent`, tắt mặc định).

Mỗi lần chạy:

1. Lấy **20.000 dòng có `listing_date` mới nhất** trong dữ liệu thô làm nguồn.
2. Rút ngẫu nhiên `count` dòng, biến đổi theo kịch bản.
3. Gọi `POST /predict/{task_type}` cho từng dòng.
4. Gọi `POST /feedback/{task_type}` một lần với kết quả thực tế của các dòng đó, mỗi phần tử kèm `predicted_on`. Mặc định gửi cho 100% request (`--feedback-ratio`).

Dự đoán và kết quả thực tế là **hai lời gọi tách rời**, đúng như trong thực tế: lúc hỏi giá chưa ai biết căn nhà bán được bao nhiêu. Agent không giả lập "chờ N ngày"; độ trễ vẫn hiện ra vì hai lời gọi tách rời.

**Năm kịch bản** (`drift_scenario`, bắt buộc phải có):

| Kịch bản | Biến đổi đầu vào | Kết quả thực tế gửi về | Dùng để kiểm chứng |
| --- | --- | --- | --- |
| `none` | Không | Thật | Không báo động nhầm |
| `price_inflation` | `list_price` × 1,2 | Thật (không đổi) | Biến động ở một cột mô hình không dùng thì không phải trôi |
| `market_rally` | `list_price` × 1,2 | `sale_price` × 1,2 | Hiệu năng có thể sụp trong khi dữ liệu đầu vào không đổi |
| `market_shift` | Dồn `city` về một, hai thành phố | Thật | Phát hiện trôi dữ liệu đầu vào |
| `new_segment` | `property_type` giá trị chưa từng thấy | Thật | Serving không lỗi với giá trị lạ |

**Kết quả đo với mô hình regression (20/09/2026):**

| Kịch bản | Feature | Prediction | Performance | Kết luận |
| --- | --- | --- | --- | --- |
| `none` | `ok` | `ok` | `ok` | Không báo động nhầm |
| `price_inflation` | `ok` | `ok` | `ok` | Giống hệt `none`. `list_price` không phải feature của regression (mục 5), nên biến động ở nó không chạm tới mô hình. |
| `market_rally` | `ok` | `ok` | **`high`** (RMSE × 2,24) | **Hiệu năng sụp trong khi feature drift bằng không.** Bằng chứng mạnh nhất cho việc báo cáo ba loại trôi tách riêng. |
| `market_shift` | `warning` | `high` | `high` | Kịch bản duy nhất thật sự thử được feature drift, vì `city` là một feature |
| `new_segment` | `warning` | `ok` | `warning` | Serving không trả HTTP 500 — điều kiện chính của kịch bản này |

Nếu agent chỉ sinh dữ liệu đúng phân phối của tập huấn luyện thì trôi không bao giờ xảy ra và không kiểm chứng được hệ thống phát hiện đúng. Hai kịch bản `price_inflation` và `market_rally` chứng minh rằng **dữ liệu đổi không đồng nghĩa với mô hình hỏng, và dữ liệu không đổi không đồng nghĩa với mô hình ổn** — phản xạ "thấy feature drift thì huấn luyện lại" sai theo cả hai chiều.

Ngày đầu chưa có lưu lượng thì màn Drift trống; người vận hành dùng nút mô phỏng trên màn đó để có dữ liệu.

### 7.8. Giám sát trôi (`stages/monitor/`)

**Mốc so sánh gắn với phiên bản champion**, không gắn với một bộ dữ liệu cố định, nên không bao giờ có chuyện so phiên bản mới với mốc của phiên bản cũ. Có ba mốc, cho ba loại trôi:

| Mốc | Nội dung | Nguồn |
| --- | --- | --- |
| Mẫu tập huấn luyện | Tối đa `MONITOR_REFERENCE_ROWS` (mặc định 10.000) dòng, seed cố định 42 | Lần ngược: `model version → run_id → param "fingerprint" → processed/{fp}/{task_type}/train.parquet` |
| Phân bố prediction lúc huấn luyện | Prediction của chính champion chạy lại trên mẫu ở trên | Tính tại thời điểm giám sát, vì lúc huấn luyện không lưu phân bố này |
| Chỉ số trên tập test | `test_*` do `evaluate` ghi cho champion | MLflow |

**Vì sao mốc hiệu năng là chỉ số trên tập test, không phải trên tập huấn luyện.** Tập test là mốc duy nhất đo trên dữ liệu mô hình chưa thấy — đúng bản chất của lưu lượng thực tế. Chỉ số `train_*` đo trên chính những dòng mô hình đã fit, nên mô hình càng overfit thì mốc càng đẹp và cảnh báo càng luôn đỏ. Đo ngày 22/09/2026: champion xgboost có RMSE 14.321 trên tập train nhưng 152.620 trên tập test; lưu lượng thực tế ở 203.809 cho tỉ lệ 14,2 lần (`high`) nếu so với train, nhưng 1,33 lần (`warning`) nếu so với test. Chỉ số test cũng là con số màn Models hiển thị.

**`profile.json`** (sinh ở `register`, lưu tại `monitoring-baseline/{model_name}/{version}/`) chứa với mỗi cột số: tỉ lệ thiếu, mean, std, min, max, phân vị 25/50/75, histogram 20 khoảng; với mỗi cột phân loại: tỉ lệ thiếu, số giá trị khác nhau, tỉ lệ từng giá trị. Evidently không nhận một bản tóm tắt (nó chỉ so hai DataFrame thật), nên `profile.json` **không** dùng để tính trôi; nó là cách rẻ nhất để trả lời "phiên bản này học từ phân bố nào" mà không phải đọc lại parquet.

**Cửa sổ:** `MONITOR_WINDOW_HOURS`, mặc định 24 giờ gần nhất.

**Ba loại trôi** — Dashboard gọi chúng là Data / Model / Performance drift; khoá trong JSON là `feature` / `prediction` / `performance`:

| Loại | So cái gì | Cách tính | Khi nào có |
| --- | --- | --- | --- |
| `feature` | Feature giải mã từ `raw_input` trong log với mẫu tập huấn luyện | Evidently `DataDriftPreset` trên các cột feature của bài toán | Ngay |
| `prediction` | Cột `prediction` trong log với phân bố prediction lúc huấn luyện | Evidently `DataDriftPreset` trên một cột | Ngay |
| `performance` | Prediction với kết quả thực tế, ghép qua `request_id` | `metrics.compute_metrics`, so với chỉ số `test_*` | Chỉ khi có ground truth |

**Luật xếp mức** (ở `drift.py`, không phụ thuộc Evidently, nên test được rẻ trên máy dev):

| Loại | `ok` | `warning` | `high` |
| --- | --- | --- | --- |
| `feature` — luật tỉ lệ | Tỉ lệ cột trôi < 0,3 | 0,3 – 0,5 | > 0,5 |
| `feature` — luật độ lớn | Tổng (`value − threshold`) trên mọi cột < 0 | ≥ 0 | — |
| `prediction` | Không trôi | — | Có trôi |
| `performance` — regression | RMSE hiện tại / RMSE test < 1,2 | 1,2 – 1,5 | > 1,5 |
| `performance` — classification | AUC giảm < 0,05 | 0,05 – 0,10 | > 0,10 |

`feature` lấy mức nặng hơn giữa hai luật. Luật tỉ lệ một mình mù trước trôi dồn vào một, hai cột: ở `market_shift`, `city` lệch Jensen-Shannon 0,78 so với ngưỡng 0,1, nhưng chỉ 2/22 cột vượt ngưỡng — đúng bằng tỉ lệ đo được ở `none` — nên luật tỉ lệ báo `ok` sai. Luật độ lớn bắt được trường hợp đó.

**Trạng thái thứ tư, `insufficient_data`.** Khi số dòng ghép được với ground truth dưới `MONITOR_MIN_GROUND_TRUTH` (mặc định 50), `performance` là `insufficient_data`, **không bao giờ** là `ok`. Báo `ok` khi chưa đo là nói dối, và là kiểu nói dối nguy hiểm nhất ở đây: dấu xanh trong khi chưa ai kiểm tra. Champion không có `test_*` (đăng ký ngoài pipeline) cũng cho `insufficient_data`.

**Mức tổng hợp** (`severity`) là mức nặng nhất trong ba loại, **bỏ qua** `insufficient_data`; nếu cả ba đều `insufficient_data` thì mức tổng hợp là `insufficient_data`. Dashboard luôn hiện ba loại tách riêng; mức tổng hợp chỉ là thông tin phụ.

**Đầu ra mỗi lần chạy, cho mỗi mô hình:**

| Object | Nội dung |
| --- | --- |
| `reports/{model}/{run_id}/summary.json` | `model_name`, `model_version`, `task_type`, `run_id`, `computed_at`, `window_hours`, `severity`, `parts`, `n_predictions`, `n_ground_truth`, `current_metrics`, `reference_metrics`, `reference_source`, `report_key` |
| `reports/{model}/latest.json` | Bản sao của summary mới nhất, ghi đè mỗi lần — để API trả "mới nhất" bằng một lần đọc |
| `reports/{model}/{run_id}/evidently.html` | Báo cáo chi tiết của Evidently, khoảng 5 MB |

Summary viết trước ngày 22/09/2026 không có `reference_metrics` và `reference_source`; mọi nơi đọc phải chịu được việc chúng vắng. `reference_source: "test_metrics"` đánh dấu thế hệ summary chấm theo chỉ số test.

**Evidently không vào `ml-base`.** Nó kéo theo khoảng 500 MB thư viện vẽ biểu đồ; `ml-monitor` là `FROM ml-base` rồi cài thêm Evidently. Vì vậy `drift.py` không import Evidently ở mức module. Lưu ý thứ tự tham số của Evidently 0.7: `report.run(current, reference)` — gọi ngược vẫn chạy và ra báo cáo, chỉ là đảo vai hai tập, không có exception nào báo.

### 7.9. Cấu hình & bí mật

- `.env.example` được commit; `.env` thật thì gitignore.
- Biến chính: `MINIO_ENDPOINT`, `MINIO_ENDPOINT_INTERNAL`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `ML_BUCKET`, `POSTGRES_*`, `MLFLOW_TRACKING_URI`, `AIRFLOW_ADMIN_USER`, `AIRFLOW_ADMIN_PASSWORD`, `SERVING_URL`.
- Docker Compose đưa các biến này vào môi trường của scheduler; DAG chuyển tiếp chúng vào từng container stage qua tham số `environment` của `DockerOperator`. Airflow Connections **không** được dùng. Không thông tin xác thực nào được viết cứng trong DAG hay trong code.
- Giới hạn số dòng khi phát triển đặt **theo từng lần chạy** qua `sample_rows` (mục 6.1); biến `SAMPLE_ROWS` trong `.env` không còn tác dụng.

### 7.10. Image dùng chung

`ml-base` (`stages/base/Dockerfile`) là `python:3.12-slim` cộng `common/` đã cài (kéo theo pandas, numpy, scikit-learn, xgboost, pyarrow, boto3) và MLflow client. Mọi image khác `FROM ml-base:latest`:

| Nhóm | Image |
| --- | --- |
| Stage | `extract`, `validate`, `prepare_dataset_for_train`, `train`, `evaluate`, `register`, `ml-monitor` (+ Evidently) |
| Service | `ml-serving`, `ml-agent`, `ml-api` |

Không có image nền chung thì mỗi image tự cài lại thư viện: build rất lâu và phiên bản dễ lệch — mà phiên bản lệch giữa lúc huấn luyện và lúc serve là loại bug khó tìm nhất. Mô hình pickle bởi scikit-learn chỉ nạp lại được bởi cùng minor version Python và cùng version scikit-learn, nên **huấn luyện và serve đều diễn ra trong container** (Python 3.12). Ví dụ đã gặp: thêm xgboost vào `common/` thì `ml-serving` cũng phải build lại, nếu không nó không unpickle được mô hình xgboost.

**Khi `common/` thay đổi phải build lại cả năm tầng, theo thứ tự:** `ml-base` → bảy stage image → `ml-serving` → `ml-agent` → `ml-api`. Chỉ build `ml-base` là chưa đủ: các image dựa trên nó vẫn giữ bản `ml_common` cũ bên trong cho tới khi được build lại.

### 7.11. Kiểm thử

- Test nằm ở `common/tests/` và `services/*/tests/`, chạy bằng `pytest`. Đo ngày 23/09/2026: 666 test pass ở Python 3.13 trên máy dev. Trong container `ml-base` (Python 3.12) chỉ có `common/`, nên test cần `stages/` hoặc `services/` được skip có chủ ý ở đó; test của `services/api/` chỉ chạy trên máy dev.
- Mỗi loại dirty trong `house_pricing_README.md` có ít nhất một test khẳng định xử lý đúng.
- Những bảo đảm kiến trúc có test riêng: `Pipeline` không bao giờ bỏ dòng và dự đoán được cho đúng một record; mô hình nhận dữ liệu thô; cột leakage không ảnh hưởng dự đoán (kiểm bằng `DecisionTreeRegressor`, không bằng `DummyRegressor` — Dummy bỏ qua mọi feature nên sẽ pass dù `Pipeline` sai); cổng chặn được mô hình đoán hằng số; luật xếp mức giám sát, kể cả `insufficient_data`.
- **Round-trip:** cùng một record thô qua `Pipeline` vừa fit và qua `Pipeline` nạp lại từ MLflow phải ra cùng kết quả (`scripts/smoke_round_trip.py`).
- Mỗi giai đoạn từ 1 tới 5a có một script kiểm tra trên hệ thống thật (`scripts/verify_*.ps1`). Dashboard hiện được kiểm tra bằng trình duyệt; chưa có script.
- Lint: ruff, cấu hình ở `ruff.toml` tại gốc repo, rule `E`, `F`, `I`, `UP`, `B`, `D` (docstring Google style bắt buộc cho code production).
- **Chưa có CI.** Repo đã có trên GitHub nhưng chưa cấu hình GitHub Actions.

---

## 8. Dashboard

Dashboard là **thành phần chính thức của hệ thống**, không phải công cụ minh hoạ: đây là nơi chạy và theo dõi pipeline, tải dữ liệu, quản lý mô hình, mô phỏng lưu lượng và theo dõi trôi.

### 8.1. Các màn hình

| Màn hình | Chức năng |
| --- | --- |
| Tổng quan | Form khởi chạy `ml_pipeline`: `task_type`, thuật toán (danh sách từ `/api/estimators`, bỏ trống là mặc định), tìm tham số, `sample_rows` hoặc toàn bộ dòng, xử lý lại dữ liệu từ đầu, `dataset_version`. Bảng các lần chạy gần đây; dải chín task của lần chạy đang chọn. |
| Dữ liệu | Tải CSV (tối đa 500 MiB, hỏi xác nhận khi ghi đè phiên bản đã có); xem tối đa 200 dòng thô và thống kê từng cột (loại, tỉ lệ thiếu, số giá trị ngoài biên) |
| Models | Mỗi mô hình một khối; bảng phiên bản với **cột chỉ số sinh từ dữ liệu thật** (RMSE/MAE/R² cho regression, AUC/F1/accuracy cho classification); đổi champion; xoá một phiên bản (bị chặn nếu là champion); xoá cả mô hình |
| Drift | Chọn mô hình; khối mô phỏng lưu lượng (kịch bản, số request, tiến trình hai chặng, tự tải lại khi xong); **ba ô trôi riêng** với bốn trạng thái; bảng so chỉ số trên tập test với trên lưu lượng thực tế; biểu đồ diễn biến; báo cáo Evidently nhúng khi bấm xem; nút "Huấn luyện lại" khi có mức `high` |

Màn "Stages & Logs" và endpoint đọc log đã bị bỏ: log chi tiết của từng task xem trên Airflow UI. Feature Store không có ở giai đoạn 1 (mục 11).

**Quy tắc chung cho mọi màn hình:**

- **`insufficient_data` phải trông khác `ok`** ở ba trục cùng lúc: nền xám gạch chéo, viền nét đứt, chữ "chưa đủ dữ liệu". Không bao giờ dùng màu xanh hay dấu tích cho nó.
- **Ba loại trôi hiện riêng**, không gộp thành một badge: ở `market_rally`, feature `ok` trong khi performance `high`, nên một badge tổng hợp màu xanh sẽ nói dối.
- Phân biệt ba tình huống: **chưa có dữ liệu** (không phải lỗi), **không tìm thấy**, **hệ thống đang hỏng**.
- Mọi thao tác ghi thật (khởi chạy huấn luyện, đổi champion, xoá, ghi đè dữ liệu) đều qua hộp xác nhận. Sau thao tác, luôn tải lại dữ liệu thật thay vì tự cập nhật trước.
- Thanh trạng thái đọc `/api/health` không nhanh hơn mỗi 10 giây và không gửi yêu cầu mới khi yêu cầu trước chưa trả lời.
- Giao diện **không tự đặt ngưỡng nào**: biểu đồ và dòng kết luận chỉ hiển thị mức do stage `monitor` tính. Chép ngưỡng sang frontend là tạo một bản thứ hai sẽ lệch.

### 8.2. Vì sao cần API layer

Gọi thẳng Airflow / MLflow / MinIO từ trình duyệt không dùng được: thông tin xác thực sẽ lộ ở frontend, mỗi service phải mở quyền truy cập từ trình duyệt riêng, và mỗi lần thay backend (Airflow → MWAA, MLflow → SageMaker) là phải sửa frontend. API layer che toàn bộ những thứ đó — khi chuyển lên AWS chỉ sửa `services/api/`, frontend giữ nguyên.

Ranh giới này hiện được giữ bằng quy ước (không chuỗi `localhost:8080`, `:5000`, `:9000` nào trong `dashboard/`); chưa có bước kiểm tra tự động (mục 13).

Mọi collaborator của API được inject (`create_app(airflow, registry, reports, probes, storage)`). Client nào không dựng được vì thiếu biến môi trường thì là `None`: app vẫn khởi động và `/api/health` báo dependency đó `down`, thay vì crash-loop.

### 8.3. API contract (Dashboard ↔ `services/api/`)

Mọi đường dẫn có tiền tố `/api`. Lỗi trả `{"detail": ...}` theo chuẩn FastAPI (riêng lỗi 500 là văn bản thuần).

| Method | Endpoint | Mô tả | Gọi xuống |
| --- | --- | --- | --- |
| `POST` | `/pipeline/run` | Khởi chạy `ml_pipeline` (body dưới). Trả ngay `{run_id, dag_id, state}`, không chờ chạy xong. | Airflow |
| `GET` | `/pipeline/runs` | Các lần chạy gần đây và trạng thái | Airflow |
| `GET` | `/pipeline/runs/{run_id}` | Trạng thái từng task của một lần chạy | Airflow |
| `GET` | `/estimators` | Thuật toán theo `task_type` | `ml_common.estimators` |
| `POST` | `/data/upload` | Tải CSV (multipart), lưu thành `raw/{dataset_version}/`. Tên phiên bản khớp `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`; trần 500 MiB (413 khi vượt). Ghi đè phiên bản đã có. | MinIO |
| `GET` | `/data/{dataset_version}/preview` | Tối đa 200 dòng thô và thống kê cột trên 200.000 dòng đầu; `total_rows` là của cả tệp | MinIO |
| `GET` | `/models` | Registered model, phiên bản, chỉ số test, `is_champion` | MLflow |
| `POST` | `/models/{name}/{version}/promote` | Chuyển alias `champion` sang phiên bản này | MLflow |
| `DELETE` | `/models/{name}/{version}` | Xoá một phiên bản; **409** nếu đó là champion | MLflow |
| `DELETE` | `/models/{name}` | Xoá cả mô hình, kể cả champion. **Không hoàn tác được.** | MLflow |
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
| `sample_rows` | Số nguyên > 0, hoặc vắng/`null` = toàn bộ dòng. `0` và số âm bị từ chối bằng 422 — không được hiểu thầm thành "tất cả", nếu không một máy chỉ đủ RAM cho lần chạy nhỏ sẽ nhận một lần chạy 2 triệu dòng. |
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
│   └── traffic_agent_dag.py         # mô phỏng lưu lượng rồi giám sát — mục 6.3
├── stages/
│   ├── base/                        # image ml-base — mục 7.10
│   ├── extract/
│   ├── validate/
│   ├── prepare_dataset_for_train/
│   ├── train/
│   ├── evaluate/
│   ├── register/                    # alias champion + profile.json
│   └── monitor/                     # Evidently
├── services/
│   ├── serving/                     # /predict /feedback /reload /health
│   ├── api/                         # backend của Dashboard
│   └── agent/                       # agent mô phỏng thị trường
├── dashboard/                       # React + Tailwind (Vite)
├── docker/                          # cấu hình riêng của Postgres, MLflow
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

`stages/` không có `deploy/`: bước đó chỉ là một lời gọi `POST /reload`, nên dùng operator có sẵn của Airflow; đóng gói cả một image để gửi một request là thừa. `register` vẫn có container riêng vì nó phải tính `profile.json` trên toàn bộ tập huấn luyện.

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
| 13 | (Nâng cao) Tự huấn luyện lại khi trôi vượt ngưỡng, kèm thời gian chờ giữa hai lần | Chưa làm |
| 14 | **Chuyển lên AWS**: MinIO → S3 (sửa `storage.py`), Airflow → MWAA, serving → SageMaker Endpoint, inference log → Data Capture, Evidently → Model Monitor | Chưa làm |

Bước 2 đứng trước mọi stage là có chủ ý: nếu viết stage trước rồi mới tách ra `common/`, khả năng cao logic sẽ bị chép sang serving trước khi kịp tách.

---

## 11. Phạm vi bị cắt khỏi giai đoạn 1

**Feature Store (Feast).** Nó kéo theo một registry PostgreSQL riêng và một job materialization, trong khi pipeline xử lý theo lô này chưa có nhu cầu cung cấp feature theo thời gian thực. Xem xét lại khi pipeline chạy ổn; khi đó nó sẽ đứng giữa `prepare_dataset_for_train` và `train`, và map sang SageMaker Feature Store lúc chuyển lên AWS.

**Tự huấn luyện lại.** Hệ thống cảnh báo, con người quyết định (mục 6.2). Có thể làm ở bước 13 của lộ trình.

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

---

## 13. Câu hỏi còn mở và hạn chế đã biết

**Câu hỏi còn mở**

- [X] Dataset: House Pricing (giả lập, ~2 triệu dòng, dirty).
- [X] Bài toán, cổng, lịch chạy, chiến lược huấn luyện lại, kiến trúc API.
- [X] Cửa sổ giám sát: mặc định 24 giờ (`MONITOR_WINDOW_HOURS`).
- [ ] Ngưỡng sàn (R² 0,75 / AUC 0,55) và ngưỡng giám sát có thể cần hiệu chỉnh khi có thêm kết quả thực tế.
- [ ] Cách phục vụ Dashboard bản chính thức: API tự phục vụ thư mục build, hay thêm CORS với danh sách origin cụ thể. Lựa chọn thứ hai là một quyết định bảo mật vì chưa có xác thực.
- [ ] Cơ chế xác thực cho API layer — bắt buộc trước khi mở ra ngoài máy local.
- [ ] Khi chuyển lên AWS: giữ MLflow song song với SageMaker Registry hay chuyển hẳn.
- [ ] Có nên đổi cột mà `price_inflation` / `market_rally` biến đổi sang một feature thật của regression (ví dụ `living_area_sqft`) để chúng thử được feature drift. Bỏ `list_price` khỏi danh sách leakage **không** phải câu trả lời: lý do loại nó ở mục 5 vẫn đúng.
- [ ] Thời gian phản hồi mục tiêu của serving, thời gian lưu giữ dữ liệu, sao lưu.

**Hạn chế đã biết**

| Hạn chế | Ảnh hưởng |
| --- | --- |
| Promote hay xoá mô hình qua API không gọi `/reload` của serving | Serving vẫn phục vụ mô hình cũ trong RAM tới lần khởi động lại hoặc lần `deploy` kế tiếp |
| Race khi ghi inference log: giám sát chạy ngay sau một đợt lưu lượng lớn có thể bắt trúng lúc bộ đệm mới ghi một phần (quan sát được một lần: 33/500) | Báo cáo có thể thiếu một phần lưu lượng vừa gửi |
| `scenario=none` không phải mốc sạch tuyệt đối: `zipcode` luôn bị coi là trôi, vì agent lấy các dòng mới nhất theo `listing_date` còn mô hình huấn luyện trên `sample_rows` dòng đầu tệp | Mọi ngưỡng hiệu chỉnh dựa trên `none` thừa hưởng sai lệch này |
| Luật độ lớn của feature drift dựa trên đúng hai lần đo và phụ thuộc số cột | Có thể báo sai khi số feature thay đổi |
| Báo cáo Evidently kết luận theo luật tỉ lệ riêng (ngưỡng 0,5) | Có thể ghi "không phát hiện trôi" trong khi badge Data drift báo `warning`; khung báo cáo có dòng giải thích |
| Giám sát phụ thuộc `processed/{fp}/`; xoá nó thì mất mốc | `monitoring_dag` fail với `FileNotFoundError` nêu rõ key |
| `zipcode` là cột phân loại với hàng chục nghìn giá trị; quy tắc gộp dưới 1% đưa gần như mọi giá trị vào nhóm "hiếm" | Cột này gần như không đóng góp; vô hại nhưng lãng phí |
| Định dạng ngày `15-Jul-2023` phụ thuộc locale của container | Locale khác tiếng Anh sẽ biến toàn bộ ngày định dạng này thành giá trị thiếu |
| Preview tải nguyên object vào bộ nhớ mỗi lần gọi | Mỗi lần 1,4–2 giây và 0,9–1,3 GB RAM ở process API (đo 21/09/2026) |
| Trần upload 500 MiB chỉ kiểm sau khi FastAPI đã nhận xong body | Tệp vượt trần vẫn chiếm đĩa tạm (tối đa khoảng ba bản) trước khi bị từ chối; Dashboard chặn ở trình duyệt |
| Hai request `/api/health` chồng lên nhau có thể báo cả năm dịch vụ `down`; `postgres` được suy ra qua Airflow | Báo động giả; Dashboard không gửi chồng |
| `/api/health` báo serving `ok` cả khi serving `degraded` (chưa có mô hình) | Màn Models và Drift có trạng thái "chưa có mô hình" riêng |
| Chưa có kiểm tra tự động cho ranh giới "Dashboard chỉ gọi API layer" | Một thay đổi sau này có thể phá ranh giới mà không ai phát hiện |
