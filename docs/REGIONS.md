# Multi-Region Support (Java & Expansion Guide)

Java provinces `31`–`36` have been live on `https://drp.digilabui.cloud` (fallback `https://drp.digilabui.workers.dev`) since 17 Nov 2026 (commit `9ee346d`, `ACTIVE_PROVINCES=31,32,33,34,35,36`).

---

## 1. Regions & Current Status

| Code | Province | Status | Kecamatan | Scored (`memadai`) | Gated (`tidak_memadai`) | Population Source |
|---|---|---|---:|---:|---:|---|
| `31` | DKI Jakarta | **Active** | 44 | 44 | 0 | BPS 2024 |
| `32` | Jawa Barat | **Active** | 627 | 321 | 306 | WorldPop R2025A 2024 (model estimate) |
| `33` | Jawa Tengah | **Active** | 573 | 288 | 285 | WorldPop R2025A 2024 (model estimate) |
| `34` | DI Yogyakarta | **Active** | 78 | 66 | 12 | WorldPop R2025A 2024 (model estimate) |
| `35` | Jawa Timur | **Active** | 666 | 327 | 339 | WorldPop R2025A 2024 (model estimate) |
| `36` | Banten | **Active** | 155 | 63 | 92 | WorldPop R2025A 2024 (model estimate) |
| — | Other Indonesian provinces | **Planned** | — | — | — | — |

Total served across Java: **2,143 kecamatan** (1,109 scored, 1,034 gated).

---

## 2. Data Sources & Licences

Raw downloads for provinces `32`–`36` are stored outside Git under `/mnt/data/rpl/data_raw/`. Exact URLs, download dates, byte sizes, and SHA-256 hashes are recorded in [`pipeline/data/sources/REGION_SOURCES.md`](../pipeline/data/sources/REGION_SOURCES.md).

| Layer | DKI Jakarta (`31`) | Java Provinces (`32`–`36`) | Licence |
|---|---|---|---|
| **Boundaries** | `SakifAbdillah/jakartaKecamatanGeoJSON` (BPS / Kemendagri) | HDX COD-AB Indonesia (`cod-ab-idn`, layer `idn_admin3`, BPS / BIG via OCHA ROAP) | DKI: Public Domain / ODbL<br>32–36: **CC BY-IGO** |
| **Population** | BPS Provinsi DKI Jakarta 2024 (*Statistik Daerah 2024*) | WorldPop Global2 constrained 100 m (`G2_CN_POP_R25A_100m`, release R2025A, 2024) | DKI: Government Open Data (BPS)<br>32–36: **CC BY 4.0** |
| **Public Facilities** | OpenStreetMap via Overpass API (`2026-10-14`, 14,496 active facilities) | OpenStreetMap via Geofabrik Java PBF (`java-latest.osm.pbf`, `2026-11-17`) | **ODbL 1.0** |
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

- **More islands:** Sumatra, Sulawesi, Papua, and the remaining provinces (Kalimantan, Bali–Nusa Tenggara, Maluku) using the same `load_region.py` pipeline and Geofabrik island PBFs.
- **SNI 1733:2026:** Switch facility standards from `SNI 03-1733-2004` to `SNI 1733:2026` once the official BSN PDF is available.
- **Official facility counts:** Supplement or replace OSM counts with official ministry / BPS / Dinas facility registries to reduce under-counting outside DKI Jakarta.

---

## 8. Follow-Up Improvements

- **Light district list endpoint:** `GET /api/v1/districts?province_code=32` currently returns the full `metrics_payload` for all 627 kecamatan (~`3.4 MB`, ~`0.9 s` over the internet). Adding a light list endpoint (or `?include_metrics=false` option) without `metrics_payload` would speed up initial province switches and map choropleth rendering while fetching full `metrics_payload` only on district click (`GET /api/v1/districts/{code}`).
