#!/usr/bin/env python3
"""Build Processed Feature Marts for PM2.5 Spatial Estimation.

Nhiệm vụ:
1. mart_grid_daily_features:
   - Spine không-thời gian: dim_grid_1km (1,581 ô) x Lịch ngày (2023-01-01 -> 2024-12-31, 731 ngày)
   - Left join với fact_meteo_daily (ERA5-Land, CAMS)
   - Left join với fact_satellite_daily (Sentinel-5P NO2, MODIS LST)
   - Tạo các feature chu kỳ lịch (sin/cos day_of_year, day_of_week, month, is_weekend)
   - Bổ sung các biến tĩnh khoảng cách (dist_to_charing_cross_km)
   -> Lưu vào data/processed/mart_grid_daily_features.parquet

2. mart_station_daily_training:
   - Nối fact_ground_truth_daily (nhãn quan trắc trạm pm25_obs) với feature tại ô lưới tương ứng
   - Lọc các ngày đạt tiêu chuẩn QC (is_valid_day = 1)
   -> Lưu vào data/processed/mart_station_daily_training.parquet (Tập dữ liệu huấn luyện ML)

Chạy từ thư mục gốc:
    python scripts/build_feature_marts.py
    python scripts/build_feature_marts.py --all-days  # bao gồm cả ngày is_valid_day = 0
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_DIR = ROOT / "data/warehouse"
PROCESSED_DIR = ROOT / "data/processed"

GRID_FILE = WAREHOUSE_DIR / "dim_grid_1km.parquet"
METEO_FILE = WAREHOUSE_DIR / "fact_meteo_daily.parquet"
SAT_FILE = WAREHOUSE_DIR / "fact_satellite_daily.parquet"
GROUND_TRUTH_FILE = WAREHOUSE_DIR / "fact_ground_truth_daily.parquet"
STATION_FILE = WAREHOUSE_DIR / "dim_station.parquet"


def check_prerequisites() -> None:
    missing = [f for f in [GRID_FILE, METEO_FILE, SAT_FILE, GROUND_TRUTH_FILE] if not f.exists()]
    if missing:
        sys.exit(
            f"Thiếu các bảng Warehouse sau: {[f.name for f in missing]}.\n"
            "Hãy chạy scripts/build_warehouse_facts.py trước."
        )


def generate_spatio_temporal_spine(grid_df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """Tạo tích Đề-các giữa 1,581 ô lưới và toàn bộ các ngày quan sát."""
    print(f"  Tạo spine không gian ({len(grid_df)} ô) x thời gian ({start_date} đến {end_date})...")
    date_range = pd.date_range(start_date, end_date, freq="D").strftime("%Y-%m-%d")
    
    # Tích Descartes giữa grid_id và date
    grid_ids = grid_df["grid_id"].to_numpy()
    grid_rep = np.repeat(grid_ids, len(date_range))
    date_rep = np.tile(date_range, len(grid_ids))
    
    spine = pd.DataFrame({"grid_id": grid_rep, "date": date_rep})
    
    # Ghép thông tin tĩnh từ dim_grid_1km
    static_cols = [
        "grid_id",
        "centroid_lon",
        "centroid_lat",
        "bng_easting",
        "bng_northing",
        "dist_to_charing_cross_km",
        "in_boundary",
    ]
    cols_to_merge = [c for c in static_cols if c in grid_df.columns]
    spine = spine.merge(grid_df[cols_to_merge], on="grid_id", how="left")
    return spine


def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Bổ sung các đặc trưng chu kỳ thời gian (sin/cos encoding)."""
    dt = pd.to_datetime(df["date"])
    df["month"] = dt.dt.month.astype("int8")
    df["day_of_week"] = dt.dt.dayofweek.astype("int8")
    df["day_of_year"] = dt.dt.dayofyear.astype("int16")
    df["is_weekend"] = (df["day_of_week"] >= 5).astype("int8")
    
    # Chu kỳ năm (Annual seasonality)
    doy = df["day_of_year"].to_numpy()
    df["sin_day_of_year"] = np.sin(2 * np.pi * doy / 365.25).astype("float32")
    df["cos_day_of_year"] = np.cos(2 * np.pi * doy / 365.25).astype("float32")
    
    # Chu kỳ tuần (Weekly traffic pattern)
    dow = df["day_of_week"].to_numpy()
    df["sin_day_of_week"] = np.sin(2 * np.pi * dow / 7.0).astype("float32")
    df["cos_day_of_week"] = np.cos(2 * np.pi * dow / 7.0).astype("float32")
    return df


def build_mart_grid_daily_features() -> pd.DataFrame:
    print("\n--- [1/2] Xây dựng mart_grid_daily_features (Feature Mart toàn lưới) ---")
    grid_df = pd.read_parquet(GRID_FILE)
    meteo_df = pd.read_parquet(METEO_FILE)
    sat_df = pd.read_parquet(SAT_FILE)
    
    start_date = meteo_df["date"].min()
    end_date = meteo_df["date"].max()
    
    # 1. Tạo spine
    spine = generate_spatio_temporal_spine(grid_df, start_date, end_date)
    print(f"  Spine hoàn tất: {len(spine):,} dòng.")
    
    # 2. Thêm calendar features
    print("  Đang tính toán đặc trưng chu kỳ lịch (sin/cos encoding)...")
    mart = add_calendar_features(spine)
    
    # 3. Join Meteo facts
    print("  Đang ghép nối fact_meteo_daily (ERA5-Land + CAMS)...")
    mart = mart.merge(meteo_df, on=["grid_id", "date"], how="left")
    
    # 4. Join Satellite facts
    print("  Đang ghép nối fact_satellite_daily (Sentinel-5P + MODIS LST)...")
    mart = mart.merge(sat_df, on=["grid_id", "date"], how="left")
    
    # 5. Sắp xếp và lưu
    mart = mart.sort_values(["date", "grid_id"]).reset_index(drop=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_pq = PROCESSED_DIR / "mart_grid_daily_features.parquet"
    mart.to_parquet(out_pq, index=False)
    
    feature_cols = [c for c in mart.columns if c not in ("grid_id", "date")]
    print(f"  -> Đã lưu {len(mart):,} dòng ({len(feature_cols)} feature) -> {out_pq.name}")
    print(f"     File size: {out_pq.stat().st_size / (1024 * 1024):.1f} MB")
    return mart


def build_mart_station_daily_training(grid_mart: pd.DataFrame, only_valid_days: bool = True) -> pd.DataFrame:
    print("\n--- [2/2] Xây dựng mart_station_daily_training (Tập dữ liệu huấn luyện ML) ---")
    gt_df = pd.read_parquet(GROUND_TRUTH_FILE)
    print(f"  Đọc {len(gt_df):,} bản ghi nhãn từ {GROUND_TRUTH_FILE.name}")
    
    if only_valid_days:
        n_before = len(gt_df)
        gt_df = gt_df[gt_df["is_valid_day"] == 1].dropna(subset=["pm25_obs"]).reset_index(drop=True)
        print(f"  Lọc ngày hợp lệ (is_valid_day=1 & pm25_obs not null): {n_before:,} -> {len(gt_df):,} dòng.")
    
    # Nối với feature tại ô lưới tương ứng
    print("  Đang nối nhãn trạm với feature ô lưới tại (grid_id, date)...")
    training = gt_df.merge(grid_mart, on=["grid_id", "date"], how="left")
    
    # Sắp xếp
    training = training.sort_values(["date", "station_key"]).reset_index(drop=True)
    out_pq = PROCESSED_DIR / "mart_station_daily_training.parquet"
    training.to_parquet(out_pq, index=False)
    
    print(f"  -> Đã lưu {len(training):,} mẫu huấn luyện ({len(training.columns)} cột) -> {out_pq.name}")
    print(f"     Trạm quan trắc duy nhất: {training['station_key'].nunique()}")
    print(f"     Nồng độ PM2.5 trung bình: {training['pm25_obs'].mean():.2f} µg/m³ (min: {training['pm25_obs'].min():.1f}, max: {training['pm25_obs'].max():.1f})")
    print(f"     Phân bố loại trạm (site_type):\n{training['site_type'].value_counts().to_string()}")
    return training


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--all-days", action="store_true", help="giữ cả các ngày is_valid_day = 0 trong tập training")
    args = ap.parse_args()

    t0 = time.time()
    check_prerequisites()
    
    # 1. Dựng mart toàn lưới
    grid_mart = build_mart_grid_daily_features()
    
    # 2. Dựng training mart
    build_mart_station_daily_training(grid_mart, only_valid_days=not args.all_days)
    
    elapsed = time.time() - t0
    print(f"\n Hoàn tất xây dựng toàn bộ Feature Marts trong {elapsed:.1f} giây!")


if __name__ == "__main__":
    main()

