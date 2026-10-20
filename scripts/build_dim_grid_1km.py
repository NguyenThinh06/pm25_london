#!/usr/bin/env python3
"""Dung dim_grid_1km: loc luoi nen theo ranh gioi Greater London + cot hinh hoc.

Doc : data/external/london_grid_1km.csv   (luoi chu nhat tu build_london_grid)
      file ranh gioi: .shp/.gpkg/.geojson, hoac .zip chua shapefile
      data/interim/dim_station.parquet|csv (de kiem tra tram nam trong luoi)
Ghi : data/warehouse/dim_grid_1km.parquet va .csv

Cach dung (chay tu thu muc goc du an):
    pip install geopandas pyogrio pyarrow pyproj

    # Cach 1: Tu dong tai ranh gioi Greater London tu ONS neu chua co:
    python scripts/build_dim_grid_1km.py --download-boundary

    # Cach 2: Truyen file ranh gioi co san:
    python scripts/build_dim_grid_1km.py --boundary data/external/greater_london.geojson

    # file ranh gioi nhieu vung (vd cac vung nuoc Anh) thi loc them:
    python scripts/build_dim_grid_1km.py --boundary data/external/regions.gpkg \
        --filter-col RGN24NM --filter-value London
"""
from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GRID_IN = ROOT / "data/external/london_grid_1km.csv"
STATION_FILES = [ROOT / "data/interim/dim_station.parquet", ROOT / "data/interim/dim_station.csv"]
OUT_DIR = ROOT / "data/warehouse"
BOUNDARY_EXT = (".shp", ".gpkg", ".geojson", ".json")
CHARING_CROSS_LONLAT = (-0.12776, 51.50739)
EXPECTED_CELLS = (1300, 2200)

# ONS Region December 2023 Boundary for London (E12000007)
ONS_LONDON_URL = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "Regions_December_2023_Boundaries_EN_BFC/FeatureServer/0/query"
    "?where=RGN23NM%20%3D%20'London'&outFields=*&outSR=4326&f=geojson"
)


def resolve_path(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    q = ROOT / arg
    if q.exists():
        return q
    sys.exit(f"Khong tim thay file: {arg}")


def download_ons_boundary(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Dang tai ranh gioi Greater London tu ONS -> {dest} ...")
    req = urllib.request.Request(ONS_LONDON_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
        f.write(resp.read())
    print("Tai thanh cong.")
    return dest


def find_boundary_file(arg: str | None, auto_download: bool = False) -> Path:
    """Tra ve duong dan file doc duoc bang geopandas (giai nen zip neu can)."""
    if auto_download:
        dest = ROOT / "data/external/greater_london_boundary.geojson"
        if not dest.exists():
            return download_ons_boundary(dest)
        return dest

    if arg is None:
        found = [
            p for p in sorted((ROOT / "data/external").glob("*"))
            if p.suffix.lower() in BOUNDARY_EXT + (".zip",)
        ]
        if not found:
            # Thu tu dong download neu thu muc trong
            dest = ROOT / "data/external/greater_london_boundary.geojson"
            print("Khong tim thay file ranh gioi nao trong data/external/.")
            return download_ons_boundary(dest)
        if len(found) > 1:
            sys.exit(
                "Dung --boundary <file>. Trong data/external/ tim thay nhieu file: "
                + ", ".join(p.name for p in found)
            )
        p = found[0]
    else:
        p = resolve_path(arg)

    if p.suffix.lower() == ".zip":
        dest = p.with_suffix("")
        if not dest.exists():
            shutil.unpack_archive(p, dest)
        shp = sorted(dest.rglob("*.shp")) + sorted(dest.rglob("*.gpkg")) + sorted(dest.rglob("*.geojson"))
        if len(shp) != 1:
            sys.exit(
                f"Trong {p.name} co {len(shp)} file ranh gioi: {[s.name for s in shp]}. "
                "Truyen thang duong dan .shp can dung vao --boundary."
            )
        return shp[0]
    return p


def load_grid() -> pd.DataFrame:
    if not GRID_IN.exists():
        sys.exit(f"Khong tim thay luoi nen: {GRID_IN}. Hay chay scripts/build_london_grid.py truoc.")
    g = pd.read_csv(GRID_IN)
    need = {"grid_id", "bng_easting", "bng_northing"}
    if not need <= set(g.columns):
        sys.exit(f"Luoi nen thieu cot: {sorted(need - set(g.columns))}")
    if g["grid_id"].duplicated().any():
        sys.exit("grid_id trong luoi nen bi trung.")
    if not {"centroid_lon", "centroid_lat"} <= set(g.columns):
        from pyproj import Transformer

        tr = Transformer.from_crs(27700, 4326, always_xy=True)
        g["centroid_lon"], g["centroid_lat"] = tr.transform(
            g["bng_easting"].to_numpy(float), g["bng_northing"].to_numpy(float)
        )
    return g


def load_station_cells() -> set[str] | None:
    for f in STATION_FILES:
        if f.exists():
            df = pd.read_parquet(f) if f.suffix == ".parquet" else pd.read_csv(f)
            for col in ("grid_id", "grid_id_computed", "grid_id_chunk"):
                if col in df.columns:
                    cells = set(df[col].dropna().astype(str))
                    if cells:
                        return cells
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--boundary", default=None, help=".shp/.gpkg/.geojson hoac .zip")
    ap.add_argument("--download-boundary", action="store_true", help="tu dong tai GeoJSON ranh gioi London tu ONS")
    ap.add_argument("--filter-col", default=None, help="cot de loc vung London trong file ranh gioi")
    ap.add_argument("--filter-value", default=None, help="gia tri cua cot do (vd London)")
    ap.add_argument("--drop-station-cells", action="store_true",
                    help="khong giu o chua tram neu tam o nam ngoai ranh gioi")
    ap.add_argument("--force", action="store_true", help="bo qua canh bao so o bat thuong")
    a = ap.parse_args()

    try:
        import geopandas as gpd
    except ImportError:
        sys.exit("Thieu geopandas: pip install geopandas pyogrio")
    from pyproj import Transformer

    grid = load_grid()
    bpath = find_boundary_file(a.boundary, auto_download=a.download_boundary)
    bd = gpd.read_file(bpath)
    print(f"Ranh gioi: {bpath.name} | {len(bd)} doi tuong | CRS ban dau: {bd.crs}")
    if bd.crs is None:
        sys.exit("File ranh gioi khong co CRS.")
    if a.filter_col:
        if a.filter_col not in bd.columns:
            sys.exit(f"Khong co cot {a.filter_col}. Cac cot: {list(bd.columns)}")
        bd = bd[bd[a.filter_col].astype(str) == str(a.filter_value)]
        if bd.empty:
            sys.exit(f"Khong co dong nao co {a.filter_col} = {a.filter_value}")
    bd = bd.to_crs(27700)
    try:
        bd["geometry"] = bd.geometry.make_valid()
    except Exception:
        pass
    try:
        geom = bd.geometry.union_all()
    except AttributeError:
        geom = bd.geometry.unary_union
    print(f"Dien tich ranh gioi: {geom.area / 1e6:,.1f} km2 (Greater London ~1,572 km2)")

    pts = gpd.GeoSeries(gpd.points_from_xy(grid["bng_easting"], grid["bng_northing"]), crs=27700)
    inside = pts.intersects(geom).to_numpy()
    n_in = int(inside.sum())
    print(f"Luoi nen: {len(grid)} o | tam nam trong ranh gioi: {n_in}")
    if not (EXPECTED_CELLS[0] <= n_in <= EXPECTED_CELLS[1]) and not a.force:
        sys.exit(
            f"So o ({n_in}) nam ngoai khoang hop ly {EXPECTED_CELLS} cho Greater London. "
            "Kiem tra file ranh gioi (co dung London khong, can --filter-col?). Dung --force neu chac."
        )

    grid["in_boundary"] = inside
    keep = grid["in_boundary"].copy()

    cells = load_station_cells()
    if cells is None:
        print("Khong tim thay dim_station -> bo qua kiem tra tram.")
    else:
        base = set(grid["grid_id"])
        kept_ids = set(grid.loc[keep, "grid_id"])
        out_of_grid = sorted(cells - base)
        out_of_boundary = sorted((cells & base) - kept_ids)
        print(f"Tram: {len(cells)} o chua tram | trong ranh gioi: {len(cells & kept_ids)} | "
              f"tam o ngoai ranh gioi: {len(out_of_boundary)} | khong co trong luoi nen: {len(out_of_grid)}")
        if out_of_boundary:
            print("  o chua tram nam ngoai ranh gioi:", out_of_boundary)
            if not a.drop_station_cells:
                keep |= grid["grid_id"].isin(out_of_boundary)
                print("  -> van giu cac o nay (in_boundary = False)")
        if out_of_grid:
            print("  CANH BAO: o chua tram khong thuoc luoi nen:", out_of_grid)

    out = grid.loc[keep].copy()
    tr = Transformer.from_crs(4326, 27700, always_xy=True)
    ce, cn = tr.transform(*CHARING_CROSS_LONLAT)
    out["dist_to_charing_cross_km"] = (
        np.hypot(out["bng_easting"] - ce, out["bng_northing"] - cn) / 1000
    ).astype("float32")
    cols = ["grid_id", "centroid_lon", "centroid_lat", "bng_easting", "bng_northing",
            "dist_to_charing_cross_km", "in_boundary"]
    out = out[cols].sort_values(["bng_easting", "bng_northing"]).reset_index(drop=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_DIR / "dim_grid_1km.parquet", index=False)
    out.to_csv(OUT_DIR / "dim_grid_1km.csv", index=False)
    print(f"\nDa ghi {len(out)} o ({int(out['in_boundary'].sum())} trong ranh gioi, "
          f"{int((~out['in_boundary']).sum())} giu vi chua tram) -> {OUT_DIR / 'dim_grid_1km.parquet'}")
    print(f"Khoang cach toi Charing Cross: {out['dist_to_charing_cross_km'].min():.1f} - "
          f"{out['dist_to_charing_cross_km'].max():.1f} km")


if __name__ == "__main__":
    main()