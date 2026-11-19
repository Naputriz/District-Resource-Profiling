"""
Pydantic schemas used across API routers.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


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
