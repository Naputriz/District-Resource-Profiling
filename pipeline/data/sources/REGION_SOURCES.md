# Regional Data Sources (Java Provinces 32–36)

All raw files are stored outside the repository under `/mnt/data/rpl/data_raw/` and are never committed to Git.

## 1. Administrative Boundaries (COD-AB Indonesia)

- **Dataset:** HDX "Indonesia - Subnational Administrative Boundaries" (`cod-ab-idn`)
- **Metadata Endpoint:** `https://data.humdata.org/api/3/action/package_show?id=cod-ab-idn`
- **File:** `idn_admin_boundaries.gdb.zip` (layer `idn_admin3`, EPSG:4326)
- **URL:** `https://data.humdata.org/dataset/84a1d98a-790b-4d66-9d14-bbfa48500802/resource/c740a308-0a63-46d6-ab15-b041e62eff58/download/idn_admin_boundaries.gdb.zip`
- **Download Date:** 2026-11-17
- **File Size:** 218,753,706 bytes
- **SHA-256:** `640c62398b19de310be321b83ccdd56c710cf796247028f453e172ff33a4e308`
- **Source / Attribution:** BPS / BIG via HDX (OCHA ROAP)
- **Licence:** Creative Commons Attribution for Intergovernmental Organisations (CC BY-IGO)
- **Code Mapping Notes:**
  - COD-AB `adm3_pcode` has format `ID` + 7 digits (`IDPPKKDDD`), where `PP` is province, `KK` is kabupaten/kota, and `DDD` is the 3-digit BPS-based subdistrict code.
  - Non-district water/forest polygons in `idn_admin3` have `adm3_pcode` ending in `555`, `888`, or `999` (e.g. `ID3175888` Danau Sunter, `ID3288888` Waduk Cirata, `ID3399999` Hutan, `ID3522888` Perairan) and are excluded when loading kecamatan.
  - On DKI Jakarta (`ID31`), all 44 kecamatan end in `0` and map 44/44 to `PP.KK.CC` (e.g. `ID3171090` -> `31.71.09`), with two minor name spacing variants (`Setia Budi` / `Setiabudi`, `Kali Deres` / `Kalideres`). Note that COD-AB uses Kemendagri city order for DKI (`71`=Selatan .. `75`=Utara) rather than `jakarta_demographics_bps.json`'s `bps_code`.
  - Outside DKI (`ID32`–`ID36`), split kecamatan carry non-zero 7th digits (`1`, `2`, e.g. `ID3273141` Antapani vs `ID3273142` Mandalajati; `ID3403051` Girisubo vs `ID3403050` Rongkop), so dropping the 7th digit is **not** exact (collides on 158 pairs in Jawa Barat, 38 in Jawa Tengah, 3 in DI Yogyakarta, 41 in Jawa Timur, 46 in Banten). Therefore, for provinces `32`–`36`, `kecamatan.cod_ab_pcode` stores the exact `adm3_pcode` (`IDPPKKDDD`), `kecamatan.bps_code` stores the 7-digit code (`PPKKDDD`), and `kecamatan.kemendagri_code` stores the unambiguous dotted code `PP.KK.DDD` (e.g. `32.73.141`).

## 2. Population Raster (WorldPop Global2 Constrained 100 m, R2025A, 2024)

- **Dataset:** WorldPop Global2 constrained 100 m, release R2025A, Indonesia, year 2024
- **Metadata Endpoint:** `https://hub.worldpop.org/rest/data/pop/G2_CN_POP_R25A_100m?iso3=IDN`
- **File:** `idn_pop_2024_CN_100m_R2025A_v1.tif` (EPSG:4326, float32, nodata `-99999.0`)
- **URL:** `https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2024/IDN/v1/100m/constrained/idn_pop_2024_CN_100m_R2025A_v1.tif`
- **Download Date:** 2026-11-17
- **File Size:** 169,081,457 bytes
- **SHA-256:** `458c20fa8a3e9b982e2eff5620b4e56438373c3eb00dd78a9093bf4b06c1668f`
- **Licence:** CC BY 4.0
- **Zonal Sum Method:** `rasterio.mask.mask(..., crop=True, filled=False, all_touched=False)` per kecamatan polygon (falling back to `all_touched=True` only if 0 valid pixels fall inside a tiny polygon), summing positive finite non-nodata pixel values and rounding to integer. Stored with `population_source='WorldPop R2025A 2024 (model estimate)'` and `population_verification_status='model_estimate'`.

## 3. Population Reference Check (COD-PS Indonesia 2020)

- **Dataset:** HDX "Indonesia - Subnational Population Statistics" (`cod-ps-idn`)
- **Metadata Endpoint:** `https://data.humdata.org/api/3/action/package_show?id=cod-ps-idn`
- **Files:**
  1. `idn_admpop_adm1_2020_v2.csv`
     - **URL:** `https://data.humdata.org/dataset/7e00297b-7b5b-4a98-932d-509f298fd8a8/resource/a7cabb5c-7a17-44ec-ae60-1481594e5857/download/idn_admpop_adm1_2020_v2.csv`
     - **Download Date:** 2026-11-17
     - **File Size:** 13,471 bytes
     - **SHA-256:** `4e5f3796a53a9b24353926325e8a310ed6ac4c2189c28dca572dc79e8ce77830`
  2. `idn_admpop_adm2_2020_v3.csv`
     - **URL:** `https://data.humdata.org/dataset/7e00297b-7b5b-4a98-932d-509f298fd8a8/resource/8f6f09d2-95f7-42dc-b6f1-aead319607f3/download/idn_admpop_adm2_2020_v3.csv`
     - **Download Date:** 2026-11-17
     - **File Size:** 175,539 bytes
     - **SHA-256:** `2069cd0719fe19d53537b7260289b9d3723fcc649d772952621d100e86c95ab3`

## 4. Public Facilities (OpenStreetMap Java PBF via Geofabrik)

- **Dataset:** Geofabrik Indonesia Java extract
- **File:** `java-latest.osm.pbf`
- **URL:** `https://download.geofabrik.de/asia/indonesia/java-latest.osm.pbf`
- **Download Date:** 2026-11-17
- **File Size:** 899,617,022 bytes
- **SHA-256:** `c8287c10a3c64dcd70d3713061f73d06533a68915af5a4087fba8f3e971bb3f6`
- **Licence:** Open Database License (ODbL 1.0), OpenStreetMap contributors
- **Extraction Method:** Two-pass `pyosmium` (`osmium.FileProcessor`) using `matching_query_groups()` + `classify_osm_element_auto()` + `deduplicate_facilities()` from `pipeline/osm_extractor.py`, matching the exact Overpass tag rules and `OSM_TAG_MAPPING.md` classification.
