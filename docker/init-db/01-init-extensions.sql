-- ============================================================================
-- DISTRICT RESOURCE PROFILING (DKI JAKARTA)
-- Database Initialization & Spatial Extension Activation
-- ============================================================================

-- Spatial Extentions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Vector Embeddings for Regulatory & Semantic Retrieval (pgvector)
CREATE EXTENSION IF NOT EXISTS vector;

-- UUID and Full-Text Search Utilities
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Confirm extensions
DO $$
BEGIN
    RAISE NOTICE 'Extensions initialized successfully: PostGIS (%), pgvector, uuid-ossp, pg_trgm', PostGIS_Full_Version();
END $$;
