"""
Regulatory hybrid RAG and legal provision retrieval endpoints.
"""

from typing import Optional
from fastapi import APIRouter, Query, Response, Depends
from backend.app.core.config import settings
from backend.app.api.deps import get_db_cursor, get_current_user
from backend.app.rag.hybrid_search import (
    HybridRegulationRetriever,
)
from backend.app.api.schemas import HybridSearchRequest

router = APIRouter()


@router.post(
    f"{settings.API_V1_STR}/rag/search",
    tags=["Regulatory RAG"],
    summary="Pencarian leksikal (trigram + hashed bag-of-words + sinonim)",
)
def search_regulations(
    req: HybridSearchRequest, current_user: dict = Depends(get_current_user)
):
    """
    Pencarian leksikal (trigram + hashed bag-of-words + sinonim) pada standar nasional dan regulasi tata ruang.
    Menggabungkan vektor fitur leksikal ter-hash via pgvector dan kemiripan trigram via Reciprocal Rank Fusion (RRF).
    Target endpoint aligned with README.revised.md §13.
    """
    citations = HybridRegulationRetriever.search_regulations(
        query=req.query,
        pillar=req.pillar,
        facility_type=req.facility_type,
        top_k=req.top_k,
    )
    markdown_summary = HybridRegulationRetriever.format_citations_markdown(citations)

    return {
        "query": req.query,
        "total_results": len(citations),
        "citations": [c.model_dump() for c in citations],
        "citations_markdown": markdown_summary,
    }


@router.post(
    f"{settings.API_V1_STR}/rag/hybrid-search",
    tags=["Regulatory RAG"],
    summary="Pencarian leksikal (alias deprecated)",
    deprecated=True,
)
def hybrid_search_regulations_alias(
    req: HybridSearchRequest,
    response: Response,
    current_user: dict = Depends(get_current_user),
):
    """
    Deprecated alias for /api/v1/rag/search (README.revised.md §13).
    """
    response.headers["Deprecation"] = "true"
    return search_regulations(req, current_user=current_user)


@router.get(f"{settings.API_V1_STR}/rag/legal-chunks", tags=["Regulatory RAG"])
def search_regulatory_chunks(
    query: Optional[str] = Query(
        None, description="Keywords to match legal provisions"
    ),
    pillar: Optional[str] = None,
):
    """Retrieves legal regulation chunks (SNI 03-1733-2004 & Perda RDTR) for verified legal grounds."""
    sql = """
        SELECT document_title, regulation_code, chapter, article_number,
               pillar, facility_type, content_text, metadata
        FROM regulatory_chunks
        WHERE 1=1
    """
    params = []

    if pillar:
        sql += " AND pillar = %s"
        params.append(pillar)

    if query:
        sql += " AND content_text ILIKE %s"
        params.append(f"%{query}%")

    sql += " LIMIT 20;"

    with get_db_cursor() as cur:
        cur.execute(sql, tuple(params) if params else None)
        rows = cur.fetchall()
        return {"total": len(rows), "chunks": rows}
