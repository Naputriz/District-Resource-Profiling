"""
Master Ingestion & Spatial Sync Pipeline for District Resource Profiling (DKI Jakarta).
Handles:
1. Administrative Hierarchy (DKI Jakarta + 6 Jurisdictions + 44 Districts).
2. 4 Pillars Public Amenities Ingestion with idempotent UPSERT.
3. Spatial Containment Mapping (ST_Contains).
4. Regulatory Legal Chunks Seeding (korpus regulasi).
5. Baseline Deterministic Compliance & Livability Scoring.
6. Redis scorecard cache.
"""

import os
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
import psycopg2
from psycopg2.extras import execute_values
import redis

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BOUNDARIES_FILE = DATA_DIR / "boundaries" / "jakarta_44_kecamatan.geojson"
FACILITIES_DIR = DATA_DIR / "facilities"
REGULATIONS_DIR = DATA_DIR / "regulations"

# 6 Official Administrative Jurisdictions of DKI Jakarta
KABUPATEN_KOTA_JAKARTA = [
    {"kemendagri_code": "31.01", "name": "Kabupaten Administrasi Kepulauan Seribu"},
    {"kemendagri_code": "31.71", "name": "Kota Administrasi Jakarta Selatan"},
    {"kemendagri_code": "31.72", "name": "Kota Administrasi Jakarta Timur"},
    {"kemendagri_code": "31.73", "name": "Kota Administrasi Jakarta Pusat"},
    {"kemendagri_code": "31.74", "name": "Kota Administrasi Jakarta Barat"},
    {"kemendagri_code": "31.75", "name": "Kota Administrasi Jakarta Utara"}
]

class DistrictDataIngestionPipeline:
    def __init__(self):
        self.db_config = {
            "dbname": os.getenv("POSTGRES_DB", "district_profiling"),
            "user": os.getenv("POSTGRES_USER", "postgres"),
            "password": os.getenv("POSTGRES_PASSWORD", "postgres_spatial_dev"),
            "host": os.getenv("POSTGRES_HOST") or "127.0.0.1",
            "port": int(os.getenv("POSTGRES_PORT", 5432))
        }
        if self.db_config["host"] == "localhost":
            self.db_config["host"] = "127.0.0.1"
        self.redis_client = None
        self._init_redis()

    def _init_redis(self):
        try:
            r_host = os.getenv("REDIS_HOST", "localhost")
            r_port = int(os.getenv("REDIS_PORT", 6379))
            self.redis_client = redis.Redis(host=r_host, port=r_port, decode_responses=True)
            self.redis_client.ping()
            logger.info("Connected to Redis 7 Caching Layer successfully.")
        except Exception as e:
            logger.warning(f"Redis connection warning (caching will be skipped if unreachable): {e}")
            self.redis_client = None

    def get_db_connection(self):
        return psycopg2.connect(**self.db_config)

    def seed_administrative_hierarchy(self, conn) -> Dict[str, str]:
        """Seeds province and 6 cities, returning city kemendagri_code -> UUID mapping."""
        city_id_map = {}
        with conn.cursor() as cur:
            # 1. Province: DKI Jakarta
            cur.execute("""
                INSERT INTO provinces (kemendagri_code, name)
                VALUES ('31', 'Provinsi DKI Jakarta')
                ON CONFLICT (kemendagri_code) DO NOTHING
                RETURNING id;
            """)
            row = cur.fetchone()
            prov_id = row[0] if row else None
            if not prov_id:
                cur.execute("SELECT id FROM provinces WHERE kemendagri_code = '31';")
                prov_id = cur.fetchone()[0]

            # 2. Kabupaten / Kota
            for kab in KABUPATEN_KOTA_JAKARTA:
                cur.execute("""
                    INSERT INTO kabupaten_kota (province_id, kemendagri_code, name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (kemendagri_code) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id;
                """, (prov_id, kab["kemendagri_code"], kab["name"]))
                city_id_map[kab["kemendagri_code"]] = cur.fetchone()[0]

            conn.commit()
            logger.info(f"Seeded Provinsi DKI Jakarta and 6 administrative cities.")
        return city_id_map

    def load_kecamatan_boundaries(self, conn, city_id_map: Dict[str, str]) -> int:
        """Loads all 44 Kecamatan from standardized GeoJSON into PostGIS."""
        if not BOUNDARIES_FILE.exists():
            logger.error(f"Boundaries file not found at {BOUNDARIES_FILE}")
            return 0

        with open(BOUNDARIES_FILE, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)

        features = geojson_data.get("features", [])
        logger.info(f"Loading {len(features)} Kecamatan into PostGIS...")

        loaded_count = 0
        with conn.cursor() as cur:
            for feat in features:
                props = feat.get("properties", {})
                k_code = props["kemendagri_code"]
                parent_code = ".".join(k_code.split(".")[:2])
                kab_id = city_id_map.get(parent_code)
                geom_json = json.dumps(feat.get("geometry"))

                cur.execute("""
                    INSERT INTO kecamatan (
                        kabupaten_kota_id, kemendagri_code, bps_code, name,
                        population, area_km2, density_per_km2, boundary
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                    )
                    ON CONFLICT (kemendagri_code) DO UPDATE SET
                        bps_code = EXCLUDED.bps_code,
                        name = EXCLUDED.name,
                        population = EXCLUDED.population,
                        area_km2 = EXCLUDED.area_km2,
                        density_per_km2 = EXCLUDED.density_per_km2,
                        boundary = EXCLUDED.boundary,
                        updated_at = CURRENT_TIMESTAMP;
                """, (
                    kab_id,
                    k_code,
                    props.get("bps_code"),
                    props.get("name"),
                    props.get("population", 0),
                    props.get("area_km2", 0.0),
                    props.get("density_per_km2", 0.0),
                    geom_json
                ))
                loaded_count += 1

            conn.commit()
            logger.info(f"Successfully loaded and verified {loaded_count} Kecamatan boundaries.")
        return loaded_count

    def load_public_facilities_4_pillars(self, conn) -> int:
        """Loads all 4 Pillars facilities from JSON snapshots and normalized OSM data into public_facilities."""
        pillar_files = [
            FACILITIES_DIR / "pillar1_lifeline_health.json",
            FACILITIES_DIR / "pillar2_human_capital_education.json",
            FACILITIES_DIR / "pillar3_urban_livability_recreation.json",
            FACILITIES_DIR / "pillar4_mobility_commercial.json"
        ]

        total_loaded = 0
        with conn.cursor() as cur:
            # 1. Ingest manual seed records (kept for offline tests & baseline fallback)
            for pf in pillar_files:
                if not pf.exists():
                    logger.warning(f"File not found: {pf.name}")
                    continue

                with open(pf, "r", encoding="utf-8") as f:
                    facilities = json.load(f)

                logger.info(f"Ingesting {len(facilities)} seed facilities from {pf.name}...")
                for item in facilities:
                    coords = item["coordinates"]["coordinates"] # [lon, lat]
                    source_id = item.get("source_id")
                    osm_id = item.get("osm_id")
                    source = item.get("source", "seed_manual")
                    is_verified = item.get("is_verified", False)

                    cur.execute("""
                        SELECT id FROM public_facilities 
                        WHERE name = %s AND facility_type = %s;
                    """, (item["name"], item["facility_type"]))
                    existing = cur.fetchone()
                    if existing:
                        fac_id = existing[0] if isinstance(existing, (list, tuple)) else existing["id"]
                        cur.execute("""
                            UPDATE public_facilities SET
                                source = %s,
                                source_id = %s,
                                osm_id = %s,
                                pillar = %s,
                                category = %s,
                                address = %s,
                                contact = %s,
                                website = %s,
                                capacity = %s,
                                coordinates = ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                                metadata = %s,
                                is_active = %s,
                                is_verified = %s,
                                last_synced_at = CURRENT_TIMESTAMP,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s;
                        """, (
                            source,
                            source_id,
                            osm_id,
                            item["pillar"],
                            item["category"],
                            item.get("address"),
                            item.get("contact"),
                            item.get("website"),
                            item.get("capacity", 0),
                            coords[0],
                            coords[1],
                            json.dumps(item.get("metadata", {})),
                            item.get("is_active", True),
                            is_verified,
                            fac_id
                        ))
                    else:
                        cur.execute("""
                            INSERT INTO public_facilities (
                                source, source_id, osm_id, name, pillar, category,
                                facility_type, address, contact, website, capacity,
                                coordinates, metadata, is_active, is_verified, last_synced_at
                            )
                            VALUES (
                                %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s,
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                                %s, %s, %s, CURRENT_TIMESTAMP
                            );
                        """, (
                            source,
                            source_id,
                            osm_id,
                            item["name"],
                            item["pillar"],
                            item["category"],
                            item["facility_type"],
                            item.get("address"),
                            item.get("contact"),
                            item.get("website"),
                            item.get("capacity", 0),
                            coords[0],
                            coords[1],
                            json.dumps(item.get("metadata", {})),
                            item.get("is_active", True),
                            is_verified
                        ))
                    total_loaded += 1

            # 2. Ingest normalized real OSM data if available
            min_files = sorted(FACILITIES_DIR.glob("osm_facilities_*.min.json"))
            if min_files:
                osm_file = min_files[-1]
            else:
                osm_files = sorted([f for f in FACILITIES_DIR.glob("osm_facilities_*.json") if not f.name.endswith(".min.json")])
                osm_file = osm_files[-1] if osm_files else None

            if osm_file:
                logger.info(f"Ingesting real OpenStreetMap data from {osm_file.name}...")
                with open(osm_file, "r", encoding="utf-8") as f:
                    osm_facilities = json.load(f)

                logger.info("Deactivating seed_manual records (setting is_active = FALSE)...")
                cur.execute("UPDATE public_facilities SET is_active = FALSE WHERE source = 'seed_manual';")
                logger.info("Resetting is_active on OSM facilities prior to fresh deduplicated load...")
                cur.execute("UPDATE public_facilities SET is_active = FALSE WHERE source = 'osm';")

                logger.info(f"Batch upserting {len(osm_facilities)} OSM facilities on (source, source_id)...")
                osm_tuples = []
                for item in osm_facilities:
                    coords = item["coordinates"]["coordinates"] # [lon, lat]
                    osm_tuples.append((
                        item.get("source", "osm"),
                        item["source_id"],
                        item.get("osm_id"),
                        item.get("name"),
                        item["pillar"],
                        item["category"],
                        item["facility_type"],
                        item.get("address"),
                        item.get("contact"),
                        item.get("website"),
                        item.get("capacity", 0),
                        item.get("area_m2"),
                        coords[0],
                        coords[1],
                        json.dumps(item.get("metadata", {})),
                        item.get("is_active", True),
                        item.get("is_verified", False)
                    ))

                execute_values(
                    cur,
                    """
                    INSERT INTO public_facilities (
                        source, source_id, osm_id, name, pillar, category,
                        facility_type, address, contact, website, capacity,
                        area_m2, coordinates, metadata, is_active, is_verified, last_synced_at
                    )
                    VALUES %s
                    ON CONFLICT (source, source_id) DO UPDATE SET
                        osm_id = EXCLUDED.osm_id,
                        name = EXCLUDED.name,
                        pillar = EXCLUDED.pillar,
                        category = EXCLUDED.category,
                        facility_type = EXCLUDED.facility_type,
                        address = EXCLUDED.address,
                        contact = EXCLUDED.contact,
                        website = EXCLUDED.website,
                        capacity = EXCLUDED.capacity,
                        area_m2 = EXCLUDED.area_m2,
                        coordinates = EXCLUDED.coordinates,
                        metadata = EXCLUDED.metadata,
                        is_active = EXCLUDED.is_active,
                        is_verified = EXCLUDED.is_verified,
                        last_synced_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    osm_tuples,
                    template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s::jsonb, %s, %s, CURRENT_TIMESTAMP)",
                    page_size=1000
                )
                total_loaded += len(osm_facilities)
                logger.info(f"Loaded {len(osm_facilities)} OSM facilities.")

            # 3. Spatially associate active facilities with their containing Kecamatan
            logger.info("Executing ST_Contains spatial district containment linking...")
            cur.execute("""
                UPDATE public_facilities f
                SET kecamatan_id = k.id
                FROM kecamatan k
                WHERE ST_Contains(k.boundary, f.coordinates);
            """)

            # 4. Check how many records fall outside all 44 polygons
            cur.execute("SELECT COUNT(*) FROM public_facilities WHERE kecamatan_id IS NULL;")
            outside_count = cur.fetchone()[0]
            logger.info(f"Records outside all 44 polygons: {outside_count}")
            # Mark records outside the 44 DKI Jakarta polygons as inactive
            cur.execute("UPDATE public_facilities SET is_active = FALSE WHERE kecamatan_id IS NULL;")

            conn.commit()
            logger.info(f"Total {total_loaded} facilities synced and spatially indexed.")
        return total_loaded

    def seed_regulatory_legal_chunks(self, conn) -> int:
        """Seeds regulatory legal chunks for Hybrid RAG into regulatory_chunks using RegulationCorpusLoader."""
        from pipeline.regulation_loader import RegulationCorpusLoader
        reg_loader = RegulationCorpusLoader()
        reg_loader.load_standards_matrix(conn)
        return reg_loader.load_all_regulatory_chunks(conn)

    def compute_baseline_compliance(self, conn) -> int:
        """Calculates deterministic compliance scores (0-100) per kecamatan across 4 pillars using standards availability."""
        from backend.app.engine.standards_availability import (
            evaluate_availability,
            calculate_pillar_and_composite_scores,
            STANDARDS_AVAILABILITY_SPEC
        )

        logger.info("Computing mathematical compliance scores per kecamatan with data availability rules...")
        computed = 0
        with conn.cursor() as cur:
            # 1. Update city-wide classified counts and availability in regulatory_standards
            cur.execute("""
                SELECT facility_type, COUNT(*) 
                FROM public_facilities 
                WHERE is_active = TRUE 
                GROUP BY facility_type;
            """)
            city_counts = dict(cur.fetchall())

            # Fetch all standards
            cur.execute("""
                SELECT facility_type, pillar, population_threshold, service_radius_meters, scored, source
                FROM regulatory_standards
                ORDER BY pillar, facility_type;
            """)
            standards = cur.fetchall()

            availability_map = {}
            for std in standards:
                ftype, pillar, threshold, radius, scored, source = std
                cnt = city_counts.get(ftype, 0)
                spec = STANDARDS_AVAILABILITY_SPEC.get(ftype, {})
                conf = spec.get("confidence", "Medium")
                is_not_avail = spec.get("is_not_available_from_osm", False)
                avail, reason = evaluate_availability(ftype, cnt, conf, is_not_avail)
                availability_map[ftype] = (avail, reason)

                cur.execute("""
                    UPDATE regulatory_standards
                    SET classified_count = %s,
                        confidence = %s,
                        data_availability = %s,
                        availability_reason = %s
                    WHERE facility_type = %s;
                """, (cnt, conf, avail, reason, ftype))

            # 2. Fetch all kecamatan
            cur.execute("SELECT id, name, kemendagri_code, population, area_km2 FROM kecamatan;")
            districts = cur.fetchall()

            for dist in districts:
                dist_id, name, code, pop, area = dist
                if pop is None or pop <= 0:
                    logger.warning(f"Kecamatan {name} ({code}) has no population recorded (population=None); excluding from compliance scoring.")
                    continue

                # Count facilities in this district
                cur.execute("""
                    SELECT facility_type, COUNT(*) 
                    FROM public_facilities
                    WHERE kecamatan_id = %s AND is_active = TRUE
                    GROUP BY facility_type;
                """, (dist_id,))
                fac_counts = dict(cur.fetchall())

                metrics_detail = []

                for std in standards:
                    ftype, pillar, threshold, radius, scored, source = std
                    existing = fac_counts.get(ftype, 0)
                    avail, reason = availability_map.get(ftype, ("available", ""))

                    # only scored=True and available types produce need/deficit/score
                    if scored and avail == "available" and threshold:
                        required = max(1, math.ceil(pop / threshold))
                        pct = min(100.0, round((existing / required) * 100.0, 2))
                        deficit = existing - required
                    else:
                        required = None
                        pct = None
                        deficit = None

                    metrics_detail.append({
                        "facility_type": ftype,
                        "pillar": pillar,
                        "existing": existing,
                        "required": required,
                        "compliance_pct": pct,
                        "deficit": deficit,
                        "data_availability": avail,
                        "availability_reason": reason,
                        "scored": scored,
                        "source": source
                    })

                # Calculate pillar and composite scores using proportional re-weighting
                scores_res = calculate_pillar_and_composite_scores(metrics_detail, availability_map)
                p_scores = scores_res["pillar_scores"]
                composite = scores_res["composite_score"]
                comp_note = scores_res["composite_note"]

                p_health = p_scores["lifeline_health"]["score"]
                p_edu = p_scores["education"]["score"]
                p_liv = p_scores["urban_livability"]["score"]
                p_mob = p_scores["mobility_connectivity"]["score"]

                cur.execute("""
                    INSERT INTO district_compliance_scores (
                        district_id, health_score, education_score, livability_score,
                        mobility_score, composite_livability_score, composite_note,
                        unserved_area_km2, metrics_payload, calculated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (district_id) DO UPDATE SET
                        health_score = EXCLUDED.health_score,
                        education_score = EXCLUDED.education_score,
                        livability_score = EXCLUDED.livability_score,
                        mobility_score = EXCLUDED.mobility_score,
                        composite_livability_score = EXCLUDED.composite_livability_score,
                        composite_note = EXCLUDED.composite_note,
                        metrics_payload = EXCLUDED.metrics_payload,
                        calculated_at = CURRENT_TIMESTAMP;
                """, (
                    dist_id, p_health, p_edu, p_liv, p_mob, composite, comp_note, 0.0,
                    json.dumps(metrics_detail)
                ))
                computed += 1

            conn.commit()
            logger.info(f"Computed and saved compliance scorecards for all {computed} districts.")
        return computed

    def sync_to_redis_cache(self, conn):
        """Caches full district scorecards and GeoJSON features into Redis for low-latency queries."""
        if not self.redis_client:
            logger.warning("Redis client not active. Skipping cache sync.")
            return

        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    k.kemendagri_code, k.name, k.population, k.area_km2,
                    s.health_score, s.education_score, s.livability_score,
                    s.mobility_score, s.composite_livability_score, s.composite_note,
                    s.metrics_payload
                FROM kecamatan k
                JOIN district_compliance_scores s ON s.district_id = k.id;
            """)
            rows = cur.fetchall()

            scorecards = {}
            for r in rows:
                code, name, pop, area, h, e, l, m, comp, note, payload = r
                scorecards[code] = {
                    "kemendagri_code": code,
                    "name": name,
                    "population": pop,
                    "area_km2": float(area),
                    "health_score": float(h) if h is not None else None,
                    "education_score": float(e) if e is not None else None,
                    "livability_score": float(l) if l is not None else None,
                    "mobility_score": float(m) if m is not None else None,
                    "composite_livability_score": float(comp) if comp is not None else None,
                    "composite_note": note,
                    "metrics": payload
                }

            # Cache with 24h TTL (86400s)
            self.redis_client.setex("cache:compliance:scores", 86400, json.dumps(scorecards))
            logger.info(f"Cached {len(scorecards)} district compliance scorecards into Redis key 'cache:compliance:scores' (TTL 24h).")

    def run_all(self):
        """Executes full ingestion, validation, scoring, and caching cycle."""
        logger.info("==============================================================")
        logger.info("STARTING MASTER SPATIAL DATA INGESTION & COMPLIANCE PIPELINE")
        logger.info("==============================================================")
        conn = self.get_db_connection()
        try:
            city_map = self.seed_administrative_hierarchy(conn)
            num_districts = self.load_kecamatan_boundaries(conn, city_map)
            num_facilities = self.load_public_facilities_4_pillars(conn)
            num_chunks = self.seed_regulatory_legal_chunks(conn)
            num_scores = self.compute_baseline_compliance(conn)
            self.sync_to_redis_cache(conn)

            logger.info("==============================================================")
            logger.info(f"PIPELINE SUMMARY SUCCESS:")
            logger.info(f" - Administrative Districts: {num_districts}")
            logger.info(f" - Public Facilities (4 Pillars): {num_facilities}")
            logger.info(f" - Regulatory Legal Chunks: {num_chunks}")
            logger.info(f" - Compliance Scorecards: {num_scores}")
            logger.info("==============================================================")
        finally:
            conn.close()

if __name__ == "__main__":
    pipeline = DistrictDataIngestionPipeline()
    pipeline.run_all()
