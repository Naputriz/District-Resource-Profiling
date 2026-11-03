-- ============================================================================
-- DISTRICT RESOURCE PROFILING & SPATIAL SIMULATION (DKI JAKARTA)
-- Schema Definition: Administrative Boundaries, 4 Pillars Public Amenities,
-- Regulatory Compliance, Transient Simulation Sandbox & Autonomous Watchdog
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Administrative Hierarchy (DKI Jakarta)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS provinces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kemendagri_code VARCHAR(10) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    boundary GEOMETRY(MultiPolygon, 4326),
    boundary_utm GEOMETRY(MultiPolygon, 32748),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kabupaten_kota (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    province_id UUID REFERENCES provinces(id) ON DELETE CASCADE,
    kemendagri_code VARCHAR(15) UNIQUE NOT NULL,
    bps_code VARCHAR(15),
    name VARCHAR(100) NOT NULL,
    boundary GEOMETRY(MultiPolygon, 4326),
    boundary_utm GEOMETRY(MultiPolygon, 32748),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kecamatan (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kabupaten_kota_id UUID REFERENCES kabupaten_kota(id) ON DELETE CASCADE,
    kemendagri_code VARCHAR(20) UNIQUE NOT NULL,
    bps_code VARCHAR(20),
    name VARCHAR(100) NOT NULL,
    population INT DEFAULT 0,
    area_km2 NUMERIC(10, 4) DEFAULT 0,
    density_per_km2 NUMERIC(12, 2) DEFAULT 0,
    total_rt INT DEFAULT 0,
    total_rw INT DEFAULT 0,
    boundary GEOMETRY(MultiPolygon, 4326) NOT NULL,
    boundary_utm GEOMETRY(MultiPolygon, 32748),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Spatial Indices on Administrative Boundaries
CREATE INDEX IF NOT EXISTS idx_provinces_boundary ON provinces USING GIST(boundary);
CREATE INDEX IF NOT EXISTS idx_provinces_boundary_utm ON provinces USING GIST(boundary_utm);
CREATE INDEX IF NOT EXISTS idx_kabupaten_boundary ON kabupaten_kota USING GIST(boundary);
CREATE INDEX IF NOT EXISTS idx_kabupaten_boundary_utm ON kabupaten_kota USING GIST(boundary_utm);
CREATE INDEX IF NOT EXISTS idx_kecamatan_boundary ON kecamatan USING GIST(boundary);
CREATE INDEX IF NOT EXISTS idx_kecamatan_boundary_utm ON kecamatan USING GIST(boundary_utm);
CREATE INDEX IF NOT EXISTS idx_kecamatan_name_trgm ON kecamatan USING gin (name gin_trgm_ops);

-- ----------------------------------------------------------------------------
-- 2. 4 Pillars Public Amenities (Dynamic & Resilient Schema)
-- ----------------------------------------------------------------------------
-- Pillars:
--   1. lifeline_health       (RSUD, Puskesmas, Damkar, Titik Evakuasi)
--   2. education             (SD, SMP, SMA/SMK, Balai Latihan, Perpustakaan)
--   3. urban_livability      (RTH, Taman Kota, RPTRA, GOR)
--   4. mobility_connectivity (MRT, LRT, KRL, Halte TransJakarta, Pasar Tradisional, UMKM)

CREATE TABLE IF NOT EXISTS public_facilities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kecamatan_id UUID REFERENCES kecamatan(id) ON DELETE SET NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'osm', -- 'osm', 'bps', 'dki_satu', 'kemenkes', 'seed_manual'
    source_id VARCHAR(100),                   -- Unique ID from source (null for manual seeds)
    osm_id BIGINT,                            -- Backward compatibility for OSM items
    name VARCHAR(255),
    pillar VARCHAR(50) NOT NULL,              -- lifeline_health, education, urban_livability, mobility_connectivity
    category VARCHAR(50) NOT NULL,            -- healthcare, emergency_fire, education, green_open_space, transit_mobility, commercial
    facility_type VARCHAR(100) NOT NULL,      -- specific sub-type matching regulatory_standards
    address TEXT,
    contact VARCHAR(100),
    website VARCHAR(255),
    capacity INT DEFAULT 0,                   -- Beds, students, daily ridership, or land area
    area_m2 NUMERIC(14, 2),                   -- Calculated polygon area in EPSG:32748
    coordinates GEOMETRY(Point, 4326) NOT NULL,
    coordinates_utm GEOMETRY(Point, 32748),
    metadata JSONB DEFAULT '{}'::jsonb,       -- Extensible attributes (tags, opening hours, accreditation, operator)
    is_active BOOLEAN DEFAULT TRUE,           -- Soft delete / decommissioned flag
    is_verified BOOLEAN DEFAULT TRUE,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_source_source_id UNIQUE (source, source_id)
);

-- Indices on Facilities
CREATE INDEX IF NOT EXISTS idx_facilities_coordinates ON public_facilities USING GIST(coordinates);
CREATE INDEX IF NOT EXISTS idx_facilities_coordinates_utm ON public_facilities USING GIST(coordinates_utm);
CREATE INDEX IF NOT EXISTS idx_facilities_pillar_type ON public_facilities(pillar, facility_type);
CREATE INDEX IF NOT EXISTS idx_facilities_kecamatan ON public_facilities(kecamatan_id);
CREATE INDEX IF NOT EXISTS idx_facilities_is_active ON public_facilities(is_active);
CREATE INDEX IF NOT EXISTS idx_facilities_name_trgm ON public_facilities USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_facilities_metadata ON public_facilities USING gin (metadata jsonb_path_ops);

-- ----------------------------------------------------------------------------
-- 3. Deterministic Regulatory Standards (SNI 03-1733-2004, SPM & Perda RDTR)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regulatory_standards (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    facility_type VARCHAR(100) NOT NULL UNIQUE,
    pillar VARCHAR(50) NOT NULL,
    category VARCHAR(50) NOT NULL,
    standard_name VARCHAR(150) NOT NULL, -- e.g. SNI 03-1733-2004, Permenkes 43/2019
    population_threshold INT,            -- e.g. 1 unit per 30,000 residents (NULL for informational types)
    service_radius_meters INT,           -- e.g. 1000m (1 km) (NULL for types without radius standard)
    min_land_area_m2 INT DEFAULT 0,
    legal_reference TEXT NOT NULL,       -- Chapter, Article, Source PDF citation
    description TEXT,
    scored BOOLEAN NOT NULL DEFAULT true,-- True if scored in index, False if informational only (§6.3)
    source TEXT,                         -- PDF table & page citation string, e.g. "SNI 03-1733-2004 Tabel 8 hal. 26"
    confidence VARCHAR(20) DEFAULT 'Medium',
    classified_count INT DEFAULT 0,
    data_availability VARCHAR(20) DEFAULT 'available',
    availability_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 4. Regulatory Vector Chunks (Cognitive Multi-Stage RAG)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regulatory_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_title VARCHAR(255) NOT NULL, -- e.g. SNI 03-1733-2004, Perda DKI 31/2022 RDTR
    regulation_code VARCHAR(100) NOT NULL,
    chapter VARCHAR(100),
    article_number VARCHAR(50),
    pillar VARCHAR(50),
    facility_type VARCHAR(100),
    content_text TEXT NOT NULL,
    embedding VECTOR(1024),               -- BAAI/bge-m3 dense representation
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reg_chunks_doc ON regulatory_chunks(regulation_code, article_number);
CREATE INDEX IF NOT EXISTS idx_reg_chunks_content_trgm ON regulatory_chunks USING gin (content_text gin_trgm_ops);

-- ----------------------------------------------------------------------------
-- 5. Baseline District Compliance & Livability Scores
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS district_compliance_scores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    district_id UUID REFERENCES kecamatan(id) ON DELETE CASCADE UNIQUE,
    health_score NUMERIC(5, 2) DEFAULT NULL,
    education_score NUMERIC(5, 2) DEFAULT NULL,
    livability_score NUMERIC(5, 2) DEFAULT NULL,
    mobility_score NUMERIC(5, 2) DEFAULT NULL,
    composite_livability_score NUMERIC(5, 2) DEFAULT NULL,
    composite_note TEXT,
    unserved_area_km2 NUMERIC(10, 4) NOT NULL DEFAULT 0.0,
    metrics_payload JSONB DEFAULT '{}'::jsonb,
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 6. Transient What-If Simulation Sandbox (Isolated Context)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS simulation_sessions (
    session_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kecamatan_id UUID REFERENCES kecamatan(id) ON DELETE CASCADE,
    user_identifier VARCHAR(100) NOT NULL DEFAULT 'anonymous',
    scenario_title VARCHAR(255) DEFAULT 'Hypothetical Scenario',
    population_shock_percent NUMERIC(5, 2) DEFAULT 0.00,
    population_shock_count INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL -- TTL 1 Jam
);

CREATE TABLE IF NOT EXISTS simulated_amenities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID REFERENCES simulation_sessions(session_id) ON DELETE CASCADE,
    pillar VARCHAR(50) NOT NULL,
    facility_type VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    coordinates GEOMETRY(Point, 4326) NOT NULL,
    coordinates_utm GEOMETRY(Point, 32748),
    planned_capacity INT DEFAULT 0,
    properties JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS simulation_delta_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID REFERENCES simulation_sessions(session_id) ON DELETE CASCADE,
    baseline_composite_index NUMERIC(5, 2) NOT NULL,
    simulated_composite_index NUMERIC(5, 2) NOT NULL,
    score_delta NUMERIC(5, 2) NOT NULL,
    newly_served_area_km2 NUMERIC(10, 4) NOT NULL,
    newly_served_population INT NOT NULL,
    simulated_blank_spots_geom GEOMETRY(MultiPolygon, 4326),
    delta_details JSONB DEFAULT '{}'::jsonb,
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 7. Incident & Self-Healing Audit Ledger (Autonomous Watchdog)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incident_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_type VARCHAR(100) NOT NULL, -- OOM_RELOAD, VRAM_EXHAUSTION, SCRAPER_RATE_LIMIT, CONTAINER_RESTART
    severity VARCHAR(20) NOT NULL,       -- LOW, MEDIUM, HIGH, CRITICAL
    target_service VARCHAR(100) NOT NULL,-- vllm, postgis, redis, backend, ingestion
    action_taken TEXT NOT NULL,
    status VARCHAR(50) NOT NULL,         -- RESOLVED, HITL_PENDING, FAILED
    gpu_temperature_celsius INT,
    vram_used_mb INT,
    error_payload JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 8. Triggers for Automatic UTM Projected Geometry Computation
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_sync_utm_geometry()
RETURNS TRIGGER AS $$
BEGIN
    -- Synchronize UTM 48S (SRID 32748) for point or multipolygon
    IF TG_TABLE_NAME = 'public_facilities' OR TG_TABLE_NAME = 'simulated_amenities' THEN
        IF NEW.coordinates IS NOT NULL THEN
            NEW.coordinates_utm := ST_Transform(NEW.coordinates, 32748);
        END IF;
    ELSIF TG_TABLE_NAME = 'kecamatan' OR TG_TABLE_NAME = 'kabupaten_kota' OR TG_TABLE_NAME = 'provinces' THEN
        IF NEW.boundary IS NOT NULL THEN
            NEW.boundary_utm := ST_Transform(NEW.boundary, 32748);
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS sync_facilities_utm ON public_facilities;
CREATE TRIGGER sync_facilities_utm
BEFORE INSERT OR UPDATE OF coordinates ON public_facilities
FOR EACH ROW EXECUTE FUNCTION trg_sync_utm_geometry();

DROP TRIGGER IF EXISTS sync_simulated_utm ON simulated_amenities;
CREATE TRIGGER sync_simulated_utm
BEFORE INSERT OR UPDATE OF coordinates ON simulated_amenities
FOR EACH ROW EXECUTE FUNCTION trg_sync_utm_geometry();

DROP TRIGGER IF EXISTS sync_kecamatan_utm ON kecamatan;
CREATE TRIGGER sync_kecamatan_utm
BEFORE INSERT OR UPDATE OF boundary ON kecamatan
FOR EACH ROW EXECUTE FUNCTION trg_sync_utm_geometry();
