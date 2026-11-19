# Sumatra Regional Data Load Report (Staging DB)

- **Target Database:** `district_profiling_stage` (PostgreSQL 16 + PostGIS 3.4)
- **Target Redis DB:** `1` (`cache:compliance:scores:<province_code>`)
- **Live Database (`district_profiling`):** Untouched (enforced by live-DB guard)
- **Standards Engine:** SNI 03-1733-2004 via `backend/app/engine/standards_availability.py` and `pipeline/load_region.py`
- **OSM PBF Extracts:** `sumatra-latest.osm.pbf` (`11`–`18`), `kalimantan-latest.osm.pbf` (`19`), and both `sumatra-latest.osm.pbf` + `kalimantan-latest.osm.pbf` (`21`, deduplicated by `source_id`)

---

## 1. Provinces `31`–`36` (DKI + Java) Unchanged Verification

| Province | Code | Kab/Kota (Before / After) | Kecamatan (Before / After) | Active Facilities (Before / After) | Scorecard SHA-256 (Before == After) |
|---|---|---|---|---|---|
| DKI Jakarta | `31` | 6 / 6 | 44 / 44 | 14,496 / 14,496 | `12a64d9ac40ae5252eec754fbf6a548eab86a059f7fc84dc7ad70d382ae49661` |
| Jawa Barat | `32` | 27 / 27 | 627 / 627 | 18,983 / 18,983 | `1dab47984e9945de54f714fdda7a788e7d8c035daa21431628db30f95348fc37` |
| Jawa Tengah | `33` | 35 / 35 | 573 / 573 | 12,543 / 12,543 | `5e0ce34bf863badd06e9046031e35ddb4487318b3af3894eebd0944b94c8de32` |
| DI Yogyakarta | `34` | 5 / 5 | 78 / 78 | 3,969 / 3,969 | `daa9459d4b914d8faa663f833eb0bd35ea3bf332fc99388706be25350e8f0f00` |
| Jawa Timur | `35` | 38 / 38 | 666 / 666 | 13,423 / 13,423 | `f58a47e5fb5a172db236ababdff3a9893f7e23b3342f0a9c1e066a60790952a0` |
| Banten | `36` | 8 / 8 | 155 / 155 | 3,675 / 3,675 | `68b4e2aa08d30ba9efb80f86c4ef510f1d6f039dcbe4274614c8cb7d4ea8a1ec` |

- **Combined `31`–`36` Scorecard Checksum (2,143 rows):**
  - Before: `c055c8f76cfb8d540e58a4d6bba2e902c234b91470cf56a778e24f6b50ec9d2b`
  - After:  `c055c8f76cfb8d540e58a4d6bba2e902c234b91470cf56a778e24f6b50ec9d2b` (0 diffs)

---

## 2. Per-Province Summary (Provinces 11–19, 21)

| Province | Code | Loaded Kecamatan | COD-AB Raw (Valid) | WorldPop 2024 | COD-PS 2020 | Pop Diff (%) | Kab/Kota \|Diff\| > 15% | Active Facilities | Zero-Facility Kecamatan | Composite Score (Min / Median / Max of Scored) | GeoJSON Size |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Aceh | `11` | 289 | 290 (289) | 5,509,970 | 5,388,093 | +2.26% | 2 | 2,197 | 51 | `NULL` (1 scored type `< 2`) | 1.92 MB |
| Sumatera Utara | `12` | 449 | 450 (449) | 15,454,553 | 14,798,404 | +4.43% | 3 | 2,160 | 219 | `NULL` (0 scored types) | 2.46 MB |
| Sumatera Barat | `13` | 179 | 181 (179) | 5,789,033 | 5,545,706 | +4.39% | 0 | 1,550 | 19 | 1.00 / 13.34 / 97.06 | 1.31 MB |
| Riau | `14` | 169 | 169 (169) | 6,677,512 | 6,951,217 | -3.94% | 2 | 2,177 | 32 | `NULL` (1 scored type `< 2`) | 0.99 MB |
| Jambi | `15` | 141 | 143 (141) | 3,699,555 | 3,604,186 | +2.65% | 1 | 1,348 | 12 | 0.71 / 21.88 / 100.00 | 0.62 MB |
| Sumatera Selatan | `16` | 236 | 237 (236) | 8,857,044 | 8,600,765 | +2.98% | 2 | 1,128 | 100 | `NULL` (0 scored types) | 1.42 MB |
| Bengkulu | `17` | 128 | 131 (128) | 2,086,875 | 1,994,349 | +4.64% | 0 | 815 | 30 | `NULL` (1 scored type `< 2`) | 0.68 MB |
| Lampung | `18` | 228 | 237 (228) | 9,323,118 | 8,534,849 | +9.24% | 2 | 1,245 | 72 | `NULL` (0 scored types) | 1.46 MB |
| Kep. Bangka Belitung | `19` | 47 | 47 (47) | 1,516,986 | 1,469,809 | +3.21% | 0 | 383 | 13 | `NULL` (1 scored type `< 2`) | 0.68 MB |
| Kepulauan Riau | `21` | 70 | 70 (70) | 2,140,871 | 2,309,529 | -7.30% | 1 | 1,506 | 13 | 0.00 / 16.28 / 88.33 | 1.62 MB |
| **Total Sumatra** | — | **1,936** | **1,955 (1,936)** | **61,055,517** | **59,196,907** | **+3.14%** | **13** | **14,509** | **561** | — | — |

### Notes on COD-AB Counts, Geofabrik Coverage & UTM SRIDs
- **Non-district exclusions (`555`, `888`, `999`):**
  - `ID11` (Aceh): 290 minus 1 (`ID1106888` Danau) = **289**.
  - `ID12` (Sumatera Utara): 450 minus 1 (`ID1288888` Danau Toba) = **449**.
  - `ID13` (Sumatera Barat): 181 minus 2 (`ID1303888` Danau, `ID1388888` Danau) = **179**.
  - `ID14` (Riau): 169 = **169**.
  - `ID15` (Jambi): 143 minus 2 (`ID1501888` Danau Kerinci lake, `ID1506999` Hutan) = **141**.
  - `ID16` (Sumatera Selatan): 237 minus 1 (`ID1688888` Danau) = **236**.
  - `ID17` (Bengkulu): 131 minus 3 (`ID1703999` Hutan, `ID1706999` Hutan, `ID1709555` Wilayah Kosong) = **128**.
  - `ID18` (Lampung): 237 minus 9 (`ID1888888` Danau, `ID1801999`/`02999`/`03999`/`04999`/`09999`/`11999` Hutan, `ID1803555`/`04555` Pulau) = **228**.
  - `ID19` (Kep. Bangka Belitung): 47 = **47**.
  - `ID21` (Kepulauan Riau): 70 = **70**.
- **Geofabrik `.poly` boundary split:** Geofabrik's `sumatra.poly` excludes Kepulauan Bangka Belitung (`19`, 47/47 inside `kalimantan.poly`) and 1.3% of Lingga (`ID2104030`) in Kepulauan Riau (`21`). Accordingly `19` loads from `kalimantan-latest.osm.pbf` and `21` loads from `sumatra-latest.osm.pbf` + `kalimantan-latest.osm.pbf` (deduplicated by `source_id`).
- **UTM SRIDs (`utm_srid`) & Geodesic Area Check:** Zero NULL `utm_srid` rows across all 1,936 kecamatan and all 14,509 active facilities. Every PostGIS `utm_srid` matches `calculate_utm_srid()` (`326xx` north of equator, `327xx` south of equator):
  - `11`: `{32647: 222, 32646: 67}` (max UTM vs `ST_Area(geography)` diff = `0.1925%`)
  - `12`: `{32647: 443, 32747: 6}` (max diff = `0.0800%`)
  - `13`: `{32747: 155, 32647: 24}` (max diff = `0.1624%`)
  - `14`: `{32647: 93, 32748: 29, 32648: 27, 32747: 20}` (max diff = `0.1946%`)
  - `15`: `{32748: 101, 32747: 40}` (max diff = `0.1959%`)
  - `16`: `{32748: 236}` (max diff = `0.1389%`)
  - `17`: `{32748: 108, 32747: 20}` (max diff = `0.1953%`)
  - `18`: `{32748: 228}` (max diff = `0.0800%`)
  - `19`: `{32748: 42, 32749: 5}` (max diff = `0.1944%`)
  - `21`: `{32648: 49, 32649: 12, 32748: 9}` (max diff = `0.1886%`)
  - Maximum UTM vs geodesic area difference across all 1,936 kecamatan is `0.1959%` (`< 1%`).

---

## 3. WorldPop 2024 vs COD-PS 2020 Comparison

### Kabupaten/Kota with |Difference| > 15%

| Province | Code | Kabupaten / Kota | WorldPop 2024 | COD-PS 2020 | Diff (%) |
|---|---|---|---:|---:|---:|
| Aceh (`11`) | `11.72` | Kota Sabang | 42,977 | 34,589 | +24.25% |
| Aceh (`11`) | `11.75` | Kota Subulussalam | 95,249 | 81,094 | +17.46% |
| Sumatera Utara (`12`) | `12.06` | Toba Samosir | 215,009 | 184,269 | +16.68% |
| Sumatera Utara (`12`) | `12.09` | Simalungun | 1,018,288 | 871,702 | +16.82% |
| Sumatera Utara (`12`) | `12.14` | Nias Selatan | 372,877 | 324,011 | +15.08% |
| Sumatera Barat (`13`) | — | *(none)* | — | — | — |
| Riau (`14`) | `14.04` | Pelalawan | 406,689 | 495,742 | -17.96% |
| Riau (`14`) | `14.07` | Rokan Hulu | 573,663 | 701,882 | -18.27% |
| Jambi (`15`) | `15.04` | Batang Hari | 317,193 | 270,055 | +17.45% |
| Sumatera Selatan (`16`) | `16.08` | Ogan Komering Ulu Selatan | 427,193 | 367,407 | +16.27% |
| Sumatera Selatan (`16`) | `16.11` | Empat Lawang | 350,433 | 253,317 | +38.34% |
| Bengkulu (`17`) | — | *(none)* | — | — | — |
| Lampung (`18`) | `18.05` | Lampung Tengah | 1,528,830 | 1,292,199 | +18.31% |
| Lampung (`18`) | `18.11` | Mesuji | 231,781 | 201,393 | +15.09% |
| Kep. Bangka Belitung (`19`) | — | *(none)* | — | — | — |
| Kepulauan Riau (`21`) | `21.71` | Kota Batam | 1,243,353 | 1,481,077 | -16.05% |

Differences reflect the 2020-to-2024 census/growth gap (e.g., Empat Lawang +38.34%, Lampung Tengah +18.31%) and WorldPop's building-constrained dasymetric allocation lowering older peri-urban/plantation projections (Kota Batam `-16.05%`, Pelalawan `-17.96%`, Rokan Hulu `-18.27%`).

---

## 4. Facility Counts per Pillar & Scoring Behavior

| Province | `lifeline_health` | `education` | `urban_livability` | `mobility_connectivity` | Total Active | Zero-Facility Kecamatan |
|---|---:|---:|---:|---:|---:|---:|
| Aceh (`11`) | 369 | 1,238 | 360 | 230 | 2,197 | 51 |
| Sumatera Utara (`12`) | 385 | 902 | 525 | 348 | 2,160 | 219 |
| Sumatera Barat (`13`) | 212 | 816 | 313 | 209 | 1,550 | 19 |
| Riau (`14`) | 299 | 875 | 637 | 366 | 2,177 | 32 |
| Jambi (`15`) | 277 | 866 | 110 | 95 | 1,348 | 12 |
| Sumatera Selatan (`16`) | 185 | 517 | 216 | 210 | 1,128 | 100 |
| Bengkulu (`17`) | 218 | 442 | 109 | 46 | 815 | 30 |
| Lampung (`18`) | 220 | 620 | 235 | 170 | 1,245 | 72 |
| Kep. Bangka Belitung (`19`) | 87 | 197 | 58 | 41 | 383 | 13 |
| Kepulauan Riau (`21`) | 188 | 501 | 478 | 339 | 1,506 | 13 |

### Why Only Three Sumatra Provinces Yield Numeric Composite Scores
- Under the J1a2 province-scaled availability gate, each scored facility type must have at least `N` classified OSM records in the province (`N` = number of kecamatan in that province), and a pillar must have `>= 2` available scored types to compute a pillar score.
- Across all 10 Sumatra provinces, `lifeline_health` has 0 facility types meeting `>= N`, so `health_score` is `NULL` (`cakupan data rendah`) everywhere.
- In `education`:
  - **Sumatera Barat (`13`, N=179):** `sekolah_dasar` (279) and `sekolah_menengah_atas` (199) are `available` (2 types) -> composite computed for 75 `memadai` kecamatan.
  - **Jambi (`15`, N=141):** `sekolah_dasar` (412) and `sekolah_menengah_pertama` (186) are `available` (2 types) -> composite computed for 104 `memadai` kecamatan.
  - **Kepulauan Riau (`21`, N=70):** `sekolah_dasar` (153), `sekolah_menengah_pertama` (74), and `sekolah_menengah_atas` (98) are `available` (3 types) -> composite computed for 27 `memadai` kecamatan.
  - **Aceh (`11`), Riau (`14`), Bengkulu (`17`), Bangka Belitung (`19`):** only 1 scored type meets `>= N` (`sekolah_menengah_atas` in `11`/`14`; `sekolah_dasar` in `17`/`19`).
  - **Sumatera Utara (`12`), Sumatera Selatan (`16`), Lampung (`18`):** 0 scored types meet `>= N`.
  - Consequently, in those 7 provinces, `education_score` and `composite_livability_score` remain `NULL` (`Data tidak memadai` / `cakupan data rendah`) even for kecamatan passing the local `sekolah_dasar >= 1` gate.

---

## 5. Spot Checks (Well-Known Urban Kecamatan)

| Kecamatan | City / Province | Code (`kemendagri_code` / `cod_ab_pcode`) | UTM SRID | Population (WorldPop 2024) | Active Facilities | `osm_coverage` (`mapped_sd / req_sd`) | Composite Score |
|---|---|---|---:|---:|---:|---|---:|
| **Medan Baru** | Kota Medan, Sumatera Utara (`12`) | `12.75.090` / `ID1275090` | `32647` | 72,583 | 53 | `memadai` (`3 / 46`) | `NULL` (0 province types `>= 449`) |
| **Padang Barat** | Kota Padang, Sumatera Barat (`13`) | `13.71.060` / `ID1371060` | `32747` | 53,006 | 72 | `memadai` (`9 / 34`) | `50.73` (`education`) |
| **Ilir Barat I** | Kota Palembang, Sumatera Selatan (`16`) | `16.71.040` / `ID1671040` | `32748` | 227,113 | 64 | `memadai` (`7 / 142`) | `NULL` (0 province types `>= 236`) |

---

## 6. OSM Coverage Gate Summary

| Province | Code | Total Kecamatan | Local Gate `tidak_memadai` (SD=0) | Local Gate `memadai` (SD>=1) | Province Scored Types `>= N` | Scored Composite (Min / Median / Max) |
|---|---|---:|---:|---:|---:|---:|
| Aceh | `11` | 289 | 225 | 64 | 1 (`SMA`: 297) | `NULL` (`< 2` types) |
| Sumatera Utara | `12` | 449 | 360 | 89 | 0 | `NULL` (`< 2` types) |
| Sumatera Barat | `13` | 179 | 104 | 75 | 2 (`SD`: 279, `SMA`: 199) | 1.00 / 13.34 / 97.06 |
| Riau | `14` | 169 | 107 | 62 | 1 (`SMA`: 244) | `NULL` (`< 2` types) |
| Jambi | `15` | 141 | 37 | 104 | 2 (`SD`: 412, `SMP`: 186) | 0.71 / 21.88 / 100.00 |
| Sumatera Selatan | `16` | 236 | 174 | 62 | 0 | `NULL` (`< 2` types) |
| Bengkulu | `17` | 128 | 68 | 60 | 1 (`SD`: 205) | `NULL` (`< 2` types) |
| Lampung | `18` | 228 | 159 | 69 | 0 | `NULL` (`< 2` types) |
| Kep. Bangka Belitung | `19` | 47 | 27 | 20 | 1 (`SD`: 62) | `NULL` (`< 2` types) |
| Kepulauan Riau | `21` | 70 | 43 | 27 | 3 (`SD`: 153, `SMP`: 74, `SMA`: 98) | 0.00 / 16.28 / 88.33 |

### Per-Type Zero Counts (Kecamatan with 0 Active OSM Records)

| Province | `taman_kanak_kanak` | `sekolah_dasar` | `sekolah_menengah_pertama` | `sekolah_menengah_atas` | `puskesmas_kelurahan` | `puskesmas_kecamatan` | `pos_damkar` |
|---|---:|---:|---:|---:|---:|---:|---:|
| Aceh (`11`, n=289) | 249 | 225 | 237 | 94 | 241 | 288 | 277 |
| Sumatera Utara (`12`, n=449) | 407 | 361 | 369 | 383 | 410 | 449 | 445 |
| Sumatera Barat (`13`, n=179) | 149 | 104 | 123 | 64 | 137 | 179 | 173 |
| Riau (`14`, n=169) | 136 | 107 | 114 | 59 | 143 | 167 | 157 |
| Jambi (`15`, n=141) | 108 | 37 | 58 | 70 | 76 | 141 | 132 |
| Sumatera Selatan (`16`, n=236) | 210 | 174 | 178 | 183 | 207 | 236 | 231 |
| Bengkulu (`17`, n=128) | 117 | 68 | 73 | 73 | 94 | 128 | 125 |
| Lampung (`18`, n=228) | 192 | 160 | 180 | 197 | 197 | 228 | 227 |
| Kep. Bangka Belitung (`19`, n=47) | 34 | 27 | 35 | 35 | 38 | 47 | 47 |
| Kepulauan Riau (`21`, n=70) | 56 | 48 | 47 | 27 | 53 | 70 | 63 |

### Known Limitation
As in Java (`32`–`36`), rural and regional OSM mapping across Sumatra is sparse: 1,304 of 1,936 kecamatan have `0` mapped `sekolah_dasar` (`tidak_memadai`), and 7 of 10 provinces have `< 2` facility types meeting the province-wide `>= N` threshold. Even kecamatan passing the local `sekolah_dasar >= 1` gate (`memadai`) often have substantial OSM under-counting relative to real facilities and must be interpreted alongside `osm_coverage`.
