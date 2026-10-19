# PM2.5 London

Dự án này xây dựng quy trình ước lượng nồng độ bụi mịn PM2.5 theo ngày cho toàn bộ lưới 1 km trên Greater London, dựa trên dữ liệu quan trắc từ các trạm hiện có và các feature phụ trợ như khí tượng, vệ tinh, dữ liệu đô thị và môi trường.

Mục tiêu không phải là dự báo tương lai mà là xây dựng bản đồ ước lượng không gian-thời gian cho các ngày đã quan sát được, phục vụ kiểm định và phân tích môi trường đô thị.

## 1. Tóm tắt dự án

- Mục tiêu: ước lượng PM2.5 trung bình ngày trên toàn bộ ô lưới 1 km của Greater London
- Đơn vị nhãn: quan trắc theo `(station_key, date)`
- Đơn vị đầu ra: dự đoán theo `(grid_id, date)`
- Cách đánh giá chính: spatial grouped cross-validation, không dùng random split
- Vùng dữ liệu: Greater London, lưới 1 km theo hệ tọa độ phù hợp với địa lý
- Chế độ sử dụng: hồi cứu / đồng thời, không phải forecasting

## 2. Vấn đề kinh doanh và kỹ thuật

London có mạng lưới quan trắc PM2.5 nhưng bị thưa và lệch không gian: các trạm thường tập trung ở nội đô và khu vực giao thông, trong khi nhiều vùng ngoại ô thiếu dữ liệu. Để hoàn thiện bề mặt ô nhiễm không gian, dự án tích hợp:

- dữ liệu trạm quan trắc
- dữ liệu khí tượng và tái phân tích (ERA5 / ERA5-Land)
- dữ liệu Aerosol và khí thải từ vệ tinh / mô hình mô phỏng (MODIS, Sentinel-5P, CAMS)
- dữ liệu tĩnh đô thị và môi trường (OSM, land cover, ranh giới, lưới)

Nhiệm vụ là tạo ra sản phẩm có thể hỗ trợ đánh giá môi trường, phân tích không gian, so sánh theo vùng và đưa ra bản đồ nồng độ ước lượng với chỉ báo sai số và độ không chắc chắn.

## 3. Nguyên tắc dữ liệu và kiến trúc

Dự án giữ các nguyên tắc sau:

- Raw data là bất biến và không chỉnh sửa
- Tầng trung gian (`interim`) xử lý chuẩn hóa dữ liệu theo nguồn
- Tầng warehouse lưu dữ liệu dạng dimension/fact chuẩn hóa
- Tầng processed lưu feature mart và training mart
- Dữ liệu thiếu không được che giấu; phải có cờ chất lượng và coverage
- Không gán nhãn trạm làm ground truth cho mọi ô lưới
- Bản đồ dự đoán không được gọi là đo đạc tuyệt đối tại mọi điểm

## 4. Kiến trúc thư mục

```text
pm25_london/
├── README.md
├── .env.example
├── .gitignore
├── docs/
│   ├── architecture.md
│   ├── analysis_plan.md
│   ├── business_case.md
│   ├── data_contract.md
│   ├── decison_log.md
│   ├── schema.md
│   ├── source_landing.md
│   └── sources.md
├── data/
│   ├── raw/
│   ├── interim/
│   ├── warehouse/
│   ├── processed/
│   └── external/
├── configs/
├── src/
│   ├── ingest/
│   ├── features/
│   ├── models/
│   ├── viz/
│   ├── config.py
│   └── aqi.py
├── scripts/
├── notebooks/
├── models/
├── reports/
│   ├── figures/
│   ├── tables/
│   ├── predictions/
│   └── final_report.md
├── app/
├── tests/
├── .github/
└── .github/workflows/
```

## 5. Luồng dữ liệu

1. Raw data: lưu dữ liệu nguyên bản, manifest, metadata và source lineage
2. Interim: chuẩn hóa tên cột, đơn vị, timezone, bản ghi và chất lượng dữ liệu
3. Warehouse: lưu `dim_grid_1km`, `dim_station`, fact station-day và fact grid-day
4. Processed: xây feature mart, training mart và spine không gian-thời gian
5. Train / evaluate: baseline + model + spatial validation
6. Predict: tạo dự đoán ở mức grid-day và báo cáo kết quả

## 6. Grain và schema chính

Các grain chưa được gộp theo kiểu sai lệch:

- `fact_ground_truth_daily`: `(station_key, date)`
- `mart_station_daily_training`: `(station_key, date)`
- `mart_grid_daily_features`: `(grid_id, date)`
- `prediction_grid_daily`: `(run_id, grid_id, date)`

Điều quan trọng là nhãn trạm dành cho quan trắc thực tế; không được đồng nhất với mọi ô lưới. Kết quả mô hình tại ô không có trạm là ước lượng, không phải ground truth.

## 7. Đánh giá mô hình

Đánh giá chính là spatial holdout hoặc grouped spatial cross-validation:

- chia theo nhóm vị trí / trạm
- giữ trạm cùng vị trí trong cùng fold
- không dùng random split hoặc split theo ngày đơn thuần như đánh giá dự báo
- temporal split chỉ dùng như kiểm tra độ ổn định, không thay thế validation không gian

Mục tiêu là đánh giá khả năng tổng quát hóa ở những khu vực không có trạm đo, chứ không chỉ đo hiệu năng trên data tương tự đã thấy.

## 8. Triển khai hiện tại

Repo hiện đang ở giai đoạn scaffold và chuẩn hóa tài liệu. Cấu trúc và thiết kế được định nghĩa rõ trong `docs/` nhưng phần pipeline code, config và mô hình thực thi vẫn đang được triển khai tiếp theo.

Điểm cần lưu ý:

- dữ liệu thực không được commit
- `data/` chứa folder chuẩn theo tầng dữ liệu
- `docs/` là nguồn kiến thức tham chiếu cho kiến trúc, schema, lưu trữ và đánh giá
- README này là bản tóm tắt chuẩn hóa cho việc phát triển và vận hành sau này

## 9. Hướng dẫn khởi tạo dự án (kế hoạch)

Sau khi pipeline code được triển khai, quy trình mong đợi sẽ là:

1. Sao chép `.env.example` thành `.env` và điền khóa và thông tin kết nối cần thiết
2. Đặt dữ liệu nguyên bản ở `data/raw/`
3. Chạy pipeline ingest / chuẩn hóa / feature building
4. Kiểm tra missing values, QC và coverage theo địa điểm
5. Huấn luyện baseline và mô hình chính
6. Chạy spatial CV và báo cáo metric
7. Tạo dự đoán trên toàn lưới và xuất báo cáo, biểu đồ, bảng kết quả

## 10. Tài liệu tham khảo trong repo

- [docs/architecture.md](docs/architecture.md)
- [docs/business_case.md](docs/business_case.md)
- [docs/analysis_plan.md](docs/analysis_plan.md)
- [docs/data_contract.md](docs/data_contract.md)
- [docs/schema.md](docs/schema.md)
- [docs/decison_log.md](docs/decison_log.md)

## 11. Giới hạn và cảnh báo

- Dữ liệu vệ tinh và reanalysis không tự động tạo ra thông tin ở độ phân giải 1 km
- PM2.5 cao cần kiểm tra kỹ thay vì bị xóa ngẫu nhiên theo ngưỡng cố định
- Không có ground truth cho mọi ô lưới; mọi dự đoán tại ô không có trạm đều cần được diễn giải như ước lượng mô hình
- Mức độ tin cậy cần được chứng minh bằng spatial holdout và kiểm tra mất mát theo không gian

## 12. Mục tiêu tiếp theo

- triển khai `src/` và `scripts/`
- xây dựng config và pipeline chạy được
- tạo baselines và spatial CV đầu tiên
- thêm feature khí tượng / vệ tinh / đô thị
- tích hợp báo cáo, bản đồ và ứng dụng hiển thị kết quả

---

Dự án này đang được thiết kế theo hướng khoa học dữ liệu, có kiểm soát leakage, dữ liệu không gian rõ ràng và đánh giá hợp lý cho bài toán ước lượng PM2.5 đô thị theo lưới. 
