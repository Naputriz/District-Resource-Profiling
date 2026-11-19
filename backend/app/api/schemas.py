"""
Pydantic schemas used across API routers.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class UserRegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=10, description="Minimal 10 karakter")
    display_name: str = Field(..., min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Kata sandi maksimal 72 byte UTF-8.")
        return v


class UserLoginRequest(BaseModel):
    email: str
    password: str


class UserInfo(BaseModel):
    id: str
    email: str
    display_name: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserInfo


class UserLimits(BaseModel):
    chat_requests_limit: int
    chat_window_minutes: int
    chat_log_retention_days: int = 90


class UserProfileResponse(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    limits: UserLimits


class ChatLogEntry(BaseModel):
    id: str
    created_at: datetime
    province_code: Optional[str] = None
    prompt: str
    response: str
    tools_used: List[str] = []
    guardrail_status: Optional[str] = None
    latency_ms: Optional[int] = None


class ChatHistoryResponse(BaseModel):
    total: int
    retention_days: int
    items: List[ChatLogEntry]


class ChatHistoryDeleteResponse(BaseModel):
    deleted_count: int



class BlankSpotSimRequest(BaseModel):
    district_code: str
    facility_type: str
    hypothetical_coordinates: List[float] = Field(
        ..., min_items=2, max_items=2, description="[longitude, latitude]"
    )
    custom_radius_meters: Optional[int] = None


class HybridSearchRequest(BaseModel):
    query: str
    pillar: Optional[str] = None
    facility_type: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
