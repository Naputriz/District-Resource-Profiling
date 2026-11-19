"""
Cognitive Spatial AI assistant chat endpoints.
"""

from fastapi import APIRouter, Response
from backend.app.core.config import settings
from backend.app.agent.orchestrator import (
    CognitiveSpatialAgentOrchestrator,
    AgentChatRequest,
    AgentChatResponse,
)

router = APIRouter()

agent_orchestrator = CognitiveSpatialAgentOrchestrator()


@router.post(
    f"{settings.API_V1_STR}/chat",
    response_model=AgentChatResponse,
    tags=["Cognitive Spatial AI"],
)
def chat_with_spatial_agent(req: AgentChatRequest):
    """
    Interactive conversation with Cognitive Spatial AI Assistant.
    Powered by local LLM (Qwen 2.5 14B).
    Performs deterministic text-to-spatial tool calling, regulation citations,
    and returns Map Action events for dual-view sync.
    Target endpoint aligned with README.revised.md §13.
    """
    response = agent_orchestrator.process_chat(req)
    return response


@router.post(
    f"{settings.API_V1_STR}/chat/conversation",
    response_model=AgentChatResponse,
    tags=["Cognitive Spatial AI"],
    deprecated=True,
)
def chat_with_spatial_agent_alias(req: AgentChatRequest, response: Response):
    """
    Deprecated alias for /api/v1/chat (README.revised.md §13).
    """
    response.headers["Deprecation"] = "true"
    return chat_with_spatial_agent(req)
