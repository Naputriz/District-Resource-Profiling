# OpenStreetMap (OSM) Tag Mapping Matrix for DKI Jakarta

This document defines the deterministic mapping classifying OSM tags into 22 facility types; 16 of them are in `regulatory_standards` (`docker/init-db/03-seed-standards.sql`: 7 scored, 9 informational) and the other 6 (`gelanggang_olahraga`, `hutan_kota`, `perpustakaan_wilayah`, `pos_polisi`, `sentra_niaga_umkm`, `tps_3r`) were removed from the standards because they are not in SNI 03-1733-2004 or have no usable data; they are still classified for reference only and are never scored.

Rules:
- **Do not guess:** If an element matches an OSM query but lacks verifiable tags or unambiguous naming heuristics, its `facility_type` is assigned to `unclassified`.
- Types without reliable OSM tags are documented with exact heuristics and marked `Low` confidence or `NOT_AVAILABLE_FROM_OSM`.
- Facility type harmonization: 16 of the 22 types are defined in `regulatory_standards` (7 scored, 9 informational per `docker/init-db/03-seed-standards.sql`), while the other 6 (`gelanggang_olahraga`, `hutan_kota`, `perpustakaan_wilayah`, `pos_polisi`, `sentra_niaga_umkm`, `tps_3r`) were removed from the standards (not in SNI 03-1733-2004 or no usable data); they are preserved for reference only and are never scored.

---

## Tag Mapping Table (22 Classified Types)

| # | Facility Type (`facility_type`) | Pillar | OSM Tags Used | How Ambiguous Cases Are Classified | Confidence |
|---|---|---|---|---|---|
| 1 | `puskesmas_kelurahan` | `lifeline_health` | `amenity=clinic`, `healthcare=centre`, `amenity=hospital` | Name heuristic: contains "puskesmas", "poskeskel", "pustu", or "kelurahan" without containing "kecamatan". If indistinguishable, classified as `unclassified`. | Low |
| 2 | `puskesmas_kecamatan` | `lifeline_health` | `amenity=clinic`, `healthcare=centre`, `amenity=hospital` | Name heuristic: contains "puskesmas" AND ("kecamatan" or "kec."). If ambiguous, classified as `unclassified`. | Medium |
| 3 | `rumah_sakit` | `lifeline_health` | `amenity=hospital`, `healthcare=hospital` | Elements tagged `amenity=hospital` or `healthcare=hospital`. Strictly excludes names containing "klinik", "clinic", "apotek", "puskesmas", "praktek", or standalone "lab" / "laboratorium". | High |
| 4 | `pos_damkar` | `lifeline_health` | `amenity=fire_station` | Mapped directly from `amenity=fire_station` or name containing "pemadam" / "damkar". | High |
| 5 | `pos_polisi` | `lifeline_health` | `amenity=police` | Name heuristic: contains "pos polisi", "pos lantas", "subsektor". Larger police stations (Polsek, Polres, Polda) or generic tags classified as `unclassified` if cannot confirm sub-sector. | Medium |
| 6 | `posyandu` | `lifeline_health` | `healthcare=centre`, `amenity=community_centre` | Name heuristic: contains "posyandu". If name does not contain "posyandu", classified as `unclassified`. | Low |
| 7 | `taman_kanak_kanak` | `education` | `amenity=kindergarten`, `amenity=school` (`isced:level=0`) | Name heuristic: contains "tk ", "tks ", "paud", "ra ", "taman kanak". If ambiguous, classified as `unclassified`. | Medium |
| 8 | `sekolah_dasar` | `education` | `amenity=school` (`isced:level=1`) | Name heuristic: contains "sd ", "sdn ", "sds ", "madrasah ibtidaiyah", "mis ", "min ", "primary". If generic school without level, classified as `unclassified`. | Medium |
| 9 | `sekolah_menengah_pertama` | `education` | `amenity=school` (`isced:level=2`) | Name heuristic: contains "smp ", "smpn", "smps", "madrasah tsanawiyah", "mts", "junior high". | Medium |
| 10 | `sekolah_menengah_atas` | `education` | `amenity=school` (`isced:level=3`) | Name heuristic: contains "sma ", "sman", "smas", "smk ", "smkn", "madrasah aliyah", "man ", "senior high". | Medium |
| 11 | `perpustakaan_wilayah` | `education` | `amenity=library` | Municipal/regional public libraries (`access=public` or public name). University and school private libraries classified as `unclassified`. | Medium |
| 12 | `taman_rt` | `urban_livability` | `NOT_AVAILABLE_FROM_OSM` | Micro-scale residential RT pocket parks (<250 m²) are not systematically tagged in OSM. Heuristic: none reliable; marked not available. | Low |
| 13 | `taman_rptra` | `urban_livability` | `leisure=park`, `leisure=playground` | Name heuristic: explicitly contains "rptra" or "ruang publik terpadu ramah anak". Generic playgrounds go to `unclassified`. | Medium |
| 14 | `taman_kelurahan` | `urban_livability` | `leisure=park` | Name heuristic: contains "taman kelurahan". If ambiguous or general park, classified as `taman_unspecified`. | Low |
| 15 | `taman_kecamatan` | `urban_livability` | `leisure=park` | Name heuristic: explicitly contains "taman kecamatan" or "taman kec.". General public parks without explicit kecamatan designation are classified as `taman_unspecified`. | High |
| 16 | `hutan_kota` | `urban_livability` | `leisure=park`, `landuse=forest`, `boundary=protected_area` | Name heuristic: contains "hutan kota" OR explicit urban forest tag (`urban_forest=yes`, `forest=urban`, `leisure=nature_reserve`). Unnamed `landuse=forest` or names with just "hutan" become `unclassified`. | High |
| 17 | `gelanggang_olahraga` | `urban_livability` | `leisure=sports_centre`, `leisure=pitch`, `leisure=stadium` | Public sports facilities whose name contains "gor", "gelanggang", "stadion", or "sport". Private fitness gyms go to `unclassified`. | Medium |
| 18 | `tps_3r` | `urban_livability` | `amenity=recycling`, `amenity=waste_transfer_station`, `amenity=waste_disposal` | Name heuristic: contains "3r", "tps3r", "tps-3r", or "tps". Generic dumpsters classified as `unclassified`. | Low |
| 19 | `stasiun_transit` | `mobility_connectivity` | `railway=station`, `railway=subway_entrance`, `station=subway`, `station=light_rail` | Heavy rail (KRL), MRT, LRT, and airport express passenger stations. Freight facilities excluded. | High |
| 20 | `halte_transjakarta` | `mobility_connectivity` | `highway=bus_stop`, `amenity=bus_station` | Tag heuristic: require `operator`, `network`, `brand`, or `route` containing "TransJakarta". Generic bus stops named "Halte ..." without TransJakarta network membership become `halte_unspecified`. | High |
| 21 | `pasar_tradisional` | `mobility_connectivity` | `amenity=marketplace`, `shop=marketplace` | Traditional wet markets and PD Pasar Jaya locations. Modern grocery stores (`shop=supermarket`) go to `unclassified`. | Medium |
| 22 | `sentra_niaga_umkm` | `mobility_connectivity` | `NOT_AVAILABLE_FROM_OSM` (Heuristic only) | Name heuristic: contains "sentra umkm", "lokbin", "lokasi binaan", "pusat jajanan". Generic shops go to `unclassified`. | Low |

---

## Unspecified & Unclassified Classes (Non-Scored)
The following classes are stored in `public_facilities` for data completeness and traceability, but are **excluded** from compliance score calculation (they are not added to `regulatory_standards`):
1. `taman_unspecified`: Public parks whose names or tags lack explicit designation as `taman_kecamatan`, `taman_kelurahan`, `taman_rptra`, or `hutan_kota`.
2. `halte_unspecified`: Bus stops or stations that lack verifiable TransJakarta operator, network, brand, or route membership.
3. `unclassified`: Query-matched urban features that lack definitive evidence to assign to any of the 22 regulatory standard categories.

---

## Deduplication Heuristics
When a node and a way (or two elements) have:
1. The identical `facility_type`, AND
2. A non-empty normalized name that matches (case-insensitive, punctuation stripped), AND
3. A distance $\le 150$ meters (haversine spherical formula):

The deduplicator retains **one** element, preferring the **way centroid** over the node (to reflect spatial footprints). If both are the same geometry type, preference is given to the element with more metadata tags, then stable `source_id`.

---

## Area Metric (`area_m2`)
For park ways and polygons, `area_m2` is computed in EPSG:32748 (UTM Zone 48S). If an element lacks polygon vertices (e.g. from Overpass `out center tags;`), `area_m2` is stored as `null`. This metric is stored for future polygon-based RTH analyses and is not currently used in unit-count scoring.

---

## Data Availability & Coverage Classification

To resolve the problem where data gaps were conflated with absent infrastructure ("no data" counted as "no facility", driving pillars to 0.00), this mapping establishes that **data completeness (city-wide coverage), not tag classification confidence, decides availability**. Classification confidence indicates whether a classified record is the right type, but does not indicate whether OSM has mapped all units. With fewer records than the number of kecamatan (44), sparse types cause artificial 0 scores due to mapping gaps rather than actual urban absence.

### Classification Rules
1. `not_available`: The mapping specification designates the type as `NOT_AVAILABLE_FROM_OSM`, or exactly 0 records are classified city-wide in OSM.
2. `insufficient`: Fewer than 44 classified records exist city-wide (fewer than an average of one unit per kecamatan), **regardless of confidence**.
3. `available`: 44 or more classified records exist city-wide.

### Scoring Impact
- $S_{pilar} = \frac{1}{|V|} \sum_{j \in V} S_{jenis, j}$ where $V = \{j \in \text{Pilar} \mid \text{availability}(j) = \text{'available'}\}$.
- Excluded types (`insufficient` and `not_available`) are returned under `types_excluded` with reason and are **never** scored as 0.
- Pillar status:
  - $|V| = 0$: `score: null` with status `"data tidak tersedia"`.
  - $|V| = 1$: scored on the single available type with status `"cakupan data rendah"` (low data coverage).
  - $|V| > 1$: status `"tersedia"`.
- The composite score proportionally re-weights the remaining active pillars:
  $$W'_p = \frac{W_p}{\sum_{q \in \text{ValidPillars}} W_q}, \quad S_{\text{composite}} = \sum_{p \in \text{ValidPillars}} W'_p \cdot S_p$$

### Facility Availability Matrix (22 Classified Types)

| # | Facility Type (`facility_type`) | Pillar | Classified Count | Confidence | Availability Flag | Reason |
|---|---|---|---|---|---|---|
| 1 | `perpustakaan_wilayah` | `education` | 5 | Medium | `insufficient` | 5 classified records city-wide (<44) - kelengkapan data tidak memadai |
| 2 | `sekolah_dasar` | `education` | 1483 | Medium | `available` | Classified records >= 44 (1483) |
| 3 | `sekolah_menengah_atas` | `education` | 539 | Medium | `available` | Classified records >= 44 (539) |
| 4 | `sekolah_menengah_pertama` | `education` | 633 | Medium | `available` | Classified records >= 44 (633) |
| 5 | `taman_kanak_kanak` | `education` | 2274 | Medium | `available` | Classified records >= 44 (2274) |
| 6 | `pos_damkar` | `lifeline_health` | 99 | High | `available` | Classified records >= 44 (99) |
| 7 | `pos_polisi` | `lifeline_health` | 75 | Medium | `available` | Classified records >= 44 (75) |
| 8 | `posyandu` | `lifeline_health` | 598 | Low | `available` | Classified records >= 44 (598) |
| 9 | `puskesmas_kecamatan` | `lifeline_health` | 57 | Medium | `available` | Classified records >= 44 (57) |
| 10 | `puskesmas_kelurahan` | `lifeline_health` | 289 | Low | `available` | Classified records >= 44 (289) |
| 11 | `rumah_sakit` | `lifeline_health` | 327 | High | `available` | Classified records >= 44 (327) |
| 12 | `halte_transjakarta` | `mobility_connectivity` | 3949 | High | `available` | Classified records >= 44 (3949) |
| 13 | `pasar_tradisional` | `mobility_connectivity` | 235 | Medium | `available` | Classified records >= 44 (235) |
| 14 | `sentra_niaga_umkm` | `mobility_connectivity` | 0 | Low | `not_available` | NOT_AVAILABLE_FROM_OSM (0 classified records city-wide) |
| 15 | `stasiun_transit` | `mobility_connectivity` | 174 | High | `available` | Classified records >= 44 (174) |
| 16 | `gelanggang_olahraga` | `urban_livability` | 90 | Medium | `available` | Classified records >= 44 (90) |
| 17 | `hutan_kota` | `urban_livability` | 13 | High | `insufficient` | 13 classified records city-wide (<44) - kelengkapan data tidak memadai |
| 18 | `taman_kecamatan` | `urban_livability` | 0 | High | `not_available` | 0 classified records city-wide in OSM |
| 19 | `taman_kelurahan` | `urban_livability` | 2 | Low | `insufficient` | 2 classified records city-wide (<44) - kelengkapan data tidak memadai |
| 20 | `taman_rptra` | `urban_livability` | 22 | Medium | `insufficient` | 22 classified records city-wide (<44) - kelengkapan data tidak memadai |
| 21 | `taman_rt` | `urban_livability` | 0 | Low | `not_available` | NOT_AVAILABLE_FROM_OSM (0 classified records city-wide) |
| 22 | `tps_3r` | `urban_livability` | 10 | Low | `insufficient` | 10 classified records city-wide (<44) - kelengkapan data tidak memadai |

