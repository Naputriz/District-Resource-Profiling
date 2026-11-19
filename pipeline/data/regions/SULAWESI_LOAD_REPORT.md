# Sulawesi Regional Data Load Report (Staging DB)

- **Target Database:** `district_profiling_stage` (PostgreSQL 16 + PostGIS 3.4)
- **Target Redis DB:** `1` (`cache:compliance:scores:<province_code>`)
- **Live Database (`district_profiling`):** Untouched (enforced by live-DB guard)
- **Standards Engine:** SNI 03-1733-2004 via `backend/app/engine/standards_availability.py` and `pipeline/load_region.py`
- **OSM PBF Extracts:** `sulawesi-latest.osm.pbf` (`71`, `73`, `74`, `75`), `sulawesi-latest.osm.pbf` + `maluku-latest.osm.pbf` (`72`, deduplicated by `source_id`), and `sulawesi-latest.osm.pbf` + `kalimantan-latest.osm.pbf` (`76`, deduplicated by `source_id`)

---

## 1. Provinces `11`–`19`, `21` (Sumatra) & `31`–`36` (DKI + Java) Unchanged Verification

| Province | Code | Kab/Kota (Before / After) | Kecamatan (Before / After) | Active Facilities (Before / After) | Scorecard SHA-256 (Before == After) |
|---|---|---|---|---|---|
| Aceh | `11` | 23 / 23 | 289 / 289 | 2,197 / 2,197 | `86dbbf96307d96296ba78994b28886128b690a0f178780b5d98f5b6e15082cb1` |
| Sumatera Utara | `12` | 33 / 33 | 449 / 449 | 2,160 / 2,160 | `3f834d77f2ee6de89375b0065ff7e59da7e106acb251f2c20186d532620f707f` |
| Sumatera Barat | `13` | 19 / 19 | 179 / 179 | 1,550 / 1,550 | `d65adf24ad631615cc48a76b6ebcadd9c882359c78f1d7e24aa54097a58b44e3` |
| Riau | `14` | 12 / 12 | 169 / 169 | 2,177 / 2,177 | `d1324db982e848ab453e125f1190a27e433e353acd96127f139e8e3b4c0fb1b6` |
| Jambi | `15` | 11 / 11 | 141 / 141 | 1,348 / 1,348 | `074d92617dccbe8ceea189ed8edd17b61a4f337dea07ccd245b29b7dc4ad2c3b` |
| Sumatera Selatan | `16` | 17 / 17 | 236 / 236 | 1,128 / 1,128 | `8461993ffd093b672174f6561239d65918fca82869b7cb450c058ffbfcd1a339` |
| Bengkulu | `17` | 10 / 10 | 128 / 128 | 815 / 815 | `3038d2520d08a394339c4c5334f4b26207996fe7a2e81fdbce64a9c90abb143f` |
| Lampung | `18` | 15 / 15 | 228 / 228 | 1,245 / 1,245 | `7eb6bf0d3e9ed8b1133c0b58eb02dbe9dc4bc1bb1a4738f272f7bebb0b8b60c8` |
| Kep. Bangka Belitung | `19` | 7 / 7 | 47 / 47 | 383 / 383 | `ba8b9c00e244d872cdde6cd48436b99c657a792aa89f500d925ae2729d7f2e6e` |
| Kepulauan Riau | `21` | 7 / 7 | 70 / 70 | 1,506 / 1,506 | `6cdf6a2de86ea6518311cbecc602354a14503c47d6ac0860246028f6958372dc` |
| DKI Jakarta | `31` | 6 / 6 | 44 / 44 | 14,496 / 14,496 | `c86866e01856f9b32351188ea12dbea08b3e17c73c37a18b40ed6a113cdf50e7` |
| Jawa Barat | `32` | 27 / 27 | 627 / 627 | 18,983 / 18,983 | `5e5ca0e8c0da8c7fae9565375a6ce113b3082673af0c302e63071fdb5e7f00d5` |
| Jawa Tengah | `33` | 35 / 35 | 573 / 573 | 12,543 / 12,543 | `c34f7fd1e0dccfb84dfd800056c47808fc969be338a177c0bb8fe7f1c8fae93c` |
| DI Yogyakarta | `34` | 5 / 5 | 78 / 78 | 3,969 / 3,969 | `acd66632fa3b3bcb57bb95ea0835454cafc13cf47dc7440a9829466b290d64f6` |
| Jawa Timur | `35` | 38 / 38 | 666 / 666 | 13,423 / 13,423 | `bed807757009329af0e330d71481d5d8da83553c1b81bb0b1fae6a0546d2f678` |
| Banten | `36` | 8 / 8 | 155 / 155 | 3,675 / 3,675 | `1752fd8b73d9632db8ffeeece943c60fc4e7bda643aedf52adfd66e3b69ea6d1` |

- **Combined `31`–`36` Scorecard Checksum (2,143 rows):**
  - Before: `3fd1aba416efe212dae7636f85198f0463e072696760a5a7cdf9dd133e179713`
  - After:  `3fd1aba416efe212dae7636f85198f0463e072696760a5a7cdf9dd133e179713` (0 diffs)
- **Combined `11`–`19`, `21` Scorecard Checksum (1,936 rows):**
  - Before: `bec1e30413161ac5fad0a0108b43cb4b7de634351c8fdc4cf7ff14e5977b97d0`
  - After:  `bec1e30413161ac5fad0a0108b43cb4b7de634351c8fdc4cf7ff14e5977b97d0` (0 diffs)
- **`regulatory_standards` rows:** `16` before == `16` after.

---

## 2. Per-Province Summary (Provinces 71–76)

| Province | Code | Loaded Kecamatan | COD-AB Raw (Valid) | WorldPop 2024 | COD-PS 2020 | Pop Diff (%) | Kab/Kota \|Diff\| > 15% | Active Facilities | Zero-Facility Kecamatan | Composite Score (Min / Median / Max of Scored) | GeoJSON Size |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Sulawesi Utara | `71` | 171 | 172 (171) | 2,735,176 | 2,512,942 | +8.84% | 2 | 2,393 | 36 | 0.00 / 40.33 / 100.00 | 1.21 MB |
| Sulawesi Tengah | `72` | 175 | 176 (175) | 3,074,487 | 3,081,720 | -0.23% | 1 | 612 | 90 | `NULL` (0 scored types) | 1.93 MB |
| Sulawesi Selatan | `73` | 307 | 309 (307) | 9,484,018 | 8,888,762 | +6.70% | 4 | 6,907 | 18 | 0.00 / 21.27 / 100.00 | 2.59 MB |
| Sulawesi Tenggara | `74` | 222 | 222 (222) | 2,732,281 | 2,703,466 | +1.07% | 3 | 1,423 | 92 | `NULL` (1 scored type `< 2`) | 1.32 MB |
| Gorontalo | `75` | 77 | 78 (77) | 1,222,007 | 1,186,261 | +3.01% | 1 | 211 | 33 | `NULL` (0 scored types) | 0.59 MB |
| Sulawesi Barat | `76` | 69 | 69 (69) | 1,482,459 | 1,378,110 | +7.57% | 0 | 238 | 37 | `NULL` (0 scored types) | 0.59 MB |
| **Total Sulawesi** | — | **1,021** | **1,026 (1,021)** | **20,730,428** | **19,751,261** | **+4.96%** | **11** | **11,784** | **306** | — | — |

### Notes on COD-AB Counts, Geofabrik Coverage, WorldPop Edge Case & UTM SRIDs
- **Non-district exclusions (`555`, `888`, `999`):**
  - `ID71` (Sulawesi Utara): 172 minus 1 (`ID7188888` Danau) = **171**.
  - `ID72` (Sulawesi Tengah): 176 minus 1 (`ID7204888` Danau) = **175**.
  - `ID73` (Sulawesi Selatan): 309 minus 2 (`ID7325888` Danau, `ID7313888` Danau Tempe) = **307**.
  - `ID74` (Sulawesi Tenggara): 222 = **222**.
  - `ID75` (Gorontalo): 78 minus 1 (`ID7502888` Danau Limboto) = **77**.
  - `ID76` (Sulawesi Barat): 69 = **69**.
- **Geofabrik `.poly` boundary split:** Polygon containment checks against `sulawesi.poly` confirmed that Sangihe and Talaud (`71`), Selayar (`73`), Wakatobi (`74`), and Gorontalo (`75`) are 100% inside `sulawesi.poly`. However, Bokan Kepulauan (`ID7211070`, Banggai Laut, `72`) lies 94.11% in `sulawesi.poly` and 5.89% in `maluku.poly`, while Balabalakang (`ID7604023`, Mamuju, `76`) lies 100% inside `kalimantan.poly` (`0%` in `sulawesi.poly`). Accordingly, `72` loads from `sulawesi-latest.osm.pbf` + `maluku-latest.osm.pbf` and `76` loads from `sulawesi-latest.osm.pbf` + `kalimantan-latest.osm.pbf` (deduplicated by `source_id`).
- **WorldPop 2024 constrained zero-pixel island kecamatan (`76.04.023`):** `Balabalakang` (Kab. Mamuju, Sulawesi Barat, area `21.88 km²`) is an outer archipelago in the Makassar Strait with 0 non-nodata pixels in the WorldPop Global2 constrained 100 m 2024 raster (even with `all_touched=True`), yielding `population = 0`. `load_region.py` skips scoring when `population <= 0` and caches all 69 kecamatan in Redis via `LEFT JOIN` so `Balabalakang` returns `score_status = "Data tidak memadai"` on the API (`scored_districts=68`, `memadai=10`, `tidak_memadai=58`, `unscored=1` in `76`).
- **UTM SRIDs (`utm_srid`) & Geodesic Area Check:** Zero NULL `utm_srid` rows across all 1,021 kecamatan and all 11,784 active facilities. Every PostGIS `utm_srid` matches `calculate_utm_srid()` (`326xx` north of the equator, `327xx` south of the equator, zones 50–52):
  - `71`: `{32651: 152, 32652: 19}` (Talaud Islands east of 126°E use 52N `32652`; max UTM vs `ST_Area(geography)` diff = `0.1374%` at Tabukan Selatan Tengah `71.03.061`)
  - `72`: `{32751: 105, 32750: 35, 32651: 34, 32650: 1}` (crosses both equator and zone 50/51 boundary; max diff = `0.1958%` at Ampibabo `72.08.030`)
  - `73`: `{32750: 182, 32751: 125}` (max diff = `0.1952%` at Walenrang Barat `73.17.092`)
  - `74`: `{32751: 222}` (max diff = `0.0799%` at Wawonii Barat `74.12.070`)
  - `75`: `{32651: 77}` (max diff = `0.0800%` at Limboto `75.02.070`)
  - `76`: `{32750: 69}` (max diff = `0.1279%` at Dapurang `76.05.011`)
  - Maximum UTM vs geodesic area difference across all 1,021 kecamatan is `0.1958%` (`< 1%`).

---

## 3. WorldPop 2024 vs COD-PS 2020 Comparison

### Kabupaten/Kota with |Difference| > 15%

| Province | Code | Kabupaten / Kota | WorldPop 2024 | COD-PS 2020 | Diff (%) |
|---|---|---|---:|---:|---:|
| Sulawesi Utara (`71`) | `71.05` | Minahasa Selatan | 248,034 | 210,400 | +17.89% |
| Sulawesi Utara (`71`) | `71.11` | Bolaang Mongondow Timur | 92,050 | 72,597 | +26.80% |
| Sulawesi Tengah (`72`) | `72.03` | Morowali | 167,142 | 122,786 | +36.12% |
| Sulawesi Selatan (`73`) | `73.04` | Jeneponto | 421,207 | 365,503 | +15.24% |
| Sulawesi Selatan (`73`) | `73.08` | Maros | 412,268 | 354,521 | +16.29% |
| Sulawesi Selatan (`73`) | `73.18` | Tana Toraja | 292,264 | 237,913 | +22.84% |
| Sulawesi Selatan (`73`) | `73.26` | Toraja Utara | 273,039 | 235,456 | +15.96% |
| Sulawesi Tenggara (`74`) | `74.01` | Buton | 119,116 | 102,112 | +16.65% |
| Sulawesi Tenggara (`74`) | `74.14` | Buton Tengah | 117,782 | 92,978 | +26.68% |
| Sulawesi Tenggara (`74`) | `74.15` | Buton Selatan | 99,475 | 80,002 | +24.34% |
| Gorontalo (`75`) | `75.05` | Gorontalo Utara | 129,454 | 112,140 | +15.44% |
| Sulawesi Barat (`76`) | — | *(none)* | — | — | — |

Differences reflect the 2020-to-2024 census/growth gap (including industrial expansion in Morowali `+36.12%`, Bolaang Mongondow Timur `+26.80%`, and post-SP2020 revisions in Buton Tengah `+26.68%` and Tana Toraja `+22.84%`).

---

## 4. Facility Counts per Pillar & Scoring Behavior

| Province | `lifeline_health` | `education` | `urban_livability` | `mobility_connectivity` | Total Active | Zero-Facility Kecamatan |
|---|---:|---:|---:|---:|---:|---:|
| Sulawesi Utara (`71`) | 288 | 1,114 | 154 | 837 | 2,393 | 36 |
| Sulawesi Tengah (`72`) | 123 | 344 | 88 | 57 | 612 | 90 |
| Sulawesi Selatan (`73`) | 901 | 3,375 | 1,718 | 913 | 6,907 | 18 |
| Sulawesi Tenggara (`74`) | 223 | 917 | 200 | 83 | 1,423 | 92 |
| Gorontalo (`75`) | 53 | 56 | 36 | 66 | 211 | 33 |
| Sulawesi Barat (`76`) | 31 | 113 | 70 | 24 | 238 | 37 |

### Why Only Two Sulawesi Provinces Yield Numeric Composite Scores
- Under the J1a2 province-scaled availability gate, each scored facility type must have at least `N` classified OSM records in the province (`N` = number of kecamatan in that province), and a pillar must have `>= 2` available scored types to compute a pillar score.
- Across all 6 Sulawesi provinces, `lifeline_health` has 0 facility types meeting `>= N`, so `health_score` is `NULL` (`cakupan data rendah`) everywhere.
- In `education`:
  - **Sulawesi Utara (`71`, N=171):** `sekolah_dasar` (530) and `sekolah_menengah_pertama` (181) are `available` (2 types) -> composite computed for 92 `memadai` kecamatan.
  - **Sulawesi Selatan (`73`, N=307):** `sekolah_dasar` (1,094), `sekolah_menengah_pertama` (398), and `sekolah_menengah_atas` (472) are `available` (3 types) -> composite computed for 168 `memadai` kecamatan.
  - **Sulawesi Tenggara (`74`, N=222):** only 1 scored type (`sekolah_dasar`: 299) meets `>= N`.
  - **Sulawesi Tengah (`72`), Gorontalo (`75`), Sulawesi Barat (`76`):** 0 scored types meet `>= N`.
  - Consequently, in provinces `72`, `74`, `75`, and `76`, `education_score` and `composite_livability_score` remain `NULL` (`Data tidak memadai` / `cakupan data rendah`) even for kecamatan passing the local `sekolah_dasar >= 1` gate.

---

## 5. Spot Checks (Well-Known Urban Kecamatan)

| Kecamatan | City / Province | Code (`kemendagri_code` / `cod_ab_pcode`) | UTM SRID | UTM vs Geog Area Diff | Population (WorldPop 2024) | Active Facilities | `osm_coverage` (`mapped_sd / req_sd`) | Composite Score |
|---|---|---|---:|---:|---:|---:|---|---:|
| **Ujung Pandang** | Kota Makassar, Sulawesi Selatan (`73`) | `73.71.050` / `ID7371050` | `32750` | `0.0969%` | 38,025 | 123 | `memadai` (`8 / 24`) | `65.28` (`education`) |
| **Wenang** | Kota Manado, Sulawesi Utara (`71`) | `71.71.030` / `ID7171030` | `32651` | `0.0239%` | 34,715 | 109 | `memadai` (`22 / 22`) | `100.00` (`education`) |
| **Palu Barat** | Kota Palu, Sulawesi Tengah (`72`) | `72.71.010` / `ID7271010` | `32750` | `0.1697%` | 38,713 | 17 | `memadai` (`2 / 25`) | `NULL` (0 province types `>= 175`) |

---

## 6. OSM Coverage Gate Summary

| Province | Code | Total Kecamatan | Local Gate `tidak_memadai` (SD=0) | Local Gate `memadai` (SD>=1) | Province Scored Types `>= N` | Scored Composite (Min / Median / Max) |
|---|---|---:|---:|---:|---:|---:|
| Sulawesi Utara | `71` | 171 | 79 | 92 | 2 (`SD`: 530, `SMP`: 181) | 0.00 / 40.33 / 100.00 |
| Sulawesi Tengah | `72` | 175 | 137 | 38 | 0 | `NULL` (`< 2` types) |
| Sulawesi Selatan | `73` | 307 | 139 | 168 | 3 (`SD`: 1,094, `SMP`: 398, `SMA`: 472) | 0.00 / 21.27 / 100.00 |
| Sulawesi Tenggara | `74` | 222 | 148 | 74 | 1 (`SD`: 299) | `NULL` (`< 2` types) |
| Gorontalo | `75` | 77 | 71 | 6 | 0 | `NULL` (`< 2` types) |
| Sulawesi Barat | `76` | 69 | 58 *(+1 zero-pop)* | 10 | 0 | `NULL` (`< 2` types) |

### Per-Type Zero Counts (Kecamatan with 0 Active OSM Records)

| Province | `taman_kanak_kanak` | `sekolah_dasar` | `sekolah_menengah_pertama` | `sekolah_menengah_atas` | `puskesmas_kelurahan` | `puskesmas_kecamatan` | `pos_damkar` |
|---|---:|---:|---:|---:|---:|---:|---:|
| Sulawesi Utara (`71`, n=171) | 144 | 80 | 96 | 103 | 112 | 171 | 169 |
| Sulawesi Tengah (`72`, n=175) | 157 | 137 | 148 | 147 | 160 | 175 | 172 |
| Sulawesi Selatan (`73`, n=307) | 225 | 140 | 178 | 72 | 174 | 305 | 290 |
| Sulawesi Tenggara (`74`, n=222) | 185 | 150 | 172 | 177 | 185 | 219 | 220 |
| Gorontalo (`75`, n=77) | 73 | 71 | 75 | 73 | 58 | 77 | 74 |
| Sulawesi Barat (`76`, n=69) | 66 | 59 | 56 | 58 | 59 | 69 | 69 |

### Known Limitation
As in Java (`32`–`36`) and Sumatra (`11`–`19`, `21`), rural and regional OSM mapping across Sulawesi is sparse: 632 of 1,021 kecamatan have `0` mapped `sekolah_dasar` (`tidak_memadai`), 1 outer island kecamatan (`Balabalakang`, `76.04.023`) has 0 WorldPop constrained pixels, and 4 of 6 provinces have `< 2` facility types meeting the province-wide `>= N` threshold. Even kecamatan passing the local `sekolah_dasar >= 1` gate (`memadai`) often have substantial OSM under-counting relative to real facilities and must be interpreted alongside `osm_coverage`.
