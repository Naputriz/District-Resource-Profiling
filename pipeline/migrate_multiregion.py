"""
Migration script: Multi-region schema upgrade (Idempotent).
- Relaxes hardcoded UTM 32748 geometry constraints to generic geometry.
- Adds utm_srid column to administrative and facility tables with default 32748.
- Adds compute_utm_srid() stored procedure using standard UTM zone formula:
  Zone = floor((lon + 180) / 6) + 1; EPSG = 32700 + Zone (South) or 32600 + Zone (North).
  Citation: NIMA Technical Report TR8350.2 / EPSG Geodetic Parameter Dataset.
- Updates trigger trg_sync_utm_geometry() to compute UTM SRID per row.
- Adds province_code to regulatory_standards and regulatory_chunks; tags DKI-specific regulations with '31'.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import logging
from psycopg2.extras import RealDictCursor
from backend.app.core.db import get_db_cursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_multiregion")

def run_migration() -> int:
    changes_made = 0
    with get_db_cursor() as cur:
        # 1. Add utm_srid columns if not exists and ensure no DEFAULT
        tables_for_utm = ["provinces", "kabupaten_kota", "kecamatan", "public_facilities", "simulated_amenities"]
        for tbl in tables_for_utm:
            cur.execute("""
                SELECT column_default FROM information_schema.columns 
                WHERE table_name = %s AND column_name = 'utm_srid';
            """, (tbl,))
            col_row = cur.fetchone()
            if not col_row:
                logger.info(f"Adding utm_srid column to table '{tbl}'...")
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN utm_srid INT;")
                changes_made += 1
            else:
                logger.info(f"Column 'utm_srid' already exists in table '{tbl}'.")
                if col_row.get("column_default") is not None:
                    logger.info(f"Dropping DEFAULT on {tbl}.utm_srid...")
                    cur.execute(f"ALTER TABLE {tbl} ALTER COLUMN utm_srid DROP DEFAULT;")
                    changes_made += 1

        # 2. Relax SRID constraint on geometry columns
        # Check current SRID in geometry_columns
        geom_targets = [
            ("provinces", "boundary_utm", "MultiPolygon"),
            ("kabupaten_kota", "boundary_utm", "MultiPolygon"),
            ("kecamatan", "boundary_utm", "MultiPolygon"),
            ("public_facilities", "coordinates_utm", "Point"),
            ("simulated_amenities", "coordinates_utm", "Point"),
        ]
        for tbl, col, gtype in geom_targets:
            cur.execute("""
                SELECT srid FROM geometry_columns 
                WHERE f_table_name = %s AND f_geometry_column = %s;
            """, (tbl, col))
            row = cur.fetchone()
            if row and row["srid"] != 0:
                logger.info(f"Relaxing SRID constraint on {tbl}.{col} (was {row['srid']}) to generic {gtype}...")
                cur.execute(f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE GEOMETRY({gtype}) USING {col};")
                changes_made += 1
            else:
                logger.info(f"Column {tbl}.{col} already has generic geometry constraint.")

        # 3. Add province_code to regulatory_standards & regulatory_chunks
        reg_tables = ["regulatory_standards", "regulatory_chunks"]
        for tbl in reg_tables:
            cur.execute("""
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = %s AND column_name = 'province_code';
            """, (tbl,))
            if not cur.fetchone():
                logger.info(f"Adding province_code column to table '{tbl}'...")
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN province_code VARCHAR(10) DEFAULT NULL;")
                changes_made += 1
            else:
                logger.info(f"Column 'province_code' already exists in table '{tbl}'.")

        # 4. Tag DKI-specific standards with province_code = '31'
        cur.execute("""
            UPDATE regulatory_standards 
            SET province_code = '31' 
            WHERE standard_name ILIKE '%%DKI%%' AND (province_code IS NULL OR province_code != '31');
        """)
        updated_stds = cur.rowcount
        if updated_stds > 0:
            logger.info(f"Tagged {updated_stds} DKI-specific regulatory standards with province_code='31'.")
            changes_made += updated_stds
        else:
            logger.info("DKI regulatory standards are already tagged with province_code='31'.")

        # 5. Tag DKI-specific regulatory chunks with province_code = '31'
        cur.execute("""
            UPDATE regulatory_chunks 
            SET province_code = '31' 
            WHERE (regulation_code ILIKE '%%DKI%%' OR document_title ILIKE '%%DKI%%')
              AND (province_code IS NULL OR province_code != '31');
        """)
        updated_chunks = cur.rowcount
        if updated_chunks > 0:
            logger.info(f"Tagged {updated_chunks} DKI-specific regulatory chunks with province_code='31'.")
            changes_made += updated_chunks
        else:
            logger.info("DKI regulatory chunks are already tagged with province_code='31'.")

        # 6. Ensure compute_utm_srid stored procedure exists
        cur.execute("""
            CREATE OR REPLACE FUNCTION compute_utm_srid(geom GEOMETRY)
            RETURNS INT AS $$
            DECLARE
                c GEOMETRY;
                lon FLOAT;
                lat FLOAT;
                zone INT;
            BEGIN
                c := ST_Centroid(geom);
                lon := ST_X(c);
                lat := ST_Y(c);
                zone := FLOOR((lon + 180.0) / 6.0)::INT + 1;
                IF lat < 0.0 THEN
                    RETURN 32700 + zone;
                ELSE
                    RETURN 32600 + zone;
                END IF;
            END;
            $$ LANGUAGE plpgsql IMMUTABLE;
        """)
        logger.info("Function compute_utm_srid() ensured.")

        # 7. Update trigger function trg_sync_utm_geometry
        cur.execute("""
            CREATE OR REPLACE FUNCTION trg_sync_utm_geometry()
            RETURNS TRIGGER AS $$
            BEGIN
                IF TG_TABLE_NAME = 'public_facilities' OR TG_TABLE_NAME = 'simulated_amenities' THEN
                    IF NEW.coordinates IS NOT NULL THEN
                        IF NEW.utm_srid IS NULL THEN
                            NEW.utm_srid := compute_utm_srid(NEW.coordinates);
                        END IF;
                        NEW.coordinates_utm := ST_Transform(NEW.coordinates, NEW.utm_srid);
                    END IF;
                ELSIF TG_TABLE_NAME = 'kecamatan' OR TG_TABLE_NAME = 'kabupaten_kota' OR TG_TABLE_NAME = 'provinces' THEN
                    IF NEW.boundary IS NOT NULL THEN
                        IF NEW.utm_srid IS NULL THEN
                            NEW.utm_srid := compute_utm_srid(NEW.boundary);
                        END IF;
                        NEW.boundary_utm := ST_Transform(NEW.boundary, NEW.utm_srid);
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        logger.info("Trigger function trg_sync_utm_geometry() ensured.")

        # 8. Ensure all existing rows have utm_srid = 32748
        for tbl in tables_for_utm:
            cur.execute(f"UPDATE {tbl} SET utm_srid = 32748 WHERE utm_srid IS NULL;")
            if cur.rowcount > 0:
                logger.info(f"Backfilled utm_srid=32748 for {cur.rowcount} rows in '{tbl}'.")
                changes_made += cur.rowcount

    logger.info(f"Migration completed. Total changes recorded: {changes_made}")
    return changes_made

if __name__ == "__main__":
    changes = run_migration()
    print(f"RESULT: changes_made={changes}")
