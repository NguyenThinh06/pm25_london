# Data Contract & Quality Gate Specification

Tài liệu này định nghĩa các ràng buộc giữa **Raw** (`data/raw/`), **Interim** (`data/interim/`), **Warehouse** (`data/warehouse/`) và **Processed** (`data/processed/`). Chỉ lỗi schema/khóa/ingest nghiêm trọng hoặc coverage thấp hơn ngưỡng cấu hình mới làm dừng pipeline; thiếu dữ liệu nguồn cần được gắn cờ và báo cáo.

## 1. Ràng buộc Không gian & Thời gian (Spatio-Temporal Constraints)
* **Grid Completeness (`CRITICAL`):** Bảng lưới chuẩn `dim_grid_1km` phải có đúng $N_{\text{grid}}$ ô (không trùng lặp `grid_id`, không có geometry `NULL` hoặc tự cắt).
* **Full Cartesian Product (`CRITICAL`):** Bảng khung xương (spine) tại tầng Processed phải chứa đủ $N_{\text{grid}} \times N_{\text{days}}$ dòng cho vùng/ngày cấu hình; không được rớt ô-ngày do thiếu nhãn hoặc feature.
* **Timezone Alignment (`CRITICAL`):** Mọi dấu thời gian từ các nguồn phải được chuẩn hóa về **UTC** trước khi cắt ngày (`00:00:00` đến `23:59:59` UTC).

## 2. Hợp đồng Ràng buộc theo Từng Biến (Field-Level Contracts)

| Thuộc tính | Kiểu dữ liệu | Miền giá trị hợp lệ (Physical Bounds) | Tỷ lệ `NULL` tối đa cho phép | Quy tắc xử lý khi vi phạm / Masking |
| :--- | :--- | :--- | :--- | :--- |
| `pm25_obs` | `FLOAT64` | Ngưỡng QC theo nguồn/thiết bị; không cắt cứng giá trị cao | NULL nếu trạm-ngày không đạt QC; không tạo dòng giả cho ngày không quan trắc | Gắn cờ giá trị âm/ngoại lai; giá trị rất cao được quarantine để xác minh, không tự động loại chỉ vì vượt 500. Chỉ tạo nhãn ngày khi đạt coverage đã cấu hình. |
| `t2m_mean_c` | `FLOAT32` | $[-25.0, 45.0]\ ^\circ\text{C}$ | Theo coverage nguồn được cấu hình | Chuyển từ Kelvin sang Celsius ($T_K - 273.15$). NULL được gắn cờ; fail khi lỗi ingest/schema hoặc coverage xuống dưới ngưỡng đã định. |
| `rh_mean_pct` | `FLOAT32` | $[0.0, 100.0]\ \%$ | Theo coverage nguồn được cấu hình | Tính từ $T_{2m}$ và $T_d$ theo công thức đã ghi nhận; lưu cờ thiếu và không âm thầm điền giá trị. |
| `blh_min_m`, `blh_max_m` | `FLOAT32` | Theo miền vật lý/QA của product | Theo coverage nguồn được cấu hình | Kiểm tra đơn vị và giá trị theo product; thiếu dữ liệu được gắn cờ, không tự động xem là lỗi pipeline. |
| `s5p_no2_mean` | `FLOAT32` | $[-0.001, 0.05]\text{ mol/m}^2$ | $\le 85.0\%$ (`WARNING`) | GEE L3 đã lọc `qa_value >= 0.75`. Cắt bỏ các giá trị cực đoan $< -0.001\text{ mol/m}^2$ thành `NULL` và bật cờ `s5p_no2_valid_flag = 0`. |
| `modis_aod_055_mean` | `FLOAT32` | $[-0.05, 5.0]$ (dimensionless) | Theo coverage nguồn được cấu hình | Nhân hệ số tỷ lệ theo product/version. Áp dụng QA bitmask đúng tài liệu sản phẩm; lưu số pixel hợp lệ và cờ valid. |
| `modis_lst_night_c` | `FLOAT32` | $[-25.0, 40.0]\ ^\circ\text{C}$ | $\le 95.0\%$ (`WARNING`) | Nhân hệ số `0.02` rồi trừ `273.15`. Lọc theo `QC_Night` (chỉ nhận bit 0–1 == `00` hoặc `01`). |
| `built_up_frac` | `FLOAT32` | $[0.0, 1.0]$ | Theo coverage nguồn được cấu hình | Tỷ lệ phần diện tích/pixel ESA WorldCover Class 50; kiểm tra tổng coverage lớp phủ, không diễn giải như phần trăm bề mặt không thấm. |

## 3. Quy tắc Cờ Nguồn gốc & Độ tin cậy (Lineage & Validity Flags)
* Mọi biến vệ tinh có khả năng bị mây che phủ (`s5p_no2`, `modis_aod_055`, `modis_lst_day`, `modis_lst_night`) bắt buộc phải đi kèm 2 cột phụ trợ trong hợp đồng dữ liệu:
  1. `<feature>_valid_px` (`INT16`): Số lượng pixel hợp lệ thực tế rơi vào trong ô 1 km sau khi lọc QA.
  2. `<feature>_valid_flag` (`INT8`): Nhận giá trị `1` nếu `<feature>_valid_px >= min_px_threshold` (mặc định là 1), ngược lại nhận giá trị `0`.

## 4. Điều chỉnh hợp đồng cho bài toán ước lượng
Các quy tắc dưới đây làm rõ và thay thế các ràng buộc rộng hơn ở trên khi có mâu thuẫn:

* **Grain nhãn:** `fact_ground_truth_daily` giữ grain `(station_key, date)`; khóa nguồn `(source_name, station_id)` được lưu để truy vết. `pm25_obs` chỉ có tại trạm/ngày đủ chất lượng; không yêu cầu nhãn ở mọi `grid_id`. Giữ tọa độ, `site_type`, nguồn đo, số giờ hợp lệ và cờ QC. Nhiều trạm cùng ô vẫn là quan trắc riêng tới khi có quy tắc tổng hợp được đánh giá.
* **Grain feature/đầu ra:** Có đủ spine `(grid_id, date)` cho vùng và cửa sổ nghiên cứu. Feature thiếu không làm mất dòng spine. Bảng dự đoán thành phố có một dòng mỗi ô-ngày; không điền dự đoán vào trường nhãn quan trắc.
* **UTC và ngày:** Giữ timestamp gốc và timestamp chuẩn hóa UTC. `date` hiện là ngày UTC; mọi nguồn phải dùng cùng quy ước khi tổng hợp. Nếu chuyển sang ngày lịch London, cần phiên bản contract riêng và kiểm tra độ nhạy do DST.
* **Thiếu feature:** Không áp dụng NULL tối đa 0% mặc định cho mọi nguồn. Tách lỗi ingest/schema khỏi thiếu quan trắc nguồn; lưu cờ missing/valid, kiểm tra tỷ lệ thiếu theo nguồn-ngày-khu vực, đặt ngưỡng cảnh báo theo nguồn và chỉ fail khi coverage không đạt ngưỡng cấu hình. Imputation (nếu dùng) phải fit trên train fold và có cờ thiếu đi kèm.
* **PM2.5 QC:** Giá trị âm cần được xử lý theo quy tắc của thiết bị/nguồn; giá trị rất cao cần quarantine để xác minh, không tự động xóa chỉ vì vượt 500. Ngưỡng số giờ tối thiểu mỗi ngày phải có nguồn tham chiếu và cần báo cáo độ nhạy.
* **Tên cột:** Dùng `modis_aod_055_mean` nhất quán giữa warehouse, mart và contract. `built_up_frac` là tỷ lệ pixel/diện tích ESA WorldCover thuộc Class 50, không mặc định đồng nghĩa với tỷ lệ bề mặt không thấm.
* **Tái lập:** Mọi chuẩn hóa, nội suy dựa trên nhãn, chọn feature và imputation có tham số fit phải fit lại trong train của từng fold. Lưu ngưỡng, phiên bản nguồn và quy tắc QA trong cấu hình/run metadata.