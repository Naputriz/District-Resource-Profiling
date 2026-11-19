# Multi-Region Support (Java & Expansion Guide)

Java provinces `31`–`36` have been live on `https://drp.digilabui.cloud` (fallback `https://drp.digilabui.workers.dev`) since 17 Nov 2026 (commit `9ee346d`, `ACTIVE_PROVINCES=31,32,33,34,35,36`).

---

## 1. Regions & Current Status

| Code | Province | Status | Kecamatan | Scored (`memadai`) | Gated (`tidak_memadai`) | Population Source |
|---|---|---|---:|---:|---:|---|
| `11` | Aceh | **Staging** | 289 | 64 | 225 | WorldPop R2025A 2024 (model estimate) |
| `12` | Sumatera Utara | **Staging** | 449 | 89 | 360 | WorldPop R2025A 2024 (model estimate) |
| `13` | Sumatera Barat | **Staging** | 179 | 75 | 104 | WorldPop R2025A 2024 (model estimate) |
| `14` | Riau | **Staging** | 169 | 62 | 107 | WorldPop R2025A 2024 (model estimate) |
| `15` | Jambi | **Staging** | 141 | 104 | 37 | WorldPop R2025A 2024 (model estimate) |
| `16` | Sumatera Selatan | **Staging** | 236 | 62 | 174 | WorldPop R2025A 2024 (model estimate) |
| `17` | Bengkulu | **Staging** | 128 | 60 | 68 | WorldPop R2025A 2024 (model estimate) |
| `18` | Lampung | **Staging** | 228 | 69 | 159 | WorldPop R2025A 2024 (model estimate) |
| `19` | Kepulauan Bangka Belitung | **Staging** | 47 | 20 | 27 | WorldPop R2025A 2024 (model estimate) |
| `21` | Kepulauan Riau | **Staging** | 70 | 27 | 43 | WorldPop R2025A 2024 (model estimate) |
| `31` | DKI Jakarta | **Active** | 44 | 44 | 0 | BPS 2024 |
| `32` | Jawa Barat | **Active** | 627 | 321 | 306 | WorldPop R2025A 2024 (model estimate) |
| `33` | Jawa Tengah | **Active** | 573 | 288 | 285 | WorldPop R2025A 2024 (model estimate) |
| `34` | DI Yogyakarta | **Active** | 78 | 66 | 12 | WorldPop R2025A 2024 (model estimate) |
| `35` | Jawa Timur | **Active** | 666 | 327 | 339 | WorldPop R2025A 2024 (model estimate) |
| `36` | Banten | **Active** | 155 | 63 | 92 | WorldPop R2025A 2024 (model estimate) |
| `51` | Bali | **Staging** | 57 | 37 | 20 | WorldPop R2025A 2024 (model estimate) |
| `52` | Nusa Tenggara Barat | **Staging** | 116 | 84 | 32 | WorldPop R2025A 2024 (model estimate) |
| `53` | Nusa Tenggara Timur | **Staging** | 307 | 109 | 198 | WorldPop R2025A 2024 (model estimate) |
| `61` | Kalimantan Barat | **Staging** | 174 | 44 | 130 | WorldPop R2025A 2024 (model estimate) |
| `62` | Kalimantan Tengah | **Staging** | 136 | 47 | 89 | WorldPop R2025A 2024 (model estimate) |
| `63` | Kalimantan Selatan | **Staging** | 152 | 110 | 42 | WorldPop R2025A 2024 (model estimate) |
| `64` | Kalimantan Timur | **Staging** | 103 | 72 | 31 | WorldPop R2025A 2024 (model estimate) |
| `65` | Kalimantan Utara | **Staging** | 53 | 32 | 21 | WorldPop R2025A 2024 (model estimate) |
| `71` | Sulawesi Utara | **Staging** | 171 | 92 | 79 | WorldPop R2025A 2024 (model estimate) |
| `72` | Sulawesi Tengah | **Staging** | 175 | 38 | 137 | WorldPop R2025A 2024 (model estimate) |
| `73` | Sulawesi Selatan | **Staging** | 307 | 168 | 139 | WorldPop R2025A 2024 (model estimate) |
| `74` | Sulawesi Tenggara | **Staging** | 222 | 74 | 148 | WorldPop R2025A 2024 (model estimate) |
| `75` | Gorontalo | **Staging** | 77 | 6 | 71 | WorldPop R2025A 2024 (model estimate) |
| `76` | Sulawesi Barat | **Staging** | 69 | 10 | 58 *(+1 zero-pop)* | WorldPop R2025A 2024 (model estimate) |
| `81` | Maluku | **Staging** | 118 | 25 | 93 | WorldPop R2025A 2024 (model estimate) |
| `82` | Maluku Utara | **Staging** | 116 | 12 | 104 | WorldPop R2025A 2024 (model estimate) |
| `91` | Papua | **Staging** | 97 | 31 | 66 | WorldPop R2025A 2024 (model estimate) |
| `92` | Papua Barat | **Staging** | 78 | 40 | 38 | WorldPop R2025A 2024 (model estimate) |
| `93` | Papua Selatan | **Staging** | 69 | 22 | 47 | WorldPop R2025A 2024 (model estimate) |
| `94` | Papua Tengah | **Staging** | 73 | 19 | 54 | WorldPop R2025A 2024 (model estimate) |
| `95` | Papua Pegunungan | **Staging** | 185 | 69 | 112 *(+4 zero-pop)* | WorldPop R2025A 2024 (model estimate) |
| `96` | Papua Barat Daya | **Staging** | 99 | 60 | 39 | WorldPop R2025A 2024 (model estimate) |

Total served across Java: **2,143 kecamatan** (1,109 scored, 1,034 gated). Sumatra in staging: **1,936 kecamatan** (`memadai`: 632; `tidak_memadai`: 1,304; provinces `13`, `15`, `21` have `>= 2` province-available scored types for composite calculation). Bali & Nusa Tenggara in staging: **480 kecamatan** (`memadai`: 230; `tidak_memadai`: 250; provinces `51`, `52` compute composites). Kalimantan in staging: **618 kecamatan** (`memadai`: 305; `tidak_memadai`: 313; provinces `63`, `64` compute composites). Sulawesi in staging: **1,021 kecamatan** (`memadai`: 388; `tidak_memadai`: 632; 1 zero-population island kecamatan `76.04.023`; provinces `71`, `73` compute composites). Maluku in staging: **234 kecamatan** (`memadai`: 37; `tidak_memadai`: 197; 0 reach `>= 2` scored types). Papua in staging: **601 kecamatan** (`memadai`: 241; `tidak_memadai`: 356; 4 zero-population highland kecamatan in `95`; 0 reach `>= 2` scored types). **All 38 Indonesian provinces (`7,033` kecamatan total) are loaded in staging.**

---

## 2. Data Sources & Licences

Raw downloads for provinces `32`–`36` and outer islands are stored outside Git under `/mnt/data/rpl/data_raw/`. Exact URLs, download dates, byte sizes, and SHA-256 hashes are recorded in [`pipeline/data/sources/REGION_SOURCES.md`](../pipeline/data/sources/REGION_SOURCES.md).

| Layer | DKI Jakarta (`31`) | Java Provinces (`32`–`36`) | Licence |
|---|---|---|---|
| **Boundaries** | `SakifAbdillah/jakartaKecamatanGeoJSON` (BPS / Kemendagri) | HDX COD-AB Indonesia (`cod-ab-idn`, layer `idn_admin3`, BPS / BIG via OCHA ROAP) | DKI: Public Domain / ODbL<br>32–36: **CC BY-IGO** |
| **Population** | BPS Provinsi DKI Jakarta 2024 (*Statistik Daerah 2024*) | WorldPop Global2 constrained 100 m (`G2_CN_POP_R25A_100m`, release R2025A, 2024) | DKI: Government Open Data (BPS)<br>32–36: **CC BY 4.0** |
| **Public Facilities** | OpenStreetMap via Overpass API (`2026-10-14`, 14,496 active facilities) | OpenStreetMap via Geofabrik PBFs (`java-latest.osm.pbf`, `sumatra-latest.osm.pbf`, `nusa-tenggara-latest.osm.pbf`, `kalimantan-latest.osm.pbf`, `sulawesi-latest.osm.pbf`, `maluku-latest.osm.pbf`, `papua-latest.osm.pbf`) | **ODbL 1.0** |
| **Standards** | SNI 03-1733-2004 (16 facility standards) | SNI 03-1733-2004 (same 16 standards) | BSN |

### District Codes & Geometry Notes
- **Non-district exclusion:** COD-AB `idn_admin3` includes water/forest polygons with `adm3_pcode` suffixes `555`, `888`, or `999` (e.g., `ID3175888` Danau Sunter, `ID3288888` Waduk Cirata, `ID3399999` Hutan, `ID3522888` Perairan). These are excluded during loading.
- **Unambiguous codes:** DKI `adm3_pcode` values all end in `0` and map 44/44 to `PP.KK.CC` (e.g., `ID3171090` -> `31.71.09`). Outside DKI, split kecamatan end in non-zero digits (`ID3273141` Antapani vs `ID3273142` Mandalajati), so `kecamatan.cod_ab_pcode` stores `IDPPKKDDD`, `kecamatan.bps_code` stores `PPKKDDD`, and `kecamatan.kemendagri_code` stores `PP.KK.DDD`.
- **Map GeoJSON:** Simplified per-province boundary files live in `frontend/data/boundaries/<code>_kecamatan.geojson` (kept under 3 MB each).
- **UTM SRID:** Every `kecamatan`, `kabupaten_kota`, `provinces`, and `public_facilities` row computes its per-row `utm_srid` via `compute_utm_srid()` (`32748` for UTM 48S, `32749` for 49S, `32750` for east Jawa Timur 50S). Cross-zone blank-spot queries pre-filter in WGS84 and reproject facilities to the district's `utm_srid`.

---

## 3. Population Estimation & BPS Check

For provinces `32`–`36`, kecamatan population is computed by [`compute_worldpop_zonal_sums()`](../pipeline/load_region.py) over the WorldPop 100 m GeoTIFF:
- Clips pixels strictly inside each COD-AB polygon using `rasterio.mask.mask(..., crop=True, filled=False, all_touched=False)` (falling back to `all_touched=True` only if 0 valid pixels intersect a tiny polygon) so adjacent kecamatan never double-count shared pixels.
- Sums positive finite non-nodata pixel values and rounds to an integer.
- Marks `population_source = 'WorldPop R2025A 2024 (model estimate)'` and `population_verification_status = 'model_estimate'`. DKI Jakarta (`31`) keeps its BPS 2024 values untouched.

### Check Against HDX COD-PS 2020
WorldPop 2024 province totals were checked against HDX `cod-ps-idn` (2020 admin-1 and admin-2 tables):

| Province | Code | WorldPop 2024 | COD-PS 2020 | Diff (%) | Kab/Kota \|Diff\| > 15% |
|---|---|---:|---:|---:|---:|
| Jawa Barat | `32` | 50,352,580 | 49,565,166 | +1.59% | 1 (Kab. Bekasi `-15.05%`) |
| Jawa Tengah | `33` | 38,175,724 | 34,738,244 | +9.90% | 7 (Cilacap, Banjarnegara, Kebumen, Wonosobo, Sragen, Pemalang, Tegal: `+15.40%` to `+18.31%`) |
| DI Yogyakarta | `34` | 3,850,140 | 3,919,197 | -1.76% | 0 |
| Jawa Timur | `35` | 42,527,064 | 39,955,941 | +6.43% | 1 (Kab. Lamongan `+16.76%`) |
| Banten | `36` | 12,403,015 | 12,895,258 | -3.82% | 1 (Kota Tangerang Selatan `-17.50%`) |
| Aceh | `11` | 5,509,970 | 5,388,093 | +2.26% | 2 (Kota Sabang `+24.25%`, Kota Subulussalam `+17.46%`) |
| Sumatera Utara | `12` | 15,454,553 | 14,798,404 | +4.43% | 3 (Toba Samosir `+16.68%`, Simalungun `+16.82%`, Nias Selatan `+15.08%`) |
| Sumatera Barat | `13` | 5,789,033 | 5,545,706 | +4.39% | 0 |
| Riau | `14` | 6,677,512 | 6,951,217 | -3.94% | 2 (Pelalawan `-17.96%`, Rokan Hulu `-18.27%`) |
| Jambi | `15` | 3,699,555 | 3,604,186 | +2.65% | 1 (Batang Hari `+17.45%`) |
| Sumatera Selatan | `16` | 8,857,044 | 8,600,765 | +2.98% | 2 (OKU Selatan `+16.27%`, Empat Lawang `+38.34%`) |
| Bengkulu | `17` | 2,086,875 | 1,994,349 | +4.64% | 0 |
| Lampung | `18` | 9,323,118 | 8,534,849 | +9.24% | 2 (Lampung Tengah `+18.31%`, Mesuji `+15.09%`) |
| Kep. Bangka Belitung | `19` | 1,516,986 | 1,469,809 | +3.21% | 0 |
| Kepulauan Riau | `21` | 2,140,871 | 2,309,529 | -7.30% | 1 (Kota Batam `-16.05%`) |
| Bali | `51` | 4,517,203 | 4,414,431 | +2.33% | 7 (Jembrana `+18.28%`, Badung `-17.49%`, Klungkung `+20.51%`, Bangli `+18.17%`, Karangasem `+23.31%`, Buleleng `+24.45%`, Kota Denpasar `-22.77%`) |
| Nusa Tenggara Barat | `52` | 5,561,107 | 5,225,915 | +6.41% | 0 |
| Nusa Tenggara Timur | `53` | 5,569,724 | 5,513,402 | +1.02% | 3 (Sumba Barat `+15.74%`, Rote Ndao `-15.64%`, Sumba Tengah `+22.14%`) |
| Kalimantan Barat | `61` | 5,649,973 | 5,104,900 | +10.68% | 4 (Sambas `+21.22%`, Bengkayang `+21.40%`, Mempawah `+18.56%`, Kayong Utara `+19.67%`) |
| Kalimantan Tengah | `62` | 2,785,265 | 2,686,252 | +3.69% | 5 (Kapuas `+17.67%`, Barito Utara `+20.83%`, Lamandau `+25.90%`, Seruyan `-17.89%`, Gunung Mas `+23.71%`) |
| Kalimantan Selatan | `63` | 4,254,599 | 4,268,610 | -0.33% | 1 (Kota Banjar Baru `+20.42%`) |
| Kalimantan Timur | `64` | 3,920,326 | 3,664,673 | +6.98% | 4 (Kutai Barat `+20.11%`, Kutai Timur `+19.96%`, Penajam Paser Utara `+17.97%`, Mahakam Hulu `+27.42%`) |
| Kalimantan Utara | `65` | 729,295 | 708,352 | +2.96% | 1 (Bulungan `+17.89%`) |
| Sulawesi Utara | `71` | 2,735,176 | 2,512,942 | +8.84% | 2 (Minahasa Selatan `+17.89%`, Boltim `+26.80%`) |
| Sulawesi Tengah | `72` | 3,074,487 | 3,081,720 | -0.23% | 1 (Morowali `+36.12%`) |
| Sulawesi Selatan | `73` | 9,484,018 | 8,888,762 | +6.70% | 4 (Jeneponto `+15.24%`, Maros `+16.29%`, Tana Toraja `+22.84%`, Toraja Utara `+15.96%`) |
| Sulawesi Tenggara | `74` | 2,732,281 | 2,703,466 | +1.07% | 3 (Buton `+16.65%`, Buton Tengah `+26.68%`, Buton Selatan `+24.34%`) |
| Gorontalo | `75` | 1,222,007 | 1,186,261 | +3.01% | 1 (Gorontalo Utara `+15.44%`) |
| Sulawesi Barat | `76` | 1,482,459 | 1,378,110 | +7.57% | 0 |
| Maluku | `81` | 1,900,373 | 1,787,087 | +6.34% | 7 (Maluku Tenggara `+22.20%`, Maluku Tengah `+16.27%`, SBB `+27.86%`, SBT `+23.45%`, MBD `+16.28%`, Buru Selatan `+27.74%`, Kota Ambon `-22.14%`) |
| Maluku Utara | `82` | 1,329,350 | 1,252,317 | +6.15% | 3 (Halmahera Barat `+16.82%`, Pulau Morotai `+15.14%`, Kota Tidore Kepulauan `+17.77%`) |
| Papua | `91` | 1,055,660 | 849,146 | +24.32% | 5 (Jayapura `+36.98%`, Kep. Yapen `+20.40%`, Supiori `+15.34%`, Mamberamo Raya `+69.89%`, Kota Jayapura `+36.85%`) |
| Papua Barat | `92` | 536,233 | 473,143 | +13.33% | 5 (Manokwari `+15.73%`, Teluk Bintuni `+41.03%`, Teluk Wondama `+27.89%`, Kaimana `-27.51%`, Manokwari Selatan `+51.54%`) |
| Papua Selatan | `93` | 547,458 | 500,577 | +9.37% | 2 (Mappi `+18.16%`, Asmat `+21.09%`) |
| Papua Tengah | `94` | 1,447,029 | 995,197 | +45.40% | 7 (Nabire `+20.83%`, Puncak Jaya `+82.68%`, Paniai `+33.75%`, Mimika `+50.90%`, Dogiyai `+24.11%`, Intan Jaya `+176.81%`, Deiyai `+37.76%`) |
| Papua Pegunungan | `95` | 1,429,309 | 1,048,155 | +36.36% | 4 (Jayawijaya `+43.38%`, Yahukimo `+84.16%`, Tolikara `+42.83%`, Yalimo `+48.50%`) |
| Papua Barat Daya | `96` | 591,403 | 512,881 | +15.31% | 2 (Sorong `+29.94%`, Tambrauw `+85.00%`) |

Differences reflect (1) 4 years of growth plus post-2020 census revisions between COD-PS 2020 and WorldPop 2024, and (2) WorldPop's building-constrained dasymetric allocation, which trims older high peri-urban projections in Bekasi and Tangerang Selatan. See [`pipeline/data/regions/JAVA_LOAD_REPORT.md`](../pipeline/data/regions/JAVA_LOAD_REPORT.md) for the full breakdown.

---

## 4. OSM Coverage Gate & Known Limitation

Outside DKI Jakarta, OpenStreetMap facility coverage is uneven. Rather than reporting 0% compliance where mapping is missing, the scoring engine applies two availability gates on top of the existing SNI 03-1733-2004 rules without altering any scoring formula:

1. **Province-scaled facility threshold:** A facility type must have at least `N` classified records in the province (`N` = number of kecamatan in that province: `44` for DKI, `627` for Jabar, `573` for Jateng, `78` for DIY, `666` for Jatim, `155` for Banten) to be marked `available`; otherwise it is `insufficient` and excluded from pillar scoring.
   - Outside DKI, `puskesmas_kecamatan` (1–8 records) and `pos_damkar` (17–43 records) are `insufficient` in every Java province, and `puskesmas_kelurahan` is `insufficient` in Jabar (414), Jateng (286), Jatim (423), and Banten (67). Because `lifeline_health` then has `< 2` available scored types, `health_score` is `NULL` (`cakupan data rendah`) and the composite index uses `education` alone (except Banten where `sekolah_menengah_atas` at `151 < 155` is also excluded, leaving 3 education types).
2. **Kecamatan `sekolah_dasar` coverage gate:** Any kecamatan with population `>= 1,600` (requiring `>= 1` primary school under SNI 03-1733-2004) and `0` mapped `sekolah_dasar` in OSM is flagged `osm_coverage.status = "tidak_memadai"`:
   - Count-based entries in `metrics_payload` receive `data_availability = "insufficient_local"`, `compliance_pct = null`, and `deficit = null` (keeping `existing` and `required`).
   - Pillar and composite scores are stored as `NULL` (never `0`), displayed as `"Data tidak memadai"`, and excluded from rankings and province averages.
   - Per-kecamatan `osm_coverage` (`status`, `mapped_sd`, `required_sd`, `rule`) is persisted in `district_compliance_scores.coverage` and returned by the API.

### Per-Province Gate Summary

| Province | Total | Gated (`tidak_memadai`) | Scored (`memadai`) | Scored Composite (Min / Median / Max) | Active OSM Facilities |
|---|---:|---:|---:|---:|---:|
| DKI Jakarta (`31`) | 44 | 0 | 44 | 5.41 / 49.20 / 65.39 | 14,496 |
| Jawa Barat (`32`) | 627 | 306 | 321 | 0.23 / 6.07 / 84.86 | 18,983 |
| Jawa Tengah (`33`) | 573 | 285 | 288 | 0.23 / 7.26 / 75.42 | 12,543 |
| DI Yogyakarta (`34`) | 78 | 12 | 66 | 0.54 / 17.02 / 64.56 | 3,969 |
| Jawa Timur (`35`) | 666 | 339 | 327 | 0.40 / 6.59 / 71.77 | 13,423 |
| Banten (`36`) | 155 | 92 | 63 | 0.25 / 5.28 / 63.25 | 3,675 |
| Aceh (`11`) | 289 | 225 | 64 | `NULL` (1 type >= N) | 2,197 |
| Sumatera Utara (`12`) | 449 | 360 | 89 | `NULL` (0 types >= N) | 2,160 |
| Sumatera Barat (`13`) | 179 | 104 | 75 | 1.00 / 13.34 / 97.06 | 1,550 |
| Riau (`14`) | 169 | 107 | 62 | `NULL` (1 type >= N) | 2,177 |
| Jambi (`15`) | 141 | 37 | 104 | 0.71 / 21.88 / 100.00 | 1,348 |
| Sumatera Selatan (`16`) | 236 | 174 | 62 | `NULL` (0 types >= N) | 1,128 |
| Bengkulu (`17`) | 128 | 68 | 60 | `NULL` (1 type >= N) | 815 |
| Lampung (`18`) | 228 | 159 | 69 | `NULL` (0 types >= N) | 1,245 |
| Kep. Bangka Belitung (`19`) | 47 | 27 | 20 | `NULL` (1 type >= N) | 383 |
| Kepulauan Riau (`21`) | 70 | 43 | 27 | 0.00 / 16.28 / 88.33 | 1,506 |
| Bali (`51`) | 57 | 20 | 37 | 0.33 / 6.48 / 29.22 | 2,478 |
| Nusa Tenggara Barat (`52`) | 116 | 32 | 84 | 1.36 / 19.27 / 72.71 | 8,636 |
| Nusa Tenggara Timur (`53`) | 307 | 198 | 109 | `NULL` (1 type >= N) | 3,487 |
| Kalimantan Barat (`61`) | 174 | 130 | 44 | `NULL` (0 types >= N) | 795 |
| Kalimantan Tengah (`62`) | 136 | 89 | 47 | `NULL` (1 type >= N) | 848 |
| Kalimantan Selatan (`63`) | 152 | 42 | 110 | 0.00 / 17.73 / 73.48 | 2,222 |
| Kalimantan Timur (`64`) | 103 | 31 | 72 | 1.78 / 21.45 / 87.50 | 2,961 |
| Kalimantan Utara (`65`) | 53 | 21 | 32 | `NULL` (1 type >= N) | 424 |
| Sulawesi Utara (`71`) | 171 | 79 | 92 | 0.00 / 40.33 / 100.00 | 2,393 |
| Sulawesi Tengah (`72`) | 175 | 137 | 38 | `NULL` (0 types >= N) | 612 |
| Sulawesi Selatan (`73`) | 307 | 139 | 168 | 0.00 / 21.27 / 100.00 | 6,907 |
| Sulawesi Tenggara (`74`) | 222 | 148 | 74 | `NULL` (1 type >= N) | 1,423 |
| Gorontalo (`75`) | 77 | 71 | 6 | `NULL` (0 types >= N) | 211 |
| Sulawesi Barat (`76`) | 69 | 58 *(+1 zero-pop)* | 10 | `NULL` (0 types >= N) | 238 |
| Maluku (`81`) | 118 | 93 | 25 | `NULL` (0 types >= N) | 682 |
| Maluku Utara (`82`) | 116 | 104 | 12 | `NULL` (0 types >= N) | 428 |
| Papua (`91`) | 97 | 66 | 31 | `NULL` (0 types >= N) | 230 |
| Papua Barat (`92`) | 78 | 38 | 40 | `NULL` (0 types >= N) | 318 |
| Papua Selatan (`93`) | 69 | 47 | 22 | `NULL` (0 types >= N) | 68 |
| Papua Tengah (`94`) | 73 | 54 | 19 | `NULL` (0 types >= N) | 111 |
| Papua Pegunungan (`95`) | 185 | 112 *(+4 zero-pop)* | 69 | `NULL` (0 types >= N) | 304 |
| Papua Barat Daya (`96`) | 99 | 39 | 60 | `NULL` (0 types >= N) | 201 |

### Known Limitation
Even kecamatan that pass the `sekolah_dasar >= 1` gate (`memadai`) may still be heavily under-counted in OpenStreetMap—for example, a kecamatan with 50 real primary schools where only 1 or 2 are mapped in OSM still passes the local gate. Because OSM completeness outside DKI Jakarta is uneven, compliance scores outside DKI are likely lower than actual on-the-ground facility availability and should always be interpreted alongside `osm_coverage` rather than as definitive proof of physical shortage.

---

## 5. `ACTIVE_PROVINCES` & Region Statuses

The backend environment variable `ACTIVE_PROVINCES` (comma-separated province codes, default `"31"`) controls which provinces are served by the API (`backend/app/core/config.py`, `backend/app/api/routers/regions.py`).

`GET /api/v1/regions` computes each province's `status` and `has_data` at request time (with a 60s in-process DB stats cache):
- **Active:** Listed in `ACTIVE_PROVINCES` **and** has `kecamatan` rows in PostgreSQL. Selectable in the header switcher; all district, facility, blank-spot, simulation, and chat endpoints work for it.
- **Staging:** Has `kecamatan` rows in PostgreSQL **but not** listed in `ACTIVE_PROVINCES`. Shown disabled in the UI; API endpoints return HTTP `404` (`"Data wilayah ini belum tersedia (rencana v1.1)"`).
- **Planned:** No `kecamatan` rows in PostgreSQL. Shown disabled in the UI; API endpoints return HTTP `404`.

---

## 6. How to Add a New Province or Island (`pipeline/load_region.py`)

`pipeline/load_region.py` includes a live-DB guard (`ensure_safe_database()`) that refuses to run against `district_profiling` unless `--allow-live` is explicitly passed. Always load and verify in staging first.

### Step 1: Prepare Raw Data & Metadata
1. Download the COD-AB boundaries, WorldPop 2024 raster (if not already present), Geofabrik `.osm.pbf` extract for the target island, and COD-PS 2020 reference CSVs into `/mnt/data/rpl/data_raw/`.
2. Record URL, download date, byte size, and SHA-256 in [`pipeline/data/sources/REGION_SOURCES.md`](../pipeline/data/sources/REGION_SOURCES.md).
3. Add the province entry to `SUPPORTED_PROVINCES` in `pipeline/load_region.py` (and `REGIONS_CATALOG` in `backend/app/api/routers/regions.py` when exposing it in the API).

### Step 2: Load into the Staging Database (`district_profiling_stage`)
1. Ensure staging schema migrations are applied:
   ```bash
   POSTGRES_DB=district_profiling_stage PYTHONPATH=. /mnt/data/rpl/og/.venv/bin/python pipeline/migrate_multiregion.py
   ```
2. Run a dry run first:
   ```bash
   POSTGRES_DB=district_profiling_stage REDIS_DB=1 PYTHONPATH=. /mnt/data/rpl/og/.venv/bin/python pipeline/load_region.py --province <code> --dry-run
   ```
3. Load boundaries, WorldPop population, OSM facilities, compliance scores, simplified GeoJSON (`frontend/data/boundaries/<code>_kecamatan.geojson`), and manifest (`pipeline/data/regions/<code>.json`):
   ```bash
   POSTGRES_DB=district_profiling_stage REDIS_DB=1 PYTHONPATH=. /mnt/data/rpl/og/.venv/bin/python pipeline/load_region.py --province <code>
   ```
   *(To re-score existing DB records without reloading polygons/facilities, pass `--rescore-only`.)*

### Step 3: Run Checks & Staging Tests
1. Verify kecamatan counts vs COD-AB, WorldPop totals vs COD-PS 2020, zero NULL `utm_srid`, OSM gate counts, spot checks, and confirm existing provinces (including DKI `31`) remain unchanged.
2. Run unit, integration, and system tests against `POSTGRES_DB=district_profiling_stage`, `REDIS_DB=1`, and `ACTIVE_PROVINCES` including the new code (see [`docs/TESTING.md`](TESTING.md)).

### Step 4: Promote to Live (`district_profiling`)
1. **Back up** the live `district_profiling` database (`pg_dump`) before making any changes.
2. **Migrate schema columns** on live (idempotent `ADD COLUMN IF NOT EXISTS` for `cod_ab_pcode`, `population_source`, `population_verification_status` on `kecamatan`, `coverage` on `district_compliance_scores`, and `utm_srid` / `compute_utm_srid()` via `pipeline/migrate_multiregion.py`).
3. **Copy data in a single transaction** from staging to live for the new provinces (`provinces`, `kabupaten_kota`, `kecamatan`, `public_facilities`, `district_compliance_scores`). Do not touch existing provinces, `app_users`, `chat_audit`, or `incident_logs`.
4. **Flush Redis scorecard cache** on the live Redis DB (`0`, keys `cache:compliance:scores:*`) so stale or empty scorecards are not served.
5. **Redeploy** from a clean `git archive` export (see [`deploy/cloudflare/README.md`](../deploy/cloudflare/README.md)):
   - Add the new province code(s) to `ACTIVE_PROVINCES` in `$DEPLOY_DIR/docker/.env`.
   - Rebuild and restart `backend` and `watchdog` (`--no-deps`).
   - If new `frontend/data/boundaries/<code>_kecamatan.geojson` files were added, redeploy the Cloudflare Worker (`npx wrangler deploy` from `deploy/cloudflare`).
6. Run a public smoke test against `https://drp.digilabui.cloud` (or `https://drp.digilabui.workers.dev`): check `/api/v1/regions`, a scored and a gated kecamatan, DKI unchanged, and chat.

---

## 7. What's Next

- **All 38 provinces loaded in staging:** Java (`31`–`36`, live), Sumatra (`11`–`19`, `21`), Bali & Nusa Tenggara (`51`–`53`), Kalimantan (`61`–`65`), Sulawesi (`71`–`76`), Maluku (`81`–`82`), and Papua (`91`–`96`) are loaded in `district_profiling_stage` using `load_region.py` and Geofabrik island PBFs. Promote to live via Step 4 when ready.
- **SNI 1733:2026:** Switch facility standards from `SNI 03-1733-2004` to `SNI 1733:2026` once the official BSN PDF is available.
- **Official facility counts:** Supplement or replace OSM counts with official ministry / BPS / Dinas facility registries to reduce under-counting outside DKI Jakarta.

---

## 8. Follow-Up Improvements

- **Light district list endpoint:** `GET /api/v1/districts?province_code=32` currently returns the full `metrics_payload` for all 627 kecamatan (~`3.4 MB`, ~`0.9 s` over the internet). Adding a light list endpoint (or `?include_metrics=false` option) without `metrics_payload` would speed up initial province switches and map choropleth rendering while fetching full `metrics_payload` only on district click (`GET /api/v1/districts/{code}`).
