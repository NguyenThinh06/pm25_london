# Analysis & Experimental Plan (Spatial Estimation)

Tài liệu này định nghĩa kiểm định cho bài toán ước lượng bề mặt PM2.5 theo ngày trên toàn Greater London từ các trạm hiện có. Đây không phải bài toán dự báo tương lai; feature cùng ngày chỉ hỗ trợ ước lượng hồi cứu/đồng thời.

## 1. Chiến lược Phân chia Dữ liệu & Kiểm định (Validation Protocol)
Tập dữ liệu có nhãn station-day được nối với feature tại vị trí trạm và đánh giá trên 2 chế độ:
1. **Chế độ A - Đánh giá Suy luận Không gian (Spatial Generalization - 5-Fold Spatial CV):**
   * Chia các địa điểm quan trắc thành 5 nhóm không giao nhau; các station ID cùng vị trí/cơ sở phải nằm cùng nhóm. Cân bằng theo `site_type` khi số lượng cho phép.
   * Tại mỗi fold, ẩn hoàn toàn 20% số trạm trong suốt 90 ngày để làm tập Test.
2. **Chế độ B - Kiểm tra độ ổn định theo thời gian (không phải dự báo tương lai):**
   * Train: Ngày 1 $\rightarrow$ Ngày 65.
   * Validation: Ngày 66 $\rightarrow$ Ngày 75 (dùng để tinh chỉnh hyperparameter và early stopping).
   * Test: Ngày 76 $\rightarrow$ Ngày 90.

## 2. Thước đo Đánh giá (Evaluation Metrics)
* **Root Mean Squared Error (RMSE):** Phạt nặng các sai số lớn vào những ngày bùng phát ô nhiễm (pollution episodes).
* **Mean Absolute Error (MAE):** Đo sai số tuyệt đối trung bình ($\mu\text{g/m}^3$).
* **Hệ số xác định ($R^2$):** Đánh giá tỷ lệ phương sai được giải thích trên cả 2 chiều: *Overall $R^2$*, *Spatial $R^2$* (trung bình theo trạm), và *Temporal $R^2$* (trung bình theo ngày).

## 3. Thiết kế 5 Câu hỏi Nghiên cứu & Thực nghiệm (Q1–Q5)

### Quy tắc áp dụng cho mọi chế độ đánh giá
Spatial CV là đánh giá chính. Nhóm station ID trùng vị trí/cùng địa điểm vào chung fold; không chia ngẫu nhiên theo dòng hoặc chỉ theo ngày. Mọi bước dựa trên nhãn trạm (IDW, KNN, kriging, spatial residual, imputation có fit, chọn feature) phải được fit/tạo lại trong train của từng fold. Residual feature cho train phải dùng residual out-of-fold/leave-one-station-out; không dùng residual in-sample của chính trạm. Tuning diễn ra bên trong train của fold ngoài.

Temporal split chỉ kiểm tra độ ổn định trong cửa sổ nghiên cứu. Khi dùng feature cùng ngày, không gọi kết quả là forecasting. Muốn tuyên bố dự báo tương lai phải thiết kế theo thời điểm phát hành và chỉ dùng dữ liệu thật sự khả dụng ở thời điểm đó; 90 ngày chưa đủ để kết luận tổng quát theo mùa.

Chỉ đánh giá dự đoán tại các quan trắc held-out; không xem toàn lưới dự đoán là ground truth. Báo cáo MAE, RMSE, bias và R² phụ trợ; thêm macro-metric theo trạm, phân tầng theo `site_type`, vùng nội/ngoại đô và khoảng cách đến trạm train. Bootstrap theo cụm trạm/địa điểm. Q1–Q5 là giả thuyết cần kiểm chứng, không phải kết quả định trước.

| Mã câu hỏi | Câu hỏi Nghiên cứu | Thiết kế Thực nghiệm (Experimental Setup) | Giả thuyết Khoa học (Hypothesis) |
| :--- | :--- | :--- | :--- |
| **Q1** | **Feature đa nguồn có cải thiện ước lượng tại trạm bị giữ lại so với baseline chỉ dùng trạm train không?** | So sánh train-mean, IDW và một GBDT trên cùng grouped spatial folds; nội suy chỉ truy cập trạm train. | Đánh giá mức thay đổi MAE/RMSE/bias trên held-out; không giả định trước mô hình hay loại trạm nào sẽ tốt hơn. |
| **Q2** | **Nhóm feature nào đóng góp thêm thông tin?** | Ablation theo nhóm khí tượng, tĩnh, vệ tinh, CAMS và residual; giữ nguyên fold, preprocessing và ngân sách tuning. Residual phải cross-fit trong train. | Kết luận theo chênh lệch metric held-out và khoảng bất định; không giả định trước nhóm nào cải thiện mạnh. |
| **Q3** | **Feature khí tượng trung bình ngày hay thống kê cực trị/gió có ích hơn?** | So sánh bộ khí tượng trung bình ngày với bộ bổ sung tốc độ gió vô hướng và thống kê BLH được định nghĩa trước. | Đánh giá metric tổng thể và theo nhóm ngày nồng độ cao; không suy ra nghịch nhiệt chỉ từ BLH tối thiểu nếu chưa kiểm chứng. |
| **Q4** | **Sai số thay đổi thế nào theo loại trạm, vùng và mức độ thưa trạm?** | Phân tầng metric held-out theo `site_type`, vùng nội/ngoại đô, khoảng cách tới trạm train và số trạm lân cận. | Mức độ đại diện/sai số có thể khác giữa roadside và background; kiểm chứng từ held-out data. |
| **Q5** | **Thiếu dữ liệu vệ tinh liên hệ thế nào với sai số ước lượng?** | Phân tầng held-out theo valid flag/cloud fraction; so sánh feature set có/không có vệ tinh và CAMS trên cùng các mẫu. | Tác động có thể phụ thuộc bối cảnh thời tiết và coverage; không giả định hướng tương quan hay mức suy giảm trước. |