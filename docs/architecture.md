# Project Architecture: London PM2.5 Spatial Estimation

## 1. Mục tiêu sản phẩm

Tạo bề mặt ước lượng PM2.5 trung bình ngày cho các ô lưới 1 km canonical của Greater London (1.577 ô có **tâm ô** nằm trong ranh giới ONS London; thêm 4 ô ngữ cảnh chứa trạm, xem [data_contract.md §4](data_contract.md)), trong cửa sổ 2023-01-01 → 2024-12-31 (UTC, 731 ngày), bằng quan trắc trạm sẵn có kết hợp feature khí tượng, vệ tinh và đô thị. Đây là ước lượng không gian hồi cứu/đồng thời, không phải dự báo tương lai.

Hai use case, không trộn lẫn: **mô hình lai** (`pm25_estimate`) cần số đo trạm cùng ngày và là sản phẩm chính; **mô hình thuần** (`pm25_estimate_pure`) không cần số đo trạm lúc suy luận và là mốc tham chiếu. Giới hạn sử dụng: chỉ trong cửa sổ dữ liệu, chỉ cho ngày có số đo trạm (lai), không nói trước tương lai, không phản ánh ô nhiễm sát đường ở độ phân giải 1 km.

Quan trắc trạm là nhãn tại vị trí trạm, không phải ground truth trực tiếp cho toàn ô. Grain nhãn chuẩn là `(station_key, date)`; mã trạm/nguồn gốc được giữ để truy vết. Grain feature và sản phẩm bản đồ là `(grid_id, date)`. Dự đoán tại ô không có trạm phải được ghi rõ là model estimate và đi kèm thông tin bất định/hỗ trợ quan trắc khi có thể.

## 2. Cấu trúc thư mục chuẩn

```text
pm25_london/
├── README.md
├── pyproject.toml
├── Makefile
├── .env.example
├── .gitignore
├── configs/
│   └── config.yaml
├── data/                         # không commit dữ liệu thực
│   ├── raw/                      # nguồn nguyên bản, bất biến, manifest + checksum
│   ├── interim/                  # chuẩn hóa theo nguồn, đơn vị, UTC, QA
│   ├── warehouse/                # dimension/fact chuẩn hóa
│   ├── processed/                # feature mart và dữ liệu sẵn sàng train
│   └── external/                 # ranh giới, bảng tham chiếu, dữ liệu nền
├── scripts/                      # entry points mỏng gọi các hàm trong src
├── src/
│   ├── config.py
│   ├── ingest/                   # OpenAQ/LAQN, ERA5, S5P, MODIS, CAMS, OSM
│   ├── features/                 # grid, labels, build_features
│   ├── models/                   # baselines, spatial_cv, train, evaluate, explain
│   ├── aqi.py
│   └── viz/
├── notebooks/                    # EDA/diagnostics; chỉ gọi src
├── models/                       # artifacts cục bộ, không commit mặc định
├── reports/
│   ├── figures/
│   ├── tables/
│   ├── predictions/              # grid-day predictions + run_id
│   └── final_report.md
├── app/                           # ứng dụng đọc artifact đã tạo
├── tests/                         # unit/schema/leakage tests, không cần dữ liệu thật
├── docs/
└── .github/workflows/ci.yml
```

**Trạng thái thực tế của cây thư mục (cập nhật sau Phase 2).** Sơ đồ trên là cấu trúc **mục tiêu**. Hiện tại chưa tồn tại: `pyproject.toml`, `Makefile`, `configs/config.yaml`, `src/config.py`, `src/aqi.py`, `reports/final_report.md`, `.github/workflows/ci.yml`, `data/raw/_registry.json`. Các thư mục `src/*`, `app/`, `configs/`, `.github/workflows/`, `reports/figures/` chỉ có `.gitkeep`. Toàn bộ logic đang nằm trong `scripts/` (bao gồm module kiểm tra hợp đồng dữ liệu `scripts/quality_gates.py`). Layout raw thực tế: `data/raw/openaq_chunks/`, `openaq_cache/`, `openaq_station_meta/`, `gee_chunks/<nguồn>/` (các nguồn: `era5land`, `cams`, `s5p`, `lst`; **không có `maiac`**), `station_meta.csv`, `pm25_labels.csv`, `outside_stations.csv`. Từ Phase 2, hai script chẩn đoán dữ liệu thật (`test.py`, `coverage.py`) đã được chuyển sang `scripts/inspect_gee_chunks.py` và `scripts/station_coverage_report.py`; thư mục `tests/` chứa bộ unit test tự động `tests/test_quality_gates.py` chạy bằng `unittest` độc lập với dữ liệu thật.

## 3. Luồng dữ liệu

1. **Raw:** Lưu payload/batch nguyên bản, dataset/version, truy vấn, thời gian tải, giấy phép và SHA-256 trong registry. Không sửa hoặc ghi đè raw.
2. **Interim:** Chuẩn hóa tên cột, kiểu, đơn vị, timestamp UTC, QA và khóa nguồn. Giữ cờ chất lượng và nguồn gốc.
3. **Warehouse:** Tạo `dim_grid_1km`, metadata trạm, nhãn station-day và fact feature grid-day. Giữ đầy đủ khóa và lineage.
4. **Processed:** Tạo spine mọi `(grid_id, date)` cùng feature mart; tạo bảng training station-day riêng bằng cách nối nhãn trạm với feature ô chứa trạm. Không chuyển nhãn trạm thành ground truth cho mọi ô.
   * *Thứ tự thực thi hiện tại:* `build_warehouse_facts.py` → `build_feature_marts.py` → `build_spatial_static_features.py` (bước cuối ghi feature tĩnh vào `dim_grid_1km` và vào hai mart đã có).
   * *Đề xuất refactor dài hạn:* Tái cấu trúc pipeline để dựng feature tĩnh thành đầu vào trước khi tạo mart, thay vì script feature tĩnh ghi đè/cập nhật mart đã tạo.
5. **Train/evaluate:** Chạy baseline và mô hình theo grouped spatial folds. Mọi preprocessing hoặc feature dùng nhãn được fit/tạo trong train fold.
6. **Predictions/reports/app:** Ghi dự đoán toàn lưới theo `(run_id, grid_id, date)`, metadata model/config và chỉ báo hỗ trợ; báo cáo metric chỉ từ quan trắc held-out.

## 4. Grain và quy tắc đánh giá

* `fact_ground_truth_daily`: một dòng mỗi `(station_key, date)` có số đo, kèm `valid_hours_count` và cờ `is_valid_day` (hiện 22.881 dòng, trong đó 20.351 hợp lệ làm nhãn); lưu `station_id`, `grid_id`, `site_type`. Nguồn (`source_name`, `source_station_id`) và tọa độ trạm thật tra qua `dim_station`; lưu thẳng trên fact là V2.
* `mart_grid_daily_features`: một dòng mỗi `(grid_id, date)` trong vùng/ngày cấu hình. Feature có thể thiếu nhưng không làm rơi spine; lưu missing/valid flags.
* `mart_station_daily_training`: một dòng mỗi `(station_key, date)` có nhãn hợp lệ và feature tại ô chứa trạm.
* `prediction_grid_daily`: mục tiêu một dòng mỗi `(run_id, grid_id, date)`; tách biệt với nhãn quan trắc. **Artifact hiện tại chưa có `run_id`** (grain thực tế `(grid_id, date)`) và chưa có chỉ báo số trạm có số đo trong ngày.
* Spatial holdout theo cụm địa điểm/trạm là kiểm định chính. Các station ID trùng vị trí phải ở cùng fold. *Hiện trạng:* `train_spatial_models.py` nhóm theo `grid_id` rồi nối các ô có tâm cách nhau ≤ 1,5 km (36 nhóm cho 92 trạm), vì mart chưa có `site_group`; mart huấn luyện chưa có tọa độ trạm thật nên khoảng cách/IDW tính từ tâm ô. IDW/KNN/kriging/residual chỉ dùng station train; residual feature train phải cross-fit.
* Temporal split trong cửa sổ nghiên cứu chỉ kiểm tra độ ổn định, không chứng minh dự báo tương lai. Pixel/lưới nguồn thô hơn 1 km vẫn giữ độ phân giải vật lý gốc dù được resample.

## 5. Thứ tự triển khai

1. Kiểm tra độ phủ và chất lượng station-day, vị trí trạm, loại trạm, vùng thiếu trạm và khả năng lấy dữ liệu nguồn.
2. Xây lưới và nhãn station-day; viết kiểm thử CRS, spatial join, khóa và QC.
3. Tạo feature mart tối thiểu cùng baseline train-mean/IDW; hoàn thiện grouped spatial CV và kiểm thử leakage.
4. Thêm feature khí tượng/tĩnh, sau đó vệ tinh/CAMS theo ablation trên cùng folds.
5. Chỉ sau khi có đánh giá holdout ổn định mới bổ sung uncertainty, SHAP, bản đồ và Streamlit.

## 6. Ranh giới vận hành

`data/`, `models/`, `.env` và dữ liệu có thông tin xác thực không được commit. `.env.example` chỉ chứa tên biến và giá trị mẫu không nhạy cảm. Notebook không chứa logic pipeline cốt lõi. `Makefile`/CLI chỉ điều phối các entry point trong `src` và `scripts`.
