import sqlite3
from pathlib import Path
from typing import List, Optional, Dict, Any

DB_PATH = Path("data") / "app.db"


def get_conn() -> sqlite3.Connection:
    """Return a SQLite connection (ensures folder exists)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they do not exist."""
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
                created_at TEXT NOT NULL
            );
            """
        )
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
            SELECT user_id, first_name, last_name, username, role, is_active, created_at
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
            SELECT user_id, first_name, last_name, username, role, is_active, created_at
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


def delete_user(username: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM users WHERE username = ?;", (username,))
        conn.commit()
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