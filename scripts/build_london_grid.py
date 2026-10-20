#!/usr/bin/env python3
"""Build a 1 km London grid and save it to data/external.

The script creates a simple 1 km grid covering Greater London using a bounding box,
then saves a CSV file with the required columns for later spatial assignment:

- grid_id
- centroid_lon
- centroid_lat
- bng_easting
- bng_northing

This matches the project schema used in docs/schema.md.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from pyproj import Transformer

DEFAULT_BBOX = {
    "min_lon": -0.55,
    "min_lat": 51.25,
    "max_lon": 0.35,
    "max_lat": 51.70,
}


def build_grid_1km(min_lon: float, min_lat: float, max_lon: float, max_lat: float, cell_size_km: float = 1.0) -> pd.DataFrame:
    """Create a 1km grid covering the requested bounding box.

    For geodesic correctness, the script uses a very simple projected conversion to
    the British National Grid (EPSG:27700), then builds cells in meters.
    """
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)

    e_min, n_min = transformer.transform(min_lon, min_lat)
    e_max, n_max = transformer.transform(max_lon, max_lat)

    cell_size_m = cell_size_km * 1000
    e_start = int(e_min // cell_size_m) * cell_size_m
    n_start = int(n_min // cell_size_m) * cell_size_m
    e_end = int(e_max // cell_size_m) * cell_size_m + cell_size_m
    n_end = int(n_max // cell_size_m) * cell_size_m + cell_size_m

    reverse_transformer = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)

    rows = []
    for e in range(int(e_start), int(e_end), int(cell_size_m)):
        for n in range(int(n_start), int(n_end), int(cell_size_m)):
            centroid_lon, centroid_lat = reverse_transformer.transform(e + cell_size_m / 2, n + cell_size_m / 2)
            grid_id = f"grid_{e}_{n}"
            rows.append(
                {
                    "grid_id": grid_id,
                    "centroid_lon": centroid_lon,
                    "centroid_lat": centroid_lat,
                    "bng_easting": e + cell_size_m / 2,
                    "bng_northing": n + cell_size_m / 2,
                }
            )

    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a 1 km London grid for PM2.5 modeling.")
    parser.add_argument("--min-lon", type=float, default=DEFAULT_BBOX["min_lon"])
    parser.add_argument("--min-lat", type=float, default=DEFAULT_BBOX["min_lat"])
    parser.add_argument("--max-lon", type=float, default=DEFAULT_BBOX["max_lon"])
    parser.add_argument("--max-lat", type=float, default=DEFAULT_BBOX["max_lat"])
    parser.add_argument("--cell-size-km", type=float, default=1.0)
    parser.add_argument("--out", default="data/external/london_grid_1km.csv")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    out_path = project_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = build_grid_1km(
        min_lon=args.min_lon,
        min_lat=args.min_lat,
        max_lon=args.max_lon,
        max_lat=args.max_lat,
        cell_size_km=args.cell_size_km,
    )

    df.to_csv(out_path, index=False)
    print(f"Saved {len(df)} grid cells to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
