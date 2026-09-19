# Plan 3 — Serving: Thiết kế

Ngày: 2026-09-19. Tiếp nối Plan 2 (Batch pipeline) đã hoàn thành và merge vào `main`.

Tài liệu này là spec cho Plan 3. Nguồn sự thật vẫn là `mlops-pipeline-design.md`;
chỗ nào lệch khỏi tài liệu gốc đều ghi rõ ở mục 8 kèm lý do.

## 1. Phạm vi

**Trong phạm vi:**

- `services/serving/` với `/predict/{model}`, `/reload`, `/health`
- Ghi inference log theo batch lên MinIO
- Task `deploy` nối vào cuối DAG `ml_pipeline`
- **Cho nhánh classification chạy thật** tới khi có champion trong Registry

**Ngoài phạm vi, để lại Plan 4:** `/feedback` và ground truth, `services/agent/`,
`stages/monitor/`, `monitoring_dag`.

Mục 7.6 của `mlops-pipeline-design.md` liệt kê `/feedback` trong bảng endpoint của
serving. Đó là mô tả **trạng thái cuối cùng** của service, không phải thứ tự xây.
Bản đồ plan ở cuối `docs/superpowers/plans/2026-09-17-foundation.md` xếp `/feedback`
vào Plan 4 cùng với thứ sinh ra dữ liệu cho nó. Hai tài liệu không mâu thuẫn.

## 2. Quyết định kiến trúc

### 2.1. Serving `FROM ml-base:latest`

Không phải lựa chọn tiện tay — đây là ràng buộc số 4 trong `CLAUDE.md`: model pickle
bởi scikit-learn chỉ load lại được bởi **cùng minor version Python và cùng version
scikit-learn**.

`train` chạy trong `ml-base`. Nếu serving dựng từ một image khác, hai bên phải tự giữ
đồng bộ bằng tay, và lệch một bản vá là model unpickle hỏng — hoặc tệ hơn, load được
nhưng hành xử khác. Dùng chung image gốc khiến hai bên khớp **theo cấu trúc**, không
phải nhờ kỷ luật.

Đây cũng chính là lập luận đã chọn `DockerOperator` ở Plan 2 mục 2.1.

### 2.2. Serving không chứa và không sao chép logic làm sạch

`/predict` nhận **record thô** — đúng như dữ liệu người dùng thật có trong tay, còn
`"$450,000"` và `"NEW YORK"`. Model tự làm sạch, vì toàn bộ `sklearn.Pipeline` đã được
đóng gói cùng nó vào MLflow ở stage `train`.

**Serving không được import `ml_common.cleaning`, và tuyệt đối không import
`ml_common.rowops`.** Một transformer xoá dòng gọi với một record sẽ trả DataFrame rỗng
và làm `/predict` sập. Ranh giới này đã được chứng minh end-to-end ở Plan 2: model load
lại từ Registry ăn được record thô lấy thẳng từ `test.parquet`.

Serving chỉ dùng `ml_common.storage` (đường dẫn MinIO) và `ml_common.schema` (nếu cần
kiểm tra cột).

### 2.3. Thiếu model thì vẫn khởi động, và nói ra

Serving load champion của **cả hai** model lúc khởi động. Nhưng model classification
chưa tồn tại cho tới khi nhánh đó chạy, và ngay cả sau đó nó vẫn có thể bị cổng chặn.

- Load được model nào thì phục vụ model đó.
- `GET /health` liệt kê model nào đang load và version bao nhiêu.
- `POST /predict/{model}` tới model chưa có trả **503** kèm lý do, không phải 500.
- `POST /reload` nạp được model mới mà **không cần restart container**.

**Lý do:** refuse-to-start biến registry trống thành restart loop, và khiến không thể
dựng serving trước khi có đủ model. Lazy-load thì `/health` không nói được gì trước khi
có traffic — mà `/health` chính là thứ dashboard ở Plan 5 đọc.

### 2.4. Inference log: batch, có trần, mất mát nhìn thấy được

Buffer trong bộ nhớ, flush khi **đủ 500 record hoặc quá 30 giây**, ghi một file parquet
qua `storage.inference_log_key()` (đã có từ Plan 1).

**Vì sao theo batch:** agent simulator ở Plan 4 bắn vài nghìn request. Ghi một object mỗi request thì
MinIO đầy object vụn và `monitoring_dag` phải mở vài nghìn file để đọc.

Ba quy tắc, theo thứ tự ưu tiên:

1. **`/predict` không bao giờ chậm hay lỗi vì chuyện ghi log.** Ghi log là việc quan
   trọng; phục vụ request quan trọng hơn.
2. **Flush hỏng thì giữ lại thử lần sau.** MinIO restart vài giây không được làm mất dữ
   liệu monitoring.
3. **Buffer có trần 5000 record.** Vượt trần thì bỏ bản **cũ nhất**, đếm số đã bỏ, và
   báo con số đó ở `/health`.

Quy tắc 3 tồn tại vì quy tắc 2: giữ lại vô hạn nghĩa là MinIO hỏng lâu + agent đang bắn
= hết RAM và serving chết. Máy 16GB đang chạy Postgres, MinIO, MLflow, hai container
Airflow, và sắp có thêm agent.

Điểm mấu chốt: **mất mát có giới hạn và nhìn thấy được**, thay vì mất âm thầm hoặc sập
hệ thống.

Mỗi bản ghi gồm: `request_id`, `timestamp`, `raw_input`, `prediction`, `model_name`,
`model_version` — đúng mục 7.6 của spec gốc.

### 2.5. Đổi bài toán classification sang `needs_renovation`

**Bài toán cũ `sold_within_30_days` bị loại sau khi đo.**

Nó phụ thuộc gần như hoàn toàn vào `days_on_market` — mà cột đó **bắt buộc phải loại**,
vì `sold_within_30_days` suy trực tiếp ra từ nó (leakage, `schema.py` đã khai báo). Bỏ nó
đi thì không còn gì: toàn bộ 19 feature còn lại gộp lại chỉ đạt **AUC 0.58**.

Một target mà bỏ một cột là hết tín hiệu thì không dạy được gì về feature engineering, và
cũng không cho monitoring ở Plan 4 thứ gì đáng theo dõi.

**Bài toán mới:** `needs_renovation` = `condition` ∈ {`poor`, `fair`}. Chiếm **25,1%** dữ liệu.

|                                    | AUC              |
| ---------------------------------- | ---------------- |
| **GBM, 19 feature hợp lệ** | **0.7061** |
| `list_price` một mình          | 0.5619           |
| `stories` một mình             | 0.5061           |
| `listing_year` một mình        | 0.5039           |
| `has_pool` một mình            | 0.5010           |
| `property_type` một mình       | 0.5004           |
| `dummy`                          | 0.5000           |

**Không cột nào một mình mang tín hiệu.** Cột mạnh nhất đạt 0.56, phần còn lại gần như
đúng 0.50 — riêng lẻ thì vô dụng. Gộp lại mới ra 0.71. Tín hiệu nằm ở **tương tác giữa
các feature**, không ở một cột chủ đạo.

**Ý nghĩa nghiệp vụ:** `condition` trong thực tế do người bán tự khai, thường thiếu hoặc
lạc quan quá mức — chính dataset này cũng có ~10% giá trị bẩn ở cột đó. Dự đoán nó từ
thuộc tính khách quan (tuổi nhà, diện tích, khu vực, giá rao, điểm trường, chỉ số tội
phạm) phục vụ: nền tảng BĐS gắn cờ tin cần thẩm định kỹ, ngân hàng đánh giá tài sản thế
chấp, nhà đầu tư săn nhà cần cải tạo.

**Hai ứng viên khác đã đo và loại:**

- **"Bán trên giá rao"** (`sale_price > list_price`) — nghe hợp lý nhất về nghiệp vụ, nhưng
  **AUC 0.4972**: generator tạo hoàn toàn ngẫu nhiên. Không có gì để học.
- **"Là chung cư"** (`property_type == "condo"`) — AUC 0.68, tín hiệu cũng phân tán, nhưng
  dự đoán loại bất động sản là vô nghĩa: người ta luôn biết sẵn.

### 2.6. Cổng classification đổi từ F1 sang AUC

F1 làm ngưỡng sàn **hỏng theo hai hướng ngược nhau**, cả hai đều đã đo được:

**Hướng 1 — cho model rác lọt.** Trên target cũ `sold_within_30_days` (55,8% dương):

| Model        | F1               | AUC              |
| ------------ | ---------------- | ---------------- |
| `dummy`    | **0.7186** | **0.5000** |
| `logistic` | 0.6982           | 0.5872           |

`DummyClassifier(strategy="prior")` phán dương cho **mọi** căn nhà. Recall = 1.0 vì nó bắt
hết ca dương; precision = 0.558 đúng bằng tỷ lệ lớp; F1 = 2×0.558×1/1.558 = **0.716**. Nó
vượt ngưỡng F1 ≥ 0.70 mà không hề nhìn dữ liệu, trong khi model thật trượt.

**Hướng 2 — chặn nhầm model tốt.** Trên target mới `needs_renovation` (25,1% dương):

| Model     | F1               | AUC              |
| --------- | ---------------- | ---------------- |
| GBM       | **0.1592** | **0.7061** |
| `dummy` | 0.0000           | 0.5000           |

Lớp dương chỉ chiếm 25% nên ở ngưỡng quyết định mặc định 0.5, model hiếm khi phán dương →
F1 thấp. Ngưỡng F1 ≥ 0.70 sẽ **chặn một model có AUC 0.71**.

**Nguyên nhân chung:** F1 phụ thuộc vào **ngưỡng quyết định** và **tỷ lệ lớp**. Một con số
F1 cố định vì thế chỉ đúng cho đúng một phân bố dữ liệu, và hỏng âm thầm khi phân bố đổi —
mà drift làm phân bố đổi chính là thứ Plan 4 tồn tại để phát hiện.

**Cổng mới:**

|                              | Cũ         | Mới                   |
| ---------------------------- | ----------- | ---------------------- |
| Ngưỡng sàn classification | F1 ≥ 0.70  | **AUC ≥ 0.55**  |
| So với champion             | F1 cao hơn | **AUC cao hơn** |

AUC không phụ thuộc ngưỡng quyết định, và mọi model đoán hằng số đều cho đúng 0.5 theo
định nghĩa. Model thật đạt 0.71 nên vượt thoải mái; `dummy` đúng 0.50 nên bị chặn.

F1 và accuracy **vẫn được tính và log vào MLflow** để báo cáo. Chỉ đổi thứ dùng làm cổng.

Regression giữ nguyên R² ≥ 0.75 và so RMSE — ở đó `dummy` ra R² ≈ 0 nên cổng đã chặn đúng.

### 2.7. Task `deploy` không có image riêng

`register → deploy`, và `deploy` chỉ là một lời gọi `POST /reload`. Dùng `PythonOperator`
với `urllib` trong thư viện chuẩn.

**Lý do:** spec gốc mục 9 ghi rõ `stages/` không có thư mục `deploy/` vì "đóng gói cả một
image để gửi một request là thừa". Dùng `PythonOperator` thay vì `HttpOperator` để khỏi
phải cấu hình một Airflow Connection cho đúng một URL nội bộ cố định.

## 3. API Endpoint

### `GET /health`

```json
{
  "status": "ok",
  "models": {
    "regression": {"loaded": true, "name": "house_price_regressor", "version": "3"},
    "classification": {"loaded": false, "name": "house_sold_fast_classifier", "version": null}
  },
  "inference_log": {"buffered": 137, "dropped": 0}
}
```

`status` là `"ok"` khi **ít nhất một** model load được, `"degraded"` khi không model nào
load được. Container vẫn sống ở cả hai trạng thái.

`dropped` là số record inference log đã bị bỏ do vượt trần — bằng 0 là khoẻ.

### `POST /predict/{model}`

`model` ∈ `regression` | `classification`. Body là **một record thô**:

```json
{"city": "  NEW YORK ", "list_price": "$450,000", "bedrooms": 3, "...": "..."}
```

Trả về:

```json
{"request_id": "uuid4", "prediction": 412350.75, "model_name": "house_price_regressor", "model_version": "3"}
```

Với classification, `prediction` là boolean và có thêm `probability` (float).

Mã lỗi:

| Mã | Khi nào                                                                        |
| --- | ------------------------------------------------------------------------------- |
| 503 | `model` hợp lệ nhưng chưa load được champion                           |
| 422 | `model` không thuộc hai giá trị cho phép, hoặc body không phải object |
| 500 | Model load rồi nhưng`predict` ném lỗi                                     |

Record thiếu cột **không** phải lỗi 4xx: `RawRecordCleaner` bỏ qua cột vắng mặt và
`SimpleImputer` điền giá trị — đúng thiết kế, vì serving phải chịu được record thật
thiếu trường tuỳ chọn.

### `POST /reload`

Không có body. Nạp lại champion của cả hai model, swap in-memory, trả về đúng khối
`models` như `/health`. Luôn trả 200 kể cả khi không model nào load được — nó báo trạng
thái, không phải báo lỗi.

## 4. Thay đổi trong code đã có

Ba chỗ dưới đây **chặn nhánh classification**, phát hiện khi khảo sát trước khi viết spec.

### 4.1. `common/ml_common/gates.py`

```python
FLOOR = {"regression": ("r2", 0.75), "classification": ("auc", 0.55)}
COMPARISON = {"regression": ("rmse", "lower"), "classification": ("auc", "higher")}
```

**Coupling phải ghi rõ:** đổi cổng sang AUC khiến `auc` trở thành khoá **bắt buộc** trong
dict metrics của classification. `metrics.compute_metrics` chỉ thêm `auc` khi được truyền
`y_proba`, và `evaluate/main.py` chỉ truyền `y_proba` khi model có `predict_proba`. Nếu
sau này ai đó thêm một classifier không có `predict_proba`, `gates.evaluate_gates` sẽ ném
`KeyError: 'auc'` — đúng như thiết kế (thà nổ còn hơn promote một model không ai đo), nhưng
thông báo lỗi sẽ khó hiểu. Plan 3 phải có test khẳng định hành vi này, để lần sau người đọc
traceback hiểu ngay vì sao.

### 4.1b. `schema.py` — target classification mới

```python
TARGET_CLASSIFICATION = "needs_renovation"
```

`needs_renovation` **không tồn tại trong raw data** — nó được sinh ra từ `condition`. Vì
vậy `condition` trở thành **cột leakage** của bài toán classification: nó chính là nguồn
của target.

Leakage classification sau khi đổi:

| Cột                    | Vì sao loại                     |
| ----------------------- | --------------------------------- |
| `property_id`         | Định danh, không phải feature |
| `condition`           | **Nguồn sinh ra target**   |
| `sale_price`          | Chỉ biết sau khi bán           |
| `days_on_market`      | Chỉ biết sau khi bán           |
| `sold_within_30_days` | Chỉ biết sau khi bán           |
| `price_category`      | Suy ra từ`sale_price`          |

`list_price` **được giữ** — tại thời điểm đăng tin nó đã biết, và nó là feature đơn lẻ
mạnh nhất (AUC 0.56).

Tên registered model đổi: `house_sold_fast_classifier` → `house_needs_renovation_classifier`.

### 4.1c. `targets.py` — sinh target thay vì chỉ parse

Hiện `parse_target(series, task_type)` nhận sẵn cột target. Regression vẫn thế
(`sale_price` có trong raw). Classification thì không — target phải **sinh ra** từ
`condition`.

Thêm `derive_target(df, task_type) -> pd.Series`:

- regression: `parse_target(df["sale_price"], "regression")` như cũ
- classification: chuẩn hoá `condition` rồi trả `condition ∈ {"poor", "fair"}`;
  `condition` thiếu hoặc không đọc được thì trả **null**, để `rowops` loại dòng đó

`prepare_dataset_for_train` gọi `derive_target` thay vì `parse_target`, gán vào cột
`needs_renovation`, rồi mới `drop_rows_missing_target` và split như cũ.

Hàm không được đoán: `condition` là `"unknown"` hay rác thì trả null, đúng quy ước
"parser không bao giờ đoán" trong `CLAUDE.md`.

### 4.2. DAG suy `model_name` từ `task_type`

Hiện `params` có `model_name` mặc định cứng theo regression. Chạy `task_type=classification`
mà quên truyền `model_name` sẽ **ghi model classification vào registered model của
regression** — hỏng registry một cách im lặng, và `evaluate` sẽ so hai model khác bài toán.

`model_name` phải suy ra từ `task_type` trong DAG, không để người gọi truyền.

### 4.3. DAG suy `estimator_name` mặc định từ `task_type`

Mặc định hiện là `"ridge"`, không hợp lệ cho classification — `build_estimator` sẽ ném
`ValueError`. Mặc định phải theo `task_type`: `ridge` cho regression, `logistic` cho
classification. Người gọi vẫn ghi đè được.

## 5. Cấu trúc thư mục mới

```
services/
└── serving/
    ├── Dockerfile          # FROM ml-base:latest
    ├── app.py              # FastAPI: routes, state, startup
    └── model_registry.py   # load champion từ MLflow, giữ trong bộ nhớ
common/ml_common/
└── inference_log.py        # bộ đệm theo lô — logic thuần, test không cần container
dags/
└── ml_pipeline_dag.py      # thêm task deploy
docker-compose.yml          # thêm service serving
```

**`inference_log.py` nằm ở `common/` chứ không ở `services/serving/`** vì nó là logic
thuần (đầy chưa, hết hạn chưa, vượt trần thì bỏ gì) và `common/` đã có sẵn bộ test chạy
ở cả Python 3.13 local lẫn 3.12 trong container. Đặt ở `services/` thì phải dựng bộ test
thứ hai.

Ranh giới: `inference_log.py` **quyết định khi nào và bỏ gì**, không tự ghi MinIO —
serving đưa cho nó một hàm flush. Nhờ vậy test được bằng danh sách trong bộ nhớ.

## 6. Test

**Logic thuần, pytest không cần container:**

- Bộ đệm: đủ 500 thì báo cần flush; quá 30 giây thì báo cần flush; dưới cả hai thì không;
  vượt trần 5000 thì bỏ bản **cũ nhất** và tăng `dropped`; flush hỏng thì record **ở lại**.
- Cổng AUC mới: `dummy` với AUC 0.50 bị chặn; model AUC 0.58 qua; hoà champion không thắng.

**Serving, dùng `fastapi.TestClient` với model giả — không cần MLflow chạy:**

- `/health` khi chưa model nào load → `status: degraded`, `loaded: false`
- `/predict/regression` khi chưa load → **503**
- `/predict/nonsense` → **422**
- `/predict` với record **thô** (`"$450,000"`, `"  NEW YORK "`) → 200, có `request_id`
- Record thiếu cột tuỳ chọn → 200, không phải 4xx
- Mỗi lần `/predict` thành công thì buffer tăng đúng 1

**Chạy thật, theo thứ tự này:**

1. `/health` khi chỉ có model regression → một model loaded, một không
2. Chạy DAG `task_type=classification` → champion classification xuất hiện
3. `POST /reload` → `/health` giờ báo **hai** model loaded
4. `/predict` cả hai model bằng record thô lấy từ `test.parquet`
5. Xác nhận inference log **nằm thật trên MinIO** qua `mc ls`, và đọc lại được bằng pandas
6. DAG chạy full có `deploy`: `register → deploy` và `/health` phản ánh version mới

## 7. Definition of Done

- [ ] `docker compose ps` có `mlops-serving` healthy
- [ ] `/health` trả đúng khối `models` và `inference_log`
- [ ] `/predict/regression` với record **thô** trả prediction hợp lý (hàng trăm nghìn đô)
- [ ] `/predict/classification` trả boolean kèm `probability`
- [ ] `/predict` tới model chưa load trả **503**, không phải 500
- [ ] Champion `house_needs_renovation_classifier` tồn tại với **AUC ≥ 0.70**, và `dummy` **bị cổng chặn**
- [ ] Không cột đơn lẻ nào đạt AUC > 0.60 — xác nhận tín hiệu thật sự phân tán
- [ ] Inference log nằm thật trên MinIO, đọc lại bằng pandas ra đủ 6 cột
- [ ] Buffer vượt trần thì `dropped` tăng và hiện ở `/health`
- [ ] DAG chạy full tới `deploy`, `/health` phản ánh version vừa register
- [ ] Serving **không import** `ml_common.cleaning` hay `ml_common.rowops` (kiểm bằng grep)
- [ ] Toàn bộ test pass ở cả Python 3.13 local lẫn 3.12 trong `ml-base`

Ba mục quan trọng nhất là **cổng chặn được `dummy`**, **`/predict` ăn record thô**, và
**serving không import logic cleaning** — chúng là ba thứ chứng minh thiết kế còn nguyên
vẹn, không phải chỉ chạy được.

## 8. Chỗ tài liệu này lệch khỏi `mlops-pipeline-design.md`

| Mục | Spec gốc                                                  | Tài liệu này                              | Lý do                                                                                  |
| ---- | ---------------------------------------------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------- |
| 7.5  | Classification: F1 ≥ 0.70                                 | **AUC ≥ 0.55**, so champion bằng AUC | F1 ≥ 0.70 cho`dummy` (0.719) lọt và chặn model thật (0.698); đo trên 48k dòng |
| 7.6  | Load bản`Production`                                    | Load alias`@champion`                      | Đã đổi ở Plan 2 mục 2.3; MLflow 2.22 deprecate stage                              |
| 7.6  | Bảng endpoint có`/feedback`                            | `/feedback` để Plan 4                    | Mục 7.6 mô tả trạng thái cuối; bản đồ plan xếp thứ tự                       |
| 7.6  | "buffer và flush khi đủ 500 record hoặc quá 30 giây" | Thêm **trần 5000 + đếm số bỏ**  | Spec không nói flush hỏng thì làm gì; giữ vô hạn là hết RAM                  |
| —   | Không nói thiếu model thì sao                          | Khởi động degraded,`/predict` trả 503  | Lỗ hổng trong spec gốc                                                               |

`mlops-pipeline-design.md` mục 7.5 và 7.6 sẽ được cập nhật theo bảng này khi Plan 3 bắt đầu.
