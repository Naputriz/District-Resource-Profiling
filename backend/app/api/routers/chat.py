"""
Cognitive Spatial AI assistant chat endpoints.
Protected with JWT authentication, per-user rate limiting, privacy audit logging,
and authenticated user chat history logging.
"""

import logging
import time
from fastapi import APIRouter, Response, Depends, HTTPException, Query, status
from backend.app.core.config import settings
from backend.app.core.auth import check_chat_rate_limit, record_chat_audit, record_chat_log
from backend.app.api.deps import get_current_user, get_db_cursor
from backend.app.api.schemas import (
    ChatLogEntry,
    ChatHistoryResponse,
    ChatHistoryDeleteResponse,
)
from backend.app.agent.orchestrator import (
    CognitiveSpatialAgentOrchestrator,
    AgentChatRequest,
    AgentChatResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

agent_orchestrator = CognitiveSpatialAgentOrchestrator()


@router.post(
    f"{settings.API_V1_STR}/chat",
    response_model=AgentChatResponse,
    tags=["Cognitive Spatial AI"],
)
def chat_with_spatial_agent(
    req: AgentChatRequest, current_user: dict = Depends(get_current_user)
):
    """
    Interactive conversation with Cognitive Spatial AI Assistant.
    Powered by local LLM (Qwen 2.5 14B).
    Performs deterministic text-to-spatial tool calling, regulation citations,
    and returns Map Action events for dual-view sync.
    Target endpoint aligned with README.md §13.
    """
    # Enforce per-user rate limit for regular authenticated users (bypass for service principal)
    if not current_user.get("is_service"):
        user_id = str(current_user["id"])
        allowed, remaining = check_chat_rate_limit(user_id)
        if not allowed:
            window_mins = settings.AUTH_CHAT_RATE_LIMIT_WINDOW_SECONDS // 60
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Batas penggunaan asisten AI tercapai ({settings.AUTH_CHAT_RATE_LIMIT_REQUESTS} permintaan / {window_mins} menit). Silakan coba beberapa saat lagi.",
            )

    t0 = time.perf_counter()
    response = agent_orchestrator.process_chat(req)
    latency_ms = int(round((time.perf_counter() - t0) * 1000))

    tools_used = [
        tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
        for tc in (response.tool_calls_executed or [])
    ]
    tools_used = [t for t in tools_used if t]

    # Privacy audit record (chat_audit): no raw prompt or user text is stored; full turns go to chat_logs.
    # Audit logging must NEVER break a chat response.
    try:
        q_len = sum(len(m.content) for m in req.messages if m.content)
        user_audit_id = (
            None if current_user.get("is_service") else current_user.get("id")
        )
        record_chat_audit(user_audit_id, q_len, tools_used, response.guardrail)
    except Exception as exc:
        logger.warning("Failed to record chat audit: %s", exc)

    # Full prompt & response log for authenticated users only (skip service principal).
    if not current_user.get("is_service") and current_user.get("id"):
        try:
            last_user_prompt = next(
                (m.content for m in reversed(req.messages) if m.role == "user" and m.content is not None),
                "",
            )
            record_chat_log(
                user_id=str(current_user["id"]),
                province_code=req.province_code,
                prompt=last_user_prompt,
                response=response.reply or "",
                tools_used=tools_used,
                guardrail_status=response.guardrail,
                latency_ms=latency_ms,
                model=getattr(response, "model_used", None),
            )
        except Exception as exc:
            logger.warning("Failed to record chat log: %s", exc)

    return response


@router.get(
    f"{settings.API_V1_STR}/chat/history",
    response_model=ChatHistoryResponse,
    tags=["Cognitive Spatial AI"],
)
def get_chat_history(
    limit: int = Query(20, ge=1),
    current_user: dict = Depends(get_current_user),
):
    """
    Returns the authenticated caller's chat history, newest first (max 100 rows).
    """
    effective_limit = min(limit, 100)
    if current_user.get("is_service"):
        return ChatHistoryResponse(
            total=0,
            retention_days=settings.CHAT_LOG_RETENTION_DAYS,
            items=[],
        )

    user_id = str(current_user["id"])
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT id, created_at, province_code, prompt, response,
                   tools_used, guardrail_status, latency_ms
            FROM chat_logs
            WHERE user_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s;
            """,
            (user_id, effective_limit),
        )
        rows = cur.fetchall()

    items = [
        ChatLogEntry(
            id=str(row["id"]),
            created_at=row["created_at"],
            province_code=row["province_code"],
            prompt=row["prompt"],
            response=row["response"],
            tools_used=list(row["tools_used"] or []),
            guardrail_status=row["guardrail_status"],
            latency_ms=row["latency_ms"],
        )
        for row in rows
    ]
    return ChatHistoryResponse(
        total=len(items),
        retention_days=settings.CHAT_LOG_RETENTION_DAYS,
        items=items,
    )


@router.delete(
    f"{settings.API_V1_STR}/chat/history",
    response_model=ChatHistoryDeleteResponse,
    tags=["Cognitive Spatial AI"],
)
def delete_chat_history(
    current_user: dict = Depends(get_current_user),
):
    """
    Deletes all chat_logs rows belonging to the authenticated caller.
    """
    if current_user.get("is_service"):
        return ChatHistoryDeleteResponse(deleted_count=0)

    user_id = str(current_user["id"])
    with get_db_cursor() as cur:
        cur.execute(
            "DELETE FROM chat_logs WHERE user_id = %s;",
            (user_id,),
        )
        deleted_count = cur.rowcount or 0
    return ChatHistoryDeleteResponse(deleted_count=deleted_count)


@router.post(
    f"{settings.API_V1_STR}/chat/conversation",
    response_model=AgentChatResponse,
    tags=["Cognitive Spatial AI"],
    deprecated=True,
)
def chat_with_spatial_agent_alias(
    req: AgentChatRequest,
    response: Response,
    current_user: dict = Depends(get_current_user),
):
    """
    Deprecated alias for /api/v1/chat (README.md §13).
    """
    response.headers["Deprecation"] = "true"
    return chat_with_spatial_agent(req, current_user=current_user)
