# Regional Data Sources (All 38 Indonesian Provinces)

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

## 4. Public Facilities (OpenStreetMap PBFs via Geofabrik)

- **Licence:** Open Database License (ODbL 1.0), OpenStreetMap contributors
- **Extraction Method:** Two-pass `pyosmium` (`osmium.FileProcessor`) using `matching_query_groups()` + `classify_osm_element_auto()` + `deduplicate_facilities()` from `pipeline/osm_extractor.py`, matching the exact Overpass tag rules and `OSM_TAG_MAPPING.md` classification.

### 4a. Java Extract (`32`–`36`)
- **Dataset:** Geofabrik Indonesia Java extract
- **File:** `java-latest.osm.pbf`
- **URL:** `https://download.geofabrik.de/asia/indonesia/java-latest.osm.pbf`
- **Download Date:** 2026-11-17
- **File Size:** 899,617,022 bytes
- **SHA-256:** `c8287c10a3c64dcd70d3713061f73d06533a68915af5a4087fba8f3e971bb3f6`

### 4b. Sumatra & Kalimantan Extracts (`11`–`19`, `21`)
Polygon containment checks against Geofabrik's `.poly` boundaries (`sumatra.poly`, `kalimantan.poly`) showed that provinces `11`–`18` are 100% inside `sumatra.poly`, whereas Kepulauan Bangka Belitung (`19`, all 47 districts) lies 100% inside `kalimantan.poly` (`0` in `sumatra.poly`), and Kepulauan Riau (`21`) has 69 districts fully inside `sumatra.poly` plus Lingga (`ID2104030`) split 98.7% in `sumatra.poly` / 1.3% in `kalimantan.poly`. Both extracts are therefore recorded and used (`11`–`18` from Sumatra, `19` from Kalimantan, `21` from Sumatra + Kalimantan deduplicated by `source_id`).

1. `sumatra-latest.osm.pbf`
   - **URL:** `https://download.geofabrik.de/asia/indonesia/sumatra-latest.osm.pbf`
   - **Download Date:** 2026-11-17
   - **File Size:** 283,380,587 bytes
   - **MD5 (verified vs Geofabrik `.md5`):** `12af5954f512f1a716f71cae85917e48`
   - **SHA-256:** `4e507cc42d80334ffecb390082ba4bcfb49adbc8f6ad310e8b7f7d8fbdbe4295`
2. `kalimantan-latest.osm.pbf`
   - **URL:** `https://download.geofabrik.de/asia/indonesia/kalimantan-latest.osm.pbf`
   - **Download Date:** 2026-11-17 (completed 2026-11-18 04:30 WIB)
   - **File Size:** 147,669,343 bytes
   - **MD5 (verified vs Geofabrik `.md5`):** `64c2ecc785dd1d30f07dc49f3052eaab`
   - **SHA-256:** `3bf975cb9d6c9b45b92489ab13702bfc5a1791ee1d5218936c6ce9c3d1791a8a`

### 4c. Sulawesi & Maluku Extracts (`71`–`76`)
Polygon containment checks against Geofabrik's `.poly` boundaries (`sulawesi.poly`, `maluku.poly`, `kalimantan.poly`) showed that:
- Provinces `71` (Sulawesi Utara, including Sangihe and Talaud), `73` (Sulawesi Selatan, including Selayar), `74` (Sulawesi Tenggara, including Wakatobi), and `75` (Gorontalo) are 100% inside `sulawesi.poly`.
- Sulawesi Tengah (`72`) has 174/175 districts fully inside `sulawesi.poly` and 1 island district (`ID7211070` Bokan Kepulauan, Banggai Laut) split 94.11% inside `sulawesi.poly` / 5.89% inside `maluku.poly`. Therefore `72` loads from `sulawesi-latest.osm.pbf` + `maluku-latest.osm.pbf` (deduplicated by `source_id`).
- Sulawesi Barat (`76`) has 68/69 districts fully inside `sulawesi.poly` and 1 island district (`ID7604023` Balabalakang, Mamuju) 100% inside `kalimantan.poly` (`0%` in `sulawesi.poly`). Therefore `76` loads from `sulawesi-latest.osm.pbf` + `kalimantan-latest.osm.pbf` (reusing the Kalimantan PBF from Sumatra, deduplicated by `source_id`).

1. `sulawesi-latest.osm.pbf`
   - **URL:** `https://download.geofabrik.de/asia/indonesia/sulawesi-latest.osm.pbf`
   - **Download Date:** 2026-11-18
   - **File Size:** 158,434,470 bytes
   - **MD5 (verified vs Geofabrik `.md5`):** `ecf0c47aaf674899e39689ecaaaa7067`
   - **SHA-256:** `4b4c04f95c6084bec56d1e156c699a47401d825cd353fafc5abc02b2b473957c`
2. `maluku-latest.osm.pbf`
   - **URL:** `https://download.geofabrik.de/asia/indonesia/maluku-latest.osm.pbf`
   - **Download Date:** 2026-11-18
   - **File Size:** 26,811,086 bytes
   - **MD5 (verified vs Geofabrik `.md5`):** `eec9cf03cb57f8f6f4f7d48bd9f6f565`
   - **SHA-256:** `855e5dd98d2d2d9ea737aaab378a508968016e2b26de48ff840e50c6dfaf8dea`

### 4d. Papua Extract (`91`–`96`)
Polygon containment checks against Geofabrik's `papua.poly` confirmed that **all 601 districts** across all 6 Papua provinces (including Raja Ampat, Waigeo, Biak, Kepulauan Yapen, and Kolepom/Kimaam) are **100% inside `papua.poly`** (`0` districts outside). Therefore all 6 provinces load solely from `papua-latest.osm.pbf`.

1. `papua-latest.osm.pbf`
   - **URL:** `https://download.geofabrik.de/asia/indonesia/papua-latest.osm.pbf`
   - **Download Date:** 2026-11-18
   - **File Size:** 36,395,021 bytes
   - **MD5 (verified vs Geofabrik `.md5`):** `223fbb085a8c2d82510ac1a6a37e8844`
   - **SHA-256:** `b21087d85d5b828ceebfd04bcce5b4895a2ea12dcf6f4d58c683e622ae2c3052`

### 4e. COD-AB Papua 2-to-6 Province Reassignment (2022 Laws & Kepmendagri Codes)
HDX COD-AB `idn_admin1`/`idn_admin2`/`idn_admin3` still uses the pre-2022 2-province layout (`ID91 Papua Barat` with 13 kab/kota / 177 kecamatan, and `ID94 Papua` with 29 kab/kota / 424 kecamatan; total 42 kab/kota, 601 kecamatan, 0 non-district polygons). Every kabupaten/kota is assigned to its current post-2022 province per:
- **UU Nomor 14 Tahun 2022** (Pembentukan Provinsi **Papua Selatan**, `93`)
- **UU Nomor 15 Tahun 2022** (Pembentukan Provinsi **Papua Tengah**, `94`)
- **UU Nomor 16 Tahun 2022** (Pembentukan Provinsi **Papua Pegunungan**, `95`)
- **UU Nomor 29 Tahun 2022** (Pembentukan Provinsi **Papua Barat Daya**, `96`)
- Remaining parent provinces: **Papua** (`91`, 9 kab/kota) and **Papua Barat** (`92`, 7 kab).

`kecamatan.cod_ab_pcode` preserves the exact COD-AB `adm3_pcode` (`IDPPKKDDD`), `kecamatan.bps_code` stores `PPKKDDD`, `kabupaten_kota.kemendagri_code` uses the official **Kepmendagri Nomor 100.1.1-6117 Tahun 2022** kabupaten/kota codes (`91.03`–`96.71`), and `kecamatan.kemendagri_code` combines `<official_kab_code>.<DDD>` (preserving the 3-digit COD-AB subdistrict suffix `DDD` unambiguously across split districts).

| COD-AB `adm1_pcode` | COD-AB `adm2_pcode` | Kabupaten / Kota | Current Province | Official Kemendagri `kab_code` | Legal Basis |
|---|---|---|---|---|---|
| `ID94` | `ID9403` | Jayapura | `91` Papua | `91.03` | Parent province (UU 14–16/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID94` | `ID9408` | Kepulauan Yapen | `91` Papua | `91.05` | Parent province (UU 14–16/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID94` | `ID9409` | Biak Numfor | `91` Papua | `91.06` | Parent province (UU 14–16/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID94` | `ID9419` | Sarmi | `91` Papua | `91.10` | Parent province (UU 14–16/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID94` | `ID9420` | Keerom | `91` Papua | `91.11` | Parent province (UU 14–16/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID94` | `ID9426` | Waropen | `91` Papua | `91.15` | Parent province (UU 14–16/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID94` | `ID9427` | Supiori | `91` Papua | `91.19` | Parent province (UU 14–16/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID94` | `ID9428` | Mamberamo Raya | `91` Papua | `91.20` | Parent province (UU 14–16/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID94` | `ID9471` | Kota Jayapura | `91` Papua | `91.71` | Parent province (UU 14–16/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID91` | `ID9105` | Manokwari | `92` Papua Barat | `92.02` | Parent province (UU 29/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID91` | `ID9101` | Fakfak | `92` Papua Barat | `92.03` | Parent province (UU 29/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID91` | `ID9104` | Teluk Bintuni | `92` Papua Barat | `92.06` | Parent province (UU 29/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID91` | `ID9103` | Teluk Wondama | `92` Papua Barat | `92.07` | Parent province (UU 29/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID91` | `ID9102` | Kaimana | `92` Papua Barat | `92.08` | Parent province (UU 29/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID91` | `ID9111` | Manokwari Selatan | `92` Papua Barat | `92.11` | Parent province (UU 29/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID91` | `ID9112` | Pegunungan Arfak | `92` Papua Barat | `92.12` | Parent province (UU 29/2022; Kepmendagri 100.1.1-6117/2022) |
| `ID94` | `ID9401` | Merauke | `93` Papua Selatan | `93.01` | UU Nomor 14 Tahun 2022 Pasal 3 |
| `ID94` | `ID9413` | Boven Digoel | `93` Papua Selatan | `93.02` | UU Nomor 14 Tahun 2022 Pasal 3 |
| `ID94` | `ID9414` | Mappi | `93` Papua Selatan | `93.03` | UU Nomor 14 Tahun 2022 Pasal 3 |
| `ID94` | `ID9415` | Asmat | `93` Papua Selatan | `93.04` | UU Nomor 14 Tahun 2022 Pasal 3 |
| `ID94` | `ID9404` | Nabire | `94` Papua Tengah | `94.01` | UU Nomor 15 Tahun 2022 Pasal 3 |
| `ID94` | `ID9411` | Puncak Jaya | `94` Papua Tengah | `94.02` | UU Nomor 15 Tahun 2022 Pasal 3 |
| `ID94` | `ID9410` | Paniai | `94` Papua Tengah | `94.03` | UU Nomor 15 Tahun 2022 Pasal 3 |
| `ID94` | `ID9412` | Mimika | `94` Papua Tengah | `94.04` | UU Nomor 15 Tahun 2022 Pasal 3 |
| `ID94` | `ID9433` | Puncak | `94` Papua Tengah | `94.05` | UU Nomor 15 Tahun 2022 Pasal 3 |
| `ID94` | `ID9434` | Dogiyai | `94` Papua Tengah | `94.06` | UU Nomor 15 Tahun 2022 Pasal 3 |
| `ID94` | `ID9435` | Intan Jaya | `94` Papua Tengah | `94.07` | UU Nomor 15 Tahun 2022 Pasal 3 |
| `ID94` | `ID9436` | Deiyai | `94` Papua Tengah | `94.08` | UU Nomor 15 Tahun 2022 Pasal 3 |
| `ID94` | `ID9402` | Jayawijaya | `95` Papua Pegunungan | `95.01` | UU Nomor 16 Tahun 2022 Pasal 3 |
| `ID94` | `ID9417` | Pegunungan Bintang | `95` Papua Pegunungan | `95.02` | UU Nomor 16 Tahun 2022 Pasal 3 |
| `ID94` | `ID9416` | Yahukimo | `95` Papua Pegunungan | `95.03` | UU Nomor 16 Tahun 2022 Pasal 3 |
| `ID94` | `ID9418` | Tolikara | `95` Papua Pegunungan | `95.04` | UU Nomor 16 Tahun 2022 Pasal 3 |
| `ID94` | `ID9431` | Mamberamo Tengah | `95` Papua Pegunungan | `95.05` | UU Nomor 16 Tahun 2022 Pasal 3 |
| `ID94` | `ID9432` | Yalimo | `95` Papua Pegunungan | `95.06` | UU Nomor 16 Tahun 2022 Pasal 3 |
| `ID94` | `ID9430` | Lanny Jaya | `95` Papua Pegunungan | `95.07` | UU Nomor 16 Tahun 2022 Pasal 3 |
| `ID94` | `ID9429` | Nduga | `95` Papua Pegunungan | `95.08` | UU Nomor 16 Tahun 2022 Pasal 3 |
| `ID91` | `ID9107` | Sorong | `96` Papua Barat Daya | `96.01` | UU Nomor 29 Tahun 2022 Pasal 3 |
| `ID91` | `ID9106` | Sorong Selatan | `96` Papua Barat Daya | `96.02` | UU Nomor 29 Tahun 2022 Pasal 3 |
| `ID91` | `ID9108` | Raja Ampat | `96` Papua Barat Daya | `96.03` | UU Nomor 29 Tahun 2022 Pasal 3 |
| `ID91` | `ID9109` | Tambrauw | `96` Papua Barat Daya | `96.04` | UU Nomor 29 Tahun 2022 Pasal 3 |
| `ID91` | `ID9110` | Maybrat | `96` Papua Barat Daya | `96.05` | UU Nomor 29 Tahun 2022 Pasal 3 |
| `ID91` | `ID9171` | Kota Sorong | `96` Papua Barat Daya | `96.71` | UU Nomor 29 Tahun 2022 Pasal 3 |

### 4f. Kalimantan, Bali–Nusa Tenggara & Maluku Extracts (`51`–`53`, `61`–`65`, `81`–`82`)
Polygon containment checks against Geofabrik's `.poly` boundaries (`nusa-tenggara.poly`, `kalimantan.poly`, `maluku.poly`) showed that:
- **Bali (`51`), Nusa Tenggara Barat (`52`), and Nusa Tenggara Timur (`53`):** `nusa-tenggara.poly` covers **57/57** Bali districts (including Nusa Penida), **116/116** NTB districts (including Sumbawa), and **307/307** NTT districts (including Alor, Rote, and Sabu) at 100% (`0` Bali districts lie in `java.poly`). Therefore `51`–`53` all load from `nusa-tenggara-latest.osm.pbf` (`java-latest.osm.pbf` is not needed for Bali).
- **Kalimantan (`61`–`65`):** `kalimantan.poly` covers **174/174** Kalbar (`61`), **136/136** Kalteng (`62`), **152/152** Kalsel (`63`), **103/103** Kaltim (`64`, including Derawan; Long Apari `ID6411050` 99.90% along the Sarawak border), and **53/53** Kaltara (`65`, 51 at 100% plus Krayan Timur `99.10%` and Lumbis Ogong `99.98%` along the Malaysian border). COD-AB `idn_admin1`/`idn_admin2`/`idn_admin3` already includes `ID65` Kalimantan Utara (5 kab/kota, 53 valid districts), so no UU 20/2012 reassignment was needed.
- **Maluku (`81`) & Maluku Utara (`82`):** `maluku.poly` covers **118/118** Maluku districts (including Kepulauan Aru and Tanimbar) and **116/116** valid Maluku Utara districts (including Morotai and Sula; 2 non-district forest polygons `ID8205999` and `ID8271999` excluded) at 100%.

1. `nusa-tenggara-latest.osm.pbf`
   - **URL:** `https://download.geofabrik.de/asia/indonesia/nusa-tenggara-latest.osm.pbf`
   - **Download Date:** 2026-11-18
   - **File Size:** 177,284,507 bytes
   - **MD5 (verified vs Geofabrik `.md5`):** `137ed8368a2d6c72ab1c8792263a0f9c`
   - **SHA-256:** `e922cf533ae1778ea4197b35964b0e746ba43128be1d85da4d0f17df06641546`
2. `kalimantan-latest.osm.pbf` (re-downloaded newer Geofabrik snapshot for `61`–`65`; `19`/`21`/`76` in staging retain the 2026-11-17 snapshot above)
   - **URL:** `https://download.geofabrik.de/asia/indonesia/kalimantan-latest.osm.pbf`
   - **Download Date:** 2026-11-18
   - **File Size:** 147,677,246 bytes
   - **MD5 (verified vs Geofabrik `.md5`):** `e3d691f79bac083d74d64630da20a6f6`
   - **SHA-256:** `d9fead392428df0851e0f60d4bc760679515cb04a87ef7e892ad45dbc531e44f`
3. `maluku-latest.osm.pbf` (reused; MD5 verified identical to Geofabrik `.md5` on 2026-11-18)
   - **URL:** `https://download.geofabrik.de/asia/indonesia/maluku-latest.osm.pbf`
   - **Download Date:** 2026-11-18
   - **File Size:** 26,811,086 bytes
   - **MD5 (verified vs Geofabrik `.md5`):** `eec9cf03cb57f8f6f4f7d48bd9f6f565`
   - **SHA-256:** `855e5dd98d2d2d9ea737aaab378a508968016e2b26de48ff840e50c6dfaf8dea`
