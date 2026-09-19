# MLOps House Pricing Pipeline

Pipeline MLOps đầy đủ chạy offline (Docker Compose), thiết kế để migrate lên AWS
với thay đổi code tối thiểu. Dự án để học và thực hành.

## Tài liệu bắt buộc đọc trước khi sửa code

| File | Nội dung |
| --- | --- |
| `mlops-pipeline-design.md` | Spec đầy đủ. Mục 12 là bảng đổi so với v1, đọc nhanh mục đó trước. |
| `docs/superpowers/plans/2026-09-17-foundation.md` | Plan 1/5 đang thực thi. Mỗi task có code thật cho từng step. |
| `house_pricing_README.md` | Mô tả dataset và 8 loại dirty cần xử lý. |

Không suy đoán thiết kế từ code — spec là nguồn sự thật. Nếu code và spec lệch
nhau, đó là bug của một trong hai, phải báo chứ không tự chọn bên.

## Ràng buộc kiến trúc — vi phạm là bug, không phải vấn đề style

### 1. Thao tác theo cột và thao tác theo dòng phải tách biệt

- `common/ml_common/cleaning.py` — transformer **theo cột**, nằm trong sklearn
  `Pipeline`, được đóng gói cùng model vào MLflow. Chạy ở cả `preprocess`
  (2 triệu dòng) lẫn serving (một record).
- `common/ml_common/rowops.py` — thao tác **theo dòng** (dedup, loại dòng hỏng).
  Chỉ được gọi từ stage `preprocess`.

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

Airflow 2.10 chưa hỗ trợ 3.13. Container (Airflow, `ml-base`, serving) đều dùng
Python 3.12. Máy dev chạy 3.13 để test logic thuần.

- **Không dùng cú pháp chỉ có ở 3.13+.**
- **Không train ở môi trường này rồi serve ở môi trường khác.** Model pickle bởi
  scikit-learn chỉ load lại được bởi cùng minor version Python và cùng version
  scikit-learn. Train và serve đều diễn ra trong container.

## Quy ước viết code

- **Dấu tiếng Việt:** file markdown có dấu. Commit message tiếng Việt **không
  dấu** — tránh lỗi encoding khi chạy qua terminal Windows và trong log
  container.
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
- **Ruff:** `line-length = 100`, rule set `["E", "F", "I", "UP", "B"]`.

## Lệnh

Gọi thẳng `.venv\Scripts\python.exe`, không dùng `Activate.ps1` (vướng execution
policy của PowerShell).

```powershell
.venv\Scripts\python.exe -m pytest common/ -v          # toàn bộ test
.venv\Scripts\python.exe -m pytest common/tests/test_parsers.py -v
.venv\Scripts\python.exe -m ruff check common/ --fix
docker compose ps                                       # trạng thái hạ tầng
powershell -ExecutionPolicy Bypass -File scripts\verify_foundation.ps1
```

Build lại image nền **mỗi khi `common/` thay đổi**, nếu không các stage sẽ dùng
bản cũ:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1
```

## Giao diện

| Service | URL | Đăng nhập |
| --- | --- | --- |
| Airflow | http://localhost:8080 | admin / admin |
| MLflow | http://localhost:5000 | — |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |

## Giới hạn máy — đã gây ra quyết định thiết kế

- **RAM 16GB** chạy đồng thời Airflow + Postgres + MinIO + MLflow. Khi dev, đặt
  `SAMPLE_ROWS=200000` trong `.env`. Xoá biến đó khi chạy thật.
- **Ổ C còn ~16GB (94% đã dùng, đo ngày 2026-09-19).** Kiểm tra dung lượng trước khi pull image lớn.
  `docker system prune -a` nếu cần chỗ.
- `house_pricing_dirty.csv` (373MB) và bản `.gz` đã được gitignore. Không bao giờ
  commit chúng.

## Quy ước commit

Conventional Commits, mô tả tiếng Việt không dấu. Một task trong plan = một commit.

```
feat: parser cho 5 loai dirty o muc gia tri don le
test: them test cho truong hop zipcode 4 so
chore: scaffolding package ml_common va tooling
docs: README va script xac nhan nen tang
```

Chỉ commit khi được yêu cầu hoặc khi plan nói rõ ở step đó.

## Trạng thái

Plan 1/5 (Foundation) **đã xong** — 13/13 task, `scripts\verify_foundation.ps1`
xanh toàn bộ. Postgres, MinIO, MLflow, Airflow chạy được; `ml-base:latest` build
được; 148 test pass ở cả Python 3.13 (local) lẫn 3.12 (container).

Bốn plan còn lại: batch pipeline, serving, monitoring, dashboard — xem bản đồ ở
cuối file plan. Mỗi plan viết sau khi plan trước chạy xong.
