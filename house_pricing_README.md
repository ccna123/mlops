# Dataset: House Pricing (dirty, ~2 triệu dòng)

File: `house_pricing_dirty.csv` (~373MB, ~2,012,000 dòng, 24 cột) — có bản nén `house_pricing_dirty.csv.gz` (~152MB) đọc trực tiếp được bằng `pd.read_csv("house_pricing_dirty.csv.gz")`.

Dataset giả lập thị trường bất động sản Mỹ (nhiều thành phố, khoảng giá khác nhau), dùng được cho **cả 2 loại bài toán**:
- **Regression**: dự đoán `sale_price` (hoặc `list_price`).
- **Classification**: dự đoán `price_category` (Low/Medium/High/Luxury) hoặc `sold_within_30_days` (Yes/No).

Dataset **cố tình để dirty** để luyện phần data cleaning trong pipeline (stage `validate`/`preprocess`).

---

## 1. Mô tả cột

| Cột | Kiểu | Mô tả |
|---|---|---|
| `property_id` | int | ID căn nhà. **Có duplicate** (giả lập lỗi nhập trùng, ~0.6%). |
| `listing_date` | string | Ngày đăng bán. **3 format khác nhau lẫn lộn** (`YYYY-MM-DD`, `MM/DD/YYYY`, `DD-Mon-YYYY`) + ~8% rỗng. |
| `city` | string | Thành phố (21 thành phố Mỹ). Một số dòng bị dirty case (`NEW YORK`, `new york`, `New_York`, có khoảng trắng thừa). |
| `state` | string | Bang (2 ký tự). Một số bị lowercase. |
| `zipcode` | string | Mã zip 5 số. ~1% thiếu, ~1% bị cắt còn 4 số (lỗi format). |
| `property_type` | string | Single Family / Condo / Townhouse / Multi-Family / Land. ~15% bị dirty case/format (`SINGLE FAMILY`, `single family`, `Single_Family`, có khoảng trắng thừa). |
| `lot_size_sqft` | float | Diện tích đất (sqft). ~1% thiếu. |
| `living_area_sqft` | float | Diện tích sử dụng (sqft). `0`/thiếu với `property_type = Land`. Có outlier (~0.2% giá trị bị nhân 15-30 lần do lỗi nhập liệu). |
| `bedrooms` | float | Số phòng ngủ. Có outlier hiếm (giá trị âm hoặc >20). |
| `bathrooms` | float | Số phòng tắm (step 0.5). ~2% thiếu, có outlier hiếm (25-60). |
| `year_built` | float | Năm xây. ~4-5% thiếu (bao gồm toàn bộ `Land`). Có outlier hiếm (tương lai như 2040/2055, hoặc quá cũ như 1750). |
| `stories` | float | Số tầng (1-3, 0 với Land). |
| `garage_spaces` | float | Số chỗ đỗ garage (0-4). ~2% thiếu. |
| `has_pool` | string | Có hồ bơi không — **cố tình lẫn nhiều kiểu biểu diễn**: `Yes/No/Y/N/1/0/True/False` + ~2% rỗng. |
| `hoa_fee_monthly` | float | Phí HOA hàng tháng. **Thiếu nhiều (~60%)** — hợp lý vì nhiều nhà (đặc biệt Single Family/Land) không có HOA. |
| `school_rating` | float | Điểm trường học khu vực (1-10). ~6% thiếu. |
| `crime_index` | float | Chỉ số tội phạm khu vực (0-100, cao = tệ hơn). ~4% thiếu. |
| `distance_to_city_center_km` | float | Khoảng cách tới trung tâm thành phố (km). Có outlier hiếm (giá trị âm — lỗi nhập liệu). |
| `condition` | string | Poor / Fair / Good / Excellent. ~10% bị dirty case. |
| `days_on_market` | int | Số ngày rao bán trước khi bán được. Dùng để tạo `sold_within_30_days`. |
| `list_price` | mixed | Giá rao bán ban đầu. **~5% bị format thành chuỗi `$xxx,xxx`**, còn lại là số thuần. |
| `sale_price` | mixed | Giá bán cuối cùng — **target cho regression**. ~3% bị format `$xxx,xxx`. |
| `price_category` | string | **Target classification #1**: Low (<300k) / Medium (300-500k) / High (500-850k) / Luxury (>850k), suy ra từ `sale_price`. |
| `sold_within_30_days` | string | **Target classification #2**: Yes nếu `days_on_market <= 30`, ngược lại No. |

---

## 2. Các loại "dirty" có trong dataset (để luyện data cleaning)

1. **Missing values** — nhiều mức độ khác nhau tuỳ cột (xem bảng trên), có cột thiếu nhiều do bản chất dữ liệu (`hoa_fee_monthly`), có cột thiếu ngẫu nhiên (lỗi nhập liệu).
2. **Duplicate rows** — ~0.6% dòng bị lặp (cùng `property_id`, dữ liệu giống hệt) — luyện `drop_duplicates`.
3. **Inconsistent categorical values** — cùng 1 giá trị nhưng viết hoa/thường/gạch dưới/khoảng trắng thừa khác nhau (`city`, `state`, `property_type`, `condition`) — luyện `str.strip().str.lower()` / mapping chuẩn hoá.
4. **Inconsistent boolean representation** — `has_pool` có 8 cách biểu diễn khác nhau cho True/False — luyện viết hàm chuẩn hoá boolean.
5. **Inconsistent date format** — `listing_date` có 3 format khác nhau — luyện `pd.to_datetime` với `format=None`/dùng `dateutil` hoặc thử lần lượt các format.
6. **Mixed numeric/string trong cùng cột** — `list_price`, `sale_price` có một phần là số, một phần là chuỗi `"$xxx,xxx"` — luyện parse bằng regex/`str.replace` trước khi convert sang float.
7. **Outliers / lỗi nhập liệu hiếm gặp (~0.1-0.3% mỗi loại)** — năm xây dựng tương lai/quá xa, số phòng ngủ âm hoặc quá lớn, diện tích sống bất thường, khoảng cách âm, số phòng tắm phi thực tế — luyện phát hiện outlier bằng IQR/z-score và quyết định xử lý (loại bỏ/impute/clip).
8. **Zipcode sai định dạng** — thiếu hoặc chỉ còn 4 số — luyện validate theo regex.

---

## 3. Gợi ý dùng trong pipeline (mục 5-7 của tài liệu thiết kế)

- **Task `validate`**: check schema, đếm missing/outlier theo từng cột, log ra Airflow.
- **Task `preprocess`**: chuẩn hoá `has_pool`, `city`/`state`/`property_type`/`condition` case, parse `list_price`/`sale_price` về float, parse `listing_date` về datetime, xử lý outlier (clip hoặc loại bỏ), xử lý missing (impute median/mode hoặc giữ NaN tuỳ model), drop duplicate theo `property_id`.
- **Task `train`**: chọn 1 trong 2 hướng —
  - Regression: target = `sale_price` (hoặc `log(sale_price)` để giảm skew).
  - Classification: target = `price_category` (multi-class) hoặc `sold_within_30_days` (binary).
- **Feature Store**: các cột đã làm sạch (`living_area_sqft`, `bedrooms`, `school_rating`...) là ứng viên tốt để đưa vào feature store.
- **Drift Detection**: có thể tách dataset theo thời gian (`listing_date` sau khi parse) để làm baseline vs current, demo drift theo thời gian thực tế thay vì random split.
