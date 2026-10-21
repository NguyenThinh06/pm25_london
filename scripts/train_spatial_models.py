#!/usr/bin/env python3
"""Train & evaluate spatial models for London PM2.5 estimation (grouped spatial CV).

Thay doi so voi ban truoc (theo phan tich ket qua CV):
  1. Fold theo NHOM TRAM: dung cot `site_group` neu mart co, neu khong thi `grid_id`.
     --merge-adjacent gop them cac o ke nhau (tam o <= 1.5 km) vao cung nhom.
  2. Bo toa do (bng_easting/northing) khoi feature: voi ~40-90 tram, toa do gan nhu
     la ma dinh danh tram nen cay hoc thuoc tram. (--keep-coords de so sanh.)
  3. Sieu tham so chong hoc thuoc: min_child_samples lon, colsample thap, num_leaves nho.
     Luu y: `subsample` cua LightGBM chi co tac dung khi subsample_freq > 0
     (ban cu khong dat nen bagging khong bat).
  4. Chi so ky nang khong gian THAT (anomaly): voi moi (fold, ngay), tru trung binh
     cac tram test cung ngay khoi ca nhan lan du doan, roi tinh R2/RMSE/tuong quan.
     Baseline "Daily Train Mean" cho gia tri hang 0 theo dinh nghia.
     "Spatial R2 (tho)" van duoc in, nhung bi lan lich quan trac khac nhau cua cac tram.
  5. Mo hinh LAI: hoc phan du log1p(obs) - log1p(nen ngay) voi nen ngay = trung binh
     cac tram KHAC NHOM cung ngay; them feature IDW / so tram / khoang cach tram gan nhat.
     Voi hang train, cac feature mang luon tinh bo chinh tram va ca nhom cua no
     (leave-group-out) de khop cach dung luc test, khong ro ri.

Bai toan ung voi mo hinh lai: (A) ve lai ban do khi co so do cung ngay cua mang tram.
Neu muon uoc luong khong dung so do cung ngay (B), chi dung mo hinh "thuan".

Chay tu thu muc goc:
    python scripts/train_spatial_models.py
    python scripts/train_spatial_models.py --merge-adjacent --min-station-days 60
    python scripts/train_spatial_models.py --predict-grid
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

try:
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    from sklearn.model_selection import GroupKFold
except ImportError:
    mean_absolute_error = None
    mean_squared_error = None
    r2_score = None
    GroupKFold = None

try:
    from scripts.quality_gates import (
        CERTIFIED_V1_FEATURES,
        EXPLORATORY_BASE_FEATURES,
        MIN_VALID_HOURS_V1,
        UNVERIFIED_V1_FEATURES,
        resolve_mode_and_feature_set,
        select_and_validate_training_features,
        validate_grid_daily_spine,
        validate_model_features,
        validate_primary_key,
        validate_satellite_flags,
        validate_training_labels,
        validate_utc_iso_dates,
    )
except ImportError:
    from quality_gates import (
        CERTIFIED_V1_FEATURES,
        EXPLORATORY_BASE_FEATURES,
        MIN_VALID_HOURS_V1,
        UNVERIFIED_V1_FEATURES,
        resolve_mode_and_feature_set,
        select_and_validate_training_features,
        validate_grid_daily_spine,
        validate_model_features,
        validate_primary_key,
        validate_satellite_flags,
        validate_training_labels,
        validate_utc_iso_dates,
    )

ROOT = Path(__file__).resolve().parents[1]
TRAIN_FILE = ROOT / "data/processed/mart_station_daily_training.parquet"
GRID_FILE = ROOT / "data/processed/mart_grid_daily_features.parquet"
REPORTS_DIR = ROOT / "reports"
TABLES_DIR = REPORTS_DIR / "tables"
PRED_DIR = REPORTS_DIR / "predictions"
MODELS_DIR = ROOT / "models"

TARGET_COL = "pm25_obs"
COORD_COLS = ["bng_easting", "bng_northing"]

# Feature moi truong + tinh (KHONG co toa do, KHONG co site_type / station_key)
# Luu y: BASE_FEATURES chua mot so bien [V1-chua xac minh] chi duoc phep dung o mode="exploratory".
BASE_FEATURES = list(EXPLORATORY_BASE_FEATURES)
CERTIFIED_FEATURES = list(CERTIFIED_V1_FEATURES)
# Feature mang tram (chi cho mo hinh lai)
NET_FEATURES = ["net_daily_mean", "net_idw", "net_n_stations", "net_nearest_km"]


# --------------------------------------------------------------------------
# Nhom tram -> fold
# --------------------------------------------------------------------------
def build_groups(df: pd.DataFrame, merge_adjacent: bool) -> tuple[np.ndarray, str]:
    if "site_group" in df.columns and df["site_group"].notna().all():
        labels = df["site_group"].astype(str)
        src = "site_group"
    else:
        labels = df["grid_id"].astype(str)
        src = "grid_id"
    if merge_adjacent:
        cen = (
            df.assign(_g=labels)
            .groupby("_g")[COORD_COLS].mean()
        )
        names = list(cen.index)
        xy = cen.to_numpy(float)
        parent = list(range(len(names)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                if np.hypot(*(xy[i] - xy[j])) <= 1500.0:
                    parent[find(i)] = find(j)
        remap = {n: f"G{find(i)}" for i, n in enumerate(names)}
        labels = labels.map(remap)
        src += " + gop o ke nhau"
    return labels.to_numpy(), src


# --------------------------------------------------------------------------
# Feature mang tram + baseline (IDW, trung binh ngay)
# --------------------------------------------------------------------------
def network_features(rows: pd.DataFrame, ref: pd.DataFrame, exclude_same_group: bool,
                     eps_m: float = 100.0, power: float = 2.0) -> pd.DataFrame:
    """Cho moi dong `rows`, tinh tu cac tram `ref` CUNG NGAY.

    rows: can cot date, bng_easting, bng_northing, group
    ref : them cot pm25_obs
    exclude_same_group=True  -> bo cac tram cung nhom voi dong dang xet (dung cho train).
    """
    ref = ref[ref[TARGET_COL].notna()]
    n = len(rows)
    out = {k: np.full(n, np.nan, dtype=np.float32) for k in NET_FEATURES}
    ref_by_date = {d: g for d, g in ref.groupby("date")}
    pos_by_date = rows.groupby("date").indices
    re_ = rows["bng_easting"].to_numpy(float)
    rn_ = rows["bng_northing"].to_numpy(float)
    rg_ = rows["group"].to_numpy()

    for d, pos in pos_by_date.items():
        r = ref_by_date.get(d)
        if r is None:
            continue
        ye = r["bng_easting"].to_numpy(float)
        yn = r["bng_northing"].to_numpy(float)
        yv = r[TARGET_COL].to_numpy(float)
        yg = r["group"].to_numpy()
        dist = np.hypot(re_[pos, None] - ye[None, :], rn_[pos, None] - yn[None, :])
        valid = (rg_[pos, None] != yg[None, :]) if exclude_same_group else np.ones(dist.shape, bool)
        cnt = valid.sum(1)
        ok = cnt > 0
        if not ok.any():
            continue
        w = np.where(valid, 1.0 / np.power(dist + eps_m, power), 0.0)
        wsum = w.sum(1)
        idx = pos[ok]
        out["net_idw"][idx] = ((w * yv).sum(1)[ok] / wsum[ok]).astype(np.float32)
        out["net_daily_mean"][idx] = ((valid * yv).sum(1)[ok] / cnt[ok]).astype(np.float32)
        out["net_n_stations"][idx] = cnt[ok].astype(np.float32)
        out["net_nearest_km"][idx] = (np.where(valid, dist, np.inf).min(1)[ok] / 1000.0).astype(np.float32)
    return pd.DataFrame(out)


# --------------------------------------------------------------------------
# Chi so
# --------------------------------------------------------------------------
def _require_sklearn() -> None:
    if mean_squared_error is None:
        raise ImportError(
            "scikit-learn is required to compute evaluation metrics or run GroupKFold. "
            "Please install scikit-learn."
        )


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    _require_sklearn()
    mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
    if not mask.any():
        return {"rmse": np.nan, "mae": np.nan, "bias": np.nan, "r2": np.nan}
    yt, yp = y_true[mask], y_pred[mask]
    return {
        "rmse": float(np.sqrt(mean_squared_error(yt, yp))),
        "mae": float(mean_absolute_error(yt, yp)),
        "bias": float(np.mean(yp - yt)),
        "r2": float(r2_score(yt, yp)),
    }


def compute_spatial_and_temporal_r2(df: pd.DataFrame, pred_col: str) -> tuple[float, float]:
    """Spatial R2 (tho, theo trung binh tram) va Temporal R2 (theo ngay)."""
    _require_sklearn()
    st = df.groupby("station_key").agg(y_true=(TARGET_COL, "mean"), y_pred=(pred_col, "mean")).dropna()
    sp = float(r2_score(st["y_true"], st["y_pred"])) if len(st) > 1 else np.nan
    dy = df.groupby("date").agg(y_true=(TARGET_COL, "mean"), y_pred=(pred_col, "mean")).dropna()
    tp = float(r2_score(dy["y_true"], dy["y_pred"])) if len(dy) > 1 else np.nan
    return sp, tp


def anomaly_metrics(df: pd.DataFrame, pred_col: str) -> dict[str, float]:
    """Ky nang khong gian that: tru trung binh cac tram test cung (fold, ngay)."""
    _require_sklearn()
    d = df[["fold", "date", TARGET_COL, pred_col]].dropna().copy()
    key = ["fold", "date"]
    d = d[d.groupby(key)[TARGET_COL].transform("size") >= 2]
    if len(d) < 3:
        return {"a_r2": np.nan, "a_rmse": np.nan, "a_corr": np.nan}
    ya = d[TARGET_COL] - d.groupby(key)[TARGET_COL].transform("mean")
    pa = d[pred_col] - d.groupby(key)[pred_col].transform("mean")
    corr = float(np.corrcoef(ya, pa)[0, 1]) if pa.std() > 1e-9 else np.nan
    return {
        "a_r2": float(r2_score(ya, pa)),
        "a_rmse": float(np.sqrt(np.mean((ya - pa) ** 2))),
        "a_corr": corr,
    }


def to_md(df: pd.DataFrame, **kw) -> str:
    try:
        return df.to_markdown(**kw)
    except ImportError:
        return "```\n" + df.to_string() + "\n```"


# --------------------------------------------------------------------------
# Mo hinh
# --------------------------------------------------------------------------
def make_lgb(seed: int, args):
    if lgb is None:
        raise ImportError(
            "lightgbm is required for training models. Please install lightgbm."
        )
    return lgb.LGBMRegressor(
        n_estimators=args.n_estimators,
        learning_rate=0.03,
        num_leaves=15,
        min_child_samples=args.min_child_samples,
        subsample=0.8,
        subsample_freq=1,          # bat buoc de subsample co tac dung
        colsample_bytree=0.6,
        reg_lambda=5.0,
        random_state=seed,
        n_jobs=-1,
        verbosity=-1,
    )


def hybrid_matrix(base: pd.DataFrame, net: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    return pd.concat([base[feats].reset_index(drop=True), net.reset_index(drop=True)], axis=1)


def hybrid_base_log(net: pd.DataFrame, fallback_mean: float) -> np.ndarray:
    return np.log1p(net["net_daily_mean"].fillna(fallback_mean).to_numpy(float))


def hybrid_predict(model, X: pd.DataFrame, base_log: np.ndarray) -> np.ndarray:
    return np.clip(np.expm1(base_log + model.predict(X)), 0, None).astype(np.float32)


def build_cli_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--min-station-days", type=int, default=1)
    ap.add_argument("--n-splits", type=int, default=5)
    ap.add_argument("--merge-adjacent", action="store_true", help="gop cac o ke nhau vao cung nhom/fold")
    ap.add_argument("--keep-coords", action="store_true", help="giu toa do trong feature (de so sanh)")
    ap.add_argument("--min-child-samples", type=int, default=200)
    ap.add_argument("--n-estimators", type=int, default=300)
    ap.add_argument("--predict-grid", action="store_true")
    ap.add_argument(
        "--mode",
        choices=["exploratory", "certified"],
        default="exploratory",
        help="che do kiem tra hop dong feature: 'certified' tu choi bien [V1-chua xac minh]",
    )
    ap.add_argument(
        "--certified",
        action="store_true",
        help="viet tat cho --mode certified",
    )
    ap.add_argument(
        "--feature-set",
        choices=["base", "certified_only"],
        default=None,
        help=(
            "tap feature dau vao: 'base' (30 bien exploratory) hoac 'certified_only' "
            "(18 bien [V1] da xac minh). Mac dinh: 'base' o exploratory, 'certified_only' o certified."
        ),
    )
    return ap


def main() -> None:
    ap = build_cli_parser()
    args = ap.parse_args()
    run_mode, effective_feature_set = resolve_mode_and_feature_set(
        mode=args.mode,
        certified_flag=args.certified,
        feature_set=args.feature_set,
    )

    t0 = time.time()
    if not TRAIN_FILE.exists():
        sys.exit(f"Khong tim thay {TRAIN_FILE}. Hay chay scripts/build_feature_marts.py truoc.")

    df = pd.read_parquet(TRAIN_FILE)
    for c in COORD_COLS + ["station_key", "grid_id", "date", TARGET_COL]:
        if c not in df.columns:
            sys.exit(f"Mart huan luyen thieu cot bat buoc: {c}")

    # Kiem tra khoa, ngay UTC, nhan huan luyen va co ve tinh theo Data Contract V1
    df["date"] = validate_utc_iso_dates(df, date_col="date", table_name="mart_station_daily_training")
    validate_primary_key(df, ["station_key", "date"], "mart_station_daily_training")
    validate_training_labels(
        df,
        min_valid_hours=MIN_VALID_HOURS_V1,
        table_name="mart_station_daily_training",
    )
    validate_satellite_flags(df, table_name="mart_station_daily_training")
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d").dt.normalize()
    print(f"Doc du lieu huan luyen: {len(df):,} dong tu {TRAIN_FILE.name} (mode={run_mode})")

    if args.min_station_days > 1:
        cnt = df.groupby("station_key")["date"].nunique()
        keep = set(cnt[cnt >= args.min_station_days].index)
        n0 = len(df)
        df = df[df["station_key"].isin(keep)].reset_index(drop=True)
        print(f"Loc tram >= {args.min_station_days} ngay: {n0:,} -> {len(df):,} dong ({len(keep)} tram).")

    # Kiem tra allowlist feature nghiem ngat (khong am tham lay giao BASE_FEATURES voi df.columns)
    feats = select_and_validate_training_features(
        available_columns=df.columns,
        mode=run_mode,
        feature_set=effective_feature_set,
        keep_coords=args.keep_coords,
        table_name="mart_station_daily_training",
    )
    unverified_in_feats = [f for f in feats if f in UNVERIFIED_V1_FEATURES]
    print(
        f"Dung {len(feats)} feature goc (mode={run_mode}, feature_set={effective_feature_set})"
        + (" | CO toa do" if args.keep_coords else " | da bo toa do")
    )
    if unverified_in_feats:
        print(
            f"  [CANH BAO CONTRACT V1] Dang chay che do '{run_mode}' voi {len(unverified_in_feats)} "
            f"feature [V1-chua xac minh]: {unverified_in_feats}. "
            "Ket qua KHONG duoc chung nhan la mo hinh san pham chuan."
        )

    grp, grp_src = build_groups(df, args.merge_adjacent)
    df["group"] = grp
    print(f"Nhom fold: {grp_src} | {df['station_key'].nunique()} tram -> {df['group'].nunique()} nhom")

    print(f"\n=== GROUPED SPATIAL {args.n_splits}-FOLD CV ===")
    oof = df.copy()
    for c in ["pred_lgb_pure", "pred_hybrid", "pred_idw", "pred_daily_mean"]:
        oof[c] = np.nan
    oof["fold"] = -1
    imp_pure = np.zeros(len(feats))
    hyb_feats = feats + NET_FEATURES
    imp_hyb = np.zeros(len(hyb_feats))

    gkf = GroupKFold(n_splits=args.n_splits)
    for k, (tr, te) in enumerate(gkf.split(df, groups=df["group"].to_numpy()), 1):
        train = df.iloc[tr].reset_index(drop=True)
        test = df.iloc[te].reset_index(drop=True)
        train_mean = float(train[TARGET_COL].mean())
        oof.loc[te, "fold"] = k
        print(f"\n--- Fold {k}/{args.n_splits} --- train {len(train):,} mau "
              f"({train['station_key'].nunique()} tram) | test {len(test):,} mau "
              f"({test['station_key'].nunique()} tram)")

        net_tr = network_features(train, train, exclude_same_group=True)
        net_te = network_features(test, train, exclude_same_group=False)

        oof.loc[te, "pred_daily_mean"] = net_te["net_daily_mean"].fillna(train_mean).to_numpy()
        oof.loc[te, "pred_idw"] = net_te["net_idw"].fillna(train_mean).to_numpy()

        m_pure = make_lgb(42 + k, args).fit(train[feats], train[TARGET_COL])
        oof.loc[te, "pred_lgb_pure"] = m_pure.predict(test[feats])
        imp_pure += m_pure.feature_importances_ / args.n_splits

        Xtr = hybrid_matrix(train, net_tr, feats)
        ytr = np.log1p(train[TARGET_COL].clip(lower=0).to_numpy(float)) - hybrid_base_log(net_tr, train_mean)
        m_h = make_lgb(142 + k, args).fit(Xtr, ytr)
        Xte = hybrid_matrix(test, net_te, feats)
        oof.loc[te, "pred_hybrid"] = hybrid_predict(m_h, Xte, hybrid_base_log(net_te, train_mean))
        imp_hyb += m_h.feature_importances_ / args.n_splits

        y = test[TARGET_COL].to_numpy()
        r = {n: compute_metrics(y, oof.loc[te, c].to_numpy())["rmse"]
             for n, c in [("thuan", "pred_lgb_pure"), ("lai", "pred_hybrid"),
                          ("IDW", "pred_idw"), ("nen ngay", "pred_daily_mean")]}
        print("  RMSE: " + " | ".join(f"{n} {v:.2f}" for n, v in r.items()))

    # ---------------------------------------------------------------- tong ket
    print("\n" + "=" * 78)
    print(" SO SANH HIEU NANG (OUT-OF-FOLD)")
    print("=" * 78)
    models = {
        "LightGBM thuan (bo toa do)": "pred_lgb_pure",
        "LightGBM lai (phan du vs nen ngay)": "pred_hybrid",
        "Baseline 3: IDW": "pred_idw",
        "Baseline 2: Daily Train Mean": "pred_daily_mean",
        "Baseline 1: CAMS PM2.5 nen": "cams_pm25_bg",
    }
    y_true = oof[TARGET_COL].to_numpy()
    rows = []
    for name, col in models.items():
        if col not in oof.columns:
            continue
        m = compute_metrics(y_true, oof[col].to_numpy())
        sp, tp = compute_spatial_and_temporal_r2(oof, col)
        a = anomaly_metrics(oof, col)
        rows.append({
            "Model": name, "RMSE": m["rmse"], "MAE": m["mae"], "Bias": m["bias"],
            "Overall R2": m["r2"], "Spatial R2 (tho)": sp, "Temporal R2": tp,
            "Anomaly R2": a["a_r2"], "Anomaly RMSE": a["a_rmse"], "Anomaly corr": a["a_corr"],
        })
    res = pd.DataFrame(rows).set_index("Model")
    print(res.round(3).to_string())
    print("\nAnomaly = ky nang khong gian sau khi tru trung binh cac tram test cung ngay; "
          "Daily Train Mean ~ 0 theo dinh nghia, moi gia tri > 0 la ky nang khong gian that.")

    # phan tang theo site_type va is_monitor
    def breakdown(col: str) -> pd.DataFrame:
        out = []
        for key, g in oof.groupby(col):
            row = {col: key, "So mau": len(g), "So tram": g["station_key"].nunique()}
            for name, c in models.items():
                if c in g.columns:
                    mm = compute_metrics(g[TARGET_COL].to_numpy(), g[c].to_numpy())
                    row[f"RMSE {name.split(':')[0].split('(')[0].strip()}"] = mm["rmse"]
                    row[f"Bias {name.split(':')[0].split('(')[0].strip()}"] = mm["bias"]
            out.append(row)
        return pd.DataFrame(out).sort_values("So mau", ascending=False).set_index(col)

    site_df = breakdown("site_type") if "site_type" in oof.columns else pd.DataFrame()
    mon_df = breakdown("is_monitor") if "is_monitor" in oof.columns else pd.DataFrame()
    for title, t in [("PHAN TANG THEO site_type", site_df), ("PHAN TANG THEO is_monitor", mon_df)]:
        if not t.empty:
            print("\n" + "-" * 78 + f"\n {title}\n" + "-" * 78)
            print(t.round(2).to_string())

    fi_h = pd.DataFrame({"Feature": hyb_feats, "Importance": imp_hyb}).sort_values("Importance", ascending=False)
    fi_p = pd.DataFrame({"Feature": feats, "Importance": imp_pure}).sort_values("Importance", ascending=False)
    print("\n" + "-" * 78 + "\n TOP 15 FEATURE - MO HINH LAI\n" + "-" * 78)
    for i, r in enumerate(fi_h.head(15).itertuples(index=False), 1):
        print(f"  {i:2d}. {r.Feature:<26} {r.Importance:.1f}")

    # ---------------------------------------------------------------- luu
    for d in (TABLES_DIR, PRED_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    res.to_csv(TABLES_DIR / "spatial_cv_metrics.csv")
    if not site_df.empty:
        site_df.to_csv(TABLES_DIR / "site_type_breakdown.csv")
    if not mon_df.empty:
        mon_df.to_csv(TABLES_DIR / "is_monitor_breakdown.csv")
    fi_h.to_csv(TABLES_DIR / "feature_importance_hybrid.csv", index=False)
    fi_p.to_csv(TABLES_DIR / "feature_importance_pure.csv", index=False)
    md = ("# Danh gia mo hinh khong gian PM2.5 London (grouped spatial CV)\n\n"
          f"Nhom fold: {grp_src}; {df['group'].nunique()} nhom.\n\n"
          f"## 1. So sanh tong the\n{to_md(res.round(3))}\n\n")
    if not site_df.empty:
        md += f"## 2. Theo site_type\n{to_md(site_df.round(2))}\n\n"
    if not mon_df.empty:
        md += f"## 3. Theo is_monitor\n{to_md(mon_df.round(2))}\n\n"
    md += f"## Top 15 feature (mo hinh lai)\n{to_md(fi_h.head(15), index=False)}\n"
    (TABLES_DIR / "spatial_cv_metrics.md").write_text(md, encoding="utf-8")

    keep_cols = [c for c in ["station_key", "station_id", "grid_id", "group", "date", "site_type",
                             TARGET_COL, "pred_lgb_pure", "pred_hybrid", "pred_idw",
                             "pred_daily_mean", "cams_pm25_bg", "fold"] if c in oof.columns]
    oof[keep_cols].to_parquet(PRED_DIR / "oof_predictions.parquet", index=False)
    print(f"\nDa ghi bao cao vao {TABLES_DIR} va OOF vao {PRED_DIR / 'oof_predictions.parquet'}")

    # ------------------------------------------------------------ mo hinh cuoi
    print(f"\nHuan luyen mo hinh cuoi tren toan bo {len(df):,} mau...")
    all_mean = float(df[TARGET_COL].mean())
    final_pure = make_lgb(42, args).fit(df[feats], df[TARGET_COL])
    net_all = network_features(df, df, exclude_same_group=True)
    y_all = np.log1p(df[TARGET_COL].clip(lower=0).to_numpy(float)) - hybrid_base_log(net_all, all_mean)
    final_hyb = make_lgb(142, args).fit(hybrid_matrix(df, net_all, feats), y_all)
    final_pure.booster_.save_model(str(MODELS_DIR / "lightgbm_pm25_pure.txt"))
    final_hyb.booster_.save_model(str(MODELS_DIR / "lightgbm_pm25_hybrid.txt"))
    (MODELS_DIR / "model_config.json").write_text(json.dumps({
        "contract_version": "V1",
        "mode": run_mode,
        "certified": (run_mode == "certified" and not unverified_in_feats),
        "unverified_features_used": unverified_in_feats,
        "pure_features": feats, "hybrid_features": hyb_feats, "net_features": NET_FEATURES,
        "hybrid_target": "log1p(pm25_obs) - log1p(net_daily_mean)", "fallback_mean": all_mean,
        "group_source": grp_src,
    }, indent=2), encoding="utf-8")
    print(f" Da luu mo hinh vao {MODELS_DIR}")

    # ------------------------------------------------------------ du doan luoi
    if args.predict_grid:
        if not GRID_FILE.exists():
            print(f"Khong co {GRID_FILE}, bo qua --predict-grid.")
        else:
            t1 = time.time()
            grid = pd.read_parquet(GRID_FILE)
            grid["date"] = validate_utc_iso_dates(grid, date_col="date", table_name="mart_grid_daily_features")
            validate_grid_daily_spine(
                grid,
                expected_grid_ids=grid["grid_id"].unique(),
                start_date=grid["date"].min(),
                end_date=grid["date"].max(),
                table_name="mart_grid_daily_features",
            )
            validate_satellite_flags(grid, table_name="mart_grid_daily_features")
            validate_model_features(
                available_columns=grid.columns,
                requested_features=feats,
                mode=run_mode,
                table_name="mart_grid_daily_features",
            )
            grid["date"] = pd.to_datetime(grid["date"], format="%Y-%m-%d").dt.normalize()
            grid["group"] = "grid_" + grid["grid_id"].astype(str)
            print(f"\nDu doan luoi: {len(grid):,} dong ({grid['grid_id'].nunique()} o)")

            cells = grid.drop_duplicates("grid_id")[["grid_id", *COORD_COLS]]
            st = df[COORD_COLS].drop_duplicates().to_numpy(float)
            dmin = np.hypot(cells["bng_easting"].to_numpy()[:, None] - st[:, 0],
                            cells["bng_northing"].to_numpy()[:, None] - st[:, 1]).min(1) / 1000.0
            grid["nearest_station_distance_km"] = grid["grid_id"].map(
                dict(zip(cells["grid_id"], dmin.astype(np.float32)))).astype(np.float32)

            net_g = network_features(grid, df, exclude_same_group=False)
            grid["pm25_estimate_pure"] = final_pure.predict(grid[feats]).astype(np.float32)
            grid["pm25_estimate"] = hybrid_predict(
                final_hyb, hybrid_matrix(grid, net_g, feats), hybrid_base_log(net_g, all_mean))
            cols = [c for c in ["grid_id", "date", "pm25_estimate", "pm25_estimate_pure",
                                "nearest_station_distance_km", "in_boundary", "centroid_lon",
                                "centroid_lat", "bng_easting", "bng_northing"] if c in grid.columns]
            grid[cols].to_parquet(PRED_DIR / "prediction_grid_daily.parquet", index=False)
            print(f" Xong ({time.time() - t1:.0f}s) -> {PRED_DIR / 'prediction_grid_daily.parquet'}")
            print(" pm25_estimate = mo hinh LAI (can so do cung ngay cua mang tram); "
                  "pm25_estimate_pure = mo hinh thuan.")

    print(f"\nHoan tat sau {time.time() - t0:.0f} giay.")


if __name__ == "__main__":
    main()
