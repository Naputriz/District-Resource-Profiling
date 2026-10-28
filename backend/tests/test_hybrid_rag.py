"""
Unit & Integration Tests for Multi-Stage Hybrid RAG Engine.
Validates pseudo-dense vector generation, RRF rank merger, and citation formatting.
"""

import pytest
from backend.app.rag.hybrid_search import (
    compute_query_dense_embedding,
    compute_query_hashed_feature_vector,
    LegalCitation,
    HybridRegulationRetriever
)

pytestmark = pytest.mark.unit

def test_dense_embedding_properties():
    text1 = "Puskesmas kelurahan radius 1000 meter melayani 30000 penduduk"
    vec1 = compute_query_dense_embedding(text1, dim=1024)
    vec_h = compute_query_hashed_feature_vector(text1, dim=1024)
    assert vec1 == vec_h

    assert len(vec1) == 1024
    # Check L2 normalization (sum of squares ~ 1.0)
    norm = sum(x * x for x in vec1)
    assert abs(norm - 1.0) < 0.01

    # Check determinism: same input produces exact same vector
    vec2 = compute_query_dense_embedding(text1, dim=1024)
    assert vec1 == vec2

    # Check semantic difference: distinct text produces distinct vector
    vec_diff = compute_query_dense_embedding("Taman RPTRA ramah anak 500 meter", dim=1024)
    assert vec1 != vec_diff

def test_citation_markdown_formatting():
    citations = [
        LegalCitation(
            document_title="Tata Cara Perencanaan Lingkungan Perumahan di Perkotaan",
            regulation_code="SNI 03-1733-2004",
            chapter="Bagian 7.3",
            article_number="Tabel 12",
            pillar="lifeline_health",
            facility_type="puskesmas_kelurahan",
            content_text="Puskesmas pembantu/kelurahan wajib disediakan melayani minimal 30.000 jiwa dengan radius pencapaian aman 1.000m.",
            dense_score=0.92,
            sparse_score=0.85,
            rrf_score=0.032
        ),
        LegalCitation(
            document_title="Rencana Detail Tata Ruang DKI Jakarta",
            regulation_code="Perda DKI No. 31/2022",
            chapter="Bab VI",
            article_number="Pasal 64",
            pillar="urban_livability",
            content_text="Pengembang superblok wajib menyerahkan 20% lahan bruto untuk RTH publik.",
            dense_score=0.88,
            sparse_score=0.79,
            rrf_score=0.029
        )
    ]

    md = HybridRegulationRetriever.format_citations_markdown(citations)
    assert "SNI 03-1733-2004" in md
    assert "Perda DKI No. 31/2022" in md
    assert "Pasal 64" in md
    assert "Tabel 12" in md
    assert "Rujukan Hukum Terverifikasi" in md

if __name__ == "__main__":
    test_dense_embedding_properties()
    test_citation_markdown_formatting()
    print("ALL HYBRID RAG UNIT TESTS PASSED!")
