#!/usr/bin/env python3
"""
CLI script to create or update users in the app_users table.
Usage:
    python scripts/create_user.py --email admin@example.com --password secretpass123 --display-name "Admin DRP" --role admin
"""

import sys
import argparse
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.core.config import settings
from backend.app.core.db import get_db_cursor
from backend.app.core.auth import hash_password


def create_user(email: str, password: str, display_name: str, role: str = "user"):
    clean_email = email.lower().strip()
    clean_name = display_name.strip()

    if not clean_email or "@" not in clean_email:
        print(f"Error: Format email '{email}' tidak valid.", file=sys.stderr)
        sys.exit(1)

    if len(password) < settings.AUTH_PASSWORD_MIN_LENGTH:
        print(
            f"Error: Kata sandi minimal {settings.AUTH_PASSWORD_MIN_LENGTH} karakter.",
            file=sys.stderr,
        )
        sys.exit(1)

    if role not in ("user", "admin"):
        print(f"Error: Role harus 'user' atau 'admin', bukan '{role}'.", file=sys.stderr)
        sys.exit(1)

    hashed = hash_password(password)

    with get_db_cursor() as cur:
        # Check if user already exists
        cur.execute(
            "SELECT id FROM app_users WHERE LOWER(email) = LOWER(%s);",
            (clean_email,),
        )
        existing = cur.fetchone()

        if existing:
            # Update user
            cur.execute(
                """
                UPDATE app_users
                SET password_hash = %s, display_name = %s, role = %s, is_active = TRUE
                WHERE id = %s
                RETURNING id, email, display_name, role;
                """,
                (hashed, clean_name, role, existing["id"]),
            )
            user = cur.fetchone()
            print(f"User updated successfully: id={user['id']}, email={user['email']}, role={user['role']}")
        else:
            cur.execute(
                """
                INSERT INTO app_users (email, password_hash, display_name, role)
                VALUES (%s, %s, %s, %s)
                RETURNING id, email, display_name, role;
                """,
                (clean_email, hashed, clean_name, role),
            )
            user = cur.fetchone()
            print(f"User created successfully: id={user['id']}, email={user['email']}, role={user['role']}")


def main():
    parser = argparse.ArgumentParser(description="Admin user creation CLI for District Resource Profiling")
    parser.add_argument("--email", required=True, help="User email address")
    parser.add_argument("--password", required=True, help="Password (min 10 characters)")
    parser.add_argument("--display-name", "--display_name", required=True, dest="display_name", help="Display name")
    parser.add_argument("--role", default="user", choices=["user", "admin"], help="User role (user or admin)")

    args = parser.parse_args()
    create_user(args.email, args.password, args.display_name, args.role)


if __name__ == "__main__":
    main()
