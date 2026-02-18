import sqlite3
from datetime import datetime, timezone, date, time, timedelta
import statistics
from pathlib import Path
from typing import List, Optional, Dict, Any
from zoneinfo import ZoneInfo
import pandas as pd

DB_PATH = Path("data") / "app.db"


def get_conn() -> sqlite3.Connection:
    """Return a SQLite connection (ensures folder exists)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_users_schema(conn: sqlite3.Connection) -> None:
    """
    Lightweight migrations for older DBs created before newer columns existed.
    """
    cols = conn.execute("PRAGMA table_info(users);").fetchall()
    col_names = {str(c["name"]) for c in cols}

    if "must_reset_password" not in col_names:
        conn.execute(
            "ALTER TABLE users ADD COLUMN must_reset_password INTEGER NOT NULL DEFAULT 0;"
        )

    if "last_login_at" not in col_names:
        conn.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT;")


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
                must_reset_password INTEGER NOT NULL DEFAULT 0 CHECK(must_reset_password IN (0,1)),
                last_login_at TEXT
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

        ensure_fantasy_block_tables_exist()
        ensure_fantasy_scoring_tables_exist()

        conn.commit()
    finally:
        conn.close()


def ensure_fantasy_block_tables_exist() -> None:
    """
    Create fantasy block tables if they do not exist (and run light migrations).
    """
    conn = get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fantasy_blocks (
                block_number INTEGER PRIMARY KEY,
                first_start_at TEXT NOT NULL,
                lock_at TEXT,
                created_at TEXT NOT NULL,
                scored_at TEXT,
                override_state TEXT CHECK(override_state IN ('OPEN','LOCKED')),
                override_until TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fantasy_block_fixtures (
                block_number INTEGER NOT NULL,
                fixture_order INTEGER NOT NULL,
                match_id TEXT NOT NULL,
                start_at TEXT NOT NULL,
                PRIMARY KEY (block_number, fixture_order),
                UNIQUE (match_id),
                FOREIGN KEY (block_number) REFERENCES fantasy_blocks(block_number)
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_fantasy_block_fixtures_block
            ON fantasy_block_fixtures(block_number);
            """
        )

        cols = conn.execute("PRAGMA table_info(fantasy_blocks);").fetchall()
        col_names = {str(c["name"]) for c in cols}

        if "scored_at" not in col_names:
            conn.execute("ALTER TABLE fantasy_blocks ADD COLUMN scored_at TEXT;")
        if "override_state" not in col_names:
            conn.execute(
                "ALTER TABLE fantasy_blocks ADD COLUMN override_state TEXT CHECK(override_state IN ('OPEN','LOCKED'));"
            )
        if "override_until" not in col_names:
            conn.execute("ALTER TABLE fantasy_blocks ADD COLUMN override_until TEXT;")

        conn.commit()
    finally:
        conn.close()


def ensure_fantasy_team_tables_exist() -> None:
    """
    Create fantasy team tables if they do not exist (and run light migrations).
    """
    conn = get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fantasy_prices (
                block_number INTEGER NOT NULL,
                player_id TEXT NOT NULL,
                price REAL NOT NULL,
                PRIMARY KEY (block_number, player_id),
                FOREIGN KEY (block_number) REFERENCES fantasy_blocks(block_number)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fantasy_entries (
                block_number INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                submitted_at TEXT NOT NULL,
                budget_used REAL NOT NULL,
                PRIMARY KEY (block_number, user_id),
                FOREIGN KEY (block_number) REFERENCES fantasy_blocks(block_number),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fantasy_entry_players (
                block_number INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                player_id TEXT NOT NULL,
                is_starting INTEGER NOT NULL CHECK(is_starting IN (0,1)),
                bench_order INTEGER NULL CHECK(bench_order IN (1,2)),
                is_captain INTEGER NOT NULL CHECK(is_captain IN (0,1)),
                is_vice_captain INTEGER NOT NULL CHECK(is_vice_captain IN (0,1)),
                PRIMARY KEY (block_number, user_id, player_id),
                FOREIGN KEY (block_number, user_id) REFERENCES fantasy_entries(block_number, user_id)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def ensure_fantasy_scoring_tables_exist() -> None:
    """
    Create fantasy scoring tables if they do not exist.
    """
    conn = get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fantasy_block_player_points (
                block_number INTEGER NOT NULL,
                player_id TEXT NOT NULL,
                points REAL NOT NULL,
                PRIMARY KEY (block_number, player_id),
                FOREIGN KEY (block_number) REFERENCES fantasy_blocks(block_number)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fantasy_block_user_points (
                block_number INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                points_total REAL NOT NULL,
                calculated_at TEXT NOT NULL,
                PRIMARY KEY (block_number, user_id),
                FOREIGN KEY (block_number) REFERENCES fantasy_blocks(block_number),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _parse_fixture_date(date_val: Any) -> Optional[date]:
    if date_val is None:
        return None
    if isinstance(date_val, datetime):
        return date_val.date()
    if isinstance(date_val, date):
        return date_val
    s = str(date_val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def _parse_fixture_time(time_val: Any) -> Optional[time]:
    if time_val is None:
        return None
    if isinstance(time_val, datetime):
        return time_val.time()
    if isinstance(time_val, time):
        return time_val
    if isinstance(time_val, (int, float)) and 0 <= float(time_val) < 1:
        seconds = int(round(float(time_val) * 86400))
        return (datetime.min + timedelta(seconds=seconds)).time()
    s = str(time_val).strip()
    if not s:
        return None
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).time()
    except ValueError:
        return None


def _fixture_start_at_london(date_val: Any, time_val: Any) -> Optional[datetime]:
    d = _parse_fixture_date(date_val)
    t = _parse_fixture_time(time_val)
    if d is None or t is None:
        return None
    naive = datetime.combine(d, t)
    return naive.replace(tzinfo=ZoneInfo("Europe/London"))


def _fixture_kickoff_at_london(date_val: Any, time_val: Any) -> Optional[datetime]:
    """
    Build fixture kickoff datetime in league local time.
    - Prefer Date + Time
    - If Time is missing but Date exists, use 00:00 on that date
    """
    d = _parse_fixture_date(date_val)
    if d is None:
        return None
    t = _parse_fixture_time(time_val)
    if t is None:
        t = time.min
    return datetime.combine(d, t).replace(tzinfo=ZoneInfo("Europe/London"))


def _normalize_datetime_for_storage(dt_val: Any) -> Optional[str]:
    if dt_val is None:
        return None
    if isinstance(dt_val, str):
        s = dt_val.strip()
        return s or None
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            dt_val = dt_val.replace(tzinfo=ZoneInfo("Europe/London"))
        return dt_val.isoformat()
    raise ValueError("Expected datetime, ISO string, or None.")


def _parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    s = str(dt_str).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("Europe/London"))
    return dt


def _get_week_value(row: Dict[str, Any]) -> Any:
    return (
        row.get("Week")
        or row.get("week")
        or row.get("Round")
        or row.get("round")
    )


def _week_sort_key(week_val: Any) -> tuple[int, Any]:
    s = str(week_val).strip()
    try:
        return (0, float(s))
    except Exception:
        return (1, s.casefold())


def _fixture_sort_key(row: Dict[str, Any]) -> tuple:
    start_at = row.get("start_at")
    fixture_date = row.get("fixture_date")
    row_index = int(row.get("_row_index", 0))
    if isinstance(start_at, datetime):
        return (0, start_at, row_index)
    if isinstance(fixture_date, date):
        return (1, fixture_date, row_index)
    return (2, row_index)


def _group_fixtures_without_week(fixtures: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    # Preferred fallback: one block per calendar date.
    dated_groups: Dict[date, List[Dict[str, Any]]] = {}
    no_date_rows: List[Dict[str, Any]] = []
    for fx in fixtures:
        d = fx.get("fixture_date")
        if isinstance(d, date):
            dated_groups.setdefault(d, []).append(fx)
        else:
            no_date_rows.append(fx)

    grouped: List[List[Dict[str, Any]]] = []
    for d in sorted(dated_groups.keys()):
        g = sorted(dated_groups[d], key=_fixture_sort_key)
        if g:
            grouped.append(g)

    # Last resort: sequential one-fixture blocks for rows with no date.
    for fx in sorted(no_date_rows, key=_fixture_sort_key):
        grouped.append([fx])

    return grouped


def rebuild_blocks_from_fixtures_if_missing(fixtures: Any) -> int:
    """
    Build fantasy blocks if no blocks exist yet.
    Preferred grouping uses Week/Round fields; fallback groups by date.
    Returns the number of blocks created.
    """
    ensure_fantasy_block_tables_exist()

    rows = []
    if fixtures is None:
        return 0
    if hasattr(fixtures, "to_dict"):
        rows = fixtures.to_dict("records")
    elif isinstance(fixtures, list):
        rows = fixtures
    else:
        raise ValueError("Fixtures must be a list of dicts or a DataFrame-like object.")

    fixtures_rows: List[Dict[str, Any]] = []
    for idx, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        fixture_date = _parse_fixture_date(r.get("Date"))
        start_at = _fixture_kickoff_at_london(r.get("Date"), r.get("Time"))
        match_id = str(r.get("MatchID") or r.get("Match Id") or "").strip()
        if not match_id:
            match_id = f"fixture_{idx + 1}"
        fixtures_rows.append(
            {
                "match_id": match_id,
                "start_at": start_at,
                "fixture_date": fixture_date,
                "week": _get_week_value(r),
                "_row_index": idx,
            }
        )

    now_local = datetime.now(ZoneInfo("Europe/London"))
    today_local = now_local.date()
    filtered_rows: List[Dict[str, Any]] = []
    for fx in fixtures_rows:
        start_at = fx.get("start_at")
        fixture_date = fx.get("fixture_date")
        if isinstance(start_at, datetime) and start_at < now_local:
            continue
        if start_at is None and isinstance(fixture_date, date) and fixture_date < today_local:
            continue
        filtered_rows.append(fx)

    total = len(filtered_rows)
    if total < 1:
        return 0

    week_groups: Dict[Any, List[Dict[str, Any]]] = {}
    has_any_week = False
    missing_week_rows: List[Dict[str, Any]] = []
    for fx in filtered_rows:
        wk = fx.get("week")
        if wk is None or str(wk).strip() == "":
            missing_week_rows.append(fx)
            continue
        has_any_week = True
        week_groups.setdefault(wk, []).append(fx)

    grouped_blocks: List[List[Dict[str, Any]]] = []
    if has_any_week:
        for wk in sorted(week_groups.keys(), key=_week_sort_key):
            grouped = sorted(week_groups[wk], key=_fixture_sort_key)
            if grouped:
                grouped_blocks.append(grouped)
        if missing_week_rows:
            grouped_blocks.extend(_group_fixtures_without_week(missing_week_rows))
    else:
        grouped_blocks = _group_fixtures_without_week(filtered_rows)

    conn = get_conn()
    try:
        existing = conn.execute("SELECT COUNT(*) AS n FROM fantasy_blocks;").fetchone()
        if int(existing["n"]) > 0:
            # Refresh missing lock times for existing unscored blocks without rebuilding.
            block_lock_map: Dict[int, str] = {}
            block_num = 0
            for group in grouped_blocks:
                if not group:
                    continue
                block_num += 1
                start_candidates = [fx["start_at"] for fx in group if isinstance(fx.get("start_at"), datetime)]
                if start_candidates:
                    block_lock_map[block_num] = min(start_candidates).isoformat()
                else:
                    date_candidates = [fx["fixture_date"] for fx in group if isinstance(fx.get("fixture_date"), date)]
                    if date_candidates:
                        block_lock_map[block_num] = datetime.combine(
                            min(date_candidates), time.min
                        ).replace(tzinfo=ZoneInfo("Europe/London")).isoformat()
            if block_lock_map:
                for bn, lock_iso in block_lock_map.items():
                    conn.execute(
                        """
                        UPDATE fantasy_blocks
                        SET lock_at = COALESCE(NULLIF(lock_at, ''), ?),
                            first_start_at = COALESCE(NULLIF(first_start_at, ''), ?)
                        WHERE block_number = ? AND scored_at IS NULL;
                        """,
                        (lock_iso, lock_iso, int(bn)),
                    )
                conn.commit()
            return 0

        created = 0
        now_iso = datetime.now(timezone.utc).isoformat()
        block_number = 0
        for group in grouped_blocks:
            if not group:
                continue
            block_number += 1
            start_candidates = [fx["start_at"] for fx in group if isinstance(fx.get("start_at"), datetime)]
            if start_candidates:
                first_start_at_dt = min(start_candidates)
                first_start_at = first_start_at_dt.isoformat()
                lock_at = first_start_at_dt.isoformat()
            else:
                date_candidates = [fx["fixture_date"] for fx in group if isinstance(fx.get("fixture_date"), date)]
                if date_candidates:
                    first_date = min(date_candidates)
                    first_start_at = datetime.combine(first_date, time.min).replace(
                        tzinfo=ZoneInfo("Europe/London")
                    ).isoformat()
                    lock_at = first_start_at
                else:
                    first_start_at = ""
                    lock_at = None

            block_lock_store = lock_at if lock_at is not None else ""

            conn.execute(
                """
                INSERT INTO fantasy_blocks
                    (block_number, first_start_at, lock_at, created_at, scored_at, override_state, override_until)
                VALUES (?, ?, ?, ?, NULL, NULL, NULL);
                """,
                (
                    block_number,
                    first_start_at,
                    block_lock_store,
                    now_iso,
                ),
            )

            for j, fx in enumerate(group, start=1):
                fixture_start = fx["start_at"].isoformat() if isinstance(fx.get("start_at"), datetime) else ""
                conn.execute(
                    """
                    INSERT INTO fantasy_block_fixtures
                        (block_number, fixture_order, match_id, start_at)
                    VALUES (?, ?, ?, ?);
                    """,
                    (
                        block_number,
                        j,
                        fx["match_id"],
                        fixture_start,
                    ),
                )
            created += 1

        conn.commit()
        return created
    finally:
        conn.close()


def list_blocks_with_fixtures() -> List[Dict[str, Any]]:
    ensure_fantasy_block_tables_exist()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                b.block_number,
                b.first_start_at,
                b.lock_at,
                b.created_at,
                b.scored_at,
                b.override_state,
                b.override_until,
                f.fixture_order,
                f.match_id,
                f.start_at AS fixture_start_at
            FROM fantasy_blocks b
            LEFT JOIN fantasy_block_fixtures f
                ON b.block_number = f.block_number
            ORDER BY b.block_number ASC, f.fixture_order ASC;
            """
        ).fetchall()

        blocks: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            bn = int(r["block_number"])
            if bn not in blocks:
                blocks[bn] = {
                    "block_number": bn,
                    "first_start_at": r["first_start_at"],
                    "lock_at": r["lock_at"],
                    "created_at": r["created_at"],
                    "scored_at": r["scored_at"],
                    "override_state": r["override_state"],
                    "override_until": r["override_until"],
                    "fixtures": [],
                }
            if r["match_id"] is not None:
                blocks[bn]["fixtures"].append(
                    {
                        "fixture_order": int(r["fixture_order"]),
                        "match_id": r["match_id"],
                        "start_at": r["fixture_start_at"],
                    }
                )
        return [blocks[k] for k in sorted(blocks.keys())]
    finally:
        conn.close()


def set_block_override(
    block_number: int,
    override_state: Optional[str],
    override_until: Any = None,
) -> None:
    ensure_fantasy_block_tables_exist()
    if override_state is not None and override_state not in ("OPEN", "LOCKED"):
        raise ValueError("override_state must be 'OPEN', 'LOCKED', or None.")
    until_iso = _normalize_datetime_for_storage(override_until)
    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE fantasy_blocks
            SET override_state = ?, override_until = ?
            WHERE block_number = ?;
            """,
            (override_state, until_iso, int(block_number)),
        )
        conn.commit()
    finally:
        conn.close()


def clear_block_override(block_number: int) -> None:
    ensure_fantasy_block_tables_exist()
    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE fantasy_blocks
            SET override_state = NULL, override_until = NULL
            WHERE block_number = ?;
            """,
            (int(block_number),),
        )
        conn.commit()
    finally:
        conn.close()


def mark_block_scored(block_number: int, scored_at: Any) -> None:
    ensure_fantasy_block_tables_exist()
    scored_iso = _normalize_datetime_for_storage(scored_at)
    if not scored_iso:
        raise ValueError("scored_at is required.")
    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE fantasy_blocks
            SET scored_at = ?
            WHERE block_number = ?;
            """,
            (scored_iso, int(block_number)),
        )
        conn.commit()
    finally:
        conn.close()


def get_block_first_fixture_start_at(block_number: int) -> Optional[datetime]:
    ensure_fantasy_block_tables_exist()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT start_at
            FROM fantasy_block_fixtures
            WHERE block_number = ?;
            """,
            (int(block_number),),
        ).fetchall()
        dts: List[datetime] = []
        for r in rows:
            dt = _parse_iso_datetime(r["start_at"])
            if not dt:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("Europe/London"))
            else:
                dt = dt.astimezone(ZoneInfo("Europe/London"))
            dts.append(dt)
        return min(dts) if dts else None
    finally:
        conn.close()


def get_block_scored_at(block_number: int) -> Optional[datetime]:
    ensure_fantasy_block_tables_exist()
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT scored_at
            FROM fantasy_blocks
            WHERE block_number = ?;
            """,
            (int(block_number),),
        ).fetchone()
        if not row:
            return None
        dt = _parse_iso_datetime(row["scored_at"])
        if not dt:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=ZoneInfo("Europe/London"))
        return dt.astimezone(ZoneInfo("Europe/London"))
    finally:
        conn.close()


def get_block_open_at(block_number: int, now_dt: datetime) -> Optional[datetime]:
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=ZoneInfo("Europe/London"))
    if int(block_number) == 1:
        return None
    prev_scored_at = get_block_scored_at(int(block_number) - 1)
    return prev_scored_at


def get_effective_block_state(block_number: int, now_dt: datetime) -> str:
    ensure_fantasy_block_tables_exist()
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=ZoneInfo("Europe/London"))

    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT lock_at, scored_at, override_state, override_until
            FROM fantasy_blocks
            WHERE block_number = ?;
            """,
            (int(block_number),),
        ).fetchone()
        if not row:
            raise ValueError(f"Block {block_number} not found.")

        if row["scored_at"]:
            return "SCORED"

        override_state = row["override_state"]
        override_until = _parse_iso_datetime(row["override_until"])
        if override_state in ("OPEN", "LOCKED"):
            if override_until is None or now_dt < override_until:
                return override_state

        if int(block_number) == 1:
            return "LOCKED"

        prev_scored_at = get_block_scored_at(int(block_number) - 1)
        if prev_scored_at is not None:
            return "OPEN"
        return "LOCKED"
    finally:
        conn.close()


def get_current_block_number() -> Optional[int]:
    ensure_fantasy_block_tables_exist()
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT block_number
            FROM fantasy_blocks
            WHERE scored_at IS NULL
            ORDER BY block_number ASC
            LIMIT 1;
            """
        ).fetchone()
        return int(row["block_number"]) if row else None
    finally:
        conn.close()


def get_latest_scored_block_number() -> Optional[int]:
    ensure_fantasy_block_tables_exist()
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT MAX(block_number) AS max_block
            FROM fantasy_blocks
            WHERE scored_at IS NOT NULL;
            """
        ).fetchone()
        if not row or row["max_block"] is None:
            return None
        return int(row["max_block"])
    finally:
        conn.close()


def get_user_block_points(block_number: int, user_id: int) -> Optional[float]:
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT points_total
            FROM fantasy_block_user_points
            WHERE block_number = ? AND user_id = ?;
            """,
            (int(block_number), int(user_id)),
        ).fetchone()
        return float(row["points_total"]) if row else None
    finally:
        conn.close()


def get_block_player_points(block_number: int) -> Dict[str, float]:
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT player_id, points
            FROM fantasy_block_player_points
            WHERE block_number = ?
            ORDER BY player_id ASC;
            """,
            (int(block_number),),
        ).fetchall()
        return {str(r["player_id"]): float(r["points"]) for r in rows}
    finally:
        conn.close()


def list_scored_blocks() -> List[int]:
    ensure_fantasy_block_tables_exist()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT block_number
            FROM fantasy_blocks
            WHERE scored_at IS NOT NULL
            ORDER BY block_number ASC;
            """
        ).fetchall()
        return [int(r["block_number"]) for r in rows]
    finally:
        conn.close()


def list_scored_fantasy_blocks() -> List[int]:
    """
    Return fantasy block numbers that have been scored.
    Uses the same scored_at gating as existing block leaderboards.
    """
    return list_scored_blocks()


def get_player_block_fantasy_points(block_number: int) -> Dict[str, float]:
    """
    Return player fantasy points for a scored block.
    If the block is not scored (or has no points), returns an empty dict.
    """
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT p.player_id, SUM(p.points) AS points_total
            FROM fantasy_block_player_points p
            JOIN fantasy_blocks b ON b.block_number = p.block_number
            WHERE p.block_number = ? AND b.scored_at IS NOT NULL
            GROUP BY p.player_id
            ORDER BY p.player_id ASC;
            """,
            (int(block_number),),
        ).fetchall()
        return {str(r["player_id"]): float(r["points_total"] or 0.0) for r in rows}
    finally:
        conn.close()


def get_player_all_time_avg_fantasy_points() -> Dict[str, float]:
    """
    Return each player's all-time average fantasy points across scored blocks
    where that player has a recorded block points row.
    """
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT p.player_id, AVG(p.points) AS avg_points
            FROM fantasy_block_player_points p
            JOIN fantasy_blocks b ON b.block_number = p.block_number
            WHERE b.scored_at IS NOT NULL
            GROUP BY p.player_id
            ORDER BY p.player_id ASC;
            """
        ).fetchall()
        return {str(r["player_id"]): float(r["avg_points"] or 0.0) for r in rows}
    finally:
        conn.close()


def get_player_season_totals_and_avg(scored_blocks: List[int]) -> Dict[str, Dict[str, float]]:
    """
    Return season totals and averages for players across the provided scored blocks.
    season_avg is calculated as:
      season_total / number_of_scored_blocks_where_player_has_data
    """
    blocks = [int(b) for b in (scored_blocks or [])]
    if not blocks:
        return {}

    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        placeholders = ",".join(["?"] * len(blocks))
        rows = conn.execute(
            f"""
            SELECT
                p.player_id,
                SUM(p.points) AS season_total,
                COUNT(DISTINCT p.block_number) AS blocks_with_data
            FROM fantasy_block_player_points p
            JOIN fantasy_blocks b ON b.block_number = p.block_number
            WHERE b.scored_at IS NOT NULL
              AND p.block_number IN ({placeholders})
            GROUP BY p.player_id
            ORDER BY p.player_id ASC;
            """,
            tuple(blocks),
        ).fetchall()

        out: Dict[str, Dict[str, float]] = {}
        for r in rows:
            pid = str(r["player_id"])
            season_total = float(r["season_total"] or 0.0)
            blocks_with_data = int(r["blocks_with_data"] or 0)
            season_avg = season_total / blocks_with_data if blocks_with_data > 0 else 0.0
            out[pid] = {"season_total": season_total, "season_avg": season_avg}
        return out
    finally:
        conn.close()


def get_season_user_totals() -> List[Dict[str, Any]]:
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                p.user_id,
                u.username,
                u.first_name,
                u.last_name,
                SUM(p.points_total) AS total_points
            FROM fantasy_block_user_points p
            JOIN fantasy_blocks b ON b.block_number = p.block_number
            JOIN users u ON u.user_id = p.user_id
            WHERE b.scored_at IS NOT NULL
            GROUP BY p.user_id
            ORDER BY total_points DESC, u.username ASC;
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user_season_total(user_id: int) -> float:
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT SUM(p.points_total) AS total_points
            FROM fantasy_block_user_points p
            JOIN fantasy_blocks b ON b.block_number = p.block_number
            WHERE b.scored_at IS NOT NULL AND p.user_id = ?;
            """,
            (int(user_id),),
        ).fetchone()
        if not row or row["total_points"] is None:
            return 0.0
        return float(row["total_points"])
    finally:
        conn.close()


def get_user_block_points_history(user_id: int) -> List[Dict[str, Any]]:
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT p.block_number, p.points_total, p.calculated_at
            FROM fantasy_block_user_points p
            JOIN fantasy_blocks b ON b.block_number = p.block_number
            WHERE b.scored_at IS NOT NULL AND p.user_id = ?
            ORDER BY p.block_number ASC;
            """,
            (int(user_id),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_block_fixtures(block_number: int) -> List[Dict[str, Any]]:
    ensure_fantasy_block_tables_exist()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT block_number, fixture_order, match_id, start_at
            FROM fantasy_block_fixtures
            WHERE block_number = ?
            ORDER BY fixture_order ASC;
            """,
            (int(block_number),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def upsert_block_prices(block_number: int, prices: Dict[str, float]) -> None:
    ensure_fantasy_team_tables_exist()
    if not prices:
        return
    conn = get_conn()
    try:
        rows = []
        for pid, price in prices.items():
            try:
                val = float(price)
            except Exception as e:
                raise ValueError("Price values must be numeric.") from e
            val = max(5.0, min(10.0, round(val * 2) / 2))
            rows.append((int(block_number), str(pid), val))
        conn.executemany(
            """
            INSERT OR REPLACE INTO fantasy_prices (block_number, player_id, price)
            VALUES (?, ?, ?);
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def get_block_prices(block_number: int) -> Dict[str, float]:
    ensure_fantasy_team_tables_exist()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT player_id, price
            FROM fantasy_prices
            WHERE block_number = ?
            ORDER BY player_id ASC;
            """,
            (int(block_number),),
        ).fetchall()
        return {str(r["player_id"]): float(r["price"]) for r in rows}
    finally:
        conn.close()


def ensure_block_prices_default(
    block_number: int,
    player_ids: List[str],
    default_price: float = 7.5,
) -> None:
    ensure_fantasy_team_tables_exist()
    if not player_ids:
        return
    conn = get_conn()
    try:
        existing = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM fantasy_prices
            WHERE block_number = ?;
            """,
            (int(block_number),),
        ).fetchone()
        if int(existing["n"]) > 0:
            return

        rows = [
            (int(block_number), str(pid), float(default_price))
            for pid in player_ids
            if str(pid).strip()
        ]
        if rows:
            conn.executemany(
                """
                INSERT INTO fantasy_prices (block_number, player_id, price)
                VALUES (?, ?, ?);
                """,
                rows,
            )
            conn.commit()
    finally:
        conn.close()


def save_fantasy_entry(
    block_number: int,
    user_id: int,
    squad_player_ids: List[str],
    starting_player_ids: List[str],
    bench1: str,
    bench2: str,
    captain_id: str,
    vice_captain_id: str,
    budget_used: float,
    submitted_at_iso: str,
) -> None:
    ensure_fantasy_team_tables_exist()
    squad_ids = [str(pid).strip() for pid in (squad_player_ids or []) if str(pid).strip()]
    starting_ids = [str(pid).strip() for pid in (starting_player_ids or []) if str(pid).strip()]
    bench1_id = str(bench1 or "").strip()
    bench2_id = str(bench2 or "").strip()
    captain_id = str(captain_id or "").strip()
    vice_captain_id = str(vice_captain_id or "").strip()

    if len(squad_ids) != 8 or len(set(squad_ids)) != 8:
        raise ValueError("Squad must include exactly 8 unique players.")
    if len(starting_ids) != 6 or len(set(starting_ids)) != 6 or not set(starting_ids).issubset(set(squad_ids)):
        raise ValueError("Starting lineup must include exactly 6 unique players from the squad.")
    if not bench1_id or not bench2_id or bench1_id == bench2_id:
        raise ValueError("Bench 1 and Bench 2 must be different players.")
    if bench1_id not in squad_ids or bench2_id not in squad_ids:
        raise ValueError("Bench players must be part of the squad.")
    if bench1_id in starting_ids or bench2_id in starting_ids:
        raise ValueError("Bench players must not be in the starting lineup.")
    if not captain_id or not vice_captain_id or captain_id == vice_captain_id:
        raise ValueError("Captain and vice-captain must be different players.")
    if captain_id not in starting_ids or vice_captain_id not in starting_ids:
        raise ValueError("Captain and vice-captain must be in the starting lineup.")
    if float(budget_used) > 60.0 + 1e-6:
        raise ValueError("Total budget exceeds 60.0.")

    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO fantasy_entries
                (block_number, user_id, submitted_at, budget_used)
            VALUES (?, ?, ?, ?);
            """,
            (int(block_number), int(user_id), str(submitted_at_iso), float(budget_used)),
        )

        conn.execute(
            """
            DELETE FROM fantasy_entry_players
            WHERE block_number = ? AND user_id = ?;
            """,
            (int(block_number), int(user_id)),
        )

        starting_set = set(starting_ids)

        rows = []
        for pid_str in squad_ids:
            bench_order = None
            if pid_str == bench1_id:
                bench_order = 1
            elif pid_str == bench2_id:
                bench_order = 2
            rows.append(
                (
                    int(block_number),
                    int(user_id),
                    pid_str,
                    1 if pid_str in starting_set else 0,
                    bench_order,
                    1 if pid_str == captain_id else 0,
                    1 if pid_str == vice_captain_id else 0,
                )
            )

        if rows:
            conn.executemany(
                """
                INSERT INTO fantasy_entry_players
                    (block_number, user_id, player_id, is_starting, bench_order, is_captain, is_vice_captain)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                rows,
            )

        conn.commit()
    finally:
        conn.close()


def get_fantasy_entry(block_number: int, user_id: int) -> Optional[Dict[str, Any]]:
    ensure_fantasy_team_tables_exist()
    conn = get_conn()
    try:
        entry = conn.execute(
            """
            SELECT block_number, user_id, submitted_at, budget_used
            FROM fantasy_entries
            WHERE block_number = ? AND user_id = ?;
            """,
            (int(block_number), int(user_id)),
        ).fetchone()
        if not entry:
            return None

        rows = conn.execute(
            """
            SELECT player_id, is_starting, bench_order, is_captain, is_vice_captain
            FROM fantasy_entry_players
            WHERE block_number = ? AND user_id = ?
            ORDER BY player_id ASC;
            """,
            (int(block_number), int(user_id)),
        ).fetchall()

        squad = [str(r["player_id"]) for r in rows]
        starting = [str(r["player_id"]) for r in rows if int(r["is_starting"]) == 1]
        bench1 = ""
        bench2 = ""
        captain = ""
        vice_captain = ""
        for r in rows:
            pid = str(r["player_id"])
            if r["bench_order"] == 1:
                bench1 = pid
            elif r["bench_order"] == 2:
                bench2 = pid
            if int(r["is_captain"]) == 1:
                captain = pid
            if int(r["is_vice_captain"]) == 1:
                vice_captain = pid

        return {
            "block_number": int(entry["block_number"]),
            "user_id": int(entry["user_id"]),
            "submitted_at": entry["submitted_at"],
            "budget_used": float(entry["budget_used"]),
            "squad_player_ids": squad,
            "starting_player_ids": starting,
            "bench1": bench1 or None,
            "bench2": bench2 or None,
            "captain_id": captain or None,
            "vice_captain_id": vice_captain or None,
        }
    finally:
        conn.close()


def upsert_block_player_points(block_number: int, player_points: Dict[str, float]) -> None:
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM fantasy_block_player_points WHERE block_number = ?;",
            (int(block_number),),
        )
        rows = [
            (int(block_number), str(pid), float(pts))
            for pid, pts in (player_points or {}).items()
        ]
        if rows:
            conn.executemany(
                """
                INSERT INTO fantasy_block_player_points (block_number, player_id, points)
                VALUES (?, ?, ?);
                """,
                rows,
            )
        conn.commit()
    finally:
        conn.close()


def upsert_block_user_points(
    block_number: int,
    user_points: Dict[int, float],
    calculated_at_iso: str,
) -> None:
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        rows = [
            (int(block_number), int(uid), float(pts), str(calculated_at_iso))
            for uid, pts in (user_points or {}).items()
        ]
        if rows:
            conn.executemany(
                """
                INSERT OR REPLACE INTO fantasy_block_user_points
                    (block_number, user_id, points_total, calculated_at)
                VALUES (?, ?, ?, ?);
                """,
                rows,
            )
            conn.commit()
    finally:
        conn.close()


def list_block_user_points(block_number: int) -> List[Dict[str, Any]]:
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                p.block_number,
                p.user_id,
                p.points_total,
                p.calculated_at,
                u.username,
                u.first_name,
                u.last_name
            FROM fantasy_block_user_points p
            JOIN users u ON u.user_id = p.user_id
            WHERE p.block_number = ?
            ORDER BY p.points_total DESC, u.username ASC;
            """,
            (int(block_number),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_entries_for_block(block_number: int) -> List[Dict[str, Any]]:
    ensure_fantasy_team_tables_exist()
    conn = get_conn()
    try:
        entries = conn.execute(
            """
            SELECT e.block_number, e.user_id, e.submitted_at, e.budget_used,
                   u.username
            FROM fantasy_entries e
            JOIN users u ON u.user_id = e.user_id
            WHERE e.block_number = ?;
            """,
            (int(block_number),),
        ).fetchall()

        if not entries:
            return []

        players = conn.execute(
            """
            SELECT block_number, user_id, player_id, is_starting, bench_order, is_captain, is_vice_captain
            FROM fantasy_entry_players
            WHERE block_number = ?;
            """,
            (int(block_number),),
        ).fetchall()

        by_user: Dict[int, List[Dict[str, Any]]] = {}
        for r in players:
            uid = int(r["user_id"])
            by_user.setdefault(uid, []).append(
                {
                    "player_id": r["player_id"],
                    "is_starting": int(r["is_starting"]),
                    "bench_order": r["bench_order"],
                    "is_captain": int(r["is_captain"]),
                    "is_vice_captain": int(r["is_vice_captain"]),
                }
            )

        out = []
        for e in entries:
            uid = int(e["user_id"])
            out.append(
                {
                    "block_number": int(e["block_number"]),
                    "user_id": uid,
                    "username": e["username"],
                    "submitted_at": e["submitted_at"],
                    "budget_used": float(e["budget_used"]),
                    "entry_players": by_user.get(uid, []),
                }
            )
        return out
    finally:
        conn.close()


def list_fantasy_submission_status_for_block(block_number: int) -> List[Dict[str, Any]]:
    """
    Return active players and whether they have a fantasy submission for the given block.
    """
    ensure_fantasy_team_tables_exist()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                u.user_id,
                u.username,
                u.first_name,
                u.last_name,
                e.submitted_at
            FROM users u
            LEFT JOIN fantasy_entries e
              ON e.user_id = u.user_id
             AND e.block_number = ?
            WHERE u.role = 'player'
              AND u.is_active = 1
            ORDER BY LOWER(u.username) ASC;
            """,
            (int(block_number),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_price(block_number: int, player_id: str) -> Optional[float]:
    ensure_fantasy_team_tables_exist()
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT price
            FROM fantasy_prices
            WHERE block_number = ? AND player_id = ?;
            """,
            (int(block_number), str(player_id)),
        ).fetchone()
        return float(row["price"]) if row else None
    finally:
        conn.close()


def set_price(block_number: int, player_id: str, price: float) -> None:
    ensure_fantasy_team_tables_exist()
    conn = get_conn()
    try:
        try:
            val = float(price)
        except Exception as e:
            raise ValueError("Price values must be numeric.") from e
        val = max(5.0, min(10.0, round(val * 2) / 2))
        conn.execute(
            """
            INSERT OR REPLACE INTO fantasy_prices (block_number, player_id, price)
            VALUES (?, ?, ?);
            """,
            (int(block_number), str(player_id), val),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_block_prices_from_dict(block_number: int, prices: Dict[str, float]) -> None:
    upsert_block_prices(block_number, prices)


def _round_to_0_5(x: float) -> float:
    return round(x * 2) / 2


def _round_to_half(x: float) -> float:
    return _round_to_0_5(x)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_starting_prices_from_history(
    appm_by_player: Dict[str, float],
    *,
    default_price: float = 7.5,
) -> Dict[str, float]:
    """
    Derive starting prices from APPM using linear scaling across 5.0..10.0
    with 0.5 rounding.
    """
    if not appm_by_player:
        return {}

    vals = [float(v) for v in appm_by_player.values()]
    min_appm = min(vals)
    max_appm = max(vals)
    prices: Dict[str, float] = {}
    if max_appm == min_appm:
        flat_price = _clamp(_round_to_0_5(default_price), 5.0, 10.0)
        for pid in appm_by_player.keys():
            prices[str(pid)] = float(flat_price)
        return prices

    for pid, appm_val in appm_by_player.items():
        raw = 5.0 + 5.0 * ((float(appm_val) - min_appm) / (max_appm - min_appm))
        price = _clamp(_round_to_half(raw), 5.0, 10.0)
        prices[str(pid)] = float(price)

    return prices


def ensure_block_prices_from_history_or_default(
    block_number: int,
    current_league_df: pd.DataFrame,
    player_id_col: str,
    name_col: str,
    player_ids: list[str],
    history_dfs: list[pd.DataFrame | None],
    default_price: float = 7.5,
) -> dict[str, float]:
    """
    Ensure prices exist for a block using historical APPM when available.
    - Does not rely on page-level mappings.
    - New players get the average of returning prices (rounded to nearest 0.5).
    """
    prices = get_block_prices(block_number)
    if prices:
        return prices

    def _normalize_name(s: object) -> str:
        return " ".join(str(s or "").split()).casefold()

    def _round_to_0_5(x: float) -> float:
        return round(x * 2) / 2

    def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
        cols = list(df.columns)
        for c in candidates:
            if c in cols:
                return c
        return None

    def _safe_float(val: object) -> float | None:
        try:
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return None
            out = float(val)
        except Exception:
            return None
        if pd.isna(out):
            return None
        return out

    name_to_pid: dict[str, str] = {}
    if player_id_col in current_league_df.columns and name_col in current_league_df.columns:
        for _, r in current_league_df[[player_id_col, name_col]].iterrows():
            pid = str(r.get(player_id_col) or "").strip()
            nm = str(r.get(name_col) or "").strip()
            if pid and nm:
                name_to_pid[_normalize_name(nm)] = pid

    valid_pids = set(str(pid).strip() for pid in player_ids if pid)
    appm_weighted_by_pid: dict[str, float] = {}
    matches_by_pid: dict[str, float] = {}

    appm_cols = [
        "Ave Fantasy Points",
        "Avg Fantasy Points",
        "Average Fantasy Points",
        "Ave Points Per Match",
        "Avg Points Per Match",
        "Average Points Per Match",
        "Ave Pts Per Match",
        "Avg Pts Per Match",
    ]
    matches_cols = ["Matches Played", "Match Played", "Games Played", "Played"]
    points_cols = ["Fantasy Points", "Total Points", "Points", "Pts"]
    pid_cols = ["PlayerID", "Player Id", "Player ID"]
    name_cols = ["Name", "Player", "Player Name"]

    for df in history_dfs:
        if df is None or df.empty:
            continue
        tmp = df.copy()
        tmp.columns = [str(c).strip() for c in tmp.columns]
        pid_col = _find_col(tmp, pid_cols)
        name_col_hist = _find_col(tmp, name_cols)
        appm_col = _find_col(tmp, appm_cols)
        matches_col = _find_col(tmp, matches_cols)
        points_col = _find_col(tmp, points_cols)
        if appm_col is None and points_col is None:
            continue

        if pid_col and pid_col in tmp.columns:
            pid_raw = tmp[pid_col]
            pid_str = pid_raw.astype(str).str.strip()
            pid_invalid = pid_raw.isna() | (pid_str == "") | (pid_str.str.casefold() == "missing")
        else:
            pid_invalid = pd.Series(False, index=tmp.index)
        if name_col_hist and name_col_hist in tmp.columns:
            name_raw = tmp[name_col_hist]
            name_invalid = name_raw.isna() | (name_raw.astype(str).str.strip() == "")
        else:
            name_invalid = pd.Series(False, index=tmp.index)
        tmp = tmp[~(pid_invalid | name_invalid)].copy()

        if appm_col is not None:
            tmp[appm_col] = pd.to_numeric(tmp[appm_col], errors="coerce")
        if matches_col is not None:
            tmp[matches_col] = pd.to_numeric(tmp[matches_col], errors="coerce")
        if points_col is not None:
            tmp[points_col] = pd.to_numeric(tmp[points_col], errors="coerce")

        for _, row in tmp.iterrows():
            matches = _safe_float(row.get(matches_col)) if matches_col else None
            if matches is None or matches <= 0:
                continue

            appm = _safe_float(row.get(appm_col)) if appm_col else None
            if appm is None and points_col:
                pts = _safe_float(row.get(points_col))
                if pts is not None:
                    appm = pts / matches
            if appm is None or pd.isna(appm):
                continue

            pid = None
            if pid_col:
                pid_val = str(row.get(pid_col) or "").strip()
                if pid_val in valid_pids:
                    pid = pid_val
            if pid is None and name_col_hist:
                nm = _normalize_name(row.get(name_col_hist))
                pid = name_to_pid.get(nm)
            if pid:
                appm_weighted_by_pid[pid] = float(appm_weighted_by_pid.get(pid, 0.0)) + float(
                    appm * matches
                )
                matches_by_pid[pid] = float(matches_by_pid.get(pid, 0.0)) + float(matches)

    if appm_weighted_by_pid:
        combined_appm: dict[str, float] = {}
        for pid, weighted_sum in appm_weighted_by_pid.items():
            total_matches = matches_by_pid.get(pid, 0.0)
            if total_matches and total_matches > 0:
                combined_appm[pid] = float(weighted_sum) / float(total_matches)

        if combined_appm:
            base_prices = compute_starting_prices_from_history(
                combined_appm, default_price=default_price
            )
            returning_prices = list(base_prices.values())
            average_price = None
            if returning_prices:
                average_price = _round_to_0_5(float(statistics.mean(returning_prices)))
            else:
                average_price = _round_to_0_5(float(default_price))

            final_prices: dict[str, float] = {}
            for pid in player_ids:
                pid_str = str(pid).strip()
                if pid_str in base_prices:
                    final_prices[pid_str] = float(base_prices[pid_str])
                else:
                    final_prices[pid_str] = (
                        average_price if average_price is not None else default_price
                    )

            upsert_block_prices_from_dict(block_number, final_prices)
            return get_block_prices(block_number)

    ensure_block_prices_default(block_number, player_ids, default_price=default_price)
    return get_block_prices(block_number)


def _fantasy_block_self_test() -> None:
    """
    Manual test helper (not executed automatically).
    """
    fixtures = [
        {"MatchID": "M1", "Date": "2026-01-24", "Time": "18:00"},
        {"MatchID": "M2", "Date": "2026-01-24", "Time": "19:30"},
        {"MatchID": "M3", "Date": "2026-01-24", "Time": "21:00"},
        {"MatchID": "M4", "Date": "2026-01-25", "Time": "18:00"},
        {"MatchID": "M5", "Date": "2026-01-25", "Time": "19:30"},
        {"MatchID": "M6", "Date": "2026-01-25", "Time": "21:00"},
    ]

    created = rebuild_blocks_from_fixtures_if_missing(fixtures)
    print(f"Created blocks: {created}")

    now_local = datetime(2026, 1, 24, 16, 30, tzinfo=ZoneInfo("Europe/London"))
    state = get_effective_block_state(1, now_local)
    print(f"Block 1 state at {now_local.isoformat()}: {state}")


def count_users() -> int:
    conn = get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM users;").fetchone()
        return int(row["n"])
    finally:
        conn.close()


def count_scorecards() -> int:
    conn = get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM scorecards;").fetchone()
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
            SELECT
                user_id,
                first_name,
                last_name,
                username,
                role,
                is_active,
                created_at,
                must_reset_password,
                last_login_at
            FROM users
            ORDER BY user_id ASC;
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
            SELECT
                user_id,
                first_name,
                last_name,
                username,
                password_hash,
                role,
                is_active,
                created_at,
                must_reset_password,
                last_login_at
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
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE role='admin';"
            ).fetchone()
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


def update_username(old_username: str, new_username: str) -> None:
    old_username = str(old_username or "").strip()
    new_username = str(new_username or "").strip()

    if not old_username:
        raise ValueError("Old username is required.")
    if not new_username:
        raise ValueError("New username is required.")
    if " " in new_username:
        raise ValueError("Username cannot contain spaces.")
    if "@" in new_username:
        raise ValueError("Username cannot contain '@'.")
    if old_username == new_username:
        raise ValueError("New username must be different from the current username.")

    conn = get_conn()
    try:
        old_row = conn.execute(
            "SELECT user_id FROM users WHERE username = ?;",
            (old_username,),
        ).fetchone()
        if not old_row:
            raise ValueError("Selected user no longer exists.")

        new_row = conn.execute(
            "SELECT user_id FROM users WHERE LOWER(username) = LOWER(?);",
            (new_username,),
        ).fetchone()
        if new_row:
            raise ValueError("That username is already taken.")

        conn.execute(
            "UPDATE users SET username = ? WHERE username = ?;",
            (new_username, old_username),
        )
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


def update_last_login(username: str, last_login_at: str) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE username = ?;",
            (last_login_at, username),
        )
        conn.commit()
    finally:
        conn.close()


def delete_user(username: str) -> None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT user_id FROM users WHERE username = ?;",
            (str(username),),
        ).fetchone()
        if not row:
            return
        user_id = int(row["user_id"])

        conn.execute("BEGIN;")
        conn.execute(
            "DELETE FROM fantasy_entry_players WHERE user_id = ?;",
            (user_id,),
        )
        conn.execute(
            "DELETE FROM fantasy_entries WHERE user_id = ?;",
            (user_id,),
        )
        conn.execute(
            "DELETE FROM fantasy_block_user_points WHERE user_id = ?;",
            (user_id,),
        )
        conn.execute(
            "DELETE FROM users WHERE user_id = ?;",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


# -----------------------------
# Backup / restore helpers
# -----------------------------
def export_users_backup_payload() -> Dict[str, Any]:
    """
    Export user records WITH password hashes.
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                user_id,
                first_name,
                last_name,
                username,
                password_hash,
                role,
                is_active,
                created_at,
                must_reset_password,
                last_login_at
            FROM users
            ORDER BY user_id ASC;
            """
        ).fetchall()
        users = []
        for r in rows:
            row = dict(r)
            if "user_id" not in row and "id" in row:
                row["user_id"] = row.get("id")
            users.append(row)
        return {"version": 3, "users": users}
    finally:
        conn.close()


def export_fantasy_backup_payload() -> Dict[str, Any]:
    """
    Export fantasy tables (blocks, entries, prices, scoring).
    """
    ensure_fantasy_block_tables_exist()
    ensure_fantasy_team_tables_exist()
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        def _fetch(table: str, order_by: str) -> List[Dict[str, Any]]:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY {order_by};").fetchall()
            return [dict(r) for r in rows]

        payload = {
            "version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "tables": {
                "fantasy_blocks": _fetch("fantasy_blocks", "block_number ASC"),
                "fantasy_block_fixtures": _fetch(
                    "fantasy_block_fixtures", "block_number ASC, fixture_order ASC"
                ),
                "fantasy_prices": _fetch("fantasy_prices", "block_number ASC, player_id ASC"),
                "fantasy_entries": _fetch("fantasy_entries", "block_number ASC, user_id ASC"),
                "fantasy_entry_players": _fetch(
                    "fantasy_entry_players", "block_number ASC, user_id ASC, player_id ASC"
                ),
                "fantasy_block_player_points": _fetch(
                    "fantasy_block_player_points", "block_number ASC, player_id ASC"
                ),
                "fantasy_block_user_points": _fetch(
                    "fantasy_block_user_points", "block_number ASC, user_id ASC"
                ),
            },
        }
        return payload
    finally:
        conn.close()


def restore_fantasy_from_backup_payload(payload: Dict[str, Any]) -> None:
    """
    Restore fantasy tables from a backup payload. Wipes existing fantasy data first.
    """
    if not isinstance(payload, dict) or int(payload.get("version") or 0) != 1:
        raise ValueError("Invalid fantasy backup payload version.")
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("Invalid fantasy backup payload: missing tables.")
    for key in (
        "fantasy_blocks",
        "fantasy_block_fixtures",
        "fantasy_prices",
        "fantasy_entries",
        "fantasy_entry_players",
        "fantasy_block_player_points",
        "fantasy_block_user_points",
    ):
        if key not in tables:
            tables[key] = []

    ensure_fantasy_block_tables_exist()
    ensure_fantasy_team_tables_exist()
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        conn.execute("BEGIN;")
        _wipe_fantasy_tables(conn)

        def _insert_rows(table: str, rows: List[Dict[str, Any]]) -> None:
            if not rows:
                return
            cols = list(rows[0].keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_sql = ", ".join(cols)
            values = [tuple(r.get(c) for c in cols) for r in rows]
            conn.executemany(
                f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders});",
                values,
            )

        _insert_rows("fantasy_blocks", tables.get("fantasy_blocks", []))
        _insert_rows("fantasy_block_fixtures", tables.get("fantasy_block_fixtures", []))
        _insert_rows("fantasy_prices", tables.get("fantasy_prices", []))
        _insert_rows("fantasy_entries", tables.get("fantasy_entries", []))
        _insert_rows("fantasy_entry_players", tables.get("fantasy_entry_players", []))
        _insert_rows("fantasy_block_player_points", tables.get("fantasy_block_player_points", []))
        _insert_rows("fantasy_block_user_points", tables.get("fantasy_block_user_points", []))

        conn.commit()
    finally:
        conn.close()


def _wipe_fantasy_tables(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM fantasy_block_user_points;")
    conn.execute("DELETE FROM fantasy_block_player_points;")
    conn.execute("DELETE FROM fantasy_entry_players;")
    conn.execute("DELETE FROM fantasy_entries;")
    conn.execute("DELETE FROM fantasy_prices;")
    conn.execute("DELETE FROM fantasy_block_fixtures;")
    conn.execute("DELETE FROM fantasy_blocks;")


def wipe_all_fantasy_data() -> None:
    ensure_fantasy_block_tables_exist()
    ensure_fantasy_team_tables_exist()
    ensure_fantasy_scoring_tables_exist()
    conn = get_conn()
    try:
        _wipe_fantasy_tables(conn)
        conn.commit()
    finally:
        conn.close()


def fantasy_has_state() -> bool:
    ensure_fantasy_block_tables_exist()
    ensure_fantasy_team_tables_exist()
    conn = get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM fantasy_blocks;").fetchone()
        if int(row["n"]) > 0:
            return True
        row2 = conn.execute("SELECT COUNT(*) AS n FROM fantasy_entries;").fetchone()
        return int(row2["n"]) > 0
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

    Passwords are restored when present in the payload. If a password hash is
    missing, default_password_hash is used and the user is forced to reset.

    Returns number of users inserted.
    """
    payload_version = int(payload.get("version") or 0)
    if payload_version not in (2, 3):
        raise ValueError("Invalid backup payload version: expected 2 or 3.")

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
        seen_user_ids: set[int] = set()
        for u in users:
            raw_user_id = u.get("user_id", u.get("id"))
            try:
                user_id = int(raw_user_id)
            except Exception:
                user_id = None
            first_name = str(u.get("first_name", "")).strip()
            last_name = str(u.get("last_name", "")).strip()
            username = str(u.get("username", "")).strip()
            password_hash = str(u.get("password_hash", "")).strip()
            role = str(u.get("role", "player")).strip() or "player"
            is_active = int(u.get("is_active", 1))
            created_at = str(u.get("created_at", "")).strip() or now_iso
            must_reset_password = int(u.get("must_reset_password", 0))
            last_login_at = str(u.get("last_login_at", "")).strip() or None

            if not username:
                continue
            if user_id is not None and user_id <= 0:
                user_id = None
            if user_id is not None and user_id in seen_user_ids:
                continue
            if role not in ("admin", "player"):
                role = "player"
            if is_active not in (0, 1):
                is_active = 1
            if must_reset_password not in (0, 1):
                must_reset_password = 0

            missing_hash = not password_hash
            if missing_hash:
                password_hash = default_password_hash
                must_reset_password = 1
            elif force_reset:
                must_reset_password = 1

            if user_id is None:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO users
                        (first_name, last_name, username, password_hash, role, is_active, created_at, must_reset_password, last_login_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        first_name or " ",
                        last_name or " ",
                        username,
                        password_hash,
                        role,
                        is_active,
                        created_at,
                        must_reset_password,
                        last_login_at,
                    ),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO users
                        (user_id, first_name, last_name, username, password_hash, role, is_active, created_at, must_reset_password, last_login_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        user_id,
                        first_name or " ",
                        last_name or " ",
                        username,
                        password_hash,
                        role,
                        is_active,
                        created_at,
                        must_reset_password,
                        last_login_at,
                    ),
                )
            if cur.rowcount == 1:
                inserted += 1
                if user_id is not None:
                    seen_user_ids.add(user_id)

        # Keep AUTOINCREMENT in sync after explicit user_id inserts.
        try:
            max_id = int(
                conn.execute(
                    "SELECT COALESCE(MAX(user_id), 0) AS max_id FROM users;"
                ).fetchone()["max_id"]
            )
            conn.execute(
                """
                UPDATE sqlite_sequence
                SET seq = ?
                WHERE name = 'users';
                """,
                (max_id,),
            )
        except sqlite3.OperationalError:
            # sqlite_sequence may not exist in edge cases; safe to ignore.
            pass

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


def upsert_scorecard(
    match_id: str,
    file_name: str,
    dropbox_path: str,
    uploaded_at: str,
    uploaded_by: str | None = None,
) -> None:
    """
    Insert scorecard row if it doesn't exist (dropbox_path is UNIQUE).
    If it already exists, update file_name/uploaded_at/uploaded_by.
    """
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO scorecards (match_id, file_name, dropbox_path, uploaded_by, uploaded_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (match_id, file_name, dropbox_path, uploaded_by, uploaded_at),
        )

        conn.execute(
            """
            UPDATE scorecards
            SET match_id = ?, file_name = ?, uploaded_by = ?, uploaded_at = ?
            WHERE dropbox_path = ?;
            """,
            (match_id, file_name, uploaded_by, uploaded_at, dropbox_path),
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
