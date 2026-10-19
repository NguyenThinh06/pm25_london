# Raw Zone & Ingestion Specification

Tài liệu này quy định kiến trúc thu thập dữ liệu thô (Raw Ingestion), cách chia lô (batching) để tránh giới hạn quota của API, và cấu trúc lưu trữ bất biến tại `data/raw/`.

## 1. Nguyên tắc Tầng Raw (Raw Zone Principles)
1. **Bất biến (Immutability):** Dữ liệu tải về từ API được lưu nguyên bản theo từng lô (batch), tuyệt đối không ghi đè hay sửa đổi trực tiếp.
2. **Định danh Lô (Batch Registration):** Mọi lần chạy lệnh thu thập phải ghi nhận vào `data/raw/_registry.json` (gồm `batch_id`, `source_name`, `dataset_version`, `query_parameters`, `window_start`, `window_end`, `fetched_at_utc`, `row_count`, `sha256_checksum`, `license` và `source_url`).
3. **Tái lập (Deterministic Query):** Không sử dụng các tham số động (như `models=best_match` hay `latest`). Mọi truy vấn phải khóa cứng phiên bản dataset.

## 2. Cấu trúc Thư mục Tầng Raw
```text
data/raw/
├── _registry.json
├── ground_truth_openaq/
│   └── batch_YYYYMMDD_YYYYMMDD.parquet
├── gee_era5_land/
│   └── batch_YYYYMMDD_YYYYMMDD.parquet
├── gee_era5_blh/
│   └── batch_YYYYMMDD_YYYYMMDD.parquet
├── gee_s5p_no2/
│   └── batch_YYYYMMDD_YYYYMMDD.parquet
├── gee_modis_maiac_lst/
│   └── batch_YYYYMMDD_YYYYMMDD.parquet
├── gee_cams/
│   └── batch_YYYYMMDD_YYYYMMDD.parquet
├── esa_worldcover_source/
│   └── esa_worldcover_v200_source.tif
└── osm_source/
    └── roads_snapshot_source.pbf
```

## 3. Các tầng sau raw
* `data/interim/`: dữ liệu theo nguồn sau chuẩn hóa schema, đơn vị, UTC, QA và khóa; chưa phải bảng feature huấn luyện.
* `data/warehouse/`: dimension/fact chuẩn hóa, gồm lưới, station metadata, quan trắc station-day và feature grid-day.
* `data/processed/`: mart huấn luyện/đầu ra đã kiểm tra schema, có thể tái tạo từ warehouse.
* `data/external/`: ranh giới London, bảng tham chiếu, dữ liệu nền có giấy phép/phiên bản và `grid_master/london_grid_1km_epsg27700.geojson` được tạo có kiểm soát từ ranh giới. Lưu CRS, cấu hình và quy trình tạo lưới.

Không ghi dữ liệu dẫn xuất ngược vào `data/raw/`. Dữ liệu nguồn lớn, credential, model binary và dự đoán không được commit; manifest/metadata nhẹ có thể commit nếu không chứa bí mật.