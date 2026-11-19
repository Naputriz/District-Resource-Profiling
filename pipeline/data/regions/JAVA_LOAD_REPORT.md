# Java Regional Data Load Report (Staging DB)

- **Target Database:** `district_profiling_stage` (PostgreSQL 16 + PostGIS 3.4)
- **Target Redis DB:** `1` (`cache:compliance:scores:<province_code>`)
- **Live Database (`district_profiling`):** Untouched (enforced by live-DB guard)
- **Standards Engine:** SNI 03-1733-2004 via `backend/app/engine/standards_availability.py` and `pipeline/load_region.py`

---

## 1. DKI Jakarta (`31`) Unchanged Verification

| Metric | Before (Live / Baseline) | After Java Load (Staging) | Status |
|---|---|---|---|
| Kecamatan count | 44 | 44 | Identical |
| District compliance scorecards | 44 | 44 | Identical (`0` diffs across all 44 `health_score`, `education_score`, `livability_score`, `mobility_score`, `composite_livability_score`, `composite_note`, `metrics_payload`) |
| Active DKI facilities | 14,496 | 14,496 | Identical across every `facility_type` |
| `regulatory_standards` rows | 16 | 16 | Identical (`regulatory_standards_unchanged=True`) |

---

## 2. Per-Province Summary (Provinces 32–36)

| Province | Code | Loaded Kecamatan | COD-AB Raw (Valid) | WorldPop 2024 | COD-PS 2020 | Pop Diff (%) | Kab/Kota \|Diff\| > 15% | Active Facilities | Zero-Facility Kecamatan | Composite Score (Min / Median / Max) | GeoJSON Size |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Jawa Barat | `32` | 627 | 630 (627) | 50,352,580 | 49,565,166 | +1.59% | 1 | 18,983 | 93 | 0.00 / 1.47 / 84.86 | 2.03 MB |
| Jawa Tengah | `33` | 573 | 577 (573) | 38,175,724 | 34,738,244 | +9.90% | 7 | 12,543 | 92 | 0.00 / 2.08 / 75.42 | 1.97 MB |
| DI Yogyakarta | `34` | 78 | 78 (78) | 3,850,140 | 3,919,197 | -1.76% | 0 | 3,969 | 0 | 0.00 / 14.68 / 64.56 | 0.55 MB |
| Jawa Timur | `35` | 666 | 667 (666) | 42,527,064 | 39,955,941 | +6.43% | 1 | 13,423 | 108 | 0.00 / 2.08 / 71.77 | 2.37 MB |
| Banten | `36` | 155 | 155 (155) | 12,403,015 | 12,895,258 | -3.82% | 1 | 3,675 | 40 | 0.00 / 0.50 / 58.15 | 1.27 MB |

### Notes on COD-AB Counts & District Codes
- COD-AB `idn_admin3` includes non-district water/forest polygons with `adm3_pcode` suffixes `555`, `888`, or `999`:
  - `ID31` (DKI): 46 raw minus 2 (`ID3175555` Danau Sunter Dll, `ID3175888` Danau Sunter) = **44**.
  - `ID32` (Jawa Barat): 630 raw minus 3 (`ID3217888` Waduk, `ID3288888` Waduk Cirata, `ID3214888` Waduk Jatiluhur) = **627**.
  - `ID33` (Jawa Tengah): 577 raw minus 4 (`ID3399999` Hutan, `ID3312888` Waduk Gajahmungkur, `ID3388888` Waduk Kedungombo, `ID3322888` Waduk Rawapening) = **573**.
  - `ID34` (DI Yogyakarta): 78 raw = **78**.
  - `ID35` (Jawa Timur): 667 raw minus 1 (`ID3522888` Perairan) = **666**.
  - `ID36` (Banten): 155 raw = **155**.
- **District Code Mapping:** On DKI Jakarta (`31`), all 44 COD-AB `adm3_pcode` values end in `0` and map 44/44 to `PP.KK.CC` (e.g. `ID3171090` -> `31.71.09`). Outside DKI (`32`–`36`), split kecamatan end in non-zero digits (`1`, `2`, etc., e.g. `ID3273141` Antapani vs `ID3273142` Mandalajati), so dropping the 7th digit is not exact. Therefore, `kecamatan.cod_ab_pcode` stores the exact `IDPPKKDDD`, `kecamatan.bps_code` stores `PPKKDDD`, and `kecamatan.kemendagri_code` stores the unambiguous dotted identifier `PP.KK.DDD`.
- **UTM SRIDs (`utm_srid`):** Zero NULL `utm_srid` rows across all provinces (`32`: `[32748, 32749]`, `33`: `[32749]`, `34`: `[32749]`, `35`: `[32749, 32750]`, `36`: `[32748]`).

---

## 3. WorldPop 2024 vs COD-PS 2020 Comparison

### Explanation of Differences
1. **Reference Year & Census Revision Gap (2020 vs 2024):** HDX `cod-ps-idn` reflects 2020 population tables (largely derived from 2010-census-based projections prior to full *Sensus Penduduk 2020* / 2024 updates), whereas WorldPop `G2_CN_POP_R25A_100m` 2024 incorporates post-2020 population adjustments and 4 years of growth. This accounts for Jawa Tengah (+9.90%) and Jawa Timur (+6.43%) being systematically higher in WorldPop 2024.
2. **Dasymetric Constrained Allocation:** WorldPop constrained 100 m grids restrict population allocation to satellite-detected settled/built-up cells. Fast-growing peri-urban regencies/cities with older high COD-PS projections (Kab. Bekasi `-15.05%`, Kota Tangerang Selatan `-17.50%`) show lower totals under WorldPop's building-constrained spatial allocation, while rural regencies in Central Java and Lamongan show +15.4% to +18.3%.
3. **Polygon Clipping:** Zonal sums use `all_touched=False` against COD-AB admin3 polygons so adjacent kecamatan never double-count shared boundary pixels.

### Kabupaten/Kota with |Difference| > 15%

| Province | Code | Kabupaten / Kota | WorldPop 2024 | COD-PS 2020 | Diff (%) |
|---|---|---|---:|---:|---:|
| Jawa Barat (`32`) | `32.16` | Bekasi | 3,232,513 | 3,805,210 | -15.05% |
| Jawa Tengah (`33`) | `33.01` | Cilacap | 2,031,993 | 1,724,302 | +17.84% |
| Jawa Tengah (`33`) | `33.04` | Banjarnegara | 1,064,738 | 922,661 | +15.40% |
| Jawa Tengah (`33`) | `33.05` | Kebumen | 1,411,907 | 1,193,408 | +18.31% |
| Jawa Tengah (`33`) | `33.07` | Wonosobo | 914,677 | 788,834 | +15.95% |
| Jawa Tengah (`33`) | `33.14` | Sragen | 1,024,461 | 887,693 | +15.41% |
| Jawa Tengah (`33`) | `33.27` | Pemalang | 1,533,477 | 1,298,111 | +18.13% |
| Jawa Tengah (`33`) | `33.28` | Tegal | 1,676,735 | 1,435,147 | +16.83% |
| DI Yogyakarta (`34`) | — | *(none)* | — | — | — |
| Jawa Timur (`35`) | `35.24` | Lamongan | 1,403,813 | 1,202,310 | +16.76% |
| Banten (`36`) | `36.74` | Kota Tangerang Selatan | 1,411,131 | 1,710,438 | -17.50% |

---

## 4. Facility Counts per Pillar & Scoring Behavior

| Province | `lifeline_health` | `education` | `urban_livability` | `mobility_connectivity` | Total Active | Zero-Facility Kecamatan |
|---|---:|---:|---:|---:|---:|---:|
| Jawa Barat (`32`) | 1,912 | 8,465 | 5,832 | 2,774 | 18,983 | 93 |
| Jawa Tengah (`33`) | 1,901 | 6,260 | 2,201 | 2,181 | 12,543 | 92 |
| DI Yogyakarta (`34`) | 701 | 1,369 | 963 | 936 | 3,969 | 0 |
| Jawa Timur (`35`) | 1,871 | 6,186 | 2,826 | 2,540 | 13,423 | 108 |
| Banten (`36`) | 499 | 1,401 | 960 | 815 | 3,675 | 40 |

### Why `health_score` Is `NULL` and Median Scores Are Low Outside DKI
- Under the exact `pipeline/osm_extractor.py` classification rules, `puskesmas_kecamatan` requires `"kecamatan"` or `"kec."` in the OSM `name` tag. Outside DKI Jakarta, regional puskesmas are usually named `"Puskesmas <DistrictName>"` or `"UPTD Puskesmas ..."` and therefore classify as `puskesmas_kelurahan` (`32`: 414, `33`: 286, `34`: 157, `35`: 423, `36`: 67), leaving `puskesmas_kecamatan` at 1–8 records per province (`< 44`, marked `insufficient`).
- Likewise, `pos_damkar` (`amenity=fire_station`) has `< 44` OSM records in every province (`32`: 43, `33`: 21, `34`: 20, `35`: 30, `36`: 17 -> `insufficient`).
- Per `standards_availability.py` (`>= 2` scored+available types required per pillar), `lifeline_health` has only 1 available scored type (`puskesmas_kelurahan`), so `health_score` is `NULL` (`cakupan data rendah`) and the composite index is computed strictly from `education` (`taman_kanak_kanak`, `sekolah_dasar`, `sekolah_menengah_pertama`, `sekolah_menengah_atas` — all 4 `available` in every province).
- Rural OSM completeness for schools and clinics is markedly lower than in DKI Jakarta, producing 93 (Jabar), 92 (Jateng), 108 (Jatim), and 40 (Banten) kecamatan with 0 mapped OSM facilities (0 in DIY) and low province-wide median scores (0.50–14.68).

---

## 5. Spot Checks (Well-Known Urban Kecamatan)

| Kecamatan | City / Province | Code (`kemendagri_code` / `cod_ab_pcode`) | UTM SRID | Population (WorldPop 2024) | Active Facilities | Education / Composite Score |
|---|---|---|---:|---:|---:|---:|
| **Coblong** | Kota Bandung, Jawa Barat (`32`) | `32.73.230` / `ID3273230` | `32748` | 121,535 | 332 | 29.23 |
| **Gondokusuman** | Kota Yogyakarta, DI Yogyakarta (`34`) | `34.71.060` / `ID3471060` | `32749` | 48,275 | 150 | 54.54 |
| **Tegalsari** | Kota Surabaya, Jawa Timur (`35`) | `35.78.180` / `ID3578180` | `32749` | 82,285 | 137 | 33.83 |

---

## 6. OSM coverage gate

Under J1a2, two extra availability gates apply without changing the SNI scoring formula:
1. **Province-scaled threshold:** Facility types must have at least `N` classified records in the province (`N` = number of kecamatan in that province: `44` for DKI, `627` for Jabar, `573` for Jateng, `78` for DIY, `666` for Jatim, `155` for Banten). Under this rule, `puskesmas_kelurahan` becomes `insufficient` in Jabar (`414 < 627`), Jateng (`286 < 573`), Jatim (`423 < 666`), and Banten (`67 < 155`), and `sekolah_menengah_atas` becomes `insufficient` in Banten (`151 < 155`).
2. **Kecamatan coverage gate:** Any kecamatan with population $\ge 1,600$ (needing $\ge 1$ `sekolah_dasar` under SNI 03-1733-2004) and `0` mapped `sekolah_dasar` in OSM is marked `osm_coverage.status = "tidak_memadai"`; its count-based facilities get `data_availability = "insufficient_local"` (`compliance_pct = NULL`, `deficit = NULL`), and pillar/composite scores are `NULL` (`Data tidak memadai`) instead of `0`.

**Before gate (J1a baseline):** All 2,099 Java kecamatan were scored with fixed threshold `44` and no local SD gate — composite min/median/max were `0.00 / 1.47 / 84.86` (Jabar `32`), `0.00 / 2.08 / 75.42` (Jateng `33`), `0.00 / 14.68 / 64.56` (DIY `34`), `0.00 / 2.08 / 71.77` (Jatim `35`), and `0.00 / 0.50 / 58.15` (Banten `36`). DKI (`31`) remains identical across all 44 rows (`0` non-coverage diffs; `44/44` `memadai`).

### Per-Province Gate Summary (After Gate)

| Province | Code | Total Kecamatan | Kecamatan Gated (`tidak_memadai`) | Kecamatan Scored (`memadai`) | Scored Composite (Min / Median / Max) |
|---|---|---:|---:|---:|---:|
| DKI Jakarta | `31` | 44 | 0 | 44 | 5.41 / 49.20 / 65.39 |
| Jawa Barat | `32` | 627 | 306 | 321 | 0.23 / 6.07 / 84.86 |
| Jawa Tengah | `33` | 573 | 285 | 288 | 0.23 / 7.26 / 75.42 |
| DI Yogyakarta | `34` | 78 | 12 | 66 | 0.54 / 17.02 / 64.56 |
| Jawa Timur | `35` | 666 | 339 | 327 | 0.40 / 6.59 / 71.77 |
| Banten | `36` | 155 | 92 | 63 | 0.25 / 5.28 / 63.25 |

### Per-Type Zero Counts (Kecamatan with 0 Active OSM Records)

| Province | `taman_kanak_kanak` | `sekolah_dasar` | `sekolah_menengah_pertama` | `sekolah_menengah_atas` | `puskesmas_kelurahan` | `puskesmas_kecamatan` | `pos_damkar` |
|---|---:|---:|---:|---:|---:|---:|---:|
| DKI Jakarta (`31`, n=44) | 0 | 0 | 1 | 1 | 1 | 5 | 5 |
| Jawa Barat (`32`, n=627) | 439 | 306 | 360 | 387 | 395 | 619 | 586 |
| Jawa Tengah (`33`, n=573) | 410 | 285 | 326 | 348 | 412 | 570 | 554 |
| DI Yogyakarta (`34`, n=78) | 27 | 12 | 18 | 23 | 16 | 77 | 61 |
| Jawa Timur (`35`, n=666) | 481 | 339 | 393 | 411 | 434 | 665 | 638 |
| Banten (`36`, n=155) | 116 | 92 | 101 | 102 | 113 | 152 | 144 |

### Known limitation
Even kecamatan that pass the `sekolah_dasar >= 1` gate (status `memadai` / scored) may still have substantial under-counting in OpenStreetMap—for example, a kecamatan with 50 real primary schools where only 1 or 2 are mapped in OSM still passes the local gate. Because OSM completeness outside DKI Jakarta is uneven, compliance scores outside DKI are likely lower than actual on-the-ground facility availability and should be interpreted alongside the `osm_coverage` metadata rather than as definitive measures of physical shortage.
