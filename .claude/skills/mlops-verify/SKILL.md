---
name: mlops-verify
description: Xác nhận toàn bộ nền tảng MLOps pipeline hoạt động — chạy test ở cả Python local lẫn trong container, kiểm tra 4 service và Definition of Done của plan. Dùng cho Task 13 của Plan 1 và bất cứ khi nào cần kiểm tra lại trạng thái hệ thống.
context: fork
model: sonnet
---
Bạn đang xác nhận nền tảng MLOps pipeline hoạt động đầy đủ. Nhiệm vụ ở đây là
**tìm ra chỗ hỏng**, không phải xác nhận mọi thứ ổn. Một lần verify kết thúc
bằng "tất cả đều xanh" mà không thực sự chạy lệnh nào là vô giá trị.

## Nguyên tắc

Không bao giờ khẳng định một thứ hoạt động mà không có output chứng minh. Dán
output thật vào báo cáo. Nếu một bước không chạy được, nói rõ là không chạy
được — đừng bỏ qua và báo phần còn lại là xanh.

## Quy trình

Chạy lần lượt, **không dừng khi gặp lỗi** — ghi nhận rồi chạy tiếp, để báo cáo
cuối cùng cho thấy toàn cảnh.

### 1. Test suite ở máy dev (Python 3.13)

```powershell
.venv\Scripts\python.exe -m pytest common/ -v
```

Kỳ vọng: pass toàn bộ. Ghi lại số test.

### 2. Lint

```powershell
.venv\Scripts\python.exe -m ruff check common/
```

### 3. Hạ tầng

```powershell
docker compose ps
```

Kỳ vọng: `postgres`, `minio`, `mlflow`, `airflow-scheduler`, `airflow-webserver`
đều `running`, những service có healthcheck thì `(healthy)`.

### 4. Storage nối được tới MinIO thật

```powershell
.venv\Scripts\python.exe scripts\smoke_storage.py
```

Bước này khác test ở mục 1: mục 1 dùng `moto` (S3 giả lập trong bộ nhớ), bước
này dùng MinIO thật. Nó bắt được lỗi cấu hình endpoint mà `moto` không bắt được.

### 5. Test suite trong container Python 3.12

```powershell
docker run --rm ml-base:latest sh -c "pip install --quiet 'pytest>=8.0' 'moto[s3]>=5.0' && python -m pytest /app/common/tests -q"
```

Đây là bước hay bị bỏ qua nhất và cũng là bước có giá trị cao nhất. Test pass ở
Python 3.13 local mà fail ở Python 3.12 container là loại khác biệt môi trường
sẽ gây lỗi khó hiểu ở các plan sau.

### 6. Postgres có đúng hai database

```powershell
docker compose exec postgres psql -U mlops -d airflow -c "\l"
```

Kỳ vọng: danh sách có cả `airflow` và `mlflow`.

### 7. MLflow ghi được artifact lên MinIO

```powershell
.venv\Scripts\python.exe scripts\smoke_mlflow.py
```

Kỳ vọng: `artifact_uri` bắt đầu bằng `s3://ml-pipeline/artifacts/`. Nếu MLflow UI
hiện run nhưng MinIO không có file, `MLFLOW_S3_ENDPOINT_URL` đang sai.

### 8. Airflow đọc được DAG

```powershell
docker compose exec airflow-scheduler airflow dags list
docker compose exec airflow-scheduler airflow dags test smoke_test 2026-09-17
```

Kỳ vọng: cả hai task đều `success`, log in ra ba biến môi trường có giá trị.

### 9. Image nền

```powershell
docker run --rm ml-base:latest
```

Kỳ vọng: `ml-base ready, ml_common 0.1.0`

### 10. Dung lượng đĩa

```powershell
.venv\Scripts\python.exe -c "import shutil; print(f'{shutil.disk_usage(\"C:/\").free/2**30:.1f} GB free')"
```

## Đối chiếu Definition of Done

Mở phần `## Definition of Done` ở cuối `docs/superpowers/plans/2026-09-17-foundation.md`
và đánh dấu từng mục dựa trên kết quả thật ở trên. Mục nào chưa chạy được thì
để trống và nói rõ, đừng đoán.

Kiểm tra riêng mục cuối: **cả 8 loại dirty của dataset đều có test tương ứng.**
Đối chiếu `house_pricing_README.md` mục 2 với các file trong `common/tests/`.
Loại nào không tìm thấy test thì liệt kê ra.

## Báo cáo

Một bảng, mỗi dòng một mục kiểm tra:

| # | Mục       | Kết quả | Chi tiết    |
| - | ---------- | --------- | ------------ |
| 1 | Test local | ✅ / ❌   | `N passed` |

Sau bảng, chỉ viết về những gì hỏng: triệu chứng, output lỗi thật, và nguyên
nhân nếu đã xác định được. Không tóm tắt lại những thứ đã xanh.

Kết bằng một câu: nền tảng đã sẵn sàng cho Plan 2 hay chưa, và nếu chưa thì
thiếu đúng cái gì.
