# Image nền cho các stage

`ml-base:latest` chứa Python 3.12 và package `ml_common` đã cài ở chế độ editable.

## Build

Chạy từ thư mục gốc của repo:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1
```

## Khi nào phải build lại

Bất cứ khi nào `common/` thay đổi. Các stage `FROM ml-base:latest` sẽ không
tự thấy thay đổi cho tới khi image nền được build lại.

## Ràng buộc

Python phải là 3.12, khớp với image Airflow và với serving. Model pickle
bởi scikit-learn chỉ load lại được bởi cùng minor version Python và cùng
version scikit-learn.
