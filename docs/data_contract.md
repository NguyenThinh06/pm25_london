# Data Contract & Quality Gate Specification — V1

Tài liệu này định nghĩa các ràng buộc giữa **Raw** (`data/raw/`), **Interim** (`data/interim/`), **Warehouse** (`data/warehouse/`) và **Processed** (`data/processed/`). Chi tiết từng cột nằm ở [schema.md](schema.md); tài liệu này giữ quy tắc, định nghĩa và giới hạn.

**Nguyên tắc ghi trạng thái.** Tài liệu chỉ ghi một điều là "đã áp dụng" khi thấy nó trong code hoặc dữ liệu của repo. Mọi mục dưới đây mang một trong các nhãn:

| Nhãn | Nghĩa |
| :--- | :--- |
| **[V1]** | Có thật trong artifact hiện tại và ngữ nghĩa đã kiểm chứng từ code/dữ liệu/tài liệu nguồn. |
| **[V1-chưa xác minh]** | Cột có thật nhưng ngữ nghĩa, đơn vị hoặc QA chưa xác minh. **Không dùng cho model chứng nhận** cho tới khi xác minh (xem §7). |
| **[V2]** | Dự kiến, chưa có trong code hoặc dữ liệu. Không được mô tả như cột hiện có. |

Các mâu thuẫn chưa giải quyết và câu hỏi dành cho chủ dự án nằm ở §11. Ngày lập: Pha 1 (chỉ đồng bộ tài liệu; chưa sửa code, chưa dựng lại artifact).

## 1. Bài toán và giới hạn sử dụng
* **Loại bài toán:** ước lượng không gian **hồi cứu/đồng thời** PM2.5 trung bình ngày theo ô 1 km. Đây **không phải dự báo**.
* **Hai use case, không trộn lẫn:**
  1. **Mô hình lai** (`pm25_estimate`) — sản phẩm chính. Cần số đo trạm **cùng ngày** làm đầu vào (nền mạng trạm, IDW, khoảng cách trạm gần nhất).
  2. **Mô hình thuần** (`pm25_estimate_pure`) — mốc tham chiếu. Không cần số đo trạm cùng ngày lúc suy luận (chỉ feature khí tượng, vệ tinh, tĩnh).
* **Nhãn là phép đo tại trạm**, không phải trung bình diện tích của ô 1 km. Prediction ở ô không có trạm là **ước lượng của mô hình**, không phải phép đo.
* **Giới hạn sử dụng:**
  * Chỉ trong cửa sổ dữ liệu 2023-01-01 → 2024-12-31 (UTC) và chỉ cho ngày có số đo trạm trong ngày đó (lai).
  * Không dùng để nói trước tương lai.
  * Không phản ánh ô nhiễm sát đường ở độ phân giải 1 km; độ phân giải 1 km là lưới xuất bản, không đảm bảo độ chính xác thực địa 1 km.
  * Không phải bằng chứng nhân quả (ví dụ về ULEZ) và không phải dữ liệu phơi nhiễm cá nhân.
* **Hiệu năng hiện có (CV hiện tại, 92 trạm, 36 nhóm không gian):** IDW là baseline mạnh (RMSE 3,454). LightGBM thuần 3,912 và lai 3,792 không tốt hơn IDW; anomaly R² của hai LightGBM âm. Xem mục "Kết quả Đánh giá Mô hình" trong [README.md](../README.md) để biết số đầy đủ. Mọi phát biểu "mô hình tốt hơn baseline" cần số liệu hỗ trợ.

## 2. Ba grain tách biệt

| Grain | Khóa | Bảng/artifact | Ghi chú |
| :--- | :--- | :--- | :--- |
| **Nhãn** | `(station_key, date)` | `fact_ground_truth_daily` | Một dòng mỗi trạm-ngày, gồm cả dòng không hợp lệ (`is_valid_day = 0`, `pm25_obs` NULL). Nhiều trạm cùng ô vẫn là quan trắc riêng. |
| **Feature** | `(grid_id, date)` | `fact_meteo_daily`, `fact_satellite_daily`, `mart_grid_daily_features` | Spine đủ tích Descartes ô × ngày: 1.581 × 731 = 1.155.711 dòng. Feature thiếu không làm rơi dòng. |
| **Dự đoán** | `(run_id, grid_id, date)` | `reports/predictions/prediction_grid_daily.parquet` | **Artifact hiện tại chưa có `run_id`** và chưa có chỉ báo "số trạm có số đo trong ngày". Cột hỗ trợ hiện có: `nearest_station_distance_km`, và đây là khoảng cách **tĩnh** (tâm ô tới tâm ô chứa trạm, mọi trạm từng xuất hiện trong huấn luyện), không phải khoảng cách tới trạm có số đo ngày đó. |

`mart_station_daily_training` là bảng dẫn xuất (grain `(station_key, date)`), nối nhãn với feature tại ô chứa trạm. Không có "ground truth theo ô".

## 3. Thời gian
* **V1 dùng ngày UTC.** `date` là chuỗi ISO `YYYY-MM-DD` ở tầng warehouse và processed. Kiểu hiện tại: chuỗi ISO ở `fact_*` và mart; `datetime.date` ở `openaq_daily` (interim); `datetime64` ở chunk GEE và `reports/predictions/*`. Chuẩn V1: chuỗi ISO ở warehouse/processed.
* **Xác nhận bằng code (Pha 1):**
  * `scripts/fetch_openaq.py`: mỗi giá trị theo giờ được quy về UTC (`parse_utc_hour`), lưu theo khóa giờ UTC (`dict`), nên một giờ không bị đếm hai lần; `valid_hours_count` là số **giờ UTC phân biệt** có giá trị; `date` là ngày UTC của giờ đó. Số đếm giờ chỉ được tính ở đây; `merge_openaq_chunks.py` và `build_warehouse_facts.py` chỉ đọc và tính lại `is_valid_day`.
  * `scripts/extract_gee_features.py`: `filterDate` theo ngày UTC cho ERA5-Land, CAMS, S5P và LST.
* **Giới hạn của xác nhận:** dữ liệu theo giờ không được lưu nên không thể kiểm lại "không đếm trùng giờ" từ dữ liệu, chỉ từ code. Quy ước nhãn thời gian của giờ OpenAQ (đầu kỳ hay cuối kỳ) và ngày của sản phẩm MODIS (`system:time_start`) **chưa xác minh**.
* Chuyển sang ngày lịch Europe/London là **thay đổi version**: phải xử lý DST, dựng lại dữ liệu và ghi `contract_version` mới. Không đổi nghĩa `date` âm thầm.

## 4. Lưới
* **CRS:** EPSG:27700 (British National Grid), ô 1 km. `grid_id = grid_{E_góc}_{N_góc}`, trong đó E/N là tọa độ mét của **góc dưới-trái** ô, làm tròn xuống bội của 1000 (ví dụ `grid_508000_177000`). Định dạng `LON_XXXX_YYYY` trong tài liệu cũ không tồn tại trong code hay dữ liệu.
* **Tâm ô:** `dim_grid_1km.bng_easting/bng_northing` = góc + (500, 500) m; `centroid_lon/lat` là tâm đó ở EPSG:4326. `dim_station.bng_easting/bng_northing` là tọa độ **trạm thật** (cùng tên cột, khác nghĩa; xem §5).
* **Quy tắc chọn ô (theo code `scripts/build_dim_grid_1km.py`):** lưới nền 3.224 ô (`data/external/london_grid_1km.csv`, bounding box); giữ ô có **tâm** giao với ranh giới ONS Regions Dec 2023 (`RGN23NM = London`, 1.573,4 km²) → `in_boundary = True`; giữ thêm ô chứa trạm nhưng tâm ngoài ranh giới → `in_boundary = False`.
* **Ô canonical vs ô ngữ cảnh:**
  * **Canonical:** 1.577 ô `in_boundary = True`. Tiêu chí chuẩn: **tâm ô nằm trong ranh giới** ONS Regions Dec 2023 (`RGN23NM = London`), không phải toàn bộ ô: 1.349/1.577 ô nằm hoàn toàn trong ranh giới; 154 ô giao một phần với ranh giới nhưng tâm ngoài nên bị loại theo đúng định nghĩa.
  * **Ngữ cảnh (context):** 4 ô `in_boundary = False` (`grid_519000_177000`, `grid_521000_176000`, `grid_524000_175000`, `grid_558000_172000`), giữ vì chứa 4 trạm. 3/4 ô giao một phần với ranh giới, ô `grid_558000_172000` (Dartford) nằm hẳn ngoài. Không gọi các ô này là "thuộc Greater London".
  * **Quy ước V1 (đề xuất mặc định theo Q2):** Dùng 1.577 ô canonical cho bản đồ và thống kê sản phẩm chính. 4 ô ngoài ranh giới chỉ đóng vai trò ngữ cảnh hỗ trợ mạng trạm; báo cáo metric tại các trạm ngoài ranh giới được tách riêng, không gộp vào metric London chính. Artifact hiện tại vẫn lưu cả 1.581 ô kèm cờ `in_boundary`.
* **Gán trạm vào ô:** 99/99 trạm có `grid_id` trùng với kết quả point-in-cell (floor của tọa độ BNG của trạm); không trạm nào đổi ô. Code gán lúc cào (`fetch_openaq.assign_grid`) dùng khoảng cách Chebyshev tới tâm ô ≤ 550 m (dung sai 50 m), tương đương point-in-cell trừ sát cạnh ô; 18 trạm cách cạnh ô ≤ 50 m.

## 5. Cột V1 và V2 (tóm tắt theo bảng; chi tiết trong [schema.md](schema.md))

| Bảng | Grain / khóa chính | Khóa ngoại | Cột chỉ có ở một tầng |
| :--- | :--- | :--- | :--- |
| `dim_grid_1km` | `grid_id` | — | Feature tĩnh (`built_up_frac`, `tree_cover_frac`, `dist_to_thames_km`, `elevation_m`, `population_density`, `major_road_length_m`) được ghi vào cả `dim_grid_1km` và hai mart bởi `build_spatial_static_features.py`; không có ở `fact_*`. |
| `dim_station` (warehouse) | `station_key`; unique `(source_name, source_station_id)` | — | `provider`, `is_monitor`, `site_type_source` chỉ ở `dim_station`, không vào mart huấn luyện. `owner`, `is_mobile`, `laqn_*`, `possible_duplicate`, `grid_id_chunk` chỉ ở bản interim. |
| `fact_ground_truth_daily` | `(station_key, date)` | `station_key → dim_station`, `grid_id → dim_grid_1km` | Thiếu `source_name`, `source_station_id`, `sensor_id`, đơn vị nguồn, hệ số quy đổi: **[V2]** (hiện truy vết qua `dim_station`; `sensor_id`, `pm25_raw_mean`, `source_units` chỉ nằm ở raw chunk/interim). |
| `fact_meteo_daily` | `(grid_id, date)` | `grid_id → dim_grid_1km` | — |
| `fact_satellite_daily` | `(grid_id, date)` | `grid_id → dim_grid_1km` | — |
| `mart_grid_daily_features` | `(grid_id, date)` | `grid_id → dim_grid_1km` | Cột lịch (`month`, `day_of_week`, `sin_*`, `cos_*`…) chỉ ở mart. |
| `mart_station_daily_training` | `(station_key, date)` | `station_key`, `grid_id` | `bng_easting/northing` ở đây là **tâm ô**, không phải tọa độ trạm; chưa có tọa độ trạm thật và chưa có `site_group` (Pha 3). |
| `oof_predictions` | `(station_key, date)` | — | Có `group`, `fold`; chỉ ở `reports/predictions/`. |
| `prediction_grid_daily` | `(grid_id, date)` hiện tại; mục tiêu `(run_id, grid_id, date)` | `grid_id` | `pm25_estimate`, `pm25_estimate_pure`, `nearest_station_distance_km`; `run_id`, uncertainty, số trạm có số đo trong ngày: **[V2]**. |

**Cột dự kiến [V2], không tồn tại trong parquet:** `blh_mean_m`, `blh_min_m`, `blh_max_m` (ERA5-Land không có BLH; chưa có nguồn BLH trong `extract_gee_features.py`), `modis_aod_055_mean`, `modis_aod_valid_px`, `modis_aod_valid_flag` (có định nghĩa nguồn `maiac` trong code nhưng chưa chạy; không có `data/raw/gee_chunks/maiac`), `modis_lst_valid_flag` (tên cột này không có; thực tế là `modis_lst_day_valid_flag` và `modis_lst_night_valid_flag`).

## 6. Quy tắc cấp biến (Field-Level Contracts)

Cột "Áp dụng trong code" cho biết quy tắc có được code thực thi không. Cột "Kiểm tra dữ liệu hiện có" là kết quả đọc artifact, không phải gate.

| Thuộc tính | Kiểu | Miền / quy tắc hợp đồng | Áp dụng trong code | Kiểm tra dữ liệu hiện có | Trạng thái |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `pm25_obs` | `FLOAT32` | µg/m³; trung bình của các giờ UTC phân biệt có giá trị, chỉ khi `valid_hours_count ≥ 18`, ngược lại NULL. Giá trị âm/ngoại lai cần gắn cờ và quarantine, không xóa theo ngưỡng tùy ý. | **Sau Phase 2:** `normalize_and_validate_labels` và `validate_label_table` (`scripts/quality_gates.py`) bắt buộc `pm25_obs` = NULL khi `is_valid_day == 0` và không NULL khi `is_valid_day == 1`. `aggregate_hourly_items` (`fetch_openaq.py`) ghi nhận `negative_hours_dropped_count` và `qc_neg_dropped_flag` khi tổng hợp từ payload giờ mới (với cache CSV cũ đã bỏ âm trước khi lưu, hai cột này đặt `NA`). | min 0,0 (1 dòng), max 74,09; 0 ngày âm; 2.530 dòng không hợp lệ đều NULL; 0 mâu thuẫn `is_valid_day` ↔ `valid_hours_count` ↔ `pm25_obs` | **[V1]** (QC âm/ngoại lai theo thiết bị: chưa xác minh; bảo toàn raw payload thuộc Phase 3) |
| `valid_hours_count`, `is_valid_day` | `INT8` | `0 <= valid_hours_count <= 24` (nguyên, không NULL); `is_valid_day = (valid_hours_count ≥ 18) AND pm25_obs IS NOT NULL`. Ngưỡng 18 giờ là tham số V1 trong code (`MIN_VALID_HOURS = 18`). | **Sau Phase 2:** thực thi nhất quán ở `fetch_openaq.py`, `merge_openaq_chunks.py`, `build_warehouse_facts.py` và `build_feature_marts.py`; `validate_training_labels` chặn mọi dòng `is_valid_day != 1` hoặc `pm25_obs` NULL vào bảng train. | Nhất quán ở 22.881 dòng | **[V1]** |
| `t2m_mean_c` | `FLOAT32` | °C, `[-25, 45]`; ERA5-Land hourly → trung bình ngày UTC, K − 273,15 | Chuyển đổi: có. Kiểm miền: không. | −2,6…24,6 | **[V1]** (đơn vị band chưa đối chiếu tài liệu ERA5-Land; xem Q9) |
| `rh_mean_pct` | `FLOAT32` | %, `[0, 100]`; Magnus từ nhiệt độ 2 m và điểm sương 2 m theo giờ, `min(100)` | Công thức: có. Kiểm miền: không. | 53,7…97,9 | **[V1]** |
| `u10_vector_mean`, `v10_vector_mean`, `wind_speed_scalar_mean`, `precip_sum_mm`, `sp_mean_hpa` | `FLOAT32` | m/s, m/s, m/s (trung bình của tốc độ giờ), mm (tổng 24 giờ), hPa | Chuyển đổi trong `era5l_image`. | Trong miền hợp lý (`precip_sum_mm` min −0,000 do làm tròn float32) | **[V1]** |
| `cams_aod_550`, `cams_pm25_bg` | `FLOAT32` | Không thiếu; CAMS NRT, `model_forecast_hour < 12`, µg/m³ (×1e9 từ kg/m³) | Có. Lấy mẫu tại điểm tâm ô (pixel thô, không bilinear). | 0 NULL | **[V1]** |
| `s5p_no2_mean` | `FLOAT32` | mol/m², miền mong đợi `[-0.001, 0.05]`, NULL tối đa ≤ 85% (`WARNING`) | **Không có** lọc `qa_value` trong code và **không có** clip `< −0,001`. Theo tài liệu GEE (tra cứu), collection L3 NO2 đã được ngưỡng `qa_value` khi tạo collection; chưa đối chiếu trực tiếp catalog. | min −7,2e−5, max 5,1e−4, NULL 67,65% | **[V1-chưa xác minh]** QA |
| `s5p_cloud_frac` | `FLOAT32` | `[0, 1]` | Có (trung bình trong ô). | NULL 21,11% (khác NO2: 67,65%) | **[V1-chưa xác minh]** (chưa có cờ coverage / QA bitmask; bị chặn ở mode="certified") |
| `s5p_no2_valid_px` | `INT16` | **Giá trị thật chỉ ∈ {0, 1}.** Là `ee.Reducer.count()` trên polygon 1 km lấy mẫu ở `scale = 1000 m`, `EPSG:27700`; pixel S5P gốc ~5,5 km nên **không phải** "số pixel S5P trong ô 1 km". | Có | 0: 781.804 dòng; 1: 373.907 dòng | **[V1-chưa xác minh]** tên/định nghĩa |
| `s5p_no2_valid_flag` | `INT8` | `1` nếu `valid_px > 0`, tức "có giá trị sau mask GEE". **Không** có nghĩa "đạt QA đầy đủ". | Có | ≡ `s5p_no2_mean IS NOT NULL` | **[V1-chưa xác minh]** |
| `modis_lst_day_c`, `modis_lst_night_c` | `FLOAT32` | °C = `LST × 0.02 − 273.15` (MOD11A1 v061). Hợp đồng ban đầu: lọc `QC_Night`/`QC_Day` bit 0–1 ∈ {00, 01}; NULL tối đa ≤ 95%. | **Không có** đọc `QC_Day/QC_Night`; chỉ mask mặc định của GEE. Định nghĩa bit 0–1 khớp tài liệu GEE (00 tốt, 01 chất lượng khác, 10/11 không tạo ra), nhưng quyết định nhận {00} hay {00, 01} chưa chốt. | ngày −25,6…41,0; đêm −16,3…24,5; NULL ngày 72,25%, đêm 68,15% | **[V1-chưa xác minh]** QA |
| `modis_lst_day_valid_px`, `modis_lst_night_valid_px`, `modis_lst_*_valid_flag` | `INT16`, `INT8` | Như S5P: `count()` ở scale 1000 m (∈ {0, 1}); flag = `count > 0`. | Có | ≡ giá trị không NULL | **[V1-chưa xác minh]** |
| `modis_aod_055_mean`, `modis_aod_valid_px`, `modis_aod_valid_flag` | — | Hợp đồng V2: `Optical_Depth_055 × 0.001`; QA bit 0–2 = 001 (clear) và bit 8–11 = 0000 (tốt nhất) theo định nghĩa trong `extract_gee_features.py` (khớp tài liệu GEE qua tra cứu); lưu số pixel hợp lệ và cờ. | Có định nghĩa nguồn `maiac`; **chưa chạy**. | Không có chunk, không có cột | **[V2]** |
| `blh_mean_m`, `blh_min_m`, `blh_max_m` | — | Cần nguồn ERA5 (ERA5-Land không có BLH) | Không có | Không có | **[V2]** |
| `dist_to_charing_cross_km` | `FLOAT32` | km, Euclid trong EPSG:27700 từ tâm ô tới Charing Cross (−0,12776, 51,50739) | Có | — | **[V1]** |
| `built_up_frac` | `FLOAT32` | `[0, 1]`; **tỷ lệ mẫu 30 m có `Map == 50`** (ESA WorldCover, `ESA/WorldCover/v100` = năm 2020, 10 m) trong ô; không phải tỷ lệ bề mặt không thấm. | Có; reducer null bị ép về 0. | 0…0,965; 8 ô = 0 | **[V1-chưa xác minh]** (null→0 chưa phân biệt được; bị chặn ở mode="certified") |
| `tree_cover_frac` | `FLOAT32` | `[0, 1]`; như trên với `Map == 10` | Như trên | 0…0,875; 5 ô = 0 | **[V1-chưa xác minh]** (null→0 chưa phân biệt được; bị chặn ở mode="certified") |
| `elevation_m` | `FLOAT32` | m; SRTM `USGS/SRTMGL1_003` 30 m, mean trong ô; null→0 | Có | 0,45…232,4; 0 ô bằng 0 | **[V1-chưa xác minh]** (null→0 chưa phân biệt được; bị chặn ở mode="certified") |
| `major_road_length_m` | `FLOAT32` | m; tổng chiều dài đoạn đường DfT Major Road Network (snapshot 2018, Open Roads, shapefile BNG) giao với hộp ô 1 km; không lọc loại đường; không chuẩn hóa diện tích; ô không giao = 0 | Có (`overlay`) | 1.191/1.581 ô = 0; max 3.410 m | **[V1]** (loại đường, giấy phép, nguồn gốc snapshot chưa ghi) |
| `dist_to_thames_km` | `FLOAT32` | **Thực tế là khoảng cách trung bình trong ô tới pixel WorldCover lớp 80 (mọi mặt nước thường trực)**, tính bằng `fastDistanceTransform(512)` × 10 m, giới hạn ~5 km. **Không phải khoảng cách tới sông Thames.** Đề xuất cho Phase 3 (Q3): đổi tên chuẩn thành `dist_to_nearest_mapped_water_km` trên raster (chưa thực hiện migration trong parquet hiện tại); chỉ dùng tên Thames nếu tính từ geometry vector sông thực tế. | Có | 0,02…2,15 km trên toàn London | **[V1-chưa xác minh]** — bị chặn ở chế độ `certified` |
| `population_density` | `FLOAT32` | **Band GHS_POP là `population_count`: số người/pixel 100 m** (tài liệu GEE). Giá trị lưu là mean của số người/pixel 100 m lấy mẫu ở 30 m, **không phải người/km²**. Đề xuất cho Phase 3 (Q4): ưu tiên chuyển sang `ghsl_population_count` (tổng dân số trong ô 1 km); chỉ tạo chỉ số mật độ sau khi xác minh diện tích hợp lệ và pixel biên (chưa thực hiện migration trong parquet hiện tại). | Có | mean 58,8; max 265,9 | **[V1-chưa xác minh]** — bị chặn ở chế độ `certified` |

## 7. Feature chưa xác minh và Allowlist cho chế độ `certified`

Từ Phase 2, [`scripts/quality_gates.py`](../scripts/quality_gates.py) phân tách danh sách feature thành:
- `CERTIFIED_V1_FEATURES`: **18 feature hiện được đưa vào allowlist cho chế độ `certified`** theo các tiêu chí kỹ thuật đã chốt (dữ liệu đầy đủ 0% NULL trong `fact_meteo_daily` và `dim_grid_1km` hiện có, không bị reducer ép null->0 làm mất thông tin, và không phụ thuộc vào quan trắc vệ tinh bị mây che phủ hoặc chưa áp dụng bitmask QA).
- `UNVERIFIED_V1_FEATURES`: **15 feature chưa xác minh** về ngữ nghĩa, đơn vị, cờ QA hoặc bị ép null->0 (bị chặn trong chế độ `certified`).

Khi chạy `train_spatial_models.py --mode certified` (hoặc `--certified`), code sẽ **fail-fast (`DataContractError`)** nếu tập feature yêu cầu chứa bất kỳ cột nào thuộc `UNVERIFIED_V1_FEATURES`, hoặc có thể dùng `--feature-set certified_only` để chỉ lấy 18 feature thuộc allowlist certified.

> [!IMPORTANT]
> **Phân biệt giữa "được đưa vào allowlist `CERTIFIED_V1_FEATURES`" và "đã xác minh đầy đủ mọi khía cạnh":**
> Việc 18 feature được cho phép trong allowlist `certified` hiện tại chỉ phản ánh rằng chúng thỏa mãn các tiêu chí sàng lọc kỹ thuật ở mức bảng fact/mart hiện có (không rỗng, không mâu thuẫn cờ cơ học). Điều này **không đồng nghĩa với việc đã xác minh toàn diện mọi khía cạnh** về nguồn gốc, đơn vị, ngữ nghĩa và lineage. Các giới hạn xác minh còn tồn tại gồm:
> 1. `major_road_length_m`: tính từ snapshot DfT 2018 (Open Roads), chưa chuẩn hóa theo diện tích ô 1 km, chưa ghi nhận đầy đủ phân loại cấp đường và điều kiện giấy phép trong code.
> 2. Các biến khí tượng ERA5-Land (`t2m_mean_c`, `rh_mean_pct`, `u10_vector_mean`, `v10_vector_mean`, `wind_speed_scalar_mean`, `precip_sum_mm`, `sp_mean_hpa`): lấy mẫu tại điểm tâm ô (pixel thô ~9 km), đơn vị band gốc trong GEE chưa được đối chiếu trực tiếp với tài liệu catalog sản phẩm chính thức, chưa có cờ kiểm miền ngoài logic code.
> 3. Các biến nền CAMS NRT (`cams_aod_550`, `cams_pm25_bg`): lấy mẫu tâm ô từ mô hình hóa học khí quyển độ phân giải thô (~44 km), chưa có cờ phân biệt lỗi ingest với dữ liệu mô hình.

| Feature/nhóm (tên cột hiện có trong parquet) | Vấn đề | Trạng thái sau Phase 2 & Hướng xử lý Phase 3 |
| :--- | :--- | :--- |
| `dist_to_thames_km` | Tính tới mọi pixel nước raster (WorldCover Class 80), không phải geometry sông Thames; đơn vị mét dựa trên pixel 10 m. | **Phase 2:** Bị chặn ở `mode="certified"`. **Đề xuất Phase 3 (Q3):** Đổi tên thành `dist_to_nearest_mapped_water_km` nếu giữ feature raster hiện tại; chỉ dùng tên Thames nếu tính lại từ geometry vector sông thực. |
| `population_density` | Band gốc là số người/pixel 100 m (`population_count`), hiện đặt tên "density" gây hiểu lầm là người/km². | **Phase 2:** Bị chặn ở `mode="certified"`. **Đề xuất Phase 3 (Q4):** Lưu `ghsl_population_count` theo tổng số người/ô; chỉ tạo mật độ sau khi xác minh band, diện tích hợp lệ và phép tính pixel biên. |
| `built_up_frac`, `tree_cover_frac`, `elevation_m` | Reducer null bị ép về 0.0 (`or 0.0`), làm cho giá trị 0 thật và dữ liệu thiếu/ngoài vùng phủ không phân biệt được. | **Phase 2:** Đã loại khỏi `CERTIFIED_V1_FEATURES`, bị chặn ở `mode="certified"`. **Phase 3:** Giữ NULL và bổ sung cờ coverage. |
| `s5p_cloud_frac` | Biến từ vệ tinh Sentinel-5P có 21,11% NULL, chưa qua bộ lọc QA bitmask và cờ coverage. | **Phase 2:** Bị chặn ở `mode="certified"`. **Phase 3:** Bổ sung QA và cờ coverage. |
| `s5p_no2_mean`, `s5p_no2_valid_px`, `s5p_no2_valid_flag` | `valid_px` không phải số pixel gốc trong ô; `valid_flag` chỉ phản ánh "có giá trị"; code chưa áp dụng `qa_value`. | **Phase 2:** Bị chặn ở `mode="certified"`; kiểm tra cơ học `valid_px >= 0`, `valid_flag ∈ {0,1}`, `(valid_flag == 1) <=> (valid_px > 0) <=> mean.notna()`. **Đề xuất Phase 3 (Q5):** Xác minh hướng dẫn sản phẩm/bitmask QA trước khi trích lại. |
| `modis_lst_day_c`, `modis_lst_night_c`, `modis_lst_*_valid_px/flag` | Như trên; code chưa áp dụng `QC_Day/QC_Night`. | **Phase 2:** Bị chặn ở `mode="certified"`; kiểm tra cơ học nhất quán giữa `mean`, `valid_px` và `valid_flag`. **Đề xuất Phase 3 (Q5):** Áp dụng QC theo tài liệu sản phẩm MODIS trước khi trích lại. |
| `*_valid_px` các nguồn | `INT16 NOT NULL` do `fillna(0)`; thiếu chunk không phân biệt được với không có quan sát. | Thêm cờ `source_present` ở Phase 3. |

**Model hiện có** (`models/model_config.json`) dùng 30 feature `EXPLORATORY_BASE_FEATURES` (gồm 18 feature thuộc allowlist certified + 12 feature chưa xác minh ở bảng trên) nên thuộc chế độ `exploratory`, **không phải model chứng nhận (`certified`)**. Kết quả CV hiện tại chỉ là kết quả của artifact hiện tại.

## 8. Lineage và Quy tắc Cờ nguồn gốc & độ tin cậy
* Biến vệ tinh có thể thiếu do mây (`s5p_no2`, `modis_lst_day`, `modis_lst_night`; `modis_aod_055` ở V2) đi kèm `<feature>_valid_px` (`INT16`) và `<feature>_valid_flag` (`INT8`), với ngữ nghĩa thực tế ở §6: **chỉ là chỉ báo có/không có giá trị sau mask của GEE**, không phải số pixel trong ô hay xác nhận QA.
* `NULL` ở giá trị trung bình nghĩa là không có quan sát hợp lệ. Cần tách ba trường hợp: lỗi ingest/thiếu chunk (lỗi pipeline), nguồn có mặt nhưng không có quan sát đạt QA (missing hợp lệ), và giá trị đo hợp lệ bằng 0 (giá trị thật). V1 chưa tách được ba trường hợp này (xem §7); sẽ xử lý ở Pha 3.
* Không điền giá trị thiếu. Imputation (nếu dùng) phải fit trên train fold và đi kèm cờ thiếu.

## 9. Versioning và tái lập (mô tả; chưa triển khai)
Mỗi lần dựng artifact và mỗi lần huấn luyện cần ghi một `run manifest` (JSON) cạnh artifact. **Hiện tại chưa có:** `models/model_config.json` chỉ chứa danh sách feature và tham số nhóm CV.

| Trường | Nội dung |
| :--- | :--- |
| `contract_version` | `"V1"` (đổi khi đổi nghĩa `date`, CRS, tập ô, định nghĩa cột) |
| `run_id`, `created_at_utc` | Định danh và thời điểm tạo (UTC) |
| `date_window` | `start`, `end` (hiện `2023-01-01` → `2024-12-31`), `n_days` |
| `timezone` | `"UTC"` |
| `crs`, `grid` | `EPSG:27700`; quy tắc `grid_id`; `n_cells_total`, `n_cells_canonical`, `n_cells_context`; nguồn và phiên bản ranh giới |
| `sources` | Mỗi nguồn: dataset ID, phiên bản/năm sản phẩm (ví dụ `ESA/WorldCover/v100`), ngày cào, API version |
| `qc_config` | `min_valid_hours`, quy tắc âm/ngoại lai, ngưỡng QA vệ tinh, quy tắc đã áp dụng |
| `features` | Danh sách feature, kèm trạng thái [V1]/[V1-chưa xác minh] và nhãn "chứng nhận/không" |
| `code_hash` | Commit SHA, cờ working tree bẩn, SHA-256 các script chính |
| `model_config_id` | Hash của cấu hình mô hình và nhóm CV |
| `row_counts`, `input_hashes` | Số dòng mỗi bảng; SHA-256 các file đầu vào |

## 10. Quality gates (đã có trong code sau Phase 2 và mục tiêu Phase 3)
* **Đã có trong code sau Phase 2 (`scripts/quality_gates.py`, được gọi trực tiếp trong các script pipeline và kiểm thử bởi `tests/test_quality_gates.py`):**
  1. **Khóa chính (PK) & định dạng mã ô:** `validate_primary_key` kiểm tra không NULL, không chuỗi rỗng và không trùng lặp cho `dim_grid_1km.grid_id`, `dim_station.station_key`, unique key `dim_station.(source_name, source_station_id)`, `fact_ground_truth_daily.(station_key, date)`, `fact_meteo_daily.(grid_id, date)`, `fact_satellite_daily.(grid_id, date)`, `mart_grid_daily_features.(grid_id, date)` và `mart_station_daily_training.(station_key, date)`. `validate_grid_ids` kiểm tra định dạng `^grid_\d+_\d+$`.
  2. **Khóa ngoại (FK):** `validate_foreign_key` kiểm tra mọi `station_key` ở fact/mart tồn tại trong `dim_station` và mọi `grid_id` tồn tại trong `dim_grid_1km`.
  3. **Chuẩn hóa ngày UTC ISO:** `validate_utc_iso_dates` bắt buộc cột `date` không NULL; khi `require_iso_string=True` (tầng warehouse/marts), bắt buộc đúng định dạng chuỗi `YYYY-MM-DD` và từ chối mọi chuỗi có kèm giờ/timezone; khi `require_iso_string=False`, parse với nhận thức UTC đầy đủ (chuyển đổi offset về đúng ngày UTC, tránh lỗi lệch ngày do cắt chuỗi thô).
  4. **Chặn khử trùng âm thầm & bảo vệ metadata:** Đã bỏ `drop_duplicates` âm thầm trong `build_warehouse_facts._load_gee_source` (thay bằng `validate_primary_key`). Ở tầng gộp chunk OpenAQ (`fetch_openaq.py`, `merge_openaq_chunks.py`), `dedupe_by_latest_fetch` kiểm tra nghiêm ngặt: mọi cột metadata ngoài `allowed_differ_cols` (như `sensor_id`, `station_id`, `grid_id`, `site_type`...) không được phép có giá trị khác nhau giữa các bản ghi trùng khóa (báo lỗi `DataContractError` nếu có xung đột metadata); đối với các cột được phép cập nhật, nếu cùng timestamp mới nhất mà giá trị xung đột hoặc thiếu `fetched_at_utc` thì báo lỗi `DataContractError`.
  5. **Quy tắc nhãn & lọc bảng huấn luyện:** `normalize_and_validate_labels` và `validate_label_table` kiểm tra `0 <= valid_hours_count <= 24` (số nguyên, không NULL), `1 <= min_valid_hours <= 24`, `is_valid_day == 1` khi và chỉ khi `valid_hours_count >= 18` **và** `pm25_obs` không NULL, đồng thời ép `pm25_obs = NaN` khi `is_valid_day == 0`. `validate_training_labels` đảm bảo `mart_station_daily_training` và dữ liệu vào `train_spatial_models.py` chỉ chứa dòng `is_valid_day == 1`, `pm25_obs` không NULL và `valid_hours_count >= 18`.
  6. **An toàn phép nối (Join) & bảo toàn grain:** `safe_merge` kiểm tra khóa join không NULL, truyền `validate="one_to_one"` hoặc `"many_to_one"` vào `pandas.merge`, kiểm tra bảo toàn số dòng (`len(after) == len(before)`) và kiểm tra lại PK sau join. Khi nhiều trạm nằm trong cùng một `grid_id` trong cùng một ngày, phép nối `mart_station_daily_training` (`many_to_one` theo `(grid_id, date)`) giữ nguyên grain `(station_key, date)`.
  7. **Độ đầy đủ của spine `(grid_id, date)`:** `validate_grid_daily_spine` kiểm tra tập `(grid_id, date)` của fact/mart khớp chính xác tích Đề-các `expected_grid_ids × dãy ngày UTC liên tục [start_date, end_date]` (không phụ thuộc số dòng hardcode).
  8. **Nhất quán cơ học cờ vệ tinh:** `validate_satellite_flags` kiểm tra `*_valid_px >= 0` (nguyên, không NULL), `*_valid_flag ∈ {0, 1}` (không NULL), `(valid_flag == 1) <=> (valid_px > 0)` và `(valid_flag == 1) <=> mean.notna()`.
  9. **Allowlist feature & chặn chế độ `certified`:** `select_and_validate_training_features` (được đưa về module nhẹ `scripts/quality_gates.py`) loại bỏ cơ chế giao cột âm thầm (`[c for c in BASE_FEATURES if c in df.columns]`), báo lỗi nếu thiếu bất kỳ cột nào được yêu cầu, và ở chế độ `--mode certified` (hoặc `--certified`) báo lỗi `DataContractError` kèm danh sách cụ thể nếu tập feature chứa bất kỳ cột nào thuộc `UNVERIFIED_V1_FEATURES` (gồm 15 biến: vệ tinh chưa QA, raster nước/dân số, và các biến bị ép null->0). Tập `CERTIFIED_V1_FEATURES` gồm đúng 18 biến hiện được allowlist theo các tiêu chí kỹ thuật đã chốt (0% NULL, không bị ép null->0, không phụ thuộc QA vệ tinh chưa rõ), kèm theo các giới hạn xác minh đã ghi nhận ở §7.
* **Chưa có trong code (thuộc phạm vi Phase 3):**
  * Lưu trữ raw payload theo giờ từ OpenAQ để bảo toàn các giờ có giá trị âm trước khi lọc (hiện tại `aggregate_hourly_items` đã đếm `negative_hours_dropped_count` và gắn cờ `qc_neg_dropped_flag` khi chạy mới từ API, nhưng các file cache CSV cũ đã lọc `< 0` trước khi ghi đĩa nên cần cào lại ở Phase 3).
  * Áp dụng bộ lọc bitmask QA cho S5P (`qa_value`) và MODIS LST (`QC_Day`, `QC_Night`) trong `extract_gee_features.py` và trích xuất lại các chunk vệ tinh.
  * Thực hiện migration đổi tên cột trong parquet (`dist_to_thames_km` → `dist_to_nearest_mapped_water_km`, `population_density` → `ghsl_population_count`) và tách thứ tự chạy feature tĩnh trước khi dựng mart.
  * Bổ sung `run_id`, `run_manifest.json`, `site_group` trên mart huấn luyện và kiểm định thời gian Chế độ B1/B2.

## 11. Câu hỏi mở, quy tắc đã có trong code và đề xuất mặc định cho Phase 3

Bảng dưới đây phân biệt rõ **quy tắc đã thực thi trong code (Phase 2)** với **đề xuất mặc định chờ chốt/triển khai ở Phase 3** (không ghi là đã thực hiện migration trên dữ liệu nếu chưa chạy lại pipeline):

1. **Q1 — Temporal Split (Chế độ B):** *Đề xuất mặc định cho Phase 3:* Chọn **Phương án B1** làm kiểm tra thời gian chính: train trên dữ liệu 2023, test trên 2024 tại các trạm có mặt ở cả hai năm (35 trạm); không tuning tham số dựa trên dữ liệu 2024; ghi rõ đây là kiểm tra độ ổn định / chuyển giao theo thời gian (*temporal transferability*), **không phải dự báo tương lai** (*forecasting*). Có thể bổ sung phương án B2 (blocked temporal CV) làm phân tích độ nhạy. *(Chưa chạy trong Phase 2.)*
2. **Q2 — 4 ô ngoài ranh giới:** *Hiện trạng code:* Giữ 1.581 ô kèm cờ `in_boundary` (`1.577` ô `True` có tâm ô trong ranh giới ONS London + `4` ô `False` chứa trạm ngữ cảnh). *Đề xuất mặc định:* Dùng **1.577 ô canonical** cho bản đồ và thống kê sản phẩm chính; báo cáo metric tại các trạm ngoài ranh giới riêng biệt.
3. **Q3 — Khoảng cách nguồn nước (`dist_to_thames_km`):** *Đã có trong code Phase 2:* Cột `dist_to_thames_km` bị đánh dấu trong `UNVERIFIED_V1_FEATURES` và bị chặn ở `mode="certified"`. *Đề xuất cho Phase 3:* Đổi tên cột thành `dist_to_nearest_mapped_water_km` nếu giữ feature raster hiện tại (WorldCover Class 80); chỉ dùng tên Thames nếu tính lại từ geometry vector sông thực tế.
4. **Q4 — Dân số GHSL (`population_density`):** *Đã có trong code Phase 2:* Cột `population_density` bị đánh dấu trong `UNVERIFIED_V1_FEATURES` và bị chặn ở `mode="certified"`. *Đề xuất cho Phase 3:* Ưu tiên lưu `ghsl_population_count` theo tổng số người trong ô 1 km; chỉ tạo mật độ sau khi xác minh band gốc, diện tích hợp lệ và phép tính pixel biên.
5. **Q5 — QA dữ liệu vệ tinh (S5P / LST):** *Đã có trong code Phase 2:* Các cột `s5p_no2_*` và `modis_lst_*` bị chặn ở `mode="certified"`; các cờ `*_valid_px` và `*_valid_flag` được kiểm tra tính nhất quán cơ học với cột `*_mean`. *Đề xuất cho Phase 3:* Xác minh hướng dẫn sản phẩm/bitmask QA từ tài liệu nguồn rồi mới sửa `extract_gee_features.py` và trích lại dữ liệu.
6. **Q6 — Giá trị PM2.5 âm:** *Đã có trong code Phase 2:* Hàm `aggregate_hourly_items` (`fetch_openaq.py`) đếm `negative_hours_dropped_count` và gắn cờ `qc_neg_dropped_flag` khi tổng hợp từ dữ liệu giờ mới (đặt `NA` khi đọc từ cache CSV lịch sử vốn đã lọc âm). *Đề xuất cho Phase 3:* Bảo toàn raw measurement theo giờ và quy định rõ quy tắc lọc theo từng nguồn/thiết bị.
7. **Q7 — Ngưỡng ngày hợp lệ:** *Đã có trong code Phase 2:* Ngưỡng `MIN_VALID_HOURS = 18` giờ UTC hợp lệ được kiểm tra tự động qua `normalize_and_validate_labels`, `validate_label_table` và `validate_training_labels` ở mọi bước pipeline. *Đề xuất cho Phase 3:* Lưu ngưỡng này vào file cấu hình và run manifest.
8. **Q8 — MAIAC AOD:** *Đã có trong code Phase 2:* Không có trong `CERTIFIED_V1_FEATURES` hay `EXPLORATORY_BASE_FEATURES`; xếp vào **[V2]**.
9. **Q9 — Độ cao lớp biên (BLH):** *Đã có trong code Phase 2:* Không có trong `CERTIFIED_V1_FEATURES` hay `EXPLORATORY_BASE_FEATURES`; xếp vào **[V2]**.
10. **Q10 — Nhóm Cross-Validation (`site_group`):** *Hiện trạng code:* `train_spatial_models.py` giữ cấu hình **36 nhóm** không gian (gộp ô kề $\le 1.5\text{ km}$) để tái lập baseline hiện tại. *Đề xuất cho Phase 3:* Bổ sung cột `site_group` tường minh và chạy thêm cấu hình 79 nhóm (kết nối trạm $< 300\text{ m}$) làm phân tích độ nhạy.
11. **Q11 — Nhóm trạm `Unknown`:** *Đề xuất cho Phase 3:* Tách nhóm trạm `site_type = Unknown` (phần lớn là cảm biến Clarity/AirGradient) thành phân tích riêng biệt; đánh giá mô hình tham chiếu chính trên các trạm đã xác định rõ loại hình và chất lượng.
12. **Q12 — Tổ chức thư mục `tests/`:** *Đã thực hiện trong Phase 2:* Đã chuyển `tests/test.py` → `scripts/inspect_gee_chunks.py` và `tests/coverage.py` → `scripts/station_coverage_report.py`; thư mục `tests/` hiện chỉ chứa unit test tự động `tests/test_quality_gates.py` (chạy bằng `python -m unittest discover -s tests -v`, hoàn toàn độc lập với dữ liệu thật, API và các thư viện ML như `lightgbm`/`sklearn`).
13. **Q13 — Dữ liệu thô OpenAQ:** *Hiện trạng:* Giữ nguyên `data/raw/pm25_labels.csv` (không xóa). *Đề xuất cho Phase 3:* Đối soát lineage và checksum SHA-256; định danh các file chunk ngày đã tổng hợp là tầng snapshot/landing đã chuẩn hóa.
14. **Q14 — Định danh lần chạy (`run_id`):** *Hiện trạng:* Không ghi đè các artifacts hiện có trong `reports/predictions/`. *Đề xuất cho Phase 3:* Bổ sung trường `run_id` và `run_manifest.json` khi sinh bảng dự đoán mới.

## 12. Điều chỉnh hợp đồng cho bài toán ước lượng
* **Grain nhãn:** `fact_ground_truth_daily` giữ grain `(station_key, date)`. Truy vết nguồn qua `dim_station` (`source_name`, `source_station_id`); lưu `site_type`, số giờ hợp lệ và cờ `is_valid_day` ở fact; tọa độ trạm chính xác ở `dim_station` (không có ở fact). `pm25_obs` chỉ có ở trạm/ngày đủ chất lượng; không yêu cầu nhãn ở mọi `grid_id`.
* **Grain feature/đầu ra:** có đủ spine `(grid_id, date)` cho cửa sổ nghiên cứu. Bảng dự đoán thành phố có một dòng mỗi ô-ngày; không điền dự đoán vào trường nhãn quan trắc.
* **Thiếu feature:** không áp dụng NULL tối đa 0% mặc định. Tách lỗi ingest/schema khỏi thiếu quan sát; kiểm tra tỷ lệ thiếu theo nguồn-ngày-khu vực.
* **Tên cột:** `modis_aod_055_mean` là tên chuẩn của AOD **ở V2**; chưa có cột này trong V1.
* **Tái lập:** chuẩn hóa, nội suy dựa trên nhãn, chọn feature và imputation có tham số fit phải fit lại trong train của từng fold. Lưu ngưỡng, phiên bản nguồn và quy tắc QA trong run manifest (§9).
