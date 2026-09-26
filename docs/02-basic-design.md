# 基本設計書 — Hệ thống MLOps dự đoán giá bất động sản

| Mục | Nội dung |
| --- | --- |
| Tên tài liệu | 基本設計書 (Tài liệu thiết kế cơ bản) |
| Hệ thống | Hệ thống MLOps dự đoán giá bất động sản |
| Phiên bản | 1.3 |
| Ngày lập | 24/09/2026 |
| Ngày sửa đổi | 25/09/2026 |
| Căn cứ | 要件定義書 phiên bản 1.3; tài liệu thiết kế hệ thống và các tài liệu thiết kế chi tiết của năm giai đoạn xây dựng, trạng thái ngày 24/09/2026 |

## Lịch sử sửa đổi

| Phiên bản | Ngày | Nội dung |
| --- | --- | --- |
| 1.0 | 24/09/2026 | Lập mới |
| 1.1 | 25/09/2026 | Theo 要件定義書 1.1. Chia vùng theo thời gian, rút mẫu ngẫu nhiên thay cho lấy dòng đầu tệp (3.2, 3.4, 3.4.1). Kiểm định chéo theo thời gian khi tinh chỉnh, ngưỡng quyết định, thuật toán mặc định, ghi truy vết (3.5). Biên độ ở cổng 2, chỉ số theo nhóm (3.6). Thẻ mô hình (3.7). Kiểm tra sau khi đưa vào sử dụng (3.8). Ghi nhật ký trước khi giám sát (3.10, 5.3). Quy trình tạo dữ liệu phản hồi (3.11). Nguồn của tác nhân mô phỏng (6). Chất lượng đầu vào, cảnh báo chủ động (7.2, 7.5). Kiểm thử tự động khi đưa mã nguồn lên (11.6). Cập nhật đối chiếu yêu cầu, vấn đề còn mở và hạn chế (13, 14). |
| 1.2 | 25/09/2026 | Theo 要件定義書 1.3:<br>• Dùng thuật ngữ tiếng Anh giống 要件定義書 (drift, train set, test set, simulation set, champion, pipeline…); giải thích thuật ngữ xem 要件定義書 mục 10.<br>• Viết lại câu chữ cho dễ hiểu; tách các đoạn dài thành từng bước.<br>• Mục 6: bảng scenario viết theo dạng câu hỏi kiểm chứng; scenario "Lạm phát giá rao" tách kỳ vọng riêng cho từng model.<br>Không thay đổi thiết kế. |
| 1.3 | 26/09/2026 | Mục 7.2: phân chia rõ việc giữa Evidently và thành phần dùng chung — Evidently tính mọi con số của bốn mục monitoring; thành phần dùng chung chuẩn bị data, chọn mốc, đọc kết quả qua adapter và xếp mức. Data quality của input đổi mốc so sánh sang mẫu training data sau data cleaning (7.1). Cập nhật 2.2, 7.4, 10.1, 11.5 cho khớp. |

---

## 1. Tổng quan

### 1.1. Mục đích của tài liệu

Tài liệu này mô tả **hệ thống được xây dựng như thế nào** để đáp ứng các yêu cầu trong 要件定義書: gồm những thành phần nào, mỗi thành phần làm gì, data đi qua chúng ra sao, và mỗi quyết định thiết kế được đưa ra vì lý do gì.

Các mã yêu cầu (NV-xx, CN-xx, PCN-xx) được dẫn lại trong nội dung; bảng đối chiếu đầy đủ ở mục 13. Các con số đo thực tế được ghi kèm ngày đo.

Tài liệu dùng cùng bộ thuật ngữ tiếng Anh với 要件定義書 (drift, train set, test set, champion…). Giải thích từng thuật ngữ xem 要件定義書 mục 10.

### 1.2. Nguyên tắc thiết kế

| STT | Nguyên tắc | Lý do |
| --- | --- | --- |
| 1 | Mỗi bước xử lý nặng chạy trong **một container riêng**. Orchestrator chỉ quyết định bước nào chạy, theo thứ tự nào; nó không chứa logic machine learning. | Từng bước có thể được thay bằng dịch vụ tương ứng trên cloud mà không ảnh hưởng các bước khác. Một bước hết RAM chỉ làm hỏng chính nó, không kéo sập orchestrator. |
| 2 | Storage **tương thích với Amazon S3 ngay từ đầu**. | Phần đọc/ghi data không phải viết lại khi chuyển lên cloud (PCN-16). |
| 3 | Điều phối, quản lý model, dự đoán và monitoring là **các thành phần tách biệt**, mỗi thành phần dùng một công cụ chuyên trách. | Không để một thành phần ôm quá nhiều việc; thay được từng phần khi chuyển đổi. |
| 4 | Mỗi bước **chạy lại được** mà không làm sai kết quả. Kết quả được ghi vào một vị trí xác định theo input; chạy lại thì ghi đè chính nó, hoặc bỏ qua nếu đã có. | PCN-07. |
| 5 | **Chỉ có một bản logic data cleaning**, và nó được đóng gói bên trong model. | NV-04. Hai bản chép tay của cùng một phép xử lý chắc chắn sẽ lệch nhau theo thời gian. |
| 6 | **Không pipeline nào chạy theo lịch** ở giai đoạn 1; mỗi pipeline chỉ chạy một lần tại một thời điểm. | NV-01, PCN-11. |
| 7 | **Test set luôn nằm sau train set trên trục thời gian**, và không phụ thuộc số dòng train. | NV-06, NV-08. Chia ngẫu nhiên cho điểm đẹp hơn thực tế mà không có lỗi nào báo ra. |
| 8 | **Alert tự đến tay operator.** Dashboard là nơi xem chi tiết và ra quyết định, không phải nơi duy nhất để biết có vấn đề. | NV-10. |

---

## 2. Kiến trúc hệ thống

### 2.1. Sơ đồ tổng thể (giai đoạn 1)

```
┌────────────────────┐
│     Dashboard      │  Trình duyệt web
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐                  ┌──────────────────────────────────┐
│ Backend trung gian │─────────────────▶│  Orchestrator (Airflow)          │
│   của dashboard    │                  │   • Training pipeline            │
│                    │──┐               │   • Simulation pipeline          │
└─────────┬──────────┘  │               │   • Monitoring pipeline          │
          │             │               │   • Feedback data pipeline       │
          │             │               └────────────────┬─────────────────┘
          │             │                                │ chạy từng bước
          │             │                                ▼ trong container riêng
          │             │               ┌──────────────────────────────────┐
          │             └──────────────▶│  Quản lý model (MLflow)          │
          │                             └────────────────┬─────────────────┘
          │                                              │
          ▼                                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                  Object storage (MinIO)                                  │
│  raw data · working copy · data đã chuẩn bị · file model                 │
│  baseline profile · prediction log · ground truth · báo cáo              │
└──────────────────────────────────────────────────────────────────────────┘
          ▲ ghi log                                      ▲ đọc log
          │                                              │
┌─────────┴──────────┐   ┌────────────────────┐   ┌──────┴─────────────────┐
│  Simulation agent  │──▶│ Prediction service │   │  Bước monitoring       │
│                    │   │                    │   │  (Evidently)           │
└────────────────────┘   └─────────▲──────────┘   └────────────────────────┘
                                   │
                                   └── bước deploy yêu cầu reload model
```

PostgreSQL (không vẽ trong sơ đồ) lưu data quản lý của Airflow và của MLflow.

Bộ lưu metric và alert (Prometheus, Grafana; mục 7.5) cũng không vẽ trong sơ đồ. Prediction service, bước monitoring và training pipeline gửi metric vào đó; từ đó alert được gửi ra kênh nhắn tin.

### 2.2. Danh sách thành phần

| Thành phần | Vai trò | Sản phẩm sử dụng |
| --- | --- | --- |
| Dashboard | Giao diện web để operator thao tác với toàn bộ hệ thống (mục 8) | Ứng dụng web chạy trên trình duyệt. Hiện chạy ở chế độ development; cách chạy bản chính thức chưa chọn (mục 14). |
| Backend trung gian | Nhận thao tác từ dashboard, chuyển tới đúng thành phần phía sau, trả kết quả về. Giữ credentials của các thành phần phía sau. | Web service tự phát triển, chạy trong container |
| Orchestrator | Chạy bốn pipeline (mục 3), ghi log từng bước | Apache Airflow, chế độ chạy trên một máy |
| Các bước xử lý | Data ingestion, data quality check, data preparation, training, evaluation, registration, monitoring. Mỗi bước là một container riêng. | Docker |
| Quản lý model | Ghi lại mỗi lần train (cấu hình, metric, file model); quản lý model version và champion | MLflow Tracking, MLflow Model Registry |
| Object storage | Lưu mọi data và file của hệ thống (mục 10.1) | MinIO, tương thích Amazon S3 |
| Database quản lý | Lưu data quản lý của Airflow và của MLflow, **ở hai database riêng** trên cùng một máy chủ | PostgreSQL |
| Prediction service | Trả kết quả dự đoán cho cả hai bài toán; ghi prediction log; nhận ground truth (mục 5) | Web service tự phát triển, chạy trong container |
| Simulation agent | Sinh traffic và ground truth theo scenario (mục 6) | Thành phần tự phát triển, chạy trong container |
| Công cụ phát hiện drift | Tính mọi con số của bốn mục monitoring (data drift, prediction drift, performance drift, data quality của input); sinh báo cáo chi tiết. **Không** quyết định mức (mục 7.2). | Evidently |
| Bộ lưu metric theo thời gian | Lưu operational metric của prediction service, kết quả mỗi lần monitoring và mỗi lần train theo thời gian (PCN-27) | Prometheus, kèm Prometheus Pushgateway cho các bước chạy theo batch |
| Dashboard theo dõi và alert | Vẽ diễn biến metric; kiểm tra alert rule và gửi alert ra kênh nhắn tin (CN-46) | Grafana |
| Khởi động toàn hệ thống | Khởi động mọi thành phần trên một máy bằng một thao tác (PCN-24) | Docker Compose |

### 2.3. Phân tách trách nhiệm

**Hệ thống có hai web service riêng biệt, không được gộp làm một:**

- **Backend trung gian** không biết gì về model. Nó chỉ chuyển thao tác của operator tới Airflow, MLflow và MinIO, và yêu cầu prediction service reload model sau khi operator thao tác tay trên model version (mục 5.2).
- **Prediction service** không biết gì về dashboard. Nó chỉ nhận thông tin căn nhà và trả kết quả dự đoán.

Hai service này có tải, vòng đời và cách chuyển lên cloud hoàn toàn khác nhau (mục 12), nên phải tách ngay từ đầu.

**Vì sao cần backend trung gian**, thay vì cho dashboard gọi thẳng Airflow, MLflow và MinIO:

1. Credentials của các thành phần đó sẽ phải nằm trong trình duyệt, tức là lộ ra ngoài (PCN-13).
2. Mỗi thành phần phía sau sẽ phải tự mở quyền truy cập từ trình duyệt.
3. Mỗi lần thay một thành phần phía sau khi chuyển lên cloud, dashboard phải sửa theo. Có backend trung gian thì chỉ lớp đó phải sửa (PCN-17).

Các danh sách lựa chọn trên dashboard (thuật toán, scenario) được backend trung gian đọc thẳng từ thành phần xử lý dùng chung, không chép lại ở dashboard. Nhờ vậy hai nơi không thể lệch nhau.

Giao diện Grafana, giống giao diện Airflow, là công cụ chuyên dụng mà operator mở riêng khi cần; dashboard không gọi vào nó. Alert rule nằm trong file cấu hình của Grafana, được lưu cùng source code chứ không tạo bằng tay trên giao diện. Nhờ vậy cấu hình alert cũng được quản lý phiên bản và được kiểm tra tự động (mục 11.6).

### 2.4. Thành phần xử lý data dùng chung

Mọi hiểu biết về dataset được đặt trong **một thành phần phần mềm dùng chung duy nhất**: danh sách cột, kiểu dữ liệu, khoảng giá trị hợp lệ, cách data cleaning, cách chia set theo thời gian, cách chọn feature theo bài toán, danh sách thuật toán, các evaluation gate, các ngưỡng monitoring, quy ước vị trí lưu trữ, cách tính baseline profile. Các bước xử lý chỉ là lớp vỏ mỏng gọi vào thành phần này.

Thành phần dùng chung chia các phép xử lý thành **hai nhóm, với ranh giới cứng**:

| Nhóm | Ví dụ | Được dùng ở đâu | Lý do |
| --- | --- | --- | --- |
| **Xử lý theo từng cột** | Chuẩn hoá cách viết, đọc ngày tháng, kéo giá trị vô lý về khoảng hợp lệ | **Đóng gói cùng model**, nên chạy cả lúc train (tới 2 triệu dòng) lẫn lúc dự đoán (một căn nhà) | Đảm bảo data cleaning lúc train và lúc dự đoán giống hệt nhau (NV-04) |
| **Xử lý theo record** | Bỏ record trùng, bỏ record không có label, chia set, lấy mẫu | **Chỉ** ở bước data preparation cho training | Nếu một phép bỏ record lọt vào phần đóng gói cùng model, lúc train nó vẫn chạy đúng. Nhưng lúc dự đoán cho một căn nhà, nó có thể bỏ mất chính căn nhà đó, và service không còn gì để dự đoán — service sẽ lỗi (PCN-09). |

Hai nhóm nằm ở hai phần riêng của thành phần dùng chung. Phần xử lý theo record **không bao giờ** được gọi từ phần tạo model hay từ prediction service. Prediction service thậm chí không gọi phần xử lý theo từng cột: nó chỉ đưa raw data vào model, và model tự làm sạch.

---

## 3. Thiết kế pipeline

Orchestrator có **bốn pipeline**. Cả bốn chỉ chạy khi được yêu cầu, và mỗi pipeline chỉ chạy một lần tại một thời điểm.

| Pipeline | Ai khởi chạy | Mục |
| --- | --- | --- |
| Training pipeline (train và deploy) | Operator, từ màn Tổng quan | 3.1 – 3.8 |
| Simulation pipeline | Operator, từ màn Giám sát drift | 3.9 |
| Monitoring pipeline | Simulation pipeline, sau khi gửi xong traffic; hoặc gọi trực tiếp qua backend trung gian (dashboard không có nút riêng) | 3.10 |
| Feedback data pipeline | Operator, từ màn Data | 3.11 |

Cả bốn pipeline được bật sẵn ngay khi hệ thống khởi động. Lý do: nếu một pipeline bị tạm dừng trong orchestrator, lần chạy được yêu cầu sẽ nằm chờ mãi mà không có dấu hiệu nào cho biết vì sao. Sự cố này đã xảy ra thật ngày 21/09/2026.

### 3.1. Training pipeline

**Tham số khởi chạy (CN-04, CN-05):**

| Tham số | Giá trị | Mặc định |
| --- | --- | --- |
| Bài toán | Dự đoán giá bán, hoặc Dự đoán nhu cầu cải tạo | Bắt buộc chọn |
| Thuật toán | Một trong ba thuật toán của bài toán (mục 3.5) | Thuật toán mặc định của bài toán |
| Hyperparameter tuning | Có / Không | Không |
| Số dòng train | Số nguyên dương, hoặc toàn bộ. Là số dòng **lấy ngẫu nhiên từ train set**; không ảnh hưởng test set (mục 3.4). | Toàn bộ (dashboard luôn gửi giá trị cụ thể) |
| Xử lý lại data từ đầu | Có / Không | Không |
| Data version | Tên data version đã upload | Data version đầu tiên |

Backend trung gian từ chối ngay (không khởi chạy) nếu thuật toán không thuộc bài toán đã chọn, hoặc số dòng bằng 0 hay âm. Tên data version không được kiểm tra trước: data version không tồn tại thì chỉ bước data ingestion bị lỗi.

**Trình tự:**

```
Ingestion → Quality check → Preparation → Training → Evaluation → Rẽ nhánh ─┬─ Registration → Deploy
                                                                            └─ Dừng (không deploy)
```

| STT | Bước | Nội dung | Output |
| --- | --- | --- | --- |
| 1 | Data ingestion | Mục 3.2 | Working copy dạng Parquet, split point, data ID |
| 2 | Data quality check | Mục 3.3 | Báo cáo chất lượng |
| 3 | Data preparation | Mục 3.4 | Train set, test set |
| 4 | Training | Mục 3.5 | Một run trong MLflow |
| 5 | Evaluation | Mục 3.6 | Đạt / Không đạt, metric trên test set |
| 6 | Rẽ nhánh | Đạt thì sang bước 7; không đạt thì sang bước 9 | — |
| 7 | Registration | Mục 3.7 | Champion mới, baseline profile, model card |
| 8 | Deploy | Mục 3.8 | Service dùng model version mới, đã qua smoke test |
| 9 | Dừng | Kết thúc, **giữ nguyên** champion hiện tại (CN-14) | — |

Mỗi lần chạy, một trong hai nhánh sau bước 6 bị bỏ qua. Đó là hành vi bình thường, không phải lỗi.

**Truyền data giữa các bước:** data lớn đi qua **object storage**, không đi qua orchestrator. Orchestrator chỉ chuyển các giá trị nhỏ giữa các bước: data ID, run ID, metric, số version.

### 3.2. Bước data ingestion

1. Tính **working copy ID** từ hai thứ: tên data version, và dấu hiệu thay đổi (ETag) mà storage gắn cho file raw data. Dùng ETag thay vì đọc và băm toàn bộ nội dung, vì storage đã tự cập nhật ETag khi file đổi. Không cần đọc 2 triệu dòng chỉ để biết data có đổi hay không.
2. Nếu vị trí của working copy ID đó chưa có working copy: đọc **toàn bộ** raw data của data version đã chọn và ghi thành working copy dạng Parquet tại đó. Nếu đã có thì bỏ qua.
3. Đọc **split point** trong hồ sơ của data version (mục 3.4.1). Data version tạo trước bản 1.1 của tài liệu này chưa có split point: bước này tính và lưu một lần, theo đúng quy tắc ở mục 3.4.1.
4. Tính **data ID** từ working copy ID, số dòng train, và random seed dùng khi lấy mẫu. Data ID được truyền cho các bước sau và ghi vào MLflow.

**Bước này không cắt bớt số dòng.** Bản 1.0 lấy N dòng đầu tệp, nhưng N dòng đầu tệp không phải một mẫu ngẫu nhiên. Nếu tệp được sắp theo ngày hay theo thành phố, model chỉ học một phần lệch của data mà không có lỗi nào báo ra. Hạn chế "mã bưu chính luôn bị coi là drift" của bản 1.0 (mục 14.2) là một biểu hiện của việc này. Việc giới hạn số dòng được chuyển sang bước data preparation, dưới dạng lấy mẫu ngẫu nhiên trong train set (mục 3.4).

**Số dòng và random seed bắt buộc nằm trong data ID** (PCN-02). Thiếu chúng, một lần chạy 200.000 dòng có thể dùng nhầm kết quả của lần chạy toàn bộ dòng. Sai kiểu này không báo lỗi: model được train trên một tập khác với tập người chạy tưởng.

### 3.3. Bước data quality check

Vai trò của bước này là **đo và báo cáo**, không phải chặn data bẩn. Dataset cố tình chứa 8 loại lỗi; đặt ngưỡng chặt thì mọi lần chạy đều bị chặn.

Pipeline **chỉ dừng** trong đúng ba trường hợp data không dùng được:

1. Thiếu cột so với danh sách cột quy định.
2. Hơn 50% label bị missing. Với bài toán cải tạo, kiểm tra trên cột dùng để tạo label (tình trạng nhà).
3. Không có dòng nào.

Mọi thứ khác — tỉ lệ missing từng cột, số giá trị ngoài khoảng hợp lệ, số mã bưu chính sai định dạng, số record trùng — chỉ được **đếm và ghi vào báo cáo chất lượng**. Các bước sau sẽ xử lý chúng.

### 3.4. Bước data preparation

**Dùng lại kết quả (CN-09, PCN-02).** Kết quả data preparation được lưu tại vị trí xác định theo **data ID và bài toán**. Khi bắt đầu bước này, nếu vị trí đó đã có đủ train set và test set, và operator không chọn "Xử lý lại data từ đầu", thì bước này được bỏ qua.

Bài toán phải nằm trong vị trí lưu, vì hai bài toán dùng chung data ID nhưng kết quả data preparation khác nhau (label khác nhau, record bị bỏ vì thiếu label cũng khác nhau). Nếu dùng chung một vị trí, bài toán này sẽ âm thầm dùng kết quả của bài toán kia.

**Các việc bước này làm:**

1. Với bài toán cải tạo: tạo cột **Cần cải tạo** từ cột tình trạng nhà (要件定義書 mục 6.2). Tình trạng nhà được chuẩn hoá cách viết trước; giá trị trống hoặc không đọc được thì để label trống — không đoán. Feedback record (mục 3.11) đã có sẵn label thì dùng thẳng.
2. Bỏ record trùng mã bất động sản, giữ record đầu tiên. **Bỏ trùng trước khi chia set**, để một căn nhà không thể vừa nằm ở train set vừa nằm ở test set.
3. Bỏ record không có label.
4. Xếp mỗi record vào một trong ba set theo split point của data version (mục 3.4.1).
5. Nếu operator giới hạn số dòng: lấy ngẫu nhiên đúng số dòng đó từ train set, với random seed cố định (PCN-21). Test set giữ nguyên.
6. Lưu train set và test set. Simulation set không được lưu vào kết quả data preparation.

Để vừa RAM khi số dòng nhỏ (PCN-05), bước này đọc data hai lượt. Lượt đầu chỉ đọc mã bất động sản, ngày đăng bán, nguồn record và thời điểm dự đoán, để xác định record nào được chọn. Lượt sau chỉ đọc đầy đủ những record được chọn.

**Bước này không làm sạch từng cột.** Kết quả data preparation vẫn ở dạng raw: vẫn còn "$450,000", vẫn còn "NEW YORK", vẫn còn mã bưu chính 4 chữ số. Data cleaning do phần xử lý đóng gói cùng model đảm nhận (mục 4). Nếu bước này làm sạch rồi mới lưu, model sẽ học trên data đã sạch, trong khi prediction service lại nhận raw data — đúng loại sai lệch mà cả thiết kế này dựng lên để tránh (NV-04). "Data preparation" ở đây chỉ có nghĩa là **đã xử lý theo record và đã chia set**, không có nghĩa là "đã làm sạch".

#### 3.4.1. Chia set theo thời gian

```
 ngày đăng bán ─────────────────────────────────────────────────────────────────▶
 ◄──────────────── Train set ────────────────►◄───── Test set ─────►◄─ Simulation set ─►
                                             T1                     T2            mới nhất
```

| Set | Gồm | Ai dùng |
| --- | --- | --- |
| Train set | Record đăng bán trước T1 | Bước training (có thể lấy mẫu bớt); làm mốc so sánh cho monitoring (mục 7.1) |
| Test set | Record đăng bán từ T1 đến trước T2 | Bước evaluation, gate 2, mốc metric cho monitoring |
| Simulation set | Record đăng bán từ T2 trở đi | Chỉ simulation agent (mục 6) |

**Cách đặt split point.** Split point được tính **một lần** khi data version được tạo, lưu trong hồ sơ của data version (mục 10.1), và không bao giờ tính lại:

- T2 được đặt sao cho simulation set có khoảng 20.000 record, nhưng không quá 10% số record có ngày đăng bán.
- T1 được đặt sao cho test set chiếm khoảng 20% số record có ngày đăng bán trước T2.
- Ngày được đọc bằng đúng quy tắc đọc ngày của phần data cleaning (mục 4.2), để "ngày" khi chia set và "ngày" model nhìn thấy là một.

Vì split point không phụ thuộc số dòng train, mọi lần chạy trên cùng một data version có **cùng một test set** (NV-06). Bản 1.0 chia ngẫu nhiên 80/20 *sau khi* đã cắt số dòng, nên lần chạy 200.000 dòng và lần chạy toàn bộ có hai test set khác nhau. Tệ hơn, test set của lần chạy mới có thể chứa những căn nhà champion đã học, làm gate 2 so sánh không công bằng.

**Record không có ngày đăng bán** (khoảng 8%) không đặt được lên trục thời gian, và hệ thống không đoán ngày (要件定義書 mục 6.5). Chúng được xếp vào train set hoặc test set bằng một phép hash cố định trên mã bất động sản, tỉ lệ khoảng 80/20, và không bao giờ vào simulation set. Nhờ vậy test set cũng có khoảng 8% record thiếu ngày, giống traffic thật, và đo được model xử lý giá trị missing này tốt đến đâu.

**Feedback record** (mục 3.11) được xếp set theo **thời điểm dự đoán**, không theo ngày đăng bán. Thời điểm dự đoán là lúc căn nhà thật sự đi vào hệ thống, và luôn nằm sau mọi data gốc.

**Vì sao chia theo thời gian (NV-08).** Khi được deploy, model dự đoán những căn nhà đăng bán *sau* toàn bộ data nó đã học. Nếu chia ngẫu nhiên, với mỗi căn nhà trong test set, train set có hàng nghìn căn đăng cùng tháng, và cả những tháng sau đó. Model biết sẵn mặt bằng giá lúc đó — điều không bao giờ có khi dùng thật (temporal leakage). Metric trên test set vì vậy đẹp hơn thực tế.

Sai lệch này đặc biệt lớn với các thuật toán dạng cây (XGBoost, Random Forest): chúng không dự đoán được mức giá cao hơn những gì đã học, và chia ngẫu nhiên che mất điểm yếu đó. Trên một dataset mô phỏng đơn giản có giá tăng 20% mỗi năm (25/09/2026), chia ngẫu nhiên báo sai số thấp hơn sai số khi dùng thật khoảng 1,5 lần; chia theo thời gian chỉ lệch khoảng 1,1 lần. Chưa đo trên dataset của hệ thống (mục 14.1).

### 3.5. Bước training

**Thuật toán:**

| Bài toán | Thuật toán có thể chọn | Mặc định |
| --- | --- | --- |
| Dự đoán giá bán | Ridge Regression; XGBoost; Random Forest | XGBoost |
| Dự đoán nhu cầu cải tạo | XGBoost; SVM; Random Forest | XGBoost |

Bản 1.0 dùng Ridge Regression làm mặc định cho bài toán giá bán. Nhưng Ridge chỉ đạt R² 0,68 khi đo trên 48.000 dòng (xem dưới), thấp hơn ngưỡng 0,75 của gate 1. Tức là operator chạy với lựa chọn mặc định sẽ luôn nhận "không đạt". Ridge được giữ lại làm **baseline model** — thước đo xem các thuật toán phức tạp hơn có thật sự đáng dùng không. Thuật toán mặc định phải được xác nhận lại bằng số đo theo cách chia set mới (mục 14.1).

SVM tự nó không trả ra xác suất, trong khi evaluation gate của bài toán cải tạo cần xác suất để tính AUC. Vì vậy SVM được bọc thêm một bước hiệu chỉnh xác suất (calibration).

**Hyperparameter tuning (CN-10, PCN-06).** Khi bật, hệ thống làm như sau:

1. Thử mọi tổ hợp trong một lưới hyperparameter nhỏ (tối đa 8 tổ hợp mỗi thuật toán).
2. Chấm mỗi tổ hợp bằng **time-based cross-validation** 5 phần trên train set. Data được sắp theo ngày đăng bán (feedback record theo thời điểm dự đoán). Ở mỗi phần, data dùng để chấm luôn nằm sau data dùng để học (NV-08). Record không có ngày luôn nằm ở phía data dùng để học.
3. Giữ tổ hợp tốt nhất, chọn theo **đúng metric mà evaluation gate và monitoring dùng**: RMSE cho bài toán giá bán, AUC cho bài toán cải tạo. Nhờ vậy "tốt nhất khi tuning" và "tốt nhất khi evaluation" là cùng một thước đo.

Cross-validation ngẫu nhiên bị loại vì cùng lý do ở mục 3.4.1: nó ưu tiên những tổ hợp học thuộc mặt bằng giá của từng tháng, rồi kém đi khi gặp tháng mới. Khi tắt tuning, thuật toán dùng bộ hyperparameter cố định sẵn. Các bước sau không cần biết có tuning hay không.

**Không đổi thang đo của giá.** Model dự đoán giá được train trực tiếp trên giá bán tính bằng đô la. Thiết kế ban đầu định train trên log của giá để giảm độ lệch phân bố. Nhưng đo trên 48.000 dòng thật cho thấy điều ngược lại: khi quy đổi ngược từ log về đô la, sai số ở nhóm nhà giá cao bị phóng đại theo cấp số nhân. Ridge ra R² âm (−0,40) và dự đoán một căn nhà giá 28,3 triệu đô, trong khi giá thật cao nhất chỉ là 2,39 triệu đô. Bỏ phép biến đổi này thì Ridge đạt R² 0,68, còn các thuật toán dạng cây không đổi.

**Decision threshold của bài toán cải tạo (CN-43).** Sau khi đã có bộ hyperparameter:

1. Tách 20% cuối (theo thời gian) của train set làm phần chọn threshold.
2. Train tạm trên 80% đầu, lấy xác suất trên 20% cuối.
3. Chọn **threshold cao nhất mà vẫn đạt recall ít nhất 70%**.
4. Train model cuối cùng trên toàn bộ train set.

Threshold được chọn trên train set, không trên test set: nếu dùng test set để chọn bất cứ thứ gì, nó không còn là thước đo khách quan. Threshold được lưu **bên trong model**, giống logic data cleaning: model trả ra cả xác suất lẫn câu trả lời có/không, và prediction service không cần biết threshold là bao nhiêu.

**Những gì được ghi vào MLflow:**

- thuật toán và hyperparameter;
- data ID và split point đã dùng; random seed;
- commit hash của source code, digest của container image (NV-09, PCN-26);
- decision threshold (bài toán cải tạo);
- metric trên train set;
- **model hoàn chỉnh**, gồm toàn bộ phần xử lý data (mục 4) và bộ dự đoán, lưu thành một khối.

Nhờ vậy model trong MLflow **tự chứa logic data cleaning** (CN-10): prediction service chỉ cần đưa raw data vào.

Commit hash được ghi vào container image lúc build (mục 11.4). Digest của image do orchestrator truyền vào khi chạy bước. Image được build từ source code còn thay đổi chưa commit thì commit hash được gắn thêm dấu "chưa commit", để không ai tưởng nhầm là truy ngược được.

### 3.6. Bước evaluation

Load model vừa train, dự đoán trên test set, tính các metric và ghi vào cùng run trong MLflow.

| Bài toán | Metric được tính |
| --- | --- |
| Dự đoán giá bán | RMSE, MAE, R² (đơn vị đô la) |
| Dự đoán nhu cầu cải tạo | AUC, F1, precision |

Model mới phải qua **cả hai evaluation gate** (CN-11, NV-03):

| Gate | Dự đoán giá bán | Dự đoán nhu cầu cải tạo | Mục đích |
| --- | --- | --- | --- |
| 1. Ngưỡng tối thiểu | R² ≥ 0,75 | AUC ≥ 0,55 | Chặn model kém, kể cả model đoán mò (PCN-22) |
| 2. Tốt hơn champion đủ nhiều | RMSE thấp hơn ít nhất 1% | AUC cao hơn ít nhất 0,005 | Không thay một model tốt bằng một model kém hơn chỉ vì model mới vượt ngưỡng; không thay model vì một chênh lệch nhỏ chỉ là may rủi. |

Gate 2 so hai model trên **cùng test set đã lưu**. Nếu chưa có champion, chỉ áp dụng gate 1. Metric của cả hai model được ghi vào cùng run, để sau này đọc lại được vì sao một model bị chặn.

Bước evaluation còn đếm số căn nhà trong test set có mặt trong train set của champion, và ghi con số này cùng kết quả.

- Nếu hai model dùng cùng một data version, hoặc model mới dùng feedback data version tạo từ data version của champion (mục 3.11), con số này bằng 0.
- Nếu khác 0: champion đã học một phần test set, nên gate 2 nghiêng về phía champion. Kết quả vẫn được ghi, kèm cảnh báo trong run.

**Metric theo nhóm (CN-45).** Ngoài metric chung, bước evaluation tính metric theo từng thành phố và từng loại bất động sản (chỉ với nhóm có ít nhất 200 record trong test set), rồi ghi vào MLflow dưới dạng bảng. Metric theo nhóm không tham gia evaluation gate.

**Vì sao bài toán cải tạo dùng AUC, không dùng F1.** Thiết kế ban đầu dùng ngưỡng F1 ≥ 0,70. Đo trên data thật cho thấy F1 hỏng theo hai hướng ngược nhau:

- **Cho model đoán mò lọt qua:** trên một bài toán có 56% lớp "có", một model lúc nào cũng trả lời "có" đạt F1 0,72 — vượt ngưỡng mà không hề nhìn data.
- **Chặn nhầm model tốt:** trên bài toán cải tạo (25% lớp "có"), một model tốt với AUC 0,71 chỉ đạt F1 0,16, vì ở threshold mặc định 0,5 nó hiếm khi trả lời "có".

Nguyên nhân chung: F1 phụ thuộc vào decision threshold và tỉ lệ giữa hai lớp, nên một ngưỡng F1 cố định chỉ đúng với đúng một phân bố data. AUC không phụ thuộc hai thứ đó, và mọi model đoán mò đều cho AUC đúng 0,5. F1 và precision vẫn được tính để báo cáo, **tại decision threshold của model** (mục 3.5), cùng với recall.

**Bước evaluation luôn kết thúc bình thường**, kể cả khi model không đạt. Kết quả đạt/không đạt được chuyển cho bước rẽ nhánh quyết định. "Không đạt" là một kết quả hợp lệ, không phải lỗi của pipeline.

### 3.7. Bước registration

1. Đăng ký model vào MLflow Model Registry, nhận số version mới.
2. Ghi lại version đang mang alias "champion" (nếu có), để bước deploy rollback được (mục 3.8). Sau đó gắn alias "champion" vào version mới. Mỗi model có tối đa một version mang alias này. Hệ thống dùng alias thay cho cơ chế "stage" cũ của MLflow, vì cơ chế cũ đã bị MLflow ngừng hỗ trợ.
3. Tính **baseline profile** (mục 7.1) từ train set đã dùng, lưu tại vị trí xác định theo tên model và số version.
4. Tạo **model card** (CN-12): một file văn bản ngắn gồm bài toán, thuật toán, data version và split point, metric chung và theo nhóm, decision threshold (bài toán cải tạo), các cột bị loại khỏi feature, và các hạn chế đã biết của bài toán (lấy từ một danh sách cố định trong thành phần dùng chung). Model card được lưu cùng run trong MLflow.

Baseline profile được tính từ **train set**, không phải test set, vì monitoring so traffic thực tế với data mà model đã học.

Mỗi bài toán là một model đăng ký riêng trong MLflow. Tên model được suy ra từ bài toán, người chạy không tự đặt. Nhờ vậy không thể vô tình ghi một model phân loại vào chỗ của model dự đoán giá.

### 3.8. Bước deploy

1. Gửi yêu cầu reload model tới prediction service (mục 5.2).
2. **Smoke test** (CN-13): version mà service báo đã load phải trùng với version vừa đăng ký; và service phải trả được kết quả cho một record mẫu lấy từ test set, gửi ở dạng raw.
3. Nếu smoke test không đạt: **rollback** — chuyển alias "champion" về version đã ghi lại ở bước registration (hoặc gỡ alias nếu trước đó chưa có champion), yêu cầu service reload lần nữa, rồi đánh dấu lần chạy thất bại và gửi alert (mục 7.5).

**Vì sao cần smoke test.** Yêu cầu reload có thể trả về thành công trong khi service vẫn đang dùng model cũ — ví dụ service không load được model mới vì môi trường phần mềm bị lệch (mục 11.4). Nếu không có smoke test, pipeline báo thành công, MLflow ghi version mới là champion, còn service thực tế vẫn trả lời bằng version cũ.

Bước này **không có container riêng**: nó chỉ gửi vài request, nên dùng chức năng có sẵn của Airflow. Đóng gói cả một container chỉ để gửi request là thừa. Ngược lại, bước registration vẫn có container riêng, vì nó phải tính baseline profile trên toàn bộ train set.

### 3.9. Simulation pipeline

| Tham số | Giá trị | Mặc định |
| --- | --- | --- |
| Scenario | Một trong năm scenario (mục 6) | Không thay đổi |
| Bài toán | Lấy theo model đang xem trên màn Giám sát drift | — |
| Số request | 1 đến 5.000 | 300 |

| STT | Bước | Nội dung |
| --- | --- | --- |
| 1 | Gửi traffic | Chạy simulation agent trong container riêng (mục 6) |
| 2 | Tính monitoring | Chạy monitoring pipeline (mục 3.10) và **chờ nó xong** |

Hai bước được nối ở tầng orchestrator chứ không nối ở dashboard. Nhờ vậy, kể cả khi operator đóng trình duyệt giữa chừng, monitoring vẫn được tính (CN-28). Vì bước 2 chờ monitoring pipeline xong, trạng thái của một lần simulation trả lời trọn câu hỏi "đã xong hết chưa". Đo ngày 22/09/2026: cả chuỗi mất khoảng 40 giây (18,5 giây gửi traffic, 20,6 giây tính monitoring).

Tại một thời điểm chỉ có một lần simulation chạy. Nếu traffic của hai scenario trộn vào cùng một khoảng thời gian, báo cáo monitoring không biết kết quả thuộc scenario nào.

### 3.10. Monitoring pipeline

Trước khi tính, pipeline gửi yêu cầu **flush** prediction log tới prediction service (mục 5.1, 5.3) và chờ phản hồi, để traffic vừa gửi đã nằm trong storage. Nếu flush thất bại, monitoring vẫn chạy, nhưng bản tóm tắt ghi rõ việc này (mục 7.3) thay vì im lặng tính trên data thiếu.

Monitoring pipeline có **một bước cho mỗi model**, hai bước chạy song song. Mỗi bước là một container tự làm trọn việc: đọc data trong khoảng thời gian xét, so sánh, ghi báo cáo (mục 7).

Không tách thành ba bước riêng "thu thập — so sánh — xuất báo cáo". Data lớn không đi qua orchestrator (mục 3.1), nên nếu tách, mỗi bước lại phải tự đọc toàn bộ data từ đầu — ba lần đọc cho một lần chạy mà không được gì thêm.

Monitoring pipeline **không** nằm trong training pipeline. Nó đo traffic tích luỹ theo thời gian, không đo kết quả của lần train vừa xong. Nếu chạy ngay sau bước deploy, model mới chưa phục vụ request nào và báo cáo sẽ rỗng.

Monitoring pipeline **không tự retrain** (NV-02). Sau khi ghi báo cáo, mỗi bước monitoring gửi kết quả sang bộ lưu metric (mục 7.5). Ở đó, alert rule quyết định có gửi alert hay không.

### 3.11. Feedback data pipeline

Pipeline này thực hiện CN-42: biến những căn nhà đã được dự đoán và đã có ground truth thành training data, để lần retrain sau học được thị trường mới (要件定義書 mục 3.2).

| Tham số | Giá trị | Mặc định |
| --- | --- | --- |
| Bài toán | Dự đoán giá bán, hoặc Dự đoán nhu cầu cải tạo | Bắt buộc chọn |
| Data version nguồn | Tên data version đã có | Data version mà champion của bài toán đã học |
| Khoảng thời gian | Khoảng thời điểm dự đoán cần lấy | 30 ngày gần nhất |
| Tên data version mới | Theo quy tắc tên ở CN-01; tên đã tồn tại bị từ chối (CN-02) | Bắt buộc nhập |

| STT | Bước | Nội dung |
| --- | --- | --- |
| 1 | Ghép | Đọc prediction log và ground truth của bài toán trong khoảng thời gian đã chọn; ghép theo request ID. Chỉ giữ những lần dự đoán đã có ground truth. |
| 2 | Tạo feedback record | Mỗi cặp ghép được thành một record:<br>• raw input đúng như đã gửi;<br>• ground truth ghi vào cột label của bài toán (giá bán cuối cùng, hoặc cột Cần cải tạo);<br>• nguồn record = "Feedback";<br>• thời điểm dự đoán.<br>Cột không có trong input thì để trống. Một mã bất động sản xuất hiện nhiều lần thì giữ lần dự đoán muộn nhất. |
| 3 | Kiểm tra số lượng | Dưới 500 feedback record thì dừng và báo lý do: test set (bước 5) sẽ quá nhỏ để đáng tin. |
| 4 | Gộp | Data version mới = các feedback record + data của data version nguồn, **trừ những record có mã bất động sản trùng với feedback record**. |
| 5 | Đặt split point | • Test set = 20% feedback record có thời điểm dự đoán muộn nhất.<br>• Train set = toàn bộ train set và test set của data version nguồn, cộng 80% feedback record sớm hơn.<br>• Simulation set = simulation set của data version nguồn, trừ các căn đã thành feedback record. |
| 6 | Ghi | Ghi data dạng Parquet vào vùng raw data, kèm hồ sơ data version: nguồn gốc (data version nguồn, khoảng thời gian, số feedback record, số record bị thay thế) và các split point. |

**Vì sao test set là phần feedback mới nhất.** Model mới phải chứng minh nó dự đoán tốt **thị trường mới**, không chỉ thị trường cũ. Đồng thời, champion chưa từng học các feedback record, nên gate 2 so sánh công bằng (mục 3.6).

**Vì sao feedback record thay thế record gốc cùng mã.** Hai record của cùng một căn nhà với hai mức giá khác nhau (giá gốc và giá theo scenario) sẽ dạy model hai label mâu thuẫn. Hơn nữa, phép bỏ trùng giữ record đầu tiên (mục 4.7) có thể âm thầm giữ lại bản cũ.

Pipeline chạy trong container riêng, vì phải đọc và ghi lại toàn bộ data của data version nguồn. Tại một thời điểm chỉ có một lần chạy (PCN-11).

---

## 4. Thiết kế xử lý data đóng gói cùng model

### 4.1. Thứ tự xử lý

Mọi data đi vào model — dù hàng trăm nghìn dòng lúc train hay một căn nhà lúc dự đoán — đều đi qua đúng các bước sau, theo đúng thứ tự:

| STT | Bước | Nội dung |
| --- | --- | --- |
| 1 | Làm sạch từng cột | Áp quy tắc làm sạch theo loại của từng cột (mục 4.2). Cột không có trong danh sách cột quy định thì giữ nguyên; cột bị thiếu thì bỏ qua, không báo lỗi. |
| 2 | Kéo giá trị vô lý về khoảng hợp lệ (clip) | Giá trị nhỏ hơn giới hạn dưới được nâng lên bằng giới hạn dưới; lớn hơn giới hạn trên được hạ xuống bằng giới hạn trên (mục 4.3). Giá trị missing vẫn giữ là missing. |
| 3 | Tách ngày tháng | Ngày đăng bán được tách thành **năm** và **tháng**, rồi bỏ cột ngày gốc. |
| 4 | Chọn feature | Giữ đúng các cột feature của bài toán, theo thứ tự cố định. Cột bị loại theo 要件定義書 mục 6.3 bị bỏ đi, **kể cả khi người gọi gửi lên**. Cột feature mà người gọi không gửi thì được thêm vào với giá trị missing. |
| 5 | Impute và biến đổi | Mục 4.5 |
| 6 | Dự đoán | Bộ dự đoán của thuật toán đã chọn. Với bài toán cải tạo, áp decision threshold đã lưu (mục 3.5) để ra câu trả lời có/không, kèm xác suất. |

**Thứ tự này là bắt buộc, không phải tuỳ chọn.** Bước 1 phải đứng đầu:

- Nếu bước 2 chạy trước bước 1, giá tiền dạng "$450,000" chưa được đọc thành số sẽ bị coi là không hợp lệ và biến thành missing.
- Nếu bước 3 chạy trước bước 1, ngày đăng bán vẫn còn ở ba định dạng lẫn lộn. Một phần sẽ không đọc được và **âm thầm biến thành missing**, không có lỗi nào báo ra.

**Không bước nào ở trên được bỏ record** (PCN-09). Số record đầu ra luôn bằng số record đầu vào.

### 4.2. Quy tắc làm sạch theo loại cột

| Loại cột | Áp dụng cho | Quy tắc | Giá trị không đọc được |
| --- | --- | --- | --- |
| Category | Thành phố, bang, loại bất động sản, tình trạng nhà, phân loại mức giá | Chuyển về chữ thường; gạch dưới và gạch nối đổi thành dấu cách; nhiều dấu cách liền nhau gộp thành một; bỏ khoảng trắng đầu và cuối. Ví dụ "Multi-Family", "MULTI FAMILY" và cách viết nối hai từ bằng gạch dưới đều thành "multi family". | Chuỗi rỗng hoặc chỉ có khoảng trắng → missing |
| Có/không | Có hồ bơi, bán trong vòng 30 ngày | "Yes", "Y", "1", "True", "T" (không phân biệt hoa thường, bỏ khoảng trắng thừa) → Có. "No", "N", "0", "False", "F" → Không. | Mọi giá trị khác → missing |
| Ngày tháng | Ngày đăng bán | Chấp nhận ba định dạng: năm-tháng-ngày (2023-07-15); tháng/ngày/năm (07/15/2023); ngày-tháng viết tắt tiếng Anh-năm (15-Jul-2023). Định dạng có gạch chéo **luôn** hiểu là tháng trước, ngày sau. Thử lần lượt từng định dạng, không dùng cơ chế tự đoán định dạng. | Không khớp định dạng nào, hoặc ngày không tồn tại → missing |
| Tiền | Giá rao bán, giá bán cuối cùng | Bỏ ký hiệu đô la, dấu phẩy phân cách hàng nghìn và khoảng trắng, rồi đọc thành số. Giá trị đã là số thì giữ nguyên. | Không phải số hợp lệ → missing |
| Mã bưu chính | Mã bưu chính | Chỉ chấp nhận **đúng 5 chữ số**. Giữ nguyên số 0 ở đầu (ví dụ "02134"). **Không tự thêm số 0** vào mã 4 chữ số. | Sai định dạng (4 chữ số, 6 chữ số, có chữ cái…) → missing |
| Số | Các cột số còn lại | Giữ nguyên, chỉ kiểm tra khoảng hợp lệ ở bước 2 | — |

Thử lần lượt từng định dạng ngày được chọn thay cho cơ chế tự đoán định dạng vì hai lý do: nhanh hơn nhiều khi xử lý 2 triệu dòng, và không bao giờ nhầm ngày với tháng.

Việc không thêm số 0 vào mã bưu chính 4 chữ số là cố ý. Mã "2134" rất có thể là "02134" bị phần mềm bảng tính cắt mất số 0, nhưng cũng có thể là một lỗi khác. Đoán sai sẽ tạo ra data sai mà không ai biết; coi là missing thì bước data quality check đếm được và báo cáo (要件定義書 mục 6.5).

### 4.3. Khoảng giá trị hợp lệ

| Cột | Giới hạn dưới | Giới hạn trên |
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

Giới hạn trên của năm xây dựng là năm hiện tại tại thời điểm chạy, không phải một con số cố định.

Giá trị vô lý được **kéo về trong khoảng** thay vì bỏ record, vì hai lý do: prediction service không được phép bỏ record (PCN-09), và một căn nhà có số phòng ngủ ghi sai vẫn còn thông tin hữu ích ở các cột khác.

### 4.4. Giá trị category chuẩn

Sau khi làm sạch, các cột category có danh sách giá trị hợp lệ cố định (đã ở dạng chuẩn hoá):

| Cột | Giá trị hợp lệ |
| --- | --- |
| Loại bất động sản | single family (nhà riêng một hộ), condo (căn hộ chung cư), townhouse (nhà liền kề), multi family (nhà nhiều hộ), land (đất trống) |
| Tình trạng nhà | poor (kém), fair (trung bình), good (tốt), excellent (rất tốt) |
| Phân loại mức giá | low (thấp), medium (trung bình), high (cao), luxury (cao cấp) |

Thành phố và bang không có danh sách cố định.

### 4.5. Nhóm feature và xử lý giá trị lạ

| Nhóm | Gồm | Impute (điền giá trị missing) | Biến đổi |
| --- | --- | --- | --- |
| Số | Các cột số, các cột tiền được dùng làm feature, các cột có/không (Có → 1, Không → 0), năm đăng bán, tháng đăng bán | Trung vị của train set | Đưa về cùng thang đo (trung bình 0, độ lệch chuẩn 1) |
| Category | Thành phố, bang, mã bưu chính, loại bất động sản, và các cột category khác được dùng làm feature | Giá trị xuất hiện nhiều nhất trong train set | One-hot: mỗi giá trị thành một cột có/không riêng |

**Giá trị hiếm:** giá trị category chiếm dưới 1% train set được gộp chung vào một nhóm "hiếm".

**Giá trị chưa từng gặp:** khi dự đoán, một giá trị category chưa có trong train set (ví dụ một loại nhà mới trong scenario "Phân khúc mới") được xếp vào nhóm "hiếm" nếu có, hoặc được bỏ qua — **không gây lỗi** (PCN-08). Nếu thiết kế sai, đây là chỗ dễ làm prediction service ngừng hoạt động nhất.

### 4.6. Cột bị loại khỏi feature theo bài toán

Theo 要件定義書 mục 6.3. Việc loại được làm ở bước 4 của mục 4.1, tức là **bên trong model**: dù người gọi có gửi các cột bị loại, model cũng bỏ chúng đi trước khi dự đoán.

### 4.7. Thao tác theo record

Chỉ được làm ở bước data preparation (mục 3.4), không bao giờ làm bên trong model:

| Thao tác | Quy tắc | Kết quả trả về |
| --- | --- | --- |
| Bỏ record trùng | Các record cùng mã bất động sản: giữ record đầu tiên | Data sau khi bỏ, số record đã bỏ |
| Bỏ record không có label | Record thiếu label của bài toán đã chọn | Data sau khi bỏ, số record đã bỏ |

Sau mỗi thao tác, số thứ tự record được đánh lại từ đầu. Vì vậy muốn truy ngược một record về dòng trong data gốc thì phải dùng mã bất động sản, không dùng số thứ tự.

---

## 5. Thiết kế prediction service

### 5.1. Chức năng

Một service duy nhất phục vụ cả hai bài toán (CN-20).

| Chức năng | Input | Output | Yêu cầu |
| --- | --- | --- | --- |
| Dự đoán | Bài toán; thông tin **raw** của một căn nhà | Kết quả dự đoán, request ID, tên model và model version. Bài toán cải tạo trả thêm xác suất; câu trả lời có/không theo decision threshold của model. | CN-19, CN-43 |
| Nhận ground truth | Bài toán; một **batch** ground truth, mỗi phần tử gồm request ID, ngày đã dự đoán, giá trị thực tế | Số ground truth đã nhận | CN-23 |
| Reload model | — | Model nào đã load, version bao nhiêu | CN-13 |
| Trạng thái | — | Model nào đang được load, version bao nhiêu; số record prediction log đang chờ ghi và số đã phải bỏ | CN-24 |
| Flush prediction log | — | Số record đã ghi, số còn chờ; báo thất bại nếu không ghi được | CN-29 |
| Operational metric | — | Số request, số lỗi theo loại phản hồi, phân bố latency, số record prediction log đang chờ và đã bỏ — theo định dạng Prometheus đọc được | PCN-27 |

**Phản hồi khi có vấn đề:**

| Tình huống | Phản hồi |
| --- | --- |
| Bài toán chưa có model | Từ chối, báo "chưa sẵn sàng" (không phải lỗi hệ thống) |
| Bài toán không hợp lệ, hoặc data gửi lên không phải một record | Từ chối, báo data gửi sai |
| Record thiếu một số cột | **Không phải lỗi** — model tự impute (mục 4.5) |
| Model đã load nhưng dự đoán thất bại | Lỗi hệ thống |
| Batch ground truth rỗng | Từ chối, báo data gửi sai |

### 5.2. Load model

- Image của service **không chứa model**. Khi khởi động, service lấy version mang alias "champion" của **cả hai** model từ MLflow Model Registry và giữ trong RAM.
- **Thiếu model vẫn khởi động được** (CN-21). Load được model nào thì phục vụ model đó. Trạng thái của service là "ổn" khi load được ít nhất một model, "suy giảm" khi không load được model nào. Lý do: nếu từ chối khởi động, một Model Registry còn trống sẽ khiến service khởi động lại liên tục, và không thể dựng service trước khi có đủ model.
- Khi nhận yêu cầu reload, service lấy lại champion mới nhất của cả hai model và **thay model trong RAM**, không khởi động lại (CN-13). Phản hồi luôn kèm trạng thái, kể cả khi không load được model nào.
- Việc reload **cũng được backend trung gian yêu cầu** ngay sau khi operator chọn champion bằng tay hoặc xoá toàn bộ một model (CN-16, CN-18; mục 9.1), không chỉ từ bước deploy. Bản 1.0 thiếu điều này: sau khi chọn champion bằng tay, service vẫn trả lời bằng model cũ cho tới lần reload kế tiếp. Nghĩa là rollback — thao tác cần nhất khi có sự cố — không có tác dụng như operator tưởng.
- Prediction service chạy trong cùng môi trường phần mềm với lúc train (PCN-20, mục 11.4).

### 5.3. Prediction log

| Cột | Nội dung |
| --- | --- |
| Request ID | ID duy nhất cho mỗi lần dự đoán; dùng để ghép với ground truth |
| Thời điểm | Thời điểm dự đoán |
| Raw input | Đúng như người gọi gửi lên, chưa làm sạch |
| Kết quả dự đoán | |
| Xác suất | Chỉ có ở bài toán cải tạo. Cần vì monitoring chấm performance của bài toán này bằng AUC, mà AUC không tính được từ một câu trả lời có/không. |
| Tên model | |
| Model version | |

**Ghi theo batch, với ba quy tắc theo thứ tự ưu tiên** (PCN-04, PCN-10):

1. **Ghi log không bao giờ được làm chậm hay làm hỏng một lần dự đoán.** Record được đưa vào buffer trong RAM. Việc ghi xuống storage chạy ở background, khi buffer đủ **500 record** hoặc sau **30 giây**.
2. **Ghi thất bại thì giữ lại để thử lần sau.** Storage khởi động lại vài giây không được làm mất data monitoring.
3. **Buffer có giới hạn 5.000 record.** Vượt giới hạn thì bỏ record **cũ nhất** và đếm số đã bỏ; con số này hiện ở chức năng Trạng thái. Giới hạn tồn tại vì quy tắc 2: nếu storage hỏng lâu trong lúc simulation agent đang gửi traffic, giữ lại vô hạn sẽ làm hết RAM và service sẽ dừng.

Ngoài hai điều kiện ở quy tắc 1, buffer được ghi ngay khi có yêu cầu **flush** (mục 3.10). Yêu cầu flush chờ ghi xong rồi mới trả lời.

Mỗi lần ghi tạo một file, chia theo model và theo ngày. Phải ghi theo batch vì simulation agent gửi hàng nghìn request; ghi riêng từng lần sẽ tạo ra quá nhiều file nhỏ và làm bước monitoring đọc rất chậm.

### 5.4. Ground truth

- Nhận **theo batch**: một lần gửi thành một file, không phải một request cho mỗi căn nhà — cùng lý do với prediction log.
- Ground truth được lưu theo **ngày đã dự đoán** do bên gửi cung cấp, **không** theo ngày nhận. Có vậy nó mới nằm cùng partition với prediction log tương ứng để ghép được. Batch có nhiều ngày khác nhau thì ghi thành nhiều file, mỗi ngày một file.
- Bên gửi cung cấp ngày, thay vì để service tự tra từ request ID, vì service không lưu bảng tra như vậy. Dựng thêm một bảng tra chỉ để phục vụ việc ghép là thêm state vào một service đang cố giữ tối giản.
- Ghi thẳng xuống storage, không qua buffer: data đã được gom theo batch sẵn và tần suất thấp.

---

## 6. Thiết kế simulation agent

Simulation agent tạo traffic thật cho prediction service, thay cho cách giả lập drift bằng cách cắt dataset gốc. Nó chạy trong container riêng, do simulation pipeline khởi chạy (mục 3.9).

**Mỗi lần chạy:**

1. Lấy nguồn là **simulation set** (mục 3.4.1) của data version mà champion đã học, **bỏ ra** mọi mã bất động sản có trong train set của champion (truy ngược giống mục 7.1). Bản 1.0 lấy 20.000 căn mới nhất của cả tệp. Khi model được train trên toàn bộ data, khoảng 80% số căn đó nằm trong train set, và scenario "Không thay đổi" chỉ đo khả năng nhớ bài của model, chứ không đo khả năng dự đoán.
2. Lấy ngẫu nhiên số căn nhà theo yêu cầu. Mỗi lần chạy lấy một mẫu khác nhau, để khi chạy lặp lại một scenario thì mẫu được mở rộng, chứ không gửi trùng các căn cũ.
3. Biến đổi data theo scenario (bảng dưới).
4. Gửi từng request dự đoán.
5. Gửi ground truth của các căn nhà đó theo batch, kèm ngày đã dự đoán (mục 5.4). Mặc định gửi ground truth cho mọi request.

Dự đoán và ground truth là **hai lần gọi tách rời**, đúng như ngoài đời: lúc hỏi giá, chưa ai biết căn nhà sẽ bán được bao nhiêu. Thiết kế ban đầu định cho simulation agent chờ "N ngày mô phỏng" rồi mới gửi ground truth. Cách này bị bỏ vì độ trễ thật không thể minh hoạ được, còn độ trễ giữa hai lần gọi vẫn thể hiện được mà không cần bộ đếm giả lập.

**Năm scenario (CN-27):**

| Scenario | Biến đổi input | Ground truth gửi về | Câu hỏi cần kiểm chứng (要件定義書 mục 4.5) |
| --- | --- | --- | --- |
| Không thay đổi | Không | Giá trị thật | Khi data không có gì thay đổi, hệ thống **có báo động nhầm hay không**? |
| Lạm phát giá rao | Giá rao bán × 1,2 | Giá trị thật (không đổi) | • Model giá bán (không dùng giá rao làm feature): hệ thống **có báo động nhầm hay không**?<br>• Model cải tạo (có dùng giá rao làm feature): hệ thống **có phát hiện được data drift hay không**? |
| Thị trường tăng giá | Giá rao bán × 1,2 | Giá bán thật × 1,2 | Khi input không đổi nhưng giá thật đã tăng, hệ thống **có phát hiện được performance drift hay không**? |
| Dịch chuyển thị trường | Dồn thành phố về một, hai thành phố | Giá trị thật | Khi giao dịch dồn về vài thành phố, hệ thống **có phát hiện được data drift hay không**? |
| Phân khúc mới | Loại bất động sản đổi thành giá trị chưa từng thấy | Giá trị thật | Khi gặp loại bất động sản chưa từng thấy, prediction service **có bị lỗi hay không**? |

**Kết quả đo thực tế với model dự đoán giá (20/09/2026).** Đo theo cách chia set và nguồn của bản 1.0; phải đo lại sau khi áp dụng mục 3.4.1 và nguồn mới ở trên.

| Scenario | Data drift | Prediction drift | Performance drift | Kết luận |
| --- | --- | --- | --- | --- |
| Không thay đổi | Ổn | Ổn | Ổn | Không báo động nhầm. |
| Lạm phát giá rao | Ổn | Ổn | Ổn | Giống hệt "Không thay đổi". Giá rao bán **không phải feature** của model giá bán (要件定義書 mục 6.3), nên thay đổi ở cột này không chạm tới model. Thay đổi ở một cột model không dùng thì không phải drift. |
| Thị trường tăng giá | Ổn | Ổn | **Cao** (RMSE tăng 2,24 lần) | **Performance sụp đổ trong khi input không hề đổi.** Đây là bằng chứng mạnh nhất cho việc báo cáo ba loại drift riêng rẽ: nếu chỉ nhìn data drift, scenario này lọt qua như không có gì xảy ra. |
| Dịch chuyển thị trường | Cảnh báo | Cao | Cao | Scenario duy nhất thật sự kiểm tra được data drift, vì thành phố là một feature của model. |
| Phân khúc mới | Cảnh báo | Ổn | Cảnh báo | Prediction service **không bị lỗi** với giá trị lạ — đây là điều kiện chính của scenario này. |

Chưa có số đo cho model cải tạo. Với scenario "Lạm phát giá rao", model cải tạo được kỳ vọng ra **data drift**, vì giá rao là feature mạnh nhất của nó. Cần đo cùng lúc với lần đo lại ở trên (mục 14.1).

---

## 7. Thiết kế monitoring

### 7.1. Mốc so sánh

Monitoring so traffic thực tế với **một mốc gắn với champion hiện tại**, không gắn với một dataset cố định. Nhờ vậy không bao giờ xảy ra chuyện so version mới với mốc của một version cũ. Có bốn mốc, cho bốn mục monitoring:

| Mốc | Nội dung | Nguồn |
| --- | --- | --- |
| Mẫu training data | Tối đa 10.000 dòng lấy ngẫu nhiên (random seed cố định, chạy lại vẫn ra như cũ) từ train set của champion | Truy ngược: model version → run đã tạo ra nó → data ID đã dùng → train set đã lưu |
| Phân bố kết quả dự đoán lúc train | Kết quả mà chính champion dự đoán trên mẫu training data ở trên | Chạy lại model lúc monitoring, vì lúc train không lưu phân bố này |
| Metric trên test set | Các metric mà bước evaluation (mục 3.6) đã ghi cho champion | MLflow |
| Mẫu training data sau data cleaning | Chính mẫu training data ở trên, cho đi qua các bước 1–3 của mục 4.1 lấy từ champion | Tính lại lúc monitoring, dùng làm mốc cho data quality của input |

**Vì sao mốc của performance là metric trên test set, không phải trên train set.** Test set là mốc duy nhất đo trên data model chưa từng thấy — đúng bản chất của traffic thực tế. Metric trên train set đo trên chính những dòng model đã học, nên model càng học vẹt thì mốc càng đẹp, và cảnh báo luôn đỏ dù có drift hay không.

Đo thật ngày 22/09/2026: một model có RMSE 14.321 trên train set nhưng 152.620 trên test set. Traffic thực tế ở mức 203.809, tức gấp 14,2 lần (Cao) nếu so với train set, nhưng chỉ gấp 1,33 lần (Cảnh báo) nếu so với test set. Metric trên test set cũng là con số màn Model đang hiển thị, nên operator so với đúng thứ mình nhìn thấy.

**Baseline profile.** Ngoài các mốc trên, bước registration (mục 3.7) lưu một baseline profile của train set cho mỗi model version. Công cụ phát hiện drift không đọc được bản tóm tắt thống kê (nó chỉ so hai tập data thật), nên baseline profile không dùng trong monitoring. Nó là cách rẻ nhất để trả lời câu hỏi "version này học từ data phân bố thế nào" mà không phải đọc lại data.

| Phần | Nội dung |
| --- | --- |
| Chung | Tổng số record; thời điểm tính (giờ UTC) |
| Mỗi cột số | Tỉ lệ missing; trung bình; độ lệch chuẩn; nhỏ nhất; lớn nhất; các phân vị 25%, 50%, 75%; histogram 20 khoảng |
| Mỗi cột category | Tỉ lệ missing; số giá trị khác nhau; tỉ lệ của từng giá trị |

### 7.2. Bốn mục monitoring: Evidently tính, thành phần dùng chung quyết định

**Nguyên tắc chia việc.** Evidently lo phần **tính toán**: kiểm định thống kê từng cột, tính metric, đếm missing, vẽ báo cáo. Hệ thống không tự viết lại những phép tính này. Thành phần dùng chung lo phần **quyết định**: đưa đúng data vào Evidently, rồi đọc con số Evidently trả về và xếp thành Ổn / Cảnh báo / Cao / Chưa đủ dữ liệu.

**Khoảng thời gian xét:** mặc định 24 giờ gần nhất tính tới lúc monitoring.

**Mỗi lần monitoring, cho mỗi model, chạy bốn bước:**

| STT | Bước | Ai làm | Nội dung |
| --- | --- | --- | --- |
| 1 | Chuẩn bị data | Thành phần dùng chung | Đọc prediction log và ground truth trong khoảng xét; ghép dự đoán với ground truth qua request ID; lấy bốn mốc (mục 7.1); cho traffic đi qua các bước 1–3 của mục 4.1 lấy từ champion (dùng cho data quality). |
| 2 | Tính | Evidently | Tính bốn bộ con số ở bảng dưới, và sinh báo cáo chi tiết. |
| 3 | Đọc kết quả | Adapter trong thành phần dùng chung | Chuyển kết quả của Evidently thành một cấu trúc con số cố định của hệ thống (mức lệch và ngưỡng của từng cột, có drift hay không, metric, tỉ lệ missing, tỉ lệ giá trị lạ). |
| 4 | Xếp mức | Thành phần dùng chung | Áp các quy tắc ở bảng "Quy tắc xếp mức" bên dưới. |

**Evidently tính gì cho từng mục:**

| Mục | Tên trên dashboard | Mốc (reference) | Data hiện tại (current) | Evidently tính |
| --- | --- | --- | --- | --- |
| Data drift | Data drift | Mẫu training data | Input trong prediction log | Kiểm định drift trên đúng các cột feature của bài toán: mức lệch và ngưỡng của từng cột |
| Prediction drift | Model drift | Phân bố kết quả dự đoán lúc train | Cột kết quả trong prediction log | Kiểm định drift trên một cột kết quả |
| Performance drift | Performance drift | — (mốc là metric trên test set đã ghi trong MLflow, không tính lại) | Các cặp dự đoán / ground truth đã ghép | Preset regression: RMSE, MAE. Preset classification: AUC, và precision/recall tại decision threshold của champion. |
| Data quality của input | Data quality | Mẫu training data sau data cleaning | Traffic sau data cleaning | Tỉ lệ missing của từng cột; tỉ lệ giá trị category chưa có trong mốc |

Metric của performance drift phải được tính **đúng cách với bước evaluation** (mục 3.6), vì nó được chia cho metric trên test set. Test của adapter kiểm tra điều này: cùng một tập dự đoán / ground truth, con số Evidently trả về phải trùng với con số bước evaluation tính.

**Quy tắc xếp mức** (thành phần dùng chung):

| Mục | Ổn | Cảnh báo | Cao |
| --- | --- | --- | --- |
| Data drift — luật tỉ lệ | Dưới 30% số cột bị drift | 30% – 50% | Trên 50% |
| Data drift — luật độ lớn | Tổng mức vượt ngưỡng trên mọi cột âm | Tổng mức vượt ngưỡng từ 0 trở lên | — |
| Prediction drift | Không drift | — | Có drift |
| Performance drift — giá bán | RMSE thực tế / RMSE trên test set dưới 1,2 | 1,2 – 1,5 | Trên 1,5 |
| Performance drift — cải tạo | AUC giảm dưới 0,05 | 0,05 – 0,10 | Trên 0,10 |
| Data quality của input | Mọi cột: tỉ lệ missing tăng dưới 5 điểm phần trăm so với mốc, và giá trị category chưa từng gặp dưới 5% | Có cột tăng 5–20 điểm phần trăm, hoặc có cột có 5–20% giá trị chưa từng gặp | Có cột tăng trên 20 điểm phần trăm, hoặc có cột có trên 20% giá trị chưa từng gặp |

**Vì sao không dùng thẳng kết luận của Evidently.** Có bốn lý do:

1. **Kết luận drift của Evidently theo luật tỉ lệ riêng** (trên 50% số cột drift), nên bỏ sót drift dồn vào một, hai cột. Ở scenario "Dịch chuyển thị trường", cột thành phố lệch gần 8 lần ngưỡng phát hiện, nhưng chỉ 2 trên 22 cột vượt ngưỡng — đúng bằng tỉ lệ đo được ở scenario "Không thay đổi". Luật tỉ lệ báo Ổn, và báo sai. Luật độ lớn cộng dồn mức vượt ngưỡng của từng cột (cột không drift đóng góp số âm), nên bắt được một cột lệch rất nặng. Data drift lấy mức nặng hơn của hai luật.
2. **Evidently không có khái niệm "Chưa đủ dữ liệu".** Có 3 cặp ghép được, nó vẫn tính ra RMSE. Quy tắc NV-07 phải nằm ở hệ thống (xem dưới).
3. **Ngưỡng phải là một bản duy nhất.** Ngưỡng xếp mức, ngưỡng ở evaluation gate và các alert rule (mục 7.5) cùng nằm trong thành phần dùng chung. Để Evidently tự quyết định là tạo ra một bản ngưỡng thứ hai.
4. **API của Evidently thay đổi khá mạnh giữa các phiên bản.** Adapter là chỗ duy nhất biết định dạng kết quả của Evidently. Nâng phiên bản Evidently thì chỉ adapter phải sửa; quy tắc xếp mức giữ nguyên.

**Chưa đủ dữ liệu (NV-07).** Khi số ground truth ghép được với dự đoán **dưới 50**, performance drift nhận trạng thái **Chưa đủ dữ liệu**, không được nhận Ổn — kể cả khi Evidently vẫn trả về một con số. Báo Ổn khi chưa đo là nói dối, và là kiểu nói dối nguy hiểm nhất ở đây: dấu xanh trên dashboard trong khi thực tế chưa ai kiểm tra. Champion không có metric trên test set (ví dụ được đăng ký ngoài pipeline) cũng cho Chưa đủ dữ liệu, không bao giờ cho Ổn. Với data drift, prediction drift và data quality: dưới 50 dự đoán trong khoảng xét thì cũng là Chưa đủ dữ liệu.

**Data quality của input (CN-44).** Cả mốc lẫn traffic đều đi qua các bước 1–3 của mục 4.1 lấy từ **chính champion**, không lấy từ bản thành phần dùng chung trong môi trường monitoring, để phép làm sạch đúng là phép model đã dùng. Đây là xử lý theo từng cột, không bỏ record nào, nên được phép dùng ở đây (mục 2.4). Evidently chạy trên raw data sẽ đếm "$450,000" hay "NEW YORK" là giá trị hợp lệ, nên không phản ánh những gì model thật sự nhìn thấy. Các ngưỡng là giá trị ban đầu, chưa hiệu chỉnh (mục 14.2).

**Mức tổng hợp** là mức nặng nhất trong ba loại drift và data quality của input, **bỏ qua** Chưa đủ dữ liệu. Nếu tất cả đều Chưa đủ dữ liệu thì mức tổng hợp cũng là Chưa đủ dữ liệu. Dashboard luôn hiện từng loại riêng; mức tổng hợp chỉ là thông tin phụ, không bao giờ thay cho từng loại.

### 7.3. Kết quả của một lần monitoring

Mỗi lần monitoring, cho mỗi model, tạo ra:

| Kết quả | Nội dung | Ai dùng |
| --- | --- | --- |
| Bản tóm tắt | Tên model và model version, bài toán, monitoring ID, thời điểm, khoảng thời gian xét, mức tổng hợp, mức của từng loại drift, mức data quality của input và các cột vi phạm, số dự đoán, số ground truth ghép được, metric trên traffic thực tế, metric trên test set và nguồn của nó, metric theo nhóm (nhóm có ít nhất 50 cặp ghép được), kết quả flush trước khi tính, số lần liên tiếp ở mức Cảnh báo của từng loại | Dashboard (báo cáo mới nhất, diễn biến) |
| Bản sao tóm tắt mới nhất | Ghi đè mỗi lần monitoring | Dashboard đọc báo cáo mới nhất bằng một lần đọc, không phải liệt kê rồi so thời gian |
| Báo cáo chi tiết | Trang web do Evidently tạo, khoảng 5 MB | Dashboard, chỉ tải khi operator bấm xem |

Bản tóm tắt viết trước ngày 22/09/2026 không có trường metric trên test set. Bản tóm tắt viết trước bản 1.1 không có các trường data quality của input, metric theo nhóm, số lần liên tiếp. Mọi nơi đọc bản tóm tắt phải chịu được việc thiếu các trường này.

### 7.4. Môi trường của bước monitoring

Evidently kéo theo khoảng 500 MB thư viện vẽ biểu đồ. Nó **không** được cài vào base image dùng chung (mục 11.4), mà chỉ vào image riêng của bước monitoring. Nhờ vậy prediction service — thứ không bao giờ tính drift — không phải mang thêm dung lượng đó.

Vì vậy, quy tắc xếp mức và adapter (mục 7.2) nằm trong thành phần dùng chung và **không import Evidently**. Adapter chỉ đọc kết quả Evidently ở dạng dữ liệu thuần (dictionary), nên test được bằng các kết quả mẫu đã lưu. Quy tắc xếp mức là phần dễ sai nhất, nên phải test được rẻ nhất, trên máy phát triển không cài Evidently.

### 7.5. Alert và lưu metric theo thời gian

Báo cáo monitoring trả lời câu hỏi "chuyện gì đang xảy ra" khi có người mở ra xem. Phần này trả lời câu hỏi "làm sao operator biết mà mở ra xem" (NV-10).

**Nguồn metric:**

| Nguồn | Metric | Cách đưa vào |
| --- | --- | --- |
| Bước monitoring | Mức của từng loại drift và data quality của input (Ổn = 0, Cảnh báo = 1, Cao = 2, Chưa đủ dữ liệu = −1); số lần liên tiếp ở mức Cảnh báo; tỉ lệ RMSE hoặc mức giảm AUC; số dự đoán; số cặp ghép được. Gắn label tên model và model version. | Push vào Pushgateway sau khi ghi bản tóm tắt |
| Training pipeline, feedback data pipeline | Kết quả lần chạy: thành công, không qua evaluation, thất bại, thất bại ở smoke test sau deploy | Push vào Pushgateway khi kết thúc |
| Prediction service | Operational metric (mục 5.1) | Prometheus tự lấy (scrape) mỗi 30 giây |

Các bước chạy theo batch kết thúc trước khi Prometheus kịp lấy metric, nên phải chủ động push qua Pushgateway. Prediction service chạy liên tục, nên để Prometheus tự scrape.

**Alert rule** (CN-46) nằm trong file cấu hình Grafana, lưu cùng source code:

| Rule | Điều kiện |
| --- | --- |
| Mức Cao | Một loại drift hoặc data quality của input có mức 2 |
| Cảnh báo kéo dài | Số lần liên tiếp ở mức Cảnh báo của một loại từ 3 trở lên |
| Pipeline thất bại | Lần training hoặc feedback data gần nhất thất bại, kể cả thất bại ở smoke test sau deploy |
| Prediction service lỗi | Tỉ lệ request lỗi hệ thống trên 1% trong 5 phút |
| Mất log | Số record prediction log đã phải bỏ tăng lên |

Số lần liên tiếp được tính ở bước monitoring, không ở Grafana: ngưỡng và quy tắc xếp mức thuộc về thành phần dùng chung (mục 7.4), còn Grafana chỉ so một con số với một giá trị cố định. Chưa đủ dữ liệu có giá trị −1 nên không bao giờ thoả rule nào. Một vấn đề đang diễn ra chỉ được nhắc lại sau 24 giờ, để operator không bị dồn alert.

**Nội dung alert:** model và model version, loại vấn đề, mức độ, thời điểm, đường dẫn tới màn Giám sát drift, và mục hướng dẫn xử lý tương ứng trong 運用手順書. Địa chỉ kênh nhắn tin nằm trong config file riêng (PCN-12). Không cấu hình kênh thì hệ thống vẫn chạy, alert chỉ hiện trên Grafana.

**Không mâu thuẫn với NV-01.** Việc Prometheus scrape định kỳ là tác vụ rất nhẹ, không phải một pipeline xử lý; nó không chạy lại training hay monitoring. Metric chỉ được giữ 15 ngày để giới hạn dung lượng đĩa (RB-01).

---

## 8. Thiết kế màn hình

### 8.1. Danh sách màn hình

| STT | Màn hình | Mục đích | Yêu cầu |
| --- | --- | --- | --- |
| 1 | Tổng quan | Chạy training pipeline, xem các lần chạy | CN-35 |
| 2 | Data | Upload data, xem mẫu và thống kê, tạo feedback data version | CN-36 |
| 3 | Model | Xem, chọn champion, xoá model version; xem model card | CN-37 |
| 4 | Giám sát drift | Chạy simulation, xem kết quả monitoring | CN-38 |

Giao diện tiếng Việt; thuật ngữ kỹ thuật giữ tên tiếng Anh như trong tài liệu này. Ưu tiên màn hình laptop (từ khoảng 1.280 pixel chiều ngang). Bảng rộng cuộn ngang bên trong khung của nó, không làm cả trang cuộn ngang. Số định dạng theo kiểu Việt Nam (2.012.000). Thời gian hiển thị tương đối ("3 phút trước"), rê chuột vào thì hiện giờ chính xác.

### 8.2. Quy ước chung

**Thanh trạng thái hệ thống.** Luôn hiện ở đầu trang, cho biết trạng thái riêng của năm thành phần: Airflow, MLflow, MinIO, prediction service, PostgreSQL (CN-39). Không làm mới nhanh hơn mỗi 10 giây, và không gửi request mới khi request trước chưa trả lời. Không kết nối được tới backend trung gian là một trạng thái riêng, khác với "có thành phần hỏng".

**Nhãn bốn trạng thái (CN-31).** Mỗi nhãn luôn có chữ; màu không bao giờ là cách phân biệt duy nhất.

| Trạng thái | Nhãn | Hình thức |
| --- | --- | --- |
| Ổn | ổn | Nền xanh lá nhạt, biểu tượng dấu tích, viền liền |
| Cảnh báo | cảnh báo | Nền vàng nhạt, biểu tượng tam giác chấm than, viền liền |
| Cao | cao | Nền đỏ nhạt, biểu tượng dấu X trong vòng tròn, viền liền đậm |
| Chưa đủ dữ liệu | chưa đủ dữ liệu | Nền xám **gạch chéo**, biểu tượng vòng tròn rỗng, viền **nét đứt** |

"Chưa đủ dữ liệu" khác "Ổn" ở ba điểm cùng lúc — hoa văn, viền, chữ — để người mù màu và bản in đen trắng vẫn phân biệt được (NV-07). Hoa văn gạch chéo chỉ dành riêng cho trạng thái này. Độ tương phản giữa chữ và nền tối thiểu 4,5:1.

**Ba tình huống không có data (CN-40):**

| Tình huống | Hiển thị |
| --- | --- |
| Chưa có dữ liệu (ví dụ ngày đầu chưa có traffic, chưa có báo cáo monitoring, data version chưa upload) | Nói vì sao trống và nên làm gì tiếp. **Không phải lỗi.** |
| Không tìm thấy | "Không tìm thấy" kèm lý do. Không phải sự cố hạ tầng. |
| Hệ thống đang lỗi | "Hệ thống đang lỗi", nút thử lại, trỏ tới thanh trạng thái để biết thành phần nào hỏng |

Mỗi màn hình có trạng thái đang tải riêng, không để màn hình trắng.

**Xác nhận trước thao tác ghi (CN-41):**

| Thao tác | Khi nào hỏi xác nhận |
| --- | --- |
| Chạy training | Luôn luôn, nhắc lại đủ các lựa chọn |
| Chọn champion | Luôn luôn |
| Tạo data version từ traffic thực tế | Luôn luôn, nêu số record sẽ thêm và số record gốc sẽ bị thay thế |
| Xoá một model version | Luôn luôn |
| Xoá toàn bộ một model | Luôn luôn, nói rõ không hoàn tác được |

Sau mỗi thao tác ghi, giao diện luôn tải lại data thật thay vì tự cập nhật trước. Thao tác thất bại không bao giờ được báo là thành công.

**Chế độ demo (PCN-25).** Công tắc ở thanh bên. Khi bật, mọi màn hình dùng data mẫu thay vì gọi backend trung gian.

### 8.3. Nội dung từng màn hình

**Màn hình 1 — Tổng quan**

| Thành phần | Nội dung |
| --- | --- |
| Form khởi chạy | Bài toán (bắt buộc, không chọn sẵn); thuật toán (danh sách theo bài toán, bỏ trống là mặc định); hyperparameter tuning (checkbox); số dòng train hoặc "dùng toàn bộ dòng"; xử lý lại data từ đầu (checkbox); data version (ô nhập chữ — hệ thống chưa có danh sách data version) |
| Hộp xác nhận | Nhắc lại đủ các lựa chọn. Khi chọn toàn bộ dòng, cảnh báo lần chạy sẽ lâu hơn và tốn RAM hơn nhiều. Nút xác nhận ghi rõ "Bắt đầu training". |
| Bảng các lần chạy gần đây | Run ID, trạng thái, bài toán, thời điểm bắt đầu, kết thúc, thời lượng |
| Thanh tiến trình | Chín ô theo đúng thứ tự của pipeline (mục 3.1); nhánh "registration → deploy" và nhánh "dừng" đặt song song sau bước rẽ nhánh. Ô chưa chạy trông khác ô bị bỏ qua; ô bị bỏ qua vì nhánh không được chọn không phải lỗi. |

**Màn hình 2 — Data**

| Thành phần | Nội dung |
| --- | --- |
| Upload | Kéo thả file CSV; ô tên data version (kiểm tra quy tắc tên ngay khi nhập; tên đã tồn tại bị từ chối, CN-02); thanh tiến độ, rồi "đang chuyển định dạng". File vượt 500 MiB bị chặn ngay ở trình duyệt, không gửi đi. |
| Dòng mẫu | Tối đa 200 dòng, **đúng như raw data** — không chuẩn hoá trên giao diện; ô trống có dấu hiệu nhìn thấy được |
| Thống kê theo cột | Kiểu dữ liệu, tỉ lệ missing, số giá trị ngoài khoảng hợp lệ. Luôn ghi rõ "thống kê trên N / M dòng" (mục 14.2). |
| Tạo data version từ traffic thực tế | Bài toán, data version nguồn, khoảng thời gian, tên data version mới. Hiện trước số cặp dự đoán / ground truth ghép được; dưới 500 thì khoá nút tạo và nói vì sao. Sau khi xác nhận, theo dõi tiến trình như một lần chạy (CN-42). |
| Số dòng xem trước | Chọn 10 / 50 / 100 / 200. Đặt xa mọi nhãn có chữ "train", để không nhầm với số dòng train ở màn Tổng quan. |

**Màn hình 3 — Model**

| Thành phần | Nội dung |
| --- | --- |
| Mỗi model một khối | Tên, bài toán, các metric của champion |
| Bảng model version | Số version, các metric trên test set, thời điểm tạo, nhãn "champion". **Cột metric sinh ra từ data thật của model**, không cố định: RMSE / MAE / R² cho bài toán giá bán; AUC / F1 / precision cho bài toán cải tạo. |
| Chọn làm champion | Chỉ có ở những hàng không phải champion. Sau khi xác nhận, prediction service chuyển ngay; giao diện hiện version mà service thực sự đang dùng, và báo rõ nếu service chưa chuyển được. |
| Model card | Xem model card của từng version (CN-12) |
| Xoá version | Bị từ chối với champion (CN-17) |
| Xoá toàn bộ model | Không hoàn tác được (CN-18) |

**Màn hình 4 — Giám sát drift**

| Thành phần | Nội dung |
| --- | --- |
| Chọn model | Danh sách model đang có |
| Khối simulation | Scenario (năm scenario, nhãn tiếng Việt), số request (1–5.000), nút "Gửi traffic". Thanh tiến trình hai chặng: gửi traffic → tính monitoring. Tự tải lại báo cáo khi xong. |
| Ba ô drift | Data drift, prediction drift, performance drift — **ba ô riêng**, mỗi ô một nhãn bốn trạng thái, kèm một dòng nói nó so sánh cái gì. Có thời điểm tính báo cáo. |
| Ô data quality của input | Ô thứ tư, **tách khỏi** ba ô drift, cùng nhãn bốn trạng thái; liệt kê các cột vi phạm (CN-44) |
| Thông báo chưa đủ dữ liệu | Khi performance drift là Chưa đủ dữ liệu: nêu số ground truth đã có, và nói rõ đây **không phải** là ổn |
| Bảng so sánh metric | Metric · trên test set · trên traffic thực tế · chênh lệch (tô đỏ khi kém hơn, xanh khi tốt hơn) |
| Bảng metric theo nhóm | Metric theo thành phố và loại bất động sản trên traffic thực tế, đặt cạnh metric của nhóm đó trên test set (CN-45). Nhóm thiếu mẫu ghi "chưa đủ dữ liệu". |
| Biểu đồ diễn biến | **Ba dải riêng xếp dọc, mỗi dải một màu.** Mỗi điểm là một lần monitoring, tô màu theo mức tại lúc đó. Bên dưới là một dải metric thật (RMSE hoặc AUC), kèm đường nét đứt là metric trên test set. Phía trên có một dòng kết luận bằng chữ: bao nhiêu lần gần nhất ở mức Cao, mức nào vừa đổi, và cảnh báo khi diễn biến gồm nhiều model version khác nhau. |
| Báo cáo chi tiết | Nút "Xem báo cáo" mở báo cáo Evidently ngay trong trang, kèm một dòng giải thích vì sao kết luận của báo cáo có thể khác nhãn mức độ (mục 14.2) |
| Nút retrain | Chỉ hiện khi có mức Cao. Chuyển sang màn Tổng quan với bài toán đã điền sẵn, kèm gợi ý tạo data version từ traffic thực tế trước (màn Data). Việc xác nhận nằm ở hộp xác nhận của màn Tổng quan. |
| Ghi chú cập nhật | "Báo cáo tính lúc …", kèm nút "Tải lại". Nếu lần flush trước khi tính thất bại (mục 3.10): "Một phần traffic vừa gửi có thể chưa có trong báo cáo này". |

Biểu đồ diễn biến chỉ **hiển thị** mức do bước monitoring tính; giao diện không tự đặt ngưỡng nào. Ngưỡng thuộc về bước monitoring; chép sang giao diện là tạo ra một bản thứ hai, sớm muộn sẽ lệch.

---

## 9. Thiết kế liên kết giữa các thành phần

### 9.1. Dashboard với backend trung gian

| Thao tác trên dashboard | Backend trung gian chuyển tới | Yêu cầu |
| --- | --- | --- |
| Chạy training pipeline → nhận run ID (trả về ngay, không chờ chạy xong) | Airflow | CN-05 |
| Xem danh sách các lần chạy gần đây | Airflow | CN-35 |
| Xem trạng thái từng bước của một lần chạy | Airflow | CN-35 |
| Lấy danh sách thuật toán theo bài toán | Thành phần dùng chung | CN-05 |
| Upload data → nhận tên data version, số dòng, split point (tên đã tồn tại bị từ chối) | MinIO | CN-01, CN-02 |
| Xem trước số cặp dự đoán / ground truth ghép được | MinIO | CN-42 |
| Chạy feedback data pipeline | Airflow | CN-42 |
| Xem mẫu và thống kê cột của một data version | MinIO | CN-03 |
| Xem danh sách model, version, metric, champion | MLflow | CN-15 |
| Chọn champion, rồi yêu cầu prediction service reload | MLflow, prediction service | CN-16 |
| Xoá một version | MLflow | CN-17 |
| Xoá toàn bộ một model, rồi yêu cầu prediction service reload | MLflow, prediction service | CN-18 |
| Xem model card | MLflow | CN-12 |
| Lấy danh sách scenario | Thành phần dùng chung | CN-25 |
| Chạy simulation | Airflow | CN-25 |
| Xem trạng thái lần simulation gần nhất, gồm trạng thái hai chặng | Airflow | CN-28 |
| Chạy monitoring trực tiếp (dashboard không có nút; dùng khi cần tính lại mà không gửi thêm traffic) | Airflow | CN-29 |
| Xem báo cáo monitoring mới nhất | MinIO | CN-33 |
| Xem diễn biến qua các lần monitoring | MinIO | CN-33 |
| Xem báo cáo chi tiết của một lần monitoring | MinIO | CN-33 |
| Xem trạng thái các thành phần phụ thuộc (mỗi thành phần tối đa 5 giây) | Tất cả | CN-39 |

Backend trung gian gọi Airflow bằng một service account. Mặc định Airflow chỉ chấp nhận phiên đăng nhập từ trình duyệt, nên phải bật thêm xác thực bằng tên và mật khẩu cho các lời gọi từ service khác. Thiếu cấu hình này, mọi lời gọi đều bị từ chối, và thông báo lỗi không gợi ý đúng nguyên nhân.

Khi yêu cầu reload sau thao tác tay thất bại (prediction service không phản hồi), thay đổi trên MLflow vẫn được giữ. Backend trung gian trả về rõ ràng rằng service chưa chuyển version, để giao diện không báo thành công trọn vẹn.

Nếu backend trung gian không kết nối được tới một thành phần (ví dụ thiếu cấu hình), nó vẫn khởi động và báo thành phần đó "hỏng" ở chức năng trạng thái, thay vì dừng hẳn.

### 9.2. Liên kết giữa các thành phần phía sau

| Từ | Tới | Nội dung |
| --- | --- | --- |
| Airflow | Các bước xử lý, simulation agent | Chạy từng bước trong container riêng; truyền tham số và các giá trị nhỏ |
| Các bước xử lý | MinIO | Đọc/ghi data, baseline profile, báo cáo |
| Các bước xử lý | MLflow | Ghi kết quả training; đọc champion để so sánh; đăng ký version mới |
| Bước deploy | Prediction service | Yêu cầu reload model |
| Simulation pipeline | Monitoring pipeline | Khởi chạy và chờ xong |
| Prediction service | MLflow | Lấy champion |
| Prediction service | MinIO | Ghi prediction log, ground truth |
| Simulation agent | MinIO | Đọc data nguồn |
| Simulation agent | Prediction service | Gửi request dự đoán, gửi ground truth |
| MLflow | PostgreSQL, MinIO | Lưu data quản lý vào PostgreSQL; lưu file model vào MinIO |
| Airflow | PostgreSQL | Lưu data quản lý |
| Backend trung gian | Prediction service | Yêu cầu reload sau khi chọn champion hoặc xoá model |
| Monitoring pipeline | Prediction service | Yêu cầu flush prediction log |
| Simulation agent | MLflow, MinIO | Truy ngược train set của champion để bỏ ra khỏi nguồn |
| Bước monitoring, training pipeline, feedback data pipeline | Pushgateway | Push metric |
| Prometheus | Prediction service, Pushgateway | Scrape metric định kỳ |
| Grafana | Prometheus; kênh nhắn tin | Đọc metric; gửi alert |

---

## 10. Thiết kế data

### 10.1. Bố cục object storage

Toàn bộ data nằm trong một bucket, chia thành các vùng sau:

| Vùng | Nội dung | Cách chia | Tạo bởi | Dùng bởi |
| --- | --- | --- | --- | --- |
| Raw data | Data upload hoặc tạo từ traffic thực tế; hồ sơ data version (split point, nguồn gốc) | Theo data version | Chức năng upload; nạp lần đầu lúc cài đặt; feedback data pipeline | Bước data ingestion, simulation agent, xem trước data |
| Working copy | Toàn bộ raw data dạng Parquet | Theo working copy ID | Bước data ingestion | Data quality check, data preparation |
| Báo cáo chất lượng | Kết quả data quality check | Theo working copy ID | Bước data quality check | Operator |
| Data đã chuẩn bị | Train set, test set | Theo data ID, rồi theo bài toán | Bước data preparation | Training, evaluation, registration, monitoring |
| File model | Model đã train và các file liên quan | Do MLflow quản lý | MLflow | Prediction service, evaluation, monitoring |
| Baseline profile | Baseline profile của từng model version | Theo tên model, rồi số version | Bước registration | Tham khảo |
| Prediction log | Log mỗi lần dự đoán | Theo tên model, rồi theo ngày | Prediction service | Bước monitoring, feedback data pipeline |
| Ground truth | Ground truth | Theo tên model, rồi theo ngày đã dự đoán | Prediction service | Bước monitoring, feedback data pipeline |
| Báo cáo monitoring | Bản tóm tắt và báo cáo chi tiết của mỗi lần monitoring; bản sao tóm tắt mới nhất | Theo tên model, rồi monitoring ID | Bước monitoring | Dashboard |

**Toàn bộ quy ước đặt đường dẫn lưu trữ nằm ở một chỗ duy nhất** trong thành phần dùng chung (mục 2.4). Không chỗ nào khác trong hệ thống tự ghép đường dẫn. Khi chuyển sang Amazon S3, chỉ chỗ này phải sửa (PCN-15).

**Data version không bao giờ bị ghi đè** (CN-02, NV-09). Ngoài quy tắc ở backend trung gian, storage bật versioning cho vùng raw data. Nhờ vậy, kể cả khi ai đó xoá hay ghi bằng tay trực tiếp trên storage, data vẫn khôi phục được.

Monitoring và simulation agent phụ thuộc vào data đã chuẩn bị (mục 6, 7.1). Nếu data đã chuẩn bị của champion bị xoá, monitoring sẽ thất bại và báo rõ đường dẫn bị thiếu.

### 10.2. Định dạng lưu trữ

| Data | Định dạng | Lý do |
| --- | --- | --- |
| Data upload | CSV, chuyển sang Parquet ngay khi nhận | Định dạng operator có sẵn |
| Mọi data dạng bảng trong storage | Parquet, có nén | Dung lượng giảm từ khoảng 373 MB còn khoảng 60–80 MB; đọc nhanh hơn nhiều lần; giữ nguyên kiểu dữ liệu nên các bước sau không phải đọc lại từ đầu (PCN-03) |
| Baseline profile, hồ sơ data version, báo cáo chất lượng, bản tóm tắt monitoring, model card | Văn bản có cấu trúc | Đọc được bằng các công cụ thông dụng |
| Báo cáo chi tiết monitoring | Trang web (HTML) | Xem được bằng trình duyệt |

### 10.3. Database quản lý

| Database | Dùng bởi | Nội dung |
| --- | --- | --- |
| Của orchestrator | Airflow | Lịch sử chạy, trạng thái từng bước |
| Của quản lý model | MLflow | Lịch sử training, model version, alias champion |

Hai database riêng trên cùng một PostgreSQL server. Tách riêng để hai công cụ không ảnh hưởng data của nhau, và để có thể chuyển từng cái sang dịch vụ cloud một cách độc lập.

---

## 11. Thiết kế phi chức năng

### 11.1. Tài nguyên và hiệu năng

| Biện pháp | Đáp ứng |
| --- | --- |
| Dùng lại working copy và data đã chuẩn bị khi raw data không đổi (mục 3.2, 3.4) | PCN-02 |
| Lưu mọi data dạng bảng ở dạng Parquet (mục 10.2) | PCN-01, PCN-03 |
| Ghi prediction log theo batch (mục 5.3) | PCN-04 |
| Operator chọn số dòng cho từng lần train; số dòng nằm trong data ID; bước data preparation đọc hai lượt để chỉ load những record được chọn (mục 3.4) | PCN-05 |
| Prometheus chỉ giữ metric 15 ngày (mục 7.5) | PCN-01 |
| Lưới hyperparameter tối đa 8 tổ hợp, cross-validation 5 phần (mục 3.5) | PCN-06 |
| Monitoring chỉ lấy mẫu tối đa 10.000 dòng làm mốc (mục 7.1) | PCN-01 |
| Công cụ phát hiện drift chỉ nằm trong image của bước monitoring (mục 7.4) | PCN-01 |
| Orchestrator chạy ở chế độ một máy, không cần hàng đợi hay máy chủ phân tán | PCN-01 |
| Không pipeline nào chạy theo lịch (mục 3) | NV-01 |

### 11.2. Chạy lại và độ tin cậy

- Vị trí output của mỗi bước được xác định hoàn toàn bởi input, nên chạy lại luôn ghi vào đúng chỗ cũ, hoặc bỏ qua nếu đã có (PCN-07).
- Mỗi pipeline chỉ chạy một lần tại một thời điểm (PCN-11).
- Phần xử lý data trong model chịu được thiếu cột, giá trị trống, giá trị category mới, và không bao giờ bỏ record (mục 4; PCN-08, PCN-09).
- Prediction service khởi động được khi thiếu model (mục 5.2). Ghi log có giới hạn mất mát, và lượng mất nhìn thấy được (mục 5.3; PCN-10).
- Backend trung gian khởi động được khi thiếu kết nối tới một thành phần (mục 9.1).
- Sau deploy luôn có smoke test; không đạt thì rollback về version trước (mục 3.8).
- Monitoring chỉ tính sau khi prediction log trong buffer đã được flush xuống storage, hoặc ghi rõ khi flush thất bại (mục 3.10, 5.3).

### 11.3. Bảo mật

| Biện pháp | Đáp ứng |
| --- | --- |
| Credentials nằm trong config file riêng, không đưa lên repository dùng chung; repository chỉ chứa file mẫu không có giá trị thật. Orchestrator truyền credentials vào các container khi chạy. | PCN-12 |
| Dashboard chỉ nói chuyện với backend trung gian (mục 2.3). Ranh giới này được kiểm tra tự động ở mỗi lần đưa source code lên (mục 11.6). | PCN-13 |
| Mọi thao tác của backend trung gian đi qua **một điểm kiểm tra quyền truy cập dùng chung**. Hiện điểm này chưa kiểm tra gì. Khi bật xác thực, chỉ phải sửa đúng một chỗ, không phải sửa từng thao tác rồi bỏ sót. | PCN-14 |
| Việc xoá champion bị chặn ở backend trung gian, không chỉ ở giao diện. Gọi thẳng backend trung gian cũng không vượt qua được. | CN-17 |
| Báo cáo chi tiết monitoring được hiển thị trong một khung tách biệt (iframe), không truy cập được vào trang chứa nó | — |
| Grafana và Prometheus chỉ mở trên máy cục bộ; thông tin đăng nhập Grafana và địa chỉ kênh nhắn tin nằm trong config file riêng | PCN-12 |

### 11.4. Môi trường chạy đồng nhất

- Có **một base image dùng chung**, cài sẵn các thư viện xử lý data, machine learning và thành phần dùng chung (mục 2.4). Mọi bước xử lý, prediction service, simulation agent và backend trung gian đều build từ base image này.
- Không có base image, mỗi thành phần sẽ tự cài lại thư viện: build rất lâu, và phiên bản thư viện dễ lệch giữa các thành phần. Lệch phiên bản giữa lúc train và lúc dự đoán là loại lỗi khó tìm nhất.
- Model đã lưu chỉ load lại đúng trong môi trường có cùng phiên bản Python và thư viện với lúc lưu. Vì vậy training và prediction **đều chạy trong container**, không train trên máy phát triển (PCN-20, RB-03). Ví dụ đã gặp: khi thêm thư viện XGBoost, prediction service cũng phải build lại; nếu không, nó sẽ không load được model train bằng XGBoost.
- Commit hash của source code được ghi vào base image lúc build, và được ghi cùng mỗi run (mục 3.5, PCN-26). Random seed nằm trong thành phần dùng chung.
- Mỗi khi thành phần dùng chung thay đổi, **phải build lại base image và mọi image dựa trên nó**, theo đúng thứ tự. Chỉ build lại base image là chưa đủ: các image dựa trên nó vẫn giữ bản cũ bên trong cho tới khi được build lại.

### 11.5. Kiểm thử

| Nội dung | Đáp ứng |
| --- | --- |
| Mỗi loại lỗi data trong 要件定義書 mục 6.4 có automated test riêng | PCN-18 |
| Phần xử lý data không bỏ record, và dự đoán được cho đúng một căn nhà | PCN-09 |
| Model nhận được raw data chưa làm sạch | CN-19 |
| Các cột bị loại không ảnh hưởng kết quả dự đoán. Kiểm bằng một thuật toán thật sự dùng data, không bằng model đoán mò — model đoán mò sẽ qua test này dù thiết kế sai. | NV-05 |
| Giá trị category mới và giá trị missing không gây lỗi | PCN-08 |
| Model sau khi lưu rồi load lại cho cùng kết quả | PCN-19 |
| Các evaluation gate chặn được model đoán mò | PCN-22 |
| Quy tắc xếp mức monitoring, gồm cả trường hợp Chưa đủ dữ liệu (kể cả khi Evidently vẫn trả về con số) | NV-07 |
| Adapter đọc đúng kết quả mẫu đã lưu của phiên bản Evidently đang dùng. Nâng phiên bản Evidently mà định dạng kết quả đổi thì test này hỏng trước tiên. | — |
| Metric performance do Evidently tính trùng với metric bước evaluation tính, trên cùng một tập dự đoán / ground truth | CN-32 |
| Mọi record có ngày trong test set đều đăng bán sau mọi record có ngày trong train set; không mã bất động sản nào nằm ở cả hai set | NV-08, PCN-21 |
| Test set giống hệt nhau khi đổi số dòng train | NV-06, PCN-21 |
| Time-based cross-validation khi tuning: phần dùng để chấm luôn nằm sau phần dùng để học | NV-08 |
| Nguồn của simulation agent không chứa căn nhà nào trong train set của champion | CN-26 |
| Decision threshold đạt recall mục tiêu trên phần chọn threshold; model trả câu trả lời có/không theo threshold đã lưu, kể cả sau khi lưu rồi load lại | CN-43, PCN-19 |
| Gate 2 chặn model chỉ tốt hơn trong phạm vi biên độ | CN-11 |
| Feedback data pipeline: feedback record thay thế record gốc cùng mã; split point đúng quy tắc; dưới 500 record thì dừng | CN-42 |
| Bước deploy rollback về version trước khi smoke test không đạt | CN-13 |
| Quy tắc xếp mức data quality của input; số lần liên tiếp ở mức Cảnh báo; Chưa đủ dữ liệu không thoả alert rule nào | CN-44, CN-46 |
| Upload với tên data version đã tồn tại bị từ chối | CN-02 |
| Dự đoán không bao giờ vượt quá ba lần giá trị lớn nhất của label (để phát hiện nếu phép biến đổi log giá bị đưa trở lại, mục 3.5) | — |
| Phần đọc/ghi storage được test trên một storage giả lập trong RAM, rồi kiểm tra lại trên MinIO thật | PCN-16 |
| Mỗi giai đoạn xây dựng, từ hạ tầng tới backend trung gian, có một script kiểm tra chạy trên hệ thống thật. Dashboard được kiểm tra bằng trình duyệt, chưa có script tự động. | — |

Đo ngày 23/09/2026: 666 automated test đạt trên máy phát triển (trước các thay đổi của bản 1.1).

### 11.6. CI — kiểm thử tự động khi đưa source code lên (PCN-28)

| STT | Bước | Nội dung |
| --- | --- | --- |
| 1 | Kiểm tra tĩnh (lint) | Định dạng và lỗi tĩnh của source code |
| 2 | Automated test | Toàn bộ test ở mục 11.5, chạy trên base image (không cần Evidently, mục 7.4) |
| 3 | Kiểm tra ranh giới | Source code dashboard không chứa địa chỉ hay lời gọi trực tiếp tới Airflow, MLflow, MinIO (PCN-13); prediction service và phần tạo model không gọi phần xử lý theo record (PCN-09) |
| 4 | Build image | Build base image rồi mọi image dựa trên nó, theo đúng thứ tự (mục 11.4), ghi commit hash vào image |
| 5 | Kiểm tra cấu hình alert | File cấu hình alert rule của Grafana hợp lệ (mục 7.5) |

Chạy bằng GitHub Actions hoặc công cụ tương đương của repository. Thay đổi làm hỏng một bước không được merge vào main branch. Script kiểm tra trên hệ thống thật và việc kiểm tra dashboard bằng trình duyệt (mục 11.5) vẫn chạy bằng tay, vì cần toàn bộ hệ thống đang chạy.

---

## 12. Thiết kế chuyển đổi lên AWS (giai đoạn 2)

### 12.1. Thành phần tương ứng

| Vai trò | Giai đoạn 1 | Giai đoạn 2 (AWS) |
| --- | --- | --- |
| Dashboard | Ứng dụng web | Giữ nguyên |
| Backend trung gian | Web service trong container | Giữ nguyên, deploy trên Amazon ECS / AWS Fargate hoặc AWS Lambda |
| Orchestrator | Apache Airflow | Amazon MWAA |
| Object storage | MinIO | Amazon S3 |
| Bước training | Container Docker | Amazon SageMaker Training Job |
| Các bước xử lý data | Container Docker | Amazon SageMaker Processing Job |
| Experiment tracking | MLflow | MLflow trên Amazon EC2 / ECS, hoặc Amazon SageMaker Experiments |
| Quản lý model version | MLflow Model Registry | Amazon SageMaker Model Registry |
| Prediction service và chức năng reload | Web service trong container | Amazon SageMaker Endpoint (cập nhật cấu hình Endpoint thay cho reload) |
| Prediction log | Prediction service tự ghi vào MinIO | Amazon SageMaker Data Capture |
| Mốc so sánh của monitoring | Tự tính khi monitoring | Baseline job của Amazon SageMaker Model Monitor |
| Monitoring drift | Evidently, chạy theo yêu cầu | Monitoring schedule của Amazon SageMaker Model Monitor, **chạy mỗi giờ** |
| Database quản lý | PostgreSQL | Amazon Aurora |
| Feedback data pipeline | Container Docker | Amazon SageMaker Processing Job |
| Lưu metric theo thời gian | Prometheus, Pushgateway | Amazon CloudWatch Metrics, hoặc Amazon Managed Service for Prometheus |
| Alert | Grafana | Amazon CloudWatch Alarms + Amazon SNS, hoặc Amazon Managed Grafana |
| Khởi động toàn hệ thống | Docker Compose | Amazon ECS / EKS, hoặc container do SageMaker quản lý |
| Khởi chạy pipeline | Bằng tay từ dashboard | AWS CodePipeline + Amazon EventBridge |

### 12.2. Nguyên tắc chuyển đổi

1. **Storage:** chỉ đổi địa chỉ kết nối từ MinIO sang Amazon S3. Toàn bộ quy ước đường dẫn nằm ở một chỗ (mục 10.1), nên chỉ chỗ đó phải sửa.
2. **Dashboard:** không đổi. Backend trung gian được sửa để trỏ tới các dịch vụ AWS (mục 2.3).
3. **Monitoring:** chạy lại định kỳ mỗi giờ, vì trên cloud chi phí tài nguyên của việc chạy định kỳ không còn là vấn đề như trên máy 16 GB.
4. **Xác thực:** phải bật trước khi hệ thống truy cập được từ bên ngoài (PCN-14).
5. **Chuyển dần từng thành phần**, không chuyển tất cả cùng lúc. Mỗi bước xử lý đã là một container riêng (nguyên tắc 1, mục 1.2), nên từng bước có thể chuyển riêng.

---

## 13. Đối chiếu yêu cầu

| Yêu cầu | Mục thiết kế |
| --- | --- |
| NV-01 Không chạy theo lịch | 1.2, 3 |
| NV-02 Không tự retrain | 3.10, 8.3 (màn hình 4) |
| NV-03 Hai evaluation gate | 3.6 |
| NV-04 Data cleaning giống nhau khi train và khi dự đoán | 2.4, 3.4, 3.5, 4.1 |
| NV-05 Cột không được dùng làm feature | 4.6 |
| NV-06 Test set chung | 3.4, 3.4.1, 3.6 |
| NV-07 Không báo "ổn" khi chưa đo | 7.2, 7.5, 8.2 |
| NV-08 Chấm điểm giống lúc dùng thật | 3.4.1, 3.5, 3.11, 6 |
| NV-09 Truy vết | 3.5, 3.7, 10.1, 11.4 |
| NV-10 Tự gửi alert | 7.5 |
| CN-01 – CN-04 Quản lý data | 3.1, 3.4.1, 8.3 (màn hình 2), 9.1, 10.1 |
| CN-05 – CN-06 Chạy pipeline | 3.1, 8.3 (màn hình 1) |
| CN-07 Data ingestion | 3.2 |
| CN-08 Data quality check | 3.3 |
| CN-09 Data preparation | 3.4, 3.4.1, 4.7 |
| CN-10 Training | 3.5 |
| CN-11 Evaluation | 3.6 |
| CN-12 Registration | 3.7, 7.1, 8.3 (màn hình 3) |
| CN-13 Deploy | 3.8, 5.2 |
| CN-14 Dừng khi không đạt | 3.1 (bước 9) |
| CN-15 – CN-18 Quản lý model | 5.2, 8.3 (màn hình 3), 9.1, 11.3 |
| CN-19 – CN-24 Prediction | 4, 5 |
| CN-25 – CN-28 Simulation | 3.9, 6 |
| CN-29 – CN-34 Monitoring | 3.10, 5.3, 7, 8.3 (màn hình 4) |
| CN-35 – CN-41 Dashboard | 8, 9.1 |
| CN-42 Feedback data | 3.11, 8.3 (màn hình 2), 9.1 |
| CN-43 Decision threshold | 3.5, 3.6, 4.1, 5.1 |
| CN-44 Data quality của input | 7.1, 7.2, 8.3 (màn hình 4) |
| CN-45 Metric theo nhóm | 3.6, 7.3, 8.3 (màn hình 4) |
| CN-46 Alert | 7.5 |
| PCN-01 – PCN-06 Hiệu năng và tài nguyên | 11.1 |
| PCN-07 – PCN-11 Độ tin cậy | 4.1, 4.5, 5.3, 11.2 |
| PCN-12 – PCN-14 Bảo mật | 2.3, 11.3 |
| PCN-15 – PCN-17 Chuyển lên cloud | 10.1, 12 |
| PCN-18 – PCN-22 Chất lượng | 3.4, 3.4.1, 3.6, 11.4, 11.5 |
| PCN-23 – PCN-25 Vận hành | 2.2, 8 |
| PCN-26 Truy vết | 3.5, 11.4 |
| PCN-27 Operational metric | 5.1, 7.5 |
| PCN-28 CI | 11.6 |

---

## 14. Vấn đề còn mở và hạn chế đã biết

### 14.1. Vấn đề còn mở

| STT | Vấn đề | Thời điểm quyết định |
| --- | --- | --- |
| 1 | Cách chạy dashboard ở bản chính thức: backend trung gian tự phục vụ giao diện từ cùng địa chỉ, hay cho phép giao diện ở địa chỉ khác gọi vào. Lựa chọn thứ hai là một quyết định bảo mật, vì hệ thống chưa có xác thực. | Trước khi triển khai chính thức |
| 2 | Cơ chế xác thực cụ thể cho backend trung gian | Trước khi mở hệ thống ra ngoài máy cục bộ |
| 3 | Khi chuyển lên AWS: giữ MLflow song song với Amazon SageMaker Model Registry, hay chuyển hẳn | Giai đoạn 2 |
| 4 | **Đã đóng ở bản 1.2.** Câu hỏi cũ: có nên đổi cột mà hai scenario "Lạm phát giá rao" và "Thị trường tăng giá" biến đổi sang một cột model giá bán thật sự dùng, để chúng kiểm tra được data drift không.<br>Kết luận theo 要件定義書 1.3: **không đổi.** Hai scenario này được thiết kế để kiểm tra hai điều khác:<br>• "Lạm phát giá rao" kiểm tra hệ thống **không báo động nhầm** với model giá bán, và **phát hiện được data drift** với model cải tạo (giá rao là feature của model cải tạo).<br>• "Thị trường tăng giá" kiểm tra hệ thống **phát hiện được performance drift khi input không đổi**.<br>Đổi cột sẽ làm mất cả hai phép kiểm tra. Data drift của model giá bán đã có scenario "Dịch chuyển thị trường". | — |
| 5 | Latency mục tiêu của prediction service, thời gian giữ data, cách backup | Trước giai đoạn 2 |
| 6 | Đo lại toàn bộ metric theo cách chia set mới (mục 3.4.1), gồm cả model cải tạo ở các scenario (mục 6); rồi xác nhận thuật toán mặc định (mục 3.5) và đặt lại ngưỡng của gate 1. Đo cả hai cách chia trên cùng data để biết mức chênh thật. | Ngay sau khi áp dụng mục 3.4.1 |
| 7 | Có retrain trên cả train set và test set trước khi deploy không. Lợi: model học được giai đoạn mới nhất, đặc biệt quan trọng với thuật toán dạng cây. Hại: model được deploy không còn đúng là model đã qua evaluation gate. Bản này giữ cách deploy đúng model đã được evaluate. | Sau khi có số đo của vấn đề 6 |
| 8 | Thêm feature về mặt bằng giá khu vực (ví dụ giá trung vị các tháng gần nhất của thành phố, chỉ tính từ data trước thời điểm dự đoán) để thuật toán dạng cây theo kịp xu hướng thị trường. | Khi xem xét cải thiện model |

### 14.2. Hạn chế đã biết

| Hạn chế | Ảnh hưởng | Hướng xử lý |
| --- | --- | --- |
| Ở bản 1.0, scenario "Không thay đổi" không phải một mốc sạch tuyệt đối: cột mã bưu chính luôn bị coi là drift. Nguyên nhân: simulation agent lấy các căn mới nhất theo ngày đăng bán, trong khi khi train trên một phần data thì model học các dòng đầu tệp. | Mọi ngưỡng hiệu chỉnh dựa trên scenario này đều mang theo sai lệch đó. | Nguyên nhân đã được loại bỏ ở bản 1.1 (mục 3.2, 3.4.1, 6). Chờ đo lại để xác nhận. |
| Đường phân cách của luật độ lớn (mục 7.2) dựa trên đúng hai lần đo, chưa có quy tắc thống kê nào đứng sau. Luật này cũng phụ thuộc số cột feature: càng nhiều cột không drift, càng dễ che mất một cột drift nặng. | Có thể báo sai khi số cột feature thay đổi. | Hiệu chỉnh lại khi có thêm số đo |
| Báo cáo chi tiết của Evidently kết luận theo luật tỉ lệ riêng của nó (trên 50% số cột drift), khác với quy tắc hai luật của hệ thống. | Báo cáo chi tiết có thể ghi "không phát hiện drift" trong khi nhãn mức độ báo Cảnh báo (đo thật ngày 22/09/2026). Khung báo cáo có một dòng giải thích điều này. | Chấp nhận |
| Mã bưu chính được xử lý như một cột category, dù nó có hàng chục nghìn giá trị khác nhau. Với quy tắc gộp giá trị dưới 1% (mục 4.5), trên data lớn gần như mọi mã bưu chính sẽ rơi vào nhóm "hiếm". | Cột này gần như không đóng góp vào dự đoán. Vô hại nhưng lãng phí. | Chưa quyết định; ví dụ gộp theo ba chữ số đầu |
| Định dạng ngày có tên tháng tiếng Anh viết tắt ("15-Jul-2023") phụ thuộc vào thiết lập ngôn ngữ (locale) của môi trường chạy. | Nếu base image đặt locale khác tiếng Anh, toàn bộ ngày ở định dạng này sẽ âm thầm biến thành missing. | Kiểm tra mỗi khi build lại base image |
| Xem trước data load nguyên file vào RAM mỗi lần gọi, nhưng chỉ tính thống kê trên 200.000 dòng đầu. | Mỗi lần xem tốn 1,4–2 giây và đẩy RAM của backend trung gian lên khoảng 0,9–1,3 GB (đo ngày 21/09/2026). Thống kê chỉ là của phần đầu file, có thể không đại diện cho cả file. Tỉ lệ missing ở đây đếm cả ô rỗng, nên có thể cao hơn con số trong báo cáo chất lượng. | Giao diện ghi rõ "thống kê trên N / M dòng"; chỉ gọi khi operator bấm xem |
| Giới hạn 500 MiB của chức năng upload chỉ được kiểm tra **sau khi** toàn bộ file đã tới server. | File vượt giới hạn vẫn chiếm đĩa tạm (tối đa khoảng ba bản) trước khi bị từ chối. | Giao diện chặn file vượt giới hạn ngay ở trình duyệt |
| Hai lần kiểm tra trạng thái hệ thống chồng lên nhau có thể báo cả năm thành phần đều hỏng. Trạng thái PostgreSQL được suy ra qua Airflow, nên luôn báo hỏng khi Airflow hỏng. | Báo động giả. | Giao diện không gửi request mới khi request trước chưa trả lời (mục 8.2) |
| Trạng thái "ổn" của prediction service trên thanh trạng thái chỉ cho biết service trả lời được, không cho biết đã có model. | Sau khi xoá hết model, thanh trạng thái vẫn báo prediction service ổn. | Màn Model và Giám sát drift có trạng thái "chưa có model" riêng |
| Tên hiển thị của prediction drift trên dashboard hiện là "Model drift", khác tên trong tài liệu. | Người đọc tài liệu và người xem dashboard có thể tưởng là hai thứ khác nhau. | Đổi nhãn trên dashboard thành "Prediction drift" khi sửa giao diện lần tới |
| Simulation set của dataset giả lập là hữu hạn. Mỗi vòng tạo feedback data rồi retrain, các căn đã dùng bị bỏ khỏi nguồn của simulation agent (mục 6), nên nguồn nhỏ dần. | Sau nhiều vòng, simulation agent không còn đủ căn nhà để gửi số request lớn. | Chưa quyết định (要件定義書 mục 9, vấn đề 8) |
| Feedback record mang giá trị đã biến đổi theo scenario, nhưng ngày đăng bán vẫn là ngày gốc. | Model học thị trường mới qua giá và thành phố, không qua thời gian; simulation chưa tái hiện được việc căn nhà mới có ngày đăng bán mới. | Chấp nhận ở giai đoạn 1 |
| Ngưỡng data quality của input (mục 7.2), số mẫu tối thiểu của metric theo nhóm, và các điều kiện của alert rule (mục 7.5) là giá trị ban đầu, chưa hiệu chỉnh. | Có thể báo quá nhiều hoặc quá ít. | Hiệu chỉnh khi có thêm số đo từ các scenario |
| Ba thành phần mới (Prometheus, Pushgateway, Grafana) chạy liên tục trên máy 16 GB. | Chiếm thêm RAM; chưa đo. | Đo sau khi thêm; đặt giới hạn RAM cho từng container |
