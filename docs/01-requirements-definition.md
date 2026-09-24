# 要件定義書 — Hệ thống vận hành học máy dự đoán giá bất động sản

| Mục | Nội dung |
| --- | --- |
| Tên tài liệu | 要件定義書 (Tài liệu định nghĩa yêu cầu) |
| Hệ thống | Hệ thống vận hành học máy dự đoán giá bất động sản |
| Phiên bản | 1.0 |
| Ngày lập | 24/09/2026 |
| Căn cứ | Tài liệu thiết kế hệ thống phiên bản 2 (17/09/2026) và tài liệu mô tả bộ dữ liệu |
| Tài liệu liên quan | 基本設計書 (Tài liệu thiết kế cơ bản) |

## Lịch sử sửa đổi

| Phiên bản | Ngày | Nội dung |
| --- | --- | --- |
| 1.0 | 24/09/2026 | Lập mới |

---

## 1. Tổng quan

### 1.1. Mục đích của tài liệu

Tài liệu này xác định **hệ thống phải làm gì** và **phải đạt những điều kiện gì**, ở mức mà một người không tham gia phát triển vẫn đọc hiểu và đánh giá được. Tài liệu không mô tả cách thực hiện; phần đó thuộc về 基本設計書.

Mỗi yêu cầu có một mã số riêng (ví dụ CN-04, PCN-07) để 基本設計書 đối chiếu lại.

### 1.2. Bối cảnh

Một mô hình học máy dự đoán giá nhà chỉ đúng trong điều kiện thị trường giống với dữ liệu mà nó đã học. Khi thị trường thay đổi — giá tăng chung, người mua dồn về thành phố khác, xuất hiện loại nhà mới — mô hình dự đoán sai dần mà không báo lỗi gì. Nếu mọi việc làm thủ công (làm sạch dữ liệu, huấn luyện, đánh giá, đưa vào sử dụng), thì rất khó lặp lại đúng như cũ, và càng khó biết lúc nào mô hình không còn đáng tin.

Hệ thống này tự động hoá toàn bộ vòng đời của mô hình: tiếp nhận dữ liệu, làm sạch, huấn luyện, đánh giá, đưa vào sử dụng, và theo dõi chất lượng sau khi sử dụng.

Dự án được xây dựng với mục đích **học tập và thực hành**. Dữ liệu là dữ liệu giả lập, không phải dữ liệu giao dịch thật.

### 1.3. Mục tiêu

1. Tự động hoá vòng đời mô hình từ dữ liệu thô đến khi mô hình được sử dụng và được theo dõi.
2. **Giai đoạn 1:** toàn bộ hệ thống chạy trên một máy tính, không cần kết nối tới dịch vụ đám mây nào.
3. **Giai đoạn 2:** chuyển dần hệ thống lên nền tảng đám mây AWS, với mức thay đổi phần mềm ít nhất có thể.
4. Phát hiện được khi mô hình không còn phù hợp với thực tế, và cảnh báo để con người quyết định.

### 1.4. Phạm vi

| Trong phạm vi giai đoạn 1 | Ngoài phạm vi giai đoạn 1 |
| --- | --- |
| Hai bài toán dự đoán (mục 3.1) | Kho đặc trưng dùng chung (mục 8) |
| Quy trình huấn luyện và đưa vào sử dụng, chạy theo yêu cầu của người vận hành | Tự động huấn luyện lại khi phát hiện bất thường |
| Dịch vụ dự đoán phục vụ cả hai bài toán | Mở hệ thống ra internet cho nhiều người dùng |
| Giám sát chất lượng mô hình tự động mỗi giờ | Chuyển hệ thống lên nền tảng đám mây (thuộc giai đoạn 2) |
| Tác nhân mô phỏng thị trường sinh lưu lượng dự đoán | |
| Bảng điều khiển để vận hành toàn bộ hệ thống | |

---

## 2. Các bên liên quan

| Bên liên quan | Vai trò |
| --- | --- |
| Người vận hành | Thao tác với hệ thống qua bảng điều khiển: tải dữ liệu lên, khởi chạy huấn luyện, xem kết quả, quyết định đưa mô hình vào sử dụng hay huấn luyện lại. Giai đoạn 1 giả định chỉ có **một** người vận hành, làm việc trên máy cục bộ. |
| Tác nhân mô phỏng thị trường | Thành phần tự động đóng vai người dùng cuối: gửi yêu cầu dự đoán cho các căn nhà mới rao bán, rồi sau đó báo lại kết quả bán thực tế. Nó thay thế cho người dùng thật, vốn không có trong một dự án học tập. |
| Chức năng giám sát định kỳ | Tự chạy mỗi giờ, không cần người khởi động. Là phần duy nhất của hệ thống chạy tự động. |

---

## 3. Yêu cầu nghiệp vụ

### 3.1. Hai bài toán dự đoán

Hệ thống phục vụ hai mô hình trên cùng một nguồn dữ liệu.

| Bài toán | Loại | Giá trị cần dự đoán | Chỉ số đánh giá |
| --- | --- | --- | --- |
| Dự đoán giá bán | Hồi quy (dự đoán một con số) | Giá bán cuối cùng của căn nhà, tính bằng đô la Mỹ | Sai số bình phương trung bình căn (RMSE), sai số tuyệt đối trung bình (MAE), hệ số xác định (R²) |
| Dự đoán bán nhanh | Phân loại hai lớp (có / không) | Căn nhà có bán được trong vòng 30 ngày kể từ khi rao hay không | Điểm F1, diện tích dưới đường cong (AUC), độ chính xác |

Hai bài toán đo hai điều khác nhau — **giá bán** và **tốc độ bán** — nên bổ sung cho nhau. Phân loại mức giá (thấp / trung bình / cao / cao cấp) không được chọn làm bài toán thứ hai, vì nó được suy ra trực tiếp từ giá bán, tức là lặp lại bài toán thứ nhất.

### 3.2. Luồng nghiệp vụ tổng thể

```
  [Người vận hành]
        │ chọn bài toán, bấm chạy
        ▼
  Tiếp nhận dữ liệu → Kiểm tra chất lượng → Chuẩn bị dữ liệu → Huấn luyện → Đánh giá
                                                                            │
                                         ┌──────────────── đạt ────────────┤
                                         ▼                                  │ không đạt
                         Đăng ký phiên bản mới → Đưa vào sử dụng           ▼
                                                                          Dừng, giữ nguyên
                                                                          mô hình đang dùng

  [Tác nhân mô phỏng] ── gửi yêu cầu dự đoán ──▶ Dịch vụ dự đoán ── ghi nhật ký
        │
        └── sau một thời gian, báo kết quả bán thực tế ──▶ Dịch vụ dự đoán ── ghi kết quả thực tế

  [Mỗi giờ] Giám sát: so nhật ký dự đoán và kết quả thực tế với lúc huấn luyện
        │
        └── báo cáo + mức cảnh báo ──▶ Bảng điều khiển ──▶ [Người vận hành] quyết định huấn luyện lại
```

### 3.3. Nguyên tắc nghiệp vụ

| Mã | Nguyên tắc |
| --- | --- |
| NV-01 | Quy trình huấn luyện **chỉ chạy khi người vận hành yêu cầu**. Chức năng giám sát là phần duy nhất chạy tự động theo lịch. |
| NV-02 | Hệ thống **không tự huấn luyện lại**. Khi phát hiện bất thường nghiêm trọng, hệ thống chỉ cảnh báo; con người quyết định. |
| NV-03 | Một mô hình mới chỉ được đưa vào sử dụng khi **vừa đạt ngưỡng chất lượng tối thiểu, vừa tốt hơn mô hình đang được sử dụng** (chi tiết ở CN-09). |
| NV-04 | Cách làm sạch dữ liệu **phải giống hệt nhau** giữa lúc huấn luyện và lúc dự đoán. Nếu hai lúc làm sạch khác nhau dù chỉ một chút, mô hình sẽ nhận đầu vào khác với những gì nó đã học và dự đoán sai mà không ai phát hiện ra. |
| NV-05 | Mỗi bài toán có danh sách thông tin **bị loại khỏi đầu vào** (mục 6.3), để mô hình không "nhìn thấy trước đáp án" và để bài toán không trở nên tầm thường. |
| NV-06 | Kết quả huấn luyện của các lần chạy phải **so sánh được với nhau**: mọi lần đánh giá dùng chung một tập dữ liệu kiểm tra cố định. |

---

## 4. Yêu cầu chức năng

### 4.1. Quản lý dữ liệu

| Mã | Yêu cầu |
| --- | --- |
| CN-01 | Người vận hành tải lên một tệp dữ liệu dạng bảng (CSV). Mỗi lần tải lên tạo ra một **phiên bản dữ liệu** mới, có tên nhận dạng riêng. |
| CN-02 | Người vận hành xem được nội dung mẫu và thống kê theo từng cột của một phiên bản dữ liệu. |
| CN-03 | Khi khởi chạy quy trình huấn luyện, người vận hành chọn được phiên bản dữ liệu. Mặc định là phiên bản mới nhất. |

### 4.2. Quy trình huấn luyện và đưa vào sử dụng

| Mã | Yêu cầu |
| --- | --- |
| CN-04 | Người vận hành khởi chạy quy trình, **bắt buộc** chọn một trong hai bài toán. Có tuỳ chọn "xử lý lại dữ liệu từ đầu" (mặc định: không). |
| CN-05 | **Tiếp nhận dữ liệu:** đọc dữ liệu thô của phiên bản đã chọn và chuyển sang dạng lưu trữ gọn, đọc nhanh cho các bước sau. |
| CN-06 | **Kiểm tra chất lượng:** đối chiếu dữ liệu với cấu trúc quy định (mục 6.2), đếm số giá trị thiếu và giá trị bất thường theo từng cột, ghi lại kết quả. Dừng quy trình nếu vi phạm nghiêm trọng. |
| CN-07 | **Chuẩn bị dữ liệu:** loại bản ghi trùng, loại bản ghi không có giá trị cần dự đoán, chia dữ liệu thành phần huấn luyện và phần kiểm tra. Nếu dữ liệu thô không thay đổi so với lần trước và người vận hành không chọn "xử lý lại", **dùng lại kết quả chuẩn bị của lần trước** thay vì xử lý lại. |
| CN-08 | **Huấn luyện:** huấn luyện mô hình cho bài toán đã chọn. Ghi lại cấu hình, các chỉ số đánh giá, bản thân mô hình, và phiên bản dữ liệu đã dùng. Mô hình được lưu **kèm theo toàn bộ logic làm sạch dữ liệu** (xem NV-04). |
| CN-09 | **Đánh giá:** mô hình mới phải vượt qua cả hai cổng: (1) đạt ngưỡng tối thiểu — hệ số xác định R² ≥ 0,75 với bài toán giá bán, điểm F1 ≥ 0,70 với bài toán bán nhanh; (2) tốt hơn mô hình đang sử dụng, đo trên **cùng một tập kiểm tra**. Nếu chưa có mô hình nào đang sử dụng thì chỉ áp dụng cổng (1). |
| CN-10 | **Đăng ký:** mô hình qua được đánh giá được ghi nhận là phiên bản đang sử dụng, đồng thời hệ thống tự tạo **hồ sơ thống kê cơ sở** của dữ liệu huấn luyện, gắn với đúng phiên bản mô hình đó (dùng cho giám sát, xem CN-18). |
| CN-11 | **Đưa vào sử dụng:** dịch vụ dự đoán chuyển sang phiên bản mô hình mới mà **không cần khởi động lại** dịch vụ. |
| CN-12 | Nếu mô hình không qua đánh giá, quy trình dừng, **không** thay đổi mô hình đang sử dụng. |

### 4.3. Dự đoán

| Mã | Yêu cầu |
| --- | --- |
| CN-13 | Nhận thông tin của **một** căn nhà ở dạng **thô, chưa làm sạch** — đúng như dữ liệu người dùng thật có trong tay — và trả về kết quả dự đoán, mã yêu cầu, phiên bản mô hình đã dùng. |
| CN-14 | Một dịch vụ dự đoán duy nhất phục vụ cả hai bài toán. |
| CN-15 | Ghi nhật ký mỗi lần dự đoán: mã yêu cầu, thời điểm, dữ liệu đầu vào thô, kết quả dự đoán, tên và phiên bản mô hình. |
| CN-16 | Nhận **kết quả thực tế** gửi đến sau (giá bán thật, hoặc có bán trong 30 ngày hay không), gắn với mã yêu cầu dự đoán ban đầu. |
| CN-17 | Cho biết mô hình nào đang được nạp và phiên bản bao nhiêu. |

### 4.4. Giám sát chất lượng mô hình

| Mã | Yêu cầu |
| --- | --- |
| CN-18 | Mỗi giờ, tự động so sánh dữ liệu dự đoán gần đây với hồ sơ thống kê cơ sở của **phiên bản mô hình đang sử dụng**. |
| CN-19 | Phát hiện ba loại trôi (chi tiết ở mục 10): trôi dữ liệu đầu vào, trôi kết quả dự đoán, suy giảm độ chính xác. |
| CN-20 | Tổng hợp thành một mức cảnh báo ba cấp: **Bình thường / Cảnh báo / Nghiêm trọng**. |
| CN-21 | Lưu báo cáo của mỗi lần giám sát; người vận hành xem được báo cáo mới nhất và diễn biến theo thời gian. |
| CN-22 | Khi mức cảnh báo là **Nghiêm trọng**, bảng điều khiển hiển thị cảnh báo kèm nút "Huấn luyện lại ngay", đã điền sẵn bài toán của mô hình bị ảnh hưởng. Người vận hành bấm thì mới chạy (NV-02). |

### 4.5. Mô phỏng thị trường

| Mã | Yêu cầu |
| --- | --- |
| CN-23 | Sinh các tin rao bán nhà mới theo phân phối mô phỏng thị trường và gửi yêu cầu dự đoán. |
| CN-24 | Sau một khoảng thời gian mô phỏng, gửi kết quả thực tế của các căn nhà đó. |
| CN-25 | Có bốn **kịch bản thị trường** chọn được: không thay đổi; giá tăng khoảng 20%; người mua dồn về thành phố khác; xuất hiện loại nhà mà mô hình chưa từng thấy. |
| CN-26 | Khi hệ thống mới khởi động và chưa có lưu lượng dự đoán, lấy phần dữ liệu có ngày đăng bán mới nhất trong bộ dữ liệu gốc, gửi dự đoán một lượt để bảng điều khiển có dữ liệu ban đầu. |

Có kịch bản thị trường là **bắt buộc**, không phải tuỳ chọn. Nếu tác nhân chỉ sinh dữ liệu giống hệt dữ liệu huấn luyện thì trôi không bao giờ xảy ra, cảnh báo lúc nào cũng "Bình thường", và không có cách nào kiểm chứng hệ thống phát hiện đúng. Kịch bản "không thay đổi" dùng để kiểm chứng hệ thống **không báo động nhầm**; ba kịch bản còn lại dùng để kiểm chứng hệ thống **phát hiện được**.

### 4.6. Bảng điều khiển

| Mã | Màn hình | Yêu cầu |
| --- | --- | --- |
| CN-27 | Tổng quan | Chọn bài toán, chọn "xử lý lại dữ liệu từ đầu", khởi chạy quy trình; xem trạng thái và nhật ký gần đây của từng bước. |
| CN-28 | Các bước và nhật ký | Xem nhật ký thật của quy trình, lọc theo bước, theo mức độ nghiêm trọng, theo từ khoá. |
| CN-29 | Dữ liệu | Tải dữ liệu lên (CN-01), xem mẫu và thống kê theo cột (CN-02). Việc tính thống kê do hệ thống phía sau thực hiện, không phải trình duyệt. |
| CN-30 | Mô hình | Xem danh sách phiên bản mô hình: tên, phiên bản, chỉ số đánh giá, trạng thái sử dụng. **Chỉ số hiển thị thay đổi theo bài toán** (RMSE / MAE / R² cho bài toán giá bán; F1 / AUC / độ chính xác cho bài toán bán nhanh). Người vận hành chuyển được một phiên bản sang trạng thái đang sử dụng. |
| CN-31 | Giám sát trôi | Xem báo cáo giám sát: ba loại trôi, mức cảnh báo, biểu đồ so sánh phân phối. Nút "Huấn luyện lại ngay" (CN-22). |
| CN-32 | (Chung) | Xem trạng thái hoạt động của các thành phần mà hệ thống phụ thuộc vào. |

---

## 5. Yêu cầu phi chức năng

### 5.1. Hiệu năng và tài nguyên

| Mã | Yêu cầu |
| --- | --- |
| PCN-01 | Xử lý được bộ dữ liệu khoảng **2 triệu dòng** trên **một máy tính bộ nhớ 16 GB**, trong khi toàn bộ các thành phần của hệ thống chạy đồng thời trên chính máy đó. |
| PCN-02 | Làm sạch 2 triệu dòng là phần tốn thời gian nhất của quy trình. Khi dữ liệu không đổi, lần chạy sau phải bỏ qua phần này (CN-07). Lý do: mỗi lần đổi bài toán để thử mô hình khác, nếu phải xử lý lại toàn bộ thì phần lớn thời gian chạy bị lãng phí. |
| PCN-03 | Sau bước tiếp nhận, dữ liệu được lưu ở dạng nén theo cột, giữ nguyên kiểu dữ liệu. Tệp gốc khoảng 373 MB dự kiến giảm còn khoảng 60–80 MB. Với một máy chạy đồng thời nhiều thành phần, đây là điều kiện để hệ thống chạy được, không phải tối ưu hoá sớm. |
| PCN-04 | Nhật ký dự đoán được ghi **theo lô**, không ghi riêng từng lần: ghi khi tích luỹ đủ 500 bản ghi hoặc sau 30 giây, tuỳ điều kiện nào đến trước. Lý do: tác nhân mô phỏng gửi hàng nghìn yêu cầu; ghi riêng từng lần sẽ tạo ra quá nhiều tệp nhỏ và làm chức năng giám sát đọc rất chậm. |
| PCN-05 | Trong quá trình phát triển, hệ thống chạy được trên một phần dữ liệu (200.000 dòng) để tiết kiệm bộ nhớ. Khi chạy thật thì dùng toàn bộ dữ liệu. |

### 5.2. Độ tin cậy

| Mã | Yêu cầu |
| --- | --- |
| PCN-06 | Mỗi bước của quy trình **chạy lại được** mà không gây sai lệch: chạy lại thì ghi đè chính kết quả cũ của nó, hoặc bỏ qua nếu kết quả đã có. |
| PCN-07 | Dịch vụ dự đoán **không được lỗi** khi đầu vào: thiếu một số thông tin không bắt buộc; có giá trị trống; có giá trị phân loại mà mô hình chưa từng gặp (ví dụ một loại nhà mới). |
| PCN-08 | Xử lý dữ liệu ở thời điểm dự đoán **không được loại bỏ bản ghi nào**. Dịch vụ nhận một căn nhà và phải trả về đúng một kết quả; nếu bước làm sạch loại bỏ bản ghi đó, dịch vụ không còn gì để dự đoán và sẽ lỗi. Việc loại bản ghi (trùng lặp, không có đáp án) chỉ được phép ở bước chuẩn bị dữ liệu huấn luyện. |

### 5.3. Bảo mật

| Mã | Yêu cầu |
| --- | --- |
| PCN-09 | Thông tin xác thực (mật khẩu, khoá truy cập) được tách khỏi phần mềm: quản lý bằng tệp cấu hình riêng không đưa lên kho lưu trữ dùng chung, và bằng chức năng quản lý kết nối của hệ thống điều phối. Không ghi trực tiếp vào phần mềm. |
| PCN-10 | Trình duyệt không kết nối trực tiếp tới các thành phần phía sau. Mọi thao tác từ bảng điều khiển đi qua một lớp trung gian, để thông tin xác thực của các thành phần phía sau không bao giờ nằm ở phía trình duyệt. |
| PCN-11 | Lớp trung gian xác thực người gọi bằng khoá truy cập. **Chưa bắt buộc** khi chạy trên máy cục bộ với một người dùng; **bắt buộc** trước khi mở hệ thống ra ngoài. |

### 5.4. Khả năng chuyển đổi lên đám mây

| Mã | Yêu cầu |
| --- | --- |
| PCN-12 | Khi chuyển lên đám mây, phần mềm phải thay đổi ít nhất có thể. Mọi quy ước về vị trí lưu trữ dữ liệu được tập trung ở **một chỗ duy nhất**, để khi chuyển chỉ phải sửa chỗ đó. |
| PCN-13 | Ngay từ giai đoạn 1, kho lưu trữ dữ liệu dùng cách truy cập tương thích với dịch vụ lưu trữ đối tượng của nền tảng đám mây đích, để không phải viết lại phần đọc/ghi dữ liệu khi chuyển. |
| PCN-14 | Khi chuyển, bảng điều khiển giữ nguyên; chỉ lớp trung gian phải thay đổi. |

### 5.5. Chất lượng

| Mã | Yêu cầu |
| --- | --- |
| PCN-15 | Mỗi loại lỗi dữ liệu trong mục 6.4 có ít nhất một kiểm thử tự động chứng minh hệ thống xử lý đúng. |
| PCN-16 | Cùng một bản ghi thô, khi đi qua bước làm sạch lúc chuẩn bị dữ liệu huấn luyện và khi đi qua mô hình lúc dự đoán, phải cho **cùng một kết quả**. |
| PCN-17 | Mô hình được huấn luyện và được sử dụng trong **cùng một môi trường phần mềm** (cùng phiên bản nền tảng và thư viện). Lý do: mô hình đã lưu chỉ đọc lại được đúng khi môi trường giống với lúc lưu. |
| PCN-18 | Tập kiểm tra được chia theo một cách cố định, lặp lại được, và được lưu lại. Nếu tập kiểm tra thay đổi giữa các lần huấn luyện, việc so sánh mô hình mới với mô hình cũ (CN-09) sẽ vô nghĩa. |

### 5.6. Vận hành

| Mã | Yêu cầu |
| --- | --- |
| PCN-19 | Nhật ký của từng bước trong quy trình xem được trên bảng điều khiển (CN-28). |
| PCN-20 | Trạng thái hoạt động của từng thành phần xem được trên bảng điều khiển (CN-32). |
| PCN-21 | Toàn bộ hệ thống khởi động được trên một máy bằng một thao tác duy nhất. |

---

## 6. Yêu cầu dữ liệu

### 6.1. Nguồn dữ liệu

Bộ dữ liệu giả lập thị trường bất động sản Mỹ tại 21 thành phố, khoảng **2.012.000 dòng, 24 mục thông tin**, dung lượng khoảng 373 MB. Dữ liệu **cố tình chứa lỗi** (mục 6.4) để hệ thống phải xử lý như với dữ liệu thực tế.

Tệp dữ liệu gốc không được đưa lên kho lưu trữ dùng chung, do dung lượng lớn.

### 6.2. Danh sách mục dữ liệu

| STT | Mục dữ liệu | Ý nghĩa | Đơn vị / giá trị |
| --- | --- | --- | --- |
| 1 | Mã bất động sản | Mã nhận dạng căn nhà. Bắt buộc có. | Số |
| 2 | Ngày đăng bán | Ngày căn nhà bắt đầu được rao bán | Ngày tháng |
| 3 | Thành phố | | Tên thành phố (21 thành phố) |
| 4 | Bang | | Mã bang, 2 ký tự |
| 5 | Mã bưu chính | | Đúng 5 chữ số |
| 6 | Loại bất động sản | | Nhà riêng một hộ / Căn hộ chung cư / Nhà liền kề / Nhà nhiều hộ / Đất trống |
| 7 | Diện tích đất | | Foot vuông |
| 8 | Diện tích sử dụng | Bằng 0 hoặc trống với loại "Đất trống" | Foot vuông |
| 9 | Số phòng ngủ | | Phòng |
| 10 | Số phòng tắm | Bước 0,5 | Phòng |
| 11 | Năm xây dựng | Trống với loại "Đất trống" | Năm |
| 12 | Số tầng | Bằng 0 với loại "Đất trống" | Tầng |
| 13 | Số chỗ đỗ xe trong nhà | | Chỗ |
| 14 | Có hồ bơi | | Có / Không |
| 15 | Phí quản lý hằng tháng | Phí hiệp hội chủ nhà. Trống với nhiều căn nhà không thuộc hiệp hội — đây là đặc điểm của dữ liệu, không phải lỗi. | Đô la Mỹ / tháng |
| 16 | Điểm trường học khu vực | | 1 đến 10 |
| 17 | Chỉ số tội phạm khu vực | Càng cao càng kém an toàn | 0 đến 100 |
| 18 | Khoảng cách tới trung tâm | | Km |
| 19 | Tình trạng nhà | | Kém / Trung bình / Tốt / Rất tốt |
| 20 | Số ngày rao bán | Số ngày từ khi rao đến khi bán được | Ngày |
| 21 | Giá rao bán | Giá chủ nhà đưa ra lúc bắt đầu rao | Đô la Mỹ |
| 22 | Giá bán cuối cùng | **Đáp án của bài toán dự đoán giá bán** | Đô la Mỹ |
| 23 | Phân loại mức giá | Suy ra từ giá bán cuối cùng: thấp (dưới 300.000), trung bình (300.000–500.000), cao (500.000–850.000), cao cấp (trên 850.000) | Thấp / Trung bình / Cao / Cao cấp |
| 24 | Bán trong vòng 30 ngày | **Đáp án của bài toán dự đoán bán nhanh.** Là "Có" nếu số ngày rao bán không quá 30. | Có / Không |

Khoảng giá trị hợp lệ chi tiết của từng mục được quy định trong 基本設計書.

### 6.3. Thông tin bị loại khỏi đầu vào của mô hình

| Bài toán | Mục bị loại | Lý do |
| --- | --- | --- |
| Dự đoán giá bán | Mã bất động sản | Chỉ là mã nhận dạng, không mang thông tin về căn nhà |
| | Giá bán cuối cùng | Là đáp án |
| | Phân loại mức giá | Suy ra trực tiếp từ đáp án |
| | Giá rao bán | Về thời điểm thì hợp lệ (biết trước khi bán), nhưng giá bán gần bằng giá rao, nên mô hình chỉ cần học một hệ số nhân và bài toán trở nên tầm thường |
| Dự đoán bán nhanh | Mã bất động sản | Chỉ là mã nhận dạng |
| | Bán trong vòng 30 ngày | Là đáp án |
| | Số ngày rao bán | Đáp án được suy ra trực tiếp từ mục này |
| | Giá bán cuối cùng | Chỉ biết được sau khi đã bán |
| | Phân loại mức giá | Suy ra từ giá bán cuối cùng |

Với bài toán dự đoán bán nhanh, **giá rao bán được giữ lại**: nó được biết trước khi bán, và quan hệ giữa giá rao với tốc độ bán là thông tin hữu ích chứ không làm bài toán tầm thường.

### 6.4. Các loại lỗi dữ liệu và yêu cầu xử lý

| STT | Loại lỗi | Mức độ trong dữ liệu | Yêu cầu xử lý |
| --- | --- | --- | --- |
| 1 | Thiếu giá trị | Tuỳ mục; phí quản lý thiếu khoảng 60%, ngày đăng bán khoảng 8%, các mục khác vài phần trăm | Giữ là "thiếu", không thay bằng giá trị quy ước tuỳ ý (như số âm hay chuỗi rỗng). Mô hình tự bổ sung giá trị theo quy tắc thống nhất. |
| 2 | Bản ghi trùng lặp | Khoảng 0,6% | Loại bản ghi trùng mã bất động sản, giữ bản đầu tiên. **Chỉ ở bước chuẩn bị dữ liệu huấn luyện.** |
| 3 | Giá trị phân loại viết không thống nhất | Loại bất động sản khoảng 15%, tình trạng nhà khoảng 10%, thành phố và bang một phần | Chuẩn hoá về một cách viết duy nhất. Ví dụ "Multi-Family", "MULTI FAMILY", và cách viết nối hai từ bằng dấu gạch dưới phải cho cùng một kết quả. |
| 4 | Giá trị có/không biểu diễn nhiều kiểu | Mục "có hồ bơi" có 8 kiểu viết, khoảng 2% trống | Quy về "Có" hoặc "Không". Giá trị không nhận ra được coi là thiếu. |
| 5 | Ngày tháng nhiều định dạng | Ngày đăng bán có 3 định dạng lẫn lộn | Đọc được cả 3 định dạng. Định dạng có dấu gạch chéo luôn được hiểu là **tháng trước, ngày sau**. |
| 6 | Số lẫn với chuỗi định dạng tiền | Giá rao bán khoảng 5%, giá bán khoảng 3% ở dạng "$450,000" | Quy về số. |
| 7 | Giá trị bất thường do nhập liệu sai | Khoảng 0,1–0,3% mỗi loại: năm xây dựng ở tương lai hoặc quá xa, số phòng ngủ âm hoặc quá lớn, diện tích sử dụng lớn bất thường, khoảng cách âm, số phòng tắm phi thực tế | Đưa về trong khoảng hợp lệ, **không xoá bản ghi**. Một căn nhà có số phòng ngủ sai vẫn còn thông tin hữu ích ở các mục khác. |
| 8 | Mã bưu chính sai định dạng | Khoảng 1% thiếu, khoảng 1% bị cắt còn 4 chữ số | Chỉ chấp nhận đúng 5 chữ số. **Không tự thêm số 0 vào đầu** mã 4 chữ số: coi là thiếu để bước kiểm tra chất lượng đếm và báo cáo. |

### 6.5. Nguyên tắc chung khi xử lý dữ liệu

**Hệ thống không bao giờ đoán.** Một giá trị không đọc được một cách chắc chắn được coi là thiếu, để bước kiểm tra chất lượng đếm được và báo cáo. Đoán sai sẽ tạo ra dữ liệu sai mà không ai biết; coi là thiếu thì ít nhất vấn đề được nhìn thấy.

---

## 7. Ràng buộc và tiền đề

### 7.1. Ràng buộc

| Mã | Ràng buộc |
| --- | --- |
| RB-01 | Giai đoạn 1 chạy trên một máy tính cá nhân bộ nhớ 16 GB, dung lượng đĩa còn trống hạn chế. |
| RB-02 | Giai đoạn 1 không phụ thuộc vào bất kỳ dịch vụ đám mây nào. |
| RB-03 | Việc huấn luyện và sử dụng mô hình diễn ra trong cùng một môi trường đóng gói (PCN-17). Máy phát triển chỉ dùng để kiểm thử logic, không dùng để huấn luyện mô hình thật. |

### 7.2. Tiền đề

- Dữ liệu là dữ liệu giả lập, không chứa thông tin cá nhân hay giao dịch thật.
- Giai đoạn 1 có một người vận hành, làm việc trên máy cục bộ.
- Lưu lượng dự đoán do tác nhân mô phỏng sinh ra, không có người dùng cuối thật.

---

## 8. Nội dung bị loại khỏi giai đoạn 1

| Nội dung | Lý do |
| --- | --- |
| Kho đặc trưng dùng chung | Kéo theo một cơ sở dữ liệu riêng và một tác vụ đồng bộ riêng, trong khi quy trình xử lý theo lô của hệ thống này chưa có nhu cầu cung cấp đặc trưng theo thời gian thực. Sẽ xem xét lại khi quy trình đã chạy ổn định; khi đó nó nằm giữa bước chuẩn bị dữ liệu và bước huấn luyện. |
| Tự động huấn luyện lại | Theo NV-02, con người quyết định. Có thể xem xét ở mức nâng cao, kèm thời gian chờ tối thiểu giữa hai lần huấn luyện. |
| Nhiều người dùng, truy cập từ internet | Ngoài mục đích của giai đoạn 1. Nếu cần, phải bật xác thực trước (PCN-11). |
| Chuyển lên nền tảng đám mây | Thuộc giai đoạn 2. |

---

## 9. Vấn đề còn mở

| STT | Vấn đề | Thời điểm quyết định |
| --- | --- | --- |
| 1 | Ngưỡng tối thiểu ở CN-09 (R² 0,75 và F1 0,70) là điểm khởi đầu, cần điều chỉnh sau lần huấn luyện đầu tiên khi biết mức thực tế của bộ dữ liệu. | Sau lần huấn luyện đầu tiên |
| 2 | Độ dài khoảng thời gian dữ liệu mà mỗi lần giám sát xem xét (một giờ gần nhất, hay 24 giờ trượt). Phụ thuộc tốc độ sinh lưu lượng của tác nhân mô phỏng. | Sau khi xây dựng tác nhân mô phỏng |
| 3 | Khi chuyển lên đám mây: giữ công cụ quản lý mô hình hiện tại song song với dịch vụ tương ứng của nền tảng đám mây, hay chuyển hẳn. | Giai đoạn 2 |
| 4 | Tiêu chí định lượng của "vi phạm nghiêm trọng" khiến quy trình dừng ở bước kiểm tra chất lượng (CN-06) chưa được quy định. | Khi xây dựng bước kiểm tra chất lượng |
| 5 | Tiêu chí định lượng để xếp kết quả giám sát vào từng mức Bình thường / Cảnh báo / Nghiêm trọng (CN-20) chưa được quy định. | Khi xây dựng chức năng giám sát |
| 6 | Thời gian phản hồi mục tiêu của dịch vụ dự đoán, thời gian lưu giữ nhật ký và báo cáo, cách sao lưu dữ liệu chưa được quy định cho giai đoạn 1. | Trước giai đoạn 2 |

---

## 10. Thuật ngữ

| Thuật ngữ | Giải thích |
| --- | --- |
| Mô hình | Kết quả của việc cho máy học từ dữ liệu quá khứ, dùng để dự đoán cho trường hợp mới. |
| Huấn luyện | Quá trình tạo ra mô hình từ dữ liệu. |
| Đặc trưng / đầu vào | Các mục thông tin về căn nhà mà mô hình dùng để dự đoán. |
| Đáp án | Giá trị mà mô hình cần dự đoán (giá bán, hoặc có bán nhanh hay không). |
| Tập kiểm tra | Phần dữ liệu tách riêng, không dùng để huấn luyện, chỉ dùng để chấm điểm mô hình. |
| Phiên bản đang sử dụng | Phiên bản mô hình mà dịch vụ dự đoán đang dùng để trả lời yêu cầu. |
| Hồ sơ thống kê cơ sở | Bản tóm tắt thống kê (giá trị trung bình, độ phân tán, phân bố, tỉ lệ thiếu…) của dữ liệu đã dùng để huấn luyện một phiên bản mô hình. Là mốc để so sánh khi giám sát. |
| Trôi dữ liệu đầu vào | Dữ liệu gửi đến để dự đoán có phân bố khác với dữ liệu lúc huấn luyện. Đo được ngay, không cần chờ kết quả thực tế. |
| Trôi kết quả dự đoán | Các kết quả mô hình trả ra có phân bố khác với lúc huấn luyện. Đo được ngay. |
| Suy giảm độ chính xác | Dự đoán sai lệch nhiều hơn so với kết quả thực tế. Là loại quan trọng nhất nhưng **luôn đến trễ**, vì phải chờ căn nhà thật sự được bán mới biết kết quả. |
| Kết quả thực tế | Giá bán thật, hoặc việc căn nhà có thật sự bán trong 30 ngày hay không. Được gửi đến sau thời điểm dự đoán. |
| Nhật ký dự đoán | Bản ghi lại mỗi lần dự đoán: đầu vào, kết quả, phiên bản mô hình. |
| Tác nhân mô phỏng | Thành phần tự động đóng vai người dùng, sinh yêu cầu dự đoán và báo kết quả thực tế. |
| Kịch bản thị trường | Cách tác nhân mô phỏng làm thay đổi dữ liệu có chủ đích, để kiểm chứng khả năng phát hiện trôi. |
| RMSE, MAE | Hai cách đo độ lệch trung bình giữa giá dự đoán và giá thật, tính bằng đô la. Càng nhỏ càng tốt. |
| R² (hệ số xác định) | Tỉ lệ biến động của giá bán mà mô hình giải thích được, từ 0 đến 1. Càng gần 1 càng tốt. |
| F1, AUC, độ chính xác | Các cách đo chất lượng của dự đoán có/không. Càng gần 1 càng tốt. |
| Vận hành học máy | Tập hợp các cách làm để đưa mô hình học máy vào sử dụng và duy trì chất lượng của nó một cách tự động, lặp lại được. |
