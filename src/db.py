import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

DB_PATH = Path("data") / "app.db"


def get_conn() -> sqlite3.Connection:
    """Return a SQLite connection (ensures folder exists)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_users_schema(conn: sqlite3.Connection) -> None:
    """
    Lightweight migration for older DBs created before must_reset_password existed.
    """
    cols = conn.execute("PRAGMA table_info(users);").fetchall()
    col_names = {str(c["name"]) for c in cols}
    if "must_reset_password" not in col_names:
        conn.execute(
            "ALTER TABLE users ADD COLUMN must_reset_password INTEGER NOT NULL DEFAULT 0;"
        )


def init_db() -> None:
    """Create tables if they do not exist (and run light migrations)."""
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

        _ensure_users_schema(conn)

        # Scorecards uploaded for fixtures/results.
        # One row per uploaded file (PDF or image).
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


# -----------------------------
# Admin/user management helpers
# -----------------------------
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


def count_admins(active_only: bool = False) -> int:
    """
    Count admins. If active_only=True, count only active admins.
    Use active_only=False for 'last admin in system' checks.
    """
    conn = get_conn()
    try:
        if active_only:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND is_active=1;"
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS n FROM users WHERE role='admin';").fetchone()
        return int(row["n"])
    finally:
        conn.close()


def set_user_active(username: str, is_active: bool) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE users SET is_active = ? WHERE username = ?;",
            (1 if is_active else 0, username),
        )
        conn.commit()
    finally:
        conn.close()


def set_user_role(username: str, role: str) -> None:
    if role not in ("admin", "player"):
        raise ValueError("Role must be 'admin' or 'player'.")
    conn = get_conn()
    try:
        conn.execute("UPDATE users SET role = ? WHERE username = ?;", (role, username))
        conn.commit()
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


def delete_user(username: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM users WHERE username = ?;", (username,))
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
    Restore users into an EMPTY users table.

    Passwords are NOT restored; all users get default_password_hash and
    must_reset_password is set to 1 if force_reset=True.

    Returns number of users inserted.
    """
    users = payload.get("users") or []
    if not isinstance(users, list):
        raise ValueError("Invalid backup payload: users must be a list.")

    conn = get_conn()
    inserted = 0
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM users;").fetchone()["n"]
        if int(n) != 0:
            return 0

        now_iso = datetime.now(timezone.utc).isoformat()
        for u in users:
            first_name = str(u.get("first_name", "")).strip()
            last_name = str(u.get("last_name", "")).strip()
            username = str(u.get("username", "")).strip()
            role = str(u.get("role", "player")).strip() or "player"
            is_active = int(u.get("is_active", 1))
            created_at = str(u.get("created_at", "")).strip() or now_iso

            if not username:
                continue
            if role not in ("admin", "player"):
                role = "player"
            if is_active not in (0, 1):
                is_active = 1

            conn.execute(
                """
                INSERT INTO users
                    (first_name, last_name, username, password_hash, role, is_active, created_at, must_reset_password)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    first_name or " ",
                    last_name or " ",
                    username,
                    default_password_hash,
                    role,
                    is_active,
                    created_at,
                    1 if force_reset else 0,
                ),
            )
            inserted += 1

        conn.commit()
        return inserted
    finally:
        conn.close()


# -----------------------------
# Scorecard helpers
# -----------------------------
def add_scorecard(
    match_id: str,
    file_name: str,
    dropbox_path: str,
    uploaded_at: str,
    uploaded_by: Optional[str] = None,
) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO scorecards (match_id, file_name, dropbox_path, uploaded_by, uploaded_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (match_id, file_name, dropbox_path, uploaded_by, uploaded_at),
        )
        conn.commit()
    finally:
        conn.close()


def list_scorecards(match_id: str):
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT scorecard_id, match_id, file_name, dropbox_path, uploaded_by, uploaded_at
            FROM scorecards
            WHERE match_id = ?
            ORDER BY uploaded_at DESC, scorecard_id DESC;
            """,
            (match_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_scorecard_match_ids() -> list[str]:
    """
    Return distinct match_ids that have at least one scorecard record.
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT match_id
            FROM scorecards
            ORDER BY match_id;
            """
        ).fetchall()
        return [str(r[0]) for r in rows if r[0] is not None]
    finally:
        conn.close()


def delete_scorecard_by_path(dropbox_path: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM scorecards WHERE dropbox_path = ?;", (dropbox_path,))
        conn.commit()
    finally:
        conn.close()


def delete_scorecards_for_match(match_id: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM scorecards WHERE match_id = ?;", (match_id,))
        conn.commit()
    finally:
        conn.close()