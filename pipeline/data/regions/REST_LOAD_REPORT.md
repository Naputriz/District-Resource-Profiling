# Rest of Indonesia (Bali–Nusa Tenggara, Kalimantan, Maluku) Regional Data Load Report (Staging DB)

- **Target Database:** `district_profiling_stage` (PostgreSQL 16 + PostGIS 3.4)
- **Target Redis DB:** `1` (`cache:compliance:scores:<province_code>`)
- **Live Database (`district_profiling`):** Untouched (enforced by live-DB guard)
- **Standards Engine:** SNI 03-1733-2004 via `backend/app/engine/standards_availability.py` and `pipeline/load_region.py`
- **OSM PBF Extracts:** `nusa-tenggara-latest.osm.pbf` (`51`–`53`), `kalimantan-latest.osm.pbf` (`61`–`65`), and `maluku-latest.osm.pbf` (`81`–`82`)
- **COD-AB `65` (Kalimantan Utara):** COD-AB `idn_admin1`/`idn_admin2`/`idn_admin3` already uses `ID65` Kalimantan Utara (5 kab/kota, 53 valid kecamatan), so no UU 20/2012 reassignment was required.

---

## 1. Provinces `11`–`19`, `21`, `31`–`36`, `71`–`76` & `91`–`96` Unchanged Verification

| Province | Code | Kab/Kota (Before / After) | Kecamatan (Before / After) | Active Facilities (Before / After) | Scorecard SHA-256 (Before == After) |
|---|---|---|---|---|---|
| Aceh | `11` | 23 / 23 | 289 / 289 | 2,197 / 2,197 | `6554dcc53705f061d2c31fdf404ae59e433a7f41630ea5e89b55a41f9440537c` |
| Sumatera Utara | `12` | 33 / 33 | 449 / 449 | 2,160 / 2,160 | `09b97740665e3ec16f931d0776175600193fc7a3e983dd2cc632ef8f38778658` |
| Sumatera Barat | `13` | 19 / 19 | 179 / 179 | 1,550 / 1,550 | `4234413d85fe9e53791e54ab01f9b76d1ac3db6c5942b79582fd12e7cc35bc08` |
| Riau | `14` | 12 / 12 | 169 / 169 | 2,177 / 2,177 | `2f1b039dbad52bceabb3b03afd2eaf963f7c73a6b095e12f01bef1b9e1581bca` |
| Jambi | `15` | 11 / 11 | 141 / 141 | 1,348 / 1,348 | `e27987c4c2ff679e14b3a4533ed3d6cb766897963fe1fc2717d85ea974e64368` |
| Sumatera Selatan | `16` | 17 / 17 | 236 / 236 | 1,128 / 1,128 | `08e45023efb5c687f1eff3ada11cb0e3efd1020f5ff7cdfad3a72f300639fcdc` |
| Bengkulu | `17` | 10 / 10 | 128 / 128 | 815 / 815 | `b38b7b72854ee39e239cf4b0596c735756def75d1c1290db64fe7a2f240535d6` |
| Lampung | `18` | 15 / 15 | 228 / 228 | 1,245 / 1,245 | `d2bd9cca2cbdec6ba26b2503bdae22b623b89f1393b984ae820572e7138bf334` |
| Kep. Bangka Belitung | `19` | 7 / 7 | 47 / 47 | 383 / 383 | `4181d7f50e331f44a9cc344a44f8ed8882b20770c31a324c55a331269e363631` |
| Kepulauan Riau | `21` | 7 / 7 | 70 / 70 | 1,506 / 1,506 | `47b7561b71d8a8b22eb52222f6508e6b13eeb683e7f3e771017e391309bcf404` |
| DKI Jakarta | `31` | 6 / 6 | 44 / 44 | 14,496 / 14,496 | `c323b7c389eb61edd93f887b6cae13e123b16566198841d87a60fa1217be7913` |
| Jawa Barat | `32` | 27 / 27 | 627 / 627 | 18,983 / 18,983 | `3ea15b8cc6e1c526a0059ea4617c4a686d9eac946eac79671433b4017dec8e50` |
| Jawa Tengah | `33` | 35 / 35 | 573 / 573 | 12,543 / 12,543 | `2104d1770420a35b3abf3492811aef07b67dbec60c80773f659867237ec91f67` |
| DI Yogyakarta | `34` | 5 / 5 | 78 / 78 | 3,969 / 3,969 | `bd41edb5b1380076f2f1a7c0a2149dc5f6e4384bd83589a71229ac75f1fea1fb` |
| Jawa Timur | `35` | 38 / 38 | 666 / 666 | 13,423 / 13,423 | `6321740ec5b2c59c03690657145e3c89061822ecf73ea4ca844b5694fa80fd82` |
| Banten | `36` | 8 / 8 | 155 / 155 | 3,675 / 3,675 | `99c210e5fff2c17c4c6496b8e714ae3aa6f165c035d45bc84a71f1cca48a9c42` |
| Sulawesi Utara | `71` | 15 / 15 | 171 / 171 | 2,393 / 2,393 | `c6c9ddfbe0f75095c73c0ee55cdf7786052bd3dcb34d04736fb5ac97bbf4fd66` |
| Sulawesi Tengah | `72` | 13 / 13 | 175 / 175 | 612 / 612 | `f463ffae8100a8d4743cc901ed91a7bae1660ea4d4af37d29859bf0fcbb9d004` |
| Sulawesi Selatan | `73` | 24 / 24 | 307 / 307 | 6,907 / 6,907 | `7dfe13ad7ab37c23d56c5cd37bc44f5b9668e3b7f8664c6021751e782270463d` |
| Sulawesi Tenggara | `74` | 17 / 17 | 222 / 222 | 1,423 / 1,423 | `997ac37210625915a3df1240c37ac03c0e67b199d8c95217e59d025f482699e7` |
| Gorontalo | `75` | 6 / 6 | 77 / 77 | 211 / 211 | `ffa9a9bbb422a0181893c82c91a96a77f5f960338cfc3ebd3a93f82e113fc300` |
| Sulawesi Barat | `76` | 6 / 6 | 69 / 69 | 238 / 238 | `17288c81b74e89ac941f479a0ef05a28e74d6acd35984c581184a5439cf81941` |
| Papua | `91` | 9 / 9 | 97 / 97 | 230 / 230 | `e5b5ca52391deaa3d966ece6aa3a11dadec7ffeb01c7b7b86440dcbda811ae17` |
| Papua Barat | `92` | 7 / 7 | 78 / 78 | 318 / 318 | `6b80cffb66071668ca0229452548d20084a68994ae2b5525284f90aec3602f64` |
| Papua Selatan | `93` | 4 / 4 | 69 / 69 | 68 / 68 | `a4128a111a02bf889ce374f14ba4a19546125870179d15ee6b8ab26b54f22ffd` |
| Papua Tengah | `94` | 8 / 8 | 73 / 73 | 111 / 111 | `d1b6713a8597fea24864c20ebb6fe06948ada2c77dee1555bb907090338b7c23` |
| Papua Pegunungan | `95` | 8 / 8 | 185 / 185 | 304 / 304 | `98ee36215192981f325568bb41cd21d3d9310913f6125036929b079dc0bb91df` |
| Papua Barat Daya | `96` | 6 / 6 | 99 / 99 | 201 / 201 | `01faa10dd8613e12c08cd64bcabadfb39b4586753ac0e8e85bfc07bb6ddf28aa` |

- **`regulatory_standards` rows:** `16` before == `16` after.
- All 28 previously loaded provinces (`11`–`19`, `21`, `31`–`36`, `71`–`76`, `91`–`96`): `0` diffs across kab/kota counts, kecamatan counts, active facility counts, and scorecard SHA-256 checksums.

---

## 2. Per-Province Summary (Provinces `51`–`53`, `61`–`65`, `81`–`82`)

| Province | Code | Loaded Kecamatan | COD-AB Raw (Valid) | WorldPop 2024 | COD-PS 2020 | Pop Diff (%) | Kab/Kota \|Diff\| > 15% | Active Facilities | Zero-Facility Kecamatan | Composite Score (Min / Median / Max of Scored) | GeoJSON Size |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| Bali | `51` | 57 | 57 (57) | 4,517,203 | 4,414,431 | +2.33% | 7 | 2,478 | 2 | 0.33 / 6.48 / 29.22 | 0.72 MB |
| Nusa Tenggara Barat | `52` | 116 | 116 (116) | 5,561,107 | 5,225,915 | +6.41% | 0 | 8,636 | 1 | 1.36 / 19.27 / 72.71 | 1.39 MB |
| Nusa Tenggara Timur | `53` | 307 | 307 (307) | 5,569,724 | 5,513,402 | +1.02% | 3 | 3,487 | 90 | `NULL` (1 scored type `< 2`) | 2.18 MB |
| Kalimantan Barat | `61` | 174 | 174 (174) | 5,649,973 | 5,104,900 | +10.68% | 4 | 795 | 89 | `NULL` (0 scored types) | 1.77 MB |
| Kalimantan Tengah | `62` | 136 | 136 (136) | 2,785,265 | 2,686,252 | +3.69% | 5 | 848 | 52 | `NULL` (1 scored type `< 2`) | 0.55 MB |
| Kalimantan Selatan | `63` | 152 | 152 (152) | 4,254,599 | 4,268,610 | -0.33% | 1 | 2,222 | 10 | 0.00 / 17.73 / 73.48 | 0.94 MB |
| Kalimantan Timur | `64` | 103 | 103 (103) | 3,920,326 | 3,664,673 | +6.98% | 4 | 2,961 | 9 | 1.78 / 21.45 / 87.50 | 1.36 MB |
| Kalimantan Utara | `65` | 53 | 53 (53) | 729,295 | 708,352 | +2.96% | 1 | 424 | 12 | `NULL` (1 scored type `< 2`) | 0.93 MB |
| Maluku | `81` | 118 | 118 (118) | 1,900,373 | 1,787,087 | +6.34% | 7 | 682 | 62 | `NULL` (0 scored types) | 1.64 MB |
| Maluku Utara | `82` | 116 | 118 (116) | 1,329,350 | 1,252,317 | +6.15% | 3 | 428 | 26 | `NULL` (0 scored types) | 1.55 MB |
| **Total (10 Provinces)** | — | **1,332** | **1,334 (1,332)** | **36,217,215** | **34,625,939** | **+4.60%** | **35** | **22,961** | **353** | — | — |

### Notes on COD-AB Counts, Geofabrik Coverage & UTM SRIDs
- **Non-district exclusions (`555`, `888`, `999`):**
  - `ID82` (Maluku Utara): 118 minus 2 (`ID8205999` Hutan, `ID8271999` Hutan Lindung) = **116**.
  - All other 9 provinces (`51`, `52`, `53`, `61`, `62`, `63`, `64`, `65`, `81`): `0` non-district exclusions.
- **Geofabrik `.poly` boundary check:**
  - `nusa-tenggara.poly` covers **57/57** Bali districts (including Nusa Penida), **116/116** NTB districts (including Sumbawa), and **307/307** NTT districts (including Alor, Rote, and Sabu) at 100% (`0` Bali districts lie in `java.poly`).
  - `kalimantan.poly` covers **618/618** Kalimantan districts (`61`–`65`, including Derawan; only tiny Malaysian border slivers in Long Apari `99.90%`, Krayan Timur `99.10%`, and Lumbis Ogong `99.98%` fall outside).
  - `maluku.poly` covers **234/234** Maluku + Maluku Utara valid districts (including Kepulauan Aru, Tanimbar, Morotai, and Sula) at 100%.
- **UTM SRIDs (`utm_srid`) & Geodesic Area Check:** Zero NULL `utm_srid` rows across all 1,332 kecamatan and all 22,961 active facilities. Every PostGIS `utm_srid` matches `calculate_utm_srid()` (`326xx` north of equator, `327xx` south of equator, zones 49–53):
  - `51`: `{32750: 57}` (max UTM vs `ST_Area(geography)` diff = `0.1011%` at Melaya `51.01.010`)
  - `52`: `{32750: 116}` (max diff = `0.0799%` at Alas `52.04.050`)
  - `53`: `{32750: 28, 32751: 279}` (max diff = `0.1859%` at Haharu `53.02.080`)
  - `61`: `{32649: 111, 32749: 63}` (max diff = `0.1396%` at Putussibau Selatan `61.08.080`)
  - `62`: `{32749: 82, 32750: 52, 32649: 1, 32650: 1}` (max diff = `0.1921%` at Kahayan Tengah `62.10.050`)
  - `63`: `{32750: 152}` (max diff = `0.1202%` at Tabunganen `63.04.010`)
  - `64`: `{32750: 59, 32650: 44}` (max diff = `0.1559%` at Long Apari `64.11.050`)
  - `65`: `{32650: 53}` (max diff = `0.0798%` at Betayau `65.03.030`)
  - `81`: `{32752: 92, 32753: 25, 32751: 1}` (max diff = `0.1921%` at Pp. Kur `81.72.010`)
  - `82`: `{32652: 68, 32752: 31, 32751: 17}` (max diff = `0.1919%` at Sulabesi Selatan `82.03.011`)
  - Maximum UTM vs `ST_Area(geography)` difference across all 1,332 kecamatan is **`0.1921%`** (`< 1%`).

---

## 3. WorldPop 2024 vs COD-PS 2020 Comparison

### Kabupaten/Kota with |Difference| > 15%

| Province | Code | Kabupaten / Kota | WorldPop 2024 | COD-PS 2020 | Diff (%) |
|---|---|---|---:|---:|---:|
| Bali (`51`) | `51.01` | Jembrana | 331,664 | 280,396 | +18.28% |
| Bali (`51`) | `51.03` | Badung | 573,462 | 695,009 | -17.49% |
| Bali (`51`) | `51.05` | Klungkung | 216,863 | 179,947 | +20.51% |
| Bali (`51`) | `51.06` | Bangli | 270,411 | 228,827 | +18.17% |
| Bali (`51`) | `51.07` | Karang Asem | 516,661 | 418,986 | +23.31% |
| Bali (`51`) | `51.08` | Buleleng | 828,227 | 665,534 | +24.45% |
| Bali (`51`) | `51.71` | Kota Denpasar | 754,991 | 977,578 | -22.77% |
| Nusa Tenggara Barat (`52`) | — | *(none)* | — | — | — |
| Nusa Tenggara Timur (`53`) | `53.01` | Sumba Barat | 152,433 | 131,704 | +15.74% |
| Nusa Tenggara Timur (`53`) | `53.14` | Rote Ndao | 151,143 | 179,171 | -15.64% |
| Nusa Tenggara Timur (`53`) | `53.16` | Sumba Tengah | 89,915 | 73,619 | +22.14% |
| Kalimantan Barat (`61`) | `61.01` | Sambas | 654,510 | 539,937 | +21.22% |
| Kalimantan Barat (`61`) | `61.02` | Bengkayang | 313,735 | 258,423 | +21.40% |
| Kalimantan Barat (`61`) | `61.04` | Mempawah | 314,267 | 265,065 | +18.56% |
| Kalimantan Barat (`61`) | `61.11` | Kayong Utara | 136,097 | 113,730 | +19.67% |
| Kalimantan Tengah (`62`) | `62.03` | Kapuas | 425,111 | 361,284 | +17.67% |
| Kalimantan Tengah (`62`) | `62.05` | Barito Utara | 158,749 | 131,381 | +20.83% |
| Kalimantan Tengah (`62`) | `62.07` | Lamandau | 101,947 | 80,973 | +25.90% |
| Kalimantan Tengah (`62`) | `62.08` | Seruyan | 167,737 | 204,275 | -17.89% |
| Kalimantan Tengah (`62`) | `62.11` | Gunung Mas | 144,464 | 116,772 | +23.71% |
| Kalimantan Selatan (`63`) | `63.72` | Kota Banjar Baru | 321,436 | 266,939 | +20.42% |
| Kalimantan Timur (`64`) | `64.02` | Kutai Barat | 179,840 | 149,731 | +20.11% |
| Kalimantan Timur (`64`) | `64.04` | Kutai Timur | 451,305 | 376,199 | +19.96% |
| Kalimantan Timur (`64`) | `64.09` | Penajam Paser Utara | 187,282 | 158,750 | +17.97% |
| Kalimantan Timur (`64`) | `64.11` | Mahakam Hulu | 33,944 | 26,639 | +27.42% |
| Kalimantan Utara (`65`) | `65.02` | Bulungan | 157,821 | 133,869 | +17.89% |
| Maluku (`81`) | `81.02` | Maluku Tenggara | 122,885 | 100,560 | +22.20% |
| Maluku (`81`) | `81.03` | Maluku Tengah | 436,481 | 375,414 | +16.27% |
| Maluku (`81`) | `81.06` | Seram Bagian Barat | 220,864 | 172,740 | +27.86% |
| Maluku (`81`) | `81.07` | Seram Bagian Timur | 139,540 | 113,036 | +23.45% |
| Maluku (`81`) | `81.08` | Maluku Barat Daya | 85,437 | 73,476 | +16.28% |
| Maluku (`81`) | `81.09` | Buru Selatan | 79,775 | 62,452 | +27.74% |
| Maluku (`81`) | `81.71` | Kota Ambon | 361,060 | 463,731 | -22.14% |
| Maluku Utara (`82`) | `82.01` | Halmahera Barat | 137,097 | 117,361 | +16.82% |
| Maluku Utara (`82`) | `82.07` | Pulau Morotai | 77,511 | 67,319 | +15.14% |
| Maluku Utara (`82`) | `82.72` | Kota Tidore Kepulauan | 118,419 | 100,555 | +17.77% |

Differences reflect the 2020-to-2024 census/projection gap (including post-SP2020 adjustments and growth in Banjarbaru `+20.42%`, Penajam Paser Utara `+17.97%`, Kutai Timur `+19.96%`, and Maluku island regencies) plus WorldPop Global2's building-constrained dasymetric allocation trimming older high urban projections in Kota Denpasar (`-22.77%`), Badung (`-17.49%`), and Kota Ambon (`-22.14%`).

---

## 4. Facility Counts per Pillar & Scoring Behavior

| Province | `lifeline_health` | `education` | `urban_livability` | `mobility_connectivity` | Total Active | Zero-Facility Kecamatan |
|---|---:|---:|---:|---:|---:|---:|
| Bali (`51`) | 443 | 650 | 487 | 898 | 2,478 | 2 |
| Nusa Tenggara Barat (`52`) | 879 | 6,807 | 494 | 456 | 8,636 | 1 |
| Nusa Tenggara Timur (`53`) | 746 | 1,793 | 655 | 293 | 3,487 | 90 |
| Kalimantan Barat (`61`) | 130 | 396 | 187 | 82 | 795 | 89 |
| Kalimantan Tengah (`62`) | 184 | 435 | 162 | 67 | 848 | 52 |
| Kalimantan Selatan (`63`) | 450 | 1,363 | 232 | 177 | 2,222 | 10 |
| Kalimantan Timur (`64`) | 704 | 1,523 | 362 | 372 | 2,961 | 9 |
| Kalimantan Utara (`65`) | 102 | 222 | 68 | 32 | 424 | 12 |
| Maluku (`81`) | 172 | 298 | 124 | 88 | 682 | 62 |
| Maluku Utara (`82`) | 59 | 228 | 93 | 48 | 428 | 26 |

### Scoring Coverage Breakdown
- Under the J1a2 province-scaled availability gate, each scored facility type must have at least `N` classified OSM records in the province (`N` = number of kecamatan in that province), and a pillar must have `>= 2` available scored types to compute a pillar score.
- Across all 10 provinces, `lifeline_health` has at most 1 scored type meeting `>= N` (`puskesmas_kelurahan` in `52`, `63`, `64`; `puskesmas_kecamatan` and `pos_damkar` are `< N` everywhere), so `health_score` is `NULL` (`cakupan data rendah`) in all 10 provinces.
- In `education`:
  - **Bali (`51`, N=57):** all 4 types (`TK`: 66, `SD`: 220, `SMP`: 63, `SMA`: 73) are `available` -> composite computed for 37 `memadai` kecamatan.
  - **Nusa Tenggara Barat (`52`, N=116):** all 4 types (`TK`: 408, `SD`: 948, `SMP`: 300, `SMA`: 251) are `available` -> composite computed for 84 `memadai` kecamatan.
  - **Kalimantan Selatan (`63`, N=152):** all 4 types (`TK`: 155, `SD`: 624, `SMP`: 180, `SMA`: 169) are `available` -> composite computed for 110 `memadai` kecamatan.
  - **Kalimantan Timur (`64`, N=103):** all 4 types (`TK`: 325, `SD`: 577, `SMP`: 229, `SMA`: 209) are `available` -> composite computed for 72 `memadai` kecamatan.
  - **NTT (`53`, N=307), Kalteng (`62`, N=136), Kaltara (`65`, N=53):** only 1 scored type (`sekolah_dasar`) meets `>= N` (`421`, `194`, `84`).
  - **Kalbar (`61`, N=174), Maluku (`81`, N=118), Maluku Utara (`82`, N=116):** 0 scored types meet `>= N`.
  - Consequently, in those 6 provinces (`53`, `61`, `62`, `65`, `81`, `82`), `education_score` and `composite_livability_score` remain `NULL` (`Data tidak memadai` / `cakupan data rendah`).

---

## 5. Spot Checks (Well-Known Urban Kecamatan)

| Kecamatan | City / Province | Code (`kemendagri_code` / `cod_ab_pcode`) | UTM SRID | UTM vs Geog Area Diff | Population (WorldPop 2024) | Active Facilities | `osm_coverage` (`mapped_sd / req_sd`) | Composite Score |
|---|---|---|---:|---:|---:|---:|---|---:|
| **Pontianak Kota** | Kota Pontianak, Kalimantan Barat (`61`) | `61.71.031` / `ID6171031` | `32749` | `0.0073%` | 162,174 | 58 | `memadai` (`3 / 102`) | `NULL` (0 province types `>= 174`) |
| **Samarinda Ulu** | Kota Samarinda, Kalimantan Timur (`64`) | `64.72.050` / `ID6472050` | `32750` | `0.0796%` | 144,160 | 164 | `memadai` (`24 / 91`) | `34.29` (`education`) |
| **Denpasar Selatan** | Kota Denpasar, Bali (`51`) | `51.71.010` / `ID5171010` | `32750` | `0.0143%` | 237,783 | 194 | `memadai` (`20 / 149`) | `11.75` (`education`) |
| **Kota Raja** | Kota Kupang, NTT (`53`) | `53.71.031` / `ID5371031` | `32751` | `0.0696%` | 49,871 | 38 | `memadai` (`7 / 32`) | `NULL` (1 province type `>= 307`) |
| **Sirimau** | Kota Ambon, Maluku (`81`) | `81.71.020` / `ID8171020` | `32752` | `0.0612%` | 148,531 | 86 | `memadai` (`5 / 93`) | `NULL` (0 province types `>= 118`) |

---

## 6. OSM Coverage Gate Summary

| Province | Code | Total Kecamatan | Local Gate `tidak_memadai` (SD=0) | Local Gate `memadai` (SD>=1) | Province Scored Types `>= N` | Scored Composite (Min / Median / Max) |
|---|---|---:|---:|---:|---|---|
| Bali | `51` | 57 | 20 | 37 | 4 (`TK`: 66, `SD`: 220, `SMP`: 63, `SMA`: 73) | 0.33 / 6.48 / 29.22 |
| Nusa Tenggara Barat | `52` | 116 | 32 | 84 | 5 (`TK`: 408, `SD`: 948, `SMP`: 300, `SMA`: 251, `PuskKel`: 176) | 1.36 / 19.27 / 72.71 |
| Nusa Tenggara Timur | `53` | 307 | 198 | 109 | 1 (`SD`: 421) | `NULL` (`< 2` types in pillar) |
| Kalimantan Barat | `61` | 174 | 130 | 44 | 0 | `NULL` (`< 2` types) |
| Kalimantan Tengah | `62` | 136 | 89 | 47 | 1 (`SD`: 194) | `NULL` (`< 2` types in pillar) |
| Kalimantan Selatan | `63` | 152 | 42 | 110 | 5 (`TK`: 155, `SD`: 624, `SMP`: 180, `SMA`: 169, `PuskKel`: 167) | 0.00 / 17.73 / 73.48 |
| Kalimantan Timur | `64` | 103 | 31 | 72 | 5 (`TK`: 325, `SD`: 577, `SMP`: 229, `SMA`: 209, `PuskKel`: 211) | 1.78 / 21.45 / 87.50 |
| Kalimantan Utara | `65` | 53 | 21 | 32 | 1 (`SD`: 84) | `NULL` (`< 2` types in pillar) |
| Maluku | `81` | 118 | 93 | 25 | 0 | `NULL` (`< 2` types) |
| Maluku Utara | `82` | 116 | 104 | 12 | 0 | `NULL` (`< 2` types) |

### Per-Type Zero Counts (Kecamatan with 0 Active OSM Records)

| Province | `taman_kanak_kanak` | `sekolah_dasar` | `sekolah_menengah_pertama` | `sekolah_menengah_atas` | `puskesmas_kelurahan` | `puskesmas_kecamatan` | `pos_damkar` |
|---|---:|---:|---:|---:|---:|---:|---:|
| Bali (`51`, n=57) | 39 | 20 | 28 | 28 | 32 | 57 | 46 |
| Nusa Tenggara Barat (`52`, n=116) | 56 | 32 | 39 | 18 | 45 | 116 | 114 |
| Nusa Tenggara Timur (`53`, n=307) | 232 | 198 | 219 | 201 | 219 | 304 | 303 |
| Kalimantan Barat (`61`, n=174) | 161 | 130 | 142 | 156 | 155 | 174 | 171 |
| Kalimantan Tengah (`62`, n=136) | 111 | 89 | 97 | 104 | 96 | 136 | 133 |
| Kalimantan Selatan (`63`, n=152) | 85 | 43 | 78 | 51 | 64 | 152 | 143 |
| Kalimantan Timur (`64`, n=103) | 45 | 31 | 39 | 45 | 33 | 103 | 85 |
| Kalimantan Utara (`65`, n=53) | 44 | 30 | 30 | 38 | 28 | 53 | 51 |
| Maluku (`81`, n=118) | 111 | 96 | 98 | 97 | 93 | 118 | 116 |
| Maluku Utara (`82`, n=116) | 70 | 104 | 104 | 89 | 102 | 116 | 113 |

### Known Limitation
As in Java (`32`–`36`), Sumatra (`11`–`19`, `21`), Sulawesi (`71`–`76`), and Papua (`91`–`96`), OSM facility mapping outside DKI Jakarta varies widely: 760 of 1,332 kecamatan across these 10 provinces have `0` mapped `sekolah_dasar` (`tidak_memadai`), and 6 of 10 provinces (`53`, `61`, `62`, `65`, `81`, `82`) have `< 2` facility types meeting the province-wide `>= N` threshold within any single pillar. Even kecamatan passing the local `sekolah_dasar >= 1` gate (`memadai`) frequently experience OSM under-counting relative to real facilities and must be interpreted alongside `osm_coverage`.
