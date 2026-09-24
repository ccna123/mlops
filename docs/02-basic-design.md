# 基本設計書 — Hệ thống vận hành học máy dự đoán giá bất động sản

| Mục | Nội dung |
| --- | --- |
| Tên tài liệu | 基本設計書 (Tài liệu thiết kế cơ bản) |
| Hệ thống | Hệ thống vận hành học máy dự đoán giá bất động sản |
| Phiên bản | 1.0 |
| Ngày lập | 24/09/2026 |
| Căn cứ | 要件定義書 phiên bản 1.0; tài liệu thiết kế hệ thống phiên bản 2 (17/09/2026) |

## Lịch sử sửa đổi

| Phiên bản | Ngày | Nội dung |
| --- | --- | --- |
| 1.0 | 24/09/2026 | Lập mới |

---

## 1. Tổng quan

### 1.1. Mục đích của tài liệu

Tài liệu này mô tả **hệ thống được xây dựng như thế nào** để đáp ứng các yêu cầu trong 要件定義書: gồm những thành phần nào, mỗi thành phần làm gì, dữ liệu đi qua chúng ra sao, và mỗi quyết định thiết kế được đưa ra vì lý do gì.

Các mã yêu cầu (CN-xx, PCN-xx, NV-xx) được dẫn lại trong nội dung. Bảng đối chiếu đầy đủ ở mục 13.

### 1.2. Nguyên tắc thiết kế

| STT | Nguyên tắc | Lý do |
| --- | --- | --- |
| 1 | Mỗi bước xử lý nặng chạy trong **một môi trường đóng gói độc lập**. Hệ thống điều phối chỉ quyết định bước nào chạy, theo thứ tự nào, vào lúc nào; nó không chứa logic học máy. | Từng bước có thể được thay bằng dịch vụ tương ứng trên đám mây mà không ảnh hưởng các bước khác. |
| 2 | Kho lưu trữ dữ liệu **tương thích với Amazon S3 ngay từ đầu**. | Phần đọc/ghi dữ liệu không phải viết lại khi chuyển lên đám mây (PCN-13). |
| 3 | Điều phối, quản lý mô hình, dự đoán và giám sát là **các thành phần tách biệt**, mỗi thành phần dùng công cụ chuyên trách. | Tránh một thành phần ôm quá nhiều việc; thay từng phần được khi chuyển đổi. |
| 4 | Mỗi bước **chạy lại được** mà không gây sai lệch. Kết quả được ghi vào vị trí xác định theo đầu vào; chạy lại thì ghi đè chính nó hoặc bỏ qua nếu đã có. | PCN-06. |
| 5 | **Chỉ có một bản logic làm sạch dữ liệu**, dùng chung cho cả bước chuẩn bị dữ liệu huấn luyện lẫn dịch vụ dự đoán. | NV-04. Hai bản chép tay của cùng một phép xử lý chắc chắn sẽ lệch nhau theo thời gian. |
| 6 | Quy trình huấn luyện chỉ chạy khi người vận hành yêu cầu; chỉ quy trình giám sát chạy tự động. | NV-01. |

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
│      khiển         │──┐               │   • Quy trình giám sát (mỗi giờ) │
└─────────┬──────────┘  │               └────────────────┬─────────────────┘
          │             │                                │ khởi chạy từng bước
          │             │                                ▼
          │             │               ┌──────────────────────────────────┐
          │             └──────────────▶│  Quản lý mô hình (MLflow)        │
          │                             └────────────────┬─────────────────┘
          │                                              │
          ▼                                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                  Kho lưu trữ đối tượng (MinIO)                           │
│  dữ liệu thô · dữ liệu đã chuẩn bị · tệp mô hình · hồ sơ thống kê cơ sở  │
│  nhật ký dự đoán · kết quả thực tế · báo cáo giám sát                    │
└──────────────────────────────────────────────────────────────────────────┘
          ▲ ghi nhật ký                                  ▲ đọc nhật ký
          │                                              │
┌─────────┴──────────┐   ┌────────────────────┐   ┌──────┴─────────────────┐
│  Tác nhân mô phỏng │──▶│  Dịch vụ dự đoán   │   │  Bước giám sát         │
│  thị trường        │   │                    │◀──│  (Evidently)           │
└────────────────────┘   └────────────────────┘   └────────────────────────┘
                                   ▲
                                   └── bước "đưa vào sử dụng" yêu cầu nạp lại mô hình
```

Cơ sở dữ liệu PostgreSQL (không vẽ trong sơ đồ) lưu thông tin quản lý của hệ thống điều phối và của MLflow.

### 2.2. Danh sách thành phần

| Thành phần | Vai trò | Sản phẩm sử dụng |
| --- | --- | --- |
| Bảng điều khiển | Giao diện web để người vận hành thao tác với toàn bộ hệ thống (mục 8) | Ứng dụng web, phục vụ bởi máy chủ web nginx |
| Lớp trung gian của bảng điều khiển | Nhận thao tác từ bảng điều khiển, chuyển tiếp tới đúng thành phần phía sau, trả kết quả về. Giữ thông tin xác thực của các thành phần phía sau. | Dịch vụ web tự phát triển |
| Hệ thống điều phối | Chạy các bước của quy trình theo đúng thứ tự, đúng lịch; ghi nhật ký từng bước | Apache Airflow, chế độ thực thi trên một máy |
| Các bước xử lý | Tiếp nhận, kiểm tra chất lượng, chuẩn bị dữ liệu, huấn luyện, đánh giá, đăng ký, giám sát. Mỗi bước là một container riêng. | Docker |
| Quản lý mô hình | Ghi lại mỗi lần huấn luyện (cấu hình, chỉ số, tệp mô hình); quản lý phiên bản mô hình và trạng thái đang sử dụng | MLflow Tracking, MLflow Model Registry |
| Kho lưu trữ đối tượng | Lưu mọi dữ liệu và tệp của hệ thống (mục 10.1) | MinIO, tương thích Amazon S3 |
| Cơ sở dữ liệu quản lý | Lưu thông tin quản lý của hệ thống điều phối và của MLflow, **ở hai cơ sở dữ liệu riêng biệt** trên cùng một máy chủ | PostgreSQL |
| Dịch vụ dự đoán | Trả kết quả dự đoán cho cả hai bài toán; ghi nhật ký; nhận kết quả thực tế (mục 5) | Dịch vụ web tự phát triển, chạy trong container |
| Tác nhân mô phỏng thị trường | Sinh lưu lượng dự đoán và kết quả thực tế theo kịch bản (mục 6) | Thành phần tự phát triển, chạy trong container |
| Công cụ phát hiện trôi | Tính toán mức độ trôi giữa dữ liệu gần đây và hồ sơ thống kê cơ sở (mục 7) | Evidently |
| Khởi động toàn hệ thống | Khởi động mọi thành phần trên một máy bằng một thao tác (PCN-21) | Docker Compose |

### 2.3. Phân tách trách nhiệm

**Hệ thống có hai dịch vụ web riêng biệt, không được gộp làm một:**

- **Lớp trung gian của bảng điều khiển** không biết gì về mô hình. Nó chỉ chuyển tiếp thao tác của người vận hành tới hệ thống điều phối, MLflow và kho lưu trữ.
- **Dịch vụ dự đoán** không biết gì về bảng điều khiển. Nó chỉ nhận thông tin căn nhà và trả kết quả dự đoán.

Hai dịch vụ này có tải, vòng đời và cách chuyển lên đám mây hoàn toàn khác nhau (mục 12), nên phải tách ngay từ đầu.

**Vì sao cần lớp trung gian**, thay vì cho bảng điều khiển gọi thẳng Airflow, MLflow và MinIO:

1. Thông tin xác thực của các thành phần đó sẽ phải nằm trong trình duyệt, tức là lộ ra ngoài (PCN-10).
2. Mỗi thành phần phía sau phải mở quyền truy cập từ trình duyệt riêng.
3. Mỗi lần thay một thành phần phía sau khi chuyển lên đám mây (Airflow sang Amazon MWAA, MLflow sang Amazon SageMaker) thì bảng điều khiển phải sửa theo. Có lớp trung gian thì chỉ lớp đó phải sửa (PCN-14).

### 2.4. Thành phần xử lý dữ liệu dùng chung

Toàn bộ hiểu biết về bộ dữ liệu — danh sách mục, kiểu dữ liệu, khoảng giá trị hợp lệ, cách làm sạch, cách chọn đầu vào theo bài toán, quy ước vị trí lưu trữ, cách tính hồ sơ thống kê — được đặt trong **một thành phần phần mềm dùng chung duy nhất**. Các bước xử lý chỉ là lớp vỏ mỏng gọi vào thành phần này.

Thành phần dùng chung tách các phép xử lý thành **hai nhóm với ranh giới cứng**:

| Nhóm | Ví dụ | Được dùng ở đâu | Lý do |
| --- | --- | --- | --- |
| **Xử lý theo từng mục thông tin** | Chuẩn hoá cách viết, đọc ngày tháng, đưa giá trị bất thường về khoảng hợp lệ | Được **đóng gói cùng mô hình**, nên chạy ở cả bước chuẩn bị dữ liệu (2 triệu dòng) lẫn dịch vụ dự đoán (một căn nhà) | Đảm bảo lúc huấn luyện và lúc dự đoán làm sạch giống hệt nhau (NV-04) |
| **Xử lý theo bản ghi** | Loại bản ghi trùng lặp, loại bản ghi không có đáp án | **Chỉ** ở bước chuẩn bị dữ liệu huấn luyện | Nếu một phép loại bản ghi lọt vào phần đóng gói cùng mô hình, nó vẫn chạy đúng suốt lúc huấn luyện, nhưng tới lúc dự đoán cho một căn nhà thì có thể không còn bản ghi nào để dự đoán — dịch vụ sẽ lỗi (PCN-08) |

Hai nhóm này được đặt ở hai phần riêng biệt của thành phần dùng chung, và phần xử lý theo bản ghi **không bao giờ** được gọi từ phần tạo mô hình hay từ dịch vụ dự đoán. Ranh giới vật lý này giúp không ai vô tình dùng nhầm.

---

## 3. Thiết kế quy trình xử lý

### 3.1. Quy trình huấn luyện và đưa vào sử dụng

**Kích hoạt:** chỉ khi người vận hành bấm chạy trên bảng điều khiển (NV-01). Không có lịch tự động.

**Tham số khởi chạy (CN-03, CN-04):**

| Tham số | Giá trị | Mặc định |
| --- | --- | --- |
| Bài toán | Dự đoán giá bán, hoặc Dự đoán bán nhanh | Bắt buộc chọn |
| Xử lý lại dữ liệu từ đầu | Có / Không | Không |
| Phiên bản dữ liệu | Tên phiên bản đã tải lên | Mới nhất |

**Trình tự:**

```
Tiếp nhận → Kiểm tra chất lượng → Chuẩn bị dữ liệu → Huấn luyện → Đánh giá → Rẽ nhánh ─┬─ Đăng ký → Đưa vào sử dụng
                                                                                      └─ Dừng (không đưa vào sử dụng)
```

| STT | Bước | Nội dung | Đầu vào | Đầu ra |
| --- | --- | --- | --- | --- |
| 1 | Tiếp nhận | Đọc dữ liệu thô của phiên bản đã chọn, chuyển sang định dạng Parquet | Dữ liệu thô | Dữ liệu thô dạng Parquet |
| 2 | Kiểm tra chất lượng | Đối chiếu với danh sách mục dữ liệu; đếm giá trị thiếu và giá trị bất thường theo từng mục; ghi kết quả vào nhật ký. Dừng quy trình nếu vi phạm nghiêm trọng. | Kết quả bước 1 | Kết quả kiểm tra trong nhật ký |
| 3 | Chuẩn bị dữ liệu | Xem mục 3.2 | Kết quả bước 1 | Tập huấn luyện, tập kiểm tra |
| 4 | Huấn luyện | Xem mục 3.3 | Tập huấn luyện | Mô hình ghi trong MLflow |
| 5 | Đánh giá | Hai cổng, xem mục 3.4 | Mô hình mới, tập kiểm tra, mô hình đang sử dụng | Đạt / Không đạt |
| 6 | Rẽ nhánh | Đạt thì sang bước 7; không đạt thì dừng, **giữ nguyên** mô hình đang sử dụng (CN-12) | Kết quả bước 5 | — |
| 7 | Đăng ký | Đánh dấu phiên bản mới là đang sử dụng trong MLflow Model Registry; tính hồ sơ thống kê cơ sở của tập huấn luyện đã dùng (mục 7.1) | Mô hình mới, tập huấn luyện | Phiên bản đang sử dụng, hồ sơ thống kê cơ sở |
| 8 | Đưa vào sử dụng | Gửi yêu cầu "nạp lại mô hình" tới dịch vụ dự đoán | — | Dịch vụ dùng phiên bản mới |

**Truyền dữ liệu giữa các bước:** dữ liệu lớn đi qua **kho lưu trữ đối tượng**, không đi qua hệ thống điều phối. Hệ thống điều phối chỉ chuyển các giá trị nhỏ giữa các bước: mã nhận dạng dữ liệu, chỉ số đánh giá, mã lần chạy.

**Bước 8 không có container riêng.** Bước này chỉ gửi một yêu cầu tới dịch vụ dự đoán, nên dùng chức năng có sẵn của Airflow. Đóng gói cả một container chỉ để gửi một yêu cầu là thừa. Ngược lại, bước 7 vẫn có container riêng vì nó phải tính hồ sơ thống kê trên toàn bộ tập huấn luyện.

### 3.2. Bước chuẩn bị dữ liệu

**Tái sử dụng kết quả (CN-07, PCN-02).** Đầu bước, hệ thống tính một **mã nhận dạng nội dung** của dữ liệu thô — tính từ chính nội dung dữ liệu, hoặc từ tên phiên bản dữ liệu kết hợp dấu hiệu thay đổi do kho lưu trữ cấp. Kết quả chuẩn bị được lưu ở vị trí đặt tên theo mã này. Nếu vị trí đó đã tồn tại và đủ tệp, bước này được bỏ qua và quy trình đi thẳng vào huấn luyện. Người vận hành chọn "Xử lý lại dữ liệu từ đầu" thì bỏ qua cơ chế này.

Vì vị trí lưu được xác định hoàn toàn bởi nội dung đầu vào, chạy lại bước này với cùng dữ liệu luôn ghi vào đúng chỗ cũ — đó là cách bước này đáp ứng PCN-06.

**Nội dung xử lý:**

1. Loại bản ghi trùng mã bất động sản, giữ bản ghi đầu tiên. Ghi lại số bản ghi đã loại vào nhật ký.
2. Loại bản ghi không có giá trị đáp án của bài toán đã chọn. Ghi lại số bản ghi đã loại.
3. Chia thành tập huấn luyện và tập kiểm tra theo **một cách chia cố định, lặp lại được** (PCN-18).
4. Lưu cả hai tập. Tập kiểm tra được lưu lại để mọi lần đánh giá sau dùng chung (NV-06).

Bước này **không** làm sạch từng mục thông tin: việc đó do phần xử lý đóng gói cùng mô hình đảm nhận (mục 4), để lúc huấn luyện và lúc dự đoán làm sạch bằng cùng một logic.

### 3.3. Bước huấn luyện

- Tạo mô hình hoàn chỉnh gồm **toàn bộ phần xử lý dữ liệu (mục 4) và bộ dự đoán**, rồi huấn luyện trên tập huấn luyện thô. Mô hình được lưu nguyên khối vào MLflow, nên mô hình trong kho **tự chứa toàn bộ logic làm sạch** (CN-08): dịch vụ dự đoán đưa dữ liệu thô vào là đủ.
- Với bài toán dự đoán giá bán: huấn luyện trên **thang logarit của giá** để giảm độ lệch của phân bố giá, nhưng các chỉ số đánh giá **luôn được quy đổi về đô la** trước khi báo cáo. Nếu không quy đổi, con số trên bảng điều khiển không đọc được, và việc so sánh mô hình mới với mô hình cũ cũng sai.
- Ghi vào MLflow: cấu hình huấn luyện, các chỉ số đánh giá, mô hình đã huấn luyện, mã nhận dạng dữ liệu đã dùng.
- Mỗi bài toán là một mô hình đăng ký riêng trong MLflow Model Registry.

### 3.4. Bước đánh giá

Mô hình mới phải qua **cả hai cổng** (CN-09, NV-03):

| Cổng | Điều kiện | Mục đích |
| --- | --- | --- |
| 1. Ngưỡng tối thiểu | Dự đoán giá bán: R² ≥ 0,75. Dự đoán bán nhanh: F1 ≥ 0,70. | Chặn mô hình kém chất lượng |
| 2. Tốt hơn mô hình đang sử dụng | Chỉ số của mô hình mới tốt hơn mô hình đang sử dụng, đo trên **cùng tập kiểm tra đã lưu** | Chặn việc thay một mô hình tốt bằng một mô hình kém hơn chỉ vì mô hình mới vượt ngưỡng |

Nếu chưa có mô hình nào đang sử dụng, chỉ áp dụng cổng 1. Các con số ngưỡng là điểm khởi đầu (vấn đề còn mở, mục 14).

### 3.5. Quy trình giám sát

**Kích hoạt:** tự động **mỗi giờ**. Đây là quy trình duy nhất chạy theo lịch.

| STT | Bước | Nội dung |
| --- | --- | --- |
| 1 | Thu thập | Đọc nhật ký dự đoán và kết quả thực tế trong khoảng thời gian gần nhất |
| 2 | Đánh giá trôi | So sánh với hồ sơ thống kê cơ sở của **phiên bản mô hình đang sử dụng**, dùng Evidently (mục 7.2) |
| 3 | Công bố | Ghi báo cáo và mức cảnh báo tổng hợp vào kho lưu trữ |

Quy trình giám sát **không** nằm trong quy trình huấn luyện. Nó đo lưu lượng dự đoán tích luỹ theo thời gian, không đo kết quả của lần huấn luyện vừa xong. Nếu chạy ngay sau bước đưa vào sử dụng, mô hình mới chưa phục vụ yêu cầu nào và báo cáo sẽ rỗng.

Quy trình giám sát **không tự khởi chạy huấn luyện lại** (NV-02); nó chỉ công bố mức cảnh báo để bảng điều khiển hiển thị.

---

## 4. Thiết kế xử lý dữ liệu đóng gói cùng mô hình

### 4.1. Thứ tự xử lý

Mọi dữ liệu đi vào mô hình — dù 2 triệu dòng lúc huấn luyện hay một căn nhà lúc dự đoán — đều đi qua đúng các bước sau, theo đúng thứ tự:

| STT | Bước | Nội dung |
| --- | --- | --- |
| 1 | Làm sạch từng mục | Áp quy tắc làm sạch tương ứng với loại của từng mục (mục 4.2). Mục không có trong danh sách mục dữ liệu được giữ nguyên; mục thiếu thì bỏ qua, không báo lỗi. |
| 2 | Đưa giá trị bất thường về khoảng hợp lệ | Giá trị nhỏ hơn giới hạn dưới được nâng lên bằng giới hạn dưới; lớn hơn giới hạn trên được hạ xuống bằng giới hạn trên (mục 4.3). Giá trị thiếu vẫn giữ là thiếu. |
| 3 | Tách ngày tháng | Ngày đăng bán được tách thành **năm** và **tháng**, rồi bỏ mục ngày gốc. |
| 4 | Chọn đầu vào | Giữ đúng các mục đầu vào của bài toán, theo thứ tự cố định. Mục bị loại theo 要件定義書 mục 6.3 bị bỏ đi **kể cả khi người gọi gửi lên**. Mục đầu vào mà người gọi không gửi được thêm vào với giá trị thiếu. |
| 5 | Bổ sung giá trị thiếu và chuyển đổi | Mục dạng số: điền giá trị trung vị của tập huấn luyện, rồi đưa về cùng thang đo. Mục dạng phân loại: điền giá trị xuất hiện nhiều nhất, rồi chuyển mỗi giá trị thành một cột có/không riêng (mục 4.5). |
| 6 | Dự đoán | Bộ dự đoán của bài toán tương ứng. |

**Thứ tự này là ràng buộc, không phải lựa chọn.** Bước 1 phải đứng đầu:

- Nếu bước 2 chạy trước bước 1, giá tiền dạng "$450,000" chưa được đọc thành số sẽ bị coi là không hợp lệ và trở thành giá trị thiếu.
- Nếu bước 3 chạy trước bước 1, ngày đăng bán còn đang ở ba định dạng lẫn lộn; một phần sẽ không đọc được và **âm thầm trở thành giá trị thiếu**, không có lỗi nào xuất hiện để cảnh báo.

**Không bước nào trong số trên được loại bỏ bản ghi** (PCN-08). Số bản ghi đầu ra luôn bằng số bản ghi đầu vào.

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

Giá trị bất thường được **đưa về trong khoảng** thay vì loại bỏ bản ghi, vì hai lý do: dịch vụ dự đoán không được phép loại bản ghi (PCN-08), và một căn nhà có số phòng ngủ ghi sai vẫn có thông tin hữu ích ở các mục khác.

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
| Phân loại | Thành phố, bang, mã bưu chính, loại bất động sản, tình trạng nhà | Giá trị xuất hiện nhiều nhất trong tập huấn luyện | Mỗi giá trị thành một cột có/không riêng |

**Giá trị hiếm:** giá trị phân loại chiếm dưới 1% tập huấn luyện được gộp chung vào một nhóm "hiếm".

**Giá trị chưa từng gặp:** khi dự đoán, một giá trị phân loại chưa có trong tập huấn luyện (ví dụ một loại nhà mới trong kịch bản thị trường "loại nhà mới") được xếp vào nhóm "hiếm" nếu có, hoặc được bỏ qua — **không gây lỗi** (PCN-07). Đây là điểm dễ làm dịch vụ dự đoán ngừng hoạt động nhất nếu thiết kế sai.

### 4.6. Mục bị loại khỏi đầu vào theo bài toán

Theo 要件定義書 mục 6.3. Việc loại được thực hiện ở bước 4 của mục 4.1, tức là **bên trong mô hình**: dù người gọi có gửi các mục bị loại, mô hình cũng bỏ chúng đi trước khi dự đoán.

### 4.7. Thao tác theo bản ghi

Chỉ được thực hiện ở bước chuẩn bị dữ liệu (mục 3.2), không bao giờ ở trong mô hình:

| Thao tác | Quy tắc | Kết quả trả về |
| --- | --- | --- |
| Loại trùng lặp | Bản ghi cùng mã bất động sản: giữ bản đầu tiên | Dữ liệu sau khi loại, số bản ghi đã loại |
| Loại bản ghi không có đáp án | Bản ghi thiếu giá trị đáp án của bài toán đã chọn | Dữ liệu sau khi loại, số bản ghi đã loại |

Sau mỗi thao tác, thứ tự đánh số bản ghi được làm lại từ đầu. Vì vậy, muốn truy ngược một bản ghi về dòng trong dữ liệu gốc thì phải dùng mã bất động sản, không dùng số thứ tự.

---

## 5. Thiết kế dịch vụ dự đoán

### 5.1. Chức năng

Một dịch vụ duy nhất phục vụ cả hai bài toán (CN-14).

| Chức năng | Đầu vào | Đầu ra | Yêu cầu |
| --- | --- | --- | --- |
| Dự đoán | Bài toán (giá bán / bán nhanh); thông tin **thô** của một căn nhà | Kết quả dự đoán, mã yêu cầu, phiên bản mô hình | CN-13 |
| Nhận kết quả thực tế | Mã yêu cầu, giá trị thực tế | Xác nhận đã ghi nhận | CN-16 |
| Nạp lại mô hình | — | Phiên bản đã nạp | CN-11 |
| Trạng thái | — | Mô hình nào đang được nạp, phiên bản bao nhiêu | CN-17 |

### 5.2. Nạp mô hình

- Bản đóng gói của dịch vụ **không chứa mô hình**. Khi khởi động, dịch vụ lấy phiên bản đang sử dụng mới nhất của **cả hai** mô hình từ MLflow Model Registry và giữ trong bộ nhớ.
- Khi nhận yêu cầu nạp lại (từ bước "đưa vào sử dụng"), dịch vụ lấy phiên bản đang sử dụng mới nhất và **thay thế mô hình trong bộ nhớ**, không khởi động lại (CN-11).
- Dịch vụ dự đoán chạy trong cùng môi trường phần mềm với lúc huấn luyện (PCN-17, mục 11.4).

### 5.3. Nhật ký dự đoán

| Mục | Nội dung |
| --- | --- |
| Mã yêu cầu | Mã duy nhất cho mỗi lần dự đoán; dùng để ghép với kết quả thực tế |
| Thời điểm | Thời điểm dự đoán |
| Dữ liệu đầu vào thô | Đúng như người gọi gửi lên, chưa làm sạch |
| Kết quả dự đoán | |
| Tên mô hình | |
| Phiên bản mô hình | |

**Ghi theo lô** (PCN-04): tích luỹ trong bộ nhớ, ghi xuống kho lưu trữ khi đủ **500 bản ghi** hoặc sau **30 giây**, tuỳ điều kiện nào đến trước. Nhật ký được chia theo mô hình và theo ngày.

### 5.4. Kết quả thực tế

Mỗi kết quả thực tế gồm mã yêu cầu và giá trị thực tế (giá bán thật, hoặc có bán trong 30 ngày hay không). Được lưu vào kho, chia theo mô hình và theo ngày. Bước giám sát ghép kết quả thực tế với nhật ký dự đoán qua **mã yêu cầu**.

---

## 6. Thiết kế tác nhân mô phỏng thị trường

Tác nhân mô phỏng sinh lưu lượng thật cho dịch vụ dự đoán, thay cho cách giả lập trôi bằng cách cắt bộ dữ liệu gốc.

| Hoạt động | Mô tả | Yêu cầu |
| --- | --- | --- |
| Sinh tin rao | Sinh căn nhà mới theo phân phối mô phỏng thị trường, gửi yêu cầu dự đoán | CN-23 |
| Báo kết quả thực tế | Sau một khoảng thời gian mô phỏng, gửi giá bán thật hoặc việc có bán trong 30 ngày hay không | CN-24 |
| Mồi dữ liệu ban đầu | Khi hệ thống mới khởi động, lấy phần dữ liệu có ngày đăng bán mới nhất trong bộ dữ liệu gốc, gửi dự đoán một lượt. Vừa tạo dữ liệu để bảng điều khiển hiển thị, vừa là bài kiểm tra nhanh cho dịch vụ dự đoán. | CN-26 |

**Kịch bản thị trường (CN-25):**

| Kịch bản | Mô phỏng | Kết quả giám sát mong đợi |
| --- | --- | --- |
| Không thay đổi | Cùng phân phối với tập huấn luyện | Bình thường — kiểm chứng hệ thống không báo động nhầm |
| Giá tăng | Mặt bằng giá tăng khoảng 20% | Nghiêm trọng |
| Dịch chuyển thị trường | Thay đổi tỉ lệ giữa các thành phố, dồn giao dịch về thành phố khác | Phát hiện được trôi; mức cảnh báo cụ thể chưa quy định |
| Loại nhà mới | Xuất hiện loại bất động sản mà mô hình chưa từng thấy | Phát hiện được trôi, mức cảnh báo cụ thể chưa quy định; dịch vụ dự đoán không lỗi (mục 4.5) |

---

## 7. Thiết kế giám sát

### 7.1. Hồ sơ thống kê cơ sở

**Hồ sơ thống kê cơ sở gắn với một phiên bản mô hình, không gắn với một bộ dữ liệu.** Nó được tính ở bước đăng ký (mục 3.1, bước 7), trên đúng tập huấn luyện đã dùng cho phiên bản đó, và lưu ở vị trí đặt theo tên mô hình và số phiên bản.

Hệ quả của thiết kế này:

- Hồ sơ **tự sinh cùng lúc** mô hình được đăng ký; không ai phải thao tác thủ công.
- Không bao giờ xảy ra chuyện so sánh phiên bản mới với hồ sơ của một phiên bản cũ.

**Nội dung hồ sơ:**

| Phần | Nội dung |
| --- | --- |
| Chung | Tổng số bản ghi; thời điểm tính (theo giờ quốc tế) |
| Với mỗi mục dạng số | Tỉ lệ thiếu; trung bình; độ lệch chuẩn; nhỏ nhất; lớn nhất; các điểm phân vị 25%, 50%, 75%; biểu đồ phân bố 20 khoảng (ranh giới các khoảng và số bản ghi trong mỗi khoảng) |
| Với mỗi mục dạng phân loại | Tỉ lệ thiếu; số giá trị khác nhau; tỉ lệ của từng giá trị (tổng bằng 1) |

Nếu một mục thiếu hoàn toàn trong dữ liệu, các giá trị thống kê của nó được ghi là "không có", không gây lỗi. Hồ sơ được lưu ở dạng văn bản có cấu trúc, đọc được bằng các công cụ thông dụng.

### 7.2. Ba loại trôi

| Loại | So sánh | Khi nào đo được |
| --- | --- | --- |
| Trôi dữ liệu đầu vào | Phân bố đầu vào trong nhật ký dự đoán với hồ sơ thống kê cơ sở | Ngay lập tức |
| Trôi kết quả dự đoán | Phân bố kết quả dự đoán với phân bố kết quả lúc huấn luyện | Ngay lập tức |
| Suy giảm độ chính xác | Kết quả dự đoán với kết quả thực tế (ghép qua mã yêu cầu) | Chỉ khi đã có kết quả thực tế |

Việc tính toán trôi dữ liệu đầu vào và trôi kết quả dự đoán dùng các bộ đánh giá có sẵn của Evidently. Suy giảm độ chính xác dùng cùng loại chỉ số với bước đánh giá (mục 3.4), tính trên khoảng thời gian đang xét.

Hai loại đầu đo được ngay vì không cần kết quả thực tế. Loại thứ ba mới là thứ quan trọng nhất, nhưng **luôn đến trễ**: lúc tác nhân hỏi giá một căn nhà, chưa ai biết nó sẽ bán được bao nhiêu.

### 7.3. Mức cảnh báo và báo cáo

- Kết quả ba loại trôi được tổng hợp thành một mức: **Bình thường / Cảnh báo / Nghiêm trọng** (CN-20). Tiêu chí định lượng cho từng mức là vấn đề còn mở (mục 14).
- Mỗi lần giám sát tạo ra một báo cáo ở hai dạng: **trang xem được bằng trình duyệt** (để người đọc) và **dạng dữ liệu có cấu trúc** (để bảng điều khiển đọc). Báo cáo được lưu theo tên mô hình và mã lần chạy (CN-21).

---

## 8. Thiết kế màn hình

### 8.1. Danh sách màn hình

| STT | Màn hình | Mục đích | Yêu cầu |
| --- | --- | --- | --- |
| 1 | Tổng quan | Khởi chạy quy trình, xem trạng thái | CN-27 |
| 2 | Các bước và nhật ký | Xem và lọc nhật ký | CN-28 |
| 3 | Dữ liệu | Tải dữ liệu lên, xem mẫu và thống kê | CN-29 |
| 4 | Mô hình | Xem phiên bản mô hình, chuyển phiên bản sang đang sử dụng | CN-30 |
| 5 | Giám sát trôi | Xem báo cáo giám sát, huấn luyện lại | CN-31 |

### 8.2. Nội dung từng màn hình

**Màn hình 1 — Tổng quan**

| Thành phần | Nội dung |
| --- | --- |
| Chọn bài toán | Danh sách chọn: Dự đoán giá bán / Dự đoán bán nhanh. Bắt buộc. |
| Xử lý lại dữ liệu từ đầu | Ô đánh dấu, mặc định không đánh dấu |
| Nút chạy | Khởi chạy quy trình huấn luyện với các lựa chọn trên |
| Trạng thái | Trạng thái của từng bước trong lần chạy gần nhất |
| Nhật ký gần đây | Các dòng nhật ký mới nhất của từng bước |

**Màn hình 2 — Các bước và nhật ký**

Hiển thị nhật ký thật do hệ thống điều phối ghi lại. Lọc được theo: bước, mức độ nghiêm trọng, từ khoá.

**Màn hình 3 — Dữ liệu**

| Thành phần | Nội dung |
| --- | --- |
| Tải lên | Chọn tệp CSV; sau khi tải lên, hệ thống trả về tên phiên bản dữ liệu mới |
| Xem mẫu | Một số dòng đầu của phiên bản dữ liệu |
| Thống kê theo cột | Do hệ thống phía sau tính, không tính trong trình duyệt |

**Màn hình 4 — Mô hình**

| Thành phần | Nội dung |
| --- | --- |
| Danh sách phiên bản | Tên mô hình, số phiên bản, chỉ số đánh giá, trạng thái sử dụng |
| Cột chỉ số | **Thay đổi theo bài toán**: RMSE / MAE / R² cho dự đoán giá bán; F1 / AUC / độ chính xác cho dự đoán bán nhanh |
| Chuyển sang đang sử dụng | Chọn một phiên bản và chuyển sang trạng thái đang sử dụng |

**Màn hình 5 — Giám sát trôi**

| Thành phần | Nội dung |
| --- | --- |
| Mức cảnh báo | Nhãn màu: Bình thường / Cảnh báo / Nghiêm trọng |
| Ba loại trôi | Kết quả của từng loại (mục 7.2) |
| Biểu đồ phân bố | So sánh phân bố hiện tại với hồ sơ thống kê cơ sở |
| Diễn biến | Mức cảnh báo theo thời gian |
| Nút "Huấn luyện lại ngay" | Chỉ hiện khi mức là **Nghiêm trọng**. Đã điền sẵn bài toán của mô hình bị ảnh hưởng. Người vận hành bấm thì mới chạy. |

Bảng điều khiển chỉ **đọc** báo cáo đã có; nó không tự tính toán trôi.

### 8.3. Lưu trữ phía trình duyệt

Trình duyệt chỉ ghi nhớ các thiết lập cá nhân tiện dụng (giao diện sáng/tối, thẻ đang mở). Mọi dữ liệu nghiệp vụ đều lấy từ hệ thống phía sau.

---

## 9. Thiết kế liên kết giữa các thành phần

### 9.1. Bảng điều khiển với lớp trung gian

| Thao tác trên bảng điều khiển | Lớp trung gian chuyển tới | Yêu cầu |
| --- | --- | --- |
| Khởi chạy quy trình huấn luyện (bài toán, xử lý lại) → nhận mã lần chạy | Airflow | CN-04 |
| Xem danh sách các lần chạy gần đây và trạng thái | Airflow | CN-27 |
| Xem trạng thái từng bước của một lần chạy | Airflow | CN-27 |
| Xem nhật ký của một lần chạy (lọc theo bước, mức độ, từ khoá) | Airflow | CN-28 |
| Tải dữ liệu lên → nhận tên phiên bản dữ liệu | MinIO | CN-01 |
| Xem mẫu và thống kê cột của một phiên bản dữ liệu | MinIO | CN-02 |
| Xem danh sách mô hình, phiên bản, chỉ số, trạng thái | MLflow | CN-30 |
| Chuyển một phiên bản sang đang sử dụng | MLflow | CN-30 |
| Xem báo cáo giám sát mới nhất | MinIO | CN-31 |
| Xem diễn biến mức cảnh báo theo thời gian | MinIO | CN-21 |
| Xem trạng thái các thành phần phụ thuộc | Tất cả | CN-32 |

### 9.2. Liên kết giữa các thành phần phía sau

| Từ | Tới | Nội dung |
| --- | --- | --- |
| Airflow | Các bước xử lý | Khởi chạy từng bước trong container riêng; truyền bài toán đã chọn và các giá trị nhỏ |
| Các bước xử lý | MinIO | Đọc/ghi dữ liệu, hồ sơ thống kê, báo cáo |
| Các bước xử lý | MLflow | Ghi kết quả huấn luyện; đọc mô hình đang sử dụng để so sánh; đăng ký phiên bản mới |
| Bước "đưa vào sử dụng" | Dịch vụ dự đoán | Yêu cầu nạp lại mô hình |
| Dịch vụ dự đoán | MLflow | Lấy phiên bản mô hình đang sử dụng |
| Dịch vụ dự đoán | MinIO | Ghi nhật ký dự đoán, kết quả thực tế |
| Tác nhân mô phỏng | Dịch vụ dự đoán | Gửi yêu cầu dự đoán, gửi kết quả thực tế |
| MLflow | PostgreSQL, MinIO | Lưu thông tin quản lý vào PostgreSQL; lưu tệp mô hình vào MinIO |
| Airflow | PostgreSQL | Lưu thông tin quản lý |

---

## 10. Thiết kế dữ liệu

### 10.1. Bố cục kho lưu trữ đối tượng

Toàn bộ dữ liệu nằm trong một vùng lưu trữ, chia thành các khu vực sau:

| Khu vực | Nội dung | Cách phân chia | Tạo bởi | Dùng bởi |
| --- | --- | --- | --- | --- |
| Dữ liệu thô | Dữ liệu tải lên | Theo phiên bản dữ liệu | Chức năng tải lên | Bước tiếp nhận |
| Dữ liệu đã chuẩn bị | Tập huấn luyện, tập kiểm tra | Theo mã nhận dạng nội dung của dữ liệu thô | Bước chuẩn bị dữ liệu | Bước huấn luyện, đánh giá, đăng ký |
| Tệp mô hình | Mô hình đã huấn luyện và tệp liên quan | Do MLflow quản lý | MLflow | Dịch vụ dự đoán |
| Hồ sơ thống kê cơ sở | Hồ sơ của từng phiên bản mô hình | Theo tên mô hình, rồi số phiên bản | Bước đăng ký | Bước giám sát |
| Nhật ký dự đoán | Nhật ký mỗi lần dự đoán | Theo tên mô hình, rồi theo ngày | Dịch vụ dự đoán | Bước giám sát |
| Kết quả thực tế | Kết quả bán thực tế | Theo tên mô hình, rồi theo ngày | Dịch vụ dự đoán | Bước giám sát |
| Báo cáo giám sát | Báo cáo mỗi lần giám sát | Theo tên mô hình, rồi mã lần chạy | Bước giám sát | Bảng điều khiển |

**Toàn bộ quy ước đặt tên vị trí lưu trữ nằm ở một chỗ duy nhất** trong thành phần dùng chung (mục 2.4). Không chỗ nào khác trong hệ thống tự ghép tên vị trí. Khi chuyển sang Amazon S3, chỉ chỗ này phải sửa (PCN-12).

### 10.2. Định dạng lưu trữ

| Dữ liệu | Định dạng | Lý do |
| --- | --- | --- |
| Dữ liệu thô tải lên | CSV | Định dạng đầu vào |
| Mọi dữ liệu dạng bảng sau bước tiếp nhận | Parquet, nén | Dung lượng giảm từ khoảng 373 MB còn khoảng 60–80 MB; đọc nhanh hơn nhiều lần; giữ nguyên kiểu dữ liệu nên các bước sau không phải đọc lại từ đầu (PCN-03) |
| Hồ sơ thống kê cơ sở | Văn bản có cấu trúc | Đọc được bằng các công cụ thông dụng |
| Báo cáo giám sát | Trang web và văn bản có cấu trúc | Mục 7.3 |

### 10.3. Cơ sở dữ liệu quản lý

| Cơ sở dữ liệu | Dùng bởi | Nội dung |
| --- | --- | --- |
| Của hệ thống điều phối | Airflow | Lịch sử chạy, trạng thái từng bước |
| Của quản lý mô hình | MLflow | Lịch sử huấn luyện, phiên bản mô hình, trạng thái sử dụng |

Hai cơ sở dữ liệu riêng biệt trên cùng một máy chủ PostgreSQL. Tách riêng để hai công cụ không ảnh hưởng dữ liệu của nhau, và để có thể chuyển từng cái sang dịch vụ đám mây độc lập.

---

## 11. Thiết kế phi chức năng

### 11.1. Tài nguyên và hiệu năng

| Biện pháp | Đáp ứng |
| --- | --- |
| Dùng lại kết quả chuẩn bị dữ liệu khi dữ liệu thô không đổi (mục 3.2) | PCN-02 |
| Lưu dữ liệu dạng Parquet sau bước tiếp nhận (mục 10.2) | PCN-01, PCN-03 |
| Ghi nhật ký dự đoán theo lô (mục 5.3) | PCN-04 |
| Hệ thống điều phối chạy ở chế độ một máy, không cần hàng đợi hay máy chủ phân tán | PCN-01 |
| Khi phát triển, giới hạn số dòng dữ liệu đọc vào ở 200.000 qua thiết lập cấu hình; bỏ thiết lập này khi chạy thật | PCN-05 |

### 11.2. Chạy lại và độ tin cậy

- Vị trí đầu ra của mỗi bước được xác định hoàn toàn bởi đầu vào, nên chạy lại luôn ghi vào đúng chỗ cũ hoặc bỏ qua nếu đã có (PCN-06).
- Phần xử lý dữ liệu trong mô hình chịu được: thiếu mục, giá trị trống, giá trị phân loại mới (mục 4.1, 4.5), và không bao giờ loại bản ghi (PCN-07, PCN-08).

### 11.3. Bảo mật

| Biện pháp | Đáp ứng |
| --- | --- |
| Thông tin xác thực nằm trong tệp cấu hình riêng không đưa lên kho lưu trữ dùng chung; kho chỉ chứa tệp mẫu không có giá trị thật | PCN-09 |
| Trong Airflow, thông tin kết nối tới MinIO và MLflow được khai báo bằng chức năng quản lý kết nối của Airflow, không ghi vào định nghĩa quy trình | PCN-09 |
| Bảng điều khiển chỉ nói chuyện với lớp trung gian (mục 2.3) | PCN-10 |
| Lớp trung gian kiểm tra khoá truy cập; bật bắt buộc trước khi mở hệ thống ra ngoài | PCN-11 |

### 11.4. Môi trường thực thi đồng nhất

- Có **một môi trường nền dùng chung**, chứa sẵn các thư viện xử lý dữ liệu và học máy cùng thành phần dùng chung (mục 2.4). Mọi bước xử lý đều xây dựng trên môi trường nền này.
- Không có môi trường nền này, mỗi bước sẽ tự cài lại thư viện: xây dựng rất lâu, và phiên bản thư viện dễ lệch giữa các bước. Lệch phiên bản giữa lúc huấn luyện và lúc dự đoán là loại lỗi khó tìm nhất.
- Mô hình đã lưu chỉ đọc lại được đúng trong môi trường có cùng phiên bản nền tảng và thư viện với lúc lưu. Vì vậy huấn luyện và dự đoán **đều diễn ra trong container**, không huấn luyện trên máy phát triển (PCN-17, RB-03).
- Mỗi khi thành phần dùng chung thay đổi, môi trường nền phải được xây dựng lại, nếu không các bước sẽ dùng bản cũ.

### 11.5. Kiểm thử

| Nội dung | Đáp ứng |
| --- | --- |
| Mỗi loại lỗi dữ liệu trong 要件定義書 mục 6.4 có kiểm thử tự động riêng | PCN-15 |
| Kiểm thử khẳng định phần xử lý dữ liệu không loại bản ghi, và dự đoán được cho đúng một căn nhà | PCN-08 |
| Kiểm thử khẳng định mô hình nhận được dữ liệu thô chưa làm sạch | CN-13 |
| Kiểm thử khẳng định các mục bị loại không ảnh hưởng kết quả dự đoán | NV-05 |
| Kiểm thử khẳng định giá trị phân loại mới và giá trị thiếu không gây lỗi | PCN-07 |
| Kiểm thử khẳng định cùng một bản ghi thô cho cùng kết quả khi đi qua bước chuẩn bị dữ liệu và khi đi qua mô hình | PCN-16 |
| Phần đọc/ghi kho lưu trữ được kiểm thử trên một kho giả lập trong bộ nhớ, rồi được kiểm tra thủ công trên MinIO thật | PCN-13 |

---

## 12. Thiết kế chuyển đổi lên AWS (giai đoạn 2)

### 12.1. Đối ứng thành phần

| Vai trò | Giai đoạn 1 | Giai đoạn 2 (AWS) |
| --- | --- | --- |
| Bảng điều khiển | Ứng dụng web + nginx | Giữ nguyên |
| Lớp trung gian | Dịch vụ web trong container | Giữ nguyên, triển khai trên Amazon ECS / AWS Fargate hoặc AWS Lambda |
| Hệ thống điều phối | Apache Airflow | Amazon MWAA |
| Kho lưu trữ đối tượng | MinIO | Amazon S3 |
| Bước huấn luyện | Container Docker | Amazon SageMaker Training Job |
| Các bước xử lý dữ liệu | Container Docker | Amazon SageMaker Processing Job |
| Quản lý thí nghiệm | MLflow | MLflow trên Amazon EC2 / ECS, hoặc Amazon SageMaker Experiments |
| Quản lý phiên bản mô hình | MLflow Model Registry | Amazon SageMaker Model Registry |
| Dịch vụ dự đoán và chức năng nạp lại mô hình | Dịch vụ web trong container | Amazon SageMaker Endpoint (cập nhật cấu hình Endpoint thay cho chức năng nạp lại) |
| Nhật ký dự đoán | Dịch vụ dự đoán tự ghi vào MinIO | Amazon SageMaker Data Capture |
| Hồ sơ thống kê cơ sở | Tự tính ở bước đăng ký | Tác vụ tạo mốc của Amazon SageMaker Model Monitor |
| Giám sát trôi | Evidently, chạy mỗi giờ | Lịch giám sát của Amazon SageMaker Model Monitor |
| Cơ sở dữ liệu quản lý | PostgreSQL | Amazon Aurora |
| Khởi động toàn hệ thống | Docker Compose | Amazon ECS / EKS, hoặc container do SageMaker quản lý |
| Khởi chạy quy trình | Thủ công từ bảng điều khiển | AWS CodePipeline + Amazon EventBridge |

### 12.2. Nguyên tắc chuyển đổi

1. **Kho lưu trữ:** chỉ thay địa chỉ kết nối từ MinIO sang Amazon S3. Toàn bộ quy ước vị trí lưu trữ nằm ở một chỗ (mục 10.1), nên chỉ chỗ đó phải sửa.
2. **Bảng điều khiển:** không thay đổi. Lớp trung gian thay đổi để trỏ tới các dịch vụ AWS (mục 2.3).
3. **Chuyển dần từng thành phần**, không chuyển đồng loạt. Mỗi bước xử lý đã là một container độc lập (nguyên tắc 1, mục 1.2), nên từng bước có thể chuyển riêng.

---

## 13. Đối chiếu yêu cầu

| Yêu cầu | Mục thiết kế |
| --- | --- |
| NV-01 Chỉ chạy khi được yêu cầu | 3.1, 3.5 |
| NV-02 Không tự huấn luyện lại | 3.5, 8.2 (màn hình 5) |
| NV-03 Hai cổng đánh giá | 3.4 |
| NV-04 Làm sạch giống nhau khi huấn luyện và dự đoán | 2.4, 3.3, 4.1 |
| NV-05 Loại thông tin khỏi đầu vào | 4.6 |
| NV-06 Tập kiểm tra chung | 3.2, 3.4 |
| CN-01 – CN-03 Quản lý dữ liệu | 8.2 (màn hình 3), 9.1, 10.1 |
| CN-04 Khởi chạy quy trình | 3.1, 8.2 (màn hình 1) |
| CN-05 Tiếp nhận | 3.1 (bước 1), 10.2 |
| CN-06 Kiểm tra chất lượng | 3.1 (bước 2) |
| CN-07 Chuẩn bị dữ liệu | 3.2, 4.7 |
| CN-08 Huấn luyện | 3.3 |
| CN-09 Đánh giá | 3.4 |
| CN-10 Đăng ký | 3.1 (bước 7), 7.1 |
| CN-11 Đưa vào sử dụng | 3.1 (bước 8), 5.2 |
| CN-12 Dừng khi không đạt | 3.1 (bước 6) |
| CN-13 – CN-17 Dự đoán | 4, 5 |
| CN-18 – CN-22 Giám sát | 3.5, 7, 8.2 (màn hình 5) |
| CN-23 – CN-26 Mô phỏng thị trường | 6 |
| CN-27 – CN-32 Bảng điều khiển | 8, 9.1 |
| PCN-01 – PCN-05 Hiệu năng và tài nguyên | 11.1 |
| PCN-06 – PCN-08 Độ tin cậy | 4.1, 4.5, 11.2 |
| PCN-09 – PCN-11 Bảo mật | 2.3, 11.3 |
| PCN-12 – PCN-14 Chuyển đổi lên đám mây | 10.1, 12 |
| PCN-15 – PCN-18 Chất lượng | 3.2, 11.4, 11.5 |
| PCN-19 – PCN-21 Vận hành | 2.2, 8 |

---

## 14. Vấn đề còn mở và hạn chế đã biết

### 14.1. Vấn đề còn mở

Kế thừa từ 要件定義書 mục 9:

| STT | Vấn đề | Thời điểm quyết định |
| --- | --- | --- |
| 1 | Ngưỡng tối thiểu R² 0,75 và F1 0,70 cần điều chỉnh theo kết quả thực tế | Sau lần huấn luyện đầu tiên |
| 2 | Độ dài khoảng thời gian dữ liệu mà mỗi lần giám sát xem xét | Sau khi xây dựng tác nhân mô phỏng |
| 3 | Khi chuyển lên AWS, giữ MLflow song song với Amazon SageMaker Model Registry hay chuyển hẳn | Giai đoạn 2 |
| 4 | Tiêu chí định lượng của "vi phạm nghiêm trọng" ở bước kiểm tra chất lượng | Khi xây dựng bước kiểm tra chất lượng |
| 5 | Tiêu chí định lượng cho từng mức cảnh báo | Khi xây dựng chức năng giám sát |
| 6 | Thời gian phản hồi mục tiêu, thời gian lưu giữ dữ liệu, cách sao lưu | Trước giai đoạn 2 |

### 14.2. Hạn chế đã biết

| Hạn chế | Ảnh hưởng | Hướng xử lý |
| --- | --- | --- |
| Mã bưu chính được xử lý như một mục phân loại, trong khi nó có hàng chục nghìn giá trị khác nhau. Với quy tắc gộp giá trị dưới 1% (mục 4.5), trên 2 triệu dòng gần như mọi mã bưu chính sẽ rơi vào nhóm "hiếm". | Mục này gần như không đóng góp vào dự đoán. Vô hại nhưng lãng phí. | Quyết định sau khi có kết quả huấn luyện đầu tiên, ví dụ gộp theo ba chữ số đầu, hoặc thay bằng giá trị thống kê của khu vực. |
| Định dạng ngày có tên tháng tiếng Anh viết tắt ("15-Jul-2023") phụ thuộc vào thiết lập ngôn ngữ của môi trường thực thi. | Nếu môi trường nền được thiết lập ngôn ngữ khác tiếng Anh, toàn bộ ngày ở định dạng này sẽ âm thầm trở thành giá trị thiếu. | Kiểm tra thiết lập ngôn ngữ khi xây dựng môi trường nền. |
