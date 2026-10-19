# Warehouse & Citywide Estimation Schema Specification

Tài liệu này định nghĩa các dimension/fact trong Warehouse (`data/warehouse/`) và hai mart tách biệt: feature grid-day và mẫu huấn luyện station-day.

## 1. Sơ đồ Quan hệ Thực thể (Entity Architecture)
Hệ thống dùng `dim_grid_1km` và `dim_station` làm bảng chiều. Các fact khí tượng/vệ tinh nối với grid-day; fact quan trắc nối với station-day và lưu `grid_id` theo phiên bản lưới để hỗ trợ spatial join/đánh giá.

---

## 2. Chi tiết Các Bảng Tầng Warehouse (M1–M3)

### 2.1. Bảng `dim_grid_1km` (Đặc trưng Tĩnh Không gian)
* **Primary Key:** `grid_id` (`STRING`, định dạng `LON_XXXX_YYYY`)
* **Số dòng dự kiến:** ~1,580 dòng (toàn vùng Greater London)

| Tên cột | Kiểu dữ liệu | Nguồn gốc | Mô tả chi tiết |
| :--- | :--- | :--- | :--- |
| `grid_id` | `STRING` | Hệ thống tạo | Định danh duy nhất của ô lưới $1 \times 1\text{ km}$. |
| `centroid_lon` | `FLOAT64` | Hệ thống tạo | Kinh độ tâm ô lưới (`EPSG:4326`). |
| `centroid_lat` | `FLOAT64` | Hệ thống tạo | Vĩ độ tâm ô lưới (`EPSG:4326`). |
| `bng_easting` | `FLOAT64` | Hệ thống tạo | Tọa độ X tâm ô theo mét (`EPSG:27700` British National Grid). |
| `bng_northing` | `FLOAT64` | Hệ thống tạo | Tọa độ Y tâm ô theo mét (`EPSG:27700`). |
| `dist_to_charing_cross_km` | `FLOAT32` | Tính toán hình học | Khoảng cách Euclid tới tâm London (Charing Cross). |
| `dist_to_thames_km` | `FLOAT32` | OSM | Khoảng cách ngắn nhất từ tâm ô tới sông Thames. |
| `built_up_frac` | `FLOAT32` | ESA WorldCover 10m | Tỷ lệ diện tích/pixel thuộc lớp Built-up (Class 50); không đồng nghĩa chính xác với tỷ lệ mặt không thấm. |
| `tree_cover_frac` | `FLOAT32` | ESA WorldCover 10m | Tỷ lệ diện tích cây xanh đô thị (Class 10). |
| `major_road_length_m` | `FLOAT32` | OpenStreetMap | Tổng chiều dài đường `motorway`, `trunk`, `primary`, `secondary` trong ô (m). |

---

### 2.2. Bảng `fact_meteo_daily` (Khí tượng & Khí dung Nền)
* **Primary Key:** `(grid_id, date)`
* **Độ phủ:** Theo coverage nguồn; thiếu dữ liệu được giữ cờ và kiểm soát bằng ngưỡng cấu hình.

| Tên cột | Kiểu dữ liệu | Nguồn gốc | Mô tả chi tiết |
| :--- | :--- | :--- | :--- |
| `grid_id` | `STRING` | FK $\rightarrow$ `dim_grid_1km` | Mã ô lưới 1 km. |
| `date` | `DATE` | Hệ thống | Ngày quan trắc theo chuẩn UTC (`YYYY-MM-DD`). |
| `t2m_mean_c` | `FLOAT32` | `era5_land` | Nhiệt độ không khí trung bình 24h ở độ cao 2m ($^\circ\text{C}$). |
| `rh_mean_pct` | `FLOAT32` | `era5_land` | Độ ẩm tương đối trung bình 24h ($\%$), tính từ $T_{2m}$ và $T_d$. |
| `u10_vector_mean` | `FLOAT32` | `era5_land` | Thành phần gió Tây - Đông trung bình 24h ($\text{m/s}$). |
| `v10_vector_mean` | `FLOAT32` | `era5_land` | Thành phần gió Nam - Bắc trung bình 24h ($\text{m/s}$). |
| `wind_speed_scalar_mean` | `FLOAT32` | `era5_land` | Tốc độ gió vô hướng trung bình 24h ($\text{m/s}$). |
| `precip_sum_mm` | `FLOAT32` | `era5_land` | Tổng lượng mưa tích lũy 24h ($\text{mm}$). |
| `sp_mean_hpa` | `FLOAT32` | `era5_land` | Áp suất bề mặt trung bình 24h ($\text{hPa}$). |
| `blh_mean_m` | `FLOAT32` | `era5` | Độ cao lớp biên trung bình 24h ($\text{m}$). |
| `blh_min_m` | `FLOAT32` | `era5` | Độ cao lớp biên cực tiểu trong ngày (bắt nghịch nhiệt ban đêm, $\text{m}$). |
| `blh_max_m` | `FLOAT32` | `era5` | Độ cao lớp biên cực đại trong ngày ($\text{m}$). |
| `cams_aod_550` | `FLOAT32` | `cams` | Độ dày quang học aerosol mô hình ở 550nm (trường nền không bị mây che). |
| `cams_pm25_bg` | `FLOAT32` | `cams` | Nồng độ $PM_{2.5}$ nền từ mô hình hóa học CAMS ($\mu\text{g/m}^3$). |

---

### 2.3. Bảng `fact_satellite_daily` (Viễn thám Vệ tinh & Cờ Chất lượng)
* **Primary Key:** `(grid_id, date)`
* **Lưu ý:** Chấp nhận `NULL` ở các cột giá trị trung bình khi mây che phủ, nhưng các cột `*_valid_px` và `*_valid_flag` bắt buộc `NOT NULL`.

| Tên cột | Kiểu dữ liệu | Nguồn gốc | Mô tả chi tiết |
| :--- | :--- | :--- | :--- |
| `grid_id` | `STRING` | FK $\rightarrow$ `dim_grid_1km` | Mã ô lưới 1 km. |
| `date` | `DATE` | Hệ thống | Ngày quan trắc (`YYYY-MM-DD`). |
| `s5p_no2_mean` | `FLOAT32` | `s5p_offl_l3` | Mật độ cột $NO_2$ tầng đối lưu ($\text{mol/m}^2$). |
| `s5p_cloud_frac` | `FLOAT32` | `s5p_offl_l3` | Tỷ lệ mây che phủ từ cảm biến TROPOMI $[0, 1]$. |
| `s5p_no2_valid_px` | `INT16` | `s5p_offl_l3` | Số pixel S5P hợp lệ trong ô. |
| `s5p_no2_valid_flag` | `INT8` | `s5p_offl_l3` | `1` nếu có dữ liệu hợp lệ, `0` nếu bị mây/lỗi. |
| `modis_aod_055_mean` | `FLOAT32` | `modis_maiac` | Độ dày quang học MAIAC AOD ở bước sóng 550nm. |
| `modis_aod_valid_px` | `INT16` | `modis_maiac` | Số pixel MAIAC đạt chuẩn QA tốt nhất trong ô. |
| `modis_aod_valid_flag`| `INT8` | `modis_maiac` | `1` nếu có AOD hợp lệ, `0` nếu bị mây che. |
| `modis_lst_day_c` | `FLOAT32` | `modis_mod11a1`| Nhiệt độ bề mặt đất ban ngày ($^\circ\text{C}$). |
| `modis_lst_night_c` | `FLOAT32` | `modis_mod11a1`| Nhiệt độ bề mặt đất ban đêm ($^\circ\text{C}$ - chỉ thị Đảo nhiệt UHI). |
| `modis_lst_valid_flag`| `INT8` | `modis_mod11a1`| Cờ hợp lệ cho LST. |

---

### 2.4. Bảng `fact_ground_truth_daily` (Quan trắc Trạm Mặt đất)
* **Primary Key:** `(station_key, date)`
* **Foreign Keys:** `station_key` tham chiếu `dim_station`; `grid_id` tham chiếu `dim_grid_1km` theo phiên bản lưới.

| Tên cột | Kiểu dữ liệu | Nguồn gốc | Mô tả chi tiết |
| :--- | :--- | :--- | :--- |
| `station_key` | `STRING` | FK -> `dim_station` | Khóa nội bộ ổn định của trạm. |
| `station_id` | `STRING` | OpenAQ / LAQN | Mã trạm gốc để truy vết về nguồn. |
| `grid_id` | `STRING` | Spatial Join | Mã ô lưới 1 km chứa trạm quan trắc. |
| `date` | `DATE` | Hệ thống | Ngày quan trắc (`YYYY-MM-DD`). |
| `site_type` | `STRING` | LAQN / AURN | Phân loại trạm (`Roadside`, `Urban Background`, `Suburban`). |
| `pm25_obs` | `FLOAT32` | Quan trắc thật | Nồng độ $PM_{2.5}$ trung bình 24h ($\mu\text{g/m}^3$). |
| `valid_hours_count` | `INT8` | Tính toán | Số giờ có số đo hợp lệ trong ngày (yêu cầu $\ge 18$ để `is_valid_day = 1`). |
| `is_valid_day` | `INT8` | Tính toán | Cờ đánh dấu bản ghi đủ tiêu chuẩn làm nhãn huấn luyện. |

### 2.5. Bảng `dim_station` (Danh mục Trạm)
* **Primary Key:** `station_key` (`STRING`)
* **Unique Key:** `(source_name, source_station_id)` trong phiên bản metadata hiện hành.
* **Grain:** Một dòng mỗi trạm theo nguồn và phiên bản metadata.

| Tên cột | Kiểu dữ liệu | Nguồn gốc | Mô tả chi tiết |
| :--- | :--- | :--- | :--- |
| `station_key` | `STRING` | Hệ thống tạo | Khóa nội bộ ổn định, không thay đổi theo thứ tự tải dữ liệu. |
| `source_name` | `STRING` | Nguồn dữ liệu | LAQN, DEFRA AURN, OpenAQ hoặc nguồn tương ứng. |
| `source_station_id` | `STRING` | Nguồn dữ liệu | Mã trạm gốc để truy vết. |
| `station_name` | `STRING` | Nguồn dữ liệu | Tên trạm; có thể NULL nếu nguồn không cung cấp. |
| `longitude`, `latitude` | `FLOAT64` | Nguồn dữ liệu | Tọa độ trạm trong EPSG:4326, kèm nguồn/ngày cập nhật metadata. |
| `site_type` | `STRING` | LAQN / AURN | Loại vi môi trường; giữ giá trị gốc và phiên bản mapping nếu chuẩn hóa. |

`fact_ground_truth_daily` nên tham chiếu `station_key`; `grid_id` là kết quả spatial join theo đúng phiên bản lưới và cần được kiểm tra lại khi lưới thay đổi.

---

## 3. Feature Mart theo ô-ngày (`mart_grid_daily_features` - M4)
Được tạo từ tích Đề-các `(dim_grid_1km x dim_calendar)` rồi `LEFT JOIN` các fact feature theo `(grid_id, date)`, đồng thời bổ sung feature trễ và feature chu kỳ. Không gộp `fact_ground_truth_daily` thành nhãn grid-day mặc định; nhãn vẫn ở grain station-day và được nối với feature tại vị trí trạm trong bảng huấn luyện dẫn xuất.

## 4. Grain nhãn, feature và dự đoán
Không gộp bảng nhãn và bảng feature thành một khái niệm “ground truth theo ô”:

* `fact_ground_truth_daily`: grain `(station_key, date)`, chứa từng quan trắc trạm hợp lệ, mã trạm nguồn, `grid_id` chứa trạm, `site_type`, coverage và QC. Không gộp các trạm cùng ô mặc định.
* `mart_grid_daily_features`: grain đầy đủ `(grid_id, date)` cho mọi ô trong vùng nghiên cứu và ngày trong cấu hình. Chỉ chứa feature. Nếu thêm nhãn trạm nullable để tiện lấy mẫu train, nhãn phải giữ lineage tới `station_id` và không được xem là giá trị đại diện chính xác của toàn ô.
* `mart_station_daily_training`: bảng dẫn xuất tùy chọn, grain `(station_key, date)`, nối nhãn với feature tại ô chứa trạm. Dùng bảng này để train/evaluate; chia fold theo địa điểm/trạm trước mọi bước có fit hoặc dùng nhãn.
* `prediction_grid_daily`: grain `(run_id, grid_id, date)`, chứa `pm25_estimate`, khoảng bất định nếu có, model/version và chỉ báo hỗ trợ (`nearest_station_distance_km`, số trạm lân cận/độ phủ). Đây là đầu ra mô hình, không phải quan trắc.

### Chỉnh định nghĩa feature không gian
* `built_up_frac` biểu thị phần diện tích/pixel phân loại ESA WorldCover Class 50 trong ô; không gọi là tỷ lệ mặt không thấm nếu chưa có nguồn phù hợp.
* `major_road_length_m` nên được chuẩn hóa theo diện tích ô hoặc lưu cùng `major_road_density`; ghi rõ tag OSM và ngày trích xuất.
* Lưới 1 km là đơn vị xuất bản. Feature ERA5/ERA5-Land/CAMS và một số pixel vệ tinh có độ phân giải thô hơn; resampling không tạo thông tin mới. Giữ metadata độ phân giải nguồn và QA/valid-pixel flags.

Tên cột AOD chuẩn trong các tầng là `modis_aod_055_mean` để khớp contract.