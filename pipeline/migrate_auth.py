#!/usr/bin/env python3
"""
Database Migration: Authentication & Authorization Schema (TODO-4).
Creates app_users and chat_audit tables idempotently.
Never alters or drops master tables (kecamatan, public_facilities, etc.).
"""

import sys
import psycopg2
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.core.config import settings


def migrate_auth_schema():
    host = settings.POSTGRES_HOST
    if not host or host == "localhost":
        host = "127.0.0.1"

    print(f"Connecting to database {settings.POSTGRES_DB} on {host}:{settings.POSTGRES_PORT} as {settings.POSTGRES_USER}...")
    conn = psycopg2.connect(
        host=host,
        port=settings.POSTGRES_PORT,
        dbname=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )
    conn.autocommit = True

    with conn.cursor() as cur:
        print("Applying auth migration: app_users table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email VARCHAR(255) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(100) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                last_login_at TIMESTAMP WITH TIME ZONE,
                is_active BOOLEAN NOT NULL DEFAULT TRUE
            );
        """)

        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_app_users_email_lower 
            ON app_users (LOWER(email));
        """)

        print("Applying auth migration: chat_audit table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_audit (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID REFERENCES app_users(id) ON DELETE SET NULL,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                question_length INT NOT NULL,
                tools_used TEXT[] DEFAULT '{}',
                guardrail_status VARCHAR(50)
            );
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_audit_user_id ON chat_audit (user_id);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_audit_timestamp ON chat_audit (timestamp DESC);
        """)

        print("Applying auth migration: chat_logs table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID REFERENCES app_users(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ DEFAULT now(),
                province_code VARCHAR(2),
                prompt TEXT NOT NULL,
                response TEXT NOT NULL,
                tools_used TEXT[] DEFAULT '{}',
                guardrail_status VARCHAR(50),
                latency_ms INT,
                model VARCHAR(100)
            );
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_logs_user_created
            ON chat_logs (user_id, created_at DESC);
        """)

        # Verification check
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name IN ('app_users', 'chat_audit', 'chat_logs');
        """)
        tables = [row[0] for row in cur.fetchall()]
        print(f"Migration successful! Verified tables exist: {tables}")

    conn.close()


if __name__ == "__main__":
    migrate_auth_schema()
