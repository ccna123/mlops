# Plan 2 — Batch Pipeline: Thiết kế

Ngày: 2026-09-19. Tiếp nối Plan 1 (Foundation) đã hoàn thành.

Tài liệu này là spec cho Plan 2. Nguồn sự thật gốc vẫn là
`mlops-pipeline-design.md`; chỗ nào tài liệu này lệch khỏi nó đều được ghi rõ ở
mục 9 kèm lý do, và `mlops-pipeline-design.md` sẽ được cập nhật cho khớp.

## 1. Phạm vi

**Trong phạm vi:** sáu stage `extract`, `validate`, `preprocess`, `train`,
`evaluate`, `register`, cộng DAG `ml_pipeline` chạy nhánh regression.

**Ngoài phạm vi, để lại cho Plan 3:** task `deploy`, `services/serving/`, nhánh
classification. Plan 4: monitoring. Plan 5: dashboard.

Dù Plan 2 chỉ chạy regression, không được hardcode `"regression"` ở chỗ nào mà
`task_type` làm được việc. Nhánh classification của Plan 3 phải là chuyện thêm
một giá trị tham số, không phải viết lại stage.

## 2. Quyết định kiến trúc

Sáu quyết định dưới đây định hình cả plan. Mỗi quyết định kèm cái giá của nó.

### 2.1. Airflow gọi stage bằng `DockerOperator`

Mỗi stage là một image riêng `FROM ml-base:latest`. Airflow không chạy code
pandas của dự án; nó chỉ bảo Docker daemon khởi container, chờ exit code, hút log
về.

**Lý do quyết định:** ràng buộc trong `CLAUDE.md` — model pickle bởi scikit-learn
chỉ load lại được bởi cùng minor version Python và cùng version scikit-learn.
Với `DockerOperator`, `train` chạy trong `ml-base` và serving ở Plan 3 cũng
`FROM ml-base` → hai bên khớp nhau **theo cấu trúc**, không phải nhờ kỷ luật. Với
`PythonOperator`, `train` sẽ chạy trong image Airflow còn serving trong
`ml-base`: hai image khác nhau phải tự giữ đồng bộ bằng tay, và lệch một bản vá
là model unpickle hỏng.

Lý do phụ: 2 triệu dòng pandas nằm trong scheduler mà OOM thì chết luôn Airflow
và mất metadata run; container stage chết một mình thì Airflow chỉ ghi nhận task
failed rồi đi tiếp.

**Giá phải trả:** phải mount docker socket vào scheduler, và traceback đi qua một
lớp log nữa.

**Đã kiểm chứng trên máy này** (spike ngày 2026-09-19, branch
`spike/docker-operator`), không phải giả định:

| Kiểm | Kết quả |
| --- | --- |
| Container stage gọi `minio:9000` / `mlflow:5000` qua hostname | 200 / 200 |
| Socket mount vào Airflow | `srw-rw---- root root`, SDK `ping: True` |
| `DockerOperator` khởi `ml-base` từ DAG | task SUCCESS, container in `ml_common 0.1.0` |

Công thức đã kiểm chứng, dùng nguyên cho Plan 2:

- Mount `//var/run/docker.sock:/var/run/docker.sock`. **Hai gạch đầu là bắt
  buộc** trên Windows, nếu không MSYS mangle đường dẫn thành `C:/Program Files/...`.
- `user: "50000:0"` sẵn có từ Plan 1 chính là thứ làm nó chạy: socket là
  `root:root` mode `660`, container thuộc group `0` nên đọc ghi được. Không cần
  chỉnh quyền gì thêm.
- `apache-airflow-providers-docker==3.14.0`.
- `network_mode="mlops_default"` — thiếu cái này thì container stage không phân
  giải được hostname `minio`.
- `auto_remove="success"` — chuỗi, không phải bool, ở provider 3.x.
- `mount_tmp_dir=False` — mặc định provider mount một tmp dir kiểu Linux, hỏng
  trên host Windows.
- Chỉ `airflow-scheduler` cần socket. `LocalExecutor` chạy task ngay trong
  scheduler, nên webserver không cần và không nên được cấp.

### 2.2. `preprocess` không làm sạch theo cột

Đây là quyết định phản trực giác nhất của plan, và là hệ quả trực tiếp của ràng
buộc kiến trúc số 1 và số 3 trong `CLAUDE.md`.

- `preprocess` **chỉ làm thao tác theo dòng**: `rowops.drop_duplicates`,
  `rowops.drop_rows_missing_target`, rồi split train/test.
- `processed/{fingerprint}/train.parquet` chứa dữ liệu **vẫn thô ở mức cột** —
  vẫn còn `"$450,000"`, vẫn còn `"NEW YORK"`, vẫn còn zipcode 4 số.
- Parse, chuẩn hoá text, clip outlier, impute, encode đều nằm trong
  `sklearn.Pipeline`, được fit lúc `train` và đóng gói cùng model vào MLflow.

**Lý do:** nếu `preprocess` làm sạch cột rồi lưu, model sẽ học trên dữ liệu đã
sạch, trong khi `/predict` ở Plan 3 nhận record thô. Đó chính là training/serving
skew mà cả thiết kế này dựng lên để tránh. Đặt toàn bộ logic cột trong Pipeline
khiến model tự chứa cách làm sạch của chính nó.

Cái tên `processed/` vì vậy có nghĩa hẹp: **đã xử lý theo dòng và đã chia tập**,
không phải "đã làm sạch".

### 2.3. Model Registry dùng alias, không dùng stage

`register` gắn alias `champion` vào version vừa tạo:
`client.set_registered_model_alias(name, "champion", version)`. `evaluate` và
serving load bằng `models:/{name}@champion`.

**Lý do:** MLflow 2.22 (bản đang chạy) đã deprecate model stage; MLflow 3 bỏ hẳn.
Dùng stage nghĩa là nhận nợ kỹ thuật ở đúng ba chỗ — `evaluate`, `register`, và
serving của Plan 3 — để đổi lấy việc bám đúng chữ trong spec cũ.

Alias cũng khớp từ vựng champion/challenger mà chính `mlops-pipeline-design.md`
mục 7.5 dùng khi mô tả cổng evaluate.

### 2.4. Raw data được seed một lần, ngoài DAG

`scripts/seed_raw_data.py` đọc `house_pricing_dirty.csv` ở đĩa local, ghi
`raw/v1/data.parquet` lên MinIO. Chạy tay một lần lúc setup.

**Lý do:** giữ `extract` đúng hợp đồng của nó — chỉ đọc từ object storage. Đó
cũng là cách hệ thống thật hoạt động: dữ liệu thô do hệ thống khác đổ vào, pipeline
không tự sinh ra nó. Nếu `extract` đọc CSV local thì khi migrate lên S3 phải viết
lại chính stage đó.

### 2.5. `SAMPLE_ROWS` được `extract` đọc, và nằm trong fingerprint

Seed đẩy đủ 2 triệu dòng lên MinIO một lần. `extract` đọc biến `SAMPLE_ROWS`:
có giá trị thì lấy `head(n)`, để trống thì lấy hết.

`SAMPLE_ROWS` **bắt buộc là một thành phần của fingerprint**. Thiếu nó, lần chạy
200k dòng sẽ ăn nhầm cache `processed/` của lần chạy 2 triệu dòng — và sai kiểu
này im lặng, model train trên tập khác tập mà người chạy tưởng.

### 2.6. Target log được xử lý bên trong Pipeline

Regression bọc estimator bằng
`TransformedTargetRegressor(regressor=estimator, func=np.log1p, inverse_func=np.expm1)`,
đặt **bên trong** Pipeline.

**Lý do:** spec mục 5 yêu cầu train trên `log(sale_price)` nhưng metric báo cáo
phải quy về đô la. Nếu nghịch đảo làm ở ngoài, thì `evaluate` phải biết nghịch
đảo, và serving ở Plan 3 cũng phải biết — hai bản logic phải giữ đồng bộ. Đặt bên
trong Pipeline thì `model.predict()` trả thẳng đô la và không ai ở hạ nguồn cần
biết chuyện gì đã xảy ra.

## 3. Luồng chạy

```
extract → validate → preprocess → train → evaluate → branch ─┬─ register
                                                             └─ stop_no_deploy
```

Dữ liệu giữa các stage đi qua **đường dẫn MinIO**, không qua XCom. XCom chỉ chở
giá trị nhỏ: fingerprint, run_id, metric, version.

Tham số DAG qua `dag_run.conf`: `task_type` (bắt buộc), `force_reprocess` (mặc
định `false`), `dataset_version` (mặc định `"v1"` — xem mục 9).

**Cơ chế XCom:** `DockerOperator` với `do_xcom_push=True` lấy **dòng cuối cùng
trên stdout** của container làm giá trị XCom. Vì vậy mỗi stage in đúng một dòng
JSON ở cuối, sau mọi log khác. Log của stage vẫn ra stdout bình thường; chỉ dòng
cuối mới được đọc làm giá trị.

## 4. Hợp đồng từng stage

Mỗi stage đọc cấu hình từ biến môi trường, ghi kết quả lên MinIO, in một dòng JSON
tóm tắt ra stdout để Airflow đẩy vào XCom.

| Stage | Đọc | Ghi | XCom ra |
| --- | --- | --- | --- |
| `extract` | `raw/{version}/data.parquet` | `extracted/{fp}/data.parquet` | `fingerprint`, `row_count` |
| `validate` | `extracted/{fp}/data.parquet` | `reports/validation/{fp}.json` | `ok` |
| `preprocess` | `extracted/{fp}/data.parquet` | `processed/{fp}/{train,test}.parquet` | `skipped` |
| `train` | `processed/{fp}/train.parquet` | MLflow run + model | `run_id` |
| `evaluate` | `processed/{fp}/test.parquet` | metric vào cùng run | `passed`, metrics |
| `register` | `processed/{fp}/train.parquet` | alias + `monitoring-baseline/{name}/{v}/profile.json` | `version` |

### 4.1. `extract`

Fingerprint = `sha256(dataset_version + ETag_của_raw_object + str(sample_rows))`.

Dùng ETag thay vì hash nội dung: ETag của MinIO đã đổi khi object đổi, nên không
cần đọc và băm 2 triệu dòng chỉ để biết dữ liệu có thay đổi hay không.

### 4.2. `validate`

Fail pipeline đúng ba trường hợp — dữ liệu vô dụng, không phải dữ liệu bẩn:

1. Thiếu cột so với `schema.COLUMNS`.
2. Hơn 50% giá trị target bị thiếu.
3. Số dòng bằng 0.

Mọi thứ khác — missing rate từng cột, số outlier ngoài bound của schema, zipcode
sai định dạng, số dòng trùng — chỉ **đếm và ghi vào report**. `preprocess` và
`Pipeline` dọn chúng ở bước sau.

**Lý do ngưỡng lỏng:** dataset này cố tình dirty; 8 loại lỗi là bài tập chứ không
phải sự cố. Ngưỡng chặt sẽ chặn mọi lần chạy. Điều này khớp với quy ước
"parser không bao giờ đoán, trả `None` để `validate` đếm được" trong `CLAUDE.md`:
vai trò của `validate` là **đo và báo cáo**, không phải gác cổng đạo đức dữ liệu.

### 4.3. `preprocess`

Đầu task kiểm tra cache: nếu `processed/{fp}/train.parquet` và `test.parquet` đều
tồn tại và `force_reprocess` là false thì skip, in `{"skipped": true}` rồi thoát 0.

Khi không skip: `drop_duplicates` → `drop_rows_missing_target` → split
`train_test_split(test_size=0.2, random_state=42)` → ghi hai file.

Seed cố định `42` là bắt buộc, không phải tuỳ chọn: cổng champion/challenger ở
mục 4.5 so hai model **trên cùng `test.parquet`**. Test set đổi giữa hai lần train
thì phép so sánh đó vô nghĩa.

### 4.4. `train`

Dựng estimator theo `task_type`, bọc `TransformedTargetRegressor` nếu là
regression, đưa vào `features.build_pipeline(task_type, estimator)`, fit trên
`train.parquet`.

Log vào MLflow: params của estimator, `fingerprint` đã dùng, metric trên tập
train, và nguyên `Pipeline` qua `mlflow.sklearn.log_model`.

**Estimator:** lần chạy đầu dùng `Ridge` làm baseline để biết sàn thật của
dataset, sau đó đổi sang `HistGradientBoostingRegressor`.

Lý do làm hai bước: spec mục 7.5 nói rõ ngưỡng R² ≥ 0.75 "sẽ hiệu chỉnh sau lần
train đầu tiên khi biết baseline thực tế". Chạy Ridge trước cho con số để hiệu
chỉnh, và tạo sẵn một model Production để cổng thứ hai có cái mà so — GBM phải
thắng Ridge mới được promote. Nếu model đầu tiên đã là GBM thì cổng
champion/challenger chưa bao giờ được chạy thật.

### 4.5. `evaluate`

Đọc `test.parquet`, load model ứng viên từ `run_id`, predict, tính RMSE / MAE / R²
**theo đơn vị đô la** (Pipeline đã tự nghịch đảo log).

Hai cổng, phải qua cả hai:

1. **Ngưỡng sàn:** regression R² ≥ 0.75; classification F1 ≥ 0.70.
2. **Phải hơn champion hiện tại** trên cùng `test.parquet`. Load
   `models:/{name}@champion`; chưa có alias nào thì bỏ qua cổng này.

Ghi metric của cả hai model vào cùng MLflow run để về sau đọc lại được vì sao một
model bị chặn.

### 4.6. `register`

`mlflow.register_model` → version N. Gắn alias `champion` vào N. Tính baseline
profile từ `train.parquet` bằng `profiling.compute_profile` (đã có từ Plan 1), ghi
vào `storage.baseline_key(model_name, N)`.

Baseline sinh từ **train**, không phải test: Plan 4 so phân phối traffic production
với phân phối dữ liệu model đã học.

## 5. Thay đổi ngoài `stages/`

### 5.1. `common/ml_common/storage.py` thêm hai hàm key

- `extracted_key(fingerprint) -> "extracted/{fp}/data.parquet"`
- `validation_report_key(fingerprint) -> "reports/validation/{fp}.json"`

Đây là mở rộng `storage.py`, không phải vi phạm ràng buộc "chỉ `storage.py` biết
đường dẫn" — ràng buộc đó nói mọi key phải sinh ra từ file này, và đó đúng là chỗ
hai hàm mới nằm.

### 5.2. `docker-compose.yml`

`airflow-scheduler` thêm docker socket và provider, theo đúng công thức ở mục 2.1.
Không đụng bốn service còn lại.

### 5.3. `scripts/seed_raw_data.py`

Đọc CSV local, ghi `raw/v1/data.parquet`. Chạy tay, ngoài DAG.

## 6. Cấu trúc thư mục mới

```
stages/
├── base/                 # đã có từ Plan 1
├── extract/
│   ├── Dockerfile
│   └── main.py
├── validate/
├── preprocess/
├── train/
├── evaluate/
└── register/
dags/
└── ml_pipeline_dag.py
scripts/
└── seed_raw_data.py
```

Mỗi `main.py` là vỏ mỏng: đọc env, gọi hàm thuần, ghi MinIO, in JSON. Logic thật
nằm trong hàm tách rời để test được không cần Docker.

## 7. Test

**Logic thuần, test bằng pytest không cần container:**

- Tính fingerprint: cùng input ra cùng kết quả; đổi `SAMPLE_ROWS` thì fingerprint
  phải đổi.
- Luật fail của `validate`: ba trường hợp fail, và các trường hợp bẩn-nhưng-hợp-lệ
  phải pass.
- Quyết định hai cổng của `evaluate`: dưới ngưỡng thì chặn; trên ngưỡng nhưng kém
  champion thì chặn; chưa có champion thì chỉ cần qua cổng một.
- Logic cache của `preprocess`: đủ file thì skip; `force_reprocess` thì không skip.

**Test round-trip** — spec mục 7.11 yêu cầu, Plan 1 chưa làm được vì chưa có model
thật: cùng một record thô đi qua Pipeline vừa fit và đi qua Pipeline load lại từ
MLflow phải ra cùng kết quả. Đây là test bắt được training/serving skew sớm nhất.

**Container:** theo spec mục 10 bước 3 — chạy tay từng container trước, ghép DAG
sau. Ghép trước rồi debug qua Airflow là cách chậm nhất để tìm lỗi.

**Toàn bộ test phải chạy được cả ở Python 3.13 local lẫn Python 3.12 trong
`ml-base`**, như Plan 1 đã thiết lập.

## 8. Definition of Done

- [ ] `scripts/seed_raw_data.py` đẩy được raw parquet lên MinIO.
- [ ] Sáu image stage build được, mỗi cái chạy tay được bằng `docker run`.
- [ ] DAG `ml_pipeline` chạy full một lượt với `task_type=regression`, tất cả task
      success tới `register`.
- [ ] Chạy lần hai với cùng tham số: `preprocess` báo `skipped: true`.
- [ ] Chạy lần ba với `force_reprocess=true`: `preprocess` chạy lại thật.
- [ ] MLflow có registered model `house_price_regressor` với alias `champion` trỏ
      vào một version.
- [ ] `monitoring-baseline/house_price_regressor/{v}/profile.json` tồn tại trên
      MinIO.
- [ ] Train Ridge rồi train GBM: GBM phải thắng cổng hai và chiếm alias champion.
- [ ] Train một model cố tình kém (ví dụ `DummyRegressor`): phải bị chặn ở
      `evaluate`, DAG đi nhánh `stop_no_deploy`, alias champion **không đổi**.
- [ ] Test round-trip pass.
- [ ] Toàn bộ test pass ở cả 3.13 local lẫn 3.12 container.

Hai mục áp chót là quan trọng nhất: chúng chứng minh cổng evaluate thật sự chặn
được, chứ không phải lúc nào cũng pass.

## 9. Chỗ tài liệu này lệch khỏi `mlops-pipeline-design.md`

| Mục | Spec gốc | Tài liệu này | Lý do |
| --- | --- | --- | --- |
| 7.5 | Registry stage `Production` | Alias `@champion` | Stage đã deprecate ở MLflow 2.22, bỏ hẳn ở MLflow 3 |
| 7.3 | Chỉ có `raw/` và `processed/` | Thêm `extracted/{fp}/` và `reports/validation/{fp}.json` | `extract` và `validate` cần chỗ ghi đầu ra của chính chúng |
| 7.4 | `preprocess` tính fingerprint | `extract` tính, truyền xuống qua XCom | `validate` chạy giữa hai stage đó và cũng cần fingerprint để đặt tên report. Tính ở `extract` thì cả ba stage sau dùng chung một giá trị, thay vì `validate` phải tính lại theo cách riêng — hai cách tính là hai chỗ để lệch nhau. |
| 6.1 | `dataset_version` mặc định `"latest"` | Mặc định `"v1"` | `raw_key()` nối thẳng giá trị này vào đường dẫn, nên `"latest"` sẽ trỏ tới `raw/latest/` theo nghĩa đen chứ không phân giải sang version mới nhất. Phân giải `"latest"` cần một cơ chế trỏ mà Plan 2 chưa có việc gì cần tới. |
| — | Không nói ai đưa CSV lên MinIO | `scripts/seed_raw_data.py` | Lỗ hổng trong spec gốc |
| — | Không nói ai đọc `SAMPLE_ROWS` | `extract` đọc, và nó nằm trong fingerprint | Lỗ hổng trong spec gốc |
| — | Không chỉ định estimator | Ridge trước, GBM sau | Cần baseline để hiệu chỉnh ngưỡng, và để cổng hai được chạy thật |

`mlops-pipeline-design.md` sẽ được cập nhật theo bảng này khi Plan 2 bắt đầu.
