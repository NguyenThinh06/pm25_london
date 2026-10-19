# Architecture & Methodology Decision Log (ADR)

Tài liệu này lưu trữ các quyết định thiết kế quan trọng trong quá trình xây dựng pipeline và mô hình hóa, nêu rõ bối cảnh, các phương án đã cân nhắc và lý do khoa học cho phương án được chọn.

---

### ADR-001: Tách biệt vận tốc gió vô hướng (`wind_speed_scalar`) và vector gió (`u10`, `v10`) khi gom nhóm theo ngày
* **Trạng thái:** Đã chấp thuận (Accepted)
* **Bối cảnh:** Dữ liệu ERA5-Land cung cấp thành phần gió $u_{10}$ và $v_{10}$ theo từng giờ. Nếu chỉ lấy trung bình cộng $u_{10}$ và $v_{10}$ trong 24 giờ rồi mới tính tốc độ gió, những ngày gió đổi chiều (ví dụ sáng gió Đông $u = -4\text{ m/s}$, chiều gió Tây $u = +4\text{ m/s}$) sẽ cho vector trung bình bằng $0\text{ m/s}$ (trạng thái lặng gió giả tạo).
* **Quyết định:** 
  1. Tại mỗi giờ $t$, tính tốc độ gió tức thời: $ws_t = \sqrt{u_{10,t}^2 + v_{10,t}^2}$.
  2. Lấy trung bình 24 giờ của $ws_t$ để tạo biến `wind_speed_scalar_mean` (đại diện cho năng lượng khuếch tán cơ học).
  3. Lấy trung bình 24 giờ của $u_{10,t}$ và $v_{10,t}$ riêng biệt để đại diện cho hướng vận chuyển ròng (net advection).

---

### ADR-002: Kết hợp ERA5-Land (9 km) và ERA5 gốc (28 km) thay vì dùng một nguồn duy nhất
* **Trạng thái:** Đã chấp thuận (Accepted)
* **Bối cảnh:** ERA5 gốc có biến Độ cao lớp biên (`BLH`) cực kỳ quan trọng nhưng độ phân giải quá thô ($0.25^\circ \approx 28\text{ km}$), chỉ phủ vài điểm lưới trên toàn bộ London. Ngược lại, ERA5-Land có độ phân giải cao hơn ($0.1^\circ \approx 9\text{ km}$) nhưng lại thiếu biến `BLH`.
* **Quyết định:** Lấy các biến nhiệt - ẩm - gió bề mặt từ **ERA5-Land**, và chỉ lấy riêng `BLH` (cùng `BLH_min` ban đêm, `BLH_max` ban ngày) từ **ERA5 gốc**.
* **Hệ quả:** Giảm thiểu sai số đại diện không gian cho nhiệt độ và độ ẩm đô thị mà vẫn giữ được thông tin vật lý về nghịch nhiệt lớp biên.

---

### ADR-003: Sử dụng nội suy Bilinear khi trích xuất dữ liệu Khí tượng/CAMS xuống lưới 1 km
* **Trạng thái:** Đã chấp thuận (Accepted)
* **Bối cảnh:** Khi gọi `reduceRegions` trên Google Earth Engine (GEE) từ ảnh độ phân giải thô (9–28 km) xuống lưới 1 km, phép lấy mẫu mặc định (`nearest neighbor`) gán cùng một giá trị cho hàng chục ô 1 km lân cận, tạo ra ranh giới bậc thang phi vật lý (blocky artifacts) trên bản đồ dự báo.
* **Quyết định:** Có thể dùng bilinear cho trường liên tục khi phù hợp với biến và quy trình trích xuất, nhưng phải lưu độ phân giải nguồn và không diễn giải giá trị resample như thông tin quan trắc 1 km mới. Với dữ liệu vệ tinh có mask (MODIS AOD, S5P $NO_2$), áp dụng QA và lưu coverage/pixel hợp lệ theo đúng product; không giả định một pixel gốc tương ứng đơn giản với từng ô 1 km.

---

### ADR-004: Giữ lại các giá trị $NO_2$ âm nhỏ của Sentinel-5P và biến cờ thiếu (`_valid_flag`) của MODIS AOD
* **Trạng thái:** Đã chấp thuận (Accepted)
* **Bối cảnh:** 
  1. Phép đo cột $NO_2$ tầng đối lưu của Sentinel-5P có nhiễu ngẫu nhiên quanh mức 0 ở những vùng không khí sạch; nếu cắt bỏ toàn bộ giá trị $< 0$ sẽ tạo ra thiên lệch dương (positive bias).
  2. Tại London, mây che phủ làm mất $>75\%$ dữ liệu MODIS MAIAC AOD vào mùa Thu - Đông. Tuy nhiên, việc mất dữ liệu không ngẫu nhiên (Missing Not At Random - MNAR): ngày quang mây (có AOD) thường gắn với hệ thống áp cao tĩnh lặng gây ô nhiễm nặng, còn ngày nhiều mây (mất AOD) thường gắn với gió Tây mang mưa từ Đại Tây Dương làm sạch không khí.
* **Quyết định:**
  1. Chỉ lọc bỏ các giá trị $NO_2 < -0.001\text{ mol/m}^2$ (nhiễu cực đoan), giữ nguyên các giá trị âm nhỏ trong khoảng $[-0.001, 0]$.
  2. Không loại bỏ các dòng thiếu MODIS AOD; thay vào đó, lưu bộ 3 cột cho mỗi biến vệ tinh: `*_mean`, `*_valid_px`, và `*_valid_flag` (0/1). Bản thân cột cờ `aod_valid_flag` được đưa vào mô hình như một chỉ báo trạng thái thời tiết synoptic.

---

### ADR-005: Thiết kế Đánh giá Chéo theo Cụm Không gian (Spatial Station Hold-out) kết hợp Thời gian
* **Trạng thái:** Đã chấp thuận (Accepted)
* **Bối cảnh:** Trong cùng một ngày $t$, các ô lưới 1 km tại London chia sẻ trường thời tiết vùng rất giống nhau. Nếu chia tập Train/Test ngẫu nhiên theo dòng `(grid_id, date)`, mô hình sẽ học thuộc lòng ngày $t$ từ trạm A để đoán trạm B cách đó 2 km (Data Leakage), dẫn đến điểm số ảo khi đánh giá nhưng thất bại khi suy luận ở các vùng không có trạm.
* **Quyết định:** Dùng **Grouped Spatial K-Fold** theo cụm địa điểm/trạm làm đánh giá chính cho khả năng suy rộng tới vị trí chưa có trạm. Temporal split chỉ là kiểm tra độ ổn định trong cửa sổ nghiên cứu, không đại diện dự báo tương lai. Mọi feature dựa trên nhãn phải được tạo lại chỉ từ train trong từng fold.