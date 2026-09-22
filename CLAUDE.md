# MLOps House Pricing Pipeline

Pipeline MLOps đầy đủ chạy offline (Docker Compose), thiết kế để migrate lên AWS
với thay đổi code tối thiểu. Dự án để học và thực hành.

## Tài liệu bắt buộc đọc trước khi sửa code

| File | Nội dung |
| --- | --- |
| `mlops-pipeline-design.md` | Spec đầy đủ. Mục 12 là bảng đổi so với v1, đọc nhanh mục đó trước. |
| `docs/superpowers/plans/2026-09-17-foundation.md` | Plan 1/5 (foundation), đã xong. Mỗi task có code thật cho từng step. |
| `house_pricing_README.md` | Mô tả dataset và 8 loại dirty cần xử lý. |

Không suy đoán thiết kế từ code — spec là nguồn sự thật. Nếu code và spec lệch
nhau, đó là bug của một trong hai, phải báo chứ không tự chọn bên.

## Ràng buộc kiến trúc — vi phạm là bug, không phải vấn đề style

### 1. Thao tác theo cột và thao tác theo dòng phải tách biệt

- `common/ml_common/cleaning.py` — transformer **theo cột**, nằm trong sklearn
  `Pipeline`, được đóng gói cùng model vào MLflow. Chạy ở cả `prepare_dataset_for_train`
  (2 triệu dòng) lẫn serving (một record).
- `common/ml_common/rowops.py` — thao tác **theo dòng** (dedup, loại dòng hỏng).
  Chỉ được gọi từ stage `prepare_dataset_for_train`.

Một transformer xoá dòng lọt vào `Pipeline` sẽ chạy đúng suốt lúc train rồi làm
serving sập khi `/predict` gọi nó với một record: DataFrame trả về rỗng.

**Không bao giờ import `rowops` từ `features.py` hay từ serving.**

### 2. `storage.py` là nơi duy nhất biết về đường dẫn object storage

Mọi key trên MinIO/S3 phải tạo qua hàm `*_key()` / `*_prefix()` trong
`common/ml_common/storage.py`. Không nối chuỗi đường dẫn ở bất kỳ file nào khác.
Khi migrate sang S3 thật, chỉ file này phải sửa.

### 3. Model tự chứa logic làm sạch

`train.py` log nguyên `Pipeline` (transformer + estimator) vào MLflow. Endpoint
`/predict` nhận record **thô** và model tự clean. Không bao giờ chép logic
cleaning sang serving — đó chính là training/serving skew mà cả thiết kế này
được dựng lên để tránh.

### 4. Python 3.12 trong container, 3.13 ở máy dev

Airflow 2.10 chưa hỗ trợ 3.13. Container (Airflow, `ml-base`, serving, agent, api)
đều dùng Python 3.12. Máy dev chạy 3.13 để test logic thuần.

- **Không dùng cú pháp chỉ có ở 3.13+.**
- **Không train ở môi trường này rồi serve ở môi trường khác.** Model pickle bởi
  scikit-learn chỉ load lại được bởi cùng minor version Python và cùng version
  scikit-learn. Train và serve đều diễn ra trong container.

## Quy ước viết code

- **Dấu tiếng Việt:** file markdown có dấu. Commit message viết **tiếng Anh** —
  xem mục Quy ước commit.
- **Ngôn ngữ trong code:** toàn bộ code — biến cục bộ lẫn API công khai, comment,
  docstring, error message — viết **tiếng Anh tự nhiên**, đặt tên sao cho dễ
  đọc (vd `result`, `deleted_row_count`, `compute_profile`, `build_pipeline`),
  không dịch word-by-word từ tiếng Việt. Lý do: traceback, log container, và
  tài liệu sklearn/MLflow đều tiếng Anh — trộn ngôn ngữ làm code khó đọc hơn.
- **Giá trị thiếu:** dùng `None` / `np.nan`. Không dùng chuỗi rỗng hay sentinel
  như `-1`.
- **Chuẩn hoá text:** categorical về chữ thường, dấu cách đơn, gạch dưới và gạch
  nối đổi thành dấu cách. `"Multi-Family"`, `"MULTI FAMILY"`, `"multi_family"`
  đều phải ra `"multi family"`.
- **Parser không bao giờ đoán.** Giá trị mơ hồ trả `None` để stage `validate`
  đếm được và báo cáo. Zipcode 4 số không được tự thêm số 0 đầu.
- **Docstring:** mọi function, method và class trong code production
  (`common/`, `services/`, `stages/`, `dags/`, `scripts/`) phải có docstring
  Google style, ghi rõ `Args:` và `Returns:`, thêm `Raises:` khi hàm có ném
  exception. Hàm không nhận tham số vẫn ghi `Args: None.` kèm danh sách biến
  môi trường nó đọc — với các stage thì đó chính là input thật sự. Thư mục
  `tests/` được miễn: tên test đã là tài liệu.
- **Example trong docstring:** thêm mục `Example:` cho hàm mà thấy cách gọi sẽ
  hiểu nhanh hơn đọc mô tả. Viết dạng **minh hoạ, không phải doctest** — dùng
  `# -> ket qua`, **không dùng `>>>`**, để pytest không thu gom chúng thành
  test. Miễn cho `fit`/`transform` của sklearn transformer (đặt example ở
  docstring của class) và `main()` của stage (chỉ chạy qua DockerOperator).
  Vì không có gì tự động chặn example sai, khi sửa hàm phải sửa luôn example.
  Có backslash trong docstring thì dùng `r"""` — ruff `D301` sẽ nhắc.
- **Ruff:** cấu hình ở `ruff.toml` **tại gốc repo** (không phải trong
  `common/`), áp dụng cho toàn bộ code. `line-length = 100`, rule set
  `["E", "F", "I", "UP", "B", "D"]`, `convention = "google"`. Rule `D` chính là
  thứ bắt buộc docstring ở trên.

## Lệnh

Gọi thẳng `.venv\Scripts\python.exe`, không dùng `Activate.ps1` (vướng execution
policy của PowerShell).

```powershell
.venv\Scripts\python.exe -m pytest common/ services/ -v   # toàn bộ test
.venv\Scripts\python.exe -m pytest common/tests/test_parsers.py -v
.venv\Scripts\python.exe -m ruff check . --fix            # config o ruff.toml goc repo
docker compose ps                                          # trạng thái hạ tầng
powershell -ExecutionPolicy Bypass -File scripts\verify_foundation.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_pipeline.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_serving.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_monitoring.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_api.ps1
```

`verify_api.ps1` gọi service thật, nên cần: **cả stack đang chạy** (kể cả `api`),
object `raw/v1/data.parquet` đã có trong MinIO (thiếu thì bước 9 **fail**, không
skip), và Airflow đã có ít nhất một run của `ml_pipeline` (chưa có thì bước 7
chỉ **SKIP** và script in ra là chưa verify đủ). Chi tiết ở đầu file script.

Khi `common/` thay đổi, phải build lại **cả năm tầng, theo đúng thứ tự này**:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_stage_images.ps1
docker build -f services/serving/Dockerfile -t ml-serving:latest .
docker build -f services/agent/Dockerfile -t ml-agent:latest .
docker build -f services/api/Dockerfile -t ml-api:latest .
```

Chỉ build `ml-base` là **chưa đủ**. Bảy stage image (kể cả `ml-monitor`),
`ml-serving`, `ml-agent` và `ml-api` đều `FROM ml-base:latest`, nên tới khi được
build lại chúng vẫn giữ nguyên bản `ml_common` cũ nướng sẵn bên trong — `docker
images` sẽ cho thấy `ml-base` mới tinh còn phần còn lại thì không. Triệu
chứng: sửa code trong `common/`, test ở máy xanh, mà DAG vẫn chạy y như cũ.
`ml-api` còn nướng thêm `services/` (`COPY services/ /app/services/`), nên sửa
`services/api/` cũng phải build lại riêng image này.

Kiểm tra test trong container (`ml-base` không có sẵn pytest nên phải cài vào):

```powershell
docker run --rm ml-base:latest sh -c "pip install --quiet 'pytest>=8.0' 'moto[s3]>=5.0' && python -m pytest /app/common/tests -q"
```

## Giao diện

| Service | URL | Đăng nhập |
| --- | --- | --- |
| Airflow | http://localhost:8080 | admin / admin |
| MLflow | http://localhost:5000 | — |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |
| API layer (`services/api/`) | http://localhost:8001 — endpoint ở `/api/...` (vd `/api/health`), Swagger ở `/docs` | — (chưa có auth, xem `mlops-pipeline-design.md` mục 3.2) |
| Dashboard | http://localhost:5173 (`cd dashboard; npm run dev`) | — (chưa có auth) |

## Giới hạn máy — đã gây ra quyết định thiết kế

- **RAM 16GB** chạy đồng thời Airflow + Postgres + MinIO + MLflow. Khi dev, giới
  hạn số dòng **theo từng lần chạy** qua `conf` của DAG `ml_pipeline`:
  `{"sample_rows": 200000}` (gửi từ API/dashboard, hoặc nhập vào ô config của
  "Trigger DAG w/ config" trên Airflow UI). Biến môi trường `SAMPLE_ROWS` trong
  `.env` **không còn tác dụng** — DAG tự truyền giá trị từ `conf` cho stage
  `extract`. **Cảnh báo:** bấm Trigger từ Airflow UI mà **không** kèm config thì
  chạy **toàn bộ** ~2 triệu dòng và có thể làm cạn RAM máy 16GB. Không còn lưới
  an toàn ở `.env` nữa, nên nhớ luôn đặt `sample_rows` khi dev.
- **Ổ C còn ~16GB (94% đã dùng, đo ngày 2026-09-19).** Kiểm tra dung lượng trước khi pull image lớn.
  `docker system prune -a` nếu cần chỗ.
- `house_pricing_dirty.csv` (373MB) và bản `.gz` đã được gitignore. Không bao giờ
  commit chúng.

## Quy ước commit

Conventional Commits, mô tả **tiếng Anh**. Một task trong plan = một commit.

```
feat: parse the 5 dirty formats at the single-value level
test: cover the 4-digit zipcode case
chore: scaffold the ml_common package and tooling
docs: README and the foundation verification script
```

Tiếng Anh thay cho tiếng Việt không dấu kể từ 2026-09-20. Lý do đổi: git log
nằm cùng chỗ với traceback, log container và docstring — vốn đã tiếng Anh cả —
nên tiếng Việt không dấu là ngôn ngữ thứ ba, và nó đọc chậm hơn hẳn (`sua tan
goc bay stdout` mất vài giây để giải mã). Tiếng Anh cũng bỏ luôn được lý do
phải bỏ dấu: không còn rủi ro encoding trên terminal Windows.

**Commit cũ giữ nguyên** — không rewrite history. Log sẽ có hai ngôn ngữ ở hai
giai đoạn, và điều đó bình thường.

Chỉ commit khi được yêu cầu hoặc khi plan nói rõ ở step đó.

## Trạng thái

Bốn plan đầu **đã xong và đã merge vào `main`** (merge commit của Plan 4 là
`706f45a`; `git branch --merged main` liệt kê cả `plan1-infra` tới
`plan4-monitoring`). Plan 5a (API) đã merge vào `main`. Plan 5b (dashboard) đã
dựng xong 5 màn và đang ở `main` dưới dạng chưa tách nhánh:

| Plan | Nội dung | Verify |
| --- | --- | --- |
| 1/5 | Foundation — Postgres, MinIO, MLflow, Airflow, `ml-base` | `scripts\verify_foundation.ps1` |
| 2/5 | Batch pipeline — 6 stage + DAG `ml_pipeline`, hai cổng promote | `scripts\verify_pipeline.ps1` |
| 3/5 | Serving — `/predict` nhận record thô, `/reload`, inference log theo lô | `scripts\verify_serving.ps1` |
| 4/5 | Monitoring — agent 5 kịch bản, `/feedback`, Evidently 3 loại drift, `monitoring_dag` | `scripts\verify_monitoring.ps1` |
| 5a/5 | API layer — `services/api/` (FastAPI, cổng 8001, 15 endpoint), Airflow REST bật basic auth, `sample_rows` thành param của DAG | `scripts\verify_api.ps1` |
| 5b/5 | Dashboard — `dashboard/` (Vite + React + Tailwind, 5 màn), xoá model version / cả model, trigger drift thủ công, chọn thuật toán train | chưa có script; verify bằng trình duyệt |

Đo ngày 2026-09-22: 679 test pass ở Python 3.13 (local,
`pytest common/ services/`). Ở 3.12 (container) image `ml-base` chỉ chứa
`common/`, nên test cần `stages/` hoặc `services/` bị skip có chủ ý ở đó, và
**test của `services/api/` chỉ chạy ở máy dev**, không chạy trong container.

### Plan 5b — dashboard (2026-09-21)

Không còn dùng "một file HTML tự chứa" như brief mô tả: chủ dự án chọn **Vite +
React + Tailwind + lucide-react + Chart.js**, có bước build. Quyết định CORS ở
mục 5.1 của brief được giải bằng **proxy của Vite dev server** (`/api` →
`http://localhost:8001`), nên `API_BASE` là đường dẫn tương đối `/api` và
trình duyệt không hề gọi cross-origin. **Bản production vẫn chưa chọn cách phục
vụ** — hoặc API tự serve thư mục build, hoặc thêm `CORSMiddleware`.

```powershell
cd dashboard; npm install; npm run dev    # http://localhost:5173
```

Sidebar có nút **"Chế độ minh hoạ"**: bật lên thì mọi màn dùng fixture JSON
chép từ brief (`src/lib/demoFixtures.js`) thay vì gọi API, để xem giao diện khi
stack chưa chạy.

**Chọn thuật toán train (2026-09-22).** Form train có dropdown "Thuật toán",
danh sách lấy từ `GET /api/estimators` — endpoint đọc thẳng
`ml_common.estimators.ESTIMATOR_NAMES`, nên không có danh sách nào bị chép lại
ở frontend. Bỏ trống thì DAG tự chọn mặc định (`ridge` / `logistic`), nhờ đó
mặc định chỉ tồn tại ở một chỗ. `hist_gradient_boosting_weak` và `dummy` nằm
trong nhóm riêng "Chỉ để test cổng promote" (khoá `diagnostic` của endpoint).

| task_type | Estimator |
| --- | --- |
| regression | `ridge`, `xgboost`, `hist_gradient_boosting`, `hist_gradient_boosting_weak`, `dummy` |
| classification | `logistic`, `xgboost`, `random_forest`, `hist_gradient_boosting`, `hist_gradient_boosting_weak`, `dummy` |

**`xgboost` là dependency mới của `common/`** (`pyproject.toml`), nên lần thêm
nó đã phải build lại **đủ cả 5 tầng**. Đây không phải thủ tục thừa: `serving`
unpickle nguyên `Pipeline` từ MLflow, nên nếu image `ml-serving` thiếu xgboost
thì model train bằng xgboost sẽ load không nổi — đúng loại training/serving
skew mà ràng buộc kiến trúc mục 3 dựng lên để tránh. Đã verify: train bằng
xgboost → `serving` `/predict/regression` trả về dự đoán thật.

**Hai DAG đều để unpaused và đều `max_active_runs=1`.** `ml_pipeline` giữ
`schedule=None`; `monitoring_dag` đổi từ `@hourly` + paused sang `schedule=None`
+ unpaused (xem mục 2.7 spec Plan 4). Lý do: run của một DAG paused nằm
`queued` vĩnh viễn và **không tín hiệu nào trên API hay dashboard cho biết vì
sao** — đúng sự cố mất nửa buổi ngày 2026-09-21. Hệ quả cần nhớ: lưới an toàn
cũ không còn, bấm Trigger từ Airflow UI mà quên `conf` sẽ chạy toàn bộ 2 triệu
dòng. Dashboard thì luôn gửi `sample_rows` nên an toàn.

### Plan 5a — những điều không tự suy ra được từ code

- **Plan 5a có sửa `common/ml_common/`**, dù non-goals của plan ghi là không
  đụng: thêm `rawdata.py` (`csv_to_parquet`, dùng chung với `scripts/seed_raw_data.py`),
  `Storage.read_parquet_head`, `Storage.check_reachable`, `drift_prefix` và
  `is_drift_summary_key`. Lý do: luật "chỉ `storage.py` biết đường dẫn" (mục 2
  ở trên) buộc key `reports/...` phải nằm ở đó, và đọc cả file raw 2 triệu dòng
  để xem trước sẽ hết RAM. Vì vậy `common/` thay đổi kéo theo build lại cả năm tầng.
- **Mọi collaborator của API được inject** (`create_app(airflow, registry, reports,
  probes, storage)`), giống serving. Client không dựng được (thiếu biến môi
  trường) thì là `None`, app vẫn lên và `/api/health` báo dependency đó `down`,
  kèm một WARNING trong log — không phải crash-loop.
- **Preview chỉ đọc 200.000 dòng đầu** của file raw (`PREVIEW_STATS_ROWS`), nên
  thống kê cột là của phần đầu file; `total_rows` mới là của cả file. Object
  vẫn được tải nguyên về bộ nhớ mỗi lần gọi; đo ở Task 12, mỗi lần gọi đẩy RSS
  của process API lên khoảng 0,9–1,2 GB (đỉnh RSS 909.420 / 1.085.624 /
  1.162.148 kB trong ba lần gọi liên tiếp; ba lần chưa đủ để chứng minh nó ngừng
  tăng). Một lần gọi thứ hai sau khi khởi động lại container đạt 1.261.240 kB.
- **Trần upload 500 MiB** (`app.state.max_upload_bytes`) chỉ chặn phần handler
  copy và chuyển đổi. FastAPI đã nhận và ghi cả body ra đĩa trước khi handler
  chạy, nên 413 chỉ đến **sau khi** upload xong, và đỉnh dùng đĩa có thể tới
  khoảng ba bản (body của framework, CSV, parquet). Đường 413 chưa được chạy
  thật trên hệ thống sống.
- **Chưa có auth**: `require_auth` rỗng, nên `promote`, `upload`, `pipeline/run`,
  và (từ Plan 5b) `DELETE /models/{name}/{version}`, `DELETE /models/{name}` lẫn
  `POST /drift/run` mở cho bất kỳ ai tới được cổng 8001. Xoá là thao tác **không
  hoàn tác được** duy nhất trong API. `DELETE /models/{name}` xoá sạch mọi
  version kèm alias champion và **không có luật nào chặn**, nên chỉ một request
  là mất cả model — thứ duy nhất đứng giữa là `ConfirmDialog` ở trình duyệt.
  Riêng xoá một *version* đang là champion thì bị chặn ở backend (409), gọi
  thẳng API cũng không lách được.
- **Xoá hết model không làm hỏng gì.** `serving` trả 503 `no champion loaded`
  (đã có từ Plan 3), `/api/health` vẫn báo serving `ok` vì probe chỉ kiểm HTTP
  200 mà serving trả 200 cả khi `degraded`, và hai màn Models/Drift đều có
  empty state riêng. Lưu ý serving vẫn phục vụ model đang nằm trong RAM cho tới
  lần restart hoặc `/reload` kế tiếp.
