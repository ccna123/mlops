# MLOps House Pricing Pipeline

Pipeline MLOps đầy đủ chạy offline, thiết kế để migrate lên AWS với thay đổi
code tối thiểu. Xem `mlops-pipeline-design.md` để biết thiết kế đầy đủ.

## Trạng thái

Plan 3/5 — serving chạy được cho cả hai model.

## Yêu cầu

- Docker Desktop
- Python 3.11+ (dev trên 3.13, container chạy 3.12)
- Ổ đĩa còn tối thiểu 15GB

## Khởi động

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e "common[dev]"
docker compose up -d
powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_stage_images.ps1
.venv\Scripts\python.exe scripts\seed_raw_data.py
```

## Giao diện

| Service | URL | Đăng nhập |
| --- | --- | --- |
| Airflow | http://localhost:8080 | admin / admin |
| MLflow | http://localhost:5000 | — |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |
| Serving | http://localhost:8000/health | — |

## Kiểm tra

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_foundation.ps1
```

## Chạy pipeline

Trên Airflow UI, bật DAG `ml_pipeline` rồi Trigger DAG w/ config:

    {"task_type": "regression", "estimator_name": "hist_gradient_boosting"}

Tham số: `task_type` (bắt buộc), `estimator_name`, `force_reprocess`,
`dataset_version`. `estimator_name` mặc định theo `task_type` (`ridge` /
`logistic`). Tên registered model luôn suy ra từ `task_type`, không truyền được.

Bài toán classification là `needs_renovation` — sinh ra từ `condition`
(`poor`/`fair`), không có sẵn trong dữ liệu thô.

Xác nhận pipeline:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_pipeline.ps1
```

## Gọi thử model

```powershell
curl -s http://localhost:8000/health
```

`/predict/{model}` nhận record **thô** — không cần làm sạch gì, model tự xử lý:

```powershell
curl -s -X POST http://localhost:8000/predict/regression -H "Content-Type: application/json" -d "{\"city\":\"  NEW YORK \",\"list_price\":\"$450,000\",\"bedrooms\":3}"
```

`model` là `regression` hoặc `classification`. Model chưa train thì trả 503.
Sau khi train model mới, `POST /reload` (task `deploy` của DAG tự gọi) để serving
nạp champion mới mà không cần restart.

Xác nhận serving:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_serving.ps1
```

## Cấu trúc

| Thư mục | Nội dung |
| --- | --- |
| `common/` | Package `ml_common` — schema, parser, transformer, storage, profiling |
| `dags/` | DAG của Airflow |
| `services/serving/` | FastAPI phục vụ champion từ MLflow Registry |
| `docker/` | Dockerfile cho hạ tầng |
| `stages/base/` | Image nền cho các stage |
| `scripts/` | Script smoke test và tiện ích |
| `docs/superpowers/` | Spec và implementation plan |

## Lưu ý về RAM

Máy 16GB chạy đồng thời Airflow + Postgres + MinIO + MLflow. Khi phát triển,
giới hạn số dòng theo từng lần chạy bằng `conf` `{"sample_rows": 200000}` (API,
dashboard, hoặc "Trigger DAG w/ config" trên Airflow UI) để không load toàn bộ
2 triệu dòng. Trigger từ Airflow UI mà không kèm config sẽ chạy toàn bộ dòng.
