#!/usr/bin/env python3
"""Build Warehouse Facts and Dimensions for London PM2.5 Spatial Estimation.

Nhiệm vụ:
1. dim_station: Chuẩn hóa từ data/interim/dim_station.parquet -> data/warehouse/dim_station.parquet
2. fact_ground_truth_daily: Chuẩn hóa quan trắc trạm từ openaq_daily.parquet, bổ sung site_type
3. fact_meteo_daily: Hợp nhất ERA5-Land (9 biến) + CAMS (AOD, PM2.5 nền), lọc theo dim_grid_1km (1,581 ô)
4. fact_satellite_daily: Hợp nhất Sentinel-5P (NO2, mây) + MODIS LST (nhiệt độ ngày/đêm), lọc theo dim_grid_1km

Chạy từ thư mục gốc:
    python scripts/build_warehouse_facts.py
    python scripts/build_warehouse_facts.py --sources meteo satellite ground_truth station
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
INTERIM_DIR = ROOT / "data/interim"
GEE_DIR = ROOT / "data/raw/gee_chunks"
GRID_FILE = WAREHOUSE_DIR / "dim_grid_1km.parquet"


def get_valid_grid_ids() -> set[str]:
    if not GRID_FILE.exists():
        sys.exit(f"Không tìm thấy {GRID_FILE}. Hãy chạy scripts/build_dim_grid_1km.py trước.")
    gdf = pd.read_parquet(GRID_FILE)
    return set(gdf["grid_id"].astype(str))


def build_dim_station() -> pd.DataFrame:
    print("\n--- [1/4] Xây dựng dim_station ---")
    src_file = INTERIM_DIR / "dim_station.parquet"
    if not src_file.exists():
        print(f"  [!] Không tìm thấy {src_file}. Bỏ qua.")
        return pd.DataFrame()

    df = pd.read_parquet(src_file)
    print(f"  Đọc {len(df)} trạm từ {src_file.name}")

    # Chuẩn hóa cột grid_id
    if "grid_id" not in df.columns:
        if "grid_id_computed" in df.columns:
            df["grid_id"] = df["grid_id_computed"]
        elif "grid_id_chunk" in df.columns:
            df["grid_id"] = df["grid_id_chunk"]

    target_cols = [
        "station_key",
        "source_name",
        "source_station_id",
        "station_id",
        "station_name",
        "locality",
        "longitude",
        "latitude",
        "bng_easting",
        "bng_northing",
        "grid_id",
        "site_type",
        "site_type_source",
        "is_monitor",
        "provider",
    ]
    cols = [c for c in target_cols if c in df.columns]
    out = df[cols].copy().sort_values("station_key").reset_index(drop=True)

    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    out_pq = WAREHOUSE_DIR / "dim_station.parquet"
    out_csv = WAREHOUSE_DIR / "dim_station.csv"
    out.to_parquet(out_pq, index=False)
    out.to_csv(out_csv, index=False)
    print(f"  -> Đã ghi {len(out)} trạm vào {out_pq.name} và {out_csv.name}")
    return out


def build_fact_ground_truth(st_df: pd.DataFrame | None = None) -> pd.DataFrame:
    print("\n--- [2/4] Xây dựng fact_ground_truth_daily ---")
    src_file = INTERIM_DIR / "openaq_daily.parquet"
    if not src_file.exists():
        print(f"  [!] Không tìm thấy {src_file}. Bỏ qua.")
        return pd.DataFrame()

    df = pd.read_parquet(src_file)
    print(f"  Đọc {len(df):,} bản ghi từ {src_file.name}")

    # Chuẩn hóa ngày ISO 'YYYY-MM-DD'
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")

    # Điền site_type từ dim_station nếu có
    if st_df is not None and not st_df.empty and "site_type" in st_df.columns:
        st_map = st_df.set_index("station_key")["site_type"].to_dict()
        curr_unknown = df["site_type"].isna() | (df["site_type"] == "Unknown")
        df.loc[curr_unknown, "site_type"] = df.loc[curr_unknown, "station_key"].map(st_map).fillna("Unknown")

    # Đảm bảo các kiểu dữ liệu tối ưu
    df["pm25_obs"] = pd.to_numeric(df["pm25_obs"], errors="coerce").astype("float32")
    df["valid_hours_count"] = pd.to_numeric(df["valid_hours_count"], errors="coerce").fillna(0).astype("int8")
    df["is_valid_day"] = (df["valid_hours_count"] >= 18).astype("int8")

    cols = [
        "station_key",
        "station_id",
        "grid_id",
        "date",
        "site_type",
        "pm25_obs",
        "valid_hours_count",
        "is_valid_day",
    ]
    out = df[[c for c in cols if c in df.columns]].copy()
    out = out.sort_values(["date", "station_key"]).reset_index(drop=True)

    out_pq = WAREHOUSE_DIR / "fact_ground_truth_daily.parquet"
    out.to_parquet(out_pq, index=False)
    valid_count = int(out["is_valid_day"].sum())
    print(f"  -> Đã ghi {len(out):,} bản ghi ({valid_count:,} ngày hợp lệ is_valid_day=1) -> {out_pq.name}")
    return out


def _load_gee_source(source_name: str, valid_grid_ids: set[str]) -> pd.DataFrame:
    src_dir = GEE_DIR / source_name
    if not src_dir.exists():
        print(f"  [!] Thư mục {src_dir} không tồn tại.")
        return pd.DataFrame()

    files = sorted(src_dir.glob("*.parquet"))
    if not files:
        print(f"  [!] Không có file parquet nào trong {src_dir}")
        return pd.DataFrame()

    print(f"  Đang nạp {len(files)} file chunk cho nguồn {source_name}...")
    frames = []
    for f in files:
        df = pd.read_parquet(f)
        # Lọc ngay theo 1,581 ô chuẩn để tiết kiệm RAM
        df = df[df["grid_id"].isin(valid_grid_ids)]
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    res = pd.concat(frames, ignore_index=True)
    res["date"] = pd.to_datetime(res["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    res = res.drop_duplicates(subset=["grid_id", "date"]).reset_index(drop=True)
    print(f"    {source_name}: {len(res):,} dòng sau khi lọc và khử trùng lặp.")
    return res


def build_fact_meteo(valid_grid_ids: set[str]) -> pd.DataFrame:
    print("\n--- [3/4] Xây dựng fact_meteo_daily (ERA5-Land + CAMS) ---")
    era = _load_gee_source("era5land", valid_grid_ids)
    cams = _load_gee_source("cams", valid_grid_ids)

    if era.empty and cams.empty:
        print("  [!] Cả ERA5-Land và CAMS đều rỗng. Bỏ qua.")
        return pd.DataFrame()

    if era.empty:
        merged = cams
    elif cams.empty:
        merged = era
    else:
        print("  Đang hợp nhất ERA5-Land và CAMS theo (grid_id, date)...")
        merged = pd.merge(era, cams, on=["grid_id", "date"], how="outer")

    # Ép kiểu float32 cho các biến đo
    float_cols = [c for c in merged.columns if c not in ("grid_id", "date")]
    for c in float_cols:
        merged[c] = pd.to_numeric(merged[c], errors="coerce").astype("float32")

    merged = merged.sort_values(["date", "grid_id"]).reset_index(drop=True)
    out_pq = WAREHOUSE_DIR / "fact_meteo_daily.parquet"
    merged.to_parquet(out_pq, index=False)
    print(f"  -> Đã ghi {len(merged):,} dòng ({len(float_cols)} feature) -> {out_pq.name}")
    print(f"     Khoảng thời gian: {merged['date'].min()} đến {merged['date'].max()} | Số ô: {merged['grid_id'].nunique()}")
    return merged


def build_fact_satellite(valid_grid_ids: set[str]) -> pd.DataFrame:
    print("\n--- [4/4] Xây dựng fact_satellite_daily (Sentinel-5P + MODIS LST) ---")
    s5p = _load_gee_source("s5p", valid_grid_ids)
    lst = _load_gee_source("lst", valid_grid_ids)

    if s5p.empty and lst.empty:
        print("  [!] Cả Sentinel-5P và LST đều rỗng. Bỏ qua.")
        return pd.DataFrame()

    if s5p.empty:
        merged = lst
    elif lst.empty:
        merged = s5p
    else:
        print("  Đang hợp nhất Sentinel-5P và MODIS LST theo (grid_id, date)...")
        merged = pd.merge(s5p, lst, on=["grid_id", "date"], how="outer")

    # Ép kiểu dữ liệu: valid flags -> int8, values -> float32
    for c in merged.columns:
        if c in ("grid_id", "date"):
            continue
        if "flag" in c:
            merged[c] = pd.to_numeric(merged[c], errors="coerce").fillna(0).astype("int8")
        elif "valid_px" in c:
            merged[c] = pd.to_numeric(merged[c], errors="coerce").fillna(0).astype("int16")
        else:
            merged[c] = pd.to_numeric(merged[c], errors="coerce").astype("float32")

    merged = merged.sort_values(["date", "grid_id"]).reset_index(drop=True)
    out_pq = WAREHOUSE_DIR / "fact_satellite_daily.parquet"
    merged.to_parquet(out_pq, index=False)
    num_feats = len([c for c in merged.columns if c not in ("grid_id", "date")])
    print(f"  -> Đã ghi {len(merged):,} dòng ({num_feats} feature) -> {out_pq.name}")
    print(f"     Khoảng thời gian: {merged['date'].min()} đến {merged['date'].max()} | Số ô: {merged['grid_id'].nunique()}")
    return merged


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument(
        "--sources",
        nargs="+",
        default=["station", "ground_truth", "meteo", "satellite"],
        help="Các bảng cần build: station, ground_truth, meteo, satellite",
    )
    args = ap.parse_args()

    t0 = time.time()
    valid_grid_ids = get_valid_grid_ids()
    print(f"Khởi tạo tầng Warehouse với {len(valid_grid_ids)} ô lưới chuẩn từ {GRID_FILE.name}")

    st_df = None
    if "station" in args.sources:
        st_df = build_dim_station()

    if "ground_truth" in args.sources:
        build_fact_ground_truth(st_df)

    if "meteo" in args.sources:
        build_fact_meteo(valid_grid_ids)

    if "satellite" in args.sources:
        build_fact_satellite(valid_grid_ids)

    elapsed = time.time() - t0
    print(f"\n Hoàn tất xây dựng toàn bộ Fact Tables trong Warehouse ({elapsed:.1f}s)!")


if __name__ == "__main__":
    main()

