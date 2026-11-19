import os
import secrets
import logging
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    PROJECT_NAME: str = "District Resource Profiling"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database Settings
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "127.0.0.1")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", 5432))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "district_profiling")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "postgres_spatial_dev")

    # Redis Cache Settings
    REDIS_HOST: str = os.getenv("REDIS_HOST", "127.0.0.1")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    REDIS_CACHE_TTL: int = 86400

    # Ambang dampak simulasi (lihat README). Nilai masih TODO-DECIDE (team).
    # Aturan Penilaian Dampak (TODO-DECIDE (team)):
    # - Rendah: delta > SIMULATION_IMPACT_DELTA_LOW (-1.0) DAN new_deficit_units <= SIMULATION_IMPACT_DEFICIT_LOW (0)
    # - Tinggi: delta <= SIMULATION_IMPACT_DELTA_HIGH (-5.0) ATAU new_deficit_units >= SIMULATION_IMPACT_DEFICIT_HIGH (3)
    # - Sedang: selain kondisi di atas
    SIMULATION_IMPACT_DELTA_LOW: float = -1.0 # TODO-DECIDE (team)
    SIMULATION_IMPACT_DEFICIT_LOW: int = 0    # TODO-DECIDE (team)
    SIMULATION_IMPACT_DELTA_HIGH: float = -5.0 # TODO-DECIDE (team)
    SIMULATION_IMPACT_DEFICIT_HIGH: int = 3   # TODO-DECIDE (team)
    SIMULATION_IMPACT_RULE: str = "Rendah: delta > -1.0 dan 0 unit defisit baru; Tinggi: delta <= -5.0 atau >= 3 unit defisit baru; Sedang: lainnya."
    SIMULATION_DISCLAIMER: str = "Bukan keputusan perizinan. Untuk bahan diskusi perencanaan."

    # Parameter asumsi simulasi superblok (lihat README)
    SUPERBLOCK_OCCUPANTS_PER_UNIT: float = 3.0
    SUPERBLOCK_SCHOOL_AGE_RATIO: float = 0.25 # ~25% usia sekolah (6-18 tahun)
    SUPERBLOCK_KDB_RATIO: float = 0.50 # Parameter asumsi, belum diverifikasi ke Perda 31/2022 (TODO-VERIFY)
    SUPERBLOCK_RTH_RATIO: float = 0.20 # Parameter asumsi, belum diverifikasi ke Perda 31/2022 (TODO-VERIFY)
    SUPERBLOCK_STORMWATER_DEPTH_M: float = 0.150 # Parameter asumsi, belum diverifikasi ke Perda 31/2022 (TODO-VERIFY)

    # Multi-Region Configuration (TODO-3)
    DEFAULT_PROVINCE_CODE: str = os.getenv("DEFAULT_PROVINCE_CODE", "31")
    DEFAULT_PROVINCE_NAME: str = os.getenv("DEFAULT_PROVINCE_NAME", "DKI Jakarta")

    # Authentication & Authorization Settings (TODO-4)
    AUTH_ALLOW_REGISTER: bool = os.getenv("AUTH_ALLOW_REGISTER", "true").lower() in ("true", "1", "yes")
    AUTH_JWT_SECRET: str = os.getenv("AUTH_JWT_SECRET", "")
    AUTH_JWT_ALGORITHM: str = "HS256"
    AUTH_JWT_EXPIRE_MINUTES: int = int(os.getenv("AUTH_JWT_EXPIRE_MINUTES", "60"))
    AUTH_PASSWORD_MIN_LENGTH: int = 10
    AUTH_CHAT_RATE_LIMIT_REQUESTS: int = int(os.getenv("AUTH_CHAT_RATE_LIMIT_REQUESTS", "20"))
    AUTH_CHAT_RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("AUTH_CHAT_RATE_LIMIT_WINDOW_SECONDS", "600"))
    AUTH_BRUTE_FORCE_MAX_ATTEMPTS: int = int(os.getenv("AUTH_BRUTE_FORCE_MAX_ATTEMPTS", "5"))
    AUTH_BRUTE_FORCE_LOCKOUT_SECONDS: int = int(os.getenv("AUTH_BRUTE_FORCE_LOCKOUT_SECONDS", "900"))

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
if not settings.AUTH_JWT_SECRET:
    settings.AUTH_JWT_SECRET = secrets.token_urlsafe(32)
    logger.warning(
        "AUTH_JWT_SECRET is not set in environment. Generated random ephemeral secret. "
        "Tokens will be invalidated on server restart."
    )

