---
name: mlops-tdd-module
description: Thực thi một task viết module Python trong common/ của MLOps pipeline theo TDD nghiêm ngặt (test trước, chạy cho fail, rồi mới implement). Dùng cho Task 2, 3, 4, 5, 6, 9 của Plan 1.
context: fork
model: opus
---
Bạn đang thực thi **một task** viết module Python trong `common/ml_common/` theo
implementation plan. Quy trình TDD ở đây là bắt buộc, không phải gợi ý.

## Trước khi bắt đầu

1. Đọc `CLAUDE.md` — ràng buộc kiến trúc và quy ước code.
2. Đọc **đúng task được giao** trong `docs/superpowers/plans/2026-09-17-foundation.md`.
   Đừng đọc lướt cả file: tìm heading `## Task N:` và đọc từ đó tới `---` tiếp theo.
3. Đọc khối **Interfaces** của task. Phần `Consumes` cho biết hàm nào đã tồn tại
   và tên chính xác của chúng; phần `Produces` là hợp đồng mà task sau phụ thuộc
   vào — tên hàm và kiểu dữ liệu phải khớp từng ký tự.

Nếu task phụ thuộc một module chưa tồn tại, dừng lại và báo — đừng tự viết nó.

## Quy trình bắt buộc

Plan đã có sẵn code cho từng step. Dùng code đó, không tự nghĩ lại.

1. **Viết file test trước.** Chép nguyên khối test từ plan. Nếu thấy test trong
   plan sai (lỗi cú pháp, assert sai logic), sửa và **nói rõ đã sửa gì** —
   nhưng không được nới lỏng assert để nó dễ pass hơn.
2. **Chạy test, xác nhận nó FAIL.** Đây là bước không được bỏ. Expected failure
   phải khớp với plan (thường là `ModuleNotFoundError`). Nếu test pass ngay ở
   bước này thì test đang không kiểm tra gì cả — dừng lại và điều tra.
3. **Viết implementation tối thiểu.** Chép code từ plan.
4. **Chạy test, xác nhận PASS.** Dán output thật vào câu trả lời, không viết
   "tests pass" mà không có bằng chứng.
5. **Chạy ruff:** `.venv\Scripts\python.exe -m ruff check common/ --fix`
6. **Chạy lại toàn bộ test suite:** `.venv\Scripts\python.exe -m pytest common/ -q`
   để chắc chắn module mới không làm hỏng module cũ.
7. **Commit** đúng message ghi trong plan.

## Lệnh

```powershell
.venv\Scripts\python.exe -m pytest common/tests/test_<module>.py -v
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/ --fix
```

Gọi thẳng `.venv\Scripts\python.exe`, không dùng `Activate.ps1`.

## Ranh giới không được vượt qua

- **Chỉ đụng vào file mà task liệt kê trong khối `Files`.** Thấy chỗ khác cần
  sửa thì báo, đừng sửa.
- **Không thêm module, hàm, hay tham số ngoài phần `Produces`.** Task sau đã
  được viết dựa trên hợp đồng đó.
- **Không đọc `house_pricing_dirty.csv`.** Plan 1 test bằng DataFrame nhỏ tạo
  trong bộ nhớ. File CSV thật chỉ được đụng tới ở Plan 2.
- **Không train model thật.** Dùng `DummyRegressor` / `DummyClassifier` hoặc
  `DecisionTreeRegressor` như plan chỉ định.
- **Không đưa thao tác xoá dòng vào `cleaning.py` hay `features.py`.** Xem mục
  ràng buộc kiến trúc trong `CLAUDE.md`.

## Khi test thất bại mà không hiểu vì sao

Đừng sửa test cho nó pass. Đọc kỹ traceback, kiểm tra giả định bằng một lệnh
`python -c` nhỏ, rồi sửa nguyên nhân thật. Nếu sau hai lần thử vẫn không ra,
dừng lại và báo cáo kèm output đầy đủ.

## Báo cáo khi xong

Ngắn gọn, gồm đúng bốn thứ:

1. Task số mấy, module nào.
2. Số test pass (dán dòng tổng kết của pytest).
3. Những chỗ đã lệch khỏi plan và lý do — nếu không lệch thì nói "bám sát plan".
4. Bất cứ điều gì phát hiện được sẽ ảnh hưởng task sau.
