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
"`none` ra `ok`, `price_inflation` ra `high`". Tách đôi thì nửa đầu chỉ chứng
minh được "record có rơi xuống MinIO", còn nửa sau không có gì để đo.

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

### 2.5. `price_inflation` và `market_rally` — hai kịch bản, hai bài học

Cả hai đều lấy **dòng có thật** trong dữ liệu rồi bóp méo feature. Khác nhau ở
chỗ **có bóp méo luôn đáp án không**.

Lấy một nhà thật: niêm yết $400.000, bán thật $420.000. Áp hệ số 1.2:

| Kịch bản | Gửi vào `/predict` | Báo về `/feedback` | Model đoán | Hệ quả |
| --- | --- | --- | --- | --- |
| `price_inflation` | niêm yết $480.000 | **$420.000** (giữ nguyên) | ~$500.000 | lệch $80.000 |
| `market_rally` | niêm yết $480.000 | **$504.000** (×1.2) | ~$500.000 | lệch $4.000 |

Hai hiện tượng thị trường khác nhau:

- `price_inflation` — người bán đua nhau hét giá, giá bán thật không nhúc nhích.
  Model tin giá niêm yết nên bị lừa. **Cả ba loại drift đều kêu.**
- `market_rally` — cả thị trường lên đều, niêm yết lên thì giá bán cũng lên.
  Model vẫn đúng tương đối. **Feature drift kêu, performance drift im.**

`market_rally` là kịch bản **không có trong §7.7**, thêm ở plan này. Lý do: nó
là bằng chứng sống cho câu "phân biệt ba loại drift là phần đáng học nhất" của
§7.8. Nếu mọi kịch bản mà feature drift kêu thì performance cũng kêu, thì tách
ba loại ra chẳng để làm gì. Phải có ít nhất một ca chứng minh **dữ liệu đổi
không đồng nghĩa với model hỏng** — nếu không, phản xạ đúng sẽ là "thấy feature
drift thì retrain", và đó là phản xạ sai.

Năm kịch bản:

| Scenario | Bóp méo | Đáp án | Dùng để |
| --- | --- | --- | --- |
| `none` | không | thật | Bắt false positive |
| `price_inflation` | `list_price` ×1.2 | **giữ nguyên** | True positive, cả 3 loại |
| `market_rally` | `list_price` ×1.2 | **×1.2** | Feature drift vô hại |
| `market_shift` | dồn `city` về 1–2 thành phố | thật | Drift trên cột categorical |
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
| `services/serving/app.py` | Thêm route `POST /feedback/{task_type}` | Endpoint mới |
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

1. `pytest common/ services/` xanh ở cả Python 3.13 (máy) lẫn 3.12 (container).
2. `ruff check .` sạch.
3. `ml-monitor:latest` build được.
4. Agent bắn được vào serving đang chạy; `/health` cho thấy `buffered` tăng.
5. `/feedback` ghi được, và file rơi vào đúng mảnh `dt=` của ngày dự đoán.
6. `monitoring_dag` chạy tay xong cả 3 task, ghi được HTML + JSON lên MinIO.
7. **Bảng kịch bản dưới đây đúng hết** — đây là điều kiện thật sự của plan này:

| Chạy | Feature | Prediction | Performance | Tổng hợp |
| --- | --- | --- | --- | --- |
| `none` | `ok` | `ok` | `ok` | **`ok`** |
| `price_inflation` | `high` | `high` | `high` | **`high`** |
| `market_rally` | `warning`/`high` | `warning`/`high` | **`ok`** | warning/high |
| `new_segment` | drift ở `property_type` | — | — | serving **không sập** |

8. Chạy `monitoring_dag` khi chưa có ground truth phải ra `insufficient_data`
   ở performance, không ra `ok`.

Điểm 7 là chỗ plan này chứng minh mình có giá trị. Một hệ thống drift luôn báo
`high` cũng vô dụng ngang một hệ thống luôn báo `ok`; phải qua được cả dòng
`none` lẫn dòng `price_inflation` thì mới nói được là nó đo thật.

---

## 9. Chỗ tài liệu này lệch khỏi `mlops-pipeline-design.md`

| Chỗ | Tài liệu gốc | Plan 4 | Lý do |
| --- | --- | --- | --- |
| §7.8 | Baseline là profile, **không phải dataset** | Evidently ăn tập train đọc lại; profile vẫn giữ cho Plan 5 | Evidently chỉ nhận DataFrame — xem 2.1 |
| §7.7 | 4 scenario | 5, thêm `market_rally` | Cần một ca chứng minh feature drift vô hại — xem 2.5 |
| §6.2 | `schedule="@hourly"` | Giữ lịch, thêm `is_paused_upon_creation=True` | Máy dev 16GB — xem 2.7 |
| §7.8 | Mức độ `ok`/`warning`/`high` | Thêm `insufficient_data` cho performance | Không báo xanh khi chưa đo — xem 2.6 |
| §7.7 | Agent gửi feedback "sau N ngày mô phỏng" | Agent gửi theo lệnh, mang theo `predicted_on` | Độ trễ thật thì không demo được; độ trễ vẫn hiện ra vì hai lệnh tách rời |

Cả năm dòng nên được vá ngược vào `mlops-pipeline-design.md` sau khi Plan 4
chạy xong, cùng cách Plan 3 đã vá §5. Vá sau chứ không vá trước, vì tới lúc đó
mới biết ngưỡng thật và cỡ cửa sổ thật là bao nhiêu.

---

## 10. Câu hỏi còn mở

- **Ngưỡng ở mục 4 chưa hiệu chỉnh.** Phải chạy `none` trước rồi mới chốt.
- **Cỡ cửa sổ.** Đề xuất mặc định 24 giờ (`MONITOR_WINDOW_HOURS`) dù DAG chạy
  mỗi giờ, vì traffic bắn tay có thể để trống nhiều giờ liền. Nếu sau này có
  agent chạy liên tục thì rút xuống.
- **Pool dữ liệu của agent.** Agent lấy các dòng mới nhất theo `listing_date`
  trong raw. Khi `SAMPLE_ROWS=200000`, `extract` lấy `head(200000)` nên phần
  đuôi là dữ liệu model chưa từng thấy — đúng ý. Khi chạy full 2 triệu dòng thì
  không còn phần nào chưa thấy, và drift lúc đó hoàn toàn do scenario tạo ra.
  Chấp nhận được, nhưng phải ghi rõ để sau này không ai hiểu nhầm là agent luôn
  gửi dữ liệu lạ.
- **Đọc raw 373MB trong container agent.** Với 200k dòng thì thoải mái. Với 2
  triệu dòng cần đọc theo row group thay vì `read_parquet` cả file. Để
  implementation plan xử lý.
