"""
Regulation & Standards Ingestion Pipeline.
Loads:
1. The 16-row standards matrix into regulatory_standards.
2. SNI 03-1733-2004 articles (pipeline/data/regulations/sni_03_1733_2004_full.json)
   into regulatory_chunks. Other regulations are not verified yet and are not indexed.

Generates 1024-dim hashed bag-of-words vectors for pgvector and indexes trigram search.
"""

import os
import json
import math
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Any
import psycopg2
from psycopg2.extras import execute_values, RealDictCursor
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
REGULATIONS_DIR = BASE_DIR / "data" / "regulations"

def generate_pseudo_dense_embedding(text: str, dim: int = 1024) -> List[float]:
    """
    Generates a deterministic, normalized 1024-dimensional dense vector representation
    using SHA-512 based n-gram term hashing.
    Provides immediate compatibility with pgvector (vector_cosine_ops)
    before neural model (BAAI/bge-m3) inference is invoked.
    """
    vec = [0.0] * dim
    words = text.lower().replace("-", " ").split()
    for i, word in enumerate(words):
        h = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        weight = 1.0 + (1.0 / (1.0 + math.log(i + 1)))
        vec[idx] += weight

        # Bigrams
        if i < len(words) - 1:
            bg = f"{word}_{words[i+1]}"
            h_bg = int(hashlib.sha512(bg.encode("utf-8")).hexdigest(), 16)
            idx_bg = h_bg % dim
            vec[idx_bg] += 1.5

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [round(x / norm, 6) for x in vec]
    return vec

class RegulationCorpusLoader:
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

    def get_connection(self):
        return psycopg2.connect(**self.db_config)

    def load_standards_matrix(self, conn) -> int:
        """Seeds granular regulatory standards into regulatory_standards table per README §6."""
        # Clean up removed types (§6.4)
        removed_types = [
            "tps_3r", "hutan_kota", "gelanggang_olahraga",
            "perpustakaan_wilayah", "sentra_niaga_umkm", "pos_polisi"
        ]
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM regulatory_standards WHERE facility_type = ANY(%s);",
                (removed_types,)
            )

        standards = [
            # §6.2 Dinilai: Pilar Pendidikan (4 Jenis)
            (
                "taman_kanak_kanak", "education", "education", "SNI 03-1733-2004",
                1250, 500, 500, "SNI 03-1733-2004 Bagian 7.2 Tabel 8 hal. 26",
                "Taman Kanak-kanak: 1 unit per 1.250 jiwa, radius 500 m",
                True, "SNI 03-1733-2004 Tabel 8 hal. 26"
            ),
            (
                "sekolah_dasar", "education", "education", "SNI 03-1733-2004",
                1600, 1000, 2000, "SNI 03-1733-2004 Bagian 7.2 Tabel 8 hal. 26",
                "Sekolah Dasar: 1 unit per 1.600 jiwa, radius 1.000 m",
                True, "SNI 03-1733-2004 Tabel 8 hal. 26"
            ),
            (
                "sekolah_menengah_pertama", "education", "education", "SNI 03-1733-2004",
                4800, 1000, 9000, "SNI 03-1733-2004 Bagian 7.2 Tabel 8 hal. 26",
                "SMP (SNI: SLTP): 1 unit per 4.800 jiwa, radius 1.000 m",
                True, "SNI 03-1733-2004 Tabel 8 hal. 26"
            ),
            (
                "sekolah_menengah_atas", "education", "education", "SNI 03-1733-2004",
                4800, 3000, 12500, "SNI 03-1733-2004 Bagian 7.2 Tabel 8 hal. 26",
                "SMA/SMK (SNI: SMU): 1 unit per 4.800 jiwa, radius 3.000 m",
                True, "SNI 03-1733-2004 Tabel 8 hal. 26"
            ),

            # §6.2 Dinilai: Pilar Kesehatan & Keselamatan (3 Jenis)
            (
                "puskesmas_kelurahan", "lifeline_health", "healthcare", "SNI 03-1733-2004",
                30000, 1500, 300, "SNI 03-1733-2004 Bagian 7.3 Tabel 12 hal. 29",
                "Puskesmas pembantu (kelurahan): 1 unit per 30.000 jiwa, radius 1.500 m",
                True, "SNI 03-1733-2004 Tabel 12 hal. 29"
            ),
            (
                "puskesmas_kecamatan", "lifeline_health", "healthcare", "SNI 03-1733-2004",
                120000, 3000, 1000, "SNI 03-1733-2004 Bagian 7.3 Tabel 12 hal. 29",
                "Puskesmas (kecamatan): 1 unit per 120.000 jiwa, radius 3.000 m",
                True, "SNI 03-1733-2004 Tabel 12 hal. 29"
            ),
            (
                "pos_damkar", "lifeline_health", "emergency_fire", "SNI 03-1733-2004",
                120000, None, None, "SNI 03-1733-2004 Bagian 7.1 Tabel 6 hal. 23-24",
                "Pos pemadam kebakaran (tingkat kecamatan): 1 unit per 120.000 jiwa, radius NULL (tanpa blank spot)",
                True, "SNI 03-1733-2004 Tabel 6 hal. 23-24"
            ),

            # §6.3 Informasi Saja (Tidak Dinilai, scored = False, threshold = NULL)
            (
                "rumah_sakit", "lifeline_health", "healthcare", "Informasi Fasilitas Kesehatan",
                None, None, None, "Tidak ada di SNI 03-1733-2004; informasi",
                "Rumah sakit: informasi fasilitas rujukan lintas wilayah, tidak dinilai",
                False, "Tidak ada di SNI 03-1733-2004; informasi"
            ),
            (
                "posyandu", "lifeline_health", "healthcare", "SNI 03-1733-2004",
                None, None, None, "SNI 03-1733-2004 Bagian 7.3 Tabel 12 hal. 29",
                "Posyandu: informasi titik OSM (data belum representatif), tidak dinilai",
                False, "SNI 03-1733-2004 Tabel 12 hal. 29; informasi (OSM belum representatif)"
            ),
            (
                "stasiun_transit", "mobility_connectivity", "transit_mobility", "Pergub DKI 67/2019 (TOD)",
                None, None, None, "Pergub DKI 67/2019 Kawasan TOD",
                "Stasiun transit (KRL/MRT/LRT): informasi titik transit, tidak dinilai",
                False, "Pergub DKI 67/2019; informasi"
            ),
            (
                "halte_transjakarta", "mobility_connectivity", "transit_mobility", "Pedoman BRT DKI",
                None, None, None, "Pedoman Teknis BRT DKI",
                "Halte TransJakarta: informasi titik transit koridor/feeder, tidak dinilai",
                False, "Pedoman Teknis BRT DKI; informasi"
            ),
            (
                "pasar_tradisional", "mobility_connectivity", "commercial", "SNI 03-1733-2004",
                None, None, None, "SNI 03-1733-2004 Bagian 7.5 Tabel 14 hal. 33",
                "Pasar tradisional: informasi sarana niaga lingkungan, tidak dinilai",
                False, "SNI 03-1733-2004 Bagian 7.5; informasi"
            ),
            (
                "taman_rt", "urban_livability", "green_open_space", "SNI 03-1733-2004",
                None, None, None, "SNI 03-1733-2004 Bagian 7.7 Tabel 16 hal. 36",
                "Taman RT: informasi ruang terbuka hijau lingkungan, tidak dinilai",
                False, "SNI 03-1733-2004 Bagian 7.7; informasi"
            ),
            (
                "taman_rptra", "urban_livability", "green_open_space", "Pergub DKI 196/2015",
                None, None, None, "Pergub DKI 196/2015 Pengelolaan RPTRA",
                "RPTRA: informasi ruang publik terpadu ramah anak, tidak dinilai",
                False, "Pergub DKI 196/2015; informasi"
            ),
            (
                "taman_kelurahan", "urban_livability", "green_open_space", "SNI 03-1733-2004",
                None, None, None, "SNI 03-1733-2004 Bagian 7.7 Tabel 16 hal. 36",
                "Taman kelurahan: informasi ruang terbuka hijau skala kelurahan, tidak dinilai",
                False, "SNI 03-1733-2004 Bagian 7.7; informasi"
            ),
            (
                "taman_kecamatan", "urban_livability", "green_open_space", "SNI 03-1733-2004",
                None, None, None, "SNI 03-1733-2004 Bagian 7.7 Tabel 16 hal. 36",
                "Taman kecamatan: informasi ruang terbuka hijau skala kecamatan, tidak dinilai",
                False, "SNI 03-1733-2004 Bagian 7.7; informasi"
            )
        ]

        query = """
            INSERT INTO regulatory_standards (
                facility_type, pillar, category, standard_name,
                population_threshold, service_radius_meters, min_land_area_m2,
                legal_reference, description, scored, source
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (facility_type) DO UPDATE SET
                pillar = EXCLUDED.pillar,
                category = EXCLUDED.category,
                standard_name = EXCLUDED.standard_name,
                population_threshold = EXCLUDED.population_threshold,
                service_radius_meters = EXCLUDED.service_radius_meters,
                min_land_area_m2 = EXCLUDED.min_land_area_m2,
                legal_reference = EXCLUDED.legal_reference,
                description = EXCLUDED.description,
                scored = EXCLUDED.scored,
                source = EXCLUDED.source;
        """
        with conn.cursor() as cur:
            cur.executemany(query, standards)
            conn.commit()
            logger.info(f"Seeded {len(standards)} regulatory standards (7 scored, 9 informational).")
        return len(standards)

    def load_all_regulatory_chunks(self, conn) -> int:
        """Parses all regulation JSON files and seeds vector-enabled chunks."""
        chunks_inserted = 0
        with conn.cursor() as cur:
            # Widen columns if needed to support descriptive article titles
            cur.execute("""
                ALTER TABLE regulatory_chunks ALTER COLUMN article_number TYPE VARCHAR(255);
                ALTER TABLE regulatory_chunks ALTER COLUMN chapter TYPE VARCHAR(255);
                TRUNCATE TABLE regulatory_chunks;
            """)

            # 1. SNI 03-1733-2004 Full (Index ONLY pdf_matched articles)
            sni_path = REGULATIONS_DIR / "sni_03_1733_2004_full.json"
            if sni_path.exists():
                with open(sni_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                doc_title = data["title"]
                reg_code = data["code"]
                for chap in data.get("chapters", []):
                    ch_title = f"{chap.get('chapter', '')}: {chap.get('title', '')}"
                    for art in chap.get("articles", []):
                        if art.get("verification") != "pdf_matched":
                            continue
                        text = f"Regulasi: {reg_code} {doc_title}. {ch_title}. Pasal/Tabel: {art.get('article_number')}. Judul: {art.get('title')}. Standar: {art.get('summary', art.get('content'))}. Rasio: {art.get('ratio', '')}. Radius Layanan: {art.get('service_radius_meters', 0)} meter. Luas Lahan Minimal: {art.get('min_land_area_m2', 0)} m²."
                        emb = generate_pseudo_dense_embedding(text)
                        cur.execute("""
                            INSERT INTO regulatory_chunks (
                                document_title, regulation_code, chapter, article_number,
                                pillar, facility_type, content_text, embedding, metadata
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                        """, (
                            doc_title, reg_code, ch_title, art.get("article_number"),
                            art.get("pillar"), art.get("facility_type"), text,
                            emb, json.dumps(art)
                        ))
                        chunks_inserted += 1

            # Other regulations (Perda RDTR, Permenkes, Permendikbud, Permendagri)
            # are 'unverified' and are NOT indexed into regulatory_chunks.
            conn.commit()
            logger.info(f"Loaded {chunks_inserted} pdf_matched regulatory legal chunks into regulatory_chunks.")
        return chunks_inserted

    def run(self):
        conn = self.get_connection()
        try:
            num_stds = self.load_standards_matrix(conn)
            num_chunks = self.load_all_regulatory_chunks(conn)
            logger.info(f"Regulation seeding complete! {num_stds} standards, {num_chunks} vector chunks.")
        finally:
            conn.close()

if __name__ == "__main__":
    loader = RegulationCorpusLoader()
    loader.run()
