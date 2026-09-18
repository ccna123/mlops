---
name: mlops-infra-service
description: Thực thi một task dựng service hạ tầng (Postgres, MinIO, MLflow, Airflow, image nền) trong docker-compose của MLOps pipeline, kèm smoke test chứng minh service hoạt động thật. Dùng cho Task 7, 10, 11, 12 của Plan 1.
context: fork
model: sonnet
---
Bạn đang thực thi **một task** dựng hạ tầng cho MLOps pipeline. Nguyên tắc chi
phối: một service chỉ được coi là xong khi có bằng chứng nó nói chuyện được với
các service khác — không phải khi container ở trạng thái `running`.

## Trước khi bắt đầu

1. Đọc `CLAUDE.md`.
2. Đọc **đúng task được giao** trong `docs/superpowers/plans/2026-09-17-foundation.md`
   (tìm heading `## Task N:`).
3. **Kiểm tra dung lượng đĩa trước khi pull image:**
   ```powershell
   .venv\Scripts\python.exe -c "import shutil; print(f'{shutil.disk_usage(\"C:/\").free/2**30:.1f} GB free')"
   ```

   Ổ C của máy này đã dùng 93%. Dưới 8GB trống thì dừng lại và báo, đừng pull.
4. Xem `docker compose ps` để biết service nào đang chạy.

## Quy trình

1. **Sửa file** đúng như plan chỉ định (`docker-compose.yml`, `docker/*/Dockerfile`).
   Khi thêm service vào `docker-compose.yml`, chèn đúng vị trí plan nói — thường
   là trước khối `volumes:` ở cuối file.
2. **Khởi động:** `docker compose up -d <service>`. Với service có `build:`, thêm
   `--build`.
3. **Chờ healthcheck:** `docker compose ps` cho tới khi trạng thái là
   `running (healthy)`. Đừng chạy smoke test khi service còn `starting`.
4. **Chạy smoke test** mà plan chỉ định. Đây là bước quan trọng nhất — nó chứng
   minh service thật sự hoạt động, không chỉ khởi động được.
5. **Xác nhận bằng mắt** nếu plan yêu cầu (mở UI trên browser). Nếu không mở được
   browser, dùng `curl`/`Invoke-WebRequest` kiểm tra endpoint health.
6. **Commit** đúng message ghi trong plan.

## Khi container không lên

Đọc log trước khi thử bất cứ cách sửa nào:

```powershell
docker compose logs <service> --tail 50
docker compose ps
```

Nguyên nhân hay gặp, theo thứ tự nên kiểm tra:

| Triệu chứng                                  | Nguyên nhân thường gặp                                                                                                                                                                               |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Biến môi trường rỗng trong container      | Thiếu file`.env` (phải copy từ `.env.example`), hoặc thiếu khối `&airflow-env`                                                                                                                |
| `connection refused` tới postgres/minio     | Thiếu`depends_on` với `condition: service_healthy`                                                                                                                                                  |
| MLflow chạy nhưng artifact không lên MinIO | `MLFLOW_S3_ENDPOINT_URL` sai — phải là địa chỉ **nội bộ** `http://minio:9000`                                                                                                           |
| Code chạy trong container không thấy MinIO  | Dùng nhầm`MINIO_ENDPOINT` (localhost) thay vì `MINIO_ENDPOINT_INTERNAL`                                                                                                                            |
| Init script SQL không chạy                   | Script trong`docker-entrypoint-initdb.d` chỉ chạy lần đầu volume được tạo. Phải `docker compose down -v` để chạy lại — **thao tác này xoá dữ liệu, hỏi trước khi làm.** |
| Port đã bị chiếm                           | `netstat -ano \| findstr :<port>`                                                                                                                                                                        |

## Ranh giới không được vượt qua

- **Không `docker compose down -v`** mà không hỏi — nó xoá toàn bộ volume, mất
  metadata Airflow và MLflow.
- **Không đổi port** đã khai báo trong plan; dashboard và các script smoke test
  ở plan sau phụ thuộc vào chúng.
- **Không hardcode credential** vào `docker-compose.yml`. Mọi giá trị đi qua
  `.env`.
- **Không sửa `common/`** trong task hạ tầng. Thấy nó có vấn đề thì báo.
- **Không bỏ qua smoke test** vì "container đã healthy rồi". Healthcheck chỉ
  chứng minh service tự sống được, không chứng minh nó nói chuyện được với
  service khác.

## Với task build image nền (`ml-base`)

Image này phải build **từ thư mục gốc repo** vì Dockerfile tham chiếu `common/`:

```powershell
docker build -f stages/base/Dockerfile -t ml-base:latest .
```

Bắt buộc chạy test suite bên trong image trước khi coi là xong — nó chứng minh
`common/` hoạt động trên Python 3.12 chứ không chỉ trên Python 3.13 của máy dev.
Test pass ở local mà fail trong container là đúng loại lỗi sẽ gây khó hiểu ở
Plan 2 và Plan 3, phải sửa ngay chứ không để lại.

## Báo cáo khi xong

1. Task số mấy, service nào.
2. Output của `docker compose ps` (chỉ dòng liên quan).
3. Kết quả smoke test — dán output thật.
4. Những chỗ đã lệch khỏi plan và lý do.
5. Dung lượng đĩa còn lại sau khi build/pull.
