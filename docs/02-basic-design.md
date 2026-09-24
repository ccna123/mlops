# 基本設計書 — Hệ thống vận hành học máy dự đoán giá bất động sản

| Mục | Nội dung |
| --- | --- |
| Tên tài liệu | 基本設計書 (Tài liệu thiết kế cơ bản) |
| Hệ thống | Hệ thống vận hành học máy dự đoán giá bất động sản |
| Phiên bản | 1.0 |
| Ngày lập | 24/09/2026 |
| Căn cứ | 要件定義書 phiên bản 1.0; tài liệu thiết kế hệ thống và các tài liệu thiết kế chi tiết của năm giai đoạn xây dựng, trạng thái ngày 24/09/2026 |

## Lịch sử sửa đổi

| Phiên bản | Ngày | Nội dung |
| --- | --- | --- |
| 1.0 | 24/09/2026 | Lập mới |

---

## 1. Tổng quan

### 1.1. Mục đích của tài liệu

Tài liệu này mô tả **hệ thống được xây dựng như thế nào** để đáp ứng các yêu cầu trong 要件定義書: gồm những thành phần nào, mỗi thành phần làm gì, dữ liệu đi qua chúng ra sao, và mỗi quyết định thiết kế được đưa ra vì lý do gì.

Các mã yêu cầu (NV-xx, CN-xx, PCN-xx) được dẫn lại trong nội dung. Bảng đối chiếu đầy đủ ở mục 13. Các con số đo thực tế được ghi kèm ngày đo.

### 1.2. Nguyên tắc thiết kế

| STT | Nguyên tắc | Lý do |
| --- | --- | --- |
| 1 | Mỗi bước xử lý nặng chạy trong **một container độc lập**. Hệ thống điều phối chỉ quyết định bước nào chạy, theo thứ tự nào; nó không chứa logic học máy. | Từng bước có thể được thay bằng dịch vụ tương ứng trên đám mây mà không ảnh hưởng các bước khác. Một bước hết bộ nhớ chỉ làm hỏng chính nó, không kéo sập hệ thống điều phối. |
| 2 | Kho lưu trữ dữ liệu **tương thích với Amazon S3 ngay từ đầu**. | Phần đọc/ghi dữ liệu không phải viết lại khi chuyển lên đám mây (PCN-16). |
| 3 | Điều phối, quản lý mô hình, dự đoán và giám sát là **các thành phần tách biệt**, mỗi thành phần dùng công cụ chuyên trách. | Tránh một thành phần ôm quá nhiều việc; thay từng phần được khi chuyển đổi. |
| 4 | Mỗi bước **chạy lại được** mà không gây sai lệch. Kết quả được ghi vào vị trí xác định theo đầu vào; chạy lại thì ghi đè chính nó hoặc bỏ qua nếu đã có. | PCN-07. |
| 5 | **Chỉ có một bản logic làm sạch dữ liệu**, và nó được đóng gói bên trong mô hình. | NV-04. Hai bản chép tay của cùng một phép xử lý chắc chắn sẽ lệch nhau theo thời gian. |
| 6 | **Không quy trình nào chạy theo lịch** ở giai đoạn 1; mỗi quy trình chỉ chạy một lần tại một thời điểm. | NV-01, PCN-11. |

---

## 2. Kiến trúc hệ thống

### 2.1. Sơ đồ tổng thể (giai đoạn 1)

```
┌────────────────────┐
│   Bảng điều khiển  │  Trình duyệt web
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐                  ┌──────────────────────────────────┐
│    Lớp trung gian  │─────────────────▶│  Hệ thống điều phối (Airflow)    │
│  của bảng điều     │                  │   • Quy trình huấn luyện         │
│      khiển         │──┐               │   • Quy trình mô phỏng lưu lượng │
└─────────┬──────────┘  │               │   • Quy trình giám sát           │
          │             │               └────────────────┬─────────────────┘
          │             │                                │ khởi chạy từng bước
          │             │                                ▼ trong container riêng
          │             │               ┌──────────────────────────────────┐
          │             └──────────────▶│  Quản lý mô hình (MLflow)        │
          │                             └────────────────┬─────────────────┘
          │                                              │
          ▼                                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                  Kho lưu trữ đối tượng (MinIO)                           │
│  dữ liệu thô · bản làm việc · dữ liệu đã chuẩn bị · tệp mô hình          │
│  hồ sơ thống kê cơ sở · nhật ký dự đoán · kết quả thực tế · báo cáo      │
└──────────────────────────────────────────────────────────────────────────┘
          ▲ ghi nhật ký                                  ▲ đọc nhật ký
          │                                              │
┌─────────┴──────────┐   ┌────────────────────┐   ┌──────┴─────────────────┐
│  Tác nhân mô phỏng │──▶│  Dịch vụ dự đoán   │   │  Bước giám sát         │
│  thị trường        │   │                    │   │  (Evidently)           │
└────────────────────┘   └─────────▲──────────┘   └────────────────────────┘
                                   │
                                   └── bước "đưa vào sử dụng" yêu cầu nạp lại mô hình
```

Cơ sở dữ liệu PostgreSQL (không vẽ trong sơ đồ) lưu thông tin quản lý của Airflow và của MLflow.

### 2.2. Danh sách thành phần

| Thành phần | Vai trò | Sản phẩm sử dụng |
| --- | --- | --- |
| Bảng điều khiển | Giao diện web để người vận hành thao tác với toàn bộ hệ thống (mục 8) | Ứng dụng web chạy trên trình duyệt. Hiện chạy ở chế độ phát triển; cách phục vụ bản chính thức chưa chọn (mục 14). |
| Lớp trung gian của bảng điều khiển | Nhận thao tác từ bảng điều khiển, chuyển tiếp tới đúng thành phần phía sau, trả kết quả về. Giữ thông tin xác thực của các thành phần phía sau. | Dịch vụ web tự phát triển, chạy trong container |
| Hệ thống điều phối | Chạy ba quy trình (mục 3), ghi nhật ký từng bước | Apache Airflow, chế độ thực thi trên một máy |
| Các bước xử lý | Tiếp nhận, kiểm tra chất lượng, chuẩn bị dữ liệu, huấn luyện, đánh giá, đăng ký, giám sát. Mỗi bước là một container riêng. | Docker |
| Quản lý mô hình | Ghi lại mỗi lần huấn luyện (cấu hình, chỉ số, tệp mô hình); quản lý phiên bản mô hình và phiên bản đang sử dụng | MLflow Tracking, MLflow Model Registry |
| Kho lưu trữ đối tượng | Lưu mọi dữ liệu và tệp của hệ thống (mục 10.1) | MinIO, tương thích Amazon S3 |
| Cơ sở dữ liệu quản lý | Lưu thông tin quản lý của Airflow và của MLflow, **ở hai cơ sở dữ liệu riêng biệt** trên cùng một máy chủ | PostgreSQL |
| Dịch vụ dự đoán | Trả kết quả dự đoán cho cả hai bài toán; ghi nhật ký; nhận kết quả thực tế (mục 5) | Dịch vụ web tự phát triển, chạy trong container |
| Tác nhân mô phỏng thị trường | Sinh lưu lượng dự đoán và kết quả thực tế theo kịch bản (mục 6) | Thành phần tự phát triển, chạy trong container |
| Công cụ phát hiện trôi | Tính mức độ trôi dữ liệu đầu vào và trôi kết quả dự đoán; sinh báo cáo chi tiết (mục 7) | Evidently |
| Khởi động toàn hệ thống | Khởi động mọi thành phần trên một máy bằng một thao tác (PCN-24) | Docker Compose |

### 2.3. Phân tách trách nhiệm

**Hệ thống có hai dịch vụ web riêng biệt, không được gộp làm một:**

- **Lớp trung gian của bảng điều khiển** không biết gì về mô hình. Nó chỉ chuyển tiếp thao tác của người vận hành tới Airflow, MLflow và MinIO.
- **Dịch vụ dự đoán** không biết gì về bảng điều khiển. Nó chỉ nhận thông tin căn nhà và trả kết quả dự đoán.

Hai dịch vụ này có tải, vòng đời và cách chuyển lên đám mây hoàn toàn khác nhau (mục 12), nên phải tách ngay từ đầu.

**Vì sao cần lớp trung gian**, thay vì cho bảng điều khiển gọi thẳng Airflow, MLflow và MinIO:

1. Thông tin xác thực của các thành phần đó sẽ phải nằm trong trình duyệt, tức là lộ ra ngoài (PCN-13).
2. Mỗi thành phần phía sau phải mở quyền truy cập từ trình duyệt riêng.
3. Mỗi lần thay một thành phần phía sau khi chuyển lên đám mây thì bảng điều khiển phải sửa theo. Có lớp trung gian thì chỉ lớp đó phải sửa (PCN-17).

Danh sách lựa chọn hiển thị trên bảng điều khiển (thuật toán, kịch bản thị trường) được lớp trung gian đọc thẳng từ thành phần xử lý dùng chung, không chép lại ở bảng điều khiển, để hai nơi không thể lệch nhau.

### 2.4. Thành phần xử lý dữ liệu dùng chung

Toàn bộ hiểu biết về bộ dữ liệu — danh sách mục, kiểu dữ liệu, khoảng giá trị hợp lệ, cách làm sạch, cách chọn đầu vào theo bài toán, danh sách thuật toán, các cổng đánh giá, các ngưỡng giám sát, quy ước vị trí lưu trữ, cách tính hồ sơ thống kê — được đặt trong **một thành phần phần mềm dùng chung duy nhất**. Các bước xử lý chỉ là lớp vỏ mỏng gọi vào thành phần này.

Thành phần dùng chung tách các phép xử lý thành **hai nhóm với ranh giới cứng**:

| Nhóm | Ví dụ | Được dùng ở đâu | Lý do |
| --- | --- | --- | --- |
| **Xử lý theo từng mục thông tin** | Chuẩn hoá cách viết, đọc ngày tháng, đưa giá trị bất thường về khoảng hợp lệ | Được **đóng gói cùng mô hình**, nên chạy ở cả lúc huấn luyện (tới 2 triệu dòng) lẫn lúc dự đoán (một căn nhà) | Đảm bảo lúc huấn luyện và lúc dự đoán làm sạch giống hệt nhau (NV-04) |
| **Xử lý theo bản ghi** | Loại bản ghi trùng lặp, loại bản ghi không có đáp án | **Chỉ** ở bước chuẩn bị dữ liệu huấn luyện | Nếu một phép loại bản ghi lọt vào phần đóng gói cùng mô hình, nó vẫn chạy đúng suốt lúc huấn luyện, nhưng tới lúc dự đoán cho một căn nhà thì có thể không còn bản ghi nào để dự đoán — dịch vụ sẽ lỗi (PCN-09) |

Hai nhóm này nằm ở hai phần riêng biệt của thành phần dùng chung, và phần xử lý theo bản ghi **không bao giờ** được gọi từ phần tạo mô hình hay từ dịch vụ dự đoán. Dịch vụ dự đoán thậm chí không gọi phần xử lý theo từng mục: nó chỉ đưa dữ liệu thô vào mô hình, và mô hình tự làm sạch.

---

## 3. Thiết kế quy trình xử lý

Hệ thống điều phối có **ba quy trình**. Cả ba chỉ chạy khi được yêu cầu, và mỗi quy trình chỉ chạy một lần tại một thời điểm.

| Quy trình | Khởi chạy bởi | Mục |
| --- | --- | --- |
| Huấn luyện và đưa vào sử dụng | Người vận hành, từ màn Tổng quan | 3.1 – 3.8 |
| Mô phỏng lưu lượng | Người vận hành, từ màn Giám sát trôi | 3.9 |
| Giám sát | Quy trình mô phỏng lưu lượng, sau khi gửi xong; hoặc gọi trực tiếp qua lớp trung gian (không có nút riêng trên bảng điều khiển) | 3.10 |

Cả ba quy trình được để ở trạng thái sẵn sàng chạy ngay khi hệ thống khởi động. Lý do: nếu một quy trình bị tạm dừng trong hệ thống điều phối, lần chạy được yêu cầu sẽ nằm chờ vĩnh viễn mà không có tín hiệu nào cho biết vì sao — sự cố đã xảy ra thật ngày 21/09/2026.

### 3.1. Quy trình huấn luyện và đưa vào sử dụng

**Tham số khởi chạy (CN-04, CN-05):**

| Tham số | Giá trị | Mặc định |
| --- | --- | --- |
| Bài toán | Dự đoán giá bán, hoặc Dự đoán nhu cầu cải tạo | Bắt buộc chọn |
| Thuật toán | Một trong ba thuật toán của bài toán (mục 3.5) | Thuật toán mặc định của bài toán |
| Tinh chỉnh tham số | Có / Không | Không |
| Số dòng huấn luyện | Số nguyên dương, hoặc toàn bộ | Toàn bộ (bảng điều khiển luôn gửi giá trị cụ thể) |
| Xử lý lại dữ liệu từ đầu | Có / Không | Không |
| Phiên bản dữ liệu | Tên phiên bản đã tải lên | Phiên bản đầu tiên |

Lớp trung gian từ chối ngay (không khởi chạy) nếu thuật toán không thuộc bài toán đã chọn, hoặc số dòng bằng 0 hay âm. Tên phiên bản dữ liệu không được kiểm tra trước: phiên bản không tồn tại chỉ làm hỏng bước tiếp nhận.

**Trình tự:**

```
Tiếp nhận → Kiểm tra chất lượng → Chuẩn bị dữ liệu → Huấn luyện → Đánh giá → Rẽ nhánh ─┬─ Đăng ký → Đưa vào sử dụng
                                                                                      └─ Dừng (không đưa vào sử dụng)
```

| STT | Bước | Nội dung | Đầu ra |
| --- | --- | --- | --- |
| 1 | Tiếp nhận | Mục 3.2 | Bản làm việc dạng Parquet, mã nhận dạng dữ liệu |
| 2 | Kiểm tra chất lượng | Mục 3.3 | Báo cáo chất lượng |
| 3 | Chuẩn bị dữ liệu | Mục 3.4 | Tập huấn luyện, tập kiểm tra |
| 4 | Huấn luyện | Mục 3.5 | Lần huấn luyện ghi trong MLflow |
| 5 | Đánh giá | Mục 3.6 | Đạt / Không đạt, chỉ số trên tập kiểm tra |
| 6 | Rẽ nhánh | Đạt thì sang bước 7; không đạt thì sang bước 9 | — |
| 7 | Đăng ký | Mục 3.7 | Phiên bản đang sử dụng mới, hồ sơ thống kê cơ sở |
| 8 | Đưa vào sử dụng | Mục 3.8 | Dịch vụ dùng phiên bản mới |
| 9 | Dừng | Kết thúc, **giữ nguyên** mô hình đang sử dụng (CN-14) | — |

Ở mỗi lần chạy, một trong hai nhánh sau bước 6 bị bỏ qua. Đó là hành vi bình thường, không phải lỗi.

**Truyền dữ liệu giữa các bước:** dữ liệu lớn đi qua **kho lưu trữ đối tượng**, không đi qua hệ thống điều phối. Hệ thống điều phối chỉ chuyển các giá trị nhỏ giữa các bước: mã nhận dạng dữ liệu, mã lần huấn luyện, chỉ số đánh giá, số phiên bản.

### 3.2. Bước tiếp nhận

1. Đọc dữ liệu thô của phiên bản đã chọn từ kho lưu trữ.
2. Tính **mã nhận dạng dữ liệu** từ ba thành phần: tên phiên bản dữ liệu, dấu hiệu thay đổi mà kho lưu trữ gắn cho tệp dữ liệu thô, và số dòng huấn luyện. Dùng dấu hiệu thay đổi của kho thay vì đọc và tính toán trên toàn bộ nội dung: kho đã tự cập nhật dấu hiệu này khi tệp đổi, nên không cần đọc 2 triệu dòng chỉ để biết dữ liệu có đổi hay không.
3. Lấy đúng số dòng đầu tiên theo yêu cầu (hoặc toàn bộ), ghi thành **bản làm việc** tại vị trí đặt theo mã nhận dạng.

**Số dòng bắt buộc nằm trong mã nhận dạng** (PCN-02). Thiếu nó, một lần chạy 200.000 dòng sẽ dùng nhầm kết quả của lần chạy toàn bộ dòng — sai kiểu này không báo lỗi, mô hình được huấn luyện trên một tập khác với tập người chạy tưởng.

### 3.3. Bước kiểm tra chất lượng

Vai trò của bước này là **đo và báo cáo**, không phải chặn dữ liệu bẩn. Bộ dữ liệu cố tình chứa 8 loại lỗi; một ngưỡng chặt sẽ chặn mọi lần chạy.

Quy trình **chỉ dừng** trong đúng ba trường hợp — dữ liệu vô dụng:

1. Thiếu mục so với danh sách mục dữ liệu quy định.
2. Hơn 50% giá trị đáp án bị thiếu. Với bài toán cải tạo, kiểm tra trên mục nguồn sinh ra đáp án (tình trạng nhà).
3. Không có dòng nào.

Mọi thứ khác — tỉ lệ thiếu từng mục, số giá trị ngoài khoảng hợp lệ, số mã bưu chính sai định dạng, số bản ghi trùng — chỉ được **đếm và ghi vào báo cáo chất lượng**. Các bước sau sẽ xử lý chúng.

### 3.4. Bước chuẩn bị dữ liệu

**Tái sử dụng kết quả (CN-09, PCN-02).** Kết quả chuẩn bị được lưu tại vị trí đặt theo **mã nhận dạng dữ liệu và bài toán**. Đầu bước, nếu vị trí đó đã có đủ tập huấn luyện và tập kiểm tra, và người vận hành không chọn "Xử lý lại dữ liệu từ đầu", thì bước này được bỏ qua.

Bài toán phải nằm trong vị trí lưu vì hai bài toán dùng chung mã nhận dạng dữ liệu nhưng kết quả chuẩn bị khác nhau (đáp án khác nhau, bản ghi bị loại vì thiếu đáp án cũng khác nhau). Dùng chung một vị trí thì bài toán này sẽ âm thầm dùng kết quả của bài toán kia.

**Nội dung xử lý:**

1. Với bài toán cải tạo: sinh mục **Cần cải tạo** từ mục tình trạng nhà (要件定義書 mục 6.2). Tình trạng nhà được chuẩn hoá cách viết trước; giá trị trống hoặc không đọc được thì để đáp án trống — không đoán.
2. Loại bản ghi trùng mã bất động sản, giữ bản ghi đầu tiên.
3. Loại bản ghi không có đáp án.
4. Chia **80% làm tập huấn luyện, 20% làm tập kiểm tra**, theo một cách chia cố định, lặp lại được (PCN-21).
5. Lưu cả hai tập.

**Bước này không làm sạch từng mục thông tin.** Dữ liệu đã chuẩn bị vẫn còn nguyên dạng thô — vẫn còn "$450,000", vẫn còn "NEW YORK", vẫn còn mã bưu chính 4 chữ số. Việc làm sạch do phần xử lý đóng gói cùng mô hình đảm nhận (mục 4). Nếu bước này làm sạch rồi lưu, mô hình sẽ học trên dữ liệu đã sạch trong khi dịch vụ dự đoán nhận dữ liệu thô — đúng loại sai lệch mà cả thiết kế này dựng lên để tránh (NV-04). "Đã chuẩn bị" ở đây chỉ có nghĩa là **đã xử lý theo bản ghi và đã chia tập**, không có nghĩa là "đã làm sạch".

### 3.5. Bước huấn luyện

**Thuật toán:**

| Bài toán | Thuật toán có thể chọn | Mặc định |
| --- | --- | --- |
| Dự đoán giá bán | Hồi quy Ridge; XGBoost; Rừng ngẫu nhiên (Random Forest) | Hồi quy Ridge |
| Dự đoán nhu cầu cải tạo | XGBoost; Máy vector hỗ trợ (SVM); Rừng ngẫu nhiên (Random Forest) | XGBoost |

Máy vector hỗ trợ tự nó không cho ra xác suất, trong khi cổng đánh giá của bài toán cải tạo cần xác suất để tính AUC. Vì vậy nó được bọc thêm một bước hiệu chỉnh xác suất.

**Tinh chỉnh tham số (CN-10, PCN-06):** khi bật, hệ thống thử mọi tổ hợp trong một lưới tham số nhỏ (tối đa 8 tổ hợp mỗi thuật toán), đánh giá mỗi tổ hợp bằng kiểm định chéo 5 phần trên tập huấn luyện, và giữ tổ hợp tốt nhất. Tiêu chí chọn là **đúng chỉ số mà cổng đánh giá và giám sát dùng**: RMSE cho bài toán giá bán, AUC cho bài toán cải tạo — để "tốt nhất khi tinh chỉnh" và "tốt nhất khi đánh giá" là cùng một thước đo. Khi tắt, thuật toán dùng bộ tham số cố định sẵn. Các bước sau không cần biết có tinh chỉnh hay không.

**Không biến đổi thang đo của giá.** Mô hình dự đoán giá được huấn luyện trực tiếp trên giá bán tính bằng đô la. Thiết kế ban đầu định huấn luyện trên thang logarit của giá để giảm độ lệch phân bố, nhưng đo trên 48.000 dòng thật cho thấy điều ngược lại: khi quy đổi ngược về đô la, sai số ở nhóm nhà giá cao bị khuếch đại theo cấp số nhân — hồi quy Ridge ra R² âm (−0,40) và dự đoán một căn nhà giá 28,3 triệu đô, trong khi giá thật cao nhất là 2,39 triệu đô. Bỏ phép biến đổi thì Ridge đạt R² 0,68, còn các thuật toán dạng cây không đổi.

**Thứ được ghi vào MLflow:** thuật toán và tham số, mã nhận dạng dữ liệu đã dùng, chỉ số trên tập huấn luyện, và **mô hình hoàn chỉnh** — gồm toàn bộ phần xử lý dữ liệu (mục 4) và bộ dự đoán — được lưu nguyên khối. Nhờ vậy mô hình trong kho **tự chứa logic làm sạch** (CN-10): dịch vụ dự đoán đưa dữ liệu thô vào là đủ.

### 3.6. Bước đánh giá

Nạp mô hình vừa huấn luyện, dự đoán trên tập kiểm tra, tính các chỉ số và ghi vào cùng lần huấn luyện trong MLflow.

| Bài toán | Chỉ số được tính |
| --- | --- |
| Dự đoán giá bán | RMSE, MAE, R² (đơn vị đô la) |
| Dự đoán nhu cầu cải tạo | AUC, F1, độ chính xác |

Mô hình mới phải qua **cả hai cổng** (CN-11, NV-03):

| Cổng | Dự đoán giá bán | Dự đoán nhu cầu cải tạo | Mục đích |
| --- | --- | --- | --- |
| 1. Ngưỡng tối thiểu | R² ≥ 0,75 | AUC ≥ 0,55 | Chặn mô hình kém chất lượng, kể cả mô hình đoán mò (PCN-22) |
| 2. Tốt hơn mô hình đang sử dụng | RMSE thấp hơn | AUC cao hơn | Chặn việc thay một mô hình tốt bằng một mô hình kém hơn chỉ vì mô hình mới vượt ngưỡng. Bằng nhau thì không thắng. |

Cổng 2 so hai mô hình trên **cùng tập kiểm tra đã lưu**. Nếu chưa có mô hình nào đang sử dụng, chỉ áp dụng cổng 1. Chỉ số của cả hai mô hình được ghi vào cùng lần huấn luyện, để về sau đọc lại được vì sao một mô hình bị chặn.

**Vì sao bài toán cải tạo dùng AUC, không dùng F1.** Thiết kế ban đầu dùng ngưỡng F1 ≥ 0,70. Đo trên dữ liệu thật cho thấy F1 hỏng theo hai hướng ngược nhau:

- **Cho mô hình đoán mò lọt qua:** trên một bài toán có 56% lớp dương, một mô hình luôn trả lời "có" đạt F1 0,72 — vượt ngưỡng mà không hề nhìn dữ liệu.
- **Chặn nhầm mô hình tốt:** trên bài toán cải tạo (25% lớp dương), một mô hình tốt với AUC 0,71 chỉ đạt F1 0,16, vì ở ngưỡng quyết định mặc định nó hiếm khi trả lời "có".

Nguyên nhân chung: F1 phụ thuộc vào ngưỡng quyết định và tỉ lệ giữa hai lớp, nên một ngưỡng F1 cố định chỉ đúng với đúng một phân bố dữ liệu. AUC không phụ thuộc hai yếu tố đó, và mọi mô hình đoán mò đều cho đúng 0,5. F1 và độ chính xác vẫn được tính để báo cáo.

**Bước đánh giá luôn kết thúc bình thường**, kể cả khi mô hình không đạt. Kết quả đạt/không đạt được chuyển cho bước rẽ nhánh quyết định; "không đạt" là một kết quả hợp lệ, không phải lỗi của quy trình.

### 3.7. Bước đăng ký

1. Đăng ký mô hình vào MLflow Model Registry, nhận số phiên bản mới.
2. Gắn nhãn "champion" vào phiên bản đó — nhãn đánh dấu **phiên bản đang sử dụng**. Mỗi mô hình có tối đa một phiên bản mang nhãn này. Hệ thống dùng nhãn thay cho cơ chế "giai đoạn vòng đời" cũ của MLflow, vì cơ chế cũ đã bị MLflow ngừng hỗ trợ.
3. Tính **hồ sơ thống kê cơ sở** (mục 7.1) từ tập huấn luyện đã dùng, lưu tại vị trí đặt theo tên mô hình và số phiên bản.

Hồ sơ được tính từ tập **huấn luyện**, không phải tập kiểm tra: giám sát so lưu lượng thực tế với dữ liệu mà mô hình đã học.

Mỗi bài toán là một mô hình đăng ký riêng trong MLflow. Tên mô hình được suy ra từ bài toán, người khởi chạy không tự đặt — để không thể vô tình ghi một mô hình phân loại vào mục của mô hình dự đoán giá.

### 3.8. Bước đưa vào sử dụng

Gửi yêu cầu "nạp lại mô hình" tới dịch vụ dự đoán (mục 5.2). Bước này **không có container riêng**: nó chỉ gửi một yêu cầu, nên dùng chức năng có sẵn của Airflow. Đóng gói cả một container chỉ để gửi một yêu cầu là thừa. Ngược lại, bước đăng ký vẫn có container riêng vì nó phải tính hồ sơ thống kê trên toàn bộ tập huấn luyện.

### 3.9. Quy trình mô phỏng lưu lượng

| Tham số | Giá trị | Mặc định |
| --- | --- | --- |
| Kịch bản thị trường | Một trong năm kịch bản (mục 6) | Không thay đổi |
| Bài toán | Lấy theo mô hình đang xem trên màn Giám sát trôi | — |
| Số yêu cầu | 1 đến 5.000 | 300 |

| STT | Bước | Nội dung |
| --- | --- | --- |
| 1 | Gửi lưu lượng | Chạy tác nhân mô phỏng trong container riêng (mục 6) |
| 2 | Tính giám sát | Khởi chạy quy trình giám sát (mục 3.10) và **chờ nó xong** |

Hai bước được nối ở tầng điều phối chứ không nối ở bảng điều khiển, để người vận hành đóng trình duyệt giữa chừng thì giám sát vẫn được tính (CN-28). Vì bước 2 chờ quy trình giám sát xong, trạng thái của một lần chạy mô phỏng trả lời trọn câu hỏi "đã xong toàn bộ chưa". Đo ngày 22/09/2026: cả chuỗi mất khoảng 40 giây (18,5 giây gửi lưu lượng, 20,6 giây tính giám sát).

Tại một thời điểm chỉ có một lần mô phỏng chạy, để lưu lượng của hai kịch bản không trộn vào cùng một khoảng thời gian — nếu trộn, báo cáo giám sát không quy được kết quả cho kịch bản nào.

### 3.10. Quy trình giám sát

Quy trình giám sát có **một bước cho mỗi mô hình**, hai bước chạy song song. Mỗi bước là một container tự làm trọn việc: đọc dữ liệu trong khoảng thời gian xét, so sánh, ghi báo cáo (mục 7).

Không tách thành ba bước riêng "thu thập — so sánh — công bố": dữ liệu lớn không đi qua hệ thống điều phối (mục 3.1), nên tách ra thì mỗi bước phải tự đọc lại toàn bộ dữ liệu từ đầu — ba lần đọc cho một lần chạy mà không được gì đổi lại.

Quy trình giám sát **không** nằm trong quy trình huấn luyện. Nó đo lưu lượng dự đoán tích luỹ theo thời gian, không đo kết quả của lần huấn luyện vừa xong; chạy ngay sau bước đưa vào sử dụng thì mô hình mới chưa phục vụ yêu cầu nào và báo cáo sẽ rỗng.

Quy trình giám sát **không tự khởi chạy huấn luyện lại** (NV-02).

---

## 4. Thiết kế xử lý dữ liệu đóng gói cùng mô hình

### 4.1. Thứ tự xử lý

Mọi dữ liệu đi vào mô hình — dù hàng trăm nghìn dòng lúc huấn luyện hay một căn nhà lúc dự đoán — đều đi qua đúng các bước sau, theo đúng thứ tự:

| STT | Bước | Nội dung |
| --- | --- | --- |
| 1 | Làm sạch từng mục | Áp quy tắc làm sạch tương ứng với loại của từng mục (mục 4.2). Mục không có trong danh sách mục dữ liệu được giữ nguyên; mục thiếu thì bỏ qua, không báo lỗi. |
| 2 | Đưa giá trị bất thường về khoảng hợp lệ | Giá trị nhỏ hơn giới hạn dưới được nâng lên bằng giới hạn dưới; lớn hơn giới hạn trên được hạ xuống bằng giới hạn trên (mục 4.3). Giá trị thiếu vẫn giữ là thiếu. |
| 3 | Tách ngày tháng | Ngày đăng bán được tách thành **năm** và **tháng**, rồi bỏ mục ngày gốc. |
| 4 | Chọn đầu vào | Giữ đúng các mục đầu vào của bài toán, theo thứ tự cố định. Mục bị loại theo 要件定義書 mục 6.3 bị bỏ đi **kể cả khi người gọi gửi lên**. Mục đầu vào mà người gọi không gửi được thêm vào với giá trị thiếu. |
| 5 | Bổ sung giá trị thiếu và chuyển đổi | Mục 4.5 |
| 6 | Dự đoán | Bộ dự đoán của thuật toán đã chọn. |

**Thứ tự này là ràng buộc, không phải lựa chọn.** Bước 1 phải đứng đầu:

- Nếu bước 2 chạy trước bước 1, giá tiền dạng "$450,000" chưa được đọc thành số sẽ bị coi là không hợp lệ và trở thành giá trị thiếu.
- Nếu bước 3 chạy trước bước 1, ngày đăng bán còn đang ở ba định dạng lẫn lộn; một phần sẽ không đọc được và **âm thầm trở thành giá trị thiếu**, không có lỗi nào xuất hiện để cảnh báo.

**Không bước nào trong số trên được loại bỏ bản ghi** (PCN-09). Số bản ghi đầu ra luôn bằng số bản ghi đầu vào.

### 4.2. Quy tắc làm sạch theo loại mục

| Loại mục | Áp dụng cho | Quy tắc | Giá trị không đọc được |
| --- | --- | --- | --- |
| Phân loại | Thành phố, bang, loại bất động sản, tình trạng nhà, phân loại mức giá | Chuyển về chữ thường; gạch dưới và gạch nối đổi thành dấu cách; nhiều dấu cách liền nhau gộp thành một; bỏ khoảng trắng đầu và cuối. Ví dụ "Multi-Family", "MULTI FAMILY", và cách viết nối hai từ bằng dấu gạch dưới đều thành "multi family". | Chuỗi rỗng hoặc chỉ có khoảng trắng → thiếu |
| Có/không | Có hồ bơi, bán trong vòng 30 ngày | "Yes", "Y", "1", "True", "T" (không phân biệt hoa thường, bỏ khoảng trắng thừa) → Có. "No", "N", "0", "False", "F" → Không. | Mọi giá trị khác → thiếu |
| Ngày tháng | Ngày đăng bán | Chấp nhận ba định dạng: năm-tháng-ngày (2023-07-15); tháng/ngày/năm (07/15/2023); ngày-tên tháng tiếng Anh viết tắt-năm (15-Jul-2023). Định dạng có gạch chéo **luôn** hiểu là tháng trước, ngày sau. Thử lần lượt từng định dạng, không dùng cơ chế tự đoán định dạng. | Không khớp định dạng nào, hoặc ngày không tồn tại → thiếu |
| Tiền | Giá rao bán, giá bán cuối cùng | Bỏ ký hiệu đô la, dấu phẩy phân cách hàng nghìn và khoảng trắng, rồi đọc thành số. Giá trị đã là số thì giữ nguyên. | Không còn là số hợp lệ → thiếu |
| Mã bưu chính | Mã bưu chính | Chấp nhận **đúng 5 chữ số**. Giữ nguyên số 0 ở đầu (ví dụ "02134"). **Không tự thêm số 0** vào mã 4 chữ số. | Sai định dạng (4 chữ số, 6 chữ số, có chữ cái…) → thiếu |
| Số | Các mục số còn lại | Giữ nguyên, chỉ kiểm tra khoảng hợp lệ ở bước 2 | — |

Việc thử lần lượt từng định dạng ngày được chọn thay cho cơ chế tự đoán định dạng vì hai lý do: nhanh hơn nhiều khi xử lý 2 triệu dòng, và không bao giờ nhầm ngày với tháng.

Việc không thêm số 0 vào mã bưu chính 4 chữ số là cố ý: mã "2134" rất có thể là "02134" bị phần mềm bảng tính cắt mất số 0, nhưng cũng có thể là lỗi khác. Đoán sai sẽ tạo ra dữ liệu sai mà không ai biết; coi là thiếu thì bước kiểm tra chất lượng đếm được và báo cáo (要件定義書 mục 6.5).

### 4.3. Khoảng giá trị hợp lệ

| Mục dữ liệu | Giới hạn dưới | Giới hạn trên |
| --- | --- | --- |
| Diện tích đất (foot vuông) | 0 | 1.000.000 |
| Diện tích sử dụng (foot vuông) | 0 | 50.000 |
| Số phòng ngủ | 0 | 20 |
| Số phòng tắm | 0 | 15 |
| Năm xây dựng | 1800 | Năm hiện tại |
| Số tầng | 0 | 5 |
| Số chỗ đỗ xe trong nhà | 0 | 6 |
| Phí quản lý hằng tháng (đô la) | 0 | 5.000 |
| Điểm trường học khu vực | 1 | 10 |
| Chỉ số tội phạm khu vực | 0 | 100 |
| Khoảng cách tới trung tâm (km) | 0 | 200 |
| Số ngày rao bán | 0 | 3.650 |
| Giá rao bán (đô la) | 0 | Không giới hạn |
| Giá bán cuối cùng (đô la) | 0 | Không giới hạn |

Giới hạn trên của năm xây dựng được tính theo năm hiện tại tại thời điểm chạy, không phải một con số cố định.

Giá trị bất thường được **đưa về trong khoảng** thay vì loại bỏ bản ghi, vì hai lý do: dịch vụ dự đoán không được phép loại bản ghi (PCN-09), và một căn nhà có số phòng ngủ ghi sai vẫn có thông tin hữu ích ở các mục khác.

### 4.4. Giá trị phân loại chuẩn

Sau khi làm sạch, các mục phân loại có danh sách giá trị hợp lệ cố định (đã ở dạng chuẩn hoá):

| Mục | Giá trị hợp lệ |
| --- | --- |
| Loại bất động sản | single family (nhà riêng một hộ), condo (căn hộ chung cư), townhouse (nhà liền kề), multi family (nhà nhiều hộ), land (đất trống) |
| Tình trạng nhà | poor (kém), fair (trung bình), good (tốt), excellent (rất tốt) |
| Phân loại mức giá | low (thấp), medium (trung bình), high (cao), luxury (cao cấp) |

Thành phố và bang không có danh sách cố định.

### 4.5. Phân nhóm đầu vào và xử lý giá trị lạ

| Nhóm | Gồm | Bổ sung giá trị thiếu | Chuyển đổi |
| --- | --- | --- | --- |
| Số | Các mục số, các mục tiền được dùng làm đầu vào, các mục có/không (Có → 1, Không → 0), năm đăng bán, tháng đăng bán | Trung vị của tập huấn luyện | Đưa về cùng thang đo (trung bình 0, độ lệch chuẩn 1) |
| Phân loại | Thành phố, bang, mã bưu chính, loại bất động sản, và các mục phân loại khác được dùng làm đầu vào | Giá trị xuất hiện nhiều nhất trong tập huấn luyện | Mỗi giá trị thành một cột có/không riêng |

**Giá trị hiếm:** giá trị phân loại chiếm dưới 1% tập huấn luyện được gộp chung vào một nhóm "hiếm".

**Giá trị chưa từng gặp:** khi dự đoán, một giá trị phân loại chưa có trong tập huấn luyện (ví dụ một loại nhà mới trong kịch bản "Phân khúc mới") được xếp vào nhóm "hiếm" nếu có, hoặc được bỏ qua — **không gây lỗi** (PCN-08). Đây là điểm dễ làm dịch vụ dự đoán ngừng hoạt động nhất nếu thiết kế sai.

### 4.6. Mục bị loại khỏi đầu vào theo bài toán

Theo 要件定義書 mục 6.3. Việc loại được thực hiện ở bước 4 của mục 4.1, tức là **bên trong mô hình**: dù người gọi có gửi các mục bị loại, mô hình cũng bỏ chúng đi trước khi dự đoán.

### 4.7. Thao tác theo bản ghi

Chỉ được thực hiện ở bước chuẩn bị dữ liệu (mục 3.4), không bao giờ ở trong mô hình:

| Thao tác | Quy tắc | Kết quả trả về |
| --- | --- | --- |
| Loại trùng lặp | Bản ghi cùng mã bất động sản: giữ bản đầu tiên | Dữ liệu sau khi loại, số bản ghi đã loại |
| Loại bản ghi không có đáp án | Bản ghi thiếu giá trị đáp án của bài toán đã chọn | Dữ liệu sau khi loại, số bản ghi đã loại |

Sau mỗi thao tác, thứ tự đánh số bản ghi được làm lại từ đầu. Vì vậy, muốn truy ngược một bản ghi về dòng trong dữ liệu gốc thì phải dùng mã bất động sản, không dùng số thứ tự.

---

## 5. Thiết kế dịch vụ dự đoán

### 5.1. Chức năng

Một dịch vụ duy nhất phục vụ cả hai bài toán (CN-20).

| Chức năng | Đầu vào | Đầu ra | Yêu cầu |
| --- | --- | --- | --- |
| Dự đoán | Bài toán; thông tin **thô** của một căn nhà | Kết quả dự đoán, mã yêu cầu, tên và phiên bản mô hình. Bài toán cải tạo trả thêm xác suất. | CN-19 |
| Nhận kết quả thực tế | Bài toán; một **lô** kết quả, mỗi phần tử gồm mã yêu cầu, ngày đã dự đoán, giá trị thực tế | Số kết quả đã nhận | CN-23 |
| Nạp lại mô hình | — | Mô hình nào đã nạp, phiên bản bao nhiêu | CN-13 |
| Trạng thái | — | Mô hình nào đang được nạp, phiên bản bao nhiêu; số bản ghi nhật ký đang chờ ghi và số đã phải bỏ | CN-24 |

**Phản hồi khi có vấn đề:**

| Tình huống | Phản hồi |
| --- | --- |
| Bài toán chưa có mô hình | Từ chối, báo "chưa sẵn sàng" (không phải lỗi hệ thống) |
| Bài toán không hợp lệ, hoặc dữ liệu gửi lên không phải một bản ghi | Từ chối, báo dữ liệu gửi sai |
| Bản ghi thiếu một số mục | **Không phải lỗi** — mô hình tự bổ sung (mục 4.5) |
| Mô hình đã nạp nhưng dự đoán thất bại | Lỗi hệ thống |
| Lô kết quả thực tế rỗng | Từ chối, báo dữ liệu gửi sai |

### 5.2. Nạp mô hình

- Bản đóng gói của dịch vụ **không chứa mô hình**. Khi khởi động, dịch vụ lấy phiên bản mang nhãn "champion" của **cả hai** mô hình từ MLflow Model Registry và giữ trong bộ nhớ.
- **Thiếu mô hình thì vẫn khởi động** (CN-21). Mô hình nào nạp được thì phục vụ mô hình đó; trạng thái của dịch vụ là "ổn" khi nạp được ít nhất một mô hình, "suy giảm" khi không nạp được mô hình nào. Lý do: nếu từ chối khởi động, kho mô hình trống sẽ biến thành vòng khởi động lại liên tục, và không thể dựng dịch vụ trước khi có đủ mô hình.
- Khi nhận yêu cầu nạp lại, dịch vụ lấy lại phiên bản mang nhãn "champion" mới nhất của cả hai mô hình và **thay thế mô hình trong bộ nhớ**, không khởi động lại (CN-13). Phản hồi luôn báo trạng thái, kể cả khi không nạp được mô hình nào.
- Dịch vụ dự đoán chạy trong cùng môi trường phần mềm với lúc huấn luyện (PCN-20, mục 11.4).

### 5.3. Nhật ký dự đoán

| Mục | Nội dung |
| --- | --- |
| Mã yêu cầu | Mã duy nhất cho mỗi lần dự đoán; dùng để ghép với kết quả thực tế |
| Thời điểm | Thời điểm dự đoán |
| Dữ liệu đầu vào thô | Đúng như người gọi gửi lên, chưa làm sạch |
| Kết quả dự đoán | |
| Xác suất | Chỉ với bài toán cải tạo. Cần thiết vì giám sát chấm độ chính xác của bài toán này bằng AUC, mà AUC không tính được từ một câu trả lời có/không. |
| Tên mô hình | |
| Phiên bản mô hình | |

**Ghi theo lô, với ba quy tắc theo thứ tự ưu tiên** (PCN-04, PCN-10):

1. **Việc ghi nhật ký không bao giờ làm chậm hay làm hỏng một lần dự đoán.** Bản ghi được đưa vào bộ đệm trong bộ nhớ; việc ghi xuống kho diễn ra ở nền, khi bộ đệm đủ **500 bản ghi** hoặc sau **30 giây**.
2. **Ghi thất bại thì giữ lại để thử lần sau.** Kho lưu trữ khởi động lại vài giây không được làm mất dữ liệu giám sát.
3. **Bộ đệm có trần 5.000 bản ghi.** Vượt trần thì bỏ bản ghi **cũ nhất** và đếm số đã bỏ; con số này hiện ở chức năng Trạng thái. Trần tồn tại vì quy tắc 2: giữ lại vô hạn khi kho hỏng lâu trong lúc tác nhân đang gửi lưu lượng sẽ làm hết bộ nhớ và dịch vụ sẽ dừng.

Mỗi lần ghi tạo một tệp, chia theo mô hình và theo ngày. Ghi theo lô vì tác nhân mô phỏng gửi hàng nghìn yêu cầu; ghi riêng từng lần sẽ tạo ra quá nhiều tệp nhỏ và làm bước giám sát đọc rất chậm.

### 5.4. Kết quả thực tế

- Nhận **theo lô**: một lần gửi thành một tệp, không phải một yêu cầu cho mỗi căn nhà — cùng lý do với nhật ký dự đoán.
- Kết quả được lưu theo **ngày đã dự đoán** do bên gửi cung cấp, **không** theo ngày nhận. Có vậy nó mới nằm cùng mảnh với nhật ký dự đoán tương ứng để ghép được. Lô có nhiều ngày khác nhau thì ghi thành nhiều tệp, mỗi ngày một tệp.
- Bên gửi cung cấp ngày, thay vì dịch vụ tự tra từ mã yêu cầu, vì dịch vụ không lưu bảng tra như vậy; dựng thêm một bảng tra chỉ để phục vụ việc ghép là thêm trạng thái vào một dịch vụ đang cố giữ tối thiểu.
- Ghi thẳng xuống kho, không qua bộ đệm: dữ liệu đã được gom theo lô sẵn và tần suất thấp.

---

## 6. Thiết kế tác nhân mô phỏng thị trường

Tác nhân mô phỏng sinh lưu lượng thật cho dịch vụ dự đoán, thay cho cách giả lập trôi bằng cách cắt bộ dữ liệu gốc. Nó chạy trong container riêng, khởi chạy bởi quy trình mô phỏng lưu lượng (mục 3.9).

**Mỗi lần chạy:**

1. Lấy **20.000 căn nhà có ngày đăng bán mới nhất** trong dữ liệu làm nguồn.
2. Rút ngẫu nhiên số căn nhà theo yêu cầu. Mỗi lần chạy rút một mẫu khác nhau, để chạy lặp lại một kịch bản thì mở rộng mẫu chứ không gửi trùng các căn nhà cũ.
3. Biến đổi theo kịch bản (bảng dưới).
4. Gửi từng yêu cầu dự đoán.
5. Gửi kết quả thực tế của các căn nhà đó theo lô, kèm ngày đã dự đoán (mục 5.4). Mặc định gửi kết quả cho mọi yêu cầu.

Dự đoán và kết quả thực tế là **hai lần gọi tách rời**, đúng như trong thực tế: lúc hỏi giá chưa ai biết căn nhà sẽ bán được bao nhiêu. Thiết kế ban đầu định để tác nhân chờ "N ngày mô phỏng" trước khi báo kết quả; cách này bị bỏ vì độ trễ thật không thể minh hoạ, còn độ trễ giữa hai lần gọi vẫn hiện ra mà không cần bộ đếm giả lập.

**Năm kịch bản (CN-27):**

| Kịch bản | Biến đổi đầu vào | Kết quả thực tế gửi về |
| --- | --- | --- |
| Không thay đổi | Không | Giá trị thật |
| Lạm phát giá rao | Giá rao bán × 1,2 | Giá trị thật (không đổi) |
| Thị trường tăng giá | Giá rao bán × 1,2 | Giá bán thật × 1,2 |
| Dịch chuyển thị trường | Dồn thành phố về một, hai thành phố | Giá trị thật |
| Phân khúc mới | Loại bất động sản đổi thành giá trị chưa từng thấy | Giá trị thật |

**Kết quả đo thực tế với mô hình dự đoán giá (20/09/2026):**

| Kịch bản | Trôi dữ liệu đầu vào | Trôi kết quả dự đoán | Suy giảm độ chính xác | Kết luận |
| --- | --- | --- | --- | --- |
| Không thay đổi | Ổn | Ổn | Ổn | Không báo động nhầm |
| Lạm phát giá rao | Ổn | Ổn | Ổn | Giống hệt "Không thay đổi". Giá rao bán **không phải đầu vào** của mô hình dự đoán giá (要件定義書 mục 6.3), nên biến động ở nó không chạm tới mô hình. Biến động ở một mục mô hình không dùng thì không phải là trôi. |
| Thị trường tăng giá | Ổn | Ổn | **Cao** (RMSE tăng 2,24 lần) | **Độ chính xác sụp đổ trong khi dữ liệu đầu vào không hề đổi.** Đây là bằng chứng mạnh nhất cho việc báo cáo ba loại trôi tách riêng: nhìn riêng trôi dữ liệu đầu vào thì kịch bản này trôi qua như không có gì xảy ra. |
| Dịch chuyển thị trường | Cảnh báo | Cao | Cao | Kịch bản duy nhất thật sự thử được trôi dữ liệu đầu vào, vì thành phố là một đầu vào của mô hình. |
| Phân khúc mới | Cảnh báo | Ổn | Cảnh báo | Dịch vụ dự đoán **không lỗi** với giá trị lạ — đây là điều kiện chính của kịch bản này. |

---

## 7. Thiết kế giám sát

### 7.1. Mốc so sánh

Giám sát so sánh lưu lượng thực tế với **một mốc gắn với phiên bản mô hình đang sử dụng**, không gắn với một bộ dữ liệu cố định. Nhờ vậy không bao giờ xảy ra chuyện so phiên bản mới với mốc của một phiên bản cũ. Có ba mốc, cho ba loại trôi:

| Mốc | Nội dung | Nguồn |
| --- | --- | --- |
| Mẫu dữ liệu huấn luyện | Tối đa 10.000 dòng rút ngẫu nhiên (cách rút cố định, lặp lại được) từ tập huấn luyện của phiên bản đang sử dụng | Lần ngược: phiên bản mô hình → lần huấn luyện tạo ra nó → mã nhận dạng dữ liệu đã dùng → tập huấn luyện đã lưu |
| Phân bố kết quả dự đoán lúc huấn luyện | Kết quả mà chính phiên bản đang sử dụng dự đoán trên mẫu dữ liệu huấn luyện ở trên | Chạy lại mô hình tại thời điểm giám sát, vì lúc huấn luyện không lưu phân bố này |
| Chỉ số trên tập kiểm tra | Các chỉ số mà bước đánh giá (mục 3.6) đã ghi cho phiên bản đang sử dụng | MLflow |

**Vì sao mốc độ chính xác là chỉ số trên tập kiểm tra, không phải trên tập huấn luyện.** Tập kiểm tra là mốc duy nhất đo trên dữ liệu mô hình chưa từng thấy — đúng bản chất của lưu lượng thực tế. Chỉ số trên tập huấn luyện đo trên chính những dòng mô hình đã học, nên mô hình càng học vẹt thì mốc càng đẹp và cảnh báo càng luôn đỏ bất kể có trôi hay không. Đo thật ngày 22/09/2026: một mô hình có RMSE 14.321 trên tập huấn luyện nhưng 152.620 trên tập kiểm tra; lưu lượng thực tế ở 203.809 cho tỉ lệ 14,2 lần (Cao) nếu so với tập huấn luyện, nhưng chỉ 1,33 lần (Cảnh báo) nếu so với tập kiểm tra. Chỉ số trên tập kiểm tra cũng là con số màn Mô hình hiển thị, nên người vận hành so với đúng thứ mình nhìn thấy.

**Hồ sơ thống kê cơ sở.** Ngoài các mốc trên, bước đăng ký (mục 3.7) lưu một hồ sơ thống kê của tập huấn luyện cho mỗi phiên bản. Công cụ phát hiện trôi không đọc được hồ sơ tóm tắt (nó chỉ so hai tập dữ liệu thật), nên hồ sơ không dùng để tính trôi; nó là cách rẻ nhất để trả lời "phiên bản này học từ phân bố nào" mà không phải đọc lại dữ liệu.

| Phần | Nội dung hồ sơ |
| --- | --- |
| Chung | Tổng số bản ghi; thời điểm tính (theo giờ quốc tế) |
| Mỗi mục dạng số | Tỉ lệ thiếu; trung bình; độ lệch chuẩn; nhỏ nhất; lớn nhất; các điểm phân vị 25%, 50%, 75%; biểu đồ phân bố 20 khoảng |
| Mỗi mục dạng phân loại | Tỉ lệ thiếu; số giá trị khác nhau; tỉ lệ của từng giá trị |

### 7.2. Ba loại trôi và quy tắc xếp mức

**Khoảng thời gian xét:** mặc định 24 giờ gần nhất tính tới lúc giám sát.

| Loại trôi (tên trên bảng điều khiển) | So sánh | Cách tính |
| --- | --- | --- |
| Trôi dữ liệu đầu vào (Data drift) | Đầu vào trong nhật ký dự đoán với mẫu dữ liệu huấn luyện | Evidently, trên đúng các mục đầu vào của bài toán |
| Trôi kết quả dự đoán (Model drift) | Kết quả trong nhật ký với phân bố kết quả lúc huấn luyện | Evidently, trên một cột kết quả |
| Suy giảm độ chính xác (Performance drift) | Kết quả dự đoán với kết quả thực tế, ghép qua mã yêu cầu | Tính cùng loại chỉ số với bước đánh giá, so với chỉ số trên tập kiểm tra |

| Loại | Ổn | Cảnh báo | Cao |
| --- | --- | --- | --- |
| Trôi dữ liệu đầu vào — luật tỉ lệ | Dưới 30% số mục bị trôi | 30% – 50% | Trên 50% |
| Trôi dữ liệu đầu vào — luật độ lớn | Tổng độ vượt ngưỡng trên mọi mục âm | Tổng độ vượt ngưỡng từ 0 trở lên | — |
| Trôi kết quả dự đoán | Không trôi | — | Có trôi |
| Suy giảm độ chính xác — giá bán | RMSE thực tế / RMSE kiểm tra dưới 1,2 | 1,2 – 1,5 | Trên 1,5 |
| Suy giảm độ chính xác — cải tạo | AUC giảm dưới 0,05 | 0,05 – 0,10 | Trên 0,10 |

**Trôi dữ liệu đầu vào dùng hai luật, lấy mức nặng hơn.** Luật tỉ lệ một mình mù trước trôi dồn vào một, hai mục: ở kịch bản "Dịch chuyển thị trường", mục thành phố lệch gần 8 lần ngưỡng phát hiện, nhưng chỉ 2 trên 22 mục vượt ngưỡng — đúng bằng tỉ lệ đo được ở kịch bản "Không thay đổi" — nên luật tỉ lệ báo Ổn sai. Luật độ lớn cộng dồn mức vượt ngưỡng của từng mục (mục không trôi đóng góp số âm), nên bắt được một mục lệch rất nặng.

**Chưa đủ dữ liệu (NV-07).** Khi số kết quả thực tế ghép được với dự đoán **dưới 50**, suy giảm độ chính xác nhận trạng thái **Chưa đủ dữ liệu**, không được nhận Ổn. Báo Ổn khi chưa đo là nói dối, và là kiểu nói dối nguy hiểm nhất ở đây: dấu xanh trên bảng điều khiển trong khi thực tế chưa ai kiểm tra. Mô hình đang sử dụng không có chỉ số trên tập kiểm tra (ví dụ được đăng ký ngoài quy trình) cũng cho Chưa đủ dữ liệu, không bao giờ cho Ổn.

**Mức tổng hợp** là mức nặng nhất trong ba loại, **bỏ qua** Chưa đủ dữ liệu. Nếu cả ba đều Chưa đủ dữ liệu thì mức tổng hợp cũng là Chưa đủ dữ liệu. Bảng điều khiển luôn hiện ba loại tách riêng; mức tổng hợp chỉ là thông tin phụ, không bao giờ thay cho ba loại.

### 7.3. Kết quả của một lần giám sát

Mỗi lần giám sát, cho mỗi mô hình, tạo ra:

| Kết quả | Nội dung | Dùng bởi |
| --- | --- | --- |
| Bản tóm tắt | Tên và phiên bản mô hình, bài toán, mã lần giám sát, thời điểm, khoảng thời gian xét, mức tổng hợp, mức của từng loại trôi, số dự đoán, số kết quả thực tế ghép được, chỉ số trên lưu lượng thực tế, chỉ số trên tập kiểm tra và nguồn của nó | Bảng điều khiển (báo cáo mới nhất, diễn biến) |
| Bản sao tóm tắt mới nhất | Ghi đè mỗi lần giám sát | Bảng điều khiển đọc báo cáo mới nhất bằng một lần đọc, không phải liệt kê và so thời gian |
| Báo cáo chi tiết | Trang web do Evidently sinh ra, dung lượng khoảng 5 MB | Bảng điều khiển, chỉ tải khi người vận hành bấm xem |

Các bản tóm tắt được viết trước ngày 22/09/2026 không có trường chỉ số trên tập kiểm tra; mọi nơi đọc bản tóm tắt phải chịu được việc thiếu trường này.

### 7.4. Môi trường của bước giám sát

Evidently kéo theo khoảng 500 MB thư viện vẽ biểu đồ. Nó **không** được cài vào môi trường nền dùng chung (mục 11.4) mà chỉ vào môi trường riêng của bước giám sát, để dịch vụ dự đoán — thứ không bao giờ tính trôi — không phải mang thêm dung lượng đó. Vì vậy phần quy tắc xếp mức (mục 7.2) nằm trong thành phần dùng chung và **không phụ thuộc Evidently**: đó là phần dễ sai nhất, nên phải kiểm thử được rẻ nhất, trên máy phát triển không có Evidently.

---

## 8. Thiết kế màn hình

### 8.1. Danh sách màn hình

| STT | Màn hình | Mục đích | Yêu cầu |
| --- | --- | --- | --- |
| 1 | Tổng quan | Khởi chạy quy trình huấn luyện, xem các lần chạy | CN-35 |
| 2 | Dữ liệu | Tải dữ liệu lên, xem mẫu và thống kê | CN-36 |
| 3 | Mô hình | Xem, chỉ định, xoá phiên bản mô hình | CN-37 |
| 4 | Giám sát trôi | Mô phỏng lưu lượng, xem kết quả giám sát | CN-38 |

Giao diện tiếng Việt. Ưu tiên màn hình máy tính xách tay (từ khoảng 1.280 điểm ảnh chiều ngang); bảng rộng cuộn ngang bên trong khung, không làm cả trang cuộn ngang. Số định dạng theo kiểu Việt Nam (2.012.000); thời gian hiển thị tương đối ("3 phút trước") kèm giờ tuyệt đối khi di chuột.

### 8.2. Quy ước chung

**Thanh trạng thái hệ thống.** Luôn hiện ở đầu trang, cho biết trạng thái riêng của năm thành phần: Airflow, MLflow, MinIO, dịch vụ dự đoán, PostgreSQL (CN-39). Không làm mới nhanh hơn mỗi 10 giây, và không gửi yêu cầu mới khi yêu cầu trước chưa trả lời. Không kết nối được tới lớp trung gian là một trạng thái riêng, khác với "có thành phần hỏng".

**Nhãn mức độ bốn trạng thái (CN-31).** Mỗi nhãn luôn có chữ; màu không bao giờ là kênh duy nhất.

| Trạng thái | Nhãn | Hình thức |
| --- | --- | --- |
| Ổn | ổn | Nền xanh lá nhạt, biểu tượng dấu tích, viền liền |
| Cảnh báo | cảnh báo | Nền vàng nhạt, biểu tượng tam giác chấm than, viền liền |
| Cao | cao | Nền đỏ nhạt, biểu tượng dấu X trong vòng tròn, viền liền đậm |
| Chưa đủ dữ liệu | chưa đủ dữ liệu | Nền xám **gạch chéo**, biểu tượng vòng tròn rỗng, viền **nét đứt** |

"Chưa đủ dữ liệu" khác "Ổn" ở ba trục cùng lúc — hoa văn, viền, chữ — để người mù màu và bản in đen trắng vẫn phân biệt được (NV-07). Hoa văn gạch chéo chỉ dành riêng cho trạng thái này. Tương phản chữ và nền tối thiểu 4,5:1.

**Ba tình huống không có dữ liệu bình thường (CN-40):**

| Tình huống | Hiển thị |
| --- | --- |
| Chưa có dữ liệu (ví dụ ngày đầu chưa có lưu lượng, chưa có báo cáo giám sát, phiên bản dữ liệu chưa tải lên) | Nói vì sao trống và làm gì tiếp theo. **Không phải lỗi.** |
| Không tìm thấy | "Không tìm thấy" kèm lý do. Không phải sự cố hạ tầng. |
| Hệ thống đang hỏng | "Hệ thống đang hỏng", nút thử lại, trỏ tới thanh trạng thái để biết thành phần nào hỏng |

Mỗi màn hình có trạng thái đang tải riêng, không để màn hình trắng.

**Xác nhận trước thao tác ghi (CN-41):**

| Thao tác | Khi nào hỏi xác nhận |
| --- | --- |
| Khởi chạy huấn luyện | Luôn luôn, nêu lại đủ các lựa chọn |
| Chỉ định phiên bản đang sử dụng | Luôn luôn |
| Tải dữ liệu lên | Chỉ khi phiên bản đích đã tồn tại (sẽ bị ghi đè) |
| Xoá một phiên bản mô hình | Luôn luôn |
| Xoá toàn bộ một mô hình | Luôn luôn, nêu rõ không hoàn tác được |

Sau thao tác ghi, giao diện luôn tải lại dữ liệu thật thay vì tự cập nhật trước; thao tác thất bại không bao giờ được báo là thành công.

**Chế độ minh hoạ (PCN-25).** Công tắc ở thanh bên: khi bật, mọi màn hình dùng dữ liệu mẫu thay vì gọi lớp trung gian.

### 8.3. Nội dung từng màn hình

**Màn hình 1 — Tổng quan**

| Thành phần | Nội dung |
| --- | --- |
| Biểu mẫu khởi chạy | Bài toán (bắt buộc, không chọn sẵn); thuật toán (danh sách theo bài toán, bỏ trống là mặc định); tinh chỉnh tham số (ô đánh dấu); số dòng huấn luyện hoặc "dùng toàn bộ dòng"; xử lý lại dữ liệu từ đầu (ô đánh dấu); phiên bản dữ liệu (ô nhập chữ — hệ thống không có danh sách phiên bản) |
| Hộp xác nhận | Nêu đủ các lựa chọn. Khi chọn toàn bộ dòng, cảnh báo lần chạy sẽ lâu hơn và tốn bộ nhớ hơn nhiều. Nút xác nhận ghi rõ "Bắt đầu huấn luyện". |
| Bảng các lần chạy gần đây | Mã lần chạy, trạng thái, bài toán, thời điểm bắt đầu, kết thúc, thời lượng |
| Dải tiến trình | Chín ô theo đúng thứ tự của quy trình (mục 3.1), nhánh "đăng ký → đưa vào sử dụng" và nhánh "dừng" đặt song song sau bước rẽ nhánh. Ô chưa chạy khác ô bị bỏ qua; ô bị bỏ qua vì nhánh không được chọn không phải lỗi. |

**Màn hình 2 — Dữ liệu**

| Thành phần | Nội dung |
| --- | --- |
| Tải lên | Kéo thả tệp CSV; ô tên phiên bản (kiểm tra quy tắc tên ngay khi nhập); thanh tiến độ, rồi "đang chuyển định dạng". Tệp vượt 500 MiB bị khoá ngay ở trình duyệt, không gửi đi. |
| Dòng mẫu | Tối đa 200 dòng, **đúng như dữ liệu thô** — không chuẩn hoá trên giao diện; ô trống có dấu hiệu nhìn thấy được |
| Thống kê theo cột | Loại dữ liệu, tỉ lệ thiếu, số giá trị ngoài khoảng hợp lệ. Luôn ghi rõ "thống kê trên N / M dòng" (mục 14.2). |
| Số dòng xem trước | Chọn 10 / 50 / 100 / 200. Đặt xa mọi nhãn có chữ "huấn luyện", để không lẫn với số dòng huấn luyện của màn Tổng quan. |

**Màn hình 3 — Mô hình**

| Thành phần | Nội dung |
| --- | --- |
| Mỗi mô hình một khối | Tên, bài toán, các chỉ số của phiên bản đang sử dụng |
| Bảng phiên bản | Số phiên bản, các chỉ số trên tập kiểm tra, thời điểm tạo, nhãn "đang sử dụng". **Cột chỉ số sinh ra từ dữ liệu thật của mô hình**, không cố định: RMSE / MAE / R² cho bài toán giá bán; AUC / F1 / độ chính xác cho bài toán cải tạo. |
| Chỉ định làm phiên bản đang sử dụng | Chỉ có ở hàng không phải phiên bản đang sử dụng |
| Xoá phiên bản | Bị từ chối với phiên bản đang sử dụng (CN-17) |
| Xoá toàn bộ mô hình | Không hoàn tác được (CN-18) |

**Màn hình 4 — Giám sát trôi**

| Thành phần | Nội dung |
| --- | --- |
| Chọn mô hình | Danh sách mô hình đang có |
| Khối mô phỏng lưu lượng | Kịch bản (năm kịch bản, nhãn tiếng Việt), số yêu cầu (1–5.000), nút "Gửi lưu lượng". Dải tiến trình hai chặng: gửi lưu lượng → tính giám sát. Tự tải lại báo cáo khi xong. |
| Ba ô mức độ | Trôi dữ liệu đầu vào, trôi kết quả dự đoán, suy giảm độ chính xác — **ba ô riêng**, mỗi ô một nhãn bốn trạng thái kèm một dòng nói nó so sánh cái gì. Thời điểm tính báo cáo. |
| Thông báo chưa đủ dữ liệu | Khi suy giảm độ chính xác là Chưa đủ dữ liệu: nêu số kết quả thực tế đã có, và nói rõ đây **không phải** là ổn |
| Bảng so sánh chỉ số | Chỉ số · trên tập kiểm tra · trên lưu lượng thực tế · chênh lệch (tô đỏ khi tệ hơn, xanh khi tốt hơn) |
| Biểu đồ diễn biến | **Ba dải riêng xếp dọc, mỗi dải một màu**, mỗi điểm là một lần giám sát, tô theo mức tại lúc đó. Dưới đó là một dải chỉ số thật (RMSE hoặc AUC) kèm đường nét đứt là chỉ số trên tập kiểm tra. Phía trên có một dòng kết luận bằng chữ: bao nhiêu trong các lần gần nhất ở mức cao, mức nào vừa đổi, và cảnh báo khi diễn biến gồm nhiều phiên bản mô hình khác nhau. |
| Báo cáo chi tiết | Nút "Xem báo cáo" mở báo cáo của Evidently ngay trong trang, kèm một dòng giải thích vì sao kết luận của báo cáo có thể khác nhãn mức độ (mục 14.2) |
| Nút huấn luyện lại | Chỉ hiện khi có mức Cao. Chuyển sang màn Tổng quan với bài toán đã điền sẵn; việc xác nhận nằm ở hộp xác nhận của màn đó. |
| Ghi chú cập nhật | "Báo cáo tính lúc … Lưu lượng vừa gửi có thể chưa có trong báo cáo này", kèm nút "Tải lại" |

Biểu đồ diễn biến chỉ **hiển thị** mức do bước giám sát tính; giao diện không tự đặt ngưỡng nào. Ngưỡng thuộc về bước giám sát; chép sang giao diện là tạo một bản thứ hai sẽ lệch.

---

## 9. Thiết kế liên kết giữa các thành phần

### 9.1. Bảng điều khiển với lớp trung gian

| Thao tác trên bảng điều khiển | Lớp trung gian chuyển tới | Yêu cầu |
| --- | --- | --- |
| Khởi chạy quy trình huấn luyện → nhận mã lần chạy (trả về ngay, không chờ chạy xong) | Airflow | CN-05 |
| Xem danh sách các lần chạy gần đây | Airflow | CN-35 |
| Xem trạng thái từng bước của một lần chạy | Airflow | CN-35 |
| Lấy danh sách thuật toán theo bài toán | Thành phần dùng chung | CN-05 |
| Tải dữ liệu lên → nhận tên phiên bản, số dòng | MinIO | CN-01 |
| Xem mẫu và thống kê cột của một phiên bản dữ liệu | MinIO | CN-03 |
| Xem danh sách mô hình, phiên bản, chỉ số, phiên bản đang sử dụng | MLflow | CN-15 |
| Chỉ định phiên bản đang sử dụng | MLflow | CN-16 |
| Xoá một phiên bản | MLflow | CN-17 |
| Xoá toàn bộ một mô hình | MLflow | CN-18 |
| Lấy danh sách kịch bản thị trường | Thành phần dùng chung | CN-25 |
| Khởi chạy mô phỏng lưu lượng | Airflow | CN-25 |
| Xem trạng thái lần mô phỏng gần nhất, gồm trạng thái hai chặng | Airflow | CN-28 |
| Khởi chạy giám sát trực tiếp (không có nút trên bảng điều khiển; dùng khi cần tính lại mà không gửi thêm lưu lượng) | Airflow | CN-29 |
| Xem báo cáo giám sát mới nhất | MinIO | CN-33 |
| Xem diễn biến qua các lần giám sát | MinIO | CN-33 |
| Xem báo cáo chi tiết của một lần giám sát | MinIO | CN-33 |
| Xem trạng thái các thành phần phụ thuộc (mỗi thành phần tối đa 5 giây) | Tất cả | CN-39 |

Lớp trung gian gọi Airflow bằng tài khoản dịch vụ. Airflow mặc định chỉ chấp nhận phiên đăng nhập từ trình duyệt, nên phải bật thêm phương thức xác thực bằng tên và mật khẩu cho các lời gọi từ dịch vụ khác; thiếu cấu hình này, mọi lời gọi bị từ chối với thông báo không gợi ý đúng nguyên nhân.

Nếu lớp trung gian không dựng được kết nối tới một thành phần (thiếu cấu hình), nó vẫn khởi động và báo thành phần đó "hỏng" ở chức năng trạng thái, thay vì dừng.

### 9.2. Liên kết giữa các thành phần phía sau

| Từ | Tới | Nội dung |
| --- | --- | --- |
| Airflow | Các bước xử lý, tác nhân mô phỏng | Khởi chạy từng bước trong container riêng; truyền các tham số và giá trị nhỏ |
| Các bước xử lý | MinIO | Đọc/ghi dữ liệu, hồ sơ thống kê, báo cáo |
| Các bước xử lý | MLflow | Ghi kết quả huấn luyện; đọc mô hình đang sử dụng để so sánh; đăng ký phiên bản mới |
| Bước "đưa vào sử dụng" | Dịch vụ dự đoán | Yêu cầu nạp lại mô hình |
| Quy trình mô phỏng lưu lượng | Quy trình giám sát | Khởi chạy và chờ xong |
| Dịch vụ dự đoán | MLflow | Lấy phiên bản mô hình đang sử dụng |
| Dịch vụ dự đoán | MinIO | Ghi nhật ký dự đoán, kết quả thực tế |
| Tác nhân mô phỏng | MinIO | Đọc dữ liệu nguồn |
| Tác nhân mô phỏng | Dịch vụ dự đoán | Gửi yêu cầu dự đoán, gửi kết quả thực tế |
| MLflow | PostgreSQL, MinIO | Lưu thông tin quản lý vào PostgreSQL; lưu tệp mô hình vào MinIO |
| Airflow | PostgreSQL | Lưu thông tin quản lý |

---

## 10. Thiết kế dữ liệu

### 10.1. Bố cục kho lưu trữ đối tượng

Toàn bộ dữ liệu nằm trong một vùng lưu trữ, chia thành các khu vực sau:

| Khu vực | Nội dung | Cách phân chia | Tạo bởi | Dùng bởi |
| --- | --- | --- | --- | --- |
| Dữ liệu thô | Dữ liệu tải lên | Theo phiên bản dữ liệu | Chức năng tải lên; nạp lần đầu lúc cài đặt | Bước tiếp nhận, tác nhân mô phỏng, xem trước dữ liệu |
| Bản làm việc | Dữ liệu thô đã lấy đúng số dòng | Theo mã nhận dạng dữ liệu | Bước tiếp nhận | Kiểm tra chất lượng, chuẩn bị dữ liệu |
| Báo cáo chất lượng | Kết quả kiểm tra chất lượng | Theo mã nhận dạng dữ liệu | Bước kiểm tra chất lượng | Người vận hành |
| Dữ liệu đã chuẩn bị | Tập huấn luyện, tập kiểm tra | Theo mã nhận dạng dữ liệu, rồi theo bài toán | Bước chuẩn bị dữ liệu | Huấn luyện, đánh giá, đăng ký, giám sát |
| Tệp mô hình | Mô hình đã huấn luyện và tệp liên quan | Do MLflow quản lý | MLflow | Dịch vụ dự đoán, đánh giá, giám sát |
| Hồ sơ thống kê cơ sở | Hồ sơ của từng phiên bản mô hình | Theo tên mô hình, rồi số phiên bản | Bước đăng ký | Tham khảo |
| Nhật ký dự đoán | Nhật ký mỗi lần dự đoán | Theo tên mô hình, rồi theo ngày | Dịch vụ dự đoán | Bước giám sát |
| Kết quả thực tế | Kết quả thực tế | Theo tên mô hình, rồi theo ngày đã dự đoán | Dịch vụ dự đoán | Bước giám sát |
| Báo cáo giám sát | Bản tóm tắt, báo cáo chi tiết của mỗi lần giám sát; bản sao tóm tắt mới nhất | Theo tên mô hình, rồi mã lần giám sát | Bước giám sát | Bảng điều khiển |

**Toàn bộ quy ước đặt tên vị trí lưu trữ nằm ở một chỗ duy nhất** trong thành phần dùng chung (mục 2.4). Không chỗ nào khác trong hệ thống tự ghép tên vị trí. Khi chuyển sang Amazon S3, chỉ chỗ này phải sửa (PCN-15).

Giám sát phụ thuộc vào dữ liệu đã chuẩn bị (mục 7.1): nếu dữ liệu đã chuẩn bị của phiên bản đang sử dụng bị xoá, giám sát sẽ thất bại và báo rõ vị trí bị thiếu.

### 10.2. Định dạng lưu trữ

| Dữ liệu | Định dạng | Lý do |
| --- | --- | --- |
| Dữ liệu tải lên | CSV, được chuyển sang Parquet ngay khi nhận | Định dạng đầu vào của người vận hành |
| Mọi dữ liệu dạng bảng trong kho | Parquet, nén | Dung lượng giảm từ khoảng 373 MB còn khoảng 60–80 MB; đọc nhanh hơn nhiều lần; giữ nguyên kiểu dữ liệu nên các bước sau không phải đọc lại từ đầu (PCN-03) |
| Hồ sơ thống kê, báo cáo chất lượng, bản tóm tắt giám sát | Văn bản có cấu trúc | Đọc được bằng các công cụ thông dụng |
| Báo cáo chi tiết giám sát | Trang web | Xem được bằng trình duyệt |

### 10.3. Cơ sở dữ liệu quản lý

| Cơ sở dữ liệu | Dùng bởi | Nội dung |
| --- | --- | --- |
| Của hệ thống điều phối | Airflow | Lịch sử chạy, trạng thái từng bước |
| Của quản lý mô hình | MLflow | Lịch sử huấn luyện, phiên bản mô hình, nhãn phiên bản đang sử dụng |

Hai cơ sở dữ liệu riêng biệt trên cùng một máy chủ PostgreSQL. Tách riêng để hai công cụ không ảnh hưởng dữ liệu của nhau, và để có thể chuyển từng cái sang dịch vụ đám mây độc lập.

---

## 11. Thiết kế phi chức năng

### 11.1. Tài nguyên và hiệu năng

| Biện pháp | Đáp ứng |
| --- | --- |
| Dùng lại bản làm việc và dữ liệu đã chuẩn bị khi dữ liệu thô không đổi (mục 3.2, 3.4) | PCN-02 |
| Lưu mọi dữ liệu dạng bảng ở dạng Parquet (mục 10.2) | PCN-01, PCN-03 |
| Ghi nhật ký dự đoán theo lô (mục 5.3) | PCN-04 |
| Người vận hành chọn số dòng cho từng lần huấn luyện; số dòng nằm trong mã nhận dạng dữ liệu | PCN-05 |
| Lưới tinh chỉnh tham số tối đa 8 tổ hợp, kiểm định chéo 5 phần (mục 3.5) | PCN-06 |
| Giám sát chỉ lấy mẫu tối đa 10.000 dòng làm mốc (mục 7.1) | PCN-01 |
| Công cụ phát hiện trôi chỉ nằm trong môi trường của bước giám sát (mục 7.4) | PCN-01 |
| Hệ thống điều phối chạy ở chế độ một máy, không cần hàng đợi hay máy chủ phân tán | PCN-01 |
| Không quy trình nào chạy theo lịch (mục 3) | NV-01 |

### 11.2. Chạy lại và độ tin cậy

- Vị trí đầu ra của mỗi bước được xác định hoàn toàn bởi đầu vào, nên chạy lại luôn ghi vào đúng chỗ cũ hoặc bỏ qua nếu đã có (PCN-07).
- Mỗi quy trình chỉ chạy một lần tại một thời điểm (PCN-11).
- Phần xử lý dữ liệu trong mô hình chịu được thiếu mục, giá trị trống, giá trị phân loại mới, và không bao giờ loại bản ghi (mục 4; PCN-08, PCN-09).
- Dịch vụ dự đoán khởi động được khi thiếu mô hình (mục 5.2); việc ghi nhật ký có giới hạn mất mát nhìn thấy được (mục 5.3; PCN-10).
- Lớp trung gian khởi động được khi thiếu kết nối tới một thành phần (mục 9.1).

### 11.3. Bảo mật

| Biện pháp | Đáp ứng |
| --- | --- |
| Thông tin xác thực nằm trong tệp cấu hình riêng không đưa lên kho lưu trữ dùng chung; kho chỉ chứa tệp mẫu không có giá trị thật. Hệ thống điều phối chuyển chúng vào các container xử lý khi khởi chạy. | PCN-12 |
| Bảng điều khiển chỉ nói chuyện với lớp trung gian (mục 2.3). Ranh giới này hiện được giữ bằng quy ước và đã được kiểm bằng tay; chưa có bước kiểm tra tự động (mục 14.2). | PCN-13 |
| Mọi thao tác của lớp trung gian đi qua **một điểm kiểm tra quyền truy cập dùng chung**. Hiện điểm này chưa kiểm tra gì; khi bật xác thực, chỉ phải sửa ở đúng một chỗ, không phải sửa từng thao tác và bỏ sót. | PCN-14 |
| Xoá phiên bản đang sử dụng bị chặn ở lớp trung gian, không chỉ ở giao diện — gọi thẳng lớp trung gian cũng không vượt qua được | CN-17 |
| Báo cáo chi tiết giám sát được hiển thị trong một khung tách biệt, không truy cập được vào trang chứa nó | — |

### 11.4. Môi trường thực thi đồng nhất

- Có **một môi trường nền dùng chung**, chứa sẵn các thư viện xử lý dữ liệu và học máy cùng thành phần dùng chung (mục 2.4). Mọi bước xử lý, dịch vụ dự đoán, tác nhân mô phỏng và lớp trung gian đều xây dựng trên môi trường nền này.
- Không có môi trường nền này, mỗi thành phần sẽ tự cài lại thư viện: xây dựng rất lâu, và phiên bản thư viện dễ lệch giữa các thành phần. Lệch phiên bản giữa lúc huấn luyện và lúc dự đoán là loại lỗi khó tìm nhất.
- Mô hình đã lưu chỉ đọc lại được đúng trong môi trường có cùng phiên bản nền tảng và thư viện với lúc lưu. Vì vậy huấn luyện và dự đoán **đều diễn ra trong container**, không huấn luyện trên máy phát triển (PCN-20, RB-03). Ví dụ đã gặp: khi thêm thư viện của thuật toán XGBoost, dịch vụ dự đoán cũng phải được xây dựng lại, nếu không nó sẽ không đọc được mô hình huấn luyện bằng XGBoost.
- Mỗi khi thành phần dùng chung thay đổi, **phải xây dựng lại môi trường nền và mọi môi trường dựa trên nó**, theo đúng thứ tự. Chỉ xây dựng lại môi trường nền là chưa đủ: các môi trường dựa trên nó vẫn giữ bản cũ bên trong cho tới khi được xây dựng lại.

### 11.5. Kiểm thử

| Nội dung | Đáp ứng |
| --- | --- |
| Mỗi loại lỗi dữ liệu trong 要件定義書 mục 6.4 có kiểm thử tự động riêng | PCN-18 |
| Phần xử lý dữ liệu không loại bản ghi, và dự đoán được cho đúng một căn nhà | PCN-09 |
| Mô hình nhận được dữ liệu thô chưa làm sạch | CN-19 |
| Các mục bị loại không ảnh hưởng kết quả dự đoán (kiểm bằng một thuật toán thật sự dùng dữ liệu, không bằng mô hình đoán mò — mô hình đoán mò sẽ vượt qua kiểm thử này dù thiết kế sai) | NV-05 |
| Giá trị phân loại mới và giá trị thiếu không gây lỗi | PCN-08 |
| Mô hình sau khi lưu rồi nạp lại cho cùng kết quả | PCN-19 |
| Các cổng đánh giá chặn được mô hình đoán mò | PCN-22 |
| Quy tắc xếp mức giám sát, gồm trường hợp chưa đủ dữ liệu | NV-07 |
| Dự đoán không bao giờ đoán vượt quá ba lần giá trị lớn nhất của đáp án (canh chừng phép biến đổi thang đo quay lại, mục 3.5) | — |
| Phần đọc/ghi kho lưu trữ được kiểm thử trên một kho giả lập trong bộ nhớ, rồi kiểm tra lại trên MinIO thật | PCN-16 |
| Mỗi giai đoạn xây dựng từ hạ tầng tới lớp trung gian có một kịch bản kiểm tra chạy trên hệ thống thật. Bảng điều khiển được kiểm tra bằng trình duyệt, chưa có kịch bản tự động. | — |

Đo ngày 23/09/2026: 666 kiểm thử tự động đạt trên máy phát triển.

---

## 12. Thiết kế chuyển đổi lên AWS (giai đoạn 2)

### 12.1. Đối ứng thành phần

| Vai trò | Giai đoạn 1 | Giai đoạn 2 (AWS) |
| --- | --- | --- |
| Bảng điều khiển | Ứng dụng web | Giữ nguyên |
| Lớp trung gian | Dịch vụ web trong container | Giữ nguyên, triển khai trên Amazon ECS / AWS Fargate hoặc AWS Lambda |
| Hệ thống điều phối | Apache Airflow | Amazon MWAA |
| Kho lưu trữ đối tượng | MinIO | Amazon S3 |
| Bước huấn luyện | Container Docker | Amazon SageMaker Training Job |
| Các bước xử lý dữ liệu | Container Docker | Amazon SageMaker Processing Job |
| Quản lý thí nghiệm | MLflow | MLflow trên Amazon EC2 / ECS, hoặc Amazon SageMaker Experiments |
| Quản lý phiên bản mô hình | MLflow Model Registry | Amazon SageMaker Model Registry |
| Dịch vụ dự đoán và chức năng nạp lại mô hình | Dịch vụ web trong container | Amazon SageMaker Endpoint (cập nhật cấu hình Endpoint thay cho chức năng nạp lại) |
| Nhật ký dự đoán | Dịch vụ dự đoán tự ghi vào MinIO | Amazon SageMaker Data Capture |
| Mốc so sánh của giám sát | Tự tính khi giám sát | Tác vụ tạo mốc của Amazon SageMaker Model Monitor |
| Giám sát trôi | Evidently, chạy theo yêu cầu | Lịch giám sát của Amazon SageMaker Model Monitor, **chạy mỗi giờ** |
| Cơ sở dữ liệu quản lý | PostgreSQL | Amazon Aurora |
| Khởi động toàn hệ thống | Docker Compose | Amazon ECS / EKS, hoặc container do SageMaker quản lý |
| Khởi chạy quy trình | Thủ công từ bảng điều khiển | AWS CodePipeline + Amazon EventBridge |

### 12.2. Nguyên tắc chuyển đổi

1. **Kho lưu trữ:** chỉ thay địa chỉ kết nối từ MinIO sang Amazon S3. Toàn bộ quy ước vị trí lưu trữ nằm ở một chỗ (mục 10.1), nên chỉ chỗ đó phải sửa.
2. **Bảng điều khiển:** không thay đổi. Lớp trung gian thay đổi để trỏ tới các dịch vụ AWS (mục 2.3).
3. **Giám sát:** trở lại chạy định kỳ mỗi giờ, vì trên đám mây chi phí tài nguyên của việc chạy định kỳ không còn là vấn đề như trên máy 16 GB.
4. **Xác thực:** phải bật trước khi hệ thống có thể truy cập được từ ngoài (PCN-14).
5. **Chuyển dần từng thành phần**, không chuyển đồng loạt. Mỗi bước xử lý đã là một container độc lập (nguyên tắc 1, mục 1.2), nên từng bước có thể chuyển riêng.

---

## 13. Đối chiếu yêu cầu

| Yêu cầu | Mục thiết kế |
| --- | --- |
| NV-01 Không chạy theo lịch | 1.2, 3 |
| NV-02 Không tự huấn luyện lại | 3.10, 8.3 (màn hình 4) |
| NV-03 Hai cổng đánh giá | 3.6 |
| NV-04 Làm sạch giống nhau khi huấn luyện và dự đoán | 2.4, 3.4, 3.5, 4.1 |
| NV-05 Loại thông tin khỏi đầu vào | 4.6 |
| NV-06 Tập kiểm tra chung | 3.4, 3.6 |
| NV-07 Không báo "ổn" khi chưa đo | 7.2, 8.2 |
| CN-01 – CN-04 Quản lý dữ liệu | 3.1, 8.3 (màn hình 2), 9.1, 10.1 |
| CN-05 – CN-06 Khởi chạy quy trình | 3.1, 8.3 (màn hình 1) |
| CN-07 Tiếp nhận | 3.2 |
| CN-08 Kiểm tra chất lượng | 3.3 |
| CN-09 Chuẩn bị dữ liệu | 3.4, 4.7 |
| CN-10 Huấn luyện | 3.5 |
| CN-11 Đánh giá | 3.6 |
| CN-12 Đăng ký | 3.7, 7.1 |
| CN-13 Đưa vào sử dụng | 3.8, 5.2 |
| CN-14 Dừng khi không đạt | 3.1 (bước 9) |
| CN-15 – CN-18 Quản lý mô hình | 8.3 (màn hình 3), 9.1, 11.3 |
| CN-19 – CN-24 Dự đoán | 4, 5 |
| CN-25 – CN-28 Mô phỏng thị trường | 3.9, 6 |
| CN-29 – CN-34 Giám sát | 3.10, 7, 8.3 (màn hình 4) |
| CN-35 – CN-41 Bảng điều khiển | 8, 9.1 |
| PCN-01 – PCN-06 Hiệu năng và tài nguyên | 11.1 |
| PCN-07 – PCN-11 Độ tin cậy | 4.1, 4.5, 5.3, 11.2 |
| PCN-12 – PCN-14 Bảo mật | 2.3, 11.3 |
| PCN-15 – PCN-17 Chuyển đổi lên đám mây | 10.1, 12 |
| PCN-18 – PCN-22 Chất lượng | 3.4, 3.6, 11.4, 11.5 |
| PCN-23 – PCN-25 Vận hành | 2.2, 8 |

---

## 14. Vấn đề còn mở và hạn chế đã biết

### 14.1. Vấn đề còn mở

| STT | Vấn đề | Thời điểm quyết định |
| --- | --- | --- |
| 1 | Cách phục vụ bảng điều khiển ở bản chính thức: lớp trung gian tự phục vụ giao diện từ cùng địa chỉ, hay cho phép giao diện ở địa chỉ khác gọi vào. Lựa chọn thứ hai là một quyết định bảo mật, vì hệ thống chưa có xác thực. | Trước khi triển khai chính thức |
| 2 | Cơ chế xác thực cụ thể cho lớp trung gian | Trước khi mở hệ thống ra ngoài máy cục bộ |
| 3 | Khi chuyển lên AWS, giữ MLflow song song với Amazon SageMaker Model Registry hay chuyển hẳn | Giai đoạn 2 |
| 4 | Có nên đổi mục mà hai kịch bản "Lạm phát giá rao" và "Thị trường tăng giá" biến đổi sang một mục mô hình dự đoán giá thật sự dùng (ví dụ diện tích sử dụng), để chúng thử được trôi dữ liệu đầu vào. Loại giá rao bán khỏi danh sách bị loại **không** phải là câu trả lời: lý do loại nó (要件定義書 mục 6.3) vẫn đúng. | Khi xem xét lại các kịch bản |
| 5 | Thời gian phản hồi mục tiêu của dịch vụ dự đoán, thời gian lưu giữ dữ liệu, cách sao lưu | Trước giai đoạn 2 |

### 14.2. Hạn chế đã biết

| Hạn chế | Ảnh hưởng | Hướng xử lý |
| --- | --- | --- |
| **Chỉ định phiên bản hay xoá mô hình trên bảng điều khiển không làm dịch vụ dự đoán nạp lại.** Nhãn phiên bản đang sử dụng đổi ngay trong MLflow, nhưng dịch vụ dự đoán chỉ nạp lại khi khởi động hoặc khi một lần huấn luyện đi tới bước "đưa vào sử dụng". | Sau khi chỉ định thủ công, dịch vụ vẫn trả lời bằng mô hình cũ cho tới lần nạp lại kế tiếp; nhật ký dự đoán ghi đúng phiên bản thực sự đã dùng. | Chưa quyết định |
| Việc ghi nhật ký dự đoán diễn ra ở nền. Chạy giám sát ngay sau một đợt lưu lượng lớn có thể bắt trúng lúc một phần nhật ký chưa được ghi xuống kho (quan sát được một lần: 33 trên 500 dự đoán). | Báo cáo giám sát có thể thiếu một phần lưu lượng vừa gửi. Bảng điều khiển luôn hiện ghi chú về khả năng này. | Chưa sửa |
| Kịch bản "Không thay đổi" không phải một mốc sạch tuyệt đối: mục mã bưu chính luôn bị coi là trôi. Nguyên nhân: tác nhân lấy các căn nhà mới nhất theo ngày đăng bán, còn khi huấn luyện trên một phần dữ liệu thì mô hình học các dòng đầu tệp — hai phần khác nhau của cùng bộ dữ liệu. | Mọi ngưỡng hiệu chỉnh dựa trên kịch bản này thừa hưởng sai lệch đó. | Chưa sửa |
| Đường phân cách của luật độ lớn (mục 7.2) dựa trên đúng hai lần đo, chưa có một quy tắc thống kê đứng sau. Luật này cũng phụ thuộc số mục đầu vào: càng nhiều mục không trôi, càng dễ che mất một mục trôi nặng. | Có thể báo sai khi số mục đầu vào thay đổi. | Hiệu chỉnh lại khi có thêm số đo |
| Báo cáo chi tiết của Evidently kết luận theo luật tỉ lệ riêng của nó (trên 50% số mục trôi), khác với quy tắc hai luật của hệ thống. | Báo cáo chi tiết có thể ghi "không phát hiện trôi" trong khi nhãn mức độ báo Cảnh báo (đo thật ngày 22/09/2026). Khung báo cáo có dòng giải thích điều này. | Chấp nhận |
| Mã bưu chính được xử lý như một mục phân loại, trong khi nó có hàng chục nghìn giá trị khác nhau. Với quy tắc gộp giá trị dưới 1% (mục 4.5), trên dữ liệu lớn gần như mọi mã bưu chính sẽ rơi vào nhóm "hiếm". | Mục này gần như không đóng góp vào dự đoán. Vô hại nhưng lãng phí. | Chưa quyết định; ví dụ gộp theo ba chữ số đầu |
| Định dạng ngày có tên tháng tiếng Anh viết tắt ("15-Jul-2023") phụ thuộc vào thiết lập ngôn ngữ của môi trường thực thi. | Nếu môi trường nền được thiết lập ngôn ngữ khác tiếng Anh, toàn bộ ngày ở định dạng này sẽ âm thầm trở thành giá trị thiếu. | Kiểm tra khi xây dựng lại môi trường nền |
| Xem trước dữ liệu tải nguyên tệp vào bộ nhớ mỗi lần gọi, nhưng chỉ tính thống kê trên 200.000 dòng đầu. | Mỗi lần xem tốn 1,4–2 giây và đẩy bộ nhớ của lớp trung gian lên khoảng 0,9–1,3 GB (đo ngày 21/09/2026). Thống kê là của phần đầu tệp, có thể không đại diện cho cả tệp. Tỉ lệ thiếu ở đây đếm cả ô rỗng nên có thể cao hơn con số trong báo cáo chất lượng. | Giao diện ghi rõ "thống kê trên N / M dòng"; chỉ gọi khi người vận hành bấm xem |
| Trần 500 MiB của chức năng tải lên chỉ được kiểm tra **sau khi** toàn bộ tệp đã tới máy chủ. | Tệp vượt trần vẫn chiếm đĩa tạm (tối đa khoảng ba bản) trước khi bị từ chối. | Giao diện chặn tệp vượt trần ngay ở trình duyệt |
| Hai lần kiểm tra trạng thái hệ thống chồng lên nhau có thể báo cả năm thành phần đều hỏng. Trạng thái của PostgreSQL được suy ra qua Airflow, nên luôn báo hỏng khi Airflow hỏng. | Báo động giả. | Giao diện không gửi yêu cầu mới khi yêu cầu trước chưa trả lời (mục 8.2) |
| Chưa có bước kiểm tra tự động xác nhận bảng điều khiển không gọi thẳng Airflow, MLflow hay MinIO. | Một thay đổi sau này có thể vô tình phá ranh giới ở mục 2.3 mà không ai phát hiện. | Thêm bước kiểm tra tự động, như đã làm với ranh giới của dịch vụ dự đoán |
| Trạng thái "ổn" của dịch vụ dự đoán ở thanh trạng thái chỉ cho biết dịch vụ trả lời được, không cho biết đã có mô hình. | Sau khi xoá hết mô hình, thanh trạng thái vẫn báo dịch vụ dự đoán ổn. | Màn Mô hình và Giám sát trôi có trạng thái "chưa có mô hình" riêng |
