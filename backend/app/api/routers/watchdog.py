"""
Observability & autonomous watchdog telemetry and incident ledger endpoints.
"""

from fastapi import APIRouter, Query
from backend.app.core.config import settings
from backend.app.api.deps import get_db_cursor
from watchdog.agent import get_watchdog_telemetry

router = APIRouter()


@router.get(
    f"{settings.API_V1_STR}/watchdog/telemetry", tags=["Observability & Watchdog"]
)
def get_system_telemetry():
    """Returns live hardware (GPU VRAM, Temp, Power), container status & AI status."""
    return get_watchdog_telemetry()


@router.get(
    f"{settings.API_V1_STR}/watchdog/incidents", tags=["Observability & Watchdog"]
)
def get_incident_audit_trail(limit: int = Query(20, le=100)):
    """Returns historical incident audit ledger from incident_logs table."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT id, incident_type, severity, target_service, action_taken,
                   status, gpu_temperature_celsius, vram_used_mb, error_payload, created_at
            FROM incident_logs
            ORDER BY created_at DESC
            LIMIT %s;
        """,
            (limit,),
        )
        rows = cur.fetchall()
        return {"total": len(rows), "incidents": rows}
