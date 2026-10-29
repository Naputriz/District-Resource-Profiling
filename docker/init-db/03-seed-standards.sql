-- ============================================================================
-- SEED DATA: REGULATORY STANDARDS MATRIX (README.md §6)
-- Source of truth: SNI 03-1733-2004 PDF verified tables (Tabel 6, 8, 12, 14, 16)
-- 7 Scored Types (§6.2), 9 Informational Types (§6.3), 6 Invented Types Removed (§6.4)
-- ============================================================================

TRUNCATE TABLE regulatory_standards CASCADE;

INSERT INTO regulatory_standards (
    facility_type, pillar, category, standard_name,
    population_threshold, service_radius_meters, min_land_area_m2,
    legal_reference, description, scored, source
)
VALUES
    -- ========================================================================
    -- §6.2 DINILAI: PILAR PENDIDIKAN (4 Jenis)
    -- ========================================================================
    (
        'taman_kanak_kanak',
        'education',
        'education',
        'SNI 03-1733-2004',
        1250,
        500,
        500,
        'SNI 03-1733-2004 Bagian 7.2 Tabel 8 hal. 26',
        'Taman Kanak-kanak: 1 unit per 1.250 jiwa, radius 500 m',
        TRUE,
        'SNI 03-1733-2004 Tabel 8 hal. 26'
    ),
    (
        'sekolah_dasar',
        'education',
        'education',
        'SNI 03-1733-2004',
        1600,
        1000,
        2000,
        'SNI 03-1733-2004 Bagian 7.2 Tabel 8 hal. 26',
        'Sekolah Dasar: 1 unit per 1.600 jiwa, radius 1.000 m',
        TRUE,
        'SNI 03-1733-2004 Tabel 8 hal. 26'
    ),
    (
        'sekolah_menengah_pertama',
        'education',
        'education',
        'SNI 03-1733-2004',
        4800,
        1000,
        9000,
        'SNI 03-1733-2004 Bagian 7.2 Tabel 8 hal. 26',
        'SMP (SNI: SLTP): 1 unit per 4.800 jiwa, radius 1.000 m',
        TRUE,
        'SNI 03-1733-2004 Tabel 8 hal. 26'
    ),
    (
        'sekolah_menengah_atas',
        'education',
        'education',
        'SNI 03-1733-2004',
        4800,
        3000,
        12500,
        'SNI 03-1733-2004 Bagian 7.2 Tabel 8 hal. 26',
        'SMA/SMK (SNI: SMU): 1 unit per 4.800 jiwa, radius 3.000 m',
        TRUE,
        'SNI 03-1733-2004 Tabel 8 hal. 26'
    ),

    -- ========================================================================
    -- §6.2 DINILAI: PILAR KESEHATAN & KESELAMATAN (3 Jenis)
    -- ========================================================================
    (
        'puskesmas_kelurahan',
        'lifeline_health',
        'healthcare',
        'SNI 03-1733-2004',
        30000,
        1500,
        300,
        'SNI 03-1733-2004 Bagian 7.3 Tabel 12 hal. 29',
        'Puskesmas pembantu (kelurahan): 1 unit per 30.000 jiwa, radius 1.500 m',
        TRUE,
        'SNI 03-1733-2004 Tabel 12 hal. 29'
    ),
    (
        'puskesmas_kecamatan',
        'lifeline_health',
        'healthcare',
        'SNI 03-1733-2004',
        120000,
        3000,
        1000,
        'SNI 03-1733-2004 Bagian 7.3 Tabel 12 hal. 29',
        'Puskesmas (kecamatan): 1 unit per 120.000 jiwa, radius 3.000 m',
        TRUE,
        'SNI 03-1733-2004 Tabel 12 hal. 29'
    ),
    (
        'pos_damkar',
        'lifeline_health',
        'emergency_fire',
        'SNI 03-1733-2004',
        120000,
        NULL,
        NULL,
        'SNI 03-1733-2004 Bagian 7.1 Tabel 6 hal. 23-24',
        'Pos pemadam kebakaran (tingkat kecamatan): 1 unit per 120.000 jiwa, radius NULL (tanpa blank spot)',
        TRUE,
        'SNI 03-1733-2004 Tabel 6 hal. 23-24'
    ),

    -- ========================================================================
    -- §6.3 INFORMASI SAJA (TIDAK DINILAI, scored = false, threshold = NULL)
    -- ========================================================================
    (
        'rumah_sakit',
        'lifeline_health',
        'healthcare',
        'Informasi Fasilitas Kesehatan',
        NULL,
        NULL,
        NULL,
        'Tidak ada di SNI 03-1733-2004; informasi',
        'Rumah sakit: informasi titik fasilitas rujukan lintas wilayah, tidak dinilai',
        FALSE,
        'Tidak ada di SNI 03-1733-2004; informasi'
    ),
    (
        'posyandu',
        'lifeline_health',
        'healthcare',
        'SNI 03-1733-2004',
        NULL,
        NULL,
        NULL,
        'SNI 03-1733-2004 Bagian 7.3 Tabel 12 hal. 29',
        'Posyandu: informasi titik OSM (data belum representatif), tidak dinilai',
        FALSE,
        'SNI 03-1733-2004 Tabel 12 hal. 29; informasi (OSM belum representatif)'
    ),
    (
        'stasiun_transit',
        'mobility_connectivity',
        'transit_mobility',
        'Pergub DKI 67/2019 (TOD)',
        NULL,
        NULL,
        NULL,
        'Pergub DKI 67/2019 Kawasan TOD',
        'Stasiun transit (KRL/MRT/LRT): informasi titik transit, tidak dinilai',
        FALSE,
        'Pergub DKI 67/2019; informasi'
    ),
    (
        'halte_transjakarta',
        'mobility_connectivity',
        'transit_mobility',
        'Pedoman BRT DKI',
        NULL,
        NULL,
        NULL,
        'Pedoman Teknis BRT DKI',
        'Halte TransJakarta: informasi titik transit koridor/feeder, tidak dinilai',
        FALSE,
        'Pedoman Teknis BRT DKI; informasi'
    ),
    (
        'pasar_tradisional',
        'mobility_connectivity',
        'commercial',
        'SNI 03-1733-2004',
        NULL,
        NULL,
        NULL,
        'SNI 03-1733-2004 Bagian 7.5 Tabel 14 hal. 33',
        'Pasar tradisional: informasi sarana niaga lingkungan, tidak dinilai',
        FALSE,
        'SNI 03-1733-2004 Bagian 7.5; informasi'
    ),
    (
        'taman_rt',
        'urban_livability',
        'green_open_space',
        'SNI 03-1733-2004',
        NULL,
        NULL,
        NULL,
        'SNI 03-1733-2004 Bagian 7.7 Tabel 16 hal. 36',
        'Taman RT: informasi ruang terbuka hijau lingkungan, tidak dinilai',
        FALSE,
        'SNI 03-1733-2004 Bagian 7.7; informasi'
    ),
    (
        'taman_rptra',
        'urban_livability',
        'green_open_space',
        'Pergub DKI 196/2015',
        NULL,
        NULL,
        NULL,
        'Pergub DKI 196/2015 Pengelolaan RPTRA',
        'RPTRA: informasi ruang publik terpadu ramah anak, tidak dinilai',
        FALSE,
        'Pergub DKI 196/2015; informasi'
    ),
    (
        'taman_kelurahan',
        'urban_livability',
        'green_open_space',
        'SNI 03-1733-2004',
        NULL,
        NULL,
        NULL,
        'SNI 03-1733-2004 Bagian 7.7 Tabel 16 hal. 36',
        'Taman kelurahan: informasi ruang terbuka hijau skala kelurahan, tidak dinilai',
        FALSE,
        'SNI 03-1733-2004 Bagian 7.7; informasi'
    ),
    (
        'taman_kecamatan',
        'urban_livability',
        'green_open_space',
        'SNI 03-1733-2004',
        NULL,
        NULL,
        NULL,
        'SNI 03-1733-2004 Bagian 7.7 Tabel 16 hal. 36',
        'Taman kecamatan: informasi ruang terbuka hijau skala kecamatan, tidak dinilai',
        FALSE,
        'SNI 03-1733-2004 Bagian 7.7; informasi'
    );
