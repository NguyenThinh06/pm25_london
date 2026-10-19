# Business Case: Citywide Daily PM2.5 Estimation Across Greater London

## 1. Bối cảnh & Vấn đề (Problem Statement)
Bụi mịn $PM_{2.5}$ (hạt lơ lửng có đường kính khí động học $\le 2.5\ \mu\text{m}$) là tác nhân hàng đầu gây ra các bệnh lý tim mạch và hô hấp tại các siêu đô thị. Tại vùng Greater London (~1,572 $\text{km}^2$), mặc dù mạng lưới quan trắc mặt đất (LAQN, DEFRA AURN, OpenAQ) hoạt động liên tục, các trạm đo này có hai nhược điểm chí mạng:
1. **Độ phủ không gian thưa và lệch (Spatial Sparsity & Bias):** Các trạm tập trung dày đặc ở khu vực nội đô (Central London) và sát lề đường lớn (Roadside), trong khi các khu dân cư ngoại ô (Outer London) có những khoảng trống từ 5–15 km không có trạm đo.
2. **Không đại diện cho toàn bộ ô lưới (Point-to-Area Mismatch):** Một trạm đo đặt sát đường cao tốc chỉ phản ánh ô nhiễm cục bộ trong bán kính vài chục mét, không phản ánh mức phơi nhiễm trung bình của cư dân trong toàn bộ ô lưới $1 \times 1\text{ km}$.

Ngược lại, dữ liệu vệ tinh quang học (MODIS AOD) và khí vết (Sentinel-5P $NO_2$) cung cấp góc nhìn bao quát toàn thành phố nhưng lại bị mất dữ liệu nghiêm trọng do mây che phủ (đặc biệt vào mùa Thu - Đông tại Anh) và chỉ đo tổng cột khí quyển (columnar density) thay vì nồng độ sát mặt đất (surface concentration).

## 2. Mục tiêu Dự án (Project Objectives)
Xây dựng hệ thống Data Pipeline và mô hình Học máy Không gian - Thời gian nhằm:
* **Ước lượng nồng độ $PM_{2.5}$ trung bình ngày ($\mu\text{g/m}^3$)** tại **mọi ô lưới $1 \times 1\text{ km}$** trên toàn bộ vùng Greater London trong cửa sổ 90 ngày liên tục.
* **Giải quyết bài toán khuyết thiếu dữ liệu vệ tinh** bằng cách tích hợp dữ liệu tái phân tích khí tượng (ERA5-Land, ERA5), dữ liệu nền Aerosol (CAMS) và đặc trưng tĩnh đô thị (OSM, ESA WorldCover).
* **Định lượng mức độ không chắc chắn (Uncertainty) và đóng góp của từng nguồn dữ liệu** thông qua hệ thống câu hỏi nghiên cứu thực nghiệm (Ablation Studies Q1–Q5).

## 3. Đơn vị Phân tích Cơ sở (Unit of Analysis)
* **Không gian:** Lưới chuẩn $1 \times 1\text{ km}$ bao phủ vùng Greater London (~1,580 ô lưới), định nghĩa trên hệ tọa độ chiếu phẳng British National Grid (`EPSG:27700`) để bảo toàn diện tích và khoảng cách mét, sau đó ánh xạ sang `EPSG:4326` khi truy vấn API.
* **Thời gian:** Độ phân giải theo ngày (Daily UTC: `00:00:00` đến `23:59:59`).
* **Grain nhãn/huấn luyện:** Quan trắc theo `(station_id, date)` (kèm nguồn để phân biệt ID trùng); dữ liệu tại các trạm cùng ô không tự động gộp.
* **Grain ước lượng:** Bản đồ đầu ra theo `(grid_id, date)` cho toàn bộ lưới trong vùng nghiên cứu.

## 4. Giá trị Thực tiễn (Business & Policy Value)
1. **Đánh giá chính sách ULEZ (Ultra Low Emission Zone):** Cung cấp bản đồ phơi nhiễm liên tục giúp so sánh nồng độ $PM_{2.5}$ giữa các vùng trong và ngoài vành đai giảm phát thải.
2. **Dịch tễ học Môi trường:** Cung cấp dữ liệu đầu vào không bị đứt gãy theo không gian cho các nghiên cứu sức khỏe cộng đồng theo mã bưu chính (Postcode/LSOA).
3. **Khả năng tái lập (Reproducibility):** Toàn bộ quy trình từ dữ liệu nguồn bất biến đến bảng feature và dự đoán được đóng gói tự động, kiểm soát lineage giữa quan trắc thật và kết quả mô hình.

## 5. Cách diễn giải mục tiêu ước lượng
Mục tiêu là ước lượng bề mặt PM2.5 theo ô-ngày cho mọi ô lưới giao với Greater London, dựa trên quan trắc trạm hiện có và feature phụ trợ. Đây là ước lượng không gian hồi cứu/đồng thời, không phải dự báo tương lai.

Quan trắc trạm là nhãn tham chiếu tại vị trí trạm, không phải phép đo trực tiếp của trung bình diện tích cả ô 1 km. Giữ từng quan trắc theo `(station_id, date)` và `site_type`; không gộp nhiều trạm cùng ô thành một nhãn duy nhất nếu chưa xác định quy tắc tổng hợp. Ô không có trạm có kết quả mô hình, không có ground truth trực tiếp.

Độ phân giải 1 km mô tả lưới đầu ra, không đảm bảo đầu vào hoặc độ chính xác thực địa có độ phân giải 1 km. Báo cáo cần kèm sai số spatial holdout, bất định và chỉ báo khoảng cách/độ phủ trạm. Không dùng bản đồ như phép đo chính thức, bằng chứng nhân quả về ULEZ hay dữ liệu phơi nhiễm cá nhân nếu chưa thẩm định độc lập.