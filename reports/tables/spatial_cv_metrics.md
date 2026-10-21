# Danh gia mo hinh khong gian PM2.5 London (grouped spatial CV)

Nhom fold: grid_id + gop o ke nhau; 36 nhom.

## 1. So sanh tong the
| Model                              |   RMSE |   MAE |   Bias |   Overall R2 |   Spatial R2 (tho) |   Temporal R2 |   Anomaly R2 |   Anomaly RMSE |   Anomaly corr |
|:-----------------------------------|-------:|------:|-------:|-------------:|-------------------:|--------------:|-------------:|---------------:|---------------:|
| LightGBM thuan (bo toa do)         |  3.912 | 2.68  | -0.105 |        0.607 |              0.428 |         0.894 |       -0.093 |          2.977 |          0.028 |
| LightGBM lai (phan du vs nen ngay) |  3.792 | 2.472 | -0.611 |        0.631 |              0.357 |         0.98  |       -0.085 |          2.967 |          0.022 |
| Baseline 3: IDW                    |  3.454 | 2.29  | -0.133 |        0.694 |              0.533 |         0.997 |        0.024 |          2.814 |          0.189 |
| Baseline 2: Daily Train Mean       |  3.507 | 2.346 | -0.024 |        0.684 |              0.512 |         1     |        0     |          2.848 |        nan     |
| Baseline 1: CAMS PM2.5 nen         |  5.207 | 3.509 | -0.817 |        0.304 |              0.136 |         0.443 |       -0.029 |          2.888 |         -0.023 |

## 2. Theo site_type
| site_type        |   So mau |   So tram |   RMSE LightGBM thuan |   Bias LightGBM thuan |   RMSE LightGBM lai |   Bias LightGBM lai |   RMSE Baseline 3 |   Bias Baseline 3 |   RMSE Baseline 2 |   Bias Baseline 2 |   RMSE Baseline 1 |   Bias Baseline 1 |
|:-----------------|---------:|----------:|----------------------:|----------------------:|--------------------:|--------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|------------------:|
| Roadside         |     9550 |        23 |                  3.48 |                  0.33 |                3.27 |               -0.13 |              3.1  |              0.18 |              3.04 |              0.19 |              4.67 |             -0.62 |
| Urban Background |     4436 |        10 |                  2.94 |                  0.89 |                2.43 |                0.44 |              2.57 |              0.86 |              2.83 |              1.06 |              4.27 |              0.38 |
| Unknown          |     3863 |        50 |                  5.7  |                 -1.93 |                5.89 |               -2.55 |              5.04 |             -1.58 |              5.07 |             -1.62 |              7.24 |             -2.61 |
| Suburban         |     1240 |         3 |                  3.12 |                  1.19 |                2.43 |                0.62 |              2.28 |              0.72 |              2.98 |              1.65 |              4.44 |              0.79 |
| Kerbside         |      839 |         5 |                  4.5  |                 -3.39 |                4.93 |               -4.14 |              4.26 |             -3.2  |              4.12 |             -3.18 |              5.68 |             -3.52 |
| Industrial       |      423 |         1 |                  2.77 |                 -0.91 |                2.44 |               -1.26 |              2.1  |             -0.91 |              2.1  |             -0.22 |              4.44 |             -0.87 |

## Top 15 feature (mo hinh lai)
| Feature                  |   Importance |
|:-------------------------|-------------:|
| built_up_frac            |        398   |
| dist_to_thames_km        |        347.8 |
| elevation_m              |        336.4 |
| dist_to_charing_cross_km |        334.8 |
| tree_cover_frac          |        317   |
| population_density       |        316.4 |
| net_daily_mean           |        288.2 |
| net_nearest_km           |        232.2 |
| net_idw                  |        217.4 |
| net_n_stations           |        189.6 |
| sin_day_of_year          |        125.2 |
| cos_day_of_year          |        110.4 |
| cams_pm25_bg             |         99.4 |
| wind_speed_scalar_mean   |         92.8 |
| rh_mean_pct              |         92   |
