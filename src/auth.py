from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any

import bcrypt

from src.db import (
    get_conn,
    count_users,
    update_password_hash,
    set_must_reset_password,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pw, salt)
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def create_user(first_name: str, last_name: str, username: str, password: str) -> Dict[str, Any]:
    """
    Creates a user.
    First user becomes admin; subsequent users become player.
    """
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    username = (username or "").strip()

    if not first_name or not last_name or not username or not password:
        raise ValueError("All fields are required.")

    role = "admin" if count_users() == 0 else "player"
    pw_hash = hash_password(password)

    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO users (first_name, last_name, username, password_hash, role, is_active, created_at, must_reset_password)
            VALUES (?, ?, ?, ?, ?, 1, ?, 0);
            """,
            (first_name, last_name, username, pw_hash, role, _now_iso()),
        )
        conn.commit()

        row = conn.execute(
            """
            SELECT user_id, first_name, last_name, username, role, is_active, created_at, must_reset_password
            FROM users
            WHERE username = ?;
            """,
            (username,),
        ).fetchone()

        return dict(row)
    finally:
        conn.close()


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    username = (username or "").strip()
    if not username or not password:
        return None

    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT user_id, first_name, last_name, username, password_hash, role, is_active, created_at, must_reset_password
            FROM users
            WHERE username = ?;
            """,
            (username,),
        ).fetchone()

        if row is None:
            return None
        if int(row["is_active"]) != 1:
            return None
        if not verify_password(password, row["password_hash"]):
            return None

        user = dict(row)
        user.pop("password_hash", None)
        return user
    finally:
        conn.close()


def change_password(username: str, new_password: str) -> None:
    """
    Used for the forced reset flow (and can be reused for a future "change password" page).
    Clears must_reset_password.
    """
    username = (username or "").strip()
    if not username or not new_password:
        raise ValueError("Username and new password are required.")

    pw_hash = hash_password(new_password)
    update_password_hash(username, pw_hash)
    set_must_reset_password(username, False)


def admin_reset_password(username: str, new_password: str) -> None:
    """
    Admin-only: reset a user's password.
    The Admin page is responsible for ensuring the caller is an admin.

    Recommended behaviour: if an admin resets a password, force the user to change it on next login.
    """
    username = (username or "").strip()
    if not username or not new_password:
        raise ValueError("Username and new password are required.")

    pw_hash = hash_password(new_password)
    update_password_hash(username, pw_hash)
    set_must_reset_password(username, True)
