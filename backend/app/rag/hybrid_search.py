"""
Pencarian leksikal (trigram + hashed bag-of-words + sinonim) untuk regulasi tata ruang.
Bukan model embedding semantik (neural embedding seperti BGE-M3 direncanakan pada tahap Lanjutan).

Metode pencarian menggabungkan:
1. Vektor fitur leksikal ter-hash (SHA-256/SHA-512 bag-of-words & bigram) via pgvector.
2. Pencarian leksikal renggang (sparse) via pg_trgm (kemiripan trigram) & pencocokan teks.
3. Reciprocal Rank Fusion (RRF) untuk penggabungan peringkat hasil.
4. Pemformatan sitasi hukum resmi (Pasal, Bab, Standar).
"""

import math
import hashlib
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

SYNONYM_MAP: Dict[str, str] = {
    r"\bdamkar\b": "pemadam kebakaran pos damkar",
    r"\bpuskesmas\b": "puskesmas pusat kesehatan masyarakat",
    r"\brth\b": "ruang terbuka hijau rth",
    r"\brs\b": "rumah sakit",
    r"\bsd\b": "sekolah dasar",
    r"\bsmp\b": "sekolah menengah pertama",
    r"\bsma\b": "sekolah menengah atas",
    r"\btod\b": "transit oriented development tod",
}

def expand_regulatory_query(query: str) -> str:
    """
    Applies deterministic synonym expansions for spatial & urban regulatory terms
    (e.g., damkar <-> pemadam kebakaran, puskesmas <-> pusat kesehatan masyarakat,
    RTH <-> ruang terbuka hijau) to align user queries with regulatory corpus terminology.
    """
    expanded = query.strip()
    for pattern, replacement in SYNONYM_MAP.items():
        expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)
    return expanded

class LegalCitation(BaseModel):
    chunk_id: Optional[str] = None
    document_title: str
    regulation_code: str
    chapter: Optional[str] = None
    article_number: Optional[str] = None
    pillar: Optional[str] = None
    facility_type: Optional[str] = None
    content_text: str
    metadata: Dict[str, Any] = {}
    dense_score: Optional[float] = None
    sparse_score: Optional[float] = None
    rrf_score: float = 0.0

def compute_query_hashed_feature_vector(query_text: str, dim: int = 1024) -> List[float]:
    """Generates 1024-dim hashed feature vector (bag-of-words + bigrams) for the query text."""
    vec = [0.0] * dim
    words = query_text.lower().replace("-", " ").split()
    for i, word in enumerate(words):
        h = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        weight = 1.0 + (1.0 / (1.0 + math.log(i + 1)))
        vec[idx] += weight

        if i < len(words) - 1:
            bg = f"{word}_{words[i+1]}"
            h_bg = int(hashlib.sha512(bg.encode("utf-8")).hexdigest(), 16)
            idx_bg = h_bg % dim
            vec[idx_bg] += 1.5

    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [round(x / norm, 6) for x in vec]
    return vec

# Backward-compatible alias
compute_query_dense_embedding = compute_query_hashed_feature_vector

class HybridRegulationRetriever:
    @staticmethod
    def search_regulations(
        query: str,
        pillar: Optional[str] = None,
        facility_type: Optional[str] = None,
        top_k: int = 5,
        rrf_k: int = 60
    ) -> List[LegalCitation]:
        """
        Melakukan pencarian leksikal (trigram + hashed bag-of-words + sinonim) dengan Reciprocal Rank Fusion.
        """
        from backend.app.core.db import get_db_cursor
        expanded_query = expand_regulatory_query(query)
        query_vec = compute_query_hashed_feature_vector(expanded_query)
        vec_str = "[" + ",".join(str(x) for x in query_vec) + "]"

        # 1. Hashed feature vector retrieval using pgvector cosine distance
        dense_results: List[Dict[str, Any]] = []
        sparse_results: List[Dict[str, Any]] = []

        with get_db_cursor() as cur:
            # Dense Query
            dense_sql = """
                SELECT id, document_title, regulation_code, chapter, article_number,
                       pillar, facility_type, content_text, metadata,
                       1 - (embedding <=> %s::vector) as cosine_sim
                FROM regulatory_chunks
                WHERE embedding IS NOT NULL
            """
            d_params = [vec_str]
            if pillar:
                dense_sql += " AND pillar = %s"
                d_params.append(pillar)
            if facility_type:
                dense_sql += " AND facility_type = %s"
                d_params.append(facility_type)

            dense_sql += " ORDER BY embedding <=> %s::vector LIMIT 20;"
            d_params.append(vec_str)

            try:
                cur.execute("SAVEPOINT dense_q")
                cur.execute(dense_sql, tuple(d_params))
                dense_results = cur.fetchall()
                cur.execute("RELEASE SAVEPOINT dense_q")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT dense_q")
                # Fallback if vector index is still compiling
                dense_results = []

            # Sparse Query (Lexical Full-Text & Trigram)
            sparse_sql = """
                SELECT id, document_title, regulation_code, chapter, article_number,
                       pillar, facility_type, content_text, metadata,
                       similarity(content_text, %s) as trigram_sim
                FROM regulatory_chunks
                WHERE (
                    similarity(content_text, %s) > 0.03
                    OR content_text ILIKE %s
                    OR document_title ILIKE %s
                    OR chapter ILIKE %s
                )
            """
            kw_param = f"%{query}%"
            s_params = [expanded_query, expanded_query, kw_param, kw_param, kw_param]

            if pillar:
                sparse_sql += " AND pillar = %s"
                s_params.append(pillar)
            if facility_type:
                sparse_sql += " AND facility_type = %s"
                s_params.append(facility_type)

            sparse_sql += " ORDER BY trigram_sim DESC NULLS LAST LIMIT 20;"

            cur.execute(sparse_sql, tuple(s_params))
            sparse_results = cur.fetchall()

        # 2. Reciprocal Rank Fusion (RRF)
        # RRF_Score(d) = sum(1 / (k + rank_i(d)))
        doc_scores: Dict[str, Dict[str, Any]] = {}

        # Process dense ranks
        for rank, item in enumerate(dense_results, start=1):
            doc_id = str(item["id"])
            if doc_id not in doc_scores:
                doc_scores[doc_id] = {
                    "data": item,
                    "dense_score": float(item.get("cosine_sim", 0.0)),
                    "sparse_score": None,
                    "rrf": 0.0
                }
            doc_scores[doc_id]["rrf"] += 1.0 / (rrf_k + rank)

        # Process sparse ranks
        for rank, item in enumerate(sparse_results, start=1):
            doc_id = str(item["id"])
            if doc_id not in doc_scores:
                doc_scores[doc_id] = {
                    "data": item,
                    "dense_score": None,
                    "sparse_score": float(item.get("trigram_sim", 0.0)),
                    "rrf": 0.0
                }
            else:
                doc_scores[doc_id]["sparse_score"] = float(item.get("trigram_sim", 0.0))
            doc_scores[doc_id]["rrf"] += 1.0 / (rrf_k + rank)

        # 3. Sort by combined RRF score
        sorted_docs = sorted(doc_scores.values(), key=lambda x: x["rrf"], reverse=True)

        final_citations = []
        for entry in sorted_docs[:top_k]:
            raw = entry["data"]
            meta = raw.get("metadata", {})
            if isinstance(meta, str):
                import json
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}

            final_citations.append(LegalCitation(
                chunk_id=str(raw["id"]),
                document_title=raw["document_title"],
                regulation_code=raw["regulation_code"],
                chapter=raw.get("chapter"),
                article_number=raw.get("article_number"),
                pillar=raw.get("pillar"),
                facility_type=raw.get("facility_type"),
                content_text=raw["content_text"],
                metadata=meta,
                dense_score=entry["dense_score"],
                sparse_score=entry["sparse_score"],
                rrf_score=round(entry["rrf"], 6)
            ))

        return final_citations

    @staticmethod
    def format_citations_markdown(citations: List[LegalCitation]) -> str:
        """Formats citations into strict, verified markdown for LLM synthesis."""
        if not citations:
            return "Tidak ditemukan dasar regulasi yang spesifik."

        lines = ["### 📜 Rujukan Hukum Terverifikasi (National & DKI Regulations):"]
        for i, c in enumerate(citations, 1):
            ref_str = f"**[{i}] {c.regulation_code}** - {c.document_title}"
            if c.article_number:
                ref_str += f" ({c.chapter or ''} | {c.article_number})"
            lines.append(f"- {ref_str}")
            lines.append(f"  > *Kutipan:* {c.content_text}")
        return "\n".join(lines)
