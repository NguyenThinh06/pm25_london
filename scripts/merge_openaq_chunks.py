"""Gộp các chunk OpenAQ theo tháng thành một bảng ngày-trạm và thống kê độ phủ.

Chạy từ thư mục gốc pm25_london/:
    python scripts/merge_openaq_chunks.py
    python scripts/merge_openaq_chunks.py --start 2023-01 --end 2024-12 --min-valid-frac 0.6

Có thể chạy lại bất cứ lúc nào (kể cả khi đang cào): mỗi lần gộp lại toàn bộ,
bỏ trùng theo (station_key, date) và giữ bản fetched_at_utc mới nhất.
"""
import argparse
import re
import time
from pathlib import Path

import pandas as pd

CHUNK_DIR = Path("data/raw/openaq_chunks")
OUT_DIR = Path("data/interim")
MIN_HOURS = 18          # theo schema: >= 18 giờ -> is_valid_day = 1
MAX_PM25 = 500.0        # ngưỡng nghi ngờ giá trị quá cao (ug/m3)
SKIP_IF_YOUNGER_S = 60  # bỏ qua file vừa được ghi, có thể đang ghi dở

KEEP_COLS = [
    "station_key", "source_name", "source_station_id", "station_id", "grid_id",
    "date", "site_type", "pm25_obs", "valid_hours_count", "is_valid_day",
    "sensor_id", "fetched_at_utc",
]


def list_chunks():
    files, skipped = [], []
    for p in sorted(CHUNK_DIR.glob("openaq_chunk_*.csv")):
        if time.time() - p.stat().st_mtime < SKIP_IF_YOUNGER_S:
            skipped.append(p.name)
            continue
        files.append(p)
    return files, skipped


def month_of(path):
    m = re.search(r"(\d{4}-\d{2})", path.name)
    return m.group(1) if m else None


def load(files):
    frames = []
    for p in files:
        try:
            df = pd.read_csv(p, dtype={"station_id": "string", "grid_id": "string"})
        except pd.errors.EmptyDataError:
            print(f"  [!] file rỗng: {p.name}")
            continue
        df["_chunk"] = p.name
        frames.append(df)
    if not frames:
        raise SystemExit("Không có chunk nào để gộp.")
    return pd.concat(frames, ignore_index=True)


def normalize(df):
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["fetched_at_utc"] = pd.to_datetime(df["fetched_at_utc"], errors="coerce", utc=True)

    # pm25 / pm25_raw_mean trùng pm25_obs trong dữ liệu hiện tại -> chỉ giữ pm25_obs.
    if "pm25_obs" not in df.columns:
        df["pm25_obs"] = df.get("pm25")
    df["valid_hours_count"] = pd.to_numeric(df["valid_hours_count"], errors="coerce")
    df["pm25_obs"] = pd.to_numeric(df["pm25_obs"], errors="coerce")

    # Tính lại cờ hợp lệ từ định nghĩa trong schema để không phụ thuộc scraper.
    df["is_valid_day"] = (
        (df["valid_hours_count"] >= MIN_HOURS) & df["pm25_obs"].notna()
    ).astype("int8")
    # Ngày không hợp lệ thì không được dùng làm nhãn: giữ NaN, không điền 0.
    df.loc[df["is_valid_day"] == 0, "pm25_obs"] = pd.NA
    return df


def dedupe(df):
    before = len(df)
    df = df.sort_values("fetched_at_utc").drop_duplicates(
        subset=["station_key", "date"], keep="last"
    )
    print(f"Bỏ trùng (station_key, date): {before - len(df)} dòng")
    return df.sort_values(["station_key", "date"]).reset_index(drop=True)


def report(df, files, skipped, start, end):
    # 1) Tháng còn thiếu
    expected = [str(p) for p in pd.period_range(start, end, freq="M")]
    have = {month_of(p) for p in files}
    missing = [m for m in expected if m not in have]
    print(f"\nChunk có: {len(have)}/{len(expected)} tháng")
    if missing:
        print("Tháng chưa có chunk:", ", ".join(missing))
    if skipped:
        print("Bỏ qua (đang ghi dở?):", ", ".join(skipped))

    # 2) Kiểm tra chất lượng
    valid = df[df["is_valid_day"] == 1]
    print(f"\nTổng dòng: {len(df)} | ngày hợp lệ: {len(valid)} "
          f"({len(valid) / len(df):.1%})")
    print(f"pm25_obs < 0: {(valid['pm25_obs'] < 0).sum()} | "
          f"> {MAX_PM25:.0f}: {(valid['pm25_obs'] > MAX_PM25).sum()}")
    print(f"site_type = Unknown: {(df['site_type'] == 'Unknown').mean():.1%} số dòng")

    # Chuỗi đứng yên (nghi sensor lỗi): >= 5 ngày liên tiếp cùng giá trị
    flat = 0
    for _, g in valid.groupby("station_key"):
        run = g["pm25_obs"].round(3).ne(g["pm25_obs"].round(3).shift()).cumsum()
        flat += int((g.groupby(run)["pm25_obs"].transform("size") >= 5).any())
    print(f"Trạm có chuỗi >=5 ngày cùng giá trị: {flat}")

    # 3) Độ phủ theo trạm
    n_days = (pd.Timestamp(end) + pd.offsets.MonthEnd(0) - pd.Timestamp(start)).days + 1
    cov = (
        df.groupby("station_key")
        .agg(
            grid_id=("grid_id", "first"),
            site_type=("site_type", "first"),
            first_date=("date", "min"),
            last_date=("date", "max"),
            rows=("date", "size"),
            valid_days=("is_valid_day", "sum"),
        )
        .reset_index()
    )
    cov["valid_frac"] = cov["valid_days"] / n_days
    return cov.sort_values("valid_frac", ascending=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01")
    ap.add_argument("--end", default="2024-12")
    ap.add_argument("--min-valid-frac", type=float, default=0.6)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files, skipped = list_chunks()
    print(f"Đọc {len(files)} chunk...")
    df = normalize(load(files))
    df = dedupe(df)

    cols = [c for c in KEEP_COLS if c in df.columns]
    out = OUT_DIR / "openaq_daily.parquet"
    tmp = out.with_suffix(".tmp")
    df[cols].to_parquet(tmp, index=False)
    tmp.replace(out)  # ghi nguyên tử, tránh file hỏng nếu bị ngắt giữa chừng

    cov = report(df, files, skipped, args.start, args.end)
    cov.to_csv(OUT_DIR / "openaq_station_coverage.csv", index=False)

    usable = cov[cov["valid_frac"] >= args.min_valid_frac]
    print(f"\nSố trạm: {len(cov)} | dùng được (>= {args.min_valid_frac:.0%} ngày hợp lệ): "
          f"{len(usable)}")
    print(cov.head(15).to_string(index=False))
    print(f"\nĐã ghi {out} và {OUT_DIR / 'openaq_station_coverage.csv'}")


if __name__ == "__main__":
    main()