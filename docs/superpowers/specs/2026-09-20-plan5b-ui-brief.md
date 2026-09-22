# Plan 5b — Brief thiết kế UI cho dashboard

Ngày: 2026-09-21. Đầu vào cho Plan 5b (bước 12 của lộ trình ở `mlops-pipeline-design.md` mục 10).
Nguồn sự thật cho hình dạng dữ liệu: phản hồi thật ghi ở Task 12 của Plan 5a, đo trên hệ thống đang chạy ngày 2026-09-21. Nguồn cho danh sách component: `2026-09-20-plan5a-api-design.md` mục 4.

## 0. Mở đầu

Đây là brief cho Claude design. Việc cần thiết kế là **dashboard của pipeline MLOps giá nhà**: một trang web điều khiển pipeline (chạy, theo dõi, xem log), quản dữ liệu (upload, xem trước), quản model (xem version, promote) và theo dõi drift. Dashboard là **một file HTML tự chứa** — React + Tailwind nạp qua CDN, Chart.js cho biểu đồ, không có bước build — và nó **chỉ** gọi `http://localhost:8001/api`. Nó không bao giờ gọi thẳng Airflow, MLflow hay MinIO.

Mọi khối JSON trong brief là **phản hồi thật** của API, chép nguyên văn từ Task 12. Không khối nào được tạo ra hay làm đẹp. Khi người ghi rút gọn một danh sách, chú thích ngay dưới khối nói rõ rút gọn ra sao; khối vẫn là JSON hợp lệ. Thứ chưa từng quan sát được trên hệ thống thật được ghi rõ là "chưa quan sát được" và mô tả bằng lời, không vẽ thành JSON.

> **Đọc trước khi thiết kế bất cứ thứ gì:** mục 5.1 nêu một **quyết định còn mở của chủ dự án** — dashboard ở dạng một file HTML gọi `http://localhost:8001/api` hiện **không chạy được** nếu mở từ `file://` hay từ origin khác, vì API chưa gửi header CORS và chưa phục vụ file tĩnh. Đừng thiết kế theo một cách triển khai chưa được chọn. Trong lúc chờ, dựng prototype bằng chính các khối JSON ở đây làm fixture.

Ngôn ngữ giao diện: tiếng Việt. Tên trường, giá trị enum (`ok`, `high`, `regression`...) và đường dẫn endpoint giữ nguyên như API trả về, không dịch.

---

## 1. Ba nguyên tắc thiết kế

Ba điều này là bài học **đo được** của Plan 4, không phải khẩu vị. Vi phạm một trong ba là bug thiết kế.

1. **`insufficient_data` phải trông khác `ok`.** Chưa đo được không phải là ổn. Performance drift luôn đến trễ vì ground truth (giá bán thật) đến sau lúc dự đoán; trong lúc đó chưa ai kiểm tra gì cả. Vẽ nó thành dấu xanh là dựng lại đúng lời nói dối mà Plan 4 mục 2.6 dựng ra để tránh. Cách vẽ: xám có **gạch chéo**, kèm chữ **"chưa đủ dữ liệu"**, tuyệt đối không dùng màu xanh. Xem mục 2.
2. **Ba loại drift hiện riêng, không gộp thành một badge.** `feature`, `prediction` và `performance` là ba phép đo khác nhau. Plan 4 đo được kịch bản `market_rally`: feature `ok` trong khi performance `high`. Một badge tổng hợp xanh ở đó sẽ nói dối. Đây là lý do mục Drift (mục 4.5) luôn có ba ô riêng.
3. **Mọi màn hình có empty state riêng.** Ngày đầu chưa có traffic thì mọi màn đều trống, và "trống" phải khác "hỏng". Hệ quả trực tiếp: mỗi màn hình phân biệt ba thứ mà người dùng dễ lẫn: **chưa có dữ liệu** (empty), **không tìm thấy** (404) và **hệ thống đang hỏng** (500 hoặc mất kết nối). Xem mục 3.2.

---

## 2. Bảng màu trạng thái: bốn trạng thái, không phải ba

`StatusBadge` có **bốn** trạng thái. Đây là các giá trị thật xuất hiện trong `parts` của drift (`ok`, `warning`, `high`, `insufficient_data`), và cũng là bộ dùng chung cho mọi nơi cần một mức độ.

| Trạng thái | Nhãn hiển thị | Nền | Chữ | Viền | Dấu phụ (không dựa vào màu) |
| --- | --- | --- | --- | --- | --- |
| `ok` | ổn | `#D1FAE5` (emerald-100) | `#065F46` (emerald-800) | `#059669` (emerald-600) | biểu tượng dấu tích, viền liền |
| `warning` | cảnh báo | `#FEF3C7` (amber-100) | `#92400E` (amber-800) | `#F59E0B` (amber-500) | biểu tượng tam giác chấm than, viền liền |
| `high` | cao | `#FEE2E2` (red-100) | `#991B1B` (red-800) | `#DC2626` (red-600) | biểu tượng dấu X trong vòng tròn, viền liền đậm |
| `insufficient_data` | **chưa đủ dữ liệu** | xám **gạch chéo**: `repeating-linear-gradient(45deg, #CBD5E1 0 4px, #F1F5F9 4px 8px)` | `#475569` (slate-600) | `#94A3B8` (slate-400), **nét đứt** | biểu tượng vòng tròn rỗng; luôn có đủ chữ "chưa đủ dữ liệu" |

Quy tắc:

- `insufficient_data` khác ba trạng thái còn lại ở **ba trục cùng lúc**: hoa văn (gạch chéo), viền (nét đứt) và chữ. Người mù màu và ảnh chụp đen trắng vẫn phải phân biệt được nó với `ok`.
- Không bao giờ dùng xanh lá hoặc dấu tích cho `insufficient_data`.
- Mọi badge luôn có **chữ nhãn**; màu không bao giờ là kênh duy nhất.
- Hoa văn gạch chéo **chỉ dành cho `insufficient_data`**. Đừng dùng nó cho thứ khác (ví dụ task chưa chạy), kẻo mất ý nghĩa.
- Tương phản chữ/nền tối thiểu 4.5:1 (các cặp trên đã chọn để đạt mức này).
- Trạng thái của **run và task** Airflow (`queued`, `running`, `success`, `failed`, `skipped`, và `null`) là một từ vựng khác, không nhét vào bốn trạng thái trên. Gợi ý: `success` dùng màu của `ok`; `failed` dùng màu của `high`; `running` xanh dương có chuyển động; `queued` xanh dương nhạt viền liền; `skipped` xám đặc, chữ gạch ngang (một task bị bỏ qua vì nhánh không được chọn thì **không phải lỗi**; nhưng khi cả run đang `failed`, các trạng thái `failed` phải nổi bật hơn `skipped`); `null` là "chưa chạy": viền xám rỗng, không hoa văn. Airflow còn hai trạng thái task **chưa quan sát được trong bằng chứng** (run hỏng duy nhất của Task 12 chỉ có `skipped`, vì nó bị đánh dấu `failed` bằng tay): `upstream_failed` (task phía sau một task lỗi, bị chặn; phải đọc là **hỏng/bị chặn**, dùng màu gần `high` nhưng khác `failed` bằng nhãn "bị chặn", không được vẽ như `skipped`) và `up_for_retry` (task lỗi và sẽ được thử lại; màu `warning`, nhãn "chờ thử lại"). Giá trị lạ không có trong danh sách: hiện nguyên chuỗi trong badge xám trung tính.
- Trạng thái dịch vụ ở `/health` là `ok` hoặc `down`: `ok` dùng màu `ok`, `down` dùng màu `high`. Trạng thái tổng `status` là `ok` hoặc `degraded`: `degraded` dùng màu `warning`.

---

## 3. Quy ước chung cho mọi màn hình

### 3.1. AppShell và HealthPill

`AppShell`: sidebar năm mục (Tổng quan, Stages & Logs, Dữ liệu, Models, Drift), topbar có `HealthPill`. `HealthPill` đọc `GET /api/health`.

Nguồn: `GET /api/health` → 200 (0,094 s), mọi dịch vụ đang ổn.

```json
{"status":"ok","services":{"airflow":"ok","mlflow":"ok","minio":"ok","serving":"ok","postgres":"ok"}}
```

Hình dạng khi có dịch vụ hỏng (chưa quan sát được trên hệ thống thật trong Task 12; đây là mô tả từ code của route, không phải phản hồi đo): `status` là `"degraded"` thay vì `"ok"`, và dịch vụ hỏng có giá trị `"down"` thay vì `"ok"`. `services` luôn có đúng năm khoá, theo thứ tự `airflow`, `mlflow`, `minio`, `serving`, `postgres`. Luôn là HTTP 200: `degraded` là trạng thái để đọc, không phải request hỏng.

Ràng buộc bắt buộc, đều là điều đã đo hoặc đã đọc từ code:

- **Tối đa một request `/health` đang bay, và không poll nhanh hơn mỗi 10 giây.** API trả lời trong khoảng 5 giây kể cả khi phụ thuộc bị treo, nhưng nếu hai request `/health` chồng lên nhau thì request thứ hai có thể báo **cả năm dịch vụ đều `down`** (lỗi đã biết, chưa sửa). Client phải chặn (`if (inFlight) return`), không dựa vào server.
- Hiện **năm dịch vụ riêng lẻ**, không chỉ một chấm tổng. Popover của `HealthPill` liệt kê từng dịch vụ.
- `postgres` được suy ra qua Airflow, nên nó luôn đọc `down` khi Airflow `down`. Popover ghi chú điều đó bên cạnh `postgres`, và đừng coi đó là hai sự cố độc lập.
- Nếu **chính request `/health` thất bại** (mất kết nối, timeout), pill hiện trạng thái riêng "không kết nối API" (xám đậm, không hoa văn), khác với `degraded`.
- Gợi ý giảm báo động giả: nếu cả năm dịch vụ cùng `down` ngay sau một lần đọc `ok`, đọc lại một lần sau 10 giây trước khi báo đỏ.

### 3.2. Hai loại lỗi phải khác nhau, và "trống" không phải lỗi

Hôm nay API phân biệt được "không tìm thấy" với "hệ thống hỏng", nên UI phải có **hai trạng thái lỗi riêng**, cộng thêm empty state:

| Tình huống | Dấu hiệu từ API | Hiển thị |
| --- | --- | --- |
| **Không tìm thấy** | HTTP 404, body là JSON có khoá `detail` (một chuỗi). Ngoại lệ: hai trường hợp ở dòng ngay dưới, nơi 404 là empty state | `NotFound`: "Không tìm thấy" kèm chuỗi `detail` nguyên văn. Đây không phải sự cố hạ tầng. |
| **Chưa có dữ liệu** (không phải lỗi) | `GET /drift/latest` trả 404 khi monitoring chưa từng chạy cho model đó; `GET /data/{dataset_version}/preview` trả 404 (`no dataset at version ...`) khi phiên bản dữ liệu chưa được tải lên, **cho phiên bản mặc định lẫn phiên bản người dùng gõ vào** (cùng mã, cùng nghĩa); `GET /drift/history` trả `{"history":[]}`; danh sách rỗng | `EmptyState`: nói vì sao trống và làm gì tiếp (drift: "chưa có báo cáo"; dữ liệu: "Chưa có dữ liệu ở phiên bản này" kèm nút tải lên). |
| **Dữ liệu gửi sai** | HTTP 422 | Thông báo ngay tại trường bị lỗi; UI nên ngăn được hầu hết trước khi gửi. Hai dạng `detail`, xem dưới. |
| **Hệ thống đang hỏng** | HTTP 500, hoặc `fetch` ném lỗi mạng (`TypeError`) | `ErrorState`: "Hệ thống đang hỏng", nút "Thử lại", và trỏ tới `HealthPill` để biết dịch vụ nào chết. |

Chi tiết cần biết khi viết lớp gọi API (một hàm `api()` dùng chung cho mọi request):

- Lỗi 500 của API trả **văn bản thuần** `Internal Server Error` (`Content-Type: text/plain`), **không phải JSON**. Không gọi `res.json()` một cách mù quáng trên response lỗi.
- `detail` có **hai dạng**: một chuỗi (`{"detail":"no dataset at version v9"}`) hoặc một mảng đối tượng kiểu FastAPI với `type`, `loc`, `msg`, `input` (422 do validate). Hiện `msg` và `loc` cho dạng mảng; hiện chuỗi cho dạng chuỗi.
- Lỗi mạng và request bị trình duyệt chặn vì CORS **giống hệt nhau** trong JavaScript (`TypeError: Failed to fetch`). Trạng thái "không kết nối" nên gợi ý cả hai khả năng: API không chạy, hoặc chưa giải quyết xong quyết định ở mục 5.1.
- `run_id` của Airflow chứa `:` và `+` (ví dụ `manual__2026-09-21T03:53:17.127926+00:00`). Luôn `encodeURIComponent(run_id)` khi đặt vào đường dẫn. Tên model cũng đi qua `encodeURIComponent`.

### 3.3. Bốn trạng thái của mỗi màn hình

Mỗi màn hình dưới đây mô tả đủ: **loading**, **empty**, **error** (không tìm thấy và hệ thống hỏng là hai thứ khác nhau), **có dữ liệu**. `LoadingSkeleton` bắt buộc ở mọi nơi: một lần chạy pipeline không tức thì (spec 5a ước tính khoảng 10 phút, **chưa đo**; Task 12 chỉ có một run 1000 dòng thành công trong khoảng 43 giây, xem `started_at`/`ended_at` ở khối JSON của mục 4.1, và chưa có số đo cho run toàn bộ dòng), không được để màn trắng. `RelativeTime` ("3 phút trước", tooltip giờ tuyệt đối) cho mọi mốc thời gian; API trả ISO 8601 có múi giờ.

### 3.4. Danh sách component dùng chung

`StatusBadge` (bốn trạng thái, mục 2) · `MetricTile` (số lớn, nhãn, hướng tốt/xấu) · `DataTable` (sort, filter, phân trang) · `EmptyState` · `ErrorState` (có hai biến thể: không tìm thấy / hệ thống hỏng) · `LoadingSkeleton` · `ConfirmDialog` · `Toast` · `RelativeTime`.

**Năm** thao tác ghi cần `ConfirmDialog`, và chúng đều là ghi thật:

| Thao tác | Endpoint | Khi nào có dialog |
| --- | --- | --- |
| Khởi động một lần train | `POST /pipeline/run` | Luôn luôn (mục 4.1, và từ nút retrain ở mục 4.5) |
| Đổi champion | `POST /models/{name}/{version}/promote` | Luôn luôn (mục 4.4) |
| Upload dataset | `POST /data/upload` | Chỉ khi phiên bản đích **đã tồn tại** (sẽ bị ghi đè âm thầm, mục 4.3) |
| Xoá một model version | `DELETE /models/{name}/{version}` | Luôn luôn (mục 4.4) |
| Xoá cả một model | `DELETE /models/{name}` | Luôn luôn (mục 4.4) |
| Tính drift thủ công | `POST /drift/run` | Luôn luôn (mục 4.5) |

Mọi `GET` không cần xác nhận.

> **Sửa ngày 2026-09-21.** Bản đầu của brief ghi "ba thao tác" và "không có thao tác
> xoá nào trong API". Chủ dự án sau đó yêu cầu thêm xoá model version và trigger
> drift thủ công, nên Plan 5b thêm ba endpoint vào `services/api/`:
> `DELETE /models/{name}/{version}`, `DELETE /models/{name}` và `POST /drift/run`.
> Xem mục 4.4 và 4.5.
>
> **Hai mức xoá, hai luật khác nhau.** Xoá một *version* đang giữ alias champion
> bị từ chối bằng **409**: nó để lại một model còn version nhưng không có gì để
> serve, trong khi promote version khác chỉ mất một cú bấm. Xoá *cả model* thì
> được phép kể cả khi nó kéo theo champion — kết quả là mạch lạc: model biến mất
> hẳn, và `serving` trả 503 `no champion loaded` (có sẵn từ Plan 3, không phải
> sửa gì). Chủ dự án chốt ngày 2026-09-21: phải xoá sạch được, còn lại thì chỉ
> cần hiện "chưa có model".

### 3.5. Nhịp lấy dữ liệu

| Dữ liệu | Khi nào lấy |
| --- | --- |
| `GET /health` | Mỗi ≥10 giây, một request một lúc (mục 3.1) |
| `GET /pipeline/runs` và `.../runs/{run_id}` | Lúc mở màn; poll khoảng 5 giây **chỉ khi** run đang xem là `queued` hoặc `running`, dừng khi `success` hoặc `failed` (gợi ý, không phải ràng buộc của API) |
| `GET /pipeline/runs/{run_id}/logs` | **Khi người dùng bấm.** Không stream, không tự làm mới. |
| `GET /data/{version}/preview` | **Chỉ khi người dùng mở màn Dữ liệu / bấm xem.** Không poll. Mỗi lần gọi tốn 1,4–2 giây và làm process API đạt đỉnh khoảng 0,9–1,3 GB RAM (đo ở Task 12). |
| `GET /models` | Lúc mở màn, và **sau mỗi lần promote** |
| `GET /drift/latest`, `/drift/history` | Lúc mở màn hoặc khi đổi model; nút làm mới thủ công. Không cần poll. |

### 3.6. Chỉ mục endpoint theo màn hình

| Endpoint | Màn hình |
| --- | --- |
| `GET /health` | AppShell (mọi màn) |
| `POST /pipeline/run` | Tổng quan (4.1), nút retrain ở Drift (4.5) |
| `GET /pipeline/runs` | Tổng quan (4.1), chọn run ở Stages & Logs (4.2) |
| `GET /pipeline/runs/{run_id}` | Tổng quan (4.1), Stages & Logs (4.2) |
| `GET /pipeline/runs/{run_id}/logs` | Stages & Logs (4.2) |
| `POST /data/upload` | Dữ liệu (4.3) |
| `GET /data/{dataset_version}/preview` | Dữ liệu (4.3) |
| `GET /models` | Models (4.4), chọn model ở Drift (4.5) |
| `POST /models/{name}/{version}/promote` | Models (4.4) |
| `GET /drift/latest` | Drift (4.5) |
| `GET /drift/history` | Drift (4.5) |

---

## 4. Năm màn hình

### 4.1. Tổng quan

**Mục đích:** chọn loại model, khởi động một lần chạy pipeline và thấy lần chạy gần nhất đang ở stage nào.

**Component:** `TaskTypeSelector` · `RunTriggerForm` (`task_type`, `estimator_name`, `force_reprocess`, `sample_rows`, `dataset_version`) · `PipelineStageStrip` · `RecentRunsTable`, cộng các component dùng chung.

> **Thêm ngày 2026-09-22: `estimator_name`.** DAG vốn đã nhận tham số này (mặc
> định `ridge` / `logistic`), nhưng `RunRequest` của API thì chưa, nên dashboard
> không có đường gửi. Nay có: dropdown "Thuật toán", danh sách lấy từ
> **`GET /api/estimators`** — endpoint đọc thẳng `ml_common.estimators`, để
> dropdown không thể lệch khỏi thứ stage `train` thật sự chấp nhận. Bỏ trống ô
> này thì không gửi `estimator_name` và DAG tự chọn mặc định, nhờ vậy mặc định
> chỉ nằm ở một chỗ duy nhất. Hai estimator `hist_gradient_boosting_weak` và
> `dummy` sinh ra để test cổng promote chứ không phải để thắng, nên endpoint
> đánh dấu chúng ở khoá `diagnostic` và dropdown xếp riêng vào nhóm "Chỉ để
> test cổng promote". API trả **422** nếu estimator không thuộc `task_type` đã
> chọn (ví dụ `random_forest` cho regression), thay vì để stage `train` chết
> sau vài phút.

**Endpoint:** `POST /pipeline/run`, `GET /pipeline/runs`, `GET /pipeline/runs/{run_id}`.

#### RunTriggerForm và trường `sample_rows`

| Trường | Kiểu và luật của API | Ghi chú thiết kế |
| --- | --- | --- |
| `task_type` | **Bắt buộc.** `"regression"` hoặc `"classification"`; thiếu hoặc sai là 422. | `TaskTypeSelector` là nút chọn một trong hai. Gợi ý: không chọn sẵn, vì đây là một lần train thật. |
| `force_reprocess` | Boolean, mặc định `false`. | Nhãn "Xử lý lại dữ liệu từ đầu". |
| `sample_rows` | Số nguyên **> 0**, hoặc `null`/vắng mặt = **dùng toàn bộ dòng**. `0` và số âm bị từ chối bằng 422 (khai báo `gt=0` trong route; chưa được gọi thử trực tiếp ở Task 12). | Đây là **số dòng dùng để train** (lấy N dòng đầu của file). Bật/tắt "Dùng toàn bộ dòng" thay vì để người dùng gõ `0`. Với dataset `v1` toàn bộ là 2.012.000 dòng: cần cảnh báo trong dialog xác nhận rằng run toàn bộ dòng lâu hơn và tốn RAM hơn nhiều so với run nhỏ (máy 16 GB). Đừng ghi một con số phút cụ thể vào câu chữ của dialog: spec 5a ước tính khoảng 10 phút nhưng con số này chưa đo. |
| `dataset_version` | Chuỗi, mặc định `"v1"`. Route này **không** kiểm định dạng; phiên bản không tồn tại sẽ chỉ hỏng ở stage `extract` (chưa quan sát được). | Áp cùng luật với upload: `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`. API **không có endpoint liệt kê các phiên bản dữ liệu**, nên đây là ô nhập chữ, không phải dropdown. |

**Đừng để `sample_rows` (số dòng của lần train) trông giống `rows` của màn Dữ liệu (số dòng xem trước, tối đa 200).** Khác nhãn, khác vị trí, khác màn hình. Xem 4.3.

**`ConfirmDialog` bắt buộc** trước khi gọi `POST /pipeline/run`, vì nó khởi động một lần train thật. Dialog nêu đủ **năm** tham số sẽ gửi — gồm `estimator_name` (hoặc "mặc định của pipeline") và đặc biệt `sample_rows`: "toàn bộ dòng" hay "N dòng" — và nút xác nhận đặt tên rõ ("Bắt đầu train"), không phải "OK".

Nguồn: `POST /api/pipeline/run`, body `{"task_type":"regression","sample_rows":1000}` → 200. Run mới chỉ ở trạng thái `queued`: chưa chạy xong; thời gian chạy phụ thuộc số dòng.

```json
{"run_id":"manual__2026-09-21T03:53:17.127926+00:00","dag_id":"ml_pipeline","state":"queued"}
```

Nguồn: cùng endpoint, body `{}` → 422 (dạng mảng của FastAPI).

```json
{"detail":[{"type":"missing","loc":["body","task_type"],"msg":"Field required","input":{}}]}
```

Cảnh báo về DAG paused (rủi ro chưa quan sát trực tiếp, nêu để thiết kế xử lý): ở trạng thái gốc mà Task 12 đo, DAG `ml_pipeline` đang **paused** và người đo phải bỏ paused bằng tay (ngoài API) trước khi gọi trigger. API không có endpoint bỏ paused, và phản hồi 200/`queued` ở trên không cho biết DAG có paused hay không. Vì vậy một run `queued` quá lâu có thể chỉ là DAG đang paused. Gợi ý: sau khoảng một phút vẫn `queued`, hiện ghi chú "Run đang chờ. Nếu DAG `ml_pipeline` đang bị paused trong Airflow thì run sẽ không bắt đầu."

#### RecentRunsTable

Nguồn: `GET /api/pipeline/runs?limit=3` → 200. Danh sách đầy đủ 3 phần tử; mới nhất trước. Lưu ý `task_type` là `null` với run được chạy tay từ Airflow UI (không có conf): hiện "—" hoặc "không rõ", không hiện chữ `null`.

```json
{"runs":[{"run_id":"manual__2026-09-20T13:34:28+00:00","state":"success","task_type":"regression","started_at":"2026-09-20T13:38:01.213139+00:00","ended_at":"2026-09-20T13:38:44.575244+00:00"},{"run_id":"manual__2026-09-19T00:00:00+00:00","state":"success","task_type":null,"started_at":"2026-09-19T00:00:00+00:00","ended_at":"2026-09-19T10:54:50.443051+00:00"},{"run_id":"manual__2026-09-18T00:00:00+00:00","state":"failed","task_type":null,"started_at":"2026-09-18T00:00:00+00:00","ended_at":"2026-09-19T08:41:19.536365+00:00"}]}
```

Cột gợi ý: `run_id` (chữ mono, cắt giữa, có nút sao chép), `state`, `task_type`, `started_at`, `ended_at`, thời lượng (tính từ hai mốc). Chọn một hàng thì `PipelineStageStrip` hiện run đó (mặc định là run mới nhất). `ended_at` có thể `null` với run đang chạy (chưa quan sát được trên phản hồi thật; xử lý phòng thủ).

#### PipelineStageStrip: đọc đúng thứ tự và trạng thái `null`

Hai điều đã đo được ở `GET /pipeline/runs/{run_id}`:

1. **Mảng `tasks` KHÔNG theo thứ tự pipeline.** Trong ví dụ dưới, khi run đang chạy, `extract` nằm **cuối** mảng. UI phải sắp theo một danh sách cố định các tên stage, không tin thứ tự API trả về.
2. **Task chưa bắt đầu có `"state": null`** (kèm `try_number` 0 và `duration` `null`). `null` nghĩa là **"chưa chạy"**, không phải lỗi, không phải `skipped`.

Thứ tự cố định (tên thật của 9 task trong DAG `ml_pipeline`, lấy từ phản hồi thật):

```
extract → validate → prepare_dataset_for_train → train → evaluate → branch_on_gates
    → nhánh đạt cổng: register → deploy
    → nhánh không đạt: stop_no_deploy
```

`branch_on_gates` chọn **đúng một** trong hai nhánh; nhánh còn lại sẽ có `state` là `skipped`, đó là chuyện bình thường, không phải lỗi. Đừng lẫn với `upstream_failed` (các task phía sau một stage đã lỗi, xem mục 2): loại này là hỏng/bị chặn. Cả `upstream_failed` và `up_for_retry` là trạng thái của Airflow chưa quan sát được trong bằng chứng. Dải stage vẽ chín ô theo thứ tự trên, nhánh `register → deploy` và `stop_no_deploy` đặt song song sau `branch_on_gates`. (Spec 5a mục 4 nói "7 stage"; API thực tế trả 9 task, và brief này theo API.) `duration` tính bằng giây (số thực) hoặc `null`; `try_number` lớn hơn 1 nghĩa là task đã chạy lại, hiện kèm "lần thử N".

Nguồn: `GET /api/pipeline/runs/{run_id}` → 200, ngay sau khi trigger. Run `queued`, mọi task `state: null`.

```json
{"run_id":"manual__2026-09-21T03:53:17.127926+00:00","state":"queued","tasks":[{"task_id":"extract","state":null,"try_number":0,"duration":null},{"task_id":"validate","state":null,"try_number":0,"duration":null},{"task_id":"prepare_dataset_for_train","state":null,"try_number":0,"duration":null},{"task_id":"train","state":null,"try_number":0,"duration":null},{"task_id":"evaluate","state":null,"try_number":0,"duration":null},{"task_id":"branch_on_gates","state":null,"try_number":0,"duration":null},{"task_id":"register","state":null,"try_number":0,"duration":null},{"task_id":"stop_no_deploy","state":null,"try_number":0,"duration":null},{"task_id":"deploy","state":null,"try_number":0,"duration":null}]}
```

Nguồn: cùng endpoint → 200, khi đang chạy. `extract` là phần tử cuối của mảng.

```json
{"run_id":"manual__2026-09-21T03:53:17.127926+00:00","state":"running","tasks":[{"task_id":"validate","state":null,"try_number":0,"duration":null},{"task_id":"prepare_dataset_for_train","state":null,"try_number":0,"duration":null},{"task_id":"train","state":null,"try_number":0,"duration":null},{"task_id":"evaluate","state":null,"try_number":0,"duration":null},{"task_id":"branch_on_gates","state":null,"try_number":0,"duration":null},{"task_id":"register","state":null,"try_number":0,"duration":null},{"task_id":"stop_no_deploy","state":null,"try_number":0,"duration":null},{"task_id":"deploy","state":null,"try_number":0,"duration":null},{"task_id":"extract","state":"running","try_number":1,"duration":null}]}
```

Nguồn: cùng endpoint → 200, sau khi run bị đánh dấu `failed` (`extract` thành công, tám task còn lại `skipped`; chú ý `validate` có `try_number` 1 còn các task `skipped` khác có `try_number` 0).

```json
{"run_id":"manual__2026-09-21T03:53:17.127926+00:00","state":"failed","tasks":[{"task_id":"register","state":"skipped","try_number":0,"duration":0.0},{"task_id":"extract","state":"success","try_number":1,"duration":1.534837},{"task_id":"prepare_dataset_for_train","state":"skipped","try_number":0,"duration":0.0},{"task_id":"train","state":"skipped","try_number":0,"duration":0.0},{"task_id":"evaluate","state":"skipped","try_number":0,"duration":0.0},{"task_id":"branch_on_gates","state":"skipped","try_number":0,"duration":0.0},{"task_id":"stop_no_deploy","state":"skipped","try_number":0,"duration":0.0},{"task_id":"deploy","state":"skipped","try_number":0,"duration":0.0},{"task_id":"validate","state":"skipped","try_number":1,"duration":0.0}]}
```

Nguồn: `GET /api/pipeline/runs/does-not-exist-live1` → 404.

```json
{"detail":"no run 'does-not-exist-live1' in DAG 'ml_pipeline'"}
```

#### Các trạng thái

| Trạng thái | Nội dung |
| --- | --- |
| Loading | Skeleton cho bảng run và dải stage. Nút "Bắt đầu train" chuyển thành đang gửi và bị khoá để không bấm đúp. |
| Empty | Chưa có run nào (mảng `runs` rỗng; chưa quan sát được trên hệ thống thật): "Chưa có lần chạy nào. Chọn loại model và bắt đầu train." Dải stage khi chưa chọn run nào: chín ô "chưa chạy". |
| Lỗi: không tìm thấy | Run được chọn không còn (404 với `detail` như trên): `NotFound`, kèm nút quay về danh sách. |
| Lỗi: hệ thống hỏng | 500 hoặc mất kết nối (Airflow chết thì `list_runs` cũng 500): `ErrorState` "Hệ thống đang hỏng". Lỗi khi trigger thì `Toast` thất bại, **không** báo thành công. |
| Có dữ liệu | Bảng run, dải stage của run chọn, thời lượng từng task. Trigger thành công: `Toast` hiện `run_id`, thêm run vào bảng ở trạng thái `queued` và chọn nó. |

---

### 4.2. Stages & Logs

**Mục đích:** đọc log của một stage trong một lần chạy, lọc theo mức và từ khoá.

**Component:** `StageTabs` · `LogFilterBar` (run / stage / level / từ khoá) · `LogViewer`, cộng các component dùng chung.

**Endpoint:** `GET /pipeline/runs/{run_id}/logs` (và `GET /pipeline/runs`, `GET /pipeline/runs/{run_id}` để chọn run và biết `try_number`).

Ghi chú về component: spec 5a liệt kê stage là một phần của `LogFilterBar`; ở đây stage được chọn qua `StageTabs` đặt ở đầu thanh lọc, và `LogFilterBar` thêm ô chọn **run** (lấy từ `GET /pipeline/runs`), vì log luôn thuộc về một run cụ thể.

#### Tham số và những điều đã biết cứng

- `stage` **bắt buộc**; thiếu là 422. Giá trị là `task_id` của mục 4.1. `StageTabs` là chín tab theo thứ tự cố định đó.
- `level` lọc theo **từ nguyên** (`level=ERROR` không khớp dòng "no errors found"), không phân biệt hoa thường. `q` lọc theo chuỗi con, không phân biệt hoa thường. Cả hai làm **ở server**, UI không lọc lại bằng JS. Ô chọn `level` gợi ý: Tất cả / INFO / WARNING / ERROR.
- **`try_number`: luôn truyền đúng số mà phản hồi chi tiết run báo cho task đó.** Mặc định của API là `1` (lần thử đầu tiên), có thể đã cũ nếu task từng chạy lại. Chỉ gọi log khi `try_number ≥ 1`; với `0` (task chưa chạy hoặc bị bỏ qua chưa bao giờ bắt đầu), không gọi mà hiện "chưa chạy, chưa có log". Tab của task có `state: null` nên bị làm mờ.
- **Một lần thử không có log KHÔNG phải 404.** Airflow trả 200 và chính chuỗi báo lỗi của Airflow ("*** Could not read served logs: ...") quay về dưới dạng các dòng log. UI phải nhận ra điều này: nếu các dòng bắt đầu bằng `*** Could not read served logs` hay `*** !!!! Please make sure`, hiện banner cảnh báo "Airflow không có log cho lần thử này" và làm mờ các dòng đó, đừng trình bày như một log thật. (Đây là lưới an toàn bằng so khớp chuỗi, mong manh; cách phòng chính là truyền đúng `try_number`.)
- **Log không lọc không có vị trí dòng cố định cho "phần của task".** Thứ tự đã quan sát ở log `extract`: dòng 1 là tên máy chạy (ví dụ `e59fd8ef0e61`, hoặc rỗng ở log của task `skipped`); rồi `*** Found local files:` và một dòng đường dẫn file log; rồi các dòng của **bộ chạy task của Airflow** (ví dụ `::group::Pre task execution logs`, "Dependencies all met", "Starting attempt 1 of 1", "Executing <Task(DockerOperator): extract>", `Running: ['airflow', 'tasks', 'run', ...]`); rồi mới tới output của chính stage (ví dụ dòng `XCOM_RESULT ...`). Có thể còn các dòng đánh dấu nhóm khác như `::endgroup::`; phần được ghi lại của Task 12 không cho thấy chúng, nên chưa xác nhận. Vì vậy đừng hứa "N dòng đầu là hệ thống" và đừng làm mờ theo vị trí dòng. **`level` và `q` là cách chính để tới nội dung** (ví dụ `q=fingerprint` trả đúng một dòng ở dữ liệu thật): đặt hai điều khiển đó nổi bật trong `LogFilterBar`, coi log không lọc là dạng xem thô đầy đủ. Nếu muốn làm mờ, chỉ làm theo nội dung (ví dụ dòng bắt đầu bằng `***`), không theo vị trí.
- **Chỉ log của `extract` (thành công) và `validate` (bị `skipped`, thuộc run đã bị đánh dấu `failed` bằng tay) đã được quan sát.** Log của `prepare_dataset_for_train`, `train`, `evaluate`, `register` (các stage DockerOperator còn lại), của `branch_on_gates` và `deploy` (PythonOperator), và của `stop_no_deploy` (EmptyOperator) **chưa từng được quan sát** và có thể trông khác hoặc rỗng. Thiết kế chín tab đồng nhất không được giả định tab nào cũng có banner, có dòng runner của Airflow hay có output; log rỗng hoặc rất ngắn là một trạng thái hợp lệ (xem empty state (d) bên dưới).
- `truncated: true` nghĩa là log bị cắt ở 2.000 dòng (`MAX_LOG_LINES` trong route). UI phải **nói ra** ("Đã cắt ở 2.000 dòng, hãy lọc để thấy phần còn lại"), không im lặng hiển thị thiếu.
- Log lấy **khi người dùng bấm "Tải log"**, không stream, không tự làm mới.
- API trả log là mảng chuỗi thô. Mức log (INFO/WARNING/ERROR) do UI nhận ra từ nội dung dòng để tô màu; dạng dòng thật là `[thời gian] {file:dòng} MỨC - nội dung`.

Nguồn: `GET /api/pipeline/runs/{run_id}/logs?stage=extract` → 200 (0,127 s, 3.440 byte).

```json
{"lines":["e59fd8ef0e61","*** Found local files:","***   * /opt/airflow/logs/dag_id=ml_pipeline/run_id=manual__2026-09-21T03:53:17.127926+00:00/task_id=extract/attempt=1.log","[2026-09-21T03:53:17.910+0000] {local_task_job_runner.py:123} INFO - ::group::Pre task execution logs","[2026-09-21T03:53:17.931+0000] {taskinstance.py:2613} INFO - Dependencies all met for dep_context=non-requeueable deps ti=<TaskInstance: ml_pipeline.extract manual__2026-09-21T03:53:17.127926+00:00 [queued]>","[2026-09-21T03:53:17.941+0000] {taskinstance.py:2613} INFO - Dependencies all met for dep_context=requeueable deps ti=<TaskInstance: ml_pipeline.extract manual__2026-09-21T03:53:17.127926+00:00 [queued]>","[2026-09-21T03:53:17.942+0000] {taskinstance.py:2866} INFO - Starting attempt 1 of 1","[2026-09-21T03:53:17.955+0000] {taskinstance.py:2889} INFO - Executing <Task(DockerOperator): extract> on 2026-09-21 03:53:17.127926+00:00","[2026-09-21T03:53:17.963+0000] {logging_mixin.py:190} WARNING - /home/airflow/.local/lib/python3.12/site-packages/airflow/task/task_runner/standard_task_runner.py:70 DeprecationWarning: This process (pid=944) is multi-threaded, use of fork() may lead to deadlocks in the child.","[2026-09-21T03:53:17.963+0000] {standard_task_runner.py:104} INFO - Running: ['airflow', 'tasks', 'run', 'ml_pipeline', 'extract', 'manual__2026-09-21T03:53:17.127926+00:00', '--job-id', '52', '--raw', '--subdir', 'DAGS_FOLDER/ml_pipeline_dag.py', '--cfg-path', '/tmp/tmpxkf365fr']"],"truncated":false}
```

Danh sách rút gọn: 10 trong 24 dòng đầu, nguyên văn từ phản hồi thật (người ghi bỏ 14 dòng cuối; `truncated` giữ nguyên là `false`). Các dòng 2 và 3 là banner của Airflow.

Nguồn: cùng endpoint với `q=fingerprint` → 200. Lọc ở server, còn đúng một dòng.

```json
{"lines":["[2026-09-21T03:53:19.138+0000] {docker.py:438} INFO - XCOM_RESULT {\"fingerprint\": \"3b318b364660175f\", \"row_count\": 1000}"],"truncated":false}
```

Nguồn: `stage=validate`, task đã bị `skipped` → 200. Log của task bị bỏ qua chỉ có banner và các dòng của bộ chạy task Airflow, không có output của stage; dòng 1 rỗng. Hiện nó như một log bình thường kèm ghi chú "task đã bị bỏ qua".

```json
{"lines":["","*** Found local files:","***   * /opt/airflow/logs/dag_id=ml_pipeline/run_id=manual__2026-09-21T03:53:17.127926+00:00/task_id=validate/attempt=1.log","[2026-09-21T03:53:19.834+0000] {local_task_job_runner.py:123} INFO - ::group::Pre task execution logs","[2026-09-21T03:53:19.847+0000] {taskinstance.py:2603} INFO - Dependencies not met for <TaskInstance: ml_pipeline.validate manual__2026-09-21T03:53:17.127926+00:00 [skipped]>, dependency 'Task Instance State' FAILED: Task is in the 'skipped' state.","[2026-09-21T03:53:19.855+0000] {local_task_job_runner.py:166} INFO - Task is not able to be run"],"truncated":false}
```

Nguồn: `stage=extract&try_number=9`, lần thử không tồn tại → **200, KHÔNG phải 404**. Đây là văn bản lỗi của Airflow nằm trong `lines`.

```json
{"lines":["e59fd8ef0e61","*** !!!! Please make sure that all your Airflow components (e.g. schedulers, webservers, workers and triggerer) have the same 'secret_key' configured in 'webserver' section and time is synchronized on all your machines (for example with ntpd)","See more at https://airflow.apache.org/docs/apache-airflow/stable/configurations-ref.html#secret-key","*** Could not read served logs: 403 Client Error: FORBIDDEN for url: http://e59fd8ef0e61:8793/log/dag_id=ml_pipeline/run_id=manual__2026-09-21T03:53:17.127926+00:00/task_id=extract/attempt=9.log",""],"truncated":false}
```

Nguồn: `stage=no_such_stage`, run có thật → 404. Stage không tồn tại trong run.

```json
{"detail":"no log for task 'no_such_stage', attempt 1, of run 'manual__2026-09-21T03:53:17.127926+00:00'"}
```

Nguồn: run không tồn tại, `.../runs/does-not-exist-live1/logs?stage=extract` → 404.

```json
{"detail":"no log for task 'extract', attempt 1, of run 'does-not-exist-live1'"}
```

Nguồn: thiếu `stage` → 422.

```json
{"detail":[{"type":"missing","loc":["query","stage"],"msg":"Field required","input":null}]}
```

Theo ghi chú của Task 12, một run vừa trigger mà `extract` chưa bắt đầu cũng có thể cho 404 ở endpoint log (log chưa tồn tại). Vì vậy UI không nên gọi log cho task có `state` là `null`.

#### Các trạng thái

| Trạng thái | Nội dung |
| --- | --- |
| Loading | Chưa chọn stage: gợi ý chọn run và stage. Đang tải (khoảng 0,1 giây): vài dòng skeleton trong khung mono. |
| Empty | Ba loại khác nhau: (a) task `null` hoặc `try_number` 0: "chưa chạy, chưa có log", không gọi API; (b) bộ lọc không khớp dòng nào (`lines` rỗng; chưa quan sát được trên hệ thống thật): "Không có dòng nào khớp bộ lọc" kèm nút xoá lọc; (c) log của task `skipped` chỉ có banner và dòng của bộ chạy task Airflow, không có output của stage; (d) log rỗng hoặc gần rỗng của task không sinh output (chưa quan sát được, đặc biệt `stop_no_deploy`, `branch_on_gates`, `deploy`): "Task này không có output", không phải lỗi. |
| Lỗi: không tìm thấy | 404 (run hoặc stage không tồn tại): `NotFound` với `detail` nguyên văn. |
| Lỗi: hệ thống hỏng | 500 hoặc mất kết nối (Airflow không trả lời): `ErrorState` "Hệ thống đang hỏng", nút thử lại. Phân biệt rõ với 404 ở trên. |
| Có dữ liệu | `LogViewer` chữ mono, tô màu theo mức, banner khi `truncated`, đếm "N dòng". Có thể có banner "không có log cho lần thử này" (ở trên). |

Màn này **không có thao tác ghi**, nên không có `ConfirmDialog`.

---

### 4.3. Dữ liệu

**Mục đích:** tải một CSV thô lên làm phiên bản dữ liệu mới và xem nó chứa gì (mẫu dòng, tỉ lệ thiếu, số giá trị ngoài biên của từng cột).

**Component:** `DatasetUploader` (kéo thả, tiến độ, báo lỗi khi vượt trần) · `DataPreviewTable` · `ColumnStatsTable` (missing %, out-of-bounds) · `RowLimitPicker`, cộng các component dùng chung.

**Endpoint:** `POST /data/upload`, `GET /data/{dataset_version}/preview`.

#### DatasetUploader: luật của API

- Chỉ nhận file **`.csv`** (đuôi khác là 422). Trường form `dataset_version` **bắt buộc**, khớp `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` (không có `/`; sai là 422). Kiểm ngay ở client.
- **Trần 500 MiB** (524.288.000 byte); vượt là 413. **Chưa quan sát được trên hệ thống thật**: vì kích hoạt nó cần upload hơn 500 MiB trên ổ C gần đầy. Theo code, body lỗi có khoá `detail` là chuỗi `upload exceeds the 524288000 byte limit` (chưa từng thấy phản hồi thật này, nên không vẽ thành khối JSON).
- Toàn bộ body upload được server ghi tạm xuống đĩa **trước** khi trần có thể từ chối. Nghĩa là trần chỉ được kiểm sau khi cả file đã tới nơi. Vì thế UI **không được** mời người dùng tải lên file lớn hơn trần mà không cảnh báo: kiểm `file.size` ở client và khoá nút tải lên (kèm giải thích) khi vượt 524.288.000 byte. Trần không được API công bố, nên đặt thành một hằng số có chú thích trong file HTML.
- **Upload vào phiên bản đã tồn tại sẽ ghi đè âm thầm** (không có 409). Vì vậy trước khi gửi, UI kiểm phiên bản đã có chưa, bằng một lần `GET /data/{dataset_version}/preview?rows=1`: 200 nghĩa là đã tồn tại, 404 nghĩa là chưa. Chỉ kiểm khi người dùng bấm tải lên (không kiểm theo từng phím gõ, vì preview tốn 1–2 giây và khoảng 1 GB RAM cho phiên bản lớn). Nếu 200: `ConfirmDialog` ghi đè, nêu `total_rows` của bản hiện có. Nếu 404: tải lên luôn, không cần dialog. Nếu kiểm ra lỗi khác: dialog với cảnh báo "không xác định được phiên bản này đã tồn tại chưa".
- Tiến độ: `fetch` không báo tiến độ tải lên; dùng `XMLHttpRequest` (`upload.onprogress`) hoặc một thanh không xác định. Sau khi byte cuối được gửi, server còn phải chuyển CSV sang parquet: hiện "Đang chuyển sang parquet". Thời gian này chưa đo với file lớn.
- Trong phản hồi, `size_mb` là dung lượng file **parquet** đã lưu, không phải CSV đã tải. Đừng gắn nhãn nó là "kích thước file".
- Theo code, 422 còn xảy ra khi CSV không đọc được hoặc chỉ có tiêu đề không có dòng (`could not parse the CSV: ...`, `the CSV has no data rows`); hai thông báo này chưa được quan sát trên hệ thống thật.

Nguồn: `POST /api/data/upload` (multipart, một CSV 4 dòng, `dataset_version=t12-upload-check`) → 200.

```json
{"dataset_version":"t12-upload-check","rows":4,"size_mb":0.01}
```

Nguồn: upload file `.txt` → 422 (`detail` là chuỗi).

```json
{"detail":"only .csv uploads are accepted"}
```

Nguồn: upload với `dataset_version=a/b` → 422 (`detail` là mảng; `loc` chỉ tới trường lỗi).

```json
{"detail":[{"type":"string_pattern_mismatch","loc":["body","dataset_version"],"msg":"String should match pattern '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'","input":"a/b","ctx":{"pattern":"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"}}]}
```

Nguồn: upload không có `dataset_version` → 422.

```json
{"detail":[{"type":"missing","loc":["body","dataset_version"],"msg":"Field required","input":null}]}
```

#### Preview: điều phải nói thật với người dùng

`GET /data/{dataset_version}/preview?rows=N` trả `total_rows`, `stats_rows`, `sample` và `columns`.

- **Thống kê chỉ tính trên `stats_rows` dòng đầu (200.000), còn `total_rows` là tổng của cả file.** Luôn hiện "thống kê trên **200.000 / 2.012.000** dòng" ngay cạnh `ColumnStatsTable` (số thật lấy từ `stats_rows` và `total_rows`, định dạng `vi-VN`). File nhỏ thì hai số bằng nhau (ví dụ 4 / 4). Đầu file có thể không đại diện cho cả file.
- **`sample` là dòng THÔ.** Mọi giá trị là chuỗi, và một ô thiếu là chuỗi rỗng `""`, **không phải `null`**. Hiện ô rỗng bằng một dấu hiệu nhìn thấy được (ví dụ chip "(trống)"), không để ô trắng trơn lẫn với ô chưa tải. Trong hai dòng mẫu của khối JSON dưới đây, cùng một cột xuất hiện với các cách viết khác nhau: `property_type` (`CONDO`, `Single_Family`), `has_pool` (`0`, `False`) và `listing_date` (`10/18/2021`, `2024-06-03`). Đó là dữ liệu bẩn thật: hiện nguyên văn, đừng chuẩn hoá trên UI. Hai dòng mẫu này không chứng minh điều đó cho các cột khác (chẳng hạn `condition`, `price_category`).
- **`missing_rate` ở đây đếm cả chuỗi rỗng là thiếu** (dữ liệu thật: `hoa_fee_monthly` khoảng 63,2%). Stage `validate` của pipeline chỉ đếm giá trị `null`, nên con số ở đây có thể **cao hơn** con số trong báo cáo của `validate` trên cùng dữ liệu. Đó là khác biệt đã biết; nếu UI đặt hai số cạnh nhau, phải giải thích.
- `out_of_bounds` là **số dòng** (trong `stats_rows` dòng đầu) có giá trị ngoài biên hợp lệ của cột. Nó không bị ảnh hưởng bởi khác biệt trên.
- `columns` đã sắp theo tên; `kind` thấy trong dữ liệu thật: `numeric`, `categorical`, `boolean`, `money`, `date`, `id`, `zipcode`. `missing_rate` là số thực từ 0 đến 1 (hiện thành phần trăm).
- **`rows` (kích thước xem trước, tối đa 200; lớn hơn thì bị hạ xuống 200 âm thầm) và `sample_rows` (số dòng một lần train dùng, mục 4.1) là hai điều khác nhau.** `RowLimitPicker` chỉ điều khiển số dòng mẫu hiển thị. Đặt nó ở đây, gắn nhãn "Số dòng xem trước", cách xa mọi nhãn có chữ "train". Gợi ý cụ thể: gọi API **một lần** với `rows=200`, và để `RowLimitPicker` cắt bớt ở phía client (10 / 50 / 100 / 200). Như vậy đổi lựa chọn không gây thêm lần gọi 1–2 giây và ~1 GB.
- Mỗi lần gọi preview tốn khoảng 1,4–2 giây và làm process API đạt đỉnh khoảng 0,9–1,3 GB RAM (Task 12, trên phiên bản `v1`; hai người mở cùng lúc thì cộng dồn). Chỉ gọi khi người dùng mở màn này hoặc bấm xem; **không bao giờ poll**.
- API **không có endpoint liệt kê phiên bản dữ liệu**. Màn này không thể có dropdown "chọn phiên bản": dùng một ô nhập `dataset_version` (mặc định `v1`) và gợi nhớ các phiên bản vừa tải lên bằng `localStorage` nếu muốn (chỉ là tiện ích, không phải nguồn sự thật).

Nguồn: `GET /api/data/v1/preview?rows=2` → 200 (2,04 s, 3.188 byte), dataset thật `v1`.

```json
{"total_rows":2012000,"stats_rows":200000,"sample":[{"property_id":"189380","listing_date":"10/18/2021","city":"Houston","state":"TX","zipcode":"16444","property_type":"CONDO","lot_size_sqft":"9632.620047925273","living_area_sqft":"620.0872753252422","bedrooms":"5.0","bathrooms":"3.0","year_built":"1941.0","stories":"2.0","garage_spaces":"2.0","has_pool":"0","hoa_fee_monthly":"442.1107181209878","school_rating":"3.0","crime_index":"1.7851112811668841","distance_to_city_center_km":"4.1892985681763815","condition":"Good","days_on_market":"11","list_price":"203474.7","sale_price":"175922.77","price_category":"Low","sold_within_30_days":"Yes"},{"property_id":"48062","listing_date":"2024-06-03","city":"Philadelphia","state":"PA","zipcode":"19009","property_type":"Single_Family","lot_size_sqft":"9283.685180461389","living_area_sqft":"1736.0294929005188","bedrooms":"3.0","bathrooms":"2.5","year_built":"1900.0","stories":"2.0","garage_spaces":"2.0","has_pool":"False","hoa_fee_monthly":"","school_rating":"5.0","crime_index":"40.50933159238418","distance_to_city_center_km":"0.39896970698237505","condition":"Good","days_on_market":"7","list_price":"305872.61","sale_price":"325256.06","price_category":"Medium","sold_within_30_days":"Yes"}],"columns":[{"name":"bathrooms","kind":"numeric","missing_rate":0.02021,"out_of_bounds":332},{"name":"bedrooms","kind":"numeric","missing_rate":0.0,"out_of_bounds":295},{"name":"city","kind":"categorical","missing_rate":0.0,"out_of_bounds":0},{"name":"condition","kind":"categorical","missing_rate":0.0,"out_of_bounds":0},{"name":"crime_index","kind":"numeric","missing_rate":0.03978,"out_of_bounds":0},{"name":"days_on_market","kind":"numeric","missing_rate":0.0,"out_of_bounds":0},{"name":"distance_to_city_center_km","kind":"numeric","missing_rate":0.0,"out_of_bounds":384},{"name":"garage_spaces","kind":"numeric","missing_rate":0.01978,"out_of_bounds":0},{"name":"has_pool","kind":"boolean","missing_rate":0.019905,"out_of_bounds":0},{"name":"hoa_fee_monthly","kind":"numeric","missing_rate":0.632155,"out_of_bounds":0},{"name":"list_price","kind":"money","missing_rate":0.0,"out_of_bounds":0},{"name":"listing_date","kind":"date","missing_rate":0.08055,"out_of_bounds":0},{"name":"living_area_sqft","kind":"numeric","missing_rate":0.005165,"out_of_bounds":109},{"name":"lot_size_sqft","kind":"numeric","missing_rate":0.01003,"out_of_bounds":0},{"name":"price_category","kind":"categorical","missing_rate":0.0,"out_of_bounds":0},{"name":"property_id","kind":"id","missing_rate":0.0,"out_of_bounds":0},{"name":"property_type","kind":"categorical","missing_rate":0.0,"out_of_bounds":0},{"name":"sale_price","kind":"money","missing_rate":0.0,"out_of_bounds":0},{"name":"school_rating","kind":"numeric","missing_rate":0.058665,"out_of_bounds":0},{"name":"sold_within_30_days","kind":"boolean","missing_rate":0.0,"out_of_bounds":0},{"name":"state","kind":"categorical","missing_rate":0.0,"out_of_bounds":0},{"name":"stories","kind":"numeric","missing_rate":0.0,"out_of_bounds":0},{"name":"year_built","kind":"numeric","missing_rate":0.03956,"out_of_bounds":452},{"name":"zipcode","kind":"zipcode","missing_rate":0.009295,"out_of_bounds":0}]}
```

`rows=2` nên `sample` có 2 dòng; `columns` đủ 24 cột. Chú ý dòng thứ hai của `sample`: `hoa_fee_monthly` là `""`. Trong `columns`, 11 cột có `missing_rate` khác 0.

Nguồn: `GET /api/data/v9/preview` → 404 (phiên bản chưa được tải lên). Đây là **empty state** (mục 3.2), không phải lỗi.

```json
{"detail":"no dataset at version v9"}
```

Nguồn: `GET /api/data/v1/preview?rows=0` → 422.

```json
{"detail":[{"type":"greater_than","loc":["query","rows"],"msg":"Input should be greater than 0","input":"0","ctx":{"gt":0}}]}
```

#### Các trạng thái

| Trạng thái | Nội dung |
| --- | --- |
| Loading | Upload: thanh tiến độ, rồi "Đang chuyển sang parquet". Preview: skeleton bảng (1,4–2 giây, không được để trắng). |
| Empty | Chưa chọn phiên bản: "Nhập phiên bản dữ liệu để xem, hoặc tải một CSV lên." **Preview trả 404 là empty state, không phải lỗi**, với mọi phiên bản (phiên bản mặc định `v1` hay phiên bản người dùng gõ vào ô nhập, cùng mã, cùng nghĩa): "Chưa có dữ liệu ở phiên bản này" (nêu tên phiên bản) kèm nút "Tải lên phiên bản này". |
| Lỗi: dữ liệu nhập sai | 422 (tên phiên bản sai định dạng, `rows` không hợp lệ): thông báo ngay tại ô nhập, không phải trang lỗi. Màn này không có trạng thái "không tìm thấy" riêng: 404 của preview là empty state ở dòng trên. |
| Lỗi: hệ thống hỏng | 500 hoặc mất kết nối (object storage không trả lời): `ErrorState`. Upload hỏng giữa chừng: `Toast` thất bại, **không** báo đã tải lên; phiên bản có thể chưa được ghi. |
| Có dữ liệu | `DataPreviewTable` (bảng cuộn ngang, 24 cột), `ColumnStatsTable`, dòng ghi "thống kê trên N / M dòng", `RowLimitPicker`. Upload thành công: `Toast` với `rows`, `size_mb`, và nút "Xem trước". |

**`ConfirmDialog`:** chỉ khi tải lên một phiên bản **đã tồn tại** (ghi đè, không hoàn tác). Tải lên phiên bản mới không cần dialog.

---

### 4.4. Models

**Mục đích:** xem các version của từng model kèm metric thật, và chuyển champion sang một version khác.

**Component:** `ModelVersionTable` (cột metric đổi theo `task_type`) · `ChampionBadge` · `PromoteButton`, cộng `MetricTile` và các component dùng chung.

**Endpoint:** `GET /models`, `POST /models/{name}/{version}/promote`.

#### Metric: đọc khoá động, không bao giờ giả định một bộ cố định

`metrics` là **những khoá thật** của model đó. Với `regression`: `rmse`, `mae`, `r2`. Với `classification`: `f1`, `accuracy`, `auc` (đo được đúng thứ tự này ở lần gọi thật; thứ tự khoá **không cố định**). Cột của `ModelVersionTable` và các `MetricTile` phải sinh ra từ các khoá trong dữ liệu (hợp của các khoá trên mọi version của model), không viết cứng `accuracy`/`f1`; đó chính là lỗi của bản frontend cũ mà spec đang sửa.

Hướng tốt/xấu cho `MetricTile` (gợi ý thiết kế, **API không trả thông tin này**): `rmse`, `mae` thấp hơn là tốt hơn; `r2`, `accuracy`, `auc`, `f1` cao hơn là tốt hơn. Khoá lạ: hiện giá trị trung tính, không mũi tên. Giá trị là số thực dài (ví dụ `98175.10328533906`): định dạng gọn khi hiển thị, giữ giá trị thô ở tooltip.

Các sự thật khác của dữ liệu:

- `versions` đã sắp mới nhất trước; `version` là **chuỗi** (`"3"`). Nếu UI tự sắp lại, sắp theo số, không theo chữ (`"10"` phải lớn hơn `"9"`).
- Trong dữ liệu thật mỗi model có đúng một version `is_champion: true`. Champion **không nhất thiết** là version có metric tốt nhất, và hai version có thể có metric giống hệt nhau (ở dữ liệu thật, version 2 và 3 của `house_price_regressor` trùng số).
- `created_at` là ISO 8601 có múi giờ.

Nguồn: `GET /api/models` → 200 (0,090 s). Đầy đủ, hai model.

```json
{"models":[{"name":"house_needs_renovation_classifier","task_type":"classification","versions":[{"version":"1","metrics":{"f1":0.1046831955922865,"accuracy":0.756128064032016,"auc":0.6468311259876465},"is_champion":true,"created_at":"2026-09-19T10:49:51.116000+00:00"}]},{"name":"house_price_regressor","task_type":"regression","versions":[{"version":"3","metrics":{"rmse":98175.10328533906,"mae":64040.68658593348,"r2":0.9475422335571709},"is_champion":true,"created_at":"2026-09-19T09:12:56.485000+00:00"},{"version":"2","metrics":{"rmse":98175.10328533906,"mae":64040.68658593348,"r2":0.9475422335571709},"is_champion":false,"created_at":"2026-09-19T08:55:40.454000+00:00"},{"version":"1","metrics":{"rmse":204970.66113894654,"mae":147923.18956396583,"r2":0.7713398598310879},"is_champion":false,"created_at":"2026-09-19T08:55:05.143000+00:00"}]}]}
```

Nếu registry chưa có model nào, phản hồi là `models` rỗng (chưa quan sát được trên hệ thống thật).

#### Promote là ghi thật lên Model Registry

`PromoteButton` chỉ xuất hiện trên các hàng **không phải** champion. Quy trình bắt buộc:

1. Bấm nút → **`ConfirmDialog`** (bắt buộc). Nội dung nêu rõ: "Chuyển champion của `house_price_regressor` từ v3 sang v2". Phải nói thêm: alias đổi **ngay** trong Registry, nhưng dịch vụ `serving` chỉ nạp lại champion lúc khởi động hoặc khi được gọi `/reload`, và API này không có endpoint reload, nên serving có thể vẫn trả lời bằng model cũ cho tới lúc đó (đọc từ code của route promote và của serving; chưa kiểm bằng thực nghiệm).
2. Trong lúc gửi: khoá nút, hiện đang gửi. Không cập nhật lạc quan (không tự đổi badge trước khi có phản hồi).
3. Thành công (200): `Toast` thành công **và gọi lại `GET /models`** để vẽ theo dữ liệu thật; không tự sửa state cục bộ.
4. Thất bại: `Toast` thất bại, **không bao giờ báo thành công**, rồi cũng gọi lại `GET /models` để thấy trạng thái thật.
   - 404: model hoặc version không còn (hai `detail` dưới đây).
   - 422: `version` không phải số nguyên (chỉ nhận toàn chữ số; UI luôn gửi số nên hiếm khi gặp).
   - 500 hoặc mất kết nối: "Registry không trả lời; chưa rõ alias đã đổi hay chưa": hiển thị bằng dữ liệu vừa tải lại.

Nguồn: `POST /api/models/house_price_regressor/2/promote` → 200 (thành công; body chỉ là xác nhận, không chứa dữ liệu mới).

```json
{"name":"house_price_regressor","version":"2","alias":"champion"}
```

Nguồn: `.../house_price_regressor/99/promote` → 404 (version không tồn tại).

```json
{"detail":"cannot promote: RESOURCE_DOES_NOT_EXIST: Model Version (name=house_price_regressor, version=99) not found"}
```

Nguồn: `.../no_such_model/1/promote` → 404 (model không tồn tại).

```json
{"detail":"cannot promote: RESOURCE_DOES_NOT_EXIST: Registered Model with name=no_such_model not found"}
```

Nguồn: `.../house_price_regressor/abc/promote` → 422 (version không phải số).

```json
{"detail":[{"type":"string_pattern_mismatch","loc":["path","version"],"msg":"String should match pattern '^[0-9]+$'","input":"abc","ctx":{"pattern":"^[0-9]+$"}}]}
```

#### Các trạng thái

| Trạng thái | Nội dung |
| --- | --- |
| Loading | Skeleton cho bảng version và các ô metric. Khi đang promote: nút của hàng đó ở trạng thái đang gửi, các nút promote khác bị khoá. |
| Empty | Registry chưa có model nào: "Chưa có model. Chạy pipeline để train model đầu tiên" kèm liên kết sang Tổng quan. |
| Lỗi: không tìm thấy | Chỉ phát sinh khi promote (404 ở trên): `Toast` lỗi cụ thể, không thay cả trang. |
| Lỗi: hệ thống hỏng | `GET /models` 500 hoặc mất kết nối (MLflow chết): `ErrorState` "Hệ thống đang hỏng". |
| Có dữ liệu | Mỗi model một khối: tên, `task_type`, `MetricTile` của champion, `ModelVersionTable` với `ChampionBadge` và `PromoteButton`. |

---

### 4.5. Drift

**Mục đích:** cho biết dự đoán của model đang chạy có còn đáng tin không, bằng ba phép đo tách biệt: feature, prediction, performance.

**Component:** `SeverityOverview` (**tách ba loại**) · `DriftHistoryChart` · `EvidentlyReportFrame` · `RetrainCTA` · `InsufficientDataNotice`, cộng `MetricTile`, `StatusBadge` và các component dùng chung.

**Bổ sung 2026-09-22 — `TrafficSimulator`.** Một khối riêng nằm **trên** khối
Drift: dropdown năm kịch bản (tên lấy từ `GET /scenarios`, nhãn tiếng Việt ở
`SCENARIO_META`), ô số request (1–5000, đúng trần của API), nút "Gửi traffic",
và một badge trạng thái tự poll `GET /simulate/status` mỗi 5 giây trong lúc run
còn `queued`/`running`. Lý do có badge: nếu chỉ báo "queued" thì người dùng
không biết lúc nào traffic đã thật sự nằm trong inference log để bấm tính drift
— đúng kiểu mơ hồ mà mục này vốn đã phải chống. `task_type` **không** là một ô
chọn riêng: nó lấy từ model đang chọn ở khối Drift, nên traffic luôn đi tới
đúng model đang xem.

**Ba loại drift đổi tên trên giao diện (2026-09-22).** Khoá của API giữ nguyên
(`feature` / `prediction` / `performance`), nhưng nhãn hiển thị là **Data
drift** / **Model drift** / **Performance drift**, mỗi nhãn kèm một dòng nói nó
so sánh cái gì (`DRIFT_FACTORS` trong `constants.js`). Tên cũ là từ vựng của
stage `monitor`, không phải từ vựng của người đọc màn hình.

**Endpoint:** `GET /drift/latest`, `GET /drift/history` (và `GET /models` để có danh sách `model_name`), cùng `POST /drift/run`, `GET /scenarios`, `POST /simulate`, `GET /simulate/status` (bổ sung 2026-09-21 và 2026-09-22).

Mọi request drift bắt buộc có `model_name` (thiếu là 422). Ô chọn model lấy từ `GET /models`.

#### Đọc một bản tóm tắt drift

Một `summary` gồm: `model_name`, `model_version`, `task_type`, `run_id` (mã theo thời gian của lần tính, dạng `20260920T075645`, **không phải** run id của Airflow), `computed_at`, `window_hours`, `severity`, `parts`, `n_predictions`, `n_ground_truth`, `current_metrics`, `report_key`.

- **`parts` có ba khoá `feature`, `prediction`, `performance`, mỗi khoá một trong bốn trạng thái.** `SeverityOverview` vẽ **ba ô riêng**, mỗi ô một `StatusBadge`. Đây là nguyên tắc 2. `parts.performance` có thể là `insufficient_data` và phải **trông khác `ok`** (nguyên tắc 1): ground truth đến trễ.
- `severity` là mức tệ nhất trong các phần **đã đo được**; `insufficient_data` bị bỏ qua khi lấy mức tệ nhất (`overall_severity` trong `common/ml_common/drift.py`). Vì thế nó có thể là `high` khi `performance` chưa đo được (thấy ở dữ liệu thật bên dưới). Khi **cả ba** phần đều `insufficient_data` thì `severity` chính là `insufficient_data` (không phải `ok`, vì `ok` sẽ khẳng định một phép kiểm chưa từng xảy ra); trường hợp này có trong code nhưng **chưa thấy** trong 12 bản tóm tắt thật, nơi `severity` chỉ là `ok`, `warning` hoặc `high`. Nên `severity` cũng có thể cần vẽ bằng trạng thái `insufficient_data` (gạch chéo). Nếu hiện `severity` thì hiện như một dòng phụ nhỏ hơn ba ô ("mức cao nhất trong các phép đo đã có"), **không bao giờ** như một badge tổng lớn. Nếu `severity` là `ok` mà có phần `insufficient_data`, đừng hiện nó bằng màu `ok`: chỉ hiện ba ô.
- `n_ground_truth` là số kết quả thật đã ghép được với dự đoán; `n_predictions` là số dự đoán trong cửa sổ `window_hours` (giờ). Trong 12 bản tóm tắt thật của `house_price_regressor`, **2 bản** có `performance` là `insufficient_data`: `n_ground_truth` là 0 (`run_id` `20260920T074759`) và 33 (`run_id` `20260920T073734`), cả hai dưới ngưỡng bên dưới, và **ở cả hai bản đó `current_metrics` là `{}`** (đã kiểm từng bản); 10 bản còn lại có `current_metrics` gồm `rmse`, `mae`, `r2`. Đó là quan sát trên 12 bản, không phải luật của API: thiết kế phải xử lý cả hai trường hợp, `current_metrics` có khoá (hiện `MetricTile`) hoặc rỗng (không hiện ô nào). Ngưỡng tối thiểu của monitor mặc định là 50 dòng ghép được (`MONITOR_MIN_GROUND_TRUTH`, Plan 4 mục 2.6); con số này **không có trong phản hồi API**, nên đừng viết cứng nó ở chỗ khác ngoài câu giải thích.
- `current_metrics` có khoá **động** giống metric của model (regression: `rmse`, `mae`, `r2`). Hiện bằng `MetricTile`, sinh từ khoá có trong dữ liệu. Không có khoá thì không hiện ô nào.
- `report_key` trỏ tới file HTML của Evidently trong object storage. **API không có endpoint nào phục vụ file đó** (spec 5a nói API không proxy nó). Xem `EvidentlyReportFrame` dưới đây.
- Phản hồi không cho biết nó có phải bản mới nhất hay không: chỉ `run_id` và `computed_at` là dấu hiệu. Luôn hiện `computed_at` bằng `RelativeTime` cạnh `SeverityOverview`.

Nguồn: `GET /api/drift/latest?model_name=house_price_regressor` → 200. `feature` là `ok` trong khi `prediction` và `performance` là `high`, nên chính ba ô tách biệt mới cho thấy bức tranh đầy đủ.

```json
{"model_name":"house_price_regressor","model_version":"3","task_type":"regression","run_id":"20260920T075645","computed_at":"2026-09-20T07:56:45.249085+00:00","window_hours":0.045,"severity":"high","parts":{"feature":"ok","prediction":"high","performance":"high"},"n_predictions":500,"n_ground_truth":500,"current_metrics":{"rmse":305791.86789740255,"mae":184188.3288157089,"r2":0.5677294118532599},"report_key":"reports/house_price_regressor/20260920T075645/evidently.html"}
```

Nguồn: `GET /api/drift/history?model_name=house_price_regressor&limit=2` → 200.

```json
{"history":[{"model_name":"house_price_regressor","model_version":"3","task_type":"regression","run_id":"20260920T075645","computed_at":"2026-09-20T07:56:45.249085+00:00","window_hours":0.045,"severity":"high","parts":{"feature":"ok","prediction":"high","performance":"high"},"n_predictions":500,"n_ground_truth":500,"current_metrics":{"rmse":305791.86789740255,"mae":184188.3288157089,"r2":0.5677294118532599},"report_key":"reports/house_price_regressor/20260920T075645/evidently.html"},{"model_name":"house_price_regressor","model_version":"3","task_type":"regression","run_id":"20260920T075608","computed_at":"2026-09-20T07:56:08.134449+00:00","window_hours":1.0,"severity":"high","parts":{"feature":"ok","prediction":"ok","performance":"high"},"n_predictions":3300,"n_ground_truth":3200,"current_metrics":{"rmse":167855.74049911226,"mae":93692.52982905749,"r2":0.8800899177082595},"report_key":"reports/house_price_regressor/20260920T075608/evidently.html"}]}
```

Danh sách rút gọn theo `limit=2`: 2 phần tử mới nhất, nguyên văn từ phản hồi thật (mặc định `limit=20` trả cả 12 bản tóm tắt hiện có). Mới nhất trước, nên `DriftHistoryChart` phải **đảo thứ tự** khi vẽ theo thời gian. Phần tử đầu trùng với `latest`.

Nguồn: một phần tử của `GET /api/drift/history?model_name=house_price_regressor` (mặc định `limit=20`, trả 12 phần tử) → 200, gọi đọc-chỉ ngày 2026-09-21. Đây là một trong **2** phần tử (trong 12) có `performance` là `insufficient_data`: phần tử thứ 3 tính từ mới nhất, `n_ground_truth` là 0, `current_metrics` là `{}`, trong khi `severity` vẫn là `high` do `prediction` cao:

```json
{"history":[{"model_name":"house_price_regressor","model_version":"3","task_type":"regression","run_id":"20260920T074759","computed_at":"2026-09-20T07:47:59.264677+00:00","window_hours":0.029,"severity":"high","parts":{"feature":"warning","prediction":"high","performance":"insufficient_data"},"n_predictions":100,"n_ground_truth":0,"current_metrics":{},"report_key":"reports/house_price_regressor/20260920T074759/evidently.html"}]}
```

Danh sách rút gọn: 1 trong 12 phần tử (`run_id` là `20260920T074759`), nguyên văn từ phản hồi thật, bọc lại trong `{"history":[...]}` để giữ đúng hình dạng phản hồi. (Phần tử `insufficient_data` còn lại, thứ 10 trong 12, không được dán ở đây: `run_id` `20260920T073734`, `feature` `high`, `prediction` `high`, `performance` `insufficient_data`, `n_predictions` 33, `n_ground_truth` 33, và `current_metrics` cũng là `{}`; đã kiểm lại bằng lần GET đọc-chỉ ngày 2026-09-21.)

Nguồn: `GET /api/drift/latest?model_name=house_needs_renovation_classifier` → **404**. Đây là **empty state, không phải lỗi**: monitoring chưa từng chạy cho model này.

```json
{"detail":"no drift report yet for house_needs_renovation_classifier"}
```

Nguồn: `GET /api/drift/history?model_name=house_needs_renovation_classifier` → 200, lịch sử rỗng.

```json
{"history":[]}
```

Nguồn: `GET /api/drift/latest` không có `model_name` → 422.

```json
{"detail":[{"type":"missing","loc":["query","model_name"],"msg":"Field required","input":null}]}
```

Nguồn: `GET /api/drift/history?...&limit=0` → 422.

```json
{"detail":[{"type":"greater_than","loc":["query","limit"],"msg":"Input should be greater than 0","input":"0","ctx":{"gt":0}}]}
```

#### DriftHistoryChart

Vẽ bằng Chart.js. **Ba dải riêng** (feature, prediction, performance) — mỗi dải là **một biểu đồ riêng, màu riêng, xếp dọc** (sửa ngày 2026-09-22: bản đầu vẽ ba đường cùng màu xám trên một trục nên không phân biệt được đường nào là gì) — chạy theo thời gian `computed_at`, mỗi điểm tô đúng màu và hoa văn của trạng thái tại thời điểm đó; **không** một đường tổng hợp. Điểm `insufficient_data` vẽ là ô xám gạch chéo (một khoảng trống có nhãn, không phải điểm ở mức thấp). Tooltip: `run_id`, `n_predictions`, `n_ground_truth`, `window_hours`, và `current_metrics` nếu có. Các cửa sổ có độ dài khác nhau (từ 0,03 đến 1 giờ trong dữ liệu thật), nên tooltip phải cho thấy `n_predictions` để người xem không so sánh mù các điểm.

**Sửa ngày 2026-09-22 — làm cho biểu đồ kết luận được.** Ba thay đổi, sau khi
chủ dự án nhận xét "mấy cái mốc thời gian khó hiểu, nhìn graph không kết luận
được gì":

1. **Trục x chỉ còn giờ:phút**, ngày chuyển thành **vạch đứt dọc** ở đúng chỗ
   sang ngày mới (plugin `dayDividers` viết tại chỗ, không thêm thư viện). Lý
   do: các điểm cách đều nhau vì mỗi điểm là *một lần đo*, không phải một mốc
   thời gian — lặp lại "20/9/26" dưới hai mươi điểm chỉ che mất chuyện hai
   trong số các khoảng cách đó rộng bằng mấy ngày.
2. **Một dòng kết luận bằng chữ** phía trên (`DriftVerdictLine`): bao nhiêu
   trong 5 lần đo gần nhất ở mức cao, mức nào vừa đổi so với lần trước, và
   cảnh báo khi lịch sử gồm nhiều `model_version` — hai model khác nhau nằm
   trên cùng một đường thì thay đổi giữa chúng không phải là xu hướng. Toàn bộ
   logic nằm ở `src/lib/driftReading.js` dạng hàm thuần, **không** tự đặt
   ngưỡng nào: mức vẫn là mức API trả về.
3. **Một dải số thật** (`MetricTrendChart`): `rmse` (regression) hoặc `auc`
   (classification) theo từng lần đo, kèm đường nét đứt là chỉ số lúc train lấy
   từ `reference_metrics` (xem addendum 2026-09-22 của spec Plan 4). Ba mức
   phân loại không trả lời được "sai hơn bao nhiêu"; dải này trả lời được.

#### InsufficientDataNotice

Hiện khi `parts.performance` là `insufficient_data`. Nội dung ý: "Chưa đủ kết quả thật để đo performance drift (`n_ground_truth` = N). Kết quả thật đến trễ hơn dự đoán. Đây **không phải** là ổn: chưa ai kiểm tra." Đặt ngay dưới ô performance, cùng hoa văn gạch chéo.

#### Báo cáo có thể chưa cập nhật (Plan 4 còn nợ một race)

Plan 4 còn một race chưa sửa ở bước ghi bộ đệm (spec 5a mục 10): ngay sau khi có traffic mới, báo cáo drift có thể chưa gồm những dự đoán vừa gửi. Ngoài ra `monitoring_dag` chạy theo giờ và được tạo ở trạng thái **paused** (Plan 4 mục 2.7, và Task 12 thấy nó vẫn paused), nên báo cáo mới nhất có thể cũ hàng giờ. Thiết kế phải có một dòng ghi chú luôn hiện: "Báo cáo tính lúc `computed_at`. Traffic mới gửi có thể chưa được ghi và chưa có trong báo cáo này." kèm nút "Tải lại". Gợi ý: nếu `computed_at` cách hiện tại quá khoảng 2 giờ, gắn chip "báo cáo cũ". **Cập nhật 2026-09-22:** hai câu cuối không còn đúng. Dashboard có nút "Tính drift ngay" (`POST /drift/run`) và khối `TrafficSimulator` (`POST /simulate`), `monitoring_dag` đã unpaused, nên cả việc gửi traffic lẫn việc tính lại drift đều làm được từ màn này.

#### EvidentlyReportFrame: chưa có endpoint

Không có endpoint nào trả nội dung file Evidently, và dashboard **không được** trỏ iframe tới MinIO (vi phạm nguyên tắc chỉ nói chuyện với API). Cho tới khi Plan 5b (hoặc chủ dự án) quyết định cách phục vụ file này, thiết kế `EvidentlyReportFrame` thành một **ô giữ chỗ**: hiện `report_key` dạng văn bản có nút sao chép và dòng "Báo cáo Evidently đầy đủ chưa xem được từ dashboard". Đây là một điểm hở đã được đánh dấu, không phải một component bị bỏ quên.

#### RetrainCTA

Hiện khi `severity` là `high`. Nó **không** tự train (auto-retrain đã bị loại từ Plan 4 mục 6.2: cảnh báo, người quyết định). Bấm nút chuyển sang màn Tổng quan với `RunTriggerForm` được điền sẵn `task_type` lấy từ `summary.task_type`; việc xác nhận nằm ở `ConfirmDialog` của form đó (mục 4.1).

#### Các trạng thái

| Trạng thái | Nội dung |
| --- | --- |
| Loading | Skeleton cho ba ô và biểu đồ. |
| Empty | `latest` 404 và `history` rỗng: "Chưa có báo cáo drift cho model này. `monitoring_dag` chưa chạy lần nào (mặc định nó ở trạng thái paused; bật trong Airflow)." Không hiện lỗi. Ngày đầu chưa có traffic thì mọi màn đều rơi vào trạng thái này. |
| Lỗi: không tìm thấy | Với màn này 404 của `latest` **là empty**, không phải `NotFound`. |
| Lỗi: hệ thống hỏng | 500 hoặc mất kết nối (object storage không trả lời): `ErrorState` "Hệ thống đang hỏng". |
| Có dữ liệu | Ba ô riêng, `RelativeTime` của `computed_at`, `MetricTile` cho `current_metrics`, `DriftHistoryChart`, ghi chú "có thể chưa cập nhật", `InsufficientDataNotice` khi cần, `RetrainCTA` khi `high`, ô giữ chỗ Evidently. |

**`ConfirmDialog`:** màn này không tự ghi. Đường retrain đi qua `ConfirmDialog` của `POST /pipeline/run` ở màn Tổng quan.

---

## 5. Ràng buộc kỹ thuật

### 5.1. Quyết định còn mở: dashboard chạy ở đâu và gọi API kiểu gì

**Đây là một quyết định của chủ dự án. Brief này cố ý không chọn hộ.**

Sự thật đã kiểm trong code của API (`services/api/`):

- API **không gửi bất kỳ header CORS nào** (không có `CORSMiddleware`).
- API **không phục vụ file tĩnh** (không có `StaticFiles`).

Hệ quả trong trình duyệt, với một file HTML gọi `http://localhost:8001/api`:

- Mở file từ `file://`, hoặc phục vụ nó từ một origin khác (bất kỳ cổng nào khác `8001`, hay `python -m http.server`): trình duyệt **chặn phản hồi**. Với JavaScript đó chỉ là `TypeError: Failed to fetch`, không có thông báo nào giải thích.
- `POST /pipeline/run` mang body JSON (`Content-Type: application/json`) nên kích hoạt **preflight `OPTIONS`**; API không xử lý nó nên request bị chặn ngay ở đó. Upload multipart và promote (không có body) là request "đơn giản" nên không bị preflight, nhưng phản hồi của chúng vẫn không đọc được, và request vẫn tới server (một thao tác ghi có thể được thực hiện dù trang không đọc được kết quả). Lưu ý: điểm này và điểm preflight ở trên là **suy ra từ luật CORS của trình duyệt, chưa được thử trong một trình duyệt thật**.

Plan 5b vì vậy cần **một** trong hai:

- **(a) API tự phục vụ file HTML** từ cùng origin (`http://localhost:8001/`). Câu hỏi CORS biến mất vì không còn request cross-origin. Nhưng (a) tự nó **không** giải quyết việc API không có xác thực: bất kỳ ai tới được cổng `8001` vẫn gọi được các endpoint ghi. Đây là hướng brief khuyến nghị; quyết định vẫn thuộc chủ dự án.
- **(b) Thêm `CORSMiddleware`** để một origin khác gọi được. Đây là một **quyết định bảo mật**. Mở CORS mở rộng những gì một trang ở origin khác được **đọc** (phản hồi của mọi endpoint, gồm dữ liệu và `detail` của lỗi) và cho phép nó gửi request JSON (như `POST /pipeline/run`) qua preflight. Riêng việc **gửi** một số request ghi "đơn giản" (upload multipart, promote không body) từ một trang web bất kỳ tới `localhost:8001` là rủi ro do thiếu xác thực và, theo luật CORS của trình duyệt (chưa thử), tồn tại ở **cả hai hướng**: CORS quyết định trang có đọc được phản hồi hay không, không phải request có tới được server hay không. Hướng (b) vì vậy cần chọn danh sách origin cụ thể, không dùng "cho phép tất cả".

Điều này để mở có chủ ý, vì CORS là quyết định bảo mật và Plan 5a không có xác thực. **Đừng thiết kế dựa trên một cách triển khai không chạy được.** Yêu cầu dành cho thiết kế:

- Đặt địa chỉ gốc API ở **một hằng số duy nhất** đầu file (ví dụ `const API_BASE = "http://localhost:8001/api"`), để chuyển sang `/api` tương đối nếu chọn (a) mà không sửa chỗ nào khác.
- Đừng phụ thuộc vào `file://` hay vào bất kỳ cách mở file cụ thể nào.
- Trạng thái "không kết nối" (mục 3.2) gợi ý cả hai nguyên nhân: API không chạy, hoặc quyết định này chưa xong.
- Dựng prototype bằng chính các khối JSON trong brief làm fixture, không cần API chạy.

### 5.2. Ràng buộc còn lại

- **Một file HTML tự chứa.** React + Tailwind qua CDN, Chart.js cho biểu đồ, **không có bước build**. JSX cần Babel chạy trong trình duyệt hoặc dùng `React.createElement`/`htm`; chọn cách nào tuỳ thiết kế, miễn không có bước build. Ghim phiên bản CDN cụ thể, không dùng `latest`.
- **Chỉ gọi `${API_BASE}`.** Tuyệt đối không có `localhost:8080` (Airflow), `localhost:5000` (MLflow), `localhost:9000` hay `9001` (MinIO) trong file. Plan 5b sẽ có bước grep kiểm điều này, giống cách `verify_serving.ps1` grep tìm import bị cấm. Lý do: credential không được lộ ra frontend, và mỗi lần đổi backend chỉ được phép sửa `services/api/`.
- **Mọi request đi qua một hàm `api()` duy nhất** thực hiện phân loại lỗi ở mục 3.2 và `encodeURIComponent` cho tham số đường dẫn. Dùng `AbortController` với timeout: `/health` khoảng 6 giây (API tự giới hạn 5 giây), các request khác khoảng 30 giây; upload không giới hạn cứng.
- **Không có xác thực ở giai đoạn này** (mọi endpoint có sẵn một dependency rỗng `require_auth()`); UI không có màn đăng nhập.
- **Ưu tiên màn hình laptop** (chiều ngang từ khoảng 1280 px); bảng rộng (24 cột của preview) cuộn ngang bên trong khung, không làm cả trang cuộn ngang.
- Định dạng số theo `vi-VN` (`2.012.000`); thời gian dùng `RelativeTime`.

---

## 6. Những thứ cố ý KHÔNG có

- **Không stream log theo thời gian thực.** Log lấy khi bấm, không WebSocket, không tự làm mới.
- **Không xác thực.** Không đăng nhập, không API key ở giai đoạn này (đã hoãn có chủ đích, xem mục 5.1 về hệ quả với CORS).
- **Không Feature Store.**
- Không auto-retrain: drift chỉ cảnh báo, người quyết định.
- Không gọi thẳng Airflow, MLflow, MinIO.
- Không liệt kê phiên bản dữ liệu, không xoá hay đổi tên dữ liệu (API không có endpoint).
- Không **bật/tắt** DAG (`ml_pipeline`, `monitoring_dag`), không gọi `/reload` của serving, không gửi traffic cho model (đó là việc của agent). Từ 2026-09-21 dashboard **trigger** được `monitoring_dag` qua `POST /drift/run`, nhưng vẫn không bật/tắt DAG: cả hai DAG được để unpaused sẵn ở tầng hạ tầng, vì một run của DAG paused sẽ nằm `queued` vĩnh viễn mà không có tín hiệu nào báo lý do.
- Không nhúng báo cáo Evidently cho tới khi có cách phục vụ nó (mục 4.5).
- Không chuẩn hoá hay làm sạch dữ liệu trên UI: preview hiển thị dữ liệu thô đúng như đã lưu.
