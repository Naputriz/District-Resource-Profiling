"""
Cognitive Spatial AI assistant chat endpoints.
Protected with JWT authentication, per-user rate limiting, and privacy audit logging.
"""

import logging
from fastapi import APIRouter, Response, Depends, HTTPException, status
from backend.app.core.config import settings
from backend.app.core.auth import check_chat_rate_limit, record_chat_audit
from backend.app.api.deps import get_current_user
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

    response = agent_orchestrator.process_chat(req)

    # Privacy audit record: no raw prompt or user text is stored.
    # Audit logging must NEVER break a chat response.
    try:
        q_len = sum(len(m.content) for m in req.messages if m.content)
        tools_used = [
            tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            for tc in (response.tool_calls_executed or [])
        ]
        tools_used = [t for t in tools_used if t]
        user_audit_id = (
            None if current_user.get("is_service") else current_user.get("id")
        )
        record_chat_audit(user_audit_id, q_len, tools_used, response.guardrail)
    except Exception as exc:
        logger.warning("Failed to record chat audit: %s", exc)

    return response


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
