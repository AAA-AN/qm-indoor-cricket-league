import sqlite3
import json
from pathlib import Path
from typing import List, Optional, Dict, Any

DB_PATH = Path("data") / "app.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_users_schema(conn: sqlite3.Connection) -> None:
    """
    Lightweight migration: ensure must_reset_password exists.
    """
    cols = conn.execute("PRAGMA table_info(users);").fetchall()
    col_names = {str(c["name"]) for c in cols}
    if "must_reset_password" not in col_names:
        conn.execute(
            "ALTER TABLE users ADD COLUMN must_reset_password INTEGER NOT NULL DEFAULT 0;"
        )


def init_db() -> None:
    conn = get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','player')),
                is_active INTEGER NOT NULL CHECK(is_active IN (0,1)),
                created_at TEXT NOT NULL,
                must_reset_password INTEGER NOT NULL DEFAULT 0 CHECK(must_reset_password IN (0,1))
            );
            """
        )

        # Ensure migration for older DBs (created before must_reset_password existed)
        _ensure_users_schema(conn)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scorecards (
                scorecard_id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                dropbox_path TEXT NOT NULL UNIQUE,
                uploaded_by TEXT,
                uploaded_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_scorecards_match_id
            ON scorecards(match_id);
            """
        )
        conn.commit()
    finally:
        conn.close()


def count_users() -> int:
    conn = get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM users;").fetchone()
        return int(row["n"])
    finally:
        conn.close()


def list_users() -> List[Dict[str, Any]]:
    """Return all users (excluding password_hash)."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT user_id, first_name, last_name, username, role, is_active, created_at, must_reset_password
            FROM users
            ORDER BY created_at ASC, user_id ASC;
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT user_id, first_name, last_name, username, role, is_active, created_at, must_reset_password
            FROM users
            WHERE username = ?;
            """,
            (username,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_password_hash(username: str, password_hash: str) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?;",
            (password_hash, username),
        )
        conn.commit()
    finally:
        conn.close()


def set_must_reset_password(username: str, must_reset: bool) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE users SET must_reset_password = ? WHERE username = ?;",
            (1 if must_reset else 0, username),
        )
        conn.commit()
    finally:
        conn.close()


# -----------------------------
# Backup / restore helpers
# -----------------------------
def export_users_backup_payload() -> Dict[str, Any]:
    """
    Export user records WITHOUT password hashes.
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT first_name, last_name, username, role, is_active, created_at
            FROM users
            ORDER BY created_at ASC, user_id ASC;
            """
        ).fetchall()
        users = [dict(r) for r in rows]
        return {"version": 1, "users": users}
    finally:
        conn.close()


def restore_users_from_backup_payload(
    payload: Dict[str, Any],
    *,
    default_password_hash: str,
    force_reset: bool = True,
) -> int:
    """
    Restore users into an EMPTY database.
    Password hashes are NOT restored; everyone gets default_password_hash.
    """
    users = payload.get("users") or []
    if not isinstance(users, list):
        raise ValueError("Invalid backup payload: users must be a list.")

    conn = get_conn()
    try:
        # Safety: only restore into empty users table
        n = conn.execute("SELECT COUNT(*) AS n FROM users;").fetchone()["n"]
        if int(n) != 0:
            return 0

        to_insert = []
        for u in users:
            to_insert.append(
                (
                    str(u.get("first_name", "")).strip(),
                    str(u.get("last_name", "")).strip(),
                    str(u.get("username", "")).strip(),
                    default_password_hash,
                    str(u.get("role", "player")).strip() or "player",
                    int(u.get("is_active", 1)),
                    str(u.get("created_at", "")).strip() or "",
                    1 if force_reset else 0,
                )
            )

        conn.executemany(
            """
            INSERT INTO users
                (first_name, last_name, username, password_hash, role, is_active, created_at, must_reset_password)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            to_insert,
        )
        conn.commit()
        return len(to_insert)
    finally:
        conn.close()