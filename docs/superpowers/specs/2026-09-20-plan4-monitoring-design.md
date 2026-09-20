# Plan 4 — Monitoring & Drift: Thiết kế

Ngày: 2026-09-20. Tiếp sau Plan 3 (Serving).

Tương ứng bước 9–10 của lộ trình ở `mlops-pipeline-design.md` mục 10.

---

## 1. Phạm vi

Plan 4 làm cho hệ thống **tự biết khi nào model của nó đang hỏng dần**.

Vào:

- `services/agent/` — sinh traffic thật theo 5 kịch bản thị trường.
- `POST /feedback/{task_type}` trên serving — nhận kết quả thật, ghi `ground-truth/`.
- `common/ml_common/drift.py` — gom cửa sổ dữ liệu, join, và luật quy ra mức độ.
- `stages/monitor/` — image `ml-monitor` chứa Evidently.
- `dags/monitoring_dag.py` — DAG duy nhất chạy theo lịch.

Không vào:

- Auto-retrain khi drift cao. §6.2 đã chốt: hệ thống cảnh báo, người quyết định.
  Nút "Retrain ngay" thuộc Plan 5.
- `services/api/` và dashboard — Plan 5.
- Đổi bất cứ thứ gì trong 6 stage của Plan 2. Xem mục 6.

Lý do gộp agent và monitoring vào một plan: Definition of Done của cả plan là
"`none` ra `ok`, `market_shift` ra `high`" — `none` là control bắt false
positive, `market_shift` là kịch bản chứng minh feature drift kêu thật, vì nó
bóp méo `city`, một feature model có nhìn thấy (xem mục 2.5 và mục 8; đo thật
ở Task 11 cho thấy `price_inflation` không dùng được cho vế thứ hai — xem mục
2.5). Tách đôi thì nửa đầu chỉ chứng minh được "record có rơi xuống MinIO",
còn nửa sau không có gì để đo.

---

## 2. Quyết định kiến trúc

### 2.1. Baseline cho Evidently là tập train đọc lại, không phải `profile.json`

Đây là quyết định quan trọng nhất của plan này, và nó **mâu thuẫn với câu chữ
của §7.8** trong tài liệu gốc.

§7.8 viết: "Baseline là profile thống kê gắn với một model version, **không
phải một dataset**." Stage `register` đang làm đúng vậy — ghi `profile.json` có
mean/std/quantile/histogram cho từng cột.

Vấn đề: Evidently không nhận profile. `DataDriftPreset` nhận **hai `Dataset`
dựng từ hai DataFrame** rồi tự so. Không có đường nào nhét một bản tóm tắt vào
chỗ đó.

Ba hướng đã cân nhắc:

| Hướng | Cách làm | Vì sao không chọn |
| --- | --- | --- |
| Lưu thêm mẫu train lúc register | `register` ghi kèm `baseline-sample.parquet` | Phải sửa stage đã chạy ổn từ Plan 2, và tốn dung lượng mỗi version |
| Tự tính drift từ `profile.json` | Tự viết PSI/KS | Phải tự code phần thống kê, và Evidently gần như chỉ còn để vẽ HTML |
| **Đọc lại tập train** | Lần ngược từ model version | **Chọn hướng này** |

Đường lần ngược:

```
model version  →  run_id  →  MLflow param "fingerprint"  →  processed/{fp}/{task}/train.parquet
```

Đường này **không phải lý thuyết**: `scripts/smoke_round_trip.py` đã chạy đúng
nó từ Plan 2 (`client.get_run(version.run_id).data.params["fingerprint"]`), và
`train/main.py` đã log `fingerprint` làm param.

`profile.json` **không bị bỏ**. Nó vẫn là thứ rẻ nhất để trả lời "model này học
từ phân phối nào" mà không phải đọc parquet, và Plan 5 sẽ dùng nó cho
histogram trên dashboard. Chỉ là Evidently không ăn được nó.

Rủi ro đã biết: nếu `processed/{fp}/` bị xoá thì mất baseline, và
monitoring_dag sẽ fail với `FileNotFoundError` nêu rõ key. Chấp nhận — khi nào
thành vấn đề thật thì chuyển sang hướng "lưu thêm mẫu", và đó chỉ là thêm một
lệnh ghi file ở `register`.

**Lấy mẫu, không lấy cả tập.** Tập train có thể 160.000 dòng. Reference chỉ lấy
tối đa 10.000 dòng (`MONITOR_REFERENCE_ROWS`, seed cố định 42). Đủ để đo phân
phối, và giữ cho Evidently lẫn bộ nhớ trong tầm của máy 16GB.

### 2.2. Evidently không vào `ml-base`

`ml-base` đang 1.32GB và là gốc của 6 stage image lẫn `ml-serving`. Evidently
kéo theo plotly và khoảng +500MB. Nhét vào `ml-base` nghĩa là serving — thứ
không bao giờ tính drift — cũng phải cõng.

Nên: `stages/monitor/Dockerfile` là `FROM ml-base:latest` rồi
`pip install evidently`, thành `ml-monitor:latest`. Chỉ image này nặng.

Kéo theo: `common/ml_common/drift.py` **không được import Evidently ở mức
module**. Bất cứ ai import `ml_common` cũng sẽ phải có Evidently, mà `ml-base`
thì không có. Phần gọi Evidently nằm trong `stages/monitor/main.py`, import
lazy trong hàm — đúng cách `model_registry.load_from_mlflow` đang import mlflow.

Phân chia trách nhiệm:

- `drift.py` — đọc cửa sổ, join `request_id`, **luật quy ra mức độ**. Thuần
  pandas, test được ở máy dev không cần Evidently.
- `monitor/main.py` — dựng `Dataset`, gọi Evidently, ghi HTML/JSON.

Luật quy ra mức độ là phần dễ sai và đáng test nhất, nên nó phải nằm chỗ test
được rẻ.

### 2.3. Evidently 0.7 — API khác hẳn 0.4, và thứ tự tham số ngược trực giác

Bản hiện tại là **0.7.23** (kiểm tra ngày 2026-09-20), yêu cầu Python >= 3.10.
Container đang 3.12 nên không vướng.

API 0.7:

```python
from evidently import DataDefinition, Dataset, Report
from evidently.presets import DataDriftPreset

schema = DataDefinition(numerical_columns=[...], categorical_columns=[...])
current = Dataset.from_pandas(df_current, data_definition=schema)
reference = Dataset.from_pandas(df_reference, data_definition=schema)

report = Report([DataDriftPreset()])
results = report.run(current, reference)     # CURRENT TRUOC, REFERENCE SAU

results.save_html("evidently.html")
summary = results.dict()
```

Hai cái bẫy, ghi ra đây vì cả hai đều **chạy được mà ra kết quả sai**:

1. **`report.run(current, reference)` — current đứng trước.** Gọi ngược thì
   Evidently vẫn chạy, vẫn ra report, chỉ là đảo vai trò: nó sẽ báo "tập train
   bị drift so với traffic production". Không có exception nào bắt giúp.
2. **API 0.4 hoàn toàn khác** (`Report(metrics=[...])`,
   `report.run(reference_data=..., current_data=...)`, `as_dict()`). Code chép
   từ blog cũ sẽ `ImportError` ngay — cái này thì may, vì nó nổ sớm.

Pin `evidently>=0.7,<0.8`. Task đầu của implementation plan là xác minh lại API
trên đúng version được pin, không viết chay.

Ràng buộc `numerical_columns`/`categorical_columns` trong `DataDefinition` lấy
thẳng từ `features._numeric_and_categorical_columns(task_type)` — đã có sẵn, và
dùng lại thì định nghĩa cột không bị chép thành hai bản.

### 2.4. Agent: lõi Python + CLI, service trong compose tắt mặc định

Lõi là hàm thuần (sinh listing theo scenario, gọi `/predict`, gửi `/feedback`).
CLI bọc quanh để bắn từng lô có ranh giới rõ. Compose có service `agent` nhưng
khai báo `profiles: ["agent"]` nên **mặc định không chạy** —
`docker compose up` không đụng tới nó, chỉ `docker compose --profile agent up -d`
mới bật.

Vì sao lõi phải là hàm chứ không phải chỉ một container chạy liên tục:

- Kịch bản cần **ranh giới**. "Bắn đúng 500 request rồi dừng" là thứ đo được;
  một container chạy mãi thì không, trừ khi viết thêm API điều khiển nó.
- Traffic hai kịch bản **trộn vào nhau** trong cùng cửa sổ thời gian thì report
  ra `warning` mà không quy được cho kịch bản nào — đúng thứ đang muốn kiểm
  chứng thì lại không kết luận được.
- Test "`none` phải ra `ok`" gọi thẳng hàm được, không phải bật container rồi đợi.

Có cả hai thì không mất gì: service chỉ là vòng lặp gọi lại đúng hàm đó.

### 2.5. `price_inflation` và `market_rally` — hai kịch bản, một bài học đã đổi sau khi đo

Cả hai đều lấy **dòng có thật** trong dữ liệu rồi bóp méo `list_price`, đẩy
giá niêm yết lên ~20%. Khác nhau ở đúng một chỗ: `price_inflation` giữ
nguyên giá bán thật báo về `/feedback`; `market_rally` cũng nhân giá bán
thật lên ~20%, cùng hệ số. **Thiết kế này — hai kịch bản chỉ khác nhau ở
việc đáp án có đi theo feature hay không — vẫn đúng**, và tách ba loại drift
ra báo riêng vẫn đúng. Cái sai nằm ở dự đoán kết quả và lý do đưa ra cho nó,
không nằm ở thiết kế kịch bản.

**Dự đoán ban đầu — đã sai, đo được ở Task 11.** Bản nháp đầu của mục này có
một bảng ví dụ bằng số: niêm yết $400.000 → $480.000 sau khi bóp méo, ngụ ý
model đổi dự đoán theo (ước tính ~$500.000). **Model không đổi dự đoán một
chút nào.** `list_price` bị loại khỏi `feature_columns("regression")` vì là
leakage (mục 5 của `mlops-pipeline-design.md`: giữ lại thì
`sale_price ≈ list_price` khiến bài toán tầm thường), nên `SelectColumns`
cắt cột đó trước khi tới model — và trước khi tới phép so drift — nên bóp
méo `list_price` không chạm được vào đâu cả. Đo thật: `price_inflation` ra
kết quả **byte-identical** với `scenario=none` (feature `ok`, prediction
`ok`, rmse 101835.89 = rmse của `none`); `market_rally` ra performance drift
thật (rmse ratio 2.24) với feature drift **`ok`** — không phải "feature kêu,
performance im" như bản nháp viết, mà ngược lại hoàn toàn.

**Vì sao dự đoán sai: chưa kiểm tra `list_price` có phải feature không.**
Bản nháp viết kịch bản theo trực giác thị trường (giá niêm yết ảnh hưởng tới
model), mà không đối chiếu với mục 5 của tài liệu gốc, nơi đã ghi rõ
`list_price` bị loại khỏi feature của regression. Một dòng kiểm tra
`"list_price" in feature_columns("regression")` trước khi viết kịch bản đã
đủ bắt lỗi này trước khi có dòng code nào được viết.

**Bài học thật, sau khi đo, là thứ được giữ lại — không phải bị bỏ:**

- `price_inflation` — **drift ở một cột model không nhìn thấy không phải là
  drift.** Một kết quả âm tính hữu ích: chứng minh hệ thống không báo động
  giả chỉ vì một cột bất kỳ trong dữ liệu thô đổi giá trị.
- `market_rally` — **performance có thể sập trong khi feature drift bằng
  KHÔNG.** Đây là ảnh gương của bài học dự định ban đầu, và nếu có khác thì
  là bằng chứng còn mạnh hơn cho việc báo cáo ba loại drift tách riêng: một
  badge feature drift xanh không có nghĩa là model ổn.
- `market_shift` — kịch bản **thật sự** thử được feature drift, vì nó bóp
  méo `city`, một feature model có nhìn thấy. `price_inflation`/
  `market_rally` không làm được việc này; đây là lý do `market_shift` giữ
  vai trò "ca chứng minh feature drift kêu thật", không phải `market_rally`
  như bản nháp ban đầu dự đoán.

`market_rally` là kịch bản **không có trong §7.7**, thêm ở plan này. Lý do
thêm nó vẫn đúng dù kết quả đảo chiều so với dự đoán: nó là bằng chứng sống
cho câu "phân biệt ba loại drift là phần đáng học nhất" của §7.8. Nếu mọi
kịch bản mà feature drift kêu thì performance cũng kêu (hoặc ngược lại), thì
tách ba loại ra chẳng để làm gì. Phải có ít nhất một ca chứng minh **dữ liệu
đổi không đồng nghĩa với model hỏng, và dữ liệu không đổi không đồng nghĩa
với model ổn** — nếu không, phản xạ đúng sẽ là "thấy feature drift thì
retrain", và đó là phản xạ sai theo cả hai chiều.

**Câu hỏi mở cho plan sau (mục 10):** có nên đổi cột mà
`price_inflation`/`market_rally` bóp méo sang một feature thật (ví dụ
`living_area_sqft`, `school_rating`) để hai kịch bản này thật sự thử được
feature drift? **Bỏ `list_price` khỏi danh sách leakage không phải câu trả
lời** — mục 5 của tài liệu gốc đã giải thích rõ vì sao loại nó, và đảo quyết
định đó chỉ để "sửa" kết quả của một kịch bản demo là phá vỡ lý do thiết kế
của Plan 2.

Năm kịch bản:

| Scenario | Bóp méo | Đáp án | Dùng để |
| --- | --- | --- | --- |
| `none` | không | thật | Bắt false positive |
| `price_inflation` | `list_price` ×1.2 | **giữ nguyên** | No-op có chủ ý — `list_price` không phải feature, đo được `ok` giống hệt `none` |
| `market_rally` | `list_price` ×1.2 | **×1.2** | Performance drift với feature drift bằng không |
| `market_shift` | dồn `city` về 1–2 thành phố | thật | Ca thật sự thử feature drift (`city` là feature) |
| `new_segment` | `property_type` giá trị chưa từng thấy | thật | Serving không được sập |

### 2.6. Chưa đủ ground truth thì phải nói ra, không được báo `ok`

Performance drift **luôn đến trễ** (§7.8): lúc agent hỏi giá một căn nhà, chưa
ai biết nó bán được bao nhiêu.

Nên trong report, performance drift có **ba trạng thái chứ không phải hai**:
`ok`, `warning`/`high`, và `insufficient_data`. Dưới
`MONITOR_MIN_GROUND_TRUTH` (mặc định 50) dòng join được thì trả
`insufficient_data`.

Báo `ok` khi chưa đo được là nói dối, và là kiểu nói dối nguy hiểm nhất ở đây:
badge xanh trên dashboard trong khi thực tế là **chưa ai kiểm tra**.

Mức độ tổng hợp bỏ qua `insufficient_data` khi lấy max, nhưng trường đó vẫn
hiện nguyên trong JSON để Plan 5 hiển thị "chưa đủ dữ liệu" thay vì dấu xanh.

### 2.7. `monitoring_dag` tạo ra ở trạng thái paused

§6.2 nói `schedule="@hourly"` và đây là DAG duy nhất tự chạy. Giữ nguyên lịch,
nhưng đặt `is_paused_upon_creation=True`.

Máy dev 16GB đang chạy Airflow + Postgres + MinIO + MLflow + serving. Một DAG
nổ mỗi giờ trong nền, mỗi lần kéo Evidently và 10.000 dòng reference, là thứ
người ta quên mất rồi tự hỏi sao máy chậm. Bật tay khi cần; lúc migrate lên
MWAA thì bỏ cờ này.

### 2.8. `/feedback` nhận cả lô, và ngày do agent cung cấp

`POST /feedback/{task_type}` nhận **một danh sách** kết quả, không phải một.
Một lần gọi thành một file parquet — nếu mỗi căn một request thì `ground-truth/`
sẽ đầy file tí hon, đúng vấn đề mà Plan 3 đã tránh cho inference log.

Mỗi phần tử mang `predicted_on` (ngày agent đã gọi `/predict`). Serving phân
mảnh `ground-truth/` theo ngày đó, **không phải ngày nhận feedback** — có vậy
nó mới nằm cùng mảnh với inference log để join được.

Vì sao agent cung cấp ngày mà không phải serving tự tra: serving không có bảng
tra `request_id → ngày`, và dựng một bảng như vậy chỉ để phục vụ join là thêm
trạng thái vào một service đang cố ở trạng thái tối thiểu. Agent biết sẵn vì
chính nó vừa gọi. Đổi lại, `/predict` **không phải đổi gì** — giữ nguyên cam kết
không đụng vào code Plan 3.

---

## 3. API endpoint mới

### `POST /feedback/{task_type}`

Body:

```json
{
  "outcomes": [
    {"request_id": "3f0a...", "predicted_on": "2026-09-20", "actual": 420000.0},
    {"request_id": "9c1d...", "predicted_on": "2026-09-20", "actual": 385000.0}
  ]
}
```

`actual` là số (regression) hoặc bool (classification).

Trả về:

```json
{"accepted": 2, "key": "ground-truth/house_price_regressor/dt=2026-09-20/part-1a2b3c4d.parquet"}
```

Nhiều `predicted_on` khác nhau trong một lô thì ghi thành nhiều file, mỗi ngày
một file — cùng cách `write_batch` của inference log đang gom theo
`(model_name, day)`.

Lỗi:

- `422` — `task_type` không hợp lệ (FastAPI tự chặn), hoặc `outcomes` rỗng.
- `503` — chưa có champion cho task đó, nên không biết ghi dưới tên model nào.

Ghi thẳng, **không qua buffer**. Feedback đã theo lô sẵn và tần suất thấp; thêm
một buffer nữa chỉ để gom cái đã gom rồi là thừa.

---

## 4. Ba loại drift và luật quy ra mức độ

| Loại | Reference | Current | Preset |
| --- | --- | --- | --- |
| Feature | feature của mẫu train (≤10k dòng) | `raw_input` giải mã từ inference log | `DataDriftPreset` |
| Prediction | prediction của champion **chạy lại trên chính mẫu train đó** | cột `prediction` trong log | `DataDriftPreset` trên 1 cột |
| Performance | metric lúc train, đọc từ MLflow run | metric tính trên phần join được ground truth | tự tính qua `metrics.compute_metrics` |

Prediction reference phải chạy model trên mẫu train tại thời điểm monitoring —
train không log lại phân phối prediction. Vì reference đã giới hạn 10.000 dòng
nên chi phí này chấp nhận được.

`raw_input` trong inference log là chuỗi JSON (Plan 3 ghi
`json.dumps(record, default=str)`), nên `drift.py` phải `json.loads` từng dòng
rồi dựng lại DataFrame trước khi đưa cho Evidently.

### Ngưỡng đề xuất

| Loại | `ok` | `warning` | `high` |
| --- | --- | --- | --- |
| Feature | tỉ lệ cột drift < 0.3 | 0.3 – 0.5 | > 0.5 |
| Prediction | không drift | — | có drift |
| Performance (regression) | `rmse` hiện tại / `rmse` train < 1.2 | 1.2 – 1.5 | > 1.5 |
| Performance (classification) | `auc` giảm < 0.05 | 0.05 – 0.10 | > 0.10 |

Tổng hợp = mức cao nhất trong ba, bỏ qua `insufficient_data`.

**Những con số này là điểm khởi đầu, không phải kết luận.** Giống ghi chú ở §13
về ngưỡng R²/F1, phải hiệu chỉnh sau lần chạy thật đầu tiên — cụ thể là sau khi
chạy `none` và xem tỉ lệ cột drift thực tế là bao nhiêu khi **không** có drift.
Nếu `none` đã ra 0.25 thì ngưỡng 0.3 là quá sát.

---

## 5. Cấu trúc thư mục mới

```
common/ml_common/
  drift.py                  # gom cua so, join, luat muc do (thuan pandas)

services/agent/
  __init__.py
  scenarios.py              # 5 kich ban bop meo
  runner.py                 # loi: sinh listing, goi /predict, gui /feedback
  __main__.py               # CLI
  Dockerfile
  tests/
    test_scenarios.py
    test_runner.py

stages/monitor/
  Dockerfile                # FROM ml-base + evidently
  main.py

dags/
  monitoring_dag.py

common/tests/
  test_drift.py
```

`storage.py` thêm hai hàm key (giữ đúng ràng buộc "chỉ file này biết đường dẫn"):

- `drift_summary_key(model_name, run_id)` → `reports/{model}/{run_id}/summary.json`
- `drift_latest_key(model_name)` → `reports/{model}/latest.json`

`latest.json` là bản sao của summary mới nhất, ghi đè mỗi lần. Có nó thì Plan 5
trả `/api/drift/latest` bằng một lần đọc, không phải liệt kê cả thư mục rồi so
thời gian.

---

## 6. Thay đổi trong code đã có

Chủ trương: **Plan 2 không bị đụng tới**. Sáu stage và `ml_pipeline` giữ nguyên.

| File | Thay đổi | Vì sao |
| --- | --- | --- |
| `common/ml_common/storage.py` | Thêm 2 hàm key ở mục 5 | Ràng buộc kiến trúc: đường dẫn chỉ được tạo ở đây |
| `services/serving/app.py` | Thêm route `POST /feedback/{task_type}`; ghi thêm `probability` vào inference log | Endpoint mới; performance drift của classification chấm bằng AUC, mà AUC không tính được từ một bool |
| `docker-compose.yml` | Thêm service `agent` với `profiles: ["agent"]` | Chế độ chạy liên tục, tắt mặc định |
| `scripts/build_stage_images.ps1` | Thêm `ml-monitor` | Image mới |
| `CLAUDE.md` | Cập nhật lệnh build và trạng thái | Đã có tiền lệ |

`register/main.py` **không đổi**. Đó là hệ quả trực tiếp của quyết định 2.1 —
chọn đọc lại tập train chính vì nó không bắt sửa stage đang chạy ổn.

---

## 7. Test

| Tầng | Test gì | Chạy ở đâu |
| --- | --- | --- |
| `test_drift.py` | Luật quy mức độ với số liệu dựng sẵn; join `request_id`; `insufficient_data` khi dưới ngưỡng; cửa sổ vắt qua hai ngày | Máy dev, không cần Evidently |
| `test_scenarios.py` | Mỗi scenario bóp méo đúng cột; `price_inflation` giữ nguyên đáp án còn `market_rally` thì không; `none` không đổi gì | Máy dev |
| `test_runner.py` | Agent gọi đúng endpoint, gom feedback theo lô, `predicted_on` đúng ngày gọi `/predict` | Máy dev, HTTP giả lập |
| `test_app.py` (thêm) | `/feedback` ghi đúng key, chia file theo ngày, 503 khi chưa có champion, 422 khi lô rỗng | Máy dev |
| `scripts/verify_monitoring.ps1` | Chạy thật 4 kịch bản, kiểm mức độ ra đúng bảng ở mục 8 | Cần stack chạy |

`test_drift.py` cố tình không cần Evidently — đó là lý do luật mức độ nằm ở
`drift.py` chứ không nằm trong `monitor/main.py`.

---

## 8. Definition of Done

1. `pytest common/ services/` xanh ở cả Python 3.13 (máy, 357 test) lẫn 3.12 (container).
2. `ruff check .` sạch.
3. `ml-monitor:latest` build được.
4. Agent bắn được vào serving đang chạy; `/health` cho thấy `buffered` tăng.
5. `/feedback` ghi được, và file rơi vào đúng mảnh `dt=` của ngày dự đoán.
6. `monitoring_dag` chạy tay xong cả 2 task (một task mỗi model, mỗi task một
   container `ml-monitor` — xem mục 9), ghi được HTML + JSON lên MinIO.
7. **Finding A. Bảng kịch bản dưới đây là số đo thật từ Task 11, không phải
   bảng dự đoán viết tay ở bản nháp đầu của mục này.** Bảng nháp đầu tiên sai ở
   `price_inflation` và `market_rally` — không phải vì hệ thống đo sai, mà vì
   bảng dự đoán chưa tính tới việc `list_price` là cột bị loại khỏi feature
   của regression (leakage, mục 5). Đây là chỗ plan này chứng minh mình có
   giá trị: một hệ thống drift luôn báo `high` vô dụng ngang một hệ thống
   luôn báo `ok`, và phải đo thật — không phải đoán trước — mới biết bảng
   nào đúng:

| Chạy | Feature | Prediction | Performance | Tổng hợp | Bài học |
| --- | --- | --- | --- | --- | --- |
| `none` | `ok` (tỉ lệ cột drift 0.0909, 2/22) | `ok` | `ok` | **`ok`** | Control cho false positive — nhưng đọc mục 10: `zipcode` tự trôi JS distance 0.825 ngay cả ở đây, control không sạch tuyệt đối |
| `price_inflation` | `ok` (giống hệt `none` tới từng bit) | `ok` | `ok` (rmse ratio 1.14) | **`ok`** | **Drift ở một cột model không nhìn thấy không phải là drift.** `list_price` bị loại khỏi `feature_columns("regression")` vì leakage; bóp méo nó không chạm tới model lẫn phép so drift — RMSE ra byte-identical với `none` |
| `market_rally` | `ok` (giống hệt `none`) | `ok` | **`high`** (rmse ratio 2.24) | **`high`** | **Performance có thể sập trong khi feature drift = 0.** Đây là bằng chứng mạnh nhất cho việc tách ba loại drift ra báo riêng — nhìn riêng feature drift, `market_rally` trôi qua như không có gì xảy ra |
| `market_shift` | `warning` (luật magnitude — xem mục 4) | `high` | `high` | **`high`** | Kịch bản duy nhất trong năm kịch bản thật sự thử được feature drift, vì nó bóp méo `city` — một cột model **có** nhìn thấy. Luật tỉ lệ cột drift một mình không thấy điều này (2/22 = 0.0909, y hệt `none`); phải có luật magnitude mới bắt được |
| `new_segment` | `warning` | `ok` | `warning` | warning | Serving **không sập** (không có HTTP 500) — đây là điều kiện thật của hàng này, không phải một mức độ cụ thể |

8. Chạy khi chưa có ground truth (feedback-ratio=0) phải ra `insufficient_data`
   ở performance, không ra `ok`. Đo thật: tổng hợp `high` (do `prediction=high`,
   một artefact của mẫu nhỏ 100 dòng làm test thống kê per-column của Evidently
   nhiễu hơn), còn `performance=insufficient_data` đúng như yêu cầu.

Chi tiết đầy đủ — số đo từng lần chạy, cách cô lập cửa sổ theo timestamp, bảng
per-column Jensen-Shannon/Wasserstein — ở
`docs/superpowers/specs/2026-09-20-plan4-monitoring-measurements.md`. Không đề
xuất bỏ `list_price` khỏi leakage của regression để "sửa" bảng cũ — mục 5 của
tài liệu gốc đã giải thích rõ vì sao loại nó (giữ lại thì bài toán tầm
thường). Câu hỏi mở cho plan sau ở mục 10.

---

## 9. Chỗ tài liệu này lệch khỏi `mlops-pipeline-design.md`

| Chỗ | Tài liệu gốc | Plan 4 | Lý do |
| --- | --- | --- | --- |
| §7.8 | Baseline là profile, **không phải dataset** | Evidently ăn tập train đọc lại; profile vẫn giữ cho Plan 5 | Evidently chỉ nhận DataFrame — xem 2.1 |
| §7.7 | 4 scenario | 5, thêm `market_rally` | Thêm để chứng minh dữ liệu đổi không đồng nghĩa model hỏng; đo thật cho kết quả ngược lại — performance sập với feature drift bằng không — càng củng cố lý do tách ba loại drift ra báo riêng, xem 2.5 |
| §6.2 | `schedule="@hourly"` | Giữ lịch, thêm `is_paused_upon_creation=True` | Máy dev 16GB — xem 2.7 |
| §7.8 | Mức độ `ok`/`warning`/`high` | Thêm `insufficient_data` cho performance | Không báo xanh khi chưa đo — xem 2.6 |
| §7.7 | Agent gửi feedback "sau N ngày mô phỏng" | Agent gửi theo lệnh, mang theo `predicted_on` | Độ trễ thật thì không demo được; độ trễ vẫn hiện ra vì hai lệnh tách rời |
| §6.2 | 3 task `collect_window`/`run_evidently`/`publish_report` | 1 task mỗi model (`house_price_regressor`, `house_needs_renovation_classifier`), mỗi task 1 container `ml-monitor` làm hết cả ba việc | XCom chỉ chuyền được giá trị nhỏ; 3 task sẽ phải đọc lại cửa sổ 3 lần — xem Task 10 |
| §7.6 | Inference log: `request_id`, `timestamp`, `raw_input`, `prediction`, `model_name`, `model_version` | Thêm `probability` | Performance drift của classification chấm bằng AUC, không tính được từ một bool — xem mục 6 |
| §8 (bảng kịch bản) | `price_inflation` phải ra `high`; `market_rally` phải ra `feature=warning/high, performance=ok` | Đo thật: `price_inflation` ra `ok` (giống hệt `none`); `market_rally` đảo ngược — `feature=ok`, `performance=high` | `list_price` bị loại khỏi feature của regression (leakage, mục 5 tài liệu gốc); cả hai kịch bản chỉ bóp méo đúng cột đó — xem mục 8 (Finding A) |
| §4 (ngưỡng feature drift) | Một luật duy nhất: tỉ lệ cột drift | Thêm luật thứ hai (magnitude — cộng dồn `value − threshold` trên mọi cột so sánh được), lấy mức nặng hơn giữa hai luật | Luật tỉ lệ mù trước drift dồn vào 1-2 cột: `market_shift` lệch `city` (Jensen-Shannon 0.7754, ngưỡng 0.1) mà tỉ lệ vẫn 2/22 = 0.0909, y hệt `none` → báo `ok` sai — xem mục 10 (Finding B) |

Chín dòng trên. Bảy dòng đầu đã được vá ngược vào `mlops-pipeline-design.md`
ở Task 12, cùng cách Plan 3 đã vá §5. Hai dòng cuối — bảng kịch bản theo đo
thật và luật magnitude cho feature drift — **không** vá lại, vì tài liệu gốc
không có bảng kỳ vọng theo kịch bản hay bảng ngưỡng số ở cấp chi tiết đó để
vá; cả hai là phát hiện mới, chỉ sống trong tài liệu spec này (mục 8, mục
10). Vá sau chứ không vá trước, vì tới lúc đó mới biết ngưỡng thật và cỡ cửa
sổ thật là bao nhiêu.

---

## 10. Câu hỏi còn mở

- **Ngưỡng ở mục 4 — đã đo thật ở Task 11, không cần hiệu chỉnh lại.** `none`
  đo được tỉ lệ cột drift 0.0909 (2/22), nằm sâu dưới ngưỡng `warning` 0.3;
  `FEATURE_WARNING_SHARE`, `FEATURE_HIGH_SHARE`, `RMSE_WARNING_RATIO`,
  `RMSE_HIGH_RATIO`, `MIN_GROUND_TRUTH` đều giữ nguyên giá trị đoán ở Task 4.
  Nhưng đo thật cũng lộ ra một lỗ hổng mà ngưỡng tỉ lệ cột một mình không
  thấy — xem điểm tiếp theo.
- **Finding B — `feature_severity` giờ có hai đường, và đường thứ hai được
  hiệu chỉnh trên một control bị nhiễm.** `market_shift` (dồn `city` về 1-2 thành phố)
  đo được Jensen-Shannon distance của `city` là 0.7754 so với ngưỡng
  per-column 0.1 — lệch gần 8 lần — nhưng luật chỉ-nhìn-tỉ-lệ-cột-drift cũ
  vẫn báo `ok`, vì chỉ 2/22 = 0.0909 cột vượt ngưỡng, y hệt tỉ lệ đo được ở
  `none`. Đã thêm một luật thứ hai — `sum(value − threshold)` cộng dồn trên
  toàn bộ cột Evidently so sánh được, cảnh báo khi `>= 0.0` — và
  `feature_severity` lấy mức nặng hơn giữa hai luật (`market_shift`:
  `none` = `-0.2844`, `market_shift` = `+0.3901`). Ba điểm yếu đã biết, ghi
  lại ở đây thay vì chỉ nằm trong code comment:
  - **(a) Luật magnitude cộng dồn trên toàn bộ cột, nên phụ thuộc số chiều.**
    Cùng kiểu điểm yếu với luật tỉ lệ mà nó bổ sung: càng nhiều cột, càng
    nhiều "khoảng trống âm" (cột không drift, `value − threshold` âm) có thể
    nuốt mất tín hiệu của một cột lệch nặng.
  - **(b) Đường `0.0` là chỗ hai mẫu đo tình cờ rơi vào, không phải một con
    số có nguyên lý.** Cả hai margin (0.284 và 0.390) đều thoải mái so với
    biên độ dao động 0.674 giữa hai lần đo, nhưng đường phân cách vẫn chỉ
    dựa trên đúng hai điểm đo, chưa có một quy tắc thống kê đứng sau.
  - **(c) `scenario=none` không phải một control sạch.** `zipcode` tự trôi
    Jensen-Shannon distance 0.825 — gấp tám lần ngưỡng phát hiện 0.1 — ngay
    cả khi không áp scenario nào, ở mọi lần chạy. Nguyên nhân: agent lấy
    mẫu ở **đuôi** dataset theo `listing_date` (đúng như bullet "Pool dữ
    liệu của agent" bên dưới đã dự đoán), trong khi model train trên
    `head(SAMPLE_ROWS)` — hai slice khác nhau của cùng một dataset. Bất kỳ
    ngưỡng nào hiệu chỉnh dựa trên `none` đều thừa hưởng sự nhiễm này. Đây
    là lỗi của **bộ đo, không phải của drift detector**: toàn bộ khoảng
    cách 0.674 phân tách hai lần chạy phía trên đến từ đúng một cột —
    `city` — không phải `zipcode` (cột này gần như giống hệt nhau ở cả hai
    lần đo, 0.825054 cả hai, vì cùng seed 42 nên cùng tập giá trị zipcode
    thật). Số liệu per-column đầy đủ ở
    `docs/superpowers/specs/2026-09-20-plan4-monitoring-measurements.md`, mục
    "Addendum 2".
- **Race khi flush buffer của inference log — chưa fix trong code.** Chạy
  `monitor` ngay sau một lô agent có thể bắt trúng lúc buffer mới flush được
  một phần (`InferenceLogBuffer` flush theo kích thước hoặc tuổi, qua một
  task nền chạy "khoảng mỗi giây", nhưng dưới một đợt 500 request đồng bộ có
  thể trễ). Quan sát được một lần: `n_predictions=33` ngay sau một lô 500
  request, rồi `/health` báo `buffered:0` vài giây sau khi flush kịp. Vòng
  qua được bằng thao tác tay trong suốt Task 11 — poll `GET /health` tới khi
  `inference_log.buffered == 0` trước khi gọi monitor — nhưng chưa sửa trong
  code. Có thể ảnh hưởng tới các lần chạy theo lịch của `monitoring_dag`, vì
  lúc đó không có ai đứng poll `/health` hộ.
- **Cỡ cửa sổ.** Đề xuất mặc định 24 giờ (`MONITOR_WINDOW_HOURS`) dù DAG chạy
  mỗi giờ, vì traffic bắn tay có thể để trống nhiều giờ liền. Nếu sau này có
  agent chạy liên tục thì rút xuống.
- **Pool dữ liệu của agent.** Agent lấy các dòng mới nhất theo `listing_date`
  trong raw. Khi `SAMPLE_ROWS=200000`, `extract` lấy `head(200000)` nên phần
  đuôi là dữ liệu model chưa từng thấy — đúng ý. Khi chạy full 2 triệu dòng thì
  không còn phần nào chưa thấy, và drift lúc đó hoàn toàn do scenario tạo ra.
  Chấp nhận được, nhưng phải ghi rõ để sau này không ai hiểu nhầm là agent luôn
  gửi dữ liệu lạ. **Đo thật xác nhận dự đoán này, và nó chính là nguồn nhiễm
  của control `none` — xem điểm (c) ở trên.**
- **Đọc raw 373MB trong container agent.** Với 200k dòng thì thoải mái. Với 2
  triệu dòng cần đọc theo row group thay vì `read_parquet` cả file. Để
  implementation plan xử lý.
- **Finding A — `price_inflation`/`market_rally` chỉ bóp méo `list_price`,
  một cột bị loại khỏi feature của regression (leakage).** Đo thật (Task 11): cả hai
  kịch bản ra kết quả feature/prediction giống hệt `none` —
  `price_inflation` giống `none` tới cả RMSE. Đây **không phải bug** — hệ
  thống đúng theo đúng nghĩa "model không nhìn thấy cột thì không thể drift
  theo cột đó". Không đề xuất bỏ `list_price` khỏi leakage của regression để
  "sửa" kết quả này — mục 5 của tài liệu gốc đã giải thích rõ vì sao loại nó
  (giữ lại thì bài toán trở nên tầm thường). Câu hỏi để ngỏ cho plan sau: có
  nên đổi cột mà `price_inflation`/`market_rally` bóp méo (ví dụ
  `living_area_sqft`, `school_rating`) để hai kịch bản đó thật sự thử được
  feature drift, thay vì chỉ `market_shift` làm việc đó? Xem mục 8, Finding
  A.
