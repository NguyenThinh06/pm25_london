# Analysis & Experimental Plan (Spatial Estimation)

Tài liệu này định nghĩa kiểm định cho bài toán ước lượng bề mặt PM2.5 theo ngày trên toàn Greater London từ các trạm hiện có. Đây không phải bài toán dự báo tương lai; feature cùng ngày chỉ hỗ trợ ước lượng hồi cứu/đồng thời.

## 1. Chiến lược Phân chia Dữ liệu & Kiểm định (Validation Protocol)
Tập dữ liệu có nhãn station-day được nối với feature tại vị trí trạm và đánh giá trên 2 chế độ:
1. **Chế độ A - Đánh giá Suy luận Không gian (Spatial Generalization - 5-Fold Spatial CV):**
   * Chia các địa điểm quan trắc thành 5 nhóm không giao nhau; các station ID cùng vị trí/cơ sở phải nằm cùng nhóm. Cân bằng theo `site_type` khi số lượng cho phép.
   * Tại mỗi fold, ẩn hoàn toàn khoảng 20% số trạm (theo nhóm) trong suốt cửa sổ dữ liệu 731 ngày (2023-01-01 → 2024-12-31, UTC) để làm tập Test.
   * *Giao thức thực tế hiện tại:* `train_spatial_models.py` dùng `GroupKFold(5)` trên 36 nhóm địa lý (`grid_id` + ô kề $\le 1.5\text{ km}$) cho 92 trạm. Đây là một giao thức spatial grouping cụ thể để tái lập kết quả, không tuyên bố "khử rò rỉ tuyệt đối". Chạy thêm cấu hình 79 nhóm (khoảng cách trạm $< 300\text{ m}$) làm phân tích độ nhạy (sensitivity analysis). Nhóm trạm `Unknown` được tách riêng để phân tích độc lập.
2. **Chế độ B - Kiểm tra độ ổn định / chuyển giao theo thời gian (Temporal Transferability - không phải dự báo tương lai):**
   * **Đã chốt Phương án B1:** Huấn luyện trên toàn bộ năm 2023, kiểm định (test) trên năm 2024 tại các trạm có mặt ở cả hai năm (35 trạm kiên trì). Tuyệt đối không điều chỉnh siêu tham số dựa trên dữ liệu 2024. Báo cáo rõ ràng đây là kiểm tra độ ổn định chuyển giao theo thời gian, **không phải dự báo tương lai**.
   * Bổ sung phương án B2 (blocked temporal CV theo khối tháng) làm phân tích độ nhạy ở giai đoạn sau. Thiết kế cũ (90 ngày) đã chính thức bị hủy bỏ.

## 2. Thước đo Đánh giá (Evaluation Metrics)
* **Root Mean Squared Error (RMSE):** Phạt nặng các sai số lớn vào những ngày bùng phát ô nhiễm (pollution episodes).
* **Mean Absolute Error (MAE):** Đo sai số tuyệt đối trung bình ($\mu\text{g/m}^3$).
* **Hệ số xác định ($R^2$):** Đánh giá tỷ lệ phương sai được giải thích trên cả 2 chiều: *Overall $R^2$*, *Spatial $R^2$* (trung bình theo trạm), và *Temporal $R^2$* (trung bình theo ngày).

## 3. Thiết kế 5 Câu hỏi Nghiên cứu & Thực nghiệm (Q1–Q5)

### Quy tắc áp dụng cho mọi chế độ đánh giá
Spatial CV là đánh giá chính. Nhóm station ID trùng vị trí/cùng địa điểm vào chung fold; không chia ngẫu nhiên theo dòng hoặc chỉ theo ngày. Mọi bước dựa trên nhãn trạm (IDW, KNN, kriging, spatial residual, imputation có fit, chọn feature) phải được fit/tạo lại trong train của từng fold. Residual feature cho train phải dùng residual out-of-fold/leave-one-station-out; không dùng residual in-sample của chính trạm. Tuning diễn ra bên trong train của fold ngoài.

Temporal split chỉ kiểm tra độ ổn định trong cửa sổ nghiên cứu. Khi dùng feature cùng ngày, không gọi kết quả là forecasting. Muốn tuyên bố dự báo tương lai phải thiết kế theo thời điểm phát hành và chỉ dùng dữ liệu thật sự khả dụng ở thời điểm đó; cửa sổ 731 ngày (hai năm) chỉ chứa hai chu kỳ mùa nên chưa đủ để kết luận tổng quát theo mùa hay giữa các năm.

Chỉ đánh giá dự đoán tại các quan trắc held-out; không xem toàn lưới dự đoán là ground truth. Báo cáo MAE, RMSE, bias và R² phụ trợ; thêm macro-metric theo trạm, phân tầng theo `site_type`, vùng nội/ngoại đô và khoảng cách đến trạm train. Bootstrap theo cụm trạm/địa điểm. Q1–Q5 là giả thuyết cần kiểm chứng, không phải kết quả định trước.

| Mã câu hỏi | Câu hỏi Nghiên cứu | Thiết kế Thực nghiệm (Experimental Setup) | Giả thuyết Khoa học (Hypothesis) |
| :--- | :--- | :--- | :--- |
| **Q1** | **Feature đa nguồn có cải thiện ước lượng tại trạm bị giữ lại so với baseline chỉ dùng trạm train không?** | So sánh train-mean, IDW và một GBDT trên cùng grouped spatial folds; nội suy chỉ truy cập trạm train. | Đánh giá mức thay đổi MAE/RMSE/bias trên held-out; không giả định trước mô hình hay loại trạm nào sẽ tốt hơn. |
| **Q2** | **Nhóm feature nào đóng góp thêm thông tin?** | Ablation theo nhóm khí tượng, tĩnh, vệ tinh, CAMS và residual; giữ nguyên fold, preprocessing và ngân sách tuning. Residual phải cross-fit trong train. | Kết luận theo chênh lệch metric held-out và khoảng bất định; không giả định trước nhóm nào cải thiện mạnh. |
| **Q3** | **Feature khí tượng trung bình ngày hay thống kê cực trị/gió có ích hơn?** | So sánh bộ khí tượng trung bình ngày với bộ bổ sung tốc độ gió vô hướng và thống kê BLH được định nghĩa trước. | Đánh giá metric tổng thể và theo nhóm ngày nồng độ cao; không suy ra nghịch nhiệt chỉ từ BLH tối thiểu nếu chưa kiểm chứng. |
| **Q4** | **Sai số thay đổi thế nào theo loại trạm, vùng và mức độ thưa trạm?** | Phân tầng metric held-out theo `site_type`, vùng nội/ngoại đô, khoảng cách tới trạm train và số trạm lân cận. | Mức độ đại diện/sai số có thể khác giữa roadside và background; kiểm chứng từ held-out data. |
| **Q5** | **Thiếu dữ liệu vệ tinh liên hệ thế nào với sai số ước lượng?** | Phân tầng held-out theo valid flag/cloud fraction; so sánh feature set có/không có vệ tinh và CAMS trên cùng các mẫu. | Tác động có thể phụ thuộc bối cảnh thời tiết và coverage; không giả định hướng tương quan hay mức suy giảm trước. |


## 4. Trạng thái thực hiện Q1–Q5 (Pha 1 kiểm kê)
Q1–Q5 là giả thuyết cần kiểm chứng. Bảng này ghi phần đã có artifact; **không** có câu hỏi nào được coi là đã hoàn thành.

| Câu hỏi | Đã làm | Chưa làm |
| :--- | :--- | :--- |
| **Q1** | Một lần chạy grouped spatial 5-fold trên 92 trạm/36 nhóm: Daily Train Mean, IDW, CAMS, LightGBM thuần và lai (`reports/tables/spatial_cv_metrics.csv`). Kết quả: IDW (RMSE 3,454) tốt hơn LightGBM lai (3,792) và thuần (3,912); Anomaly R² của hai mô hình LightGBM đều mang giá trị âm (-0.085 và -0.093). Kết quả hiện có cho thấy IDW đang tốt hơn LightGBM theo RMSE; chưa có cơ sở tuyên bố LightGBM cải thiện kỹ năng không gian. | Khoảng tin cậy (bootstrap theo cụm trạm), macro-metric theo trạm, nhiều seed/cấu hình, ablation. Kết quả chưa đủ để nói feature đa nguồn cải thiện so với baseline. |
| **Q2** | Chưa có ablation. (Có bảng feature importance, **không** phải ablation và không phải bằng chứng nhân quả.) | Ablation theo nhóm feature trên cùng fold; residual cross-fit. |
| **Q3** | Chưa. Chưa có BLH (V2). | So sánh bộ khí tượng; cần nguồn BLH (Q9 trong [data_contract.md](data_contract.md)). |
| **Q4** | Phân tầng theo `site_type` (`reports/tables/site_type_breakdown.csv`). | Phân tầng theo vùng nội/ngoại đô, khoảng cách tới trạm train, số trạm lân cận; bootstrap. |
| **Q5** | Chưa. | Phân tầng theo valid flag/cloud fraction; so sánh có/không vệ tinh và CAMS trên cùng mẫu. Cần QA vệ tinh đã xác minh trước (xem [data_contract.md §7](data_contract.md)). |

## 5. Thiết kế kiểm định chế độ B cho 731 ngày (Đề xuất mặc định: Phương án B1 làm chính, B2 làm phân tích độ nhạy)

**Dữ kiện từ dữ liệu hiện có** (nhãn hợp lệ, `is_valid_day = 1`): 2023 có 38 trạm và 8.011 nhãn; 2024 có 89 trạm và 12.340 nhãn; 35 trạm có mặt ở cả hai năm, 54 trạm chỉ có ở 2024, 3 trạm chỉ có ở 2023. Số nhãn mỗi tháng dao động từ 76 (02/2023) tới 1.473 (12/2024); số trạm có nhãn mỗi tháng tăng từ ~30 (2023) lên 72 (12/2024). Có 55/731 ngày không có trạm nào hợp lệ. Vì vậy mọi phép chia theo thời gian đồng thời thay đổi cả tập trạm (nhiễu chồng giữa "trôi theo thời gian" và "ngoại suy sang trạm mới").

| | Phương án B1 (Đề xuất làm chính) — train 2023, test theo khối tháng 2024 | Phương án B2 (Đề xuất độ nhạy) — K-fold theo khối tháng liền kề (blocked temporal CV) |
| :--- | :--- | :--- |
| **Cách làm** | Train: 2023-01 → 2023-12. Validation (chỉnh tham số/early stopping): hai tháng cuối của 2023 hoặc tách từ train theo khối. Test: từng khối tháng của 2024 (báo kết quả theo từng tháng). Đánh giá chính trên **các trạm có mặt ở cả hai năm** (35 trạm); báo thêm trên toàn bộ trạm 2024. | Chia 24 tháng thành các khối liền kề (ví dụ 6 khối × 4 tháng, hoặc 8 khối × 3 tháng), mỗi khối lần lượt làm test; chèn khoảng đệm ± vài ngày giữa train và test để giảm rò rỉ tự tương quan. Có thể kết hợp trạm cố định (chỉ trạm có mặt ở cả train và test) để cô lập hiệu ứng thời gian. |
| **Ưu** | Đơn giản, dễ diễn giải, đúng trình tự thời gian; test theo tháng cho thấy sự thay đổi theo mùa của 2024. | Dùng cả hai năm cho cả train và test; mỗi mùa xuất hiện ở cả hai phía; ổn định thống kê hơn; ít nhạy với giai đoạn mạng trạm mở rộng cuối 2024. |
| **Nhược** | Train chỉ có 38 trạm và 8.011 nhãn, tháng 02/2023 gần như trống (76 nhãn); 54/89 trạm của 2024 không có trong train nên khó tách hiệu ứng thời gian với hiệu ứng không gian nếu không giới hạn ở 35 trạm chung; một chuỗi test duy nhất (rất ít thông tin về mùa). | Mô hình train trên "tương lai" để dự đoán "quá khứ" (chấp nhận được vì không phải dự báo, nhưng phải ghi rõ); tự tương quan theo thời gian vẫn còn rò rỉ dù có khoảng đệm; tốn tính toán hơn; cần quy tắc rõ khi một khối thiếu dữ liệu. |

Cả hai phương án giữ các quy tắc ở mục 3: mọi bước dựa trên nhãn (IDW, nền mạng trạm, imputation, chọn feature) được tạo lại trong train, và kết quả chỉ gọi là "độ ổn định chuyển giao theo thời gian", **không gọi là dự báo tương lai**. Tuyệt đối không tuning mô hình dựa trên tập test 2024.
