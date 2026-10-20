"""Dựng dim_station: lấy tọa độ/nhà cung cấp từ OpenAQ v3, gán site_type từ LAQN, kiểm tra grid_id.

Yêu cầu:
    pip install requests pyproj
    API key đọc từ file .env ở thư mục gốc (OPENAQ_API_KEY=...), hoặc từ biến môi trường.

Chạy từ thư mục gốc pm25_london/ (sau khi đã có data/interim/openaq_daily.parquet):
    python scripts/build_dim_station.py
    python scripts/build_dim_station.py --no-laqn          # bỏ qua bước gán site_type
    python scripts/build_dim_station.py --match-m 100      # ngưỡng ghép trạm OpenAQ <-> LAQN (mét)

Có cache JSON trong data/raw/openaq_station_meta/ nên chạy lại không gọi API lần nữa.
"""
import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from pyproj import Transformer

DAILY = Path("data/interim/openaq_daily.parquet")
CACHE = Path("data/raw/openaq_station_meta")
OUT_DIR = Path("data/interim")
OPENAQ_URL = "https://api.openaq.org/v3/locations/{}"
LAQN_URL = ("https://api.erg.ic.ac.uk/AirQuality/Information/"
            "MonitoringSites/GroupName=London/Json")
DUP_M = 50  # hai trạm gần hơn ngưỡng này (m) bị gắn cờ nghi trùng

KEY_NAMES = ("OPENAQ_API_KEY",)  # tên biến có thể có trong .env

to_bng = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)


def load_env(path=".env"):
    """Nạp .env vào os.environ (không ghi đè biến đã có). Dùng python-dotenv nếu có."""
    try:
        from dotenv import load_dotenv
        load_dotenv(path)
        return
    except ImportError:
        pass
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.removeprefix("export ").strip()
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def fetch_location(loc_id, key):
    """Lấy metadata 1 location, có cache. Trả về dict hoặc None nếu không tìm thấy."""
    cache = CACHE / f"{loc_id}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    for attempt in range(5):
        r = requests.get(OPENAQ_URL.format(loc_id), headers={"X-API-Key": key}, timeout=30)
        if r.status_code == 429:  # quá giới hạn tốc độ
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        results = r.json().get("results") or []
        if not results:
            return None
        CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(results[0], ensure_ascii=False), encoding="utf-8")
        time.sleep(1.1)  # free tier ~60 request/phút
        return results[0]
    raise RuntimeError(f"Location {loc_id}: bị giới hạn tốc độ quá nhiều lần")


def openaq_location_id(source_station_id):
    loc_id = str(source_station_id).strip()
    if loc_id.startswith("OAQ_"):
        loc_id = loc_id.removeprefix("OAQ_")
    if not loc_id.isdigit():
        raise ValueError(f"OpenAQ source_station_id không phải ID số: {source_station_id!r}")
    return loc_id


def parse_location(loc):
    if not loc:
        return {}
    coords = loc.get("coordinates") or {}
    return {
        "station_name": loc.get("name"),
        "locality": loc.get("locality"),
        "longitude": coords.get("longitude"),
        "latitude": coords.get("latitude"),
        "provider": (loc.get("provider") or {}).get("name"),
        "owner": (loc.get("owner") or {}).get("name"),
        "is_monitor": loc.get("isMonitor"),  # True = trạm tham chiếu, False = cảm biến
        "is_mobile": loc.get("isMobile"),
        "datetime_first_utc": (loc.get("datetimeFirst") or {}).get("utc"),
        "datetime_last_utc": (loc.get("datetimeLast") or {}).get("utc"),
    }


def grid_id_from_bng(e, n):
    """Quy ước: góc dưới-trái ô 1 km theo BNG (mét), vd grid_508000_177000."""
    return f"grid_{int(e // 1000) * 1000}_{int(n // 1000) * 1000}"


def load_laqn():
    r = requests.get(LAQN_URL, timeout=60)
    r.raise_for_status()
    sites = r.json()["Sites"]["Site"]
    if isinstance(sites, dict):
        sites = [sites]
    df = pd.DataFrame(sites).rename(columns=lambda c: c.lstrip("@"))
    df = df[["SiteCode", "SiteName", "SiteType", "Latitude", "Longitude"]].copy()
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df = df.dropna(subset=["Latitude", "Longitude"]).reset_index(drop=True)
    df["e"], df["n"] = to_bng.transform(df["Longitude"].values, df["Latitude"].values)
    return df


def assign_site_type(st, laqn, max_m):
    """Ghép từng trạm OpenAQ với trạm LAQN gần nhất trong max_m mét."""
    st["site_type"], st["site_type_source"] = "Unknown", "none"
    st["laqn_site_code"], st["laqn_match_m"] = None, np.nan
    ok = st["bng_easting"].notna()
    if not ok.any() or laqn.empty:
        return st
    de = st.loc[ok, "bng_easting"].values[:, None] - laqn["e"].values[None, :]
    dn = st.loc[ok, "bng_northing"].values[:, None] - laqn["n"].values[None, :]
    dist = np.hypot(de, dn)
    j = dist.argmin(axis=1)
    d = dist[np.arange(len(j)), j]
    idx = st.index[ok]
    for k, i in enumerate(idx):
        st.at[i, "laqn_match_m"] = round(float(d[k]), 1)  # luôn ghi để bạn tự kiểm tra
        if d[k] <= max_m:
            st.at[i, "site_type"] = laqn.at[j[k], "SiteType"]
            st.at[i, "site_type_source"] = "LAQN"
            st.at[i, "laqn_site_code"] = laqn.at[j[k], "SiteCode"]
    return st


def flag_duplicates(st):
    st["nearest_other_station_m"] = np.nan
    pos = np.where(st["bng_easting"].notna().values)[0]
    e, n = st["bng_easting"].values[pos], st["bng_northing"].values[pos]
    for a, i in enumerate(pos):
        d = np.delete(np.hypot(e - e[a], n - n[a]), a)  # bỏ chính nó
        if len(d):
            st.at[st.index[i], "nearest_other_station_m"] = round(float(d.min()), 1)
    st["possible_duplicate"] = st["nearest_other_station_m"] < DUP_M
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-laqn", action="store_true")
    ap.add_argument("--match-m", type=float, default=100.0)
    args = ap.parse_args()

    load_env()
    key = next((os.environ[n] for n in KEY_NAMES if os.environ.get(n)), None)

    daily = pd.read_parquet(DAILY)
    base = (
        daily.groupby("station_key")
        .agg(source_name=("source_name", "first"),
             source_station_id=("source_station_id", "first"),
             station_id=("station_id", "first"),
             grid_id_chunk=("grid_id", "first"))
        .reset_index()
    )
    source_ids = base["source_station_id"].map(openaq_location_id)
    need_api = [sid for sid in source_ids if not (CACHE / f"{sid}.json").exists()]
    if need_api and not key:
        raise SystemExit(f"Không tìm thấy API key trong .env/môi trường (đã thử: {', '.join(KEY_NAMES)}). "
                         "Sửa KEY_NAMES ở đầu file cho đúng tên biến trong .env của bạn.")

    rows = []
    for k, (sid, source_id) in enumerate(zip(base["station_id"], source_ids), 1):
        print(f"[{k}/{len(base)}] location {source_id} ({sid})")
        try:
            rows.append(parse_location(fetch_location(source_id, key)))
        except Exception as ex:  # một trạm lỗi không làm hỏng cả lượt chạy
            print(f"  [!] lỗi: {ex}")
            rows.append({})
    metadata_columns = [
        "station_name", "locality", "longitude", "latitude", "provider", "owner",
        "is_monitor", "is_mobile", "datetime_first_utc", "datetime_last_utc",
    ]
    st = pd.concat([base, pd.DataFrame(rows, columns=metadata_columns)], axis=1)

    st["longitude"] = pd.to_numeric(st["longitude"], errors="coerce")
    st["latitude"] = pd.to_numeric(st["latitude"], errors="coerce")
    ok = st["longitude"].notna() & st["latitude"].notna()
    if not ok.any():
        raise SystemExit("Không lấy được tọa độ cho trạm nào từ OpenAQ; kiểm tra API response/cache rồi chạy lại.")
    st.loc[ok, "bng_easting"], st.loc[ok, "bng_northing"] = to_bng.transform(
        st.loc[ok, "longitude"].values, st.loc[ok, "latitude"].values)
    st["grid_id_computed"] = [
        grid_id_from_bng(e, n) if pd.notna(e) else None
        for e, n in zip(st["bng_easting"], st["bng_northing"])
    ]
    st["grid_match"] = st["grid_id_computed"] == st["grid_id_chunk"]

    if args.no_laqn:
        st["site_type"], st["site_type_source"] = "Unknown", "none"
    else:
        try:
            st = assign_site_type(st, load_laqn(), args.match_m)
        except Exception as ex:
            print(f"[!] Không lấy được LAQN ({ex}); giữ site_type = Unknown")
            st["site_type"], st["site_type_source"] = "Unknown", "none"

    st = flag_duplicates(st)
    st["metadata_fetched_at_utc"] = pd.Timestamp.now(tz="UTC")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    st.to_parquet(OUT_DIR / "dim_station.parquet", index=False)
    st.to_csv(OUT_DIR / "dim_station.csv", index=False)

    print("\n=== Tóm tắt ===")
    print(f"Số trạm: {len(st)} | có tọa độ: {int(ok.sum())}")
    print(f"grid_id khớp với chunk: {int(st['grid_match'].sum())}/{len(st)}")
    print("is_monitor:", st["is_monitor"].value_counts(dropna=False).to_dict())
    print("provider:", st["provider"].value_counts(dropna=False).to_dict())
    print("site_type:", st["site_type"].value_counts(dropna=False).to_dict())
    print(f"Trạm nghi trùng (< {DUP_M} m): {int(st['possible_duplicate'].sum())}")
    bad = st[~st["grid_match"]]
    if len(bad):
        print("\nTrạm lệch grid_id (kiểm tra quy ước ô lưới):")
        print(bad[["station_key", "grid_id_chunk", "grid_id_computed"]].to_string(index=False))
    print(f"\nĐã ghi {OUT_DIR / 'dim_station.parquet'} và dim_station.csv")


if __name__ == "__main__":
    main()