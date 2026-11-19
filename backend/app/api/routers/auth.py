"""
Authentication and User Management Router (TODO-4).
Provides:
- POST /api/v1/auth/register (Public or disabled via AUTH_ALLOW_REGISTER)
- POST /api/v1/auth/login (JWT token issue with brute-force protection)
- GET /api/v1/auth/me (Current user profile with exposed rate-limit assumptions)
- POST /api/v1/auth/logout (Stateless JWT drop acknowledgement)
"""

import re
from fastapi import APIRouter, Depends, HTTPException, Request, status
from backend.app.core.config import settings
from backend.app.core.db import get_db_cursor
from backend.app.core.auth import (
    hash_password,
    verify_password,
    create_access_token,
    is_brute_force_locked,
    record_failed_login,
    reset_failed_login,
    get_client_ip,
    _DUMMY_BCRYPT_HASH,
)
from backend.app.api.deps import get_current_user
from backend.app.api.schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    UserInfo,
    TokenResponse,
    UserProfileResponse,
    UserLimits,
)

router = APIRouter()


@router.post(
    f"{settings.API_V1_STR}/auth/register",
    response_model=UserInfo,
    status_code=status.HTTP_201_CREATED,
    tags=["Authentication"],
    summary="Daftar akun baru",
)
def register_user(req: UserRegisterRequest):
    """
    Mendaftarkan pengguna baru dengan email dan kata sandi.
    Dapat dinonaktifkan menggunakan konfigurasi AUTH_ALLOW_REGISTER=false.
    """
    if not settings.AUTH_ALLOW_REGISTER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pendaftaran pengguna baru dinonaktifkan.",
        )

    clean_email = str(req.email).lower().strip()
    clean_display_name = req.display_name.strip()

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean_email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Format email tidak valid.",
        )

    if not clean_display_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nama tampilan tidak boleh kosong.",
        )

    # Check email uniqueness (case-insensitive)
    with get_db_cursor() as cur:
        cur.execute(
            "SELECT id FROM app_users WHERE LOWER(email) = LOWER(%s);",
            (clean_email,),
        )
        if cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email sudah terdaftar.",
            )

        hashed = hash_password(req.password)

        cur.execute(
            """
            INSERT INTO app_users (email, password_hash, display_name, role)
            VALUES (%s, %s, %s, 'user')
            RETURNING id, email, display_name, role, created_at;
            """,
            (clean_email, hashed, clean_display_name),
        )
        user = cur.fetchone()

        return UserInfo(
            id=str(user["id"]),
            email=user["email"],
            display_name=user["display_name"],
            role=user["role"],
        )


@router.post(
    f"{settings.API_V1_STR}/auth/login",
    response_model=TokenResponse,
    tags=["Authentication"],
    summary="Masuk dan peroleh access token JWT",
)
def login_user(req: UserLoginRequest, request: Request):
    """
    Autentikasi menggunakan email dan kata sandi.
    Dilindungi perlindungan brute-force per-email dan per-IP.
    Pesan kegagalan identik untuk email tidak terdaftar dan sandi salah.
    """
    client_ip = get_client_ip(request)
    clean_email = req.email.lower().strip()

    if is_brute_force_locked(clean_email, client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Terlalu banyak percobaan gagal. Silakan coba beberapa saat lagi.",
        )

    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT id, email, password_hash, display_name, role, is_active
            FROM app_users
            WHERE LOWER(email) = LOWER(%s);
            """,
            (clean_email,),
        )
        user = cur.fetchone()

        # Identical error message for unknown email, inactive user, and wrong password
        # Always run verify_password even if user does not exist to ensure constant timing
        target_hash = user["password_hash"] if user else _DUMMY_BCRYPT_HASH
        password_ok = verify_password(req.password, target_hash)

        if not user or not user["is_active"] or not password_ok:
            record_failed_login(clean_email, client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email atau kata sandi salah.",
            )

        # Success: reset brute force counters and update last login
        reset_failed_login(clean_email, client_ip)
        cur.execute(
            "UPDATE app_users SET last_login_at = CURRENT_TIMESTAMP WHERE id = %s;",
            (user["id"],),
        )

        expires_delta = None
        expires_in = settings.AUTH_JWT_EXPIRE_MINUTES * 60
        token = create_access_token(
            {
                "sub": str(user["id"]),
                "email": user["email"],
                "role": user["role"],
            },
            expires_delta=expires_delta,
        )

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
            user=UserInfo(
                id=str(user["id"]),
                email=user["email"],
                display_name=user["display_name"],
                role=user["role"],
            ),
        )


@router.get(
    f"{settings.API_V1_STR}/auth/me",
    response_model=UserProfileResponse,
    tags=["Authentication"],
    summary="Profil pengguna terautentikasi dan batas rate limit",
)
def get_my_profile(current_user: dict = Depends(get_current_user)):
    """
    Mengambil data profil pengguna yang sedang login.
    Mengekspos konstanta asumsi rate limit (Engineering Rule 6).
    """
    return UserProfileResponse(
        id=str(current_user["id"]),
        email=current_user["email"],
        display_name=current_user["display_name"],
        role=current_user["role"],
        limits=UserLimits(
            chat_requests_limit=settings.AUTH_CHAT_RATE_LIMIT_REQUESTS,
            chat_window_minutes=settings.AUTH_CHAT_RATE_LIMIT_WINDOW_SECONDS // 60,
        ),
    )


@router.post(
    f"{settings.API_V1_STR}/auth/logout",
    tags=["Authentication"],
    summary="Keluar dari sesi",
)
def logout_user():
    """
    Logout pengguna.
    Karena menggunakan stateless JWT, token dihapus pada sisi klien (sessionStorage).
    Endpoint ini mengembalikan konfirmasi standar.
    """
    return {"detail": "Berhasil keluar."}
