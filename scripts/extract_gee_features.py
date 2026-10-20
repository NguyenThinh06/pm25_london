#!/usr/bin/env python
"""Trich feature tu Google Earth Engine cho tung o luoi 1 km, chunk theo thang.

Nguon: era5land, cams, s5p, lst, maiac
Dau ra: data/raw/gee_chunks/<nguon>/<nguon>_<YYYY-MM>.parquet
        Ten cot khop schema.md; buoc dung fact_* se chi con noi cac chunk + ep kieu.

Cach dung (chay tu thu muc goc du an):
    # 1) Kiem tra dataset/band/don vi truoc, in ra 3 o dau tien cua 1 ngay
    python scripts/extract_gee_features.py --probe 2023-06-15 era5land cams s5p lst maiac

    # 2) Chay that (co the ngat giua chung, chay lai se bo qua thang da xong)
    python scripts/extract_gee_features.py era5land cams --start 2023-01 --end 2024-12
    python scripts/extract_gee_features.py s5p lst maiac --start 2023-01 --end 2024-12

Can: pip install earthengine-api pandas pyarrow pyproj
     earthengine authenticate   (mot lan)
     GEE_PROJECT=<ten project> trong .env (hoac --project)

Quy uoc ngay: UTC (filterDate theo ngay UTC), khop schema.md.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

try:
    import ee
except ImportError:  # cho phep import file de test phan pandas
    ee = None

ROOT = Path(__file__).resolve().parents[1]
GRID_CANDIDATES = [
    ROOT / "data/external/london_grid_1km.csv",  # dung dau gach cheo, khong dung \e
    ROOT / "data/warehouse/dim_grid_1km.parquet",
    ROOT / "data/warehouse/dim_grid_1km.csv",
    ROOT / "data/interim/dim_grid_1km.parquet",
    ROOT / "data/interim/dim_grid_1km.csv",
]
OUT_DIR = ROOT / "data/raw/gee_chunks"
PROJECT_KEYS = ("GEE_PROJECT", "EE_PROJECT", "GOOGLE_CLOUD_PROJECT")

# CAMS NRT: moi anh la 1 forecast. Lay forecast_hour < 12 de moi gio hieu luc
# lay tu chu ky moi nhat (00Z -> 00-11h, 12Z -> 12-23h). XAC MINH bang --probe.
CAMS_MAX_FORECAST_HOUR = 12

# Khung rong quanh Greater London (lon_min, lat_min, lon_max, lat_max). Dung de
# loc granule MAIAC: filterDate thuan tra ~1500 granule toan cau moi ngay.
LONDON_BBOX = [-0.8, 51.1, 0.6, 51.9]


# --------------------------------------------------------------------------
# .env, luoi
# --------------------------------------------------------------------------
def load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[7:].strip()
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def load_grid(path: str | None = None) -> pd.DataFrame:
    p = Path(path) if path else next((c for c in GRID_CANDIDATES if c.exists()), None)
    if p is None or not p.exists():
        sys.exit("Khong tim thay dim_grid_1km. Dung --grid <duong dan .parquet/.csv>.")
    df = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
    gid = df["grid_id"].astype(str)
    m = gid.str.extract(r"grid_(\d+)_(\d+)$")
    if m.notna().all().all():  # quy uoc grid_{E_goc}_{N_goc}
        e0, n0 = m[0].astype(int), m[1].astype(int)
    elif {"bng_easting", "bng_northing"} <= set(df.columns):  # tam o -> goc o
        e0 = (df["bng_easting"] - 500).round().astype(int)
        n0 = (df["bng_northing"] - 500).round().astype(int)
    else:
        sys.exit("grid_id khong theo dang grid_E_N va thieu bng_easting/bng_northing.")
    from pyproj import Transformer

    tr = Transformer.from_crs(27700, 4326, always_xy=True)
    lon, lat = tr.transform((e0 + 500).to_numpy(float), (n0 + 500).to_numpy(float))
    out = pd.DataFrame({"grid_id": gid, "e0": e0, "n0": n0, "lon": lon, "lat": lat})
    return out.drop_duplicates("grid_id").reset_index(drop=True)


def make_fc(grid: pd.DataFrame, kind: str):
    feats = []
    for r in grid.itertuples(index=False):
        if kind == "polygon":
            geom = ee.Geometry.Rectangle(
                [int(r.e0), int(r.n0), int(r.e0) + 1000, int(r.n0) + 1000], "EPSG:27700", False
            )
        else:  # nguon tho (ERA5-Land, CAMS): lay gia tri pixel chua tam o
            geom = ee.Geometry.Point([float(r.lon), float(r.lat)])
        feats.append(ee.Feature(geom, {"grid_id": r.grid_id}))
    return ee.FeatureCollection(feats)


# --------------------------------------------------------------------------
# Dinh nghia nguon
# --------------------------------------------------------------------------
def _col(cid: str, d):
    return ee.ImageCollection(cid).filterDate(d, d.advance(1, "day"))


def safe_composite(col, bands: list[str], how: str = "mean"):
    """Composite ngay; neu ngay khong co anh thi tra anh bi mask het (khong loi)."""
    empty = ee.Image.constant([0] * len(bands)).rename(bands).selfMask()
    comp = getattr(col.select(bands), how)()
    return ee.Image(ee.Algorithms.If(col.size().gt(0), comp, empty))


def _base(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"grid_id": df["grid_id"].to_numpy(), "date": df["date"].to_numpy()})


def _f(s):
    return s.astype("float32")


def _px(s):
    return s.fillna(0).astype("int16")


def _flag(s):
    return (s.fillna(0) > 0).astype("int8")


@dataclass
class Source:
    name: str
    kind: str          # polygon (nguon ~1 km) | point (nguon tho)
    scale: float
    crs: str
    raw: Callable      # (ee.Date) -> ImageCollection goc, dung cho --probe
    image: Callable    # (ee.Date) -> ee.Image da doi ten band
    raw_props: list    # cac thuoc tinh ky vong sau reduceRegions
    post: Callable     # (DataFrame tho) -> DataFrame dung ten cot schema
    variants: dict = field(default_factory=dict)  # chi dung cho --probe (chan doan)


# ---- S5P NO2 --------------------------------------------------------------
S5P_ID = "COPERNICUS/S5P/OFFL/L3_NO2"


def s5p_image(d):
    col = _col(S5P_ID, d).select(
        ["tropospheric_NO2_column_number_density", "cloud_fraction"], ["no2", "cloud"]
    )
    return safe_composite(col, ["no2", "cloud"])


def s5p_post(df):
    o = _base(df)
    o["s5p_no2_mean"] = _f(df["no2_mean"])
    o["s5p_cloud_frac"] = _f(df["cloud_mean"])
    o["s5p_no2_valid_px"] = _px(df["no2_count"])
    o["s5p_no2_valid_flag"] = _flag(df["no2_count"])
    return o


# ---- MODIS LST (Terra, MOD11A1) ------------------------------------------
LST_ID = "MODIS/061/MOD11A1"


def lst_image(d):
    col = _col(LST_ID, d).select(["LST_Day_1km", "LST_Night_1km"], ["lst_day", "lst_night"])
    col = ee.ImageCollection(col.map(lambda i: i.multiply(0.02).subtract(273.15)))  # K -> C
    return safe_composite(col, ["lst_day", "lst_night"])


def lst_post(df):
    o = _base(df)
    o["modis_lst_day_c"] = _f(df["lst_day_mean"])
    o["modis_lst_night_c"] = _f(df["lst_night_mean"])
    o["modis_lst_day_valid_px"] = _px(df["lst_day_count"])
    o["modis_lst_night_valid_px"] = _px(df["lst_night_count"])
    o["modis_lst_day_valid_flag"] = _flag(df["lst_day_count"])
    o["modis_lst_night_valid_flag"] = _flag(df["lst_night_count"])
    return o


# ---- MAIAC AOD ------------------------------------------------------------
MAIAC_ID = "MODIS/061/MCD19A2_GRANULES"


def _maiac_col(d):
    return _col(MAIAC_ID, d).filterBounds(ee.Geometry.Rectangle(LONDON_BBOX))


def maiac_image_mode(mode: str):
    """mode: full (cloud clear + QA tot nhat) | cloud_only | no_qa (chi de chan doan)."""

    def image(d):
        def prep(i):
            qa = i.select("AOD_QA")
            aod = i.select("Optical_Depth_055").multiply(0.001)
            clear = qa.bitwiseAnd(7).eq(1)                # bit 0-2: cloud mask = clear
            best = qa.rightShift(8).bitwiseAnd(15).eq(0)  # bit 8-11: QA AOD = best quality
            if mode == "full":
                aod = aod.updateMask(clear.And(best))
            elif mode == "cloud_only":
                aod = aod.updateMask(clear)
            return aod.rename("aod")

        col = ee.ImageCollection(_maiac_col(d).map(prep))
        return safe_composite(col, ["aod"])

    return image


maiac_image = maiac_image_mode("full")


def maiac_post(df):
    o = _base(df)
    o["modis_aod_055_mean"] = _f(df["aod_mean"])
    o["modis_aod_valid_px"] = _px(df["aod_count"])
    o["modis_aod_valid_flag"] = _flag(df["aod_count"])
    return o


# ---- ERA5-Land (hourly -> daily, UTC) ------------------------------------
ERA5L_ID = "ECMWF/ERA5_LAND/HOURLY"


def era5l_image(d):
    def derive(i):
        t = i.select("temperature_2m").subtract(273.15)
        td = i.select("dewpoint_temperature_2m").subtract(273.15)
        u = i.select("u_component_of_wind_10m")
        v = i.select("v_component_of_wind_10m")
        a, b = 17.625, 243.04  # Magnus
        rh = (
            td.multiply(a).divide(td.add(b)).exp()
            .divide(t.multiply(a).divide(t.add(b)).exp())
            .multiply(100).min(100)
        )
        return ee.Image.cat([
            t.rename("t2m"), rh.rename("rh"), u.rename("u10"), v.rename("v10"),
            u.hypot(v).rename("ws"),
            i.select("surface_pressure").divide(100).rename("sp"),
            i.select("total_precipitation_hourly").multiply(1000).rename("pr"),
        ])

    col = ee.ImageCollection(_col(ERA5L_ID, d).map(derive))
    mean = safe_composite(col, ["t2m", "rh", "u10", "v10", "ws", "sp"], "mean")
    pr = safe_composite(col, ["pr"], "sum")
    return mean.addBands(pr)


def era5l_post(df):
    o = _base(df)
    o["t2m_mean_c"] = _f(df["t2m"])
    o["rh_mean_pct"] = _f(df["rh"])
    o["u10_vector_mean"] = _f(df["u10"])
    o["v10_vector_mean"] = _f(df["v10"])
    o["wind_speed_scalar_mean"] = _f(df["ws"])
    o["precip_sum_mm"] = _f(df["pr"])
    o["sp_mean_hpa"] = _f(df["sp"])
    return o


# ---- CAMS NRT -------------------------------------------------------------
CAMS_ID = "ECMWF/CAMS/NRT"


def cams_image(d):
    col = (
        _col(CAMS_ID, d)
        .filter(ee.Filter.lt("model_forecast_hour", CAMS_MAX_FORECAST_HOUR))
        .select(
            ["particulate_matter_d_less_than_25_um_surface",
             "total_aerosol_optical_depth_at_550nm_surface"],
            ["pm25", "aod"],
        )
    )
    # kg/m3 -> ug/m3
    col = ee.ImageCollection(
        col.map(lambda i: ee.Image.cat([i.select("pm25").multiply(1e9), i.select("aod")]))
    )
    return safe_composite(col, ["pm25", "aod"])


def cams_post(df):
    o = _base(df)
    o["cams_aod_550"] = _f(df["aod"])
    o["cams_pm25_bg"] = _f(df["pm25"])
    return o


def build_sources() -> dict[str, Source]:
    return {
        "era5land": Source("era5land", "point", 11132, "EPSG:4326",
                           lambda d: _col(ERA5L_ID, d), era5l_image,
                           ["t2m", "rh", "u10", "v10", "ws", "sp", "pr"], era5l_post),
        "cams": Source("cams", "point", 44528, "EPSG:4326",
                       lambda d: _col(CAMS_ID, d), cams_image,
                       ["pm25", "aod"], cams_post),
        "s5p": Source("s5p", "polygon", 1000, "EPSG:27700",
                      lambda d: _col(S5P_ID, d), s5p_image,
                      ["no2_mean", "no2_count", "cloud_mean", "cloud_count"], s5p_post),
        "lst": Source("lst", "polygon", 1000, "EPSG:27700",
                      lambda d: _col(LST_ID, d), lst_image,
                      ["lst_day_mean", "lst_day_count", "lst_night_mean", "lst_night_count"],
                      lst_post),
        "maiac": Source("maiac", "polygon", 1000, "EPSG:27700",
                        _maiac_col, maiac_image,
                        ["aod_mean", "aod_count"], maiac_post,
                        variants={"chi_loc_may": maiac_image_mode("cloud_only"),
                                  "khong_loc_QA": maiac_image_mode("no_qa")}),
    }


ALL_SOURCES = ["era5land", "cams", "s5p", "lst", "maiac"]


# --------------------------------------------------------------------------
# Chay
# --------------------------------------------------------------------------
def fetch_day(src: Source, fc, day: date, retries: int = 6) -> pd.DataFrame:
    for k in range(retries):
        try:
            d = ee.Date(day.isoformat())
            img = src.image(d)
            if src.kind == "polygon":
                red = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
                kw = {"tileScale": 4}
            else:
                red, kw = ee.Reducer.first(), {}
            res = img.reduceRegions(
                collection=fc, reducer=red, scale=src.scale, crs=src.crs, **kw
            )
            info = res.select([".*"], None, False).getInfo()
            df = pd.DataFrame([f["properties"] for f in info["features"]])
            df["date"] = pd.Timestamp(day)
            return df
        except Exception as e:  # het quota/timeout: doi roi thu lai
            if k == retries - 1:
                raise
            wait = min(60, 2 ** (k + 1))
            print(f"  [{src.name} {day}] loi {type(e).__name__}: thu lai sau {wait}s", flush=True)
            time.sleep(wait)


def run_month(src: Source, fc, n_cells: int, ym: str, workers: int, force: bool) -> None:
    path = OUT_DIR / src.name / f"{src.name}_{ym}.parquet"
    if path.exists() and not force:
        print(f"[{src.name}] {ym}: da co, bo qua")
        return
    y, m = map(int, ym.split("-"))
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    days = [start + timedelta(i) for i in range((end - start).days)]
    t0 = time.time()
    frames = []
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(fetch_day, src, fc, d) for d in days]
        for f in as_completed(futs):
            frames.append(f.result())
    df = pd.concat(frames, ignore_index=True)
    df = df.reindex(columns=["grid_id", "date"] + src.raw_props)
    out = src.post(df).sort_values(["date", "grid_id"]).reset_index(drop=True)
    expected = n_cells * len(days)
    note = "" if len(out) == expected else f"  CANH BAO: {len(out)} dong, ky vong {expected}"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    out.to_parquet(tmp, index=False)
    tmp.replace(path)
    value_cols = [c for c in out.columns if c not in ("grid_id", "date") and "valid" not in c]
    miss = out[value_cols].isna().all(axis=1).mean() if value_cols else 0.0
    print(f"[{src.name}] {ym}: {len(out)} dong, {miss:.1%} dong rong, {time.time()-t0:.0f}s{note}",
          flush=True)


def probe(src: Source, grid: pd.DataFrame, day: str) -> None:
    d = ee.Date(day)
    col = src.raw(d)
    n = col.size().getInfo()
    print(f"\n=== {src.name} | {day} | {n} anh goc ===")
    if n:
        first = col.first()
        print("band :", first.bandNames().getInfo())
        print("prop :", first.propertyNames().getInfo())
    if src.name == "cams":  # kiem tra cac anh con lai sau bo loc forecast_hour
        sel = col.filter(ee.Filter.lt("model_forecast_hour", CAMS_MAX_FORECAST_HOUR))
        rows = sel.reduceColumns(
            ee.Reducer.toList(3),
            ["system:time_start", "model_initialization_hour", "model_forecast_hour"],
        ).get("list").getInfo()
        print(f"sau loc forecast_hour < {CAMS_MAX_FORECAST_HOUR}: {len(rows)} anh (ky vong 8)")
        for t, ih, fh in sorted(rows):
            print("  time_start", pd.to_datetime(t, unit="ms"), "| init_hour", ih, "| forecast_hour", fh)
    df = fetch_day(src, make_fc(grid.head(3), src.kind), date.fromisoformat(day))
    print(src.post(df.reindex(columns=["grid_id", "date"] + src.raw_props)).T.to_string())
    _coverage(src, grid, day, "ca luoi")
    for name, fn in src.variants.items():
        _coverage(replace(src, image=fn), grid, day, name)


def _coverage(src: Source, grid: pd.DataFrame, day: str, label: str) -> None:
    """Ty le o co du lieu tren TOAN luoi (3 o dau co the khong dai dien)."""
    df = fetch_day(src, make_fc(grid, src.kind), date.fromisoformat(day))
    out = src.post(df.reindex(columns=["grid_id", "date"] + src.raw_props))
    cols = [c for c in out.columns if c not in ("grid_id", "date") and "valid" not in c]
    frac = out[cols].notna().mean().round(3).to_dict()
    print(f"  [{label}] {len(out)} o | ty le co du lieu: {frac}")


def months(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    y2, m2 = map(int, end.split("-"))
    out = []
    while (y, m) <= (y2, m2):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("sources", nargs="*",
                    help="era5land cams s5p lst maiac (bo trong = tat ca)")
    ap.add_argument("--start", default="2023-01")
    ap.add_argument("--end", default="2024-12")
    ap.add_argument("--workers", type=int, default=4, help="so ngay chay song song")
    ap.add_argument("--project", default=None, help="GEE project (mac dinh doc tu .env)")
    ap.add_argument("--grid", default=None, help="duong dan dim_grid_1km")
    ap.add_argument("--probe", default=None, metavar="YYYY-MM-DD",
                    help="chi kiem tra 1 ngay, in 3 o dau tien")
    ap.add_argument("--force", action="store_true", help="ghi de chunk da co")
    a = ap.parse_args()

    if ee is None:
        sys.exit("Thieu earthengine-api: pip install earthengine-api")
    load_env()
    project = a.project or next((os.environ[k] for k in PROJECT_KEYS if os.environ.get(k)), None)
    if not project:
        sys.exit("Thieu GEE project: dat GEE_PROJECT trong .env hoac dung --project.")
    try:
        ee.Initialize(project=project)
    except Exception as e:
        sys.exit(f"Khong khoi tao duoc GEE ({e}). Chay: earthengine authenticate")

    grid = load_grid(a.grid)
    print(f"Luoi: {len(grid)} o | project: {project}")
    srcs = build_sources()
    chosen = a.sources or ALL_SOURCES
    bad = [s for s in chosen if s not in srcs]
    if bad:
        sys.exit(f"Nguon khong hop le: {bad}. Chon trong {ALL_SOURCES}")

    if a.probe:
        for name in chosen:
            probe(srcs[name], grid, a.probe)
        return

    fcs: dict[str, object] = {}
    for name in chosen:
        src = srcs[name]
        fcs.setdefault(src.kind, make_fc(grid, src.kind))
        for ym in months(a.start, a.end):
            run_month(src, fcs[src.kind], len(grid), ym, a.workers, a.force)


if __name__ == "__main__":
    main()