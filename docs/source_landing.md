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


## 4. Hiện trạng thực tế so với layout mục tiêu (Pha 1 kiểm kê)
Mục 1–3 mô tả layout **mục tiêu**. Hiện tại:

* **Chưa có** `data/raw/_registry.json`, không có SHA-256 hay `license` theo lô; raw chưa được khóa phiên bản bằng registry. Layout raw thật:

| Thực tế | Nội dung | Ghi chú |
| :--- | :--- | :--- |
| `data/raw/openaq_chunks/openaq_chunk_YYYY-MM.csv` | Nhãn PM2.5 theo ngày-trạm từ OpenAQ v3 (`/sensors/{id}/hours`, tổng hợp ngày UTC) | Nguồn thật của `data/interim/openaq_daily.parquet` |
| `data/raw/openaq_cache/`, `openaq_station_meta/*.json` | Cache theo sensor và metadata location | Cache lưu trung bình ngày và số giờ, không lưu từng giờ |
| `data/raw/gee_chunks/<nguồn>/<nguồn>_YYYY-MM.parquet` | `era5land`, `cams`, `s5p`, `lst` (24 tháng); **không có `maiac`** | Chunk chứa 3.224 ô (lưới nền), warehouse lọc còn 1.581 ô |
| `data/raw/pm25_labels.csv`, `station_meta.csv`, `outside_stations.csv` | Đầu ra gộp của `fetch_openaq.py` | `pm25_labels.csv` (20.962 dòng) khác `openaq_daily.parquet` (22.881 dòng). Đề xuất mặc định (Q13): chưa xóa `pm25_labels.csv`, trước hết cần đối soát lineage và checksum; các chunk ngày tổng hợp được định danh chính xác là snapshot/landing đã chuẩn hóa, trừ khi có lưu hourly payload riêng. |
| `data/external/greater_london_boundary.geojson` | Ranh giới ONS Regions Dec 2023 (London) | Dùng chọn ô canonical |
| `data/external/london_grid_1km.csv` | Lưới nền 3.224 ô, tạo từ bounding box | Không phải `grid_master/london_grid_1km_epsg27700.geojson` |
| `data/external/major_roads_dft/` | Shapefile DfT Major Road Network 2018 (Open Roads) | Thay cho `osm_source/roads_snapshot_source.pbf` (không dùng OSM) |

* **Không có** `esa_worldcover_source/esa_worldcover_v200_source.tif`: WorldCover được đọc trực tiếp qua GEE (`ESA/WorldCover/v100`, năm 2020), không lưu bản sao cục bộ. Các nguồn BLH (`gee_era5_blh/`) và MAIAC (`gee_modis_maiac_lst/`, tách MAIAC khỏi LST) trong sơ đồ trên là kế hoạch **V2**, chưa có dữ liệu.
* Truy vấn GEE hiện lọc theo ngày UTC và không khóa phiên bản dataset ngoài ID trong code (`ECMWF/ERA5_LAND/HOURLY`, `ECMWF/CAMS/NRT`, `COPERNICUS/S5P/OFFL/L3_NO2`, `MODIS/061/MOD11A1`).
