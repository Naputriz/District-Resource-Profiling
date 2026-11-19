"""
FastAPI route modules for District Resource Profiling backend.
"""

from backend.app.api.routers import (
    meta,
    districts,
    spatial,
    simulation,
    rag,
    chat,
    watchdog,
    auth,
)

__all__ = [
    "meta",
    "districts",
    "spatial",
    "simulation",
    "rag",
    "chat",
    "watchdog",
    "auth",
]
