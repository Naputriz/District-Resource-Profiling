"""
Data Integrity Tests for OpenStreetMap (OSM) Ingestion & Spatial Sync.
Data integrity validation:
1. No facility with source = 'osm' has a null osm_id.
2. No active facility has source = 'seed_manual' after OSM load.
3. Every active facility has an associated kecamatan (kecamatan_id is not null).
"""

import pytest
import psycopg2
from backend.app.core.config import settings

pytestmark = pytest.mark.db

def test_data_integrity_post_osm_load():
    conn = psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        dbname=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD
    )
    cur = conn.cursor()
    try:
        # Rule 1: No facility with source = 'osm' has a null osm_id
        cur.execute("SELECT COUNT(*) FROM public_facilities WHERE source = 'osm' AND osm_id IS NULL;")
        null_osm_id_count = cur.fetchone()[0]
        assert null_osm_id_count == 0, f"Expected 0 null osm_ids for OSM source, got {null_osm_id_count}"

        # Rule 2: No active facility has source = 'seed_manual' after OSM load
        cur.execute("SELECT COUNT(*) FROM public_facilities WHERE source = 'seed_manual' AND is_active = TRUE;")
        active_seed_count = cur.fetchone()[0]
        assert active_seed_count == 0, f"Expected 0 active seed_manual facilities after OSM load, got {active_seed_count}"

        # Rule 3: Every active facility has a kecamatan
        cur.execute("SELECT COUNT(*) FROM public_facilities WHERE is_active = TRUE AND kecamatan_id IS NULL;")
        unassigned_active_count = cur.fetchone()[0]
        assert unassigned_active_count == 0, f"Expected 0 active facilities without kecamatan, got {unassigned_active_count}"

        # Additional sanity checks
        cur.execute("SELECT COUNT(*) FROM public_facilities WHERE is_active = TRUE;")
        total_active = cur.fetchone()[0]
        assert total_active > 10000, f"Expected >10,000 active facilities, got {total_active}"

        cur.execute("SELECT COUNT(*) FROM public_facilities WHERE source = 'seed_manual';")
        total_seed = cur.fetchone()[0]
        assert total_seed > 0, "Seed manual records must be preserved for unit test fixtures"

        print(f">> [PASSED] Data Integrity: {total_active:,} active facilities verified (0 null osm_ids, 0 active seeds, 0 unassigned).")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    test_data_integrity_post_osm_load()
