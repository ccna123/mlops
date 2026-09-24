# 要件定義書 — Hệ thống vận hành học máy dự đoán giá bất động sản

| Mục | Nội dung |
| --- | --- |
| Tên tài liệu | 要件定義書 (Tài liệu định nghĩa yêu cầu) |
| Hệ thống | Hệ thống vận hành học máy dự đoán giá bất động sản |
| Phiên bản | 1.0 |
| Ngày lập | 24/09/2026 |
| Căn cứ | Tài liệu thiết kế hệ thống và các tài liệu thiết kế chi tiết của năm giai đoạn xây dựng, trạng thái ngày 24/09/2026 |
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
| Quy trình huấn luyện và đưa vào sử dụng | Tự động huấn luyện lại khi phát hiện bất thường |
| Dịch vụ dự đoán phục vụ cả hai bài toán | Xác thực người dùng, mở hệ thống ra internet |
| Giám sát chất lượng mô hình | Quy trình chạy tự động theo lịch |
| Tác nhân mô phỏng thị trường sinh lưu lượng dự đoán | Chuyển hệ thống lên nền tảng đám mây (thuộc giai đoạn 2) |
| Bảng điều khiển để vận hành toàn bộ hệ thống | |

---

## 2. Các bên liên quan

| Bên liên quan | Vai trò |
| --- | --- |
| Người vận hành | Thao tác với hệ thống qua bảng điều khiển: tải dữ liệu lên, khởi chạy huấn luyện, xem kết quả, quyết định phiên bản mô hình nào được sử dụng, cho mô phỏng lưu lượng và xem kết quả giám sát, quyết định huấn luyện lại. Giai đoạn 1 giả định chỉ có **một** người vận hành, làm việc trên máy cục bộ. |
| Tác nhân mô phỏng thị trường | Thành phần tự động đóng vai người dùng cuối: gửi yêu cầu dự đoán cho các căn nhà rao bán, rồi báo lại kết quả thực tế. Nó thay thế cho người dùng thật, vốn không có trong một dự án học tập. Chỉ hoạt động khi người vận hành ra lệnh. |

---

## 3. Yêu cầu nghiệp vụ

### 3.1. Hai bài toán dự đoán

Hệ thống phục vụ hai mô hình trên cùng một nguồn dữ liệu.

| Bài toán | Loại | Giá trị cần dự đoán | Chỉ số dùng để quyết định | Chỉ số báo cáo thêm |
| --- | --- | --- | --- | --- |
| Dự đoán giá bán | Hồi quy (dự đoán một con số) | Giá bán cuối cùng của căn nhà, tính bằng đô la Mỹ | Hệ số xác định (R²), sai số bình phương trung bình căn (RMSE) | Sai số tuyệt đối trung bình (MAE) |
| Dự đoán nhu cầu cải tạo | Phân loại hai lớp (có / không) | Căn nhà có **cần cải tạo** hay không — tức tình trạng nhà là "Kém" hoặc "Trung bình" | Diện tích dưới đường cong (AUC) | Điểm F1, độ chính xác |

Hai bài toán đo hai điều khác nhau — **giá bán** và **tình trạng tài sản** — nên bổ sung cho nhau.

**Ý nghĩa nghiệp vụ của bài toán thứ hai.** Tình trạng nhà trong thực tế do người bán tự khai, thường bị bỏ trống hoặc khai lạc quan. Dự đoán nó từ các thuộc tính khách quan (tuổi nhà, diện tích, khu vực, giá rao, điểm trường, chỉ số tội phạm…) giúp: 
1. nền tảng bất động sản gắn cờ tin cần thẩm định kỹ
2. ngân hàng đánh giá tài sản thế chấp
3. nhà đầu tư tìm nhà cần cải tạo.

**Vì sao không chọn các bài toán khác** (đã đo trên dữ liệu thật trước khi quyết định):

| Ứng viên | Lý do loại |
| --- | --- |
| Phân loại mức giá (thấp / trung bình / cao / cao cấp) | Suy ra trực tiếp từ giá bán, tức lặp lại bài toán thứ nhất |
| Bán trong vòng 30 ngày | Gần như chỉ phụ thuộc vào số ngày rao bán — thông tin bắt buộc phải loại vì đáp án suy ra từ nó. Bỏ nó đi thì mọi thông tin còn lại gộp lại chỉ đạt AUC 0,58, gần như đoán mò. |
| Bán cao hơn giá rao | AUC 0,50: dữ liệu giả lập tạo mục này hoàn toàn ngẫu nhiên, không có gì để học |

Bài toán "cần cải tạo" đạt AUC khoảng 0,71, và tín hiệu **phân tán thật** trên nhiều thông tin: không thông tin đơn lẻ nào vượt quá 0,56. Tỉ lệ nhà cần cải tạo trong dữ liệu là khoảng 25%.

### 3.2. Luồng nghiệp vụ tổng thể

```
  [Người vận hành]
        │ chọn bài toán, thuật toán, bấm chạy
        ▼
  Tiếp nhận dữ liệu → Kiểm tra chất lượng → Chuẩn bị dữ liệu → Huấn luyện → Đánh giá
                                                                            │
                                         ┌──────────────── đạt ────────────┤
                                         ▼                                  │ không đạt
                         Đăng ký phiên bản mới → Đưa vào sử dụng           ▼
                                                                          Dừng, giữ nguyên
                                                                          mô hình đang dùng

  [Người vận hành] chọn kịch bản thị trường, số yêu cầu, bấm mô phỏng
        │
        ▼
  Tác nhân mô phỏng ── gửi yêu cầu dự đoán ──▶ Dịch vụ dự đoán ── ghi nhật ký
        │
        └── gửi kết quả thực tế ──▶ Dịch vụ dự đoán ── ghi kết quả thực tế
        │
        ▼
  Giám sát: so nhật ký dự đoán và kết quả thực tế với lúc huấn luyện
        │
        └── báo cáo + mức cảnh báo ──▶ Bảng điều khiển ──▶ [Người vận hành] quyết định huấn luyện lại
```

### 3.3. Nguyên tắc nghiệp vụ

| Mã | Nguyên tắc |
| --- | --- |
| NV-01 | **Không có quy trình nào tự chạy theo lịch** ở giai đoạn 1. Huấn luyện, mô phỏng lưu lượng và giám sát đều chạy khi người vận hành yêu cầu. Lý do: máy chạy hệ thống có tài nguyên hạn chế, và một tác vụ nặng tự chạy trong nền là thứ người ta quên mất rồi không hiểu vì sao máy chậm. Khi chuyển lên đám mây, giám sát sẽ trở lại chạy định kỳ mỗi giờ. |
| NV-02 | Hệ thống **không tự huấn luyện lại**. Khi phát hiện bất thường nghiêm trọng, hệ thống chỉ cảnh báo; con người quyết định. |
| NV-03 | Một mô hình mới chỉ được đưa vào sử dụng tự động khi **vừa đạt ngưỡng chất lượng tối thiểu, vừa tốt hơn mô hình đang được sử dụng** (chi tiết ở CN-10). Người vận hành vẫn có quyền chỉ định thủ công phiên bản nào được sử dụng. |
| NV-04 | Cách làm sạch dữ liệu **phải giống hệt nhau** giữa lúc huấn luyện và lúc dự đoán. Nếu hai lúc làm sạch khác nhau dù chỉ một chút, mô hình sẽ nhận đầu vào khác với những gì nó đã học và dự đoán sai mà không ai phát hiện ra. |
| NV-05 | Mỗi bài toán có danh sách thông tin **bị loại khỏi đầu vào** (mục 6.3), để mô hình không "nhìn thấy trước đáp án" và để bài toán không trở nên tầm thường. |
| NV-06 | Kết quả huấn luyện của các lần chạy phải **so sánh được với nhau**: mọi lần đánh giá dùng chung một tập dữ liệu kiểm tra cố định. |
| NV-07 | Hệ thống **không được báo "ổn" khi chưa đo được**. Khi chưa đủ kết quả thực tế để đánh giá độ chính xác, hệ thống phải nói rõ là "chưa đủ dữ liệu", không được hiển thị như trạng thái tốt. |

---

## 4. Yêu cầu chức năng

### 4.1. Quản lý dữ liệu

| Mã | Yêu cầu |
| --- | --- |
| CN-01 | Người vận hành tải lên một tệp dữ liệu dạng bảng (CSV), đặt tên cho **phiên bản dữ liệu**. Tên phiên bản bắt đầu bằng chữ hoặc số, dài tối đa 64 ký tự, chỉ gồm chữ, số, dấu chấm, gạch dưới và gạch nối. Dung lượng tệp tối đa 500 MiB. |
| CN-02 | Tải lên vào một phiên bản **đã tồn tại** sẽ ghi đè dữ liệu cũ. Hệ thống phải hỏi xác nhận trước khi ghi đè. |
| CN-03 | Người vận hành xem được các dòng mẫu (tối đa 200 dòng, đúng như dữ liệu thô đã lưu, không làm sạch) và thống kê theo từng cột của một phiên bản dữ liệu: loại dữ liệu, tỉ lệ thiếu, số giá trị nằm ngoài khoảng hợp lệ. |
| CN-04 | Khi khởi chạy quy trình huấn luyện, người vận hành chỉ định được phiên bản dữ liệu. |

### 4.2. Quy trình huấn luyện và đưa vào sử dụng

| Mã | Yêu cầu |
| --- | --- |
| CN-05 | Người vận hành khởi chạy quy trình với các lựa chọn: bài toán (**bắt buộc**); thuật toán (một trong ba thuật toán của bài toán đó, bỏ trống thì dùng mặc định); có tinh chỉnh tham số tự động hay không (mặc định: không); số dòng dữ liệu dùng để huấn luyện hoặc toàn bộ; có xử lý lại dữ liệu từ đầu hay không (mặc định: không); phiên bản dữ liệu. Hệ thống hỏi xác nhận trước khi chạy, nêu lại đủ các lựa chọn. |
| CN-06 | Tại một thời điểm chỉ có **một** lần chạy quy trình huấn luyện được thực hiện. |
| CN-07 | **Tiếp nhận dữ liệu:** đọc dữ liệu thô của phiên bản đã chọn, lấy số dòng yêu cầu, chuyển sang dạng lưu trữ gọn, đọc nhanh cho các bước sau. |
| CN-08 | **Kiểm tra chất lượng:** đo và báo cáo chất lượng dữ liệu — tỉ lệ thiếu, số giá trị ngoài khoảng hợp lệ, số mã bưu chính sai định dạng, số bản ghi trùng. Chỉ dừng quy trình khi dữ liệu **vô dụng**: thiếu mục so với danh sách quy định, hơn một nửa giá trị đáp án bị thiếu, hoặc không có dòng nào. Dữ liệu bẩn nhưng dùng được thì không dừng. |
| CN-09 | **Chuẩn bị dữ liệu:** loại bản ghi trùng, loại bản ghi không có đáp án, chia dữ liệu thành phần huấn luyện và phần kiểm tra. Nếu dữ liệu không thay đổi so với lần trước và người vận hành không chọn "xử lý lại", **dùng lại kết quả chuẩn bị của lần trước**. |
| CN-10 | **Huấn luyện:** huấn luyện mô hình bằng thuật toán đã chọn. Nếu người vận hành bật tinh chỉnh tham số, hệ thống tự thử một số tổ hợp tham số và chọn tổ hợp tốt nhất theo đúng chỉ số dùng để quyết định ở CN-11. Ghi lại cấu hình, các chỉ số, bản thân mô hình, và dữ liệu đã dùng. Mô hình được lưu **kèm theo toàn bộ logic làm sạch dữ liệu** (xem NV-04). |
| CN-11 | **Đánh giá:** chấm mô hình trên tập kiểm tra. Mô hình mới phải vượt qua cả hai cổng: (1) đạt ngưỡng tối thiểu — R² ≥ 0,75 với bài toán giá bán, AUC ≥ 0,55 với bài toán cải tạo; (2) tốt hơn mô hình đang sử dụng trên **cùng một tập kiểm tra** — RMSE thấp hơn với bài toán giá bán, AUC cao hơn với bài toán cải tạo. Nếu chưa có mô hình nào đang sử dụng thì chỉ áp dụng cổng (1). |
| CN-12 | **Đăng ký:** mô hình qua được đánh giá được ghi nhận là phiên bản đang sử dụng, đồng thời hệ thống tự tạo **hồ sơ thống kê cơ sở** của dữ liệu huấn luyện, gắn với đúng phiên bản đó. |
| CN-13 | **Đưa vào sử dụng:** dịch vụ dự đoán chuyển sang phiên bản mô hình mới mà **không cần khởi động lại** dịch vụ. |
| CN-14 | Nếu mô hình không qua đánh giá, quy trình dừng, **không** thay đổi mô hình đang sử dụng. |

### 4.3. Quản lý mô hình

| Mã | Yêu cầu |
| --- | --- |
| CN-15 | Người vận hành xem được danh sách phiên bản của từng mô hình: số phiên bản, các chỉ số trên tập kiểm tra, thời điểm tạo, phiên bản nào đang được sử dụng. **Các chỉ số hiển thị thay đổi theo bài toán** (RMSE / MAE / R² cho bài toán giá bán; AUC / F1 / độ chính xác cho bài toán cải tạo). |
| CN-16 | Người vận hành chỉ định thủ công một phiên bản khác làm phiên bản đang sử dụng, sau khi xác nhận. |
| CN-17 | Người vận hành xoá được một phiên bản, sau khi xác nhận. **Không được xoá phiên bản đang sử dụng**: phải chuyển phiên bản đang sử dụng sang phiên bản khác trước. |
| CN-18 | Người vận hành xoá được toàn bộ một mô hình (mọi phiên bản, kể cả phiên bản đang sử dụng), sau khi xác nhận. Đây là thao tác **không hoàn tác được**. Sau khi xoá, dịch vụ dự đoán báo rõ là chưa có mô hình cho bài toán đó. |

### 4.4. Dự đoán

| Mã | Yêu cầu |
| --- | --- |
| CN-19 | Nhận thông tin của **một** căn nhà ở dạng **thô, chưa làm sạch** — đúng như dữ liệu người dùng thật có trong tay — và trả về kết quả dự đoán, mã yêu cầu, phiên bản mô hình đã dùng. Với bài toán cải tạo, trả thêm xác suất. |
| CN-20 | Một dịch vụ dự đoán duy nhất phục vụ cả hai bài toán. |
| CN-21 | Dịch vụ vẫn hoạt động khi một hoặc cả hai mô hình chưa có: bài toán có mô hình thì phục vụ bình thường, bài toán chưa có thì báo rõ là chưa sẵn sàng. |
| CN-22 | Ghi nhật ký mỗi lần dự đoán: mã yêu cầu, thời điểm, dữ liệu đầu vào thô, kết quả dự đoán, xác suất (bài toán cải tạo), tên và phiên bản mô hình. |
| CN-23 | Nhận **kết quả thực tế** gửi đến sau theo lô, mỗi kết quả gắn với mã yêu cầu dự đoán ban đầu và ngày đã dự đoán. |
| CN-24 | Cho biết mô hình nào đang được nạp, phiên bản bao nhiêu, và tình trạng ghi nhật ký. |

### 4.5. Mô phỏng thị trường

| Mã | Yêu cầu |
| --- | --- |
| CN-25 | Người vận hành chọn kịch bản thị trường và số yêu cầu (1 đến 5.000), rồi ra lệnh mô phỏng cho mô hình đang xem. |
| CN-26 | Tác nhân mô phỏng lấy các căn nhà có ngày đăng bán mới nhất trong dữ liệu, biến đổi theo kịch bản, gửi yêu cầu dự đoán, rồi gửi kết quả thực tế tương ứng. |
| CN-27 | Có **năm** kịch bản thị trường (bảng dưới). |
| CN-28 | Sau khi gửi lưu lượng, hệ thống **tự động chạy giám sát** và bảng điều khiển tự tải lại báo cáo khi xong. Người vận hành thấy được tiến trình hai chặng (gửi lưu lượng → tính giám sát). Việc tính giám sát vẫn hoàn tất kể cả khi người vận hành đóng trình duyệt giữa chừng. |

| Kịch bản | Mô phỏng | Dùng để kiểm chứng |
| --- | --- | --- |
| Không thay đổi | Giống dữ liệu huấn luyện | Hệ thống **không báo động nhầm** |
| Lạm phát giá rao | Giá rao bán tăng khoảng 20%, giá bán thật giữ nguyên | Biến động ở một thông tin mà mô hình **không dùng** thì không phải là trôi |
| Thị trường tăng giá | Giá rao bán và giá bán thật cùng tăng khoảng 20% | Độ chính xác có thể sụt giảm **trong khi dữ liệu đầu vào không hề đổi** |
| Dịch chuyển thị trường | Giao dịch dồn về một vài thành phố | Hệ thống phát hiện được trôi dữ liệu đầu vào |
| Phân khúc mới | Xuất hiện loại bất động sản mô hình chưa từng thấy | Dịch vụ dự đoán **không lỗi** với giá trị lạ |

Có kịch bản thị trường là **bắt buộc**. Nếu tác nhân chỉ sinh dữ liệu giống hệt dữ liệu huấn luyện thì trôi không bao giờ xảy ra và không có cách nào kiểm chứng hệ thống phát hiện đúng. Hai kịch bản "Lạm phát giá rao" và "Thị trường tăng giá" tồn tại để chứng minh rằng **dữ liệu đổi không đồng nghĩa với mô hình hỏng, và dữ liệu không đổi không đồng nghĩa với mô hình ổn** — lý do phải báo cáo ba loại trôi tách riêng (CN-30).

### 4.6. Giám sát chất lượng mô hình

| Mã | Yêu cầu |
| --- | --- |
| CN-29 | Giám sát so sánh dữ liệu dự đoán trong khoảng thời gian gần đây với dữ liệu lúc huấn luyện của **phiên bản mô hình đang sử dụng**, cho cả hai mô hình. |
| CN-30 | Báo cáo **ba loại trôi tách riêng**, không gộp thành một: trôi dữ liệu đầu vào, trôi kết quả dự đoán, suy giảm độ chính xác. |
| CN-31 | Mỗi loại trôi có một trong **bốn** trạng thái: **Ổn / Cảnh báo / Cao / Chưa đủ dữ liệu**. "Chưa đủ dữ liệu" phải trông khác hẳn "Ổn" (NV-07). |
| CN-32 | Mỗi báo cáo có so sánh trực tiếp các chỉ số trên tập kiểm tra với các chỉ số trên lưu lượng thực tế, kèm mức chênh lệch. |
| CN-33 | Người vận hành xem được báo cáo mới nhất, diễn biến qua các lần giám sát, và báo cáo chi tiết của công cụ phát hiện trôi. |
| CN-34 | Khi có mức **Cao**, bảng điều khiển hiển thị nút "Huấn luyện lại", đưa người vận hành sang màn khởi chạy với bài toán đã điền sẵn. Người vận hành xác nhận thì mới chạy (NV-02). |

### 4.7. Bảng điều khiển

| Mã | Màn hình | Yêu cầu |
| --- | --- | --- |
| CN-35 | Tổng quan | Khởi chạy quy trình (CN-05); xem danh sách các lần chạy gần đây và trạng thái từng bước của một lần chạy. |
| CN-36 | Dữ liệu | Tải dữ liệu lên, xem mẫu và thống kê (CN-01 – CN-03). Việc tính thống kê do hệ thống phía sau thực hiện, không phải trình duyệt. |
| CN-37 | Mô hình | Quản lý phiên bản mô hình (CN-15 – CN-18). |
| CN-38 | Giám sát trôi | Mô phỏng lưu lượng (CN-25 – CN-28) và xem kết quả giám sát (CN-29 – CN-34). |
| CN-39 | (Chung) | Xem trạng thái hoạt động của từng thành phần mà hệ thống phụ thuộc vào. |
| CN-40 | (Chung) | Mọi màn hình phân biệt được ba tình huống: **chưa có dữ liệu** (bình thường, ví dụ ngày đầu chưa có lưu lượng), **không tìm thấy**, và **hệ thống đang hỏng**. |
| CN-41 | (Chung) | Mọi thao tác ghi thật (khởi chạy huấn luyện, chỉ định phiên bản, xoá, ghi đè dữ liệu) phải được xác nhận trước khi thực hiện. |

---

## 5. Yêu cầu phi chức năng

### 5.1. Hiệu năng và tài nguyên

| Mã | Yêu cầu |
| --- | --- |
| PCN-01 | Xử lý được bộ dữ liệu khoảng **2 triệu dòng** trên **một máy tính bộ nhớ 16 GB**, trong khi toàn bộ các thành phần của hệ thống chạy đồng thời trên chính máy đó. |
| PCN-02 | Khi dữ liệu không đổi, lần chạy sau phải bỏ qua phần đọc và chuẩn bị dữ liệu (CN-09). Lý do: đây là phần tốn thời gian nhất của quy trình; mỗi lần đổi thuật toán để thử, nếu phải xử lý lại toàn bộ thì phần lớn thời gian chạy bị lãng phí. Kết quả chuẩn bị ứng với số dòng khác nhau không bao giờ được dùng lẫn cho nhau. |
| PCN-03 | Sau bước tiếp nhận, dữ liệu được lưu ở dạng nén theo cột, giữ nguyên kiểu dữ liệu. Tệp gốc khoảng 373 MB dự kiến giảm còn khoảng 60–80 MB. |
| PCN-04 | Nhật ký dự đoán được ghi **theo lô**, không ghi riêng từng lần: ghi khi tích luỹ đủ 500 bản ghi hoặc sau 30 giây, tuỳ điều kiện nào đến trước. |
| PCN-05 | Người vận hành giới hạn được số dòng dữ liệu cho từng lần huấn luyện, để thử nghiệm trên máy có bộ nhớ hạn chế. Bảng điều khiển luôn gửi giới hạn này. |
| PCN-06 | Việc tinh chỉnh tham số (CN-10) chỉ thử một số ít tổ hợp (tối đa 8 cho mỗi thuật toán) để vừa với tài nguyên của máy. |

### 5.2. Độ tin cậy

| Mã | Yêu cầu |
| --- | --- |
| PCN-07 | Mỗi bước của quy trình **chạy lại được** mà không gây sai lệch: chạy lại thì ghi đè chính kết quả cũ của nó, hoặc bỏ qua nếu kết quả đã có. |
| PCN-08 | Dịch vụ dự đoán **không được lỗi** khi đầu vào: thiếu một số thông tin; có giá trị trống; có giá trị phân loại mà mô hình chưa từng gặp. |
| PCN-09 | Xử lý dữ liệu ở thời điểm dự đoán **không được loại bỏ bản ghi nào**. Dịch vụ nhận một căn nhà và phải trả về đúng một kết quả; nếu bước làm sạch loại bỏ bản ghi đó, dịch vụ không còn gì để dự đoán và sẽ lỗi. Việc loại bản ghi chỉ được phép ở bước chuẩn bị dữ liệu huấn luyện. |
| PCN-10 | Việc ghi nhật ký **không bao giờ được làm chậm hay làm hỏng** một lần dự đoán. Khi ghi thất bại, dữ liệu được giữ lại để thử lần sau; khi bộ đệm đầy thì bỏ bản ghi cũ nhất và **đếm số bản ghi đã bỏ** để người vận hành nhìn thấy. Mất mát phải có giới hạn và nhìn thấy được, không âm thầm. |
| PCN-11 | Mỗi quy trình chỉ chạy một lần tại một thời điểm, để kết quả của hai lần chạy không trộn lẫn vào nhau. |

### 5.3. Bảo mật

| Mã | Yêu cầu |
| --- | --- |
| PCN-12 | Thông tin xác thực (mật khẩu, khoá truy cập) được tách khỏi phần mềm: quản lý bằng tệp cấu hình riêng không đưa lên kho lưu trữ dùng chung. |
| PCN-13 | Trình duyệt không kết nối trực tiếp tới các thành phần phía sau. Mọi thao tác từ bảng điều khiển đi qua một lớp trung gian, để thông tin xác thực của các thành phần phía sau không bao giờ nằm ở phía trình duyệt. |
| PCN-14 | Lớp trung gian phải có điểm kiểm tra quyền truy cập dùng chung cho mọi thao tác. Ở giai đoạn 1 điểm này **chưa kiểm tra gì**: chấp nhận được khi chạy trên máy cục bộ với một người dùng, **bắt buộc** phải bật trước khi mở hệ thống ra ngoài (xem mục 7.2). |

### 5.4. Khả năng chuyển đổi lên đám mây

| Mã | Yêu cầu |
| --- | --- |
| PCN-15 | Khi chuyển lên đám mây, phần mềm phải thay đổi ít nhất có thể. Mọi quy ước về vị trí lưu trữ dữ liệu được tập trung ở **một chỗ duy nhất**, để khi chuyển chỉ phải sửa chỗ đó. |
| PCN-16 | Ngay từ giai đoạn 1, kho lưu trữ dữ liệu dùng cách truy cập tương thích với dịch vụ lưu trữ đối tượng của nền tảng đám mây đích. |
| PCN-17 | Khi chuyển, bảng điều khiển giữ nguyên; chỉ lớp trung gian phải thay đổi. |

### 5.5. Chất lượng

| Mã | Yêu cầu |
| --- | --- |
| PCN-18 | Mỗi loại lỗi dữ liệu trong mục 6.4 có ít nhất một kiểm thử tự động chứng minh hệ thống xử lý đúng. |
| PCN-19 | Một mô hình sau khi lưu rồi nạp lại phải cho **cùng kết quả** với chính nó trước khi lưu, trên cùng một bản ghi thô. |
| PCN-20 | Mô hình được huấn luyện và được sử dụng trong **cùng một môi trường phần mềm** (cùng phiên bản nền tảng và thư viện). Lý do: mô hình đã lưu chỉ đọc lại được đúng khi môi trường giống với lúc lưu. |
| PCN-21 | Tập kiểm tra được chia theo một cách cố định, lặp lại được, và được lưu lại (NV-06). |
| PCN-22 | Các cổng đánh giá phải chặn được một mô hình đoán mò (mô hình không nhìn dữ liệu mà luôn trả cùng một câu trả lời). |

### 5.6. Vận hành

| Mã | Yêu cầu |
| --- | --- |
| PCN-23 | Trạng thái từng bước của mỗi lần chạy xem được trên bảng điều khiển. Nhật ký chi tiết của từng bước xem trên giao diện của hệ thống điều phối. |
| PCN-24 | Toàn bộ hệ thống khởi động được trên một máy bằng một thao tác duy nhất. |
| PCN-25 | Bảng điều khiển có chế độ minh hoạ dùng dữ liệu mẫu, để xem được giao diện khi hệ thống phía sau chưa chạy. |

---

## 6. Yêu cầu dữ liệu

### 6.1. Nguồn dữ liệu

Bộ dữ liệu giả lập thị trường bất động sản Mỹ tại 21 thành phố, khoảng **2.012.000 dòng, 24 mục thông tin**, dung lượng khoảng 373 MB. Dữ liệu **cố tình chứa lỗi** (mục 6.4) để hệ thống phải xử lý như với dữ liệu thực tế.

Tệp dữ liệu gốc không được đưa lên kho lưu trữ dùng chung, do dung lượng lớn. Nó được nạp vào kho dữ liệu của hệ thống một lần lúc cài đặt, làm phiên bản dữ liệu đầu tiên.

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
| 19 | Tình trạng nhà | Do người bán tự khai. **Là nguồn sinh ra đáp án của bài toán cải tạo.** | Kém / Trung bình / Tốt / Rất tốt |
| 20 | Số ngày rao bán | Số ngày từ khi rao đến khi bán được | Ngày |
| 21 | Giá rao bán | Giá chủ nhà đưa ra lúc bắt đầu rao | Đô la Mỹ |
| 22 | Giá bán cuối cùng | **Đáp án của bài toán dự đoán giá bán** | Đô la Mỹ |
| 23 | Phân loại mức giá | Suy ra từ giá bán cuối cùng: thấp (dưới 300.000), trung bình (300.000–500.000), cao (500.000–850.000), cao cấp (trên 850.000) | Thấp / Trung bình / Cao / Cao cấp |
| 24 | Bán trong vòng 30 ngày | Là "Có" nếu số ngày rao bán không quá 30 | Có / Không |

**Mục sinh thêm (không có trong dữ liệu gốc):**

| Mục | Cách sinh | Dùng cho |
| --- | --- | --- |
| Cần cải tạo | "Có" nếu tình trạng nhà là Kém hoặc Trung bình; "Không" nếu Tốt hoặc Rất tốt; **để trống** nếu tình trạng nhà trống hoặc không đọc được | Đáp án của bài toán dự đoán nhu cầu cải tạo |

Khoảng giá trị hợp lệ chi tiết của từng mục được quy định trong 基本設計書.

### 6.3. Thông tin bị loại khỏi đầu vào của mô hình

| Bài toán | Mục bị loại | Lý do |
| --- | --- | --- |
| Dự đoán giá bán | Mã bất động sản | Chỉ là mã nhận dạng, không mang thông tin về căn nhà |
| | Giá bán cuối cùng | Là đáp án |
| | Phân loại mức giá | Suy ra trực tiếp từ đáp án |
| | Giá rao bán | Về thời điểm thì hợp lệ (biết trước khi bán), nhưng giá bán gần bằng giá rao, nên mô hình chỉ cần học một hệ số nhân và bài toán trở nên tầm thường |
| Dự đoán nhu cầu cải tạo | Mã bất động sản | Chỉ là mã nhận dạng |
| | Tình trạng nhà | Là nguồn sinh ra đáp án |
| | Giá bán cuối cùng | Chỉ biết được sau khi đã bán |
| | Số ngày rao bán | Chỉ biết được sau khi đã bán |
| | Bán trong vòng 30 ngày | Chỉ biết được sau khi đã bán |
| | Phân loại mức giá | Suy ra từ giá bán cuối cùng |

Với bài toán cải tạo, **giá rao bán được giữ lại**: nó được biết tại thời điểm đăng tin, và là thông tin đơn lẻ mạnh nhất của bài toán đó.

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
| RB-03 | Việc huấn luyện và sử dụng mô hình diễn ra trong cùng một môi trường đóng gói (PCN-20). Máy phát triển chỉ dùng để kiểm thử logic, không dùng để huấn luyện mô hình thật. |

### 7.2. Tiền đề

- Dữ liệu là dữ liệu giả lập, không chứa thông tin cá nhân hay giao dịch thật.
- Giai đoạn 1 có một người vận hành, làm việc trên máy cục bộ. **Hệ thống chưa có xác thực**: bất kỳ ai kết nối được tới lớp trung gian đều thực hiện được mọi thao tác, kể cả xoá mô hình. Tiền đề này chỉ đúng khi hệ thống không được mở ra ngoài máy cục bộ.
- Lưu lượng dự đoán do tác nhân mô phỏng sinh ra, không có người dùng cuối thật.

---

## 8. Nội dung bị loại khỏi giai đoạn 1

| Nội dung | Lý do |
| --- | --- |
| Kho đặc trưng dùng chung | Kéo theo một cơ sở dữ liệu riêng và một tác vụ đồng bộ riêng, trong khi quy trình xử lý theo lô của hệ thống này chưa có nhu cầu cung cấp đặc trưng theo thời gian thực. Sẽ xem xét lại khi quy trình đã chạy ổn định. |
| Tự động huấn luyện lại | Theo NV-02, con người quyết định. Có thể xem xét ở mức nâng cao, kèm thời gian chờ tối thiểu giữa hai lần huấn luyện. |
| Quy trình chạy theo lịch | Theo NV-01. Giám sát định kỳ mỗi giờ được khôi phục khi chuyển lên đám mây. |
| Xem nhật ký chi tiết trên bảng điều khiển | Đã có ở bản thiết kế đầu, sau đó bỏ. Nhật ký chi tiết xem trên giao diện của hệ thống điều phối. |
| Liệt kê, xoá hay đổi tên phiên bản dữ liệu | Chưa có nhu cầu. Người vận hành nhập tên phiên bản bằng tay. |
| Xác thực, nhiều người dùng, truy cập từ internet | Ngoài mục đích của giai đoạn 1 (PCN-14). |
| Chuyển lên nền tảng đám mây | Thuộc giai đoạn 2. |

---

## 9. Vấn đề còn mở

| STT | Vấn đề | Thời điểm quyết định |
| --- | --- | --- |
| 1 | Ngưỡng tối thiểu ở CN-11 là điểm khởi đầu, có thể điều chỉnh khi có thêm kết quả huấn luyện thực tế. | Theo kết quả vận hành |
| 2 | Khi chuyển lên đám mây: giữ công cụ quản lý mô hình hiện tại song song với dịch vụ tương ứng của nền tảng đám mây, hay chuyển hẳn. | Giai đoạn 2 |
| 3 | Bắt buộc xác thực người dùng (PCN-14) — cơ chế cụ thể chưa chọn. | Trước khi mở hệ thống ra ngoài máy cục bộ |
| 4 | Cách phục vụ bảng điều khiển ở bản chính thức (hiện chỉ chạy ở chế độ phát triển). | Trước khi triển khai chính thức |
| 5 | Thời gian phản hồi mục tiêu của dịch vụ dự đoán, thời gian lưu giữ nhật ký và báo cáo, cách sao lưu dữ liệu chưa được quy định. | Trước giai đoạn 2 |

---

## 10. Thuật ngữ

| Thuật ngữ | Giải thích |
| --- | --- |
| Mô hình | Kết quả của việc cho máy học từ dữ liệu quá khứ, dùng để dự đoán cho trường hợp mới. |
| Huấn luyện | Quá trình tạo ra mô hình từ dữ liệu. |
| Thuật toán | Phương pháp học mà mô hình dùng. Mỗi bài toán có ba thuật toán để chọn. |
| Tinh chỉnh tham số | Thử tự động một số cấu hình của thuật toán và chọn cấu hình cho kết quả tốt nhất. |
| Đặc trưng / đầu vào | Các mục thông tin về căn nhà mà mô hình dùng để dự đoán. |
| Đáp án | Giá trị mà mô hình cần dự đoán (giá bán, hoặc có cần cải tạo hay không). |
| Tập kiểm tra | Phần dữ liệu tách riêng, không dùng để huấn luyện, chỉ dùng để chấm điểm mô hình. |
| Phiên bản đang sử dụng | Phiên bản mô hình mà dịch vụ dự đoán dùng để trả lời yêu cầu. Mỗi mô hình có tối đa một phiên bản đang sử dụng. |
| Hồ sơ thống kê cơ sở | Bản tóm tắt thống kê (giá trị trung bình, độ phân tán, phân bố, tỉ lệ thiếu…) của dữ liệu đã dùng để huấn luyện một phiên bản mô hình. |
| Trôi dữ liệu đầu vào | Dữ liệu gửi đến để dự đoán có phân bố khác với dữ liệu lúc huấn luyện. Đo được ngay, không cần chờ kết quả thực tế. |
| Trôi kết quả dự đoán | Các kết quả mô hình trả ra có phân bố khác với lúc huấn luyện. Đo được ngay. |
| Suy giảm độ chính xác | Dự đoán sai lệch nhiều hơn so với kết quả thực tế. Là loại quan trọng nhất nhưng **luôn đến trễ**, vì phải chờ kết quả thực tế. |
| Kết quả thực tế | Giá bán thật, hoặc tình trạng thật của căn nhà. Được gửi đến sau thời điểm dự đoán. |
| Nhật ký dự đoán | Bản ghi lại mỗi lần dự đoán: đầu vào, kết quả, phiên bản mô hình. |
| Tác nhân mô phỏng | Thành phần tự động đóng vai người dùng, sinh yêu cầu dự đoán và báo kết quả thực tế. |
| Kịch bản thị trường | Cách tác nhân mô phỏng làm thay đổi dữ liệu có chủ đích, để kiểm chứng khả năng phát hiện trôi. |
| RMSE, MAE | Hai cách đo độ lệch trung bình giữa giá dự đoán và giá thật, tính bằng đô la. Càng nhỏ càng tốt. |
| R² (hệ số xác định) | Tỉ lệ biến động của giá bán mà mô hình giải thích được, tối đa là 1. Càng gần 1 càng tốt. |
| AUC | Khả năng xếp hạng đúng nhà cần cải tạo cao hơn nhà không cần, từ 0 đến 1. Đoán mò cho đúng 0,5. Không phụ thuộc ngưỡng quyết định hay tỉ lệ giữa hai lớp, nên được dùng làm tiêu chí quyết định. |
| F1, độ chính xác | Các cách đo chất lượng của dự đoán có/không tại một ngưỡng quyết định cố định. Chỉ dùng để báo cáo, vì chúng thay đổi theo tỉ lệ giữa hai lớp. |
| Vận hành học máy | Tập hợp các cách làm để đưa mô hình học máy vào sử dụng và duy trì chất lượng của nó một cách tự động, lặp lại được. |
