# Papua Regional Data Load Report (Staging DB)

- **Target Database:** `district_profiling_stage` (PostgreSQL 16 + PostGIS 3.4)
- **Target Redis DB:** `1` (`cache:compliance:scores:<province_code>`)
- **Live Database (`district_profiling`):** Untouched (enforced by live-DB guard)
- **Standards Engine:** SNI 03-1733-2004 via `backend/app/engine/standards_availability.py` and `pipeline/load_region.py`
- **OSM PBF Extract:** `papua-latest.osm.pbf` (`91`–`96`, all 601 districts 100% inside `papua.poly`)
- **COD-AB 2-to-6 Province Split:** Assigned via UU 14/2022 (`93`), UU 15/2022 (`94`), UU 16/2022 (`95`), UU 29/2022 (`96`), and parent provinces (`91`, `92`) using Kepmendagri `100.1.1-6117 Tahun 2022` kabupaten codes; exact COD-AB pcodes retained in `cod_ab_pcode`.

---

## 1. Provinces `11`–`19`, `21`, `31`–`36` & `71`–`76` Unchanged Verification

| Province | Code | Kab/Kota (Before / After) | Kecamatan (Before / After) | Active Facilities (Before / After) | Scorecard SHA-256 (Before == After) |
|---|---|---|---|---|---|
| Aceh | `11` | 23 / 23 | 289 / 289 | 2,197 / 2,197 | `bc4bee00285486f179aae9a1dc5049f28294dbb310a46c2e7bdca86e4420fa22` |
| Sumatera Utara | `12` | 33 / 33 | 449 / 449 | 2,160 / 2,160 | `bc4c87a2dcf8af78297f5e226ee5663c8d3e9ba95e4f1915f0c5d2de433769e4` |
| Sumatera Barat | `13` | 19 / 19 | 179 / 179 | 1,550 / 1,550 | `4d3236d5234225263879e28f3154f53e043b39f6d20e38b5efb995b4d111502d` |
| Riau | `14` | 12 / 12 | 169 / 169 | 2,177 / 2,177 | `6eb05c8c7b7367644508ec1c7c91dd98c4d647bf28d4cf7f53776c04b13fae7a` |
| Jambi | `15` | 11 / 11 | 141 / 141 | 1,348 / 1,348 | `bc02d7719a1b67c43e62f48b6b5576d498495827ff98318cc48db63b5230edc0` |
| Sumatera Selatan | `16` | 17 / 17 | 236 / 236 | 1,128 / 1,128 | `5d40821e9186c25cad9f4e6b323bfd307b222fc9a331d1bb4e51bae245dbf668` |
| Bengkulu | `17` | 10 / 10 | 128 / 128 | 815 / 815 | `46207ca84e511c2db22326bd7183a9e6d4715e3f61e5fe7905b097effe590f62` |
| Lampung | `18` | 15 / 15 | 228 / 228 | 1,245 / 1,245 | `beb530dac4e201dc95ae43d830d19fd2918dcc130e821d6fe7a8a596b6259a7d` |
| Kep. Bangka Belitung | `19` | 7 / 7 | 47 / 47 | 383 / 383 | `da074d5c0747fa235cfa6bdb39d95184fda31db56ca2f7efc9cc0afaf9610a53` |
| Kepulauan Riau | `21` | 7 / 7 | 70 / 70 | 1,506 / 1,506 | `ce1011cd0214d8cd39c4d65544d8713d54945a1da69a9c36351d3f45f01bb2b4` |
| DKI Jakarta | `31` | 6 / 6 | 44 / 44 | 14,496 / 14,496 | `f61c3ba1343e7053a579528a76a7f066f232b1ae5bb8948ea9f25b40110d27f9` |
| Jawa Barat | `32` | 27 / 27 | 627 / 627 | 18,983 / 18,983 | `cd852b3480506314a739f84f8058c4c0f07c97ab44369c48eb636230c323d935` |
| Jawa Tengah | `33` | 35 / 35 | 573 / 573 | 12,543 / 12,543 | `cc2f013474e1b6f923a36d7faa9a77002788c0e857059acc3317bb88d3d2969c` |
| DI Yogyakarta | `34` | 5 / 5 | 78 / 78 | 3,969 / 3,969 | `f71fef143c3c18d7149af0a412b08a2ca4bb5664b2aae5e160790a99b80f94c1` |
| Jawa Timur | `35` | 38 / 38 | 666 / 666 | 13,423 / 13,423 | `efd6622806b07f4882b0078610ab1b36113f54bc7bf73de5625573fe9af1719d` |
| Banten | `36` | 8 / 8 | 155 / 155 | 3,675 / 3,675 | `943517120748fd52ca1442785132944e4231a2a3c4ff92e54595c5558abf851a` |
| Sulawesi Utara | `71` | 15 / 15 | 171 / 171 | 2,393 / 2,393 | `c7fb3950361194fc9984059c7f522f5c3d11307076602c0c242f78f755a4de78` |
| Sulawesi Tengah | `72` | 13 / 13 | 175 / 175 | 612 / 612 | `36e3b972e2b5fe6963d81a416fa59a5440a556691b9aec824655f54b31e2fba1` |
| Sulawesi Selatan | `73` | 24 / 24 | 307 / 307 | 6,907 / 6,907 | `d89fedc512fb07c4ed92d7b8a6124ea2a538654a0c7b01fd1372894e3ec4a408` |
| Sulawesi Tenggara | `74` | 17 / 17 | 222 / 222 | 1,423 / 1,423 | `4c2a11a3453b4a44ad0c0a09fff932aa3b8d9397b906d375632c99ff6dd3067f` |
| Gorontalo | `75` | 6 / 6 | 77 / 77 | 211 / 211 | `ca6aa8c1c34bc937bbadd5fb692ecc7230a25f81896492d8f2497a4f1ca06c20` |
| Sulawesi Barat | `76` | 6 / 6 | 69 / 69 | 238 / 238 | `28bd661f7dbab30f15f0f4fbe35ed897cddc92141efd76dd7d82c66aa039c895` |

- **`regulatory_standards` rows:** `16` before == `16` after.
- All 22 previously loaded provinces (`11`–`19`, `21`, `31`–`36`, `71`–`76`): `0` diffs across kab/kota counts, kecamatan counts, active facility counts, and scorecard SHA-256 checksums.

---

## 2. Per-Province Summary (Provinces 91–96)

| Province | Code | Loaded Kecamatan | COD-AB Raw (Valid) | WorldPop 2024 | COD-PS 2020 | Pop Diff (%) | Kab/Kota \|Diff\| > 15% | Active Facilities | Zero-Facility Kecamatan | Composite Score (Min / Median / Max of Scored) | GeoJSON Size |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| Papua | `91` | 97 | 97 (97) | 1,055,660 | 849,146 | +24.32% | 5 | 230 | 45 | `NULL` (0 types `>= 97`) | 1.46 MB |
| Papua Barat | `92` | 78 | 78 (78) | 536,233 | 473,143 | +13.33% | 5 | 318 | 45 | `NULL` (0 types `>= 78`) | 0.46 MB |
| Papua Selatan | `93` | 69 | 69 (69) | 547,458 | 500,577 | +9.37% | 2 | 68 | 53 | `NULL` (0 types `>= 69`) | 0.59 MB |
| Papua Tengah | `94` | 73 | 73 (73) | 1,447,029 | 995,197 | +45.40% | 7 | 111 | 51 | `NULL` (0 types `>= 73`) | 0.45 MB |
| Papua Pegunungan | `95` | 185 | 185 (185) | 1,429,309 | 1,048,155 | +36.36% | 4 | 304 | 148 | `NULL` (0 types `>= 185`) | 0.39 MB |
| Papua Barat Daya | `96` | 99 | 99 (99) | 591,403 | 512,881 | +15.31% | 2 | 201 | 57 | `NULL` (0 types `>= 99`) | 0.58 MB |
| **Total Papua** | — | **601** | **601 (601)** | **5,607,092** | **4,379,099** | **+28.04%** | **25** | **1,232** | **399** | — | — |

### Notes on COD-AB Counts, Geofabrik Coverage, WorldPop Highlands Edge Case & UTM SRIDs
- **COD-AB 2-to-6 province split:** COD-AB `idn_admin3` contains 601 polygons (`ID91`: 177, `ID94`: 424) with `0` non-district (`555`/`888`/`999`) polygons. All 42 kabupaten/kota were mapped cleanly to provinces `91`–`96` per UU 14, 15, 16, and 29 of 2022 (`pipeline/data/sources/REGION_SOURCES.md` §4e).
- **Geofabrik `.poly` boundary check:** Polygon containment against `papua.poly` confirmed **601 / 601 districts (100%)**—including Raja Ampat, Waigeo, Biak, Kepulauan Yapen, and Kolepom/Kimaam—lie fully inside `papua.poly`.
- **WorldPop 2024 constrained zero-pixel highland kecamatan (`95`):** Four remote highland kecamatan in Papua Pegunungan (`95`)—`95.03.052` Soloikma (`105.54 km²`) and `95.03.055` Kwikma (`75.99 km²`) in Kab. Yahukimo, plus `95.04.048` Wari / Taiyeve (`140.49 km²`) and `95.04.100` Gundagi (`87.79 km²`) in Kab. Tolikara—contain 0 non-nodata pixels in the WorldPop Global2 constrained 100 m 2024 raster (no built-up cells detected in the settlement mask), yielding `population = 0`. `load_region.py` skips inserting `district_compliance_scores` rows for `population <= 0` (`scored_districts=181`, `memadai=69`, `tidak_memadai=112`, `+4 zero-pop`) while caching all 185 kecamatan in Redis via `LEFT JOIN` so the API returns `score_status = "Data tidak memadai"`.
- **UTM SRIDs (`utm_srid`) & Geodesic Area Check:** Zero NULL `utm_srid` rows across all 601 kecamatan and all 1,232 active facilities. Every PostGIS `utm_srid` matches `calculate_utm_srid()` (`326xx` north of the equator, `327xx` south of the equator, zones 52–54):
  - `91`: `{32753: 53, 32754: 44}` (max UTM vs `ST_Area(geography)` diff = `0.1944%` at Mamberamo Tengah Timur `91.20.060`)
  - `92`: `{32753: 78}` (max diff = `0.1730%` at Fakfak Barat `92.03.070`)
  - `93`: `{32753: 1, 32754: 68}` (max diff = `0.1880%` at Joerat `93.04.073`)
  - `94`: `{32753: 69, 32754: 4}` (max diff = `0.1939%` at Yamo `94.02.052`)
  - `95`: `{32753: 2, 32754: 183}` (max diff = `0.1849%` at Kuyawage `95.07.050`)
  - `96`: `{32752: 51, 32753: 46, 32652: 2}` (two northern Raja Ampat districts north of 0° receive `32652` / 52N; max diff = `0.1943%` at Fokour `96.02.081`)
  - Maximum UTM vs `ST_Area(geography)` difference across all 601 kecamatan is `0.1944%` (`< 1%`).

---

## 3. WorldPop 2024 vs COD-PS 2020 Comparison

### Kabupaten/Kota with |Difference| > 15%

| Province | Code | Kabupaten / Kota | WorldPop 2024 | COD-PS 2020 | Diff (%) |
|---|---|---|---:|---:|---:|
| Papua (`91`) | `91.03` | Jayapura | 174,566 | 127,435 | +36.98% |
| Papua (`91`) | `91.05` | Kepulauan Yapen | 117,462 | 97,559 | +20.40% |
| Papua (`91`) | `91.19` | Supiori | 23,477 | 20,355 | +15.34% |
| Papua (`91`) | `91.20` | Mamberamo Raya | 40,856 | 24,049 | +69.89% |
| Papua (`91`) | `91.71` | Kota Jayapura | 414,384 | 302,800 | +36.85% |
| Papua Barat (`92`) | `92.02` | Manokwari | 198,410 | 171,449 | +15.73% |
| Papua Barat (`92`) | `92.06` | Teluk Bintuni | 93,553 | 66,335 | +41.03% |
| Papua Barat (`92`) | `92.07` | Teluk Wondama | 42,784 | 33,454 | +27.89% |
| Papua Barat (`92`) | `92.08` | Kaimana | 45,628 | 62,948 | -27.51% |
| Papua Barat (`92`) | `92.11` | Manokwari Selatan | 38,724 | 25,554 | +51.54% |
| Papua Selatan (`93`) | `93.03` | Mappi | 118,236 | 100,062 | +18.16% |
| Papua Selatan (`93`) | `93.04` | Asmat | 120,196 | 99,262 | +21.09% |
| Papua Tengah (`94`) | `94.01` | Nabire | 176,948 | 146,444 | +20.83% |
| Papua Tengah (`94`) | `94.02` | Puncak Jaya | 232,289 | 127,159 | +82.68% |
| Papua Tengah (`94`) | `94.03` | Paniai | 227,774 | 170,303 | +33.75% |
| Papua Tengah (`94`) | `94.04` | Mimika | 326,644 | 216,468 | +50.90% |
| Papua Tengah (`94`) | `94.06` | Dogiyai | 121,340 | 97,771 | +24.11% |
| Papua Tengah (`94`) | `94.07` | Intan Jaya | 139,787 | 50,499 | +176.81% |
| Papua Tengah (`94`) | `94.08` | Deiyai | 103,537 | 75,160 | +37.76% |
| Papua Pegunungan (`95`) | `95.01` | Jayawijaya | 301,697 | 210,415 | +43.38% |
| Papua Pegunungan (`95`) | `95.03` | Yahukimo | 357,072 | 193,891 | +84.16% |
| Papua Pegunungan (`95`) | `95.04` | Tolikara | 207,992 | 145,626 | +42.83% |
| Papua Pegunungan (`95`) | `95.06` | Yalimo | 98,112 | 66,067 | +48.50% |
| Papua Barat Daya (`96`) | `96.01` | Sorong | 119,145 | 91,690 | +29.94% |
| Papua Barat Daya (`96`) | `96.04` | Tambrauw | 28,485 | 15,397 | +85.00% |

Differences reflect the 2020-to-2024 census/projection gap (including large *Sensus Penduduk 2020* vs older 2010-projected COD-PS revisions in central highland regencies such as Intan Jaya `+176.81%`, Yahukimo `+84.16%`, and Puncak Jaya `+82.68%`, plus urban/resource growth in Mimika `+50.90%` and Kota Jayapura `+36.85%`) and WorldPop Global2's building-constrained dasymetric allocation (which lowers Kaimana `-27.51%` and leaves 4 remote highland districts in `95` at 0 settled pixels).

---

## 4. Facility Counts per Pillar & Scoring Behavior

| Province | `lifeline_health` | `education` | `urban_livability` | `mobility_connectivity` | Total Active | Zero-Facility Kecamatan |
|---|---:|---:|---:|---:|---:|---:|
| Papua (`91`) | 36 | 101 | 57 | 36 | 230 | 45 |
| Papua Barat (`92`) | 48 | 163 | 69 | 38 | 318 | 45 |
| Papua Selatan (`93`) | 18 | 37 | 7 | 6 | 68 | 53 |
| Papua Tengah (`94`) | 20 | 60 | 23 | 8 | 111 | 51 |
| Papua Pegunungan (`95`) | 28 | 80 | 180 | 16 | 304 | 148 |
| Papua Barat Daya (`96`) | 60 | 93 | 26 | 22 | 201 | 57 |

### Why No Papua Province Yields Numeric Composite Scores
- Under the J1a2 province-scaled availability gate, each scored facility type must have at least `N` classified OSM records in the province (`N` = number of kecamatan in that province: `97` for `91`, `78` for `92`, `69` for `93`, `73` for `94`, `185` for `95`, `99` for `96`), and a pillar must have `>= 2` available scored types to compute a pillar score.
- Across all 6 Papua provinces, **0 scored facility types** reach `>= N` (the highest count is `sekolah_dasar` in Papua Barat `92` at `62 < 78`).
- Consequently, all pillar scores and `composite_livability_score` remain `NULL` (`Data tidak memadai` / `cakupan data rendah`) across all 6 provinces, even for kecamatan that pass the local `sekolah_dasar >= 1` gate (`memadai`).

---

## 5. Spot Checks (Well-Known Urban Kecamatan)

| Kecamatan | City / Province | Code (`kemendagri_code` / `cod_ab_pcode`) | UTM SRID | UTM vs Geog Area Diff | Population (WorldPop 2024) | Active Facilities | `osm_coverage` (`mapped_sd / req_sd`) | Composite Score |
|---|---|---|---:|---:|---:|---:|---|---:|
| **Jayapura Utara** | Kota Jayapura, Papua (`91`) | `91.71.040` / `ID9471040` | `32754` | `0.0770%` | 81,384 | 15 | `tidak_memadai` (`0 / 51`) | `NULL` (gated SD=0) |
| **Sorong** | Kota Sorong, Papua Barat Daya (`96`) | `96.71.022` / `ID9171022` | `32752` | `0.0778%` | 43,632 | 32 | `memadai` (`1 / 28`) | `NULL` (0 province types `>= 99`) |
| **Merauke** | Kab. Merauke, Papua Selatan (`93`) | `93.01.040` / `ID9401040` | `32754` | `0.0739%` | 112,478 | 18 | `tidak_memadai` (`0 / 71`) | `NULL` (gated SD=0) |

---

## 6. OSM Coverage Gate Summary

| Province | Code | Total Kecamatan | Local Gate `tidak_memadai` (SD=0) | Local Gate `memadai` (SD>=1 or pop<1600) | Province Scored Types `>= N` | Scored Composite (Min / Median / Max) |
|---|---|---:|---:|---:|---:|---|
| Papua | `91` | 97 | 66 | 31 | 0 | `NULL` (`< 2` types) |
| Papua Barat | `92` | 78 | 38 | 40 | 0 | `NULL` (`< 2` types) |
| Papua Selatan | `93` | 69 | 47 | 22 | 0 | `NULL` (`< 2` types) |
| Papua Tengah | `94` | 73 | 54 | 19 | 0 | `NULL` (`< 2` types) |
| Papua Pegunungan | `95` | 185 | 112 *(+4 zero-pop)* | 69 | 0 | `NULL` (`< 2` types) |
| Papua Barat Daya | `96` | 99 | 39 | 60 | 0 | `NULL` (`< 2` types) |

### Per-Type Zero Counts (Kecamatan with 0 Active OSM Records)

| Province | `taman_kanak_kanak` | `sekolah_dasar` | `sekolah_menengah_pertama` | `sekolah_menengah_atas` | `puskesmas_kelurahan` | `puskesmas_kecamatan` | `pos_damkar` |
|---|---:|---:|---:|---:|---:|---:|---:|
| Papua (`91`, n=97) | 96 | 89 | 91 | 64 | 89 | 97 | 96 |
| Papua Barat (`92`, n=78) | 69 | 60 | 65 | 58 | 67 | 78 | 77 |
| Papua Selatan (`93`, n=69) | 67 | 66 | 66 | 58 | 65 | 69 | 69 |
| Papua Tengah (`94`, n=73) | 70 | 68 | 67 | 56 | 69 | 73 | 70 |
| Papua Pegunungan (`95`, n=185) | 184 | 171 | 180 | 179 | 180 | 185 | 185 |
| Papua Barat Daya (`96`, n=99) | 99 | 79 | 90 | 74 | 93 | 99 | 99 |

### Known Limitation
OSM facility mapping across Papua is very sparse: 399 of 601 kecamatan have `0` mapped OSM facilities, 356 kecamatan are locally gated (`tidak_memadai` with `0` `sekolah_dasar` for population `>= 1,600`), 4 remote highland kecamatan in Papua Pegunungan (`95`) have `0` WorldPop constrained pixels, and 0 of 6 provinces reach the province-wide `>= N` facility threshold for any scored type. All Papua scorecards therefore honestly display `"Data tidak memadai"` rather than extrapolating 0% compliance from missing OSM data.
