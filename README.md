# MLOps House Pricing Pipeline

Pipeline MLOps đầy đủ chạy offline, thiết kế để migrate lên AWS với thay đổi
code tối thiểu. Xem `mlops-pipeline-design.md` để biết thiết kế đầy đủ.

## Trạng thái

Plan 1/5 (Foundation) — hạ tầng và package `common/`.

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
```

## Giao diện

| Service | URL | Đăng nhập |
| --- | --- | --- |
| Airflow | http://localhost:8080 | admin / admin |
| MLflow | http://localhost:5000 | — |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |

## Kiểm tra

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_foundation.ps1
```

## Cấu trúc

| Thư mục | Nội dung |
| --- | --- |
| `common/` | Package `ml_common` — schema, parser, transformer, storage, profiling |
| `dags/` | DAG của Airflow |
| `docker/` | Dockerfile cho hạ tầng |
| `stages/base/` | Image nền cho các stage |
| `scripts/` | Script smoke test và tiện ích |
| `docs/superpowers/` | Spec và implementation plan |

## Lưu ý về RAM

Máy 16GB chạy đồng thời Airflow + Postgres + MinIO + MLflow. Khi phát triển,
đặt `SAMPLE_ROWS=200000` trong `.env` để không load toàn bộ 2 triệu dòng.
Xoá biến đó khi chạy thật.
