# Warehouse & Citywide Estimation Schema Specification (Contract V1)

Tài liệu này định nghĩa các dimension/fact trong Warehouse (`data/warehouse/`) và hai mart tách biệt: feature grid-day và mẫu huấn luyện station-day. Quy tắc, định nghĩa và giới hạn nằm ở [data_contract.md](data_contract.md).

**Chú giải trạng thái** (cột "TT"):
* **V1** — cột có thật trong parquet hiện tại, ngữ nghĩa đã kiểm chứng.
* **V1?** — cột có thật nhưng ngữ nghĩa/QA/đơn vị **chưa xác minh**; không dùng cho model chứng nhận.
* **V2** — dự kiến, **chưa tồn tại** trong parquet (không được mô tả như cột hiện có).
* "Chỉ ở tầng X" — cột chỉ xuất hiện ở một tầng, không lan sang tầng khác.

Kiểu ghi theo parquet thực tế. Nullable: "không" = 0 NULL trong artifact hiện tại và được code đảm bảo hoặc quan sát; "có" = NULL hợp lệ.

## 1. Sơ đồ Quan hệ Thực thể (Entity Architecture)
Hệ thống dùng `dim_grid_1km` và `dim_station` làm bảng chiều. Các fact khí tượng/vệ tinh nối với grid-day; fact quan trắc nối với station-day và lưu `grid_id` theo phiên bản lưới để hỗ trợ spatial join/đánh giá.

**Quy ước chung**
* `date`: ngày **UTC**, chuỗi ISO `YYYY-MM-DD` ở warehouse và processed (xem [data_contract.md §3](data_contract.md)).
* `grid_id`: `grid_{E_góc}_{N_góc}`, tọa độ mét EPSG:27700 của **góc dưới-trái** ô 1 km (ví dụ `grid_508000_177000`). **Không** có định dạng `LON_XXXX_YYYY`.
* `bng_easting/bng_northing` ở `dim_grid_1km` và mart là **tâm ô** (góc + 500 m); ở `dim_station` là **tọa độ trạm thật**. Cùng tên cột, khác nghĩa.

---

## 2. Chi tiết Các Bảng Tầng Warehouse (M1–M3)

### 2.1. Bảng `dim_grid_1km` (Đặc trưng Tĩnh Không gian)
* **Primary Key:** `grid_id` (`STRING`, định dạng `grid_{E_góc}_{N_góc}`)
* **Số dòng:** 1.581 dòng = **1.577 ô canonical** (`in_boundary = True`: tiêu chí chuẩn là **tâm ô nằm trong ranh giới** ONS Region London Dec 2023, không phải "nằm hoàn toàn trong ranh giới") + **4 ô ngữ cảnh** (`in_boundary = False`, giữ vì chứa trạm; xem [data_contract.md §4](data_contract.md)).
* **Ghi bởi:** `build_dim_grid_1km.py` (cột 1–7); `build_spatial_static_features.py` cập nhật cột feature tĩnh (8–13). Chạy lại `build_dim_grid_1km.py` sẽ ghi đè các cột tĩnh.

| Tên cột | Kiểu | Nullable | Đơn vị | Nguồn | Mô tả / quy tắc | TT |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `grid_id` | `STRING` | không | — | Hệ thống tạo | Định danh ô 1×1 km. | V1 |
| `centroid_lon` | `FLOAT64` | không | độ (EPSG:4326) | Hệ thống tạo | Kinh độ tâm ô. | V1 |
| `centroid_lat` | `FLOAT64` | không | độ (EPSG:4326) | Hệ thống tạo | Vĩ độ tâm ô. | V1 |
| `bng_easting` | `FLOAT64` | không | m (EPSG:27700) | Hệ thống tạo | X của **tâm ô** (= góc + 500). | V1 |
| `bng_northing` | `FLOAT64` | không | m (EPSG:27700) | Hệ thống tạo | Y của **tâm ô** (= góc + 500). | V1 |
| `dist_to_charing_cross_km` | `FLOAT32` | không | km | Hình học | Khoảng cách Euclid trong EPSG:27700 từ tâm ô tới Charing Cross. | V1 |
| `in_boundary` | `BOOL` | không | — | `build_dim_grid_1km.py` | `True` nếu **tâm ô** nằm trong ranh giới ONS London (canonical); `False` = ô ngữ cảnh. Không có nghĩa "toàn ô nằm trong ranh giới". | V1 |
| `built_up_frac` | `FLOAT32` | không (null→0 trong code) | tỷ lệ [0, 1] | ESA WorldCover **v100 (2020)**, 10 m | Tỷ lệ mẫu 30 m có lớp Built-up (Class 50) trong ô; không đồng nghĩa với tỷ lệ bề mặt không thấm. Reducer null bị ép về 0 nên chưa phân biệt được 0 thật và thiếu dữ liệu; bị chặn ở `mode="certified"`. | **V1?** |
| `tree_cover_frac` | `FLOAT32` | không (null→0 trong code) | tỷ lệ [0, 1] | ESA WorldCover **v100 (2020)**, 10 m | Tỷ lệ mẫu 30 m có lớp Tree cover (Class 10). Reducer null bị ép về 0; bị chặn ở `mode="certified"`. | **V1?** |
| `dist_to_thames_km` | `FLOAT32` | không (null→0 trong code) | km | ESA WorldCover v100, lớp 80 | **Tên không đúng nội dung.** Giá trị là khoảng cách raster tới pixel *nước thường trực bất kỳ* (Class 80), không phải sông Thames; toàn London chỉ 0,02–2,15 km. Bị chặn ở `mode="certified"` (Phase 2). Đề xuất cho Phase 3 (Q3): đổi tên chuẩn thành `dist_to_nearest_mapped_water_km` (chưa thực hiện migration trên parquet hiện tại); chỉ dùng tên Thames nếu tính từ geometry vector sông thực tế. | **V1?** |
| `elevation_m` | `FLOAT32` | không (null→0 trong code) | m | `USGS/SRTMGL1_003` (30 m) | Độ cao trung bình trong ô. Reducer null bị ép về 0; bị chặn ở `mode="certified"`. | **V1?** |
| `population_density` | `FLOAT32` | không (null→0 trong code) | **người/pixel 100 m** (không phải người/km²) | `JRC/GHSL/P2023A/GHS_POP` (100 m), band `population_count` | Trung bình số người/pixel 100 m lấy mẫu 30 m trong ô. Bị chặn ở `mode="certified"` (Phase 2). Đề xuất cho Phase 3 (Q4): ưu tiên chuyển sang `ghsl_population_count` (tổng dân số trong ô); chỉ tạo mật độ sau khi xác minh diện tích hợp lệ và pixel biên (chưa thực hiện migration trên parquet hiện tại). | **V1?** |
| `major_road_length_m` | `FLOAT32` | không | m | DfT Major Road Network 2018 (Open Roads) | Tổng chiều dài đoạn đường giao với hộp ô 1 km; không lọc loại đường; không chuẩn hóa theo diện tích; ô không có đường = 0. Không dùng OSM. | V1 |

**Cột dự kiến (V2):** `major_road_density` (chuẩn hóa theo diện tích).

---

### 2.2. Bảng `fact_meteo_daily` (Khí tượng & Khí dung Nền)
* **Primary Key:** `(grid_id, date)`; **FK:** `grid_id → dim_grid_1km`.
* **Số dòng hiện có:** 1.155.711 = 1.581 × 731 (không NULL ở mọi cột).
* **Cách lấy:** ERA5-Land (`ECMWF/ERA5_LAND/HOURLY`, ~11 km) và CAMS NRT (`ECMWF/CAMS/NRT`, ~44 km) lấy tại **điểm tâm ô** (`Reducer.first()`, không bilinear), trung bình/tổng theo ngày UTC. Giá trị bị lặp giữa các ô lân cận do pixel thô.

| Tên cột | Kiểu | Nullable | Đơn vị | Nguồn | Mô tả / quy tắc | TT |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `grid_id` | `STRING` | không | — | FK → `dim_grid_1km` | Mã ô lưới. | V1 |
| `date` | `STRING` (ISO) | không | ngày UTC | Hệ thống | `YYYY-MM-DD`. | V1 |
| `t2m_mean_c` | `FLOAT32` | không | °C | ERA5-Land | Nhiệt độ 2 m trung bình 24 h (K − 273,15). | V1 |
| `rh_mean_pct` | `FLOAT32` | không | % | ERA5-Land | Độ ẩm tương đối trung bình 24 h, tính theo giờ từ nhiệt độ và điểm sương 2 m (Magnus), trần 100. | V1 |
| `u10_vector_mean` | `FLOAT32` | không | m/s | ERA5-Land | Thành phần gió Tây–Đông trung bình 24 h. | V1 |
| `v10_vector_mean` | `FLOAT32` | không | m/s | ERA5-Land | Thành phần gió Nam–Bắc trung bình 24 h. | V1 |
| `wind_speed_scalar_mean` | `FLOAT32` | không | m/s | ERA5-Land | Trung bình 24 h của tốc độ gió tức thời (ADR-001). | V1 |
| `precip_sum_mm` | `FLOAT32` | không | mm | ERA5-Land | Tổng 24 h (`total_precipitation_hourly` × 1000). | V1 |
| `sp_mean_hpa` | `FLOAT32` | không | hPa | ERA5-Land | Áp suất bề mặt trung bình 24 h. | V1 |
| `cams_aod_550` | `FLOAT32` | không | không thứ nguyên | CAMS NRT | AOD mô hình ở 550 nm (`model_forecast_hour < 12`). | V1 |
| `cams_pm25_bg` | `FLOAT32` | không | µg/m³ | CAMS NRT | PM2.5 nền từ mô hình hóa học (×1e9 từ kg/m³). | V1 |
| `blh_mean_m` | `FLOAT32` | — | m | ERA5 (chưa có nguồn) | Độ cao lớp biên trung bình 24 h. **Chưa tồn tại**: ERA5-Land không có BLH và `extract_gee_features.py` chưa có nguồn ERA5. | V2 |
| `blh_min_m` | `FLOAT32` | — | m | ERA5 (chưa có nguồn) | BLH cực tiểu trong ngày. **Chưa tồn tại.** | V2 |
| `blh_max_m` | `FLOAT32` | — | m | ERA5 (chưa có nguồn) | BLH cực đại trong ngày. **Chưa tồn tại.** | V2 |

---

### 2.3. Bảng `fact_satellite_daily` (Viễn thám Vệ tinh & Cờ Chất lượng)
* **Primary Key:** `(grid_id, date)`; **FK:** `grid_id → dim_grid_1km`.
* **Số dòng hiện có:** 1.155.711. `*_valid_px` và `*_valid_flag` `NOT NULL` do code `fillna(0)`: thiếu chunk sẽ thành 0 và không phân biệt được với "không có quan sát" (hiện không có ô-ngày nào thiếu chunk).
* **Cách lấy:** polygon ô 1 km, `ee.Reducer.mean()` + `ee.Reducer.count()` ở `scale = 1000 m`, `EPSG:27700`.
* **Ngữ nghĩa `*_valid_px` / `*_valid_flag`:** `valid_px` là `count()` của mẫu không bị mask trong polygon; giá trị quan sát thật chỉ ∈ {0, 1}. `valid_flag = valid_px > 0`, tương đương "giá trị trung bình không NULL". **Không** phải "số pixel gốc trong ô" và **không** phải xác nhận QA đầy đủ.

| Tên cột | Kiểu | Nullable | Đơn vị | Nguồn | Mô tả / quy tắc | TT |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `grid_id` | `STRING` | không | — | FK → `dim_grid_1km` | Mã ô lưới. | V1 |
| `date` | `STRING` (ISO) | không | ngày UTC | Hệ thống | `YYYY-MM-DD`. | V1 |
| `s5p_no2_mean` | `FLOAT32` | có (67,65% NULL) | mol/m² | `COPERNICUS/S5P/OFFL/L3_NO2`, band `tropospheric_NO2_column_number_density` | Cột NO₂ tầng đối lưu. Pixel gốc ~5,5 km; resample không tăng phân giải. Code **không** lọc `qa_value`; theo tài liệu GEE collection đã ngưỡng khi ingest (chưa đối chiếu trực tiếp). | **V1?** (QA) |
| `s5p_cloud_frac` | `FLOAT32` | có (21,11% NULL) | [0, 1] | `COPERNICUS/S5P/OFFL/L3_NO2`, band `cloud_fraction` | Phần mây từ TROPOMI. Chưa có cờ coverage / QA bitmask; bị chặn ở `mode="certified"`. | **V1?** |
| `s5p_no2_valid_px` | `INT16` | không | số mẫu (∈ {0, 1}) | `COPERNICUS/S5P/OFFL/L3_NO2` | `count()` ở scale 1000 m; **không phải số pixel S5P trong ô.** Dự kiến đổi tên trung tính ở Pha 3. | **V1?** |
| `s5p_no2_valid_flag` | `INT8` | không | 0/1 | `COPERNICUS/S5P/OFFL/L3_NO2` | `1` nếu `valid_px > 0`; không có nghĩa "đạt QA". | **V1?** |
| `modis_lst_day_c` | `FLOAT32` | có (72,25% NULL) | °C | `MODIS/061/MOD11A1` (Terra), `LST_Day_1km` | `LST × 0.02 − 273,15`. Code **không** áp dụng `QC_Day`. | **V1?** (QA) |
| `modis_lst_night_c` | `FLOAT32` | có (68,15% NULL) | °C | `MODIS/061/MOD11A1` (Terra), `LST_Night_1km` | Như trên; code **không** áp dụng `QC_Night`. | **V1?** (QA) |
| `modis_lst_day_valid_px` | `INT16` | không | số mẫu (∈ {0, 1}) | `MODIS/061/MOD11A1` | `count()` ở scale 1000 m. | **V1?** |
| `modis_lst_night_valid_px` | `INT16` | không | số mẫu (∈ {0, 1}) | `MODIS/061/MOD11A1` | Như trên. | **V1?** |
| `modis_lst_day_valid_flag` | `INT8` | không | 0/1 | `MODIS/061/MOD11A1` | `1` nếu `valid_px > 0`; không phản ánh QC. | **V1?** |
| `modis_lst_night_valid_flag` | `INT8` | không | 0/1 | `MODIS/061/MOD11A1` | Như trên. | **V1?** |
| `modis_aod_055_mean` | `FLOAT32` | — | không thứ nguyên | `MODIS/061/MCD19A2_GRANULES` (MAIAC) | AOD 550 nm. **Chưa tồn tại**: nguồn `maiac` được định nghĩa trong code nhưng chưa chạy; không có `data/raw/gee_chunks/maiac`. | V2 |
| `modis_aod_valid_px` | `INT16` | — | — | MAIAC | Số mẫu đạt QA. **Chưa tồn tại.** | V2 |
| `modis_aod_valid_flag` | `INT8` | — | 0/1 | MAIAC | **Chưa tồn tại.** | V2 |

> Tài liệu cũ liệt kê cột `modis_lst_valid_flag`: cột này **không tồn tại**; thực tế là hai cột `modis_lst_day_valid_flag` và `modis_lst_night_valid_flag`.

---

### 2.4. Bảng `fact_ground_truth_daily` (Quan trắc Trạm Mặt đất)
* **Primary Key:** `(station_key, date)`; **FK:** `station_key → dim_station`; `grid_id → dim_grid_1km`.
* **Số dòng hiện có:** 22.881 dòng = 20.351 ngày hợp lệ (`is_valid_day = 1`) + 2.530 dòng có số đo nhưng chưa đủ giờ (`is_valid_day = 0`, `pm25_obs` NULL). 99 trạm, 92 trạm có ≥ 1 ngày hợp lệ.
* **Quy tắc:** `is_valid_day = 1` khi `valid_hours_count ≥ 18` **và** `pm25_obs IS NOT NULL`; khi `is_valid_day = 0` thì `pm25_obs` bắt buộc là `NULL` (được kiểm tra tự động từ Phase 2 qua `normalize_and_validate_labels` và `validate_label_table` trong `fetch_openaq.py`, `merge_openaq_chunks.py`, `build_warehouse_facts.py` và `build_feature_marts.py`). Ngày không hợp lệ bị chặn khỏi bảng huấn luyện bởi `validate_training_labels`.
* **Truy vết:** `station_key = openaq_{source_station_id}`; `source_name`, `source_station_id` tra qua `dim_station`. `sensor_id`, `pm25_raw_mean`, `source_units` chỉ có ở raw chunk/interim, **chưa có ở bảng này**.

| Tên cột | Kiểu | Nullable | Đơn vị | Nguồn | Mô tả / quy tắc | TT |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `station_key` | `STRING` | không | — | FK → `dim_station` | Khóa nội bộ ổn định của trạm. | V1 |
| `station_id` | `STRING` | không | — | OpenAQ | `OAQ_{id}`; mã trạm nguồn để truy vết. | V1 |
| `grid_id` | `STRING` | không | — | Gán lúc cào + `dim_station` | Ô 1 km chứa trạm (99/99 trùng với point-in-cell). | V1 |
| `date` | `STRING` (ISO) | không | ngày UTC | Hệ thống | `YYYY-MM-DD`. | V1 |
| `site_type` | `STRING` | không | — | LAQN (ghép ≤ 100 m) / `Unknown` | Một trong `Roadside`, `Urban Background`, `Suburban`, `Kerbside`, `Industrial`, `Unknown`. Với trạm không phải LAQN, giá trị mượn từ trạm LAQN lân cận. | V1 |
| `pm25_obs` | `FLOAT32` | có | µg/m³ | OpenAQ `/sensors/{id}/hours` | Trung bình các giờ UTC phân biệt có giá trị; NULL khi không hợp lệ. Giờ `value < 0` bị bỏ trước khi trung bình. | V1 |
| `valid_hours_count` | `INT8` | không | giờ UTC (0–24) | Tính từ giờ OpenAQ | Số giờ UTC phân biệt có giá trị. | V1 |
| `is_valid_day` | `INT8` | không | 0/1 | Tính toán | Cờ ngày đủ tiêu chuẩn làm nhãn huấn luyện. | V1 |
| `source_name`, `source_station_id`, `sensor_id`, `source_units`, `unit_scale_to_ugm3`, `pm25_raw_mean` | — | — | — | — | Truy vết nguồn, đơn vị và hệ số quy đổi ngay trên fact. | V2 |

### 2.5. Bảng `dim_station` (Danh mục Trạm)
* **Primary Key:** `station_key` (`STRING`). **Unique Key:** `(source_name, source_station_id)`.
* **Grain:** một dòng mỗi trạm. Hiện có 99 dòng, toàn bộ `source_name = 'OpenAQ'`.
* **Phân bố (99 trạm):** `provider` — London Air Quality Network 40, Clarity 39, AirGradient 18, EEA 2; `is_monitor` True 42/False 57; `site_type` — Unknown 56, Roadside 24, Urban Background 10, Kerbside 5, Suburban 3, Industrial 1.
* Bản `warehouse` (15 cột) là tập con của bản `interim` (26 cột).

| Tên cột | Kiểu | Nullable | Nguồn | Mô tả / quy tắc | Tầng | TT |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `station_key` | `STRING` | không | Hệ thống | `openaq_{id}`; ổn định, không đổi theo thứ tự tải. | cả hai | V1 |
| `source_name` | `STRING` | không | Nguồn | Hiện luôn là `OpenAQ`. | cả hai | V1 |
| `source_station_id` | `STRING` | không | OpenAQ | ID location OpenAQ. | cả hai | V1 |
| `station_id` | `STRING` | không | OpenAQ | `OAQ_{id}`. | cả hai | V1 |
| `station_name`, `locality` | `STRING` | có | OpenAQ | Tên trạm/địa phương. | cả hai | V1 |
| `longitude`, `latitude` | `FLOAT64` | không | OpenAQ | **Tọa độ trạm thật**, EPSG:4326. | cả hai | V1 |
| `bng_easting`, `bng_northing` | `FLOAT64` | không | `pyproj` từ lon/lat | **Tọa độ trạm thật** trong EPSG:27700 (khác nghĩa với cùng tên cột ở `dim_grid_1km`). | cả hai | V1 |
| `grid_id` | `STRING` | không | Tính từ tọa độ trạm | Ô chứa trạm (floor của BNG, trùng `grid_id_computed`). | warehouse | V1 |
| `site_type` | `STRING` | không | LAQN ≤ 100 m, ngược lại `Unknown` | Giữ giá trị gốc LAQN. | cả hai | V1 |
| `site_type_source` | `STRING` | không | Hệ thống | `LAQN` hoặc `none`. | cả hai | V1 |
| `is_monitor` | `BOOL` | không | OpenAQ | `True` = trạm tham chiếu, `False` = cảm biến (theo OpenAQ). | cả hai | V1 |
| `provider` | `STRING` | không | OpenAQ | Nhà cung cấp dữ liệu. | cả hai | V1 |
| `grid_id_chunk`, `grid_id_computed`, `grid_match` | `STRING`/`BOOL` | không | Hệ thống | Đối soát `grid_id` lúc cào và `grid_id` tính lại. | chỉ ở interim | V1 |
| `owner`, `is_mobile`, `datetime_first_utc`, `datetime_last_utc`, `metadata_fetched_at_utc` | — | — | OpenAQ | Metadata nguồn. | chỉ ở interim | V1 |
| `laqn_site_code`, `laqn_match_m`, `nearest_other_station_m`, `possible_duplicate` | — | — | Tính toán | Ghép LAQN và cờ nghi trùng (< 50 m; hiện 14 trạm). | chỉ ở interim | V1 |

`fact_ground_truth_daily` tham chiếu `station_key`; `grid_id` là kết quả gán ô và cần được kiểm tra lại khi lưới thay đổi.

---

## 3. Feature Mart theo ô-ngày (`mart_grid_daily_features` - M4)
* **Grain/PK:** `(grid_id, date)`; 1.155.711 dòng = 1.581 ô × 731 ngày; 41 cột.
* **Cách dựng (`build_feature_marts.py`):** tích Đề-các `dim_grid_1km × lịch ngày` rồi `LEFT JOIN` (`safe_merge` với `validate="one_to_one"`) `fact_meteo_daily` và `fact_satellite_daily` theo `(grid_id, date)`, bổ sung feature lịch và kiểm tra `validate_grid_daily_spine`.
* **Quy tắc thứ tự thực thi (Pipeline Dependency):** Từ Phase 2, `generate_spatio_temporal_spine` trong `build_feature_marts.py` tự động giữ lại 6 cột tĩnh nếu chúng đã tồn tại sẵn trong `dim_grid_1km`; đồng thời `build_spatial_static_features.py` dùng `safe_merge` (`one_to_one` cho `dim_grid_1km`, `many_to_one` cho hai mart) để kiểm tra bảo toàn số dòng và khóa chính khi cập nhật mart. Tuy nhiên, nếu dựng từ đầu khi `dim_grid_1km` chưa có cột tĩnh, thứ tự chạy vẫn là: `warehouse_facts` → `feature_marts` → `spatial_static_features` (hoặc chạy `spatial_static_features` trước `feature_marts`). Về dài hạn (Phase 3), pipeline sẽ tách hẳn việc dựng feature tĩnh vào `dim_grid_1km` trước khi tạo mart.
* Không gộp `fact_ground_truth_daily` thành nhãn grid-day.

| Nhóm cột | Cột | Kiểu | Ghi chú | TT |
| :--- | :--- | :--- | :--- | :--- |
| Khóa | `grid_id`, `date` | `STRING` | Khóa chính. | V1 |
| Hình học (từ `dim_grid_1km`) | `centroid_lon`, `centroid_lat`, `bng_easting`, `bng_northing`, `dist_to_charing_cross_km`, `in_boundary` | như `dim_grid_1km` | `bng_*` là tâm ô. | V1 |
| Lịch | `month`, `day_of_week`, `day_of_year`, `is_weekend`, `sin_day_of_year`, `cos_day_of_year`, `sin_day_of_week`, `cos_day_of_week` | `INT8/INT16/FLOAT32` | Suy từ `date`, chỉ có ở mart. | V1 |
| Khí tượng/CAMS | 9 cột ở §2.2 | `FLOAT32` | — | V1 |
| Vệ tinh | 10 cột ở §2.3 | như §2.3 | NULL ở giá trị trung bình khi không có quan sát. | V1 / V1? |
| Tĩnh | 6 cột ở §2.1 | `FLOAT32` | Cập nhật bởi `build_spatial_static_features.py`. | V1 / V1? |

## 4. Grain nhãn, feature và dự đoán
Không gộp bảng nhãn và bảng feature thành một khái niệm "ground truth theo ô":

* `fact_ground_truth_daily`: grain `(station_key, date)`, mỗi quan trắc trạm, `grid_id` chứa trạm, `site_type`, số giờ hợp lệ và cờ `is_valid_day`. Không gộp các trạm cùng ô mặc định.
* `mart_grid_daily_features`: grain `(grid_id, date)` cho mọi ô trong lưới và ngày trong cửa sổ. Chỉ chứa feature. Nếu thêm nhãn trạm nullable để tiện lấy mẫu train, nhãn phải giữ lineage tới `station_key` và không được xem là giá trị đại diện của toàn ô.
* `mart_station_daily_training`: bảng dẫn xuất, grain `(station_key, date)`, **20.351 dòng, 47 cột, 92 trạm trên 75 ô**. Gồm các cột của fact nhãn (`station_key`, `station_id`, `grid_id`, `date`, `site_type`, `pm25_obs`, `valid_hours_count`, `is_valid_day`) nối với 39 cột của mart lưới tại ô chứa trạm (trừ `grid_id`, `date`). Chỉ giữ ngày `is_valid_day = 1` và `pm25_obs` không NULL. **Không** có `source_name`, `provider`, `is_monitor`, tọa độ trạm thật; `bng_easting/northing` là tâm ô. **Chưa có `site_group`.** Dùng bảng này để train/evaluate; chia fold theo địa điểm/trạm trước mọi bước có fit hoặc dùng nhãn.
* `reports/predictions/oof_predictions.parquet`: 13 cột (`station_key`, `station_id`, `grid_id`, `group`, `date`, `site_type`, `pm25_obs`, `pred_lgb_pure`, `pred_hybrid`, `pred_idw`, `pred_daily_mean`, `cams_pm25_bg`, `fold`), 20.351 dòng. `group` = nhóm CV hiện dùng (36 nhóm; xem [analysis_plan.md](analysis_plan.md)).
* `reports/predictions/prediction_grid_daily.parquet`: hiện 10 cột (`grid_id`, `date`, `pm25_estimate`, `pm25_estimate_pure`, `nearest_station_distance_km`, `in_boundary`, `centroid_lon`, `centroid_lat`, `bng_easting`, `bng_northing`), 1.155.711 dòng, grain thực tế `(grid_id, date)`. Đây là đầu ra mô hình, không phải quan trắc.
  * `pm25_estimate` = mô hình **lai** (cần số đo trạm cùng ngày); `pm25_estimate_pure` = mô hình thuần.
  * `nearest_station_distance_km` = khoảng cách **tĩnh** tới trạm gần nhất (tâm ô → tâm ô chứa trạm, mọi trạm từng có trong huấn luyện).
  * **V2 (chưa có):** `run_id` (khóa `(run_id, grid_id, date)`), số trạm có số đo trong ngày, khoảng bất định, model/config ID.

### Chỉnh định nghĩa feature không gian
* `built_up_frac` là tỷ lệ mẫu 30 m thuộc ESA WorldCover Class 50 (v100, năm 2020) trong ô; không gọi là tỷ lệ mặt không thấm hay "tỷ lệ bê tông".
* `major_road_length_m` hiện là tổng chiều dài (m), chưa chuẩn hóa theo diện tích; nguồn DfT Major Road Network 2018. Chuẩn hóa/`major_road_density` thuộc V2.
* Lưới 1 km là đơn vị xuất bản. Feature ERA5-Land/CAMS (và pixel S5P ~5,5 km) thô hơn 1 km; resampling không tạo thông tin mới. Giữ metadata độ phân giải nguồn và cờ valid-pixel.

Tên cột AOD chuẩn ở V2 là `modis_aod_055_mean` (V1 chưa có cột này).
