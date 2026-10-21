#!/usr/bin/env python3
"""Data Contract V1 Quality Gates for the London PM2.5 Pipeline.

Cung cấp các hàm kiểm tra tính toàn vẹn dữ liệu (keys, grains, foreign keys,
UTC dates, joins, spine completeness, label QC rules, satellite flags và
feature allowlist cho chế độ exploratory vs certified).

Tất cả các hàm đều độc lập với dữ liệu thật trên đĩa và API bên ngoài,
ném `DataContractError` kèm thông tin chi tiết khi phát hiện vi phạm.
"""
from __future__ import annotations

import re
import sys
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class DataContractError(ValueError):
    """Ngoại lệ ném ra khi dữ liệu hoặc cấu hình vi phạm Data Contract V1."""


MIN_VALID_HOURS_V1: int = 18
MIN_HOURS_BOUND: int = 0
MAX_HOURS_BOUND: int = 24

GRID_ID_REGEX = re.compile(r"^grid_\d+_\d+$")
ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Danh sách 18 feature [V1] đã xác minh ngữ nghĩa đầy đủ trong code và dữ liệu hiện có
# (0% NULL trong fact_meteo_daily và dim_grid_1km, không bị ép null->0, không phụ thuộc QA vệ tinh chưa kiểm chứng).
CERTIFIED_V1_FEATURES: tuple[str, ...] = (
    "major_road_length_m",
    "dist_to_charing_cross_km",
    "month",
    "day_of_week",
    "is_weekend",
    "sin_day_of_year",
    "cos_day_of_year",
    "sin_day_of_week",
    "cos_day_of_week",
    "t2m_mean_c",
    "rh_mean_pct",
    "u10_vector_mean",
    "v10_vector_mean",
    "wind_speed_scalar_mean",
    "precip_sum_mm",
    "sp_mean_hpa",
    "cams_aod_550",
    "cams_pm25_bg",
)

# Danh sách các feature [V1-chưa xác minh] đang có trong parquet nhưng KHÔNG được phép
# đưa vào mô hình "certified" cho tới khi hoàn tất xác minh QA / ngữ nghĩa ở Phase 3.
UNVERIFIED_V1_FEATURES: dict[str, str] = {
    "dist_to_thames_km": (
        "[V1-chưa xác minh] Thực tế tính khoảng cách raster tới lớp nước thường trực "
        "WorldCover Class 80, không phải sông Thames (dự kiến đổi tên thành "
        "dist_to_nearest_mapped_water_km hoặc tính từ geometry sông thực)."
    ),
    "population_density": (
        "[V1-chưa xác minh] Band gốc GHSL là population_count (số người/pixel 100m lấy mẫu 30m), "
        "không phải mật độ người/km² (dự kiến chuyển sang ghsl_population_count)."
    ),
    "built_up_frac": (
        "[V1-chưa xác minh] Reducer null bị ép về 0.0 (hoặc 0) nên chưa phân biệt được "
        "0 thật và dữ liệu thiếu/ngoài vùng phủ; cần giữ NULL và cờ coverage ở Phase 3."
    ),
    "tree_cover_frac": (
        "[V1-chưa xác minh] Reducer null bị ép về 0.0 (hoặc 0) nên chưa phân biệt được "
        "0 thật và dữ liệu thiếu/ngoài vùng phủ; cần giữ NULL và cờ coverage ở Phase 3."
    ),
    "elevation_m": (
        "[V1-chưa xác minh] Reducer null bị ép về 0.0 (hoặc 0) nên chưa phân biệt được "
        "0 thật và dữ liệu thiếu; cần giữ NULL và cờ coverage ở Phase 3."
    ),
    "s5p_cloud_frac": (
        "[V1-chưa xác minh] Biến vệ tinh Sentinel-5P có 21,11% NULL, chưa qua xác minh "
        "bộ lọc QA bitmask và cờ coverage."
    ),
    "s5p_no2_mean": (
        "[V1-chưa xác minh] Code trích xuất GEE chưa áp dụng bộ lọc qa_value tường minh "
        "và chưa kiểm miền [-0.001, 0.05]."
    ),
    "s5p_no2_valid_px": (
        "[V1-chưa xác minh] Giá trị là count() ở scale 1000m (nhị phân {0, 1}), "
        "không phải số pixel S5P gốc trong ô."
    ),
    "s5p_no2_valid_flag": (
        "[V1-chưa xác minh] Chỉ phản ánh có/không có giá trị sau mask mặc định của GEE, "
        "chưa xác nhận đạt chuẩn QA sản phẩm."
    ),
    "modis_lst_day_c": (
        "[V1-chưa xác minh] Code trích xuất GEE chưa lọc bitmask QC_Day từ MODIS MOD11A1."
    ),
    "modis_lst_night_c": (
        "[V1-chưa xác minh] Code trích xuất GEE chưa lọc bitmask QC_Night từ MODIS MOD11A1."
    ),
    "modis_lst_day_valid_px": (
        "[V1-chưa xác minh] Giá trị là count() ở scale 1000m (nhị phân {0, 1}), "
        "chưa phản ánh lọc QC_Day."
    ),
    "modis_lst_night_valid_px": (
        "[V1-chưa xác minh] Giá trị là count() ở scale 1000m (nhị phân {0, 1}), "
        "chưa phản ánh lọc QC_Night."
    ),
    "modis_lst_day_valid_flag": (
        "[V1-chưa xác minh] Chỉ phản ánh có/không có giá trị sau mask mặc định, "
        "chưa xác nhận QC_Day."
    ),
    "modis_lst_night_valid_flag": (
        "[V1-chưa xác minh] Chỉ phản ánh có/không có giá trị sau mask mặc định, "
        "chưa xác nhận QC_Night."
    ),
}

# Bộ 30 feature mặc định hiện dùng cho chạy thực nghiệm (exploratory).
EXPLORATORY_BASE_FEATURES: tuple[str, ...] = (
    "built_up_frac",
    "tree_cover_frac",
    "dist_to_thames_km",
    "elevation_m",
    "population_density",
    "major_road_length_m",
    "dist_to_charing_cross_km",
    "month",
    "day_of_week",
    "is_weekend",
    "sin_day_of_year",
    "cos_day_of_year",
    "sin_day_of_week",
    "cos_day_of_week",
    "t2m_mean_c",
    "rh_mean_pct",
    "u10_vector_mean",
    "v10_vector_mean",
    "wind_speed_scalar_mean",
    "precip_sum_mm",
    "sp_mean_hpa",
    "cams_aod_550",
    "cams_pm25_bg",
    "s5p_no2_mean",
    "s5p_cloud_frac",
    "s5p_no2_valid_flag",
    "modis_lst_day_c",
    "modis_lst_night_c",
    "modis_lst_day_valid_flag",
    "modis_lst_night_valid_flag",
)


def _normalize_col_list(cols: Sequence[str] | str) -> list[str]:
    if isinstance(cols, str):
        return [cols]
    return list(cols)


def _require_columns(df: pd.DataFrame, cols: Sequence[str], table_name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise DataContractError(
            f"[{table_name}] Thiếu cột bắt buộc: {missing}. "
            f"Các cột hiện có: {list(df.columns)}"
        )


def validate_primary_key(
    df: pd.DataFrame,
    key_cols: Sequence[str] | str,
    table_name: str,
) -> None:
    """Kiểm tra khóa chính (hoặc unique key) không có NULL, không chuỗi rỗng và không trùng lặp."""
    cols = _normalize_col_list(key_cols)
    if not cols:
        raise DataContractError(f"[{table_name}] Danh sách cột khóa không được rỗng.")
    _require_columns(df, cols, table_name)

    for col in cols:
        s = df[col]
        null_mask = s.isna()
        if s.dtype == object or pd.api.types.is_string_dtype(s.dtype):
            str_s = s.dropna().astype(str).str.strip()
            empty_count = int((str_s == "").sum())
        else:
            empty_count = 0
        null_count = int(null_mask.sum()) + empty_count
        if null_count > 0:
            raise DataContractError(
                f"[{table_name}] Khóa {cols} có {null_count} giá trị NULL/rỗng tại cột '{col}'."
            )

    dup_mask = df.duplicated(subset=cols, keep=False)
    if dup_mask.any():
        dup_rows = int(dup_mask.sum())
        dup_keys_df = df.loc[df.duplicated(subset=cols, keep="first"), cols]
        n_dup_keys = len(dup_keys_df)
        samples = dup_keys_df.head(5).to_dict(orient="records")
        raise DataContractError(
            f"[{table_name}] Vi phạm tính duy nhất của khóa {cols}: "
            f"{dup_rows} dòng trùng trên {n_dup_keys} giá trị khóa. Mẫu vi phạm: {samples}"
        )


def validate_foreign_key(
    df: pd.DataFrame,
    fk_col: str,
    ref_values: Iterable[Any],
    table_name: str,
    ref_table_name: str,
    allow_null: bool = False,
) -> None:
    """Kiểm tra khóa ngoại trong `df[fk_col]` phải tồn tại trong `ref_values`."""
    _require_columns(df, [fk_col], table_name)
    s = df[fk_col]
    null_count = int(s.isna().sum())
    if null_count > 0 and not allow_null:
        raise DataContractError(
            f"[{table_name}] Cột khóa ngoại '{fk_col}' (tham chiếu {ref_table_name}) "
            f"có {null_count} giá trị NULL."
        )

    valid_set = set(ref_values)
    if not valid_set:
        raise DataContractError(
            f"[{table_name}] Tập khóa tham chiếu từ '{ref_table_name}' cho cột '{fk_col}' đang rỗng."
        )

    non_null = s.dropna()
    orphan_mask = ~non_null.isin(valid_set)
    if orphan_mask.any():
        n_orphan_rows = int(orphan_mask.sum())
        orphan_vals = sorted(set(non_null[orphan_mask].astype(str)))
        raise DataContractError(
            f"[{table_name}] Vi phạm khóa ngoại '{fk_col}' -> '{ref_table_name}': "
            f"{n_orphan_rows} dòng chứa {len(orphan_vals)} mã không tồn tại trong {ref_table_name}. "
            f"Mẫu vi phạm: {orphan_vals[:5]}"
        )


def validate_grid_ids(
    df: pd.DataFrame,
    grid_col: str = "grid_id",
    table_name: str = "dim_grid_1km",
) -> None:
    """Kiểm tra định dạng chuẩn `grid_{E}_{N}` của cột `grid_id`."""
    _require_columns(df, [grid_col], table_name)
    if df[grid_col].isna().any():
        raise DataContractError(
            f"[{table_name}] Cột '{grid_col}' có {int(df[grid_col].isna().sum())} giá trị NULL."
        )
    s = df[grid_col].astype(str)
    bad_mask = ~s.str.match(GRID_ID_REGEX)
    if bad_mask.any():
        bad_vals = s[bad_mask].unique()[:5].tolist()
        raise DataContractError(
            f"[{table_name}] Cột '{grid_col}' có {int(bad_mask.sum())} dòng sai định dạng "
            f"'grid_{{E}}_{{N}}'. Mẫu lỗi: {bad_vals}"
        )


def validate_utc_iso_dates(
    df: pd.DataFrame,
    date_col: str = "date",
    table_name: str = "table",
    require_iso_string: bool = False,
) -> pd.Series:
    """Kiểm tra cột ngày không NULL, parse được theo lịch UTC và chuẩn hóa về chuỗi ISO YYYY-MM-DD.

    Quy tắc:
    - Nếu require_iso_string=True: bắt buộc giá trị phải là chuỗi đúng định dạng 'YYYY-MM-DD'
      (từ chối timestamp có giờ hoặc timezone offset).
    - Nếu require_iso_string=False: cho phép đầu vào là timestamp/datetime có hoặc không có timezone;
      nếu có timezone hoặc giờ, giá trị bắt buộc phải được chuyển về ngày UTC thật (ví dụ:
      '2023-01-01T01:00:00+02:00' chuyển thành ngày UTC '2022-12-31').
    """
    _require_columns(df, [date_col], table_name)
    s = df[date_col]
    null_count = int(s.isna().sum())
    if null_count > 0:
        raise DataContractError(
            f"[{table_name}] Cột ngày '{date_col}' có {null_count} giá trị NULL."
        )

    if require_iso_string:
        str_s = s.astype(str).str.strip()
        bad_fmt = ~str_s.str.match(ISO_DATE_REGEX)
        if bad_fmt.any():
            samples = str_s[bad_fmt].unique()[:5].tolist()
            raise DataContractError(
                f"[{table_name}] Cột '{date_col}' yêu cầu định dạng ISO 'YYYY-MM-DD' "
                f"(từ chối timestamp có giờ/timezone). Mẫu lỗi: {samples}"
            )
        parsed = pd.to_datetime(str_s, format="%Y-%m-%d", errors="coerce")
        bad_parse = parsed.isna()
        if bad_parse.any():
            samples = str_s[bad_parse].unique()[:5].tolist()
            raise DataContractError(
                f"[{table_name}] Cột '{date_col}' có {int(bad_parse.sum())} ngày không hợp lệ. "
                f"Mẫu lỗi: {samples}"
            )
        return str_s

    # require_iso_string=False: Parse với nhận thức UTC đầy đủ (chuyển đổi offset về UTC)
    try:
        if pd.api.types.is_datetime64_any_dtype(s.dtype) and hasattr(s.dt, "tz") and s.dt.tz is not None:
            utc_dt = s.dt.tz_convert("UTC")
        else:
            utc_dt = pd.to_datetime(s, errors="coerce", utc=True)
    except Exception as exc:
        raise DataContractError(
            f"[{table_name}] Lỗi khi chuyển đổi cột '{date_col}' sang UTC: {exc}"
        ) from exc

    bad_parse = utc_dt.isna()
    if bad_parse.any():
        samples = s[bad_parse].astype(str).unique()[:5].tolist()
        raise DataContractError(
            f"[{table_name}] Cột '{date_col}' có {int(bad_parse.sum())} giá trị không thể parse "
            f"thành thời gian UTC hợp lệ. Mẫu lỗi: {samples}"
        )

    return utc_dt.dt.strftime("%Y-%m-%d")


def safe_merge(
    left: pd.DataFrame,
    right: pd.DataFrame,
    on: Sequence[str] | str,
    how: str = "left",
    validate: str = "many_to_one",
    preserve_left_rows: bool = True,
    left_name: str = "left",
    right_name: str = "right",
    expected_grain_cols: Sequence[str] | str | None = None,
) -> pd.DataFrame:
    """Thực hiện join có kiểm soát cardinality, khóa NULL và số dòng trước/sau."""
    on_cols = _normalize_col_list(on)
    _require_columns(left, on_cols, left_name)
    _require_columns(right, on_cols, right_name)

    for tbl_df, tbl_name in ((left, left_name), (right, right_name)):
        for c in on_cols:
            n_null = int(tbl_df[c].isna().sum())
            if n_null > 0:
                raise DataContractError(
                    f"[Join {left_name} -> {right_name}] Bảng '{tbl_name}' có {n_null} "
                    f"giá trị NULL tại cột khóa join '{c}'."
                )

    if validate in ("one_to_one", "many_to_one"):
        validate_primary_key(right, on_cols, right_name)
    if validate in ("one_to_one", "one_to_many"):
        validate_primary_key(left, on_cols, left_name)

    n_before = len(left)
    try:
        merged = pd.merge(left, right, on=on_cols, how=how, validate=validate)
    except pd.errors.MergeError as exc:
        raise DataContractError(
            f"[Join {left_name} -> {right_name}] Vi phạm cardinality '{validate}' "
            f"trên khóa {on_cols}: {exc}"
        ) from exc

    if preserve_left_rows and len(merged) != n_before:
        raise DataContractError(
            f"[Join {left_name} -> {right_name}] Số dòng thay đổi ngoài dự kiến sau {how} join "
            f"trên khóa {on_cols}: trước={n_before:,}, sau={len(merged):,}."
        )

    if expected_grain_cols is not None:
        validate_primary_key(
            merged,
            expected_grain_cols,
            f"{left_name}_joined_{right_name}",
        )

    return merged


DEFAULT_ALLOWED_DIFFER_COLS: tuple[str, ...] = (
    "fetched_at_utc",
    "pm25_obs",
    "valid_hours_count",
    "is_valid_day",
    "negative_hours_dropped_count",
    "qc_neg_dropped_flag",
    "chunk_file",
    "source_file",
    "file_name",
    "batch_id",
)


def dedupe_by_latest_fetch(
    df: pd.DataFrame,
    key_cols: Sequence[str] | str,
    ts_col: str = "fetched_at_utc",
    allowed_differ_cols: Sequence[str] | None = None,
    table_name: str = "openaq_chunks",
) -> tuple[pd.DataFrame, int]:
    """Khử trùng lặp có kiểm soát cho các chunk cào chồng lấp theo `fetched_at_utc`.

    Quy tắc an toàn dữ liệu:
    1. Kiểm tra khóa chính: không cho phép khóa chính có NULL.
    2. Kiểm tra xung đột metadata: Mọi cột KHÔNG nằm trong `key_cols` và KHÔNG nằm trong
       `allowed_differ_cols` (ví dụ: sensor_id, station_id, grid_id, site_type...) được xem
       là metadata nghiêm ngặt. Nếu hai bản ghi cùng khóa có giá trị metadata khác nhau,
       hàm ném `DataContractError` ngay lập tức thay vì âm thầm loại bỏ sensor_id hoặc metadata khác.
    3. Phân giải theo timestamp: Đối với các cột được phép cập nhật (như số đo pm25_obs,
       valid_hours_count...), nếu các dòng trùng khóa có cùng timestamp mới nhất nhưng giá trị
       xung đột (hoặc thiếu timestamp), ném `DataContractError`. Ngược lại, giữ bản ghi tại
       thời điểm `ts_col` mới nhất.
    """
    cols = _normalize_col_list(key_cols)
    _require_columns(df, cols, table_name)
    for c in cols:
        if df[c].isna().any():
            raise DataContractError(
                f"[{table_name}] Khóa {cols} có giá trị NULL tại cột '{c}'."
            )

    dup_mask = df.duplicated(subset=cols, keep=False)
    if not dup_mask.any():
        return df.sort_values(cols).reset_index(drop=True), 0

    allowed_set = set(DEFAULT_ALLOWED_DIFFER_COLS if allowed_differ_cols is None else allowed_differ_cols)
    allowed_set.add(ts_col)

    # 1. Kiểm tra xung đột metadata nghiêm ngặt
    strict_metadata_cols = [c for c in df.columns if c not in cols and c not in allowed_set]
    if strict_metadata_cols:
        dup_df = df[dup_mask]
        for col in strict_metadata_cols:
            nunique = dup_df.groupby(cols)[col].nunique(dropna=False)
            conflicts = nunique[nunique > 1]
            if not conflicts.empty:
                bad_key_samples = conflicts.index.tolist()[:3]
                details = []
                for k in bad_key_samples:
                    if isinstance(k, tuple):
                        cond = pd.Series(True, index=dup_df.index)
                        for c_name, c_val in zip(cols, k):
                            cond &= (dup_df[c_name] == c_val)
                    else:
                        cond = (dup_df[cols[0]] == k)
                    vals = dup_df.loc[cond, col].unique().tolist()
                    details.append(f"khóa {k}: các giá trị {vals}")
                raise DataContractError(
                    f"[{table_name}] Xung đột metadata giữa các bản ghi cùng khóa {cols}: "
                    f"cột '{col}' có giá trị khác nhau ({len(conflicts)} khóa vi phạm). "
                    f"Mẫu vi phạm: {details}. "
                    f"Chỉ các cột trong allowed_differ_cols={sorted(allowed_set)} mới được phép khác biệt."
                )

    # 2. Bỏ các bản sao hoàn toàn giống hệt nhau trên tất cả các cột
    work = df.drop_duplicates().copy()

    still_dup = work.duplicated(subset=cols, keep=False)
    if still_dup.any():
        if ts_col not in work.columns:
            samples = work.loc[still_dup, cols].head(5).to_dict(orient="records")
            raise DataContractError(
                f"[{table_name}] Có {int(still_dup.sum())} dòng trùng khóa {cols} với giá trị "
                f"xung đột nhưng thiếu cột timestamp '{ts_col}' để phân giải. Mẫu: {samples}"
            )
        ts_parsed = pd.to_datetime(work[ts_col], errors="coerce", utc=True)
        if ts_parsed[still_dup].isna().any():
            samples = work.loc[still_dup & ts_parsed.isna(), cols].head(5).to_dict(orient="records")
            raise DataContractError(
                f"[{table_name}] Các dòng trùng khóa {cols} có '{ts_col}' bị NULL/không hợp lệ. "
                f"Mẫu: {samples}"
            )
        work["_parsed_ts"] = ts_parsed
        max_ts = work.groupby(cols)["_parsed_ts"].transform("max")
        at_max = work[work["_parsed_ts"] == max_ts]
        # Kiểm tra tại thời điểm mới nhất còn nhiều dòng xung đột giá trị không
        conflict_at_max = at_max.duplicated(subset=cols, keep=False)
        if conflict_at_max.any():
            # Kiểm tra xem các dòng tại max_ts có khác nhau trên bất kỳ cột nào không
            at_max_dedup = at_max.drop(columns=["_parsed_ts"]).drop_duplicates()
            if at_max_dedup.duplicated(subset=cols, keep=False).any():
                samples = (
                    at_max_dedup.loc[at_max_dedup.duplicated(subset=cols, keep=False), cols]
                    .drop_duplicates()
                    .head(5)
                    .to_dict(orient="records")
                )
                raise DataContractError(
                    f"[{table_name}] Xung đột dữ liệu: nhiều bản ghi cùng khóa {cols} và cùng "
                    f"thời điểm '{ts_col}' mới nhất nhưng khác giá trị. Mẫu khóa vi phạm: {samples}"
                )
        work = (
            work.sort_values(cols + ["_parsed_ts"])
            .drop_duplicates(subset=cols, keep="last")
            .drop(columns=["_parsed_ts"])
        )

    n_dropped = len(df) - len(work)
    work = work.sort_values(cols).reset_index(drop=True)
    validate_primary_key(work, cols, table_name)
    return work, n_dropped


def validate_label_table(
    df: pd.DataFrame,
    min_valid_hours: int = MIN_VALID_HOURS_V1,
    table_name: str = "fact_ground_truth_daily",
) -> None:
    """Kiểm tra quy tắc chất lượng nhãn trạm-ngày (không làm thay đổi DataFrame đầu vào).

    Quy tắc Contract V1:
    - `valid_hours_count` không NULL, là số nguyên và nằm trong khoảng [0, 24].
    - `is_valid_day` chỉ nhận giá trị {0, 1}.
    - `is_valid_day == 1` khi và chỉ khi `valid_hours_count >= min_valid_hours` và `pm25_obs` không NULL.
    - Khi `is_valid_day == 0`, `pm25_obs` bắt buộc phải là NULL (NaN/NA).
    """
    if not (1 <= min_valid_hours <= MAX_HOURS_BOUND):
        raise DataContractError(
            f"[{table_name}] Ngưỡng min_valid_hours={min_valid_hours} nằm ngoài miền [1, 24]."
        )
    _require_columns(df, ["valid_hours_count", "is_valid_day", "pm25_obs"], table_name)

    vh_raw = df["valid_hours_count"]
    vh_num = pd.to_numeric(vh_raw, errors="coerce")
    if vh_num.isna().any():
        n_bad = int(vh_num.isna().sum())
        raise DataContractError(
            f"[{table_name}] Cột 'valid_hours_count' có {n_bad} giá trị NULL hoặc không phải số."
        )
    if ((vh_num % 1) != 0).any():
        raise DataContractError(
            f"[{table_name}] Cột 'valid_hours_count' chứa giá trị không nguyên."
        )
    out_of_range = (vh_num < MIN_HOURS_BOUND) | (vh_num > MAX_HOURS_BOUND)
    if out_of_range.any():
        bad_vals = vh_num[out_of_range].unique()[:5].tolist()
        raise DataContractError(
            f"[{table_name}] Cột 'valid_hours_count' có {int(out_of_range.sum())} dòng nằm ngoài "
            f"miền hợp lệ [{MIN_HOURS_BOUND}, {MAX_HOURS_BOUND}]. Mẫu lỗi: {bad_vals}"
        )

    iv_num = pd.to_numeric(df["is_valid_day"], errors="coerce")
    if iv_num.isna().any() or not iv_num.isin([0, 1]).all():
        bad_vals = df.loc[~iv_num.isin([0, 1]) | iv_num.isna(), "is_valid_day"].unique()[:5].tolist()
        raise DataContractError(
            f"[{table_name}] Cột 'is_valid_day' phải thuộc {{0, 1}} và không NULL. Mẫu lỗi: {bad_vals}"
        )

    pm_num = pd.to_numeric(df["pm25_obs"], errors="coerce")
    # Kiểm tra nếu có chuỗi không ép kiểu được sang float ở pm25_obs (khi không phải NA)
    non_null_unparseable = df["pm25_obs"].notna() & pm_num.isna()
    if non_null_unparseable.any():
        raise DataContractError(
            f"[{table_name}] Cột 'pm25_obs' có {int(non_null_unparseable.sum())} giá trị không phải số."
        )

    # 1. Dòng đánh dấu is_valid_day == 0 nhưng pm25_obs không NULL
    invalid_with_obs = (iv_num == 0) & pm_num.notna()
    if invalid_with_obs.any():
        raise DataContractError(
            f"[{table_name}] Có {int(invalid_with_obs.sum())} dòng is_valid_day=0 nhưng pm25_obs "
            f"không được gán NULL."
        )

    # 2. Dòng đánh dấu is_valid_day == 1 nhưng thiếu giờ (< min_valid_hours) hoặc pm25_obs NULL
    valid_but_bad = (iv_num == 1) & ((vh_num < min_valid_hours) | pm_num.isna())
    if valid_but_bad.any():
        raise DataContractError(
            f"[{table_name}] Có {int(valid_but_bad.sum())} dòng is_valid_day=1 nhưng "
            f"valid_hours_count < {min_valid_hours} hoặc pm25_obs là NULL."
        )


def normalize_and_validate_labels(
    df: pd.DataFrame,
    min_valid_hours: int = MIN_VALID_HOURS_V1,
    table_name: str = "ground_truth",
) -> pd.DataFrame:
    """Chuẩn hóa cờ `is_valid_day` và `pm25_obs` theo quy tắc Contract V1 rồi kiểm tra toàn vẹn."""
    if not (1 <= min_valid_hours <= MAX_HOURS_BOUND):
        raise DataContractError(
            f"[{table_name}] Ngưỡng min_valid_hours={min_valid_hours} nằm ngoài miền [1, 24]."
        )
    out = df.copy()
    if "pm25_obs" not in out.columns and "pm25" in out.columns:
        out["pm25_obs"] = out["pm25"]
    _require_columns(out, ["valid_hours_count", "pm25_obs"], table_name)

    vh_num = pd.to_numeric(out["valid_hours_count"], errors="coerce")
    if vh_num.isna().any():
        raise DataContractError(
            f"[{table_name}] Cột 'valid_hours_count' có {int(vh_num.isna().sum())} giá trị NULL/không hợp lệ."
        )
    if ((vh_num % 1) != 0).any():
        raise DataContractError(
            f"[{table_name}] Cột 'valid_hours_count' chứa giá trị không nguyên."
        )
    out_of_range = (vh_num < MIN_HOURS_BOUND) | (vh_num > MAX_HOURS_BOUND)
    if out_of_range.any():
        bad_vals = vh_num[out_of_range].unique()[:5].tolist()
        raise DataContractError(
            f"[{table_name}] Cột 'valid_hours_count' có {int(out_of_range.sum())} dòng nằm ngoài "
            f"miền [{MIN_HOURS_BOUND}, {MAX_HOURS_BOUND}]. Mẫu lỗi: {bad_vals}"
        )

    out["valid_hours_count"] = vh_num.astype("int8")
    pm_num = pd.to_numeric(out["pm25_obs"], errors="coerce")
    non_null_unparseable = out["pm25_obs"].notna() & pm_num.isna()
    if non_null_unparseable.any():
        raise DataContractError(
            f"[{table_name}] Cột 'pm25_obs' có {int(non_null_unparseable.sum())} giá trị không phải số."
        )

    out["is_valid_day"] = ((out["valid_hours_count"] >= min_valid_hours) & pm_num.notna()).astype("int8")
    out["pm25_obs"] = pm_num.where(out["is_valid_day"] == 1, np.nan).astype("float32")

    validate_label_table(out, min_valid_hours=min_valid_hours, table_name=table_name)
    return out


def validate_training_labels(
    df: pd.DataFrame,
    min_valid_hours: int = MIN_VALID_HOURS_V1,
    table_name: str = "mart_station_daily_training",
) -> None:
    """Đảm bảo tập huấn luyện chuẩn chỉ chứa các dòng hợp lệ (`is_valid_day == 1`, `pm25_obs` không NULL)."""
    _require_columns(df, ["pm25_obs"], table_name)
    if df.empty:
        raise DataContractError(f"[{table_name}] Tập dữ liệu huấn luyện đang rỗng.")

    null_obs = int(df["pm25_obs"].isna().sum())
    if null_obs > 0:
        raise DataContractError(
            f"[{table_name}] Tập huấn luyện chứa {null_obs} dòng có 'pm25_obs' là NULL."
        )

    if "is_valid_day" in df.columns:
        bad_flag = df["is_valid_day"] != 1
        if bad_flag.any():
            raise DataContractError(
                f"[{table_name}] Tập huấn luyện chứa {int(bad_flag.sum())} dòng có 'is_valid_day' != 1."
            )

    if "valid_hours_count" in df.columns:
        vh = pd.to_numeric(df["valid_hours_count"], errors="coerce")
        bad_vh = vh.isna() | (vh < min_valid_hours) | (vh > MAX_HOURS_BOUND)
        if bad_vh.any():
            raise DataContractError(
                f"[{table_name}] Tập huấn luyện chứa {int(bad_vh.sum())} dòng có "
                f"'valid_hours_count' ngoài khoảng [{min_valid_hours}, {MAX_HOURS_BOUND}]."
            )


def validate_grid_daily_spine(
    df: pd.DataFrame,
    expected_grid_ids: Iterable[str],
    start_date: str,
    end_date: str,
    table_name: str = "mart_grid_daily_features",
) -> None:
    """Kiểm tra bảng grid-day có đủ tích Descartes (expected_grid_ids x ngày UTC từ start_date đến end_date)."""
    validate_primary_key(df, ["grid_id", "date"], table_name)
    norm_dates = validate_utc_iso_dates(df, "date", table_name)

    exp_grids = {str(g) for g in expected_grid_ids}
    if not exp_grids:
        raise DataContractError(f"[{table_name}] Danh sách expected_grid_ids không được rỗng.")

    try:
        exp_date_index = pd.date_range(start_date, end_date, freq="D")
    except Exception as exc:
        raise DataContractError(
            f"[{table_name}] Khoảng ngày kỳ vọng ({start_date} -> {end_date}) không hợp lệ: {exc}"
        ) from exc
    if exp_date_index.empty:
        raise DataContractError(
            f"[{table_name}] Khoảng ngày ({start_date} -> {end_date}) rỗng."
        )
    exp_dates = set(exp_date_index.strftime("%Y-%m-%d"))

    act_grids = set(df["grid_id"].astype(str))
    act_dates = set(norm_dates)

    missing_grids = sorted(exp_grids - act_grids)
    extra_grids = sorted(act_grids - exp_grids)
    missing_dates = sorted(exp_dates - act_dates)
    extra_dates = sorted(act_dates - exp_dates)
    expected_len = len(exp_grids) * len(exp_dates)

    if missing_grids or extra_grids or missing_dates or extra_dates or len(df) != expected_len:
        raise DataContractError(
            f"[{table_name}] Spine (grid_id, date) không hoàn chỉnh: "
            f"số dòng thực tế={len(df):,} vs kỳ vọng={expected_len:,} "
            f"({len(exp_grids)} ô x {len(exp_dates)} ngày); "
            f"ô thiếu={len(missing_grids)} {missing_grids[:3]}, "
            f"ô thừa={len(extra_grids)} {extra_grids[:3]}, "
            f"ngày thiếu={len(missing_dates)} {missing_dates[:3]}, "
            f"ngày thừa={len(extra_dates)} {extra_dates[:3]}."
        )


def validate_satellite_flags(
    df: pd.DataFrame,
    table_name: str = "fact_satellite_daily",
) -> None:
    """Kiểm tra ngữ nghĩa cơ học hiện có của các cột `*_valid_px` và `*_valid_flag`.

    Lưu ý: Gate này chỉ xác nhận tính nhất quán giữa giá trị trung bình (NULL hay không NULL),
    `valid_px >= 0` và `valid_flag in {0, 1}` như code hiện tại tạo ra; KHÔNG xác nhận
    rằng dữ liệu đã qua lọc bitmask QA của sản phẩm vệ tinh.
    """
    specs = (
        ("s5p_no2_mean", "s5p_no2_valid_px", "s5p_no2_valid_flag"),
        ("modis_lst_day_c", "modis_lst_day_valid_px", "modis_lst_day_valid_flag"),
        ("modis_lst_night_c", "modis_lst_night_valid_px", "modis_lst_night_valid_flag"),
        ("modis_aod_055_mean", "modis_aod_valid_px", "modis_aod_valid_flag"),
    )
    for val_col, px_col, flag_col in specs:
        present = [c for c in (val_col, px_col, flag_col) if c in df.columns]
        if not present:
            continue

        if flag_col in df.columns:
            fl = pd.to_numeric(df[flag_col], errors="coerce")
            if fl.isna().any() or not fl.isin([0, 1]).all():
                raise DataContractError(
                    f"[{table_name}] Cột cờ '{flag_col}' phải thuộc {{0, 1}} và không NULL."
                )

        if px_col in df.columns:
            px = pd.to_numeric(df[px_col], errors="coerce")
            if px.isna().any() or ((px % 1) != 0).any() or (px < 0).any():
                raise DataContractError(
                    f"[{table_name}] Cột '{px_col}' phải là số nguyên không âm và không NULL."
                )

        if flag_col in df.columns and px_col in df.columns:
            mismatch_px = (df[flag_col] == 1) != (df[px_col] > 0)
            if mismatch_px.any():
                raise DataContractError(
                    f"[{table_name}] Mâu thuẫn giữa '{flag_col}' và '{px_col}' tại "
                    f"{int(mismatch_px.sum())} dòng (quy tắc: valid_flag == 1 <=> valid_px > 0)."
                )

        if val_col in df.columns and flag_col in df.columns:
            mismatch_val = df[val_col].notna() != (df[flag_col] == 1)
            if mismatch_val.any():
                raise DataContractError(
                    f"[{table_name}] Mâu thuẫn giữa '{val_col}' và '{flag_col}' tại "
                    f"{int(mismatch_val.sum())} dòng (quy tắc: {val_col} notna <=> {flag_col} == 1)."
                )


def validate_model_features(
    available_columns: Iterable[str],
    requested_features: Sequence[str],
    mode: str = "exploratory",
    table_name: str = "mart_station_daily_training",
) -> list[str]:
    """Kiểm tra danh sách feature huấn luyện theo allowlist, từ chối âm thầm lấy giao cột.

    - Mọi feature trong `requested_features` bắt buộc phải có mặt trong `available_columns`.
    - Ở chế độ `mode="certified"`: từ chối mọi feature thuộc `UNVERIFIED_V1_FEATURES` hoặc
      không nằm trong `CERTIFIED_V1_FEATURES`, báo rõ danh sách và lý do chưa xác minh.
    - Ở chế độ `mode="exploratory"`: cho phép chạy thực nghiệm khi đủ cột nhưng không
      được chứng nhận là model sản phẩm chuẩn.
    """
    if mode not in ("exploratory", "certified"):
        raise DataContractError(
            f"[{table_name}] Chế độ huấn luyện không hợp lệ: mode={mode!r} "
            "(chỉ chấp nhận 'exploratory' hoặc 'certified')."
        )
    feats = list(requested_features)
    if not feats:
        raise DataContractError(f"[{table_name}] Danh sách feature yêu cầu không được rỗng.")

    if len(feats) != len(set(feats)):
        dups = sorted({f for f in feats if feats.count(f) > 1})
        raise DataContractError(
            f"[{table_name}] Danh sách feature yêu cầu có cột bị lặp: {dups}"
        )

    avail_set = set(available_columns)
    missing = [f for f in feats if f not in avail_set]
    if missing:
        raise DataContractError(
            f"[{table_name}] Thiếu {len(missing)} feature bắt buộc trong dữ liệu: {missing}. "
            "Không được phép âm thầm lấy phần giao (column intersection)."
        )

    if mode == "certified":
        certified_set = set(CERTIFIED_V1_FEATURES)
        unverified_used: list[str] = []
        details: list[str] = []
        for f in feats:
            if f in UNVERIFIED_V1_FEATURES:
                unverified_used.append(f)
                details.append(f"  - {f}: {UNVERIFIED_V1_FEATURES[f]}")
            elif f not in certified_set:
                unverified_used.append(f)
                details.append(f"  - {f}: Chưa nằm trong allowlist CERTIFIED_V1_FEATURES.")
        if unverified_used:
            detail_str = "\n".join(details)
            raise DataContractError(
                f"[{table_name}] Không thể chạy chế độ 'certified' vì danh sách feature chứa "
                f"{len(unverified_used)} biến chưa được xác minh theo Data Contract V1: "
                f"{unverified_used}\nChi tiết:\n{detail_str}\n"
                "Hãy dùng --mode exploratory cho mục đích thử nghiệm hoặc chỉ chọn CERTIFIED_V1_FEATURES."
            )

    return feats


def select_and_validate_training_features(
    available_columns: Iterable[str] | pd.Index,
    mode: str = "exploratory",
    feature_set: str = "base",
    keep_coords: bool = False,
    coord_cols: Sequence[str] = ("bng_easting", "bng_northing"),
    table_name: str = "mart_station_daily_training",
) -> list[str]:
    """Chọn danh sách feature theo chế độ (exploratory vs certified) và kiểm tra nghiêm ngặt bằng allowlist.

    Hàm này độc lập hoàn toàn với các thư viện học máy (LightGBM, Scikit-learn),
    có thể chạy an toàn trong môi trường kiểm thử nhẹ.
    """
    requested = list(CERTIFIED_V1_FEATURES if feature_set == "certified_only" else EXPLORATORY_BASE_FEATURES)
    if keep_coords:
        requested += list(coord_cols)
    return validate_model_features(
        available_columns=available_columns,
        requested_features=requested,
        mode=mode,
        table_name=table_name,
    )


def resolve_mode_and_feature_set(
    mode: str = "exploratory",
    certified_flag: bool = False,
    feature_set: str | None = None,
) -> tuple[str, str]:
    """Xác định chế độ (run_mode) và tập feature (feature_set) hiệu lực từ tham số CLI.

    Quy tắc hợp đồng:
    1. run_mode = 'certified' nếu certified_flag=True hoặc mode == 'certified',
       ngược lại là 'exploratory'.
    2. Nếu feature_set được truyền tường minh (khác None), giữ nguyên giá trị đó:
       - 'base' -> 'base' (kể cả khi run_mode == 'certified', để quality gate
         từ chối feature chưa xác minh với lỗi rõ ràng).
       - 'certified_only' -> 'certified_only'.
    3. Nếu feature_set không được truyền (None):
       - run_mode == 'certified' -> tự động chọn 'certified_only'.
       - run_mode == 'exploratory' -> mặc định 'base'.
    """
    effective_mode = "certified" if (certified_flag or mode == "certified") else "exploratory"
    if feature_set is not None:
        return effective_mode, feature_set
    effective_feature_set = "certified_only" if effective_mode == "certified" else "base"
    return effective_mode, effective_feature_set


