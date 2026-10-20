"""Lay PM2.5 trung binh ngay tu OpenAQ (API v3) va tao 2 file de ghep voi grid_daily:

  station_meta.csv : station_id, grid_id, lat, lon (+ name, site_type, sensor_id)
  pm25_labels.csv  : station_id, date, pm25

pip install requests pandas numpy pyproj pyarrow

Can API key (dang ky mien phi tai https://explore.openaq.org), dat bien moi truong:
  export OPENAQ_API_KEY=...        (Windows PowerShell: $env:OPENAQ_API_KEY="...")

Vi du (chay tu thu muc goc data_science):
  python scripts/fetch_openaq.py --start 2025-01-01 --end 2025-12-31 \
      --grid data/processed/grid_daily.parquet

--grid: dung de gan tram vao DUNG o luoi cua ban (so khop theo toa do tam o, khong phu thuoc
cach dat ten grid_id). Neu bo --grid, script tu sinh grid_id = BNG_<floor(E/1000)>_<floor(N/1000)>
- khi do hay tu kiem tra co khop voi grid_id trong grid_daily khong.
"""

import argparse
import calendar
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

BASE = "https://api.openaq.org/v3"
PM25_PARAM_ID = 2
CELL_M = 1000          # kich thuoc o luoi (m)
TOL_M = 50             # sai so cho phep khi so toa do


def load_env_file():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


load_env_file()


class Client:
    def __init__(self, key):
        self.s = requests.Session()
        self.s.headers["X-API-Key"] = key

    def get(self, path, **params):
        for attempt in range(6):
            try:
                r = self.s.get(BASE + path, params=params, timeout=60)
            except requests.exceptions.RequestException:
                if attempt == 5:
                    raise
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (408, 429):
                try:
                    wait = float(r.headers.get("Retry-After", 5 * 2 ** attempt))
                except ValueError:
                    wait = 5 * 2 ** attempt
                print(f"  HTTP {r.status_code}, cho {wait:.0f}s ...", file=sys.stderr)
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                if attempt == 5:
                    r.raise_for_status()
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            time.sleep(1.1)  # giu duoi gioi han ~60 request/phut
            return r.json()
        raise RuntimeError(f"Loi khi goi {path} sau nhieu lan thu")

    def pages(self, path, limit=1000, **params):
        page = 1
        while True:
            js = self.get(path, limit=limit, page=page, **params)
            res = js.get("results", [])
            yield from res
            if len(res) < limit:
                break
            page += 1


def fetch_stations(client, bbox, start, end):
    rows = []
    metadata_fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for loc in client.pages("/locations", bbox=bbox, parameters_id=PM25_PARAM_ID):
        sensor = next((s for s in loc.get("sensors", [])
                       if s.get("parameter", {}).get("name") == "pm25"), None)
        coords = loc.get("coordinates") or {}
        if sensor is None or coords.get("latitude") is None:
            continue
        first = (loc.get("datetimeFirst") or {}).get("utc")
        last = (loc.get("datetimeLast") or {}).get("utc")
        if (last and last[:10] < start) or (first and first[:10] > end):
            continue  # tram khong co du lieu trong khoang can lay
        rows.append({
            "station_key": f"openaq_{loc['id']}",
            "source_name": "OpenAQ",
            "source_id": "openaq",
            "source_api_version": "v3",
            "source_station_id": str(loc["id"]),
            "metadata_fetched_at_utc": metadata_fetched_at,
            "station_id": f"OAQ_{loc['id']}",
            "station_name": loc.get("name"),
            "name": loc.get("name"),
            "lat": coords["latitude"],
            "lon": coords["longitude"],
            "latitude": coords["latitude"],
            "longitude": coords.get("longitude"),
            "site_type": loc.get("locationType") or loc.get("type") or "Unknown",
            "is_monitor": bool(loc.get("isMonitor", False)),
            "sensor_id": sensor["id"],
            "sensor_units": (sensor.get("parameter") or {}).get("units"),
            "timezone": loc.get("timezone"),
        })
    return pd.DataFrame(rows)


def assign_grid(st, grid_path):
    from pyproj import Transformer
    st = st.copy()
    tr = Transformer.from_crs(4326, 27700, always_xy=True)  # WGS84 -> British National Grid
    E, N = tr.transform(st["lon"].values, st["lat"].values)

    if not grid_path:
        st["grid_id"] = [f"BNG_{int(e // CELL_M)}_{int(n // CELL_M)}" for e, n in zip(E, N)]
        print("CANH BAO: khong co --grid, grid_id duoc tu sinh theo BNG_<E km>_<N km>; "
              "hay kiem tra co khop grid_daily.", file=sys.stderr)
        return st

    if grid_path.lower().endswith(".parquet"):
        g = pd.read_parquet(grid_path)
    else:
        g = pd.read_csv(grid_path)
    if "grid_id" not in g:
        raise ValueError("Grid file must include grid_id.")
    lon_col = "centroid_lon" if "centroid_lon" in g else "center_lon"
    lat_col = "centroid_lat" if "centroid_lat" in g else "center_lat"
    has_bng = {"bng_easting", "bng_northing"}.issubset(g.columns)
    if not has_bng and not {lon_col, lat_col}.issubset(g.columns):
        raise ValueError("Grid must include centroid_lon/centroid_lat or center_lon/center_lat.")
    keep = ["grid_id"] + (["bng_easting", "bng_northing"] if has_bng else [lon_col, lat_col])
    g = g[keep]
    g = g.dropna().drop_duplicates("grid_id").reset_index(drop=True)
    if g.empty:
        raise ValueError("Grid file contains no usable grid cells.")
    if has_bng:
        gE = g["bng_easting"].to_numpy(dtype=float)
        gN = g["bng_northing"].to_numpy(dtype=float)
    else:
        gE, gN = tr.transform(g[lon_col].values, g[lat_col].values)

    # khoang cach Chebyshev toi tam tung o; tram nam trong o neu <= nua canh o
    d = np.maximum(np.abs(E[:, None] - gE[None, :]), np.abs(N[:, None] - gN[None, :]))
    idx = d.argmin(axis=1)
    inside = d[np.arange(len(E)), idx] <= CELL_M / 2 + TOL_M
    st["grid_id"] = np.where(inside, g["grid_id"].values[idx], None)
    return st


def month_windows(start, end):
    start_day = date.fromisoformat(start)
    end_day = date.fromisoformat(end)
    if end_day < start_day:
        raise ValueError("--end must be on or after --start.")
    windows = []
    current = start_day
    while current <= end_day:
        last_day = calendar.monthrange(current.year, current.month)[1]
        window_end = min(date(current.year, current.month, last_day), end_day)
        windows.append((current.isoformat(), window_end.isoformat()))
        current = window_end + timedelta(days=1)
    return windows


def parse_utc_hour(item):
    period = item.get("period") or {}
    datetime_from = period.get("datetimeFrom") or {}
    value = datetime_from.get("utc") if isinstance(datetime_from, dict) else datetime_from
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def pm25_unit_scale(units):
    normalized = str(units or "").strip().lower()
    normalized = (normalized.replace("μ", "u").replace("µ", "u")
                  .replace("³", "3").replace("^", "").replace(" ", ""))
    scales = {
        "ug/m3": 1.0,
        "ugm-3": 1.0,
        "mg/m3": 1000.0,
        "mgm-3": 1000.0,
        "ng/m3": 0.001,
        "ngm-3": 0.001,
    }
    if normalized not in scales:
        raise ValueError(f"Unsupported PM2.5 sensor units {units!r}; expected concentration units convertible to µg/m³.")
    return scales[normalized]


def fetch_daily(client, sensor_id, start, end, cache_dir, min_valid_hours=18, units="µg/m³"):
    unit_scale = pm25_unit_scale(units)
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, f"sensor_{sensor_id}_{start}_{end}_hourly_utc.csv")
    if os.path.exists(cache):
        hourly_daily = pd.read_csv(cache)
    else:
        hourly = {}
        for item in client.pages(
            f"/sensors/{sensor_id}/hours",
            datetime_from=f"{start}T00:00:00Z",
            datetime_to=f"{end}T23:59:59Z",
        ):
            value = item.get("value")
            hour = parse_utc_hour(item)
            if value is None or hour is None or not np.isfinite(float(value)) or float(value) < 0:
                continue
            if start <= hour.date().isoformat() <= end:
                hourly[hour] = float(value)

        if hourly:
            hourly_df = pd.DataFrame(
                [(hour, value) for hour, value in hourly.items()],
                columns=["hour_utc", "pm25_hourly"],
            )
            hourly_df["date"] = hourly_df["hour_utc"].map(lambda value: value.date().isoformat())
            hourly_daily = (
                hourly_df.groupby("date", as_index=False)
                .agg(pm25_raw_mean=("pm25_hourly", "mean"), valid_hours_count=("pm25_hourly", "count"))
            )
        else:
            hourly_daily = pd.DataFrame(columns=["date", "pm25_raw_mean", "valid_hours_count"])
        hourly_daily.to_csv(cache, index=False)

    if hourly_daily.empty:
        return pd.DataFrame(columns=["date", "pm25_raw_mean", "pm25_obs", "valid_hours_count", "is_valid_day"])
    hourly_daily["valid_hours_count"] = pd.to_numeric(hourly_daily["valid_hours_count"], errors="coerce").fillna(0).astype("int16")
    hourly_daily["pm25_raw_mean"] = pd.to_numeric(hourly_daily["pm25_raw_mean"], errors="coerce")
    hourly_daily["is_valid_day"] = (hourly_daily["valid_hours_count"] >= min_valid_hours).astype("int8")
    hourly_daily["pm25_obs"] = (hourly_daily["pm25_raw_mean"] * unit_scale).where(hourly_daily["is_valid_day"].eq(1))
    hourly_daily["source_units"] = units
    return hourly_daily[["date", "pm25_raw_mean", "source_units", "pm25_obs", "valid_hours_count", "is_valid_day"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--bbox", default="-0.60,51.20,0.40,51.80",
                    help="minLon,minLat,maxLon,maxLat (mac dinh: bao quanh London)")
    ap.add_argument("--grid", help="grid_daily.parquet/csv de gan tram vao o luoi")
    ap.add_argument("--meta-out", default="data/raw/station_meta.csv")
    ap.add_argument("--labels-out", default="data/raw/pm25_labels.csv")
    ap.add_argument("--outside-out", default="data/raw/outside_stations.csv",
                    help="noi luu cac tram khong map duoc vao o luoi nao")
    ap.add_argument("--cache-dir", default="data/raw/openaq_cache")
    ap.add_argument("--chunks-dir", default="data/raw/openaq_chunks",
                    help="thu muc luu raw chunk theo thang")
    ap.add_argument("--min-valid-hours", type=int, default=18,
                    help="so gio toi thieu de danh dau ngay hop le (mac dinh: 18)")
    args = ap.parse_args()

    try:
        windows = month_windows(args.start, args.end)
    except ValueError as exc:
        ap.error(str(exc))
    if not 1 <= args.min_valid_hours <= 25:
        ap.error("--min-valid-hours must be between 1 and 25.")

    key = os.environ.get("OPENAQ_API_KEY")
    if not key:
        sys.exit("Thieu OPENAQ_API_KEY (lay tai https://explore.openaq.org)")
    client = Client(key)
    fetched_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("1/3 Tim tram PM2.5 trong bbox ...")
    st = fetch_stations(client, args.bbox, args.start, args.end)
    if st.empty:
        sys.exit("Khong tim thay tram nao")
    print(f"  {len(st)} tram co sensor pm25")

    print("2/3 Gan tram vao o luoi ...")
    st = assign_grid(st, args.grid)
    outside = st["grid_id"].isna()
    if outside.any():
        os.makedirs(os.path.dirname(args.outside_out) or ".", exist_ok=True)
        st[outside].to_csv(args.outside_out, index=False)
        print(f"  bo {int(outside.sum())} tram nam ngoai luoi (luu de debug: {args.outside_out})")
    st = st[~outside].reset_index(drop=True)
    print(f"  giu {len(st)} tram, {st['grid_id'].nunique()} o luoi khac nhau")

    print("3/3 Lay PM2.5 theo gio, tong hop ngay UTC ...")
    os.makedirs(args.chunks_dir, exist_ok=True)
    fact_columns = [
        "station_key", "source_name", "source_id", "source_api_version", "source_station_id", "station_id", "grid_id",
        "date", "site_type", "pm25_raw_mean", "source_units", "pm25_obs", "pm25", "valid_hours_count",
        "is_valid_day", "sensor_id", "fetched_at_utc",
    ]
    parts = []
    for month_start, month_end in windows:
        month_rows = []
        for i, row in st.iterrows():
            daily = fetch_daily(
                client, row["sensor_id"], month_start, month_end, args.cache_dir,
                min_valid_hours=args.min_valid_hours,
                units=row["sensor_units"],
            )
            if daily.empty:
                continue
            daily = daily.assign(
                station_key=row["station_key"],
                source_name=row["source_name"],
                source_id=row["source_id"],
                source_api_version=row["source_api_version"],
                source_station_id=row["source_station_id"],
                station_id=row["station_id"],
                grid_id=row["grid_id"],
                site_type=row["site_type"],
                pm25=daily["pm25_obs"],
                sensor_id=row["sensor_id"],
                fetched_at_utc=fetched_at_utc,
            )
            month_rows.append(daily[fact_columns])
            print(f"  {month_start[:7]} [{i + 1}/{len(st)}] {row['station_id']}: {len(daily)} ngay")

        chunk = pd.concat(month_rows, ignore_index=True) if month_rows else pd.DataFrame(columns=fact_columns)
        chunk = chunk.drop_duplicates(["station_key", "date"]).sort_values(["station_key", "date"])
        chunk_path = os.path.join(args.chunks_dir, f"openaq_chunk_{month_start[:7]}.csv")
        chunk.to_csv(chunk_path, index=False)
        print(f"  Luu raw chunk: {chunk_path} ({len(chunk)} dong)")
        if not chunk.empty:
            parts.append(chunk)

    if not parts:
        sys.exit("Khong co du lieu PM2.5 nao trong khoang ngay nay")

    labels = pd.concat(parts, ignore_index=True)
    labels = labels.drop_duplicates(["station_key", "date"]).sort_values(["station_key", "date"])
    st = st[st["station_key"].isin(labels["station_key"])].copy()

    for p in (args.meta_out, args.labels_out):
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    meta_columns = [
        "station_key", "source_name", "source_id", "source_api_version", "source_station_id",
        "metadata_fetched_at_utc", "station_id", "grid_id",
        "station_name", "name", "longitude", "latitude", "lon", "lat", "site_type",
        "is_monitor", "sensor_id", "sensor_units", "timezone",
    ]
    st[meta_columns].to_csv(args.meta_out, index=False)
    labels.to_csv(args.labels_out, index=False)
    print(f"\n{args.meta_out}: {len(st)} tram | {args.labels_out}: {len(labels)} dong")


if __name__ == "__main__":
    main()