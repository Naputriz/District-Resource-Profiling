"""
Shared dependencies and database helpers for API routers.
Provides authentication & principal resolution for user & service clients.
"""

import os
from typing import Dict, Any, Optional
from fastapi import Request, HTTPException, status
from backend.app.core.db import get_db_cursor, get_redis_client
from backend.app.core.auth import decode_access_token

AUTH_REQUIRED_MESSAGE = "Login diperlukan untuk memakai simulasi dan asisten AI."


def get_current_user(request: Request) -> Dict[str, Any]:
    """
    Resolves the current authenticated principal.
    Supports:
    1. Machine client with valid X-API-Key header matching API_KEY.
    2. User with Bearer JWT access token.
    Raises 401 on invalid or missing credentials.
    """
    api_key = os.getenv("API_KEY")
    client_api_key = request.headers.get("X-API-Key")

    # If client supplied X-API-Key
    if client_api_key:
        if api_key and client_api_key == api_key:
            return {
                "id": "00000000-0000-0000-0000-000000000000",
                "email": "service@drp.local",
                "display_name": "Service Principal",
                "role": "admin",
                "is_service": True,
            }
        if api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Invalid or missing X-API-Key header",
            )

    # Check Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            payload = decode_access_token(token)
            user_id = payload.get("sub")
            if not user_id:
                raise ValueError("Missing subject")

            # Service principal token signed with server secret (no DB lookup, rate-limit exempt)
            if user_id == "00000000-0000-0000-0000-000000000000" and payload.get("is_service") is True:
                return {
                    "id": "00000000-0000-0000-0000-000000000000",
                    "email": payload.get("email", "service@drp.local"),
                    "display_name": "Service Principal",
                    "role": payload.get("role", "admin"),
                    "is_service": True,
                }

            with get_db_cursor() as cur:
                cur.execute(
                    "SELECT id, email, display_name, role, is_active FROM app_users WHERE id = %s;",
                    (user_id,),
                )
                user = cur.fetchone()
                if not user or not user["is_active"]:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=AUTH_REQUIRED_MESSAGE,
                    )
                return dict(user)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AUTH_REQUIRED_MESSAGE,
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AUTH_REQUIRED_MESSAGE,
    )


def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    """Resolves authenticated principal if credentials exist, otherwise returns None."""
    try:
        return get_current_user(request)
    except HTTPException:
        return None


__all__ = [
    "get_db_cursor",
    "get_redis_client",
    "get_current_user",
    "get_optional_user",
    "AUTH_REQUIRED_MESSAGE",
]
