from datetime import datetime

import streamlit as st
import pandas as pd

from src.guard import (
    APP_TITLE,
    require_login,
    hide_home_page_when_logged_in,
    hide_admin_page_for_non_admins,
    render_sidebar_header,
    render_logout_button,
)
from src.dropbox_api import get_access_token, download_file, get_temporary_link
from src.excel_io import load_league_workbook_from_bytes
from src.db import list_scorecards, list_scorecard_match_ids

st.set_page_config(page_title=f"{APP_TITLE} - QM Social League", layout="wide")

require_login()
hide_home_page_when_logged_in()
hide_admin_page_for_non_admins()
render_sidebar_header()
render_logout_button()

st.title("QM Social League")


def _get_secret(name: str) -> str:
    val = st.secrets.get(name, "")
    if not val:
        raise RuntimeError(f"Missing Streamlit secret: {name}")
    return str(val)


@st.cache_data(ttl=60, show_spinner=False)
def _load_from_dropbox(app_key: str, app_secret: str, refresh_token: str, dropbox_path: str):
    access_token = get_access_token(app_key, app_secret, refresh_token)
    xbytes = download_file(access_token, dropbox_path)
    return load_league_workbook_from_bytes(xbytes)


@st.cache_data(ttl=300, show_spinner=False)
def _download_scorecard_bytes(app_key: str, app_secret: str, refresh_token: str, dropbox_path: str) -> bytes:
    """Download a scorecard file from Dropbox (cached briefly for UX)."""
    access_token = get_access_token(app_key, app_secret, refresh_token)
    return download_file(access_token, dropbox_path)


@st.cache_data(ttl=60, show_spinner=False)
def _get_temp_link(app_key: str, app_secret: str, refresh_token: str, dropbox_path: str) -> str:
    access_token = get_access_token(app_key, app_secret, refresh_token)
    return get_temporary_link(access_token, dropbox_path)


@st.cache_data(ttl=60, show_spinner=False)
def _match_has_scorecards(match_id: str) -> bool:
    """Fast check to filter the fixture selector to only fixtures with uploads."""
    return len(list_scorecards(match_id)) > 0


def _format_date_dd_mmm(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce", dayfirst=True)
    return dt.dt.strftime("%d-%b").fillna(series.astype(str))


def _format_time_ampm(series: pd.Series) -> pd.Series:
    formats = ("%H:%M", "%H:%M:%S", "%I %p", "%I:%M %p")

    def _format_one(val: object) -> str:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return str(val)
        raw = str(val).strip()
        if not raw or raw.lower() == "nan":
            return raw
        for fmt in formats:
            try:
                parsed = datetime.strptime(raw, fmt)
            except ValueError:
                continue
            hour = parsed.strftime("%I").lstrip("0") or "12"
            if parsed.minute == 0:
                return f"{hour} {parsed.strftime('%p')}"
            return f"{hour}:{parsed.strftime('%M')} {parsed.strftime('%p')}"
        return raw

    return series.apply(_format_one)


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = list(df.columns)
    for c in candidates:
        if c in cols:
            return c
    return None


def _normalize_playerid_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """
    Streamlit uses Arrow; mixed types in object columns (int + str) can cause ArrowInvalid.
    Force PlayerID-like columns to clean strings.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    for c in ["PlayerID", "Player Id", "Player ID"]:
        if c in out.columns:
            out[c] = out[c].astype(str).str.strip()
            out[c] = out[c].replace({"nan": "", "None": "", "NaT": ""})
    return out


ALL = "All"


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    try:
        return list(v)
    except Exception:
        return []


def enforce_all_exclusive(key: str, all_token: str = ALL) -> None:
    sel = _as_list(st.session_state.get(key))
    prev_key = f"__prev_{key}"
    prev = _as_list(st.session_state.get(prev_key))

    if all_token in sel:
        if all_token not in prev:
            st.session_state[key] = [all_token]
            return
        if len(sel) > 1:
            st.session_state[key] = [x for x in sel if x != all_token]
            return


def _resolved_selection(
    widget_key: str,
    real_options: list[str],
    default_list: list[str],
    all_label: str = ALL,
) -> list[str]:
    sel = _as_list(st.session_state.get(widget_key, default_list))
    if not sel:
        return []
    if all_label in sel:
        return real_options[:]
    return [x for x in sel if x in real_options]


def _init_or_sanitize_multiselect_state_allow_empty(key: str, options: list[str], defaults: list[str]) -> None:
    """
    - First load: set defaults (only those in options).
    - Later loads: remove invalid selections only.
    - Allow user to clear all selections (empty remains empty).
    """
    if key not in st.session_state:
        st.session_state[key] = [c for c in defaults if c in options]
        return

    current = st.session_state.get(key, [])
    if current is None:
        current = []
    st.session_state[key] = [c for c in current if c in options]


# ---- Read secrets ----
try:
    app_key = _get_secret("DROPBOX_APP_KEY")
    app_secret = _get_secret("DROPBOX_APP_SECRET")
    refresh_token = _get_secret("DROPBOX_REFRESH_TOKEN")
    dropbox_path = _get_secret("DROPBOX_FILE_PATH")
except Exception as e:
    st.error(str(e))
    st.stop()

# ---- Load workbook from Dropbox ----
with st.spinner("Loading latest league workbook from Dropbox..."):
    try:
        data = _load_from_dropbox(app_key, app_secret, refresh_token, dropbox_path)
    except Exception as e:
        st.error(f"Failed to load workbook from Dropbox: {e}")
        st.stop()

# ---- Fixtures ----
fixtures = data.fixture_results.copy()
fixtures.columns = [str(c).strip() for c in fixtures.columns]

# ---- League table (pre-calculated in Excel) ----
league_table_df = getattr(data, "league_table", None)
if league_table_df is not None and not league_table_df.empty:
    league_table = league_table_df.copy()
    league_table.columns = [str(c).strip() for c in league_table.columns]
else:
    league_table = pd.DataFrame()

# ----------------------------
# Tabs
# ----------------------------
selected_tab = st.radio(
    label="Navigation Tabs",
    options=["Fixtures & Results", "League Table", "Teams", "Player Stats", "Historical Stats", "Scorecards"],
    horizontal=True,
    key="main_tab",
    label_visibility="collapsed",
)

st.markdown(
    """
    <style>
    /* =========================================================
       Stateful tabs built from st.radio (native Streamlit look)
       ========================================================= */

    /* --- Radiogroup container (acts like tab bar) --- */
    div[role="radiogroup"] {
        display: flex !important;
        flex-direction: row !important;
        gap: 1.25rem !important;
        border-bottom: none !important;      /* no separator line */
        padding-bottom: 0 !important;
        margin-bottom: 1.25rem;
    }

    /* --- Each tab label --- */
    div[role="radiogroup"] > label {
        display: inline-flex !important;
        align-items: center !important;
        margin: 0 !important;
        padding: 0.45rem 0 !important;
        cursor: pointer !important;
        background: transparent !important;
        border: none !important;
        gap: 0 !important;

        /* Underline support (prevents layout quirks) */
        border-bottom: 2px solid transparent !important;
        text-decoration: none !important;
    }

    /* --- Hide radio controls ONLY (keep labels visible) --- */
    div[role="radiogroup"] > label > div:first-child,
    div[role="radiogroup"] > label > span:first-child {
        display: none !important;
        width: 0 !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }

    div[role="radiogroup"] > label svg {
        display: none !important;
        width: 0 !important;
        height: 0 !important;
    }

    div[role="radiogroup"] input[type="radio"] {
        position: absolute !important;
        opacity: 0 !important;
        width: 0 !important;
        height: 0 !important;
        pointer-events: none !important;
    }

    /* --- Tab text container (Streamlit varies between div/span) --- */
    div[role="radiogroup"] > label > div,
    div[role="radiogroup"] > label > span {
        padding: 0 !important;
        font-weight: 500 !important;
        color: rgba(49, 51, 63, 0.75) !important;   /* unselected (light) */
    }

    /* Hover (light mode) */
    div[role="radiogroup"] > label:hover > div,
    div[role="radiogroup"] > label:hover > span {
        color: rgba(49, 51, 63, 1) !important;
    }

    /* Selected tab (light mode): underline + red text */
    div[role="radiogroup"] > label:has(input:checked) {
        border-bottom-color: rgba(255, 0, 0, 0.85) !important;
    }

    div[role="radiogroup"] > label:has(input:checked) > div,
    div[role="radiogroup"] > label:has(input:checked) > span {
        font-weight: 600 !important;
        color: rgba(255, 0, 0, 0.85) !important;    /* selected red */
    }

    /* =========================================================
       Dark mode: unselected white, selected red, underline red
       ========================================================= */
    @media (prefers-color-scheme: dark) {

        /* Unselected */
        div[role="radiogroup"] > label > div,
        div[role="radiogroup"] > label > span {
            color: rgba(255, 255, 255, 0.90) !important;
        }

        /* Hover */
        div[role="radiogroup"] > label:hover > div,
        div[role="radiogroup"] > label:hover > span {
            color: rgba(255, 255, 255, 1) !important;
        }

        /* Selected */
        div[role="radiogroup"] > label:has(input:checked) {
            border-bottom-color: rgba(255, 0, 0, 0.90) !important;
        }

        div[role="radiogroup"] > label:has(input:checked) > div,
        div[role="radiogroup"] > label:has(input:checked) > span {
            color: rgba(255, 0, 0, 0.90) !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================
# TAB 1: FIXTURES & RESULTS
# ============================
if selected_tab == "Fixtures & Results":
    st.subheader("Fixtures & Results")

    display = fixtures.copy()

    if "Date" in display.columns:
        display["Date"] = _format_date_dd_mmm(display["Date"])
    if "Time" in display.columns:
        display["Time"] = _format_time_ampm(display["Time"])

    ordered_cols = ["Date", "Time", "Home Team", "Away Team", "Status", "Won By", "Home Score", "Away Score"]
    show_cols = [c for c in ordered_cols if c in display.columns]

    st.dataframe(
        display[show_cols] if show_cols else display,
        width="stretch",
        hide_index=True,
    )

# ============================
# TAB 2: LEAGUE TABLE
# ============================
if selected_tab == "League Table":
    st.subheader("League Table")

    if league_table is None or league_table.empty:
        st.info(
            "League table not available yet. Confirm the Excel table is named 'League_Table' "
            "on sheet 'Fixture_Results' and that it contains at least one data row."
        )
    else:
        lt = league_table.copy()

        cols_to_hide = [
            "Runs Scored",
            "Runs Conceeded",
            "Wickets Taken",
            "Wickets Lost",
            "Overs Faced",
            "Overs Bowled",
        ]
        lt = lt.drop(columns=[c for c in cols_to_hide if c in lt.columns], errors="ignore")

        lt.insert(0, "Position", range(1, len(lt) + 1))

        if "NRR" in lt.columns:
            nrr = pd.to_numeric(lt["NRR"], errors="coerce")
            lt["NRR"] = nrr.map(lambda x: f"{x:.2f}" if pd.notna(x) else "")

        html_table = lt.to_html(index=False, escape=True)

        st.markdown(
            """
            <style>
                .lt-wrap {
                width: 100%;
                border: 1px solid rgba(49, 51, 63, 0.15);
                border-radius: 0.5rem;
                overflow: hidden;
                background: white;
                padding-bottom: 0;
              }

                .lt-scroll {
                width: 100%;
                overflow-x: auto;
                overflow-y: hidden;
              }

                .lt-wrap table {
                width: 100%;
                border-collapse: separate;
                border-spacing: 0;
                font-size: 0.95rem;
                border-top: none !important;
                border-bottom: none !important;
                margin: 0 !important;
                padding: 0 !important;
              }

                .lt-wrap thead th {
                position: sticky;
                top: 0;
                z-index: 2;
                background: rgba(250, 250, 252, 1);
                color: rgba(49, 51, 63, 0.9);
                text-align: left;
                font-weight: 600;
                padding: 0.65rem 0.75rem;
                border-bottom: 1px solid rgba(49, 51, 63, 0.15);
                white-space: nowrap;
              }

                .lt-wrap tbody td {
                padding: 0.6rem 0.75rem;
                border-bottom: 1px solid rgba(49, 51, 63, 0.08);
                color: rgba(49, 51, 63, 0.95);
                white-space: nowrap;
              }

                .lt-wrap tbody td:not(:nth-child(2)),
                .lt-wrap thead th:not(:nth-child(2)) {
                text-align: center;
              }

                .lt-wrap tbody tr:nth-child(1) td { background: rgba(255, 215, 0, 0.08); }
                .lt-wrap tbody tr:nth-child(2) td { background: rgba(192, 192, 192, 0.22); }
                .lt-wrap tbody tr:nth-child(3) td { background: rgba(205, 127, 50, 0.10); }

                .lt-wrap tbody tr:last-child td { border-bottom: 1px solid transparent; }

                .lt-wrap tbody tr:hover td { background: rgba(240, 242, 246, 1); }

                .lt-wrap table, .lt-wrap th, .lt-wrap td {
                border-left: none !important;
                border-right: none !important;
              }

            @media (prefers-color-scheme: dark) {

                .lt-wrap {
                    background: rgba(14, 17, 23, 1) !important;
                    border: 1px solid rgba(255, 255, 255, 0.12) !important;
                }

                .lt-wrap table {
                    background: transparent !important;
                }

                .lt-wrap thead th {
                    background: rgba(28, 31, 38, 1) !important;
                    color: rgba(255, 255, 255, 0.90) !important;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.12) !important;
                }

                .lt-wrap tbody td {
                    color: rgba(255, 255, 255, 0.88) !important;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
                }

                .lt-wrap tbody tr:hover td {
                    background: rgba(255, 255, 255, 0.06) !important;
                }

                .lt-wrap tbody tr:nth-child(1) td { background: rgba(255, 215, 0, 0.10) !important; }
                .lt-wrap tbody tr:nth-child(2) td { background: rgba(192, 192, 192, 0.10) !important; }
                .lt-wrap tbody tr:nth-child(3) td { background: rgba(205, 127, 50, 0.10) !important; }

                .lt-wrap table, .lt-wrap th, .lt-wrap td {
                    border-left: none !important;
                    border-right: none !important;
                }
            }

            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div class="lt-wrap">
              <div class="lt-scroll">
                {html_table}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ============================
# TAB 3: TEAMS
# ============================
if selected_tab == "Teams":
    st.subheader("Teams")

    teams_df = getattr(data, "teams", None)
    league_df = getattr(data, "league_data", None)

    if teams_df is None or teams_df.empty:
        st.info("No Teams_Table found yet.")
        st.stop()

    teams = teams_df.copy()
    teams.columns = [str(c).strip() for c in teams.columns]

    team_id_col = _find_col(teams, ["TeamID", "Team Id", "Team ID"])
    team_name_col = _find_col(teams, ["Team Names", "Team Name"])
    active_col = _find_col(teams, ["Active"])
    captain_name_col = _find_col(teams, ["Captain's Name", "Captains Name", "Captain Name"])

    if not team_name_col:
        st.error("Teams_Table is missing 'Team Names'.")
        st.stop()

    teams[team_name_col] = teams[team_name_col].astype(str).str.strip()
    if team_id_col and team_id_col in teams.columns:
        teams[team_id_col] = teams[team_id_col].astype(str).str.strip()
    if active_col and active_col in teams.columns:
        teams[active_col] = teams[active_col].astype(str).str.strip()
    if captain_name_col and captain_name_col in teams.columns:
        teams[captain_name_col] = teams[captain_name_col].astype(str).str.strip()

    team_names = sorted(
        [t for t in teams[team_name_col].dropna().unique().tolist() if str(t).strip() != ""],
        key=str.lower,
    )
    team_choice = st.selectbox("Team", ["All Teams"] + team_names, key="ts_team_name")

    # ---------------------------------------------------------
    # ALL TEAMS
    # ---------------------------------------------------------
    if team_choice == "All Teams":

        if league_df is None or league_df.empty:
            st.info("No League_Data_Stats found yet, so team totals cannot be calculated.")
            st.stop()

        league = league_df.copy()
        league.columns = [str(c).strip() for c in league.columns]

        team_id_col_league = _find_col(league, ["TeamID", "Team Id", "Team ID"])

        team_id_to_name: dict[str, str] = {}
        if team_id_col and team_id_col in teams.columns:
            tmap = teams[[team_id_col, team_name_col]].copy()
            tmap[team_id_col] = tmap[team_id_col].astype(str).str.strip()
            tmap[team_name_col] = tmap[team_name_col].astype(str).str.strip()
            tmap = tmap[(tmap[team_id_col] != "") & (tmap[team_name_col] != "")].drop_duplicates()
            team_id_to_name = dict(zip(tmap[team_id_col], tmap[team_name_col]))

        if not team_id_col_league or team_id_col_league not in league.columns or not team_id_to_name:
            st.info("Team totals require TeamID in League_Data and TeamID/Team Names in Teams_Table.")
            st.stop()

        league[team_id_col_league] = league[team_id_col_league].astype(str).str.strip()
        league["Team"] = league[team_id_col_league].map(team_id_to_name)

        league = league[league["Team"].notna() & (league["Team"].astype(str).str.strip() != "")]
        if league.empty:
            st.info("No mapped team stats available yet.")
            st.stop()

        sum_cols = [
            "Runs Scored",
            "Balls Faced",
            "6s",
            "Retirements",
            "Innings Played",
            "Not Out's",
            "Total Overs",
            "Overs",
            "Balls Bowled",
            "Maidens",
            "Runs Conceded",
            "Wickets",
            "Wides",
            "No Balls",
            "Catches",
            "Run Outs",
            "Stumpings",
            "Fantasy Points",
        ]
        for c in sum_cols:
            if c in league.columns:
                league[c] = pd.to_numeric(league[c], errors="coerce")

        agg_map = {c: "sum" for c in sum_cols if c in league.columns}
        team_totals = league.groupby("Team", as_index=False).agg(agg_map) if agg_map else league[["Team"]].drop_duplicates()

        # Derived metrics (same column names as player stats where possible)
        if "Runs Scored" in team_totals.columns and "Balls Faced" in team_totals.columns:
            rs = pd.to_numeric(team_totals["Runs Scored"], errors="coerce")
            bf = pd.to_numeric(team_totals["Balls Faced"], errors="coerce")
            team_totals["Batting Strike Rate"] = (rs / bf) * 100
            team_totals.loc[(bf.isna()) | (bf <= 0), "Batting Strike Rate"] = pd.NA

        if "Runs Scored" in team_totals.columns and "Innings Played" in team_totals.columns and "Not Out's" in team_totals.columns:
            rs = pd.to_numeric(team_totals["Runs Scored"], errors="coerce")
            inn = pd.to_numeric(team_totals["Innings Played"], errors="coerce")
            no = pd.to_numeric(team_totals["Not Out's"], errors="coerce")
            outs = inn - no
            outs = outs.where((outs.notna()) & (outs > 0), 1)
            team_totals["Batting Average"] = rs / outs
            team_totals.loc[rs.isna(), "Batting Average"] = pd.NA

        if "Runs Conceded" in team_totals.columns and "Overs" in team_totals.columns:
            rc = pd.to_numeric(team_totals["Runs Conceded"], errors="coerce")
            ov = pd.to_numeric(team_totals["Overs"], errors="coerce")
            team_totals["Economy"] = rc / ov
            team_totals.loc[(ov.isna()) | (ov <= 0), "Economy"] = pd.NA

        if "Balls Bowled" in team_totals.columns and "Wickets" in team_totals.columns:
            bb = pd.to_numeric(team_totals["Balls Bowled"], errors="coerce")
            wk = pd.to_numeric(team_totals["Wickets"], errors="coerce")
            team_totals["Bowling Strike Rate"] = bb / wk
            team_totals.loc[(wk.isna()) | (wk <= 0), "Bowling Strike Rate"] = pd.NA

        if "Runs Conceded" in team_totals.columns and "Wickets" in team_totals.columns:
            rc = pd.to_numeric(team_totals["Runs Conceded"], errors="coerce")
            wk = pd.to_numeric(team_totals["Wickets"], errors="coerce")
            team_totals["Bowling Average"] = rc / wk
            team_totals.loc[(wk.isna()) | (wk <= 0), "Bowling Average"] = pd.NA

        # Join Active + Captain (optional)
        teams_named = teams.rename(columns={team_name_col: "Team"}).copy()
        teams_named["Team"] = teams_named["Team"].astype(str).str.strip()

        meta_cols: list[str] = []
        if active_col and active_col in teams_named.columns:
            meta_cols.append(active_col)

        tmeta = teams_named[["Team"] + meta_cols].drop_duplicates() if meta_cols else teams_named[["Team"]].drop_duplicates()
        team_totals = team_totals.merge(tmeta, on="Team", how="left")

        # ---- Form (Last 5) from Fixture_Results_Table ----
        # Uses: fixtures (already loaded at top), columns: Date, Time, Home Team, Away Team, Status, Won By
        def _team_form_last_n(team_name: str, n: int = 5) -> str:
            if fixtures is None or fixtures.empty:
                return ""

            f = fixtures.copy()
            f.columns = [str(c).strip() for c in f.columns]

            required = ["Date", "Time", "Home Team", "Away Team", "Status", "Won By"]
            if not all(c in f.columns for c in required):
                return ""

            # Only matches involving this team
            f = f[
                (f["Home Team"].astype(str).str.strip() == str(team_name).strip())
                | (f["Away Team"].astype(str).str.strip() == str(team_name).strip())
            ].copy()

            if f.empty:
                return ""

            # Sort by Date+Time (most recent first)
            dt = pd.to_datetime(f["Date"], errors="coerce")
            tm = pd.to_datetime("2000-01-01 " + f["Time"].astype(str), errors="coerce").dt.time
            f["_dt"] = pd.to_datetime(dt.dt.date.astype(str) + " " + tm.astype(str), errors="coerce")
            f = f.sort_values("_dt", ascending=False)

            # Keep only completed matches
            f = f[f["Status"].astype(str).str.strip().isin(["Played", "Abandoned"])].copy()

            # If no completed matches, show nothing
            if f.empty:
                return ""

            # Take up to last N completed matches (most recent N)
            f = f.head(n)

            out = []
            team_s = str(team_name).strip().lower()

            for _, r in f.iterrows():
                status = str(r.get("Status", "")).strip()
                won_by = str(r.get("Won By", "")).strip().lower()

                # Abandoned is always a dash in the form guide
                if status == "Abandoned":
                    out.append("➖")
                    continue

                # Played: decide W/L if possible, else dash
                if won_by and team_s in won_by:
                    out.append("✅")
                elif won_by:
                    out.append("❌")
                else:
                    out.append("➖")

            return " ".join(out)

        # Compute form per team
        team_totals["Form (Last 5)"] = team_totals["Team"].apply(lambda t: _team_form_last_n(t, 5))

        # ---- Sort All Teams to match league_table order (as sorted in Excel) ----
        # Requires league_table to contain a Team column with the same labels as team_totals["Team"]
        if "Team" in league_table.columns and not league_table.empty:
            _order_df = league_table[["Team"]].copy()
            _order_df["__order"] = range(len(_order_df))
            team_totals = team_totals.merge(_order_df, on="Team", how="left")
            team_totals = team_totals.sort_values("__order", ascending=True, na_position="last").drop(columns=["__order"])

        # ---- selectors (Batting / Bowling / Fielding) ----
        TEAM_BATTING_STATS = [
            "Runs Scored",
            "Balls Faced",
            "6s",
            "Retirements",
            "Batting Strike Rate",
            "Batting Average",
        ]
        TEAM_BOWLING_STATS = [
            "Total Overs",
            "Overs",
            "Balls Bowled",
            "Maidens",
            "Runs Conceded",
            "Wickets",
            "Wides",
            "No Balls",
            "Economy",
            "Bowling Strike Rate",
            "Bowling Average",
        ]
        TEAM_FIELDING_STATS = ["Catches", "Run Outs", "Stumpings"]

        batting_options = [c for c in TEAM_BATTING_STATS if c in team_totals.columns]
        bowling_options = [c for c in TEAM_BOWLING_STATS if c in team_totals.columns]
        fielding_options = [c for c in TEAM_FIELDING_STATS if c in team_totals.columns]

        default_batting = [c for c in ["Runs Scored", "Batting Average"] if c in batting_options]
        default_bowling = [c for c in ["Wickets", "Economy"] if c in bowling_options]
        default_fielding: list[str] = []

        _init_or_sanitize_multiselect_state_allow_empty("ts_all_batting_cols", batting_options, default_batting)
        _init_or_sanitize_multiselect_state_allow_empty("ts_all_bowling_cols", bowling_options, default_bowling)
        _init_or_sanitize_multiselect_state_allow_empty("ts_all_fielding_cols", fielding_options, default_fielding)

        st.markdown("#### Select Team Stats To Display")
        d1, d2, d3 = st.columns(3)
        with d1:
            selected_batting = st.multiselect("Batting Stats", options=batting_options, key="ts_all_batting_cols")
        with d2:
            selected_bowling = st.multiselect("Bowling Stats", options=bowling_options, key="ts_all_bowling_cols")
        with d3:
            selected_fielding = st.multiselect("Fielding Stats", options=fielding_options, key="ts_all_fielding_cols")

        selected_columns = selected_batting + selected_bowling + selected_fielding

        # Build columns: Team + Form + meta + selected + Fantasy Points (Fantasy Points last)
        display_cols = ["Team"]
        if "Form (Last 5)" in team_totals.columns:
            display_cols.append("Form (Last 5)")

        for mc in meta_cols:
            if mc in team_totals.columns and mc not in display_cols:
                display_cols.append(mc)

        for c in selected_columns:
            if c in team_totals.columns and c not in display_cols:
                display_cols.append(c)

        if "Fantasy Points" in team_totals.columns and "Fantasy Points" not in display_cols:
            display_cols.append("Fantasy Points")

        view = team_totals[display_cols].copy() if all(c in team_totals.columns for c in display_cols) else team_totals.copy()

        col_config = {"Team": st.column_config.TextColumn(pinned=True)}
        for c in ["Batting Strike Rate", "Batting Average", "Economy", "Bowling Strike Rate", "Bowling Average"]:
            if c in view.columns:
                col_config[c] = st.column_config.NumberColumn(format="%.2f")

        # Do not pin Fantasy Points (ensures it stays far right)
        if "Fantasy Points" in view.columns:
            col_config["Fantasy Points"] = st.column_config.NumberColumn()

        st.data_editor(
            view,
            width="stretch",
            hide_index=True,
            disabled=True,
            column_config=col_config,
        )

        st.markdown("---")
        st.caption("Select a team above to view team details.")
        st.stop()
    # ---------------------------------------------------------
    # SINGLE TEAM VIEW
    # ---------------------------------------------------------
    team_row = teams.loc[teams[team_name_col] == team_choice]
    if team_row.empty:
        st.info("Selected team not found in Teams_Table.")
        st.stop()
    team_row = team_row.iloc[0]

    meta_c1, meta_c2, meta_c3 = st.columns([2, 1, 2])
    with meta_c1:
        st.markdown(f"**Team:** {team_choice}")
    with meta_c2:
        st.markdown(f"**Active:** {team_row.get(active_col, '—') if active_col else '—'}")
    with meta_c3:
        st.markdown(f"**Captain:** {team_row.get(captain_name_col, '—') if captain_name_col else '—'}")

    if league_table is not None and not league_table.empty and "Team" in league_table.columns:
        lt_lookup = league_table.copy()
        lt_lookup.columns = [str(c).strip() for c in lt_lookup.columns]
        lt_team = lt_lookup[lt_lookup["Team"].astype(str).str.strip() == str(team_choice).strip()]
        if not lt_team.empty:
            r = lt_team.iloc[0].to_dict()
            played = r.get("Played", "—")
            points = r.get("Points", "—")
            nrr_val = r.get("NRR", "—")
            try:
                nrr_val = f"{float(nrr_val):.2f}"
            except Exception:
                pass
            st.markdown(f"**Played:** {played} &nbsp;&nbsp; **Points:** {points} &nbsp;&nbsp; **NRR:** {nrr_val}")

    st.markdown("---")

    if league_df is None or league_df.empty:
        st.info("No League_Data_Stats found yet, so team stats cannot be displayed.")
        st.stop()

    league = league_df.copy()
    league.columns = [str(c).strip() for c in league.columns]

    name_col = _find_col(league, ["Name"])
    team_id_col_league = _find_col(league, ["TeamID", "Team Id", "Team ID"])

    if not (team_id_col and team_id_col_league and team_id_col in teams.columns and team_id_col_league in league.columns):
        st.info("Team page requires TeamID in Teams_Table and League_Data.")
        st.stop()

    selected_team_id = str(team_row.get(team_id_col, "")).strip()
    if not selected_team_id:
        st.info("Selected team has no TeamID in Teams_Table.")
        st.stop()

    filtered_team = league.copy()
    filtered_team[team_id_col_league] = filtered_team[team_id_col_league].astype(str).str.strip()
    filtered_team = filtered_team[filtered_team[team_id_col_league] == selected_team_id]

    if filtered_team.empty:
        st.info("No matching player stats found for this team yet.")
        st.stop()

    numeric_cols = [
        "Runs Scored", "Balls Faced", "6s", "Retirements",
        "Batting Strike Rate", "Batting Average", "Highest Score",
        "Innings Played", "Not Out's",
        "Total Overs", "Overs", "Balls Bowled", "Maidens", "Runs Conceded", "Wickets",
        "Wides", "No Balls", "Economy", "Bowling Strike Rate", "Bowling Average",
        "Catches", "Run Outs", "Stumpings", "Fantasy Points",
    ]
    for c in numeric_cols:
        if c in filtered_team.columns:
            filtered_team[c] = pd.to_numeric(filtered_team[c], errors="coerce")

    # Selectors (Batting / Bowling / Fielding)
    BATTING_STATS = [
        "Runs Scored",
        "Balls Faced",
        "6s",
        "Retirements",
        "Batting Strike Rate",
        "Batting Average",
        "Highest Score",
        "Innings Played",
        "Not Out's",
    ]
    BOWLING_STATS = [
        "Total Overs",
        "Overs",
        "Balls Bowled",
        "Maidens",
        "Runs Conceded",
        "Wickets",
        "Wides",
        "No Balls",
        "Economy",
        "Bowling Strike Rate",
        "Bowling Average",
        "Best Figures",
    ]
    FIELDING_STATS = ["Catches", "Run Outs", "Stumpings"]

    batting_options = [c for c in BATTING_STATS if c in filtered_team.columns]
    bowling_options = [c for c in BOWLING_STATS if c in filtered_team.columns]
    fielding_options = [c for c in FIELDING_STATS if c in filtered_team.columns]

    default_batting = [c for c in ["Runs Scored", "Batting Average"] if c in batting_options]
    default_bowling = [c for c in ["Wickets", "Economy"] if c in bowling_options]
    default_fielding: list[str] = []

    _init_or_sanitize_multiselect_state_allow_empty("ts_batting_cols", batting_options, default_batting)
    _init_or_sanitize_multiselect_state_allow_empty("ts_bowling_cols", bowling_options, default_bowling)
    _init_or_sanitize_multiselect_state_allow_empty("ts_fielding_cols", fielding_options, default_fielding)

    st.markdown("#### Select Stats To Display")
    d1, d2, d3 = st.columns(3)
    with d1:
        selected_batting = st.multiselect("Batting Stats", options=batting_options, key="ts_batting_cols")
    with d2:
        selected_bowling = st.multiselect("Bowling Stats", options=bowling_options, key="ts_bowling_cols")
    with d3:
        selected_fielding = st.multiselect("Fielding Stats", options=fielding_options, key="ts_fielding_cols")

    selected_columns = selected_batting + selected_bowling + selected_fielding

    fixed_name = "Name" if "Name" in filtered_team.columns else (name_col if name_col in filtered_team.columns else None)
    fixed_cols: list[str] = []
    if fixed_name:
        fixed_cols.append(fixed_name)

    display_cols: list[str] = []
    for c in fixed_cols:
        if c in filtered_team.columns and c not in display_cols:
            display_cols.append(c)

    for c in selected_columns:
        if c in filtered_team.columns and c not in display_cols:
            display_cols.append(c)

    if "Fantasy Points" in filtered_team.columns and "Fantasy Points" not in display_cols:
        display_cols.append("Fantasy Points")

    player_view = filtered_team[display_cols].copy() if display_cols else filtered_team.copy()

    if "Fantasy Points" in player_view.columns:
        try:
            player_view = player_view.sort_values(by="Fantasy Points", ascending=False)
        except Exception:
            pass
    elif "Runs Scored" in player_view.columns:
        try:
            player_view = player_view.sort_values(by="Runs Scored", ascending=False)
        except Exception:
            pass

    col_config: dict = {}
    if fixed_name and fixed_name in player_view.columns:
        col_config[fixed_name] = st.column_config.TextColumn(pinned=True)

    for c in ["Batting Strike Rate", "Batting Average", "Economy", "Bowling Strike Rate", "Bowling Average"]:
        if c in player_view.columns:
            col_config[c] = st.column_config.NumberColumn(format="%.2f")

    # Do not pin Fantasy Points (ensures it stays far right)
    if "Fantasy Points" in player_view.columns:
        col_config["Fantasy Points"] = st.column_config.NumberColumn()

    st.markdown("#### Player Stats (Team)")
    st.data_editor(
        player_view,
        width="stretch",
        hide_index=True,
        disabled=True,
        column_config=col_config,
    )

    # Totals table (same columns as player_view)
    st.markdown("#### Team Totals")

    base = filtered_team.copy()

    def _sum(col: str) -> float | None:
        if col not in base.columns:
            return None
        s = pd.to_numeric(base[col], errors="coerce").fillna(0).sum()
        return float(s)

    totals_row: dict = {}
    if fixed_name:
        totals_row[fixed_name] = "Team Totals"

    for col in [
        "Runs Scored", "Balls Faced", "6s", "Retirements",
        "Innings Played", "Not Out's",
        "Total Overs", "Overs", "Balls Bowled", "Maidens", "Runs Conceded", "Wickets", "Wides", "No Balls",
        "Catches", "Run Outs", "Stumpings", "Fantasy Points",
    ]:
        val = _sum(col)
        if val is not None and col in player_view.columns:
            totals_row[col] = val

    if "Batting Strike Rate" in player_view.columns:
        rs = _sum("Runs Scored") or 0.0
        bf = _sum("Balls Faced") or 0.0
        totals_row["Batting Strike Rate"] = (rs / bf) * 100 if bf > 0 else pd.NA

    if "Batting Average" in player_view.columns:
        rs = _sum("Runs Scored") or 0.0
        inn = _sum("Innings Played")
        no = _sum("Not Out's")
        if inn is not None and no is not None:
            outs = inn - no
            outs = outs if outs > 0 else 1.0
            totals_row["Batting Average"] = rs / outs
        else:
            totals_row["Batting Average"] = pd.NA

    if "Economy" in player_view.columns:
        rc = _sum("Runs Conceded") or 0.0
        ov = _sum("Overs") or 0.0
        totals_row["Economy"] = (rc / ov) if ov > 0 else pd.NA

    if "Bowling Strike Rate" in player_view.columns:
        bb = _sum("Balls Bowled") or 0.0
        wk = _sum("Wickets") or 0.0
        totals_row["Bowling Strike Rate"] = (bb / wk) if wk > 0 else pd.NA

    if "Bowling Average" in player_view.columns:
        rc = _sum("Runs Conceded") or 0.0
        wk = _sum("Wickets") or 0.0
        totals_row["Bowling Average"] = (rc / wk) if wk > 0 else pd.NA

    totals_df = pd.DataFrame([{c: totals_row.get(c, pd.NA) for c in player_view.columns}])

    st.data_editor(
        totals_df,
        width="stretch",
        hide_index=True,
        disabled=True,
        column_config=col_config,
    )
# ============================
# TAB 4: PLAYER STATS
# ============================
if selected_tab == "Player Stats":
    st.subheader("Player Stats")

    league_df = data.league_data
    if league_df is None or league_df.empty:
        st.info("No player stats found yet (League_Data_Stats table not loaded).")
        st.stop()

    league = league_df.copy()
    league.columns = [str(c).strip() for c in league.columns]

    # -----------------------------
    # Map TeamID -> Team Names via Teams_Table
    # -----------------------------
    teams_df = getattr(data, "teams_table", None)
    if teams_df is None:
        teams_df = getattr(data, "teams", None)
    if teams_df is None:
        teams_df = getattr(data, "teams_data", None)

    team_id_col_league = _find_col(league, ["TeamID", "Team Id", "Team ID"])
    name_col = _find_col(league, ["Name"])

    team_id_to_name: dict[str, str] = {}
    team_name_to_id: dict[str, str] = {}

    if teams_df is not None and not teams_df.empty:
        teams = teams_df.copy()
        teams.columns = [str(c).strip() for c in teams.columns]

        team_id_col_teams = _find_col(teams, ["TeamID"])
        team_name_col_teams = _find_col(teams, ["Team Names"])

        if team_id_col_teams and team_name_col_teams:
            ttmp = teams[[team_id_col_teams, team_name_col_teams]].copy()
            ttmp[team_id_col_teams] = ttmp[team_id_col_teams].astype(str).str.strip()
            ttmp[team_name_col_teams] = ttmp[team_name_col_teams].astype(str).str.strip()
            ttmp = ttmp[(ttmp[team_id_col_teams] != "") & (ttmp[team_name_col_teams] != "")].drop_duplicates()

            team_id_to_name = dict(zip(ttmp[team_id_col_teams], ttmp[team_name_col_teams]))
            team_name_to_id = dict(zip(ttmp[team_name_col_teams], ttmp[team_id_col_teams]))

    # Team name helper column for filtering (TeamID never shown in UI)
    if team_id_col_league and team_id_col_league in league.columns and team_id_to_name:
        league[team_id_col_league] = league[team_id_col_league].astype(str).str.strip()
        league["Team"] = league[team_id_col_league].map(team_id_to_name)
    else:
        if "Team" not in league.columns:
            league["Team"] = None

    # Coerce numeric columns so Streamlit sorts numerically (not as strings)
    numeric_cols = [
        "Runs Scored",
        "Balls Faced",
        "6s",
        "Retirements",
        "Batting Strike Rate",
        "Batting Average",
        "Highest Score",
        "Innings Played",
        "Not Out's",
        "Total Overs",
        "Overs",
        "Balls Bowled",
        "Maidens",
        "Runs Conceded",
        "Wickets",
        "Wides",
        "No Balls",
        "Economy",
        "Bowling Strike Rate",
        "Bowling Average",
        "Catches",
        "Run Outs",
        "Stumpings",
        "Fantasy Points",
    ]
    for col in numeric_cols:
        if col in league.columns:
            league[col] = pd.to_numeric(league[col], errors="coerce")

    # -----------------------------
    # Filters (Team by name; Players optional and scoped by current team)
    # -----------------------------
    team_names = sorted([t for t in team_name_to_id.keys() if str(t).strip() != ""]) if team_name_to_id else []
    team_dropdown_options = ["All"] + team_names

    current_team_name = st.session_state.get("ps_team_name", "All")
    current_team_id = team_name_to_id.get(current_team_name) if current_team_name != "All" else None

    player_options_df = league
    if current_team_id is not None and team_id_col_league and team_id_col_league in league.columns:
        player_options_df = league[league[team_id_col_league].astype(str).str.strip() == str(current_team_id).strip()]

    if name_col and name_col in league.columns:
        player_options = player_options_df[name_col].dropna().astype(str).map(str.strip)
        player_options = sorted([p for p in player_options.unique().tolist() if p != ""])
    else:
        player_options = []

    # -----------------------------
    # Filters (no Apply button)
    # Team by name; Players optional and scoped by current team
    # -----------------------------
    team_names = sorted([t for t in team_name_to_id.keys() if str(t).strip() != ""]) if team_name_to_id else []
    team_dropdown_options = ["All"] + team_names

    c1, c2 = st.columns([2, 1])

    with c2:
        selected_team_name = st.selectbox(
            "Team",
            team_dropdown_options if team_dropdown_options else ["All"],
            key="ps_team_name",
        )

    selected_team_id = team_name_to_id.get(selected_team_name) if selected_team_name != "All" else None

    # Build player options based on currently selected team
    player_options_df = league
    if selected_team_id is not None and team_id_col_league and team_id_col_league in league.columns:
        player_options_df = league[
            league[team_id_col_league].astype(str).str.strip() == str(selected_team_id).strip()
        ]

    if name_col and name_col in league.columns:
        player_options = (
            player_options_df[name_col]
            .dropna()
            .astype(str)
            .map(str.strip)
        )
        player_options = sorted([p for p in player_options.unique().tolist() if p != ""])
    else:
        player_options = []

    # Drop any previously selected players that are no longer valid for this team
    current_players = st.session_state.get("ps_players", [])
    current_players = [p for p in current_players if p in player_options]
    st.session_state["ps_players"] = current_players

    with c1:
        selected_players = st.multiselect(
    "Players – Leave blank for all players",
    player_options,
    key="ps_players",
    )

    filtered = league.copy()

    if selected_team_id is not None and team_id_col_league and team_id_col_league in filtered.columns:
        filtered = filtered[filtered[team_id_col_league].astype(str).str.strip() == str(selected_team_id).strip()]

    if name_col and name_col in filtered.columns and selected_players:
        filtered = filtered[filtered[name_col].astype(str).str.strip().isin(selected_players)]

    # -----------------------------
    # Stat selectors (Batting / Bowling / Fielding)
    # Name fixed; Fantasy Points always last column
    # Defaults on first load: Runs Scored, Batting Average, Wickets, Economy
    # Users can clear all stat selections.
    # -----------------------------
    BATTING_STATS = [
        "Runs Scored",
        "Balls Faced",
        "6s",
        "Retirements",
        "Batting Strike Rate",
        "Batting Average",
        "Highest Score",
        "Innings Played",
        "Not Out's",
    ]

    BOWLING_STATS = [
        "Total Overs",
        "Overs",
        "Balls Bowled",
        "Maidens",
        "Runs Conceded",
        "Wickets",
        "Wides",
        "No Balls",
        "Economy",
        "Bowling Strike Rate",
        "Bowling Average",
        "Best Figures",
    ]

    FIELDING_STATS = [
        "Catches",
        "Run Outs",
        "Stumpings",
    ]

    batting_options = [c for c in BATTING_STATS if c in filtered.columns]
    bowling_options = [c for c in BOWLING_STATS if c in filtered.columns]
    fielding_options = [c for c in FIELDING_STATS if c in filtered.columns]

    default_batting = [c for c in ["Runs Scored", "Batting Average"] if c in batting_options]
    default_bowling = [c for c in ["Wickets", "Economy"] if c in bowling_options]
    default_fielding: list[str] = []

    st.markdown("#### Select Stats To Display")
    d1, d2, d3 = st.columns(3)

    DEFAULT_BATTING = ["Runs Scored", "Batting Average"]
    DEFAULT_BOWLING = ["Wickets", "Economy"]
    DEFAULT_FIELDING: list[str] = []

    batting_select_key = "batting_cols_select"
    bowling_select_key = "bowling_cols_select"
    fielding_select_key = "fielding_cols_select"

    if f"__prev_{batting_select_key}" not in st.session_state:
        st.session_state[f"__prev_{batting_select_key}"] = DEFAULT_BATTING
    if f"__prev_{bowling_select_key}" not in st.session_state:
        st.session_state[f"__prev_{bowling_select_key}"] = DEFAULT_BOWLING
    if f"__prev_{fielding_select_key}" not in st.session_state:
        st.session_state[f"__prev_{fielding_select_key}"] = DEFAULT_FIELDING

    with d1:
        batting_select_options = [ALL] + batting_options
        selected_batting = st.multiselect(
            "Batting stats",
            options=batting_select_options,
            default=DEFAULT_BATTING,
            key=batting_select_key,
            on_change=lambda: enforce_all_exclusive(batting_select_key),
        )
    with d2:
        bowling_select_options = [ALL] + bowling_options
        selected_bowling = st.multiselect(
            "Bowling stats",
            options=bowling_select_options,
            default=DEFAULT_BOWLING,
            key=bowling_select_key,
            on_change=lambda: enforce_all_exclusive(bowling_select_key),
        )
    with d3:
        fielding_select_options = [ALL] + fielding_options
        selected_fielding = st.multiselect(
            "Fielding stats",
            options=fielding_select_options,
            default=DEFAULT_FIELDING,
            key=fielding_select_key,
            on_change=lambda: enforce_all_exclusive(fielding_select_key),
        )

    resolved_batting = _resolved_selection(batting_select_key, batting_options, DEFAULT_BATTING)
    resolved_bowling = _resolved_selection(bowling_select_key, bowling_options, DEFAULT_BOWLING)
    resolved_fielding = _resolved_selection(fielding_select_key, fielding_options, DEFAULT_FIELDING)

    st.session_state[f"__prev_{batting_select_key}"] = st.session_state.get(batting_select_key) or []
    st.session_state[f"__prev_{bowling_select_key}"] = st.session_state.get(bowling_select_key) or []
    st.session_state[f"__prev_{fielding_select_key}"] = st.session_state.get(fielding_select_key) or []

    selected_columns = resolved_batting + resolved_bowling + resolved_fielding

    # Fixed columns (Name first)
    fixed_cols: list[str] = []
    if "Name" in filtered.columns:
        fixed_cols.append("Name")
    elif name_col and name_col in filtered.columns:
        fixed_cols.append(name_col)

    # Assemble display columns (Fantasy Points appended last)
    display_cols: list[str] = []
    for c in fixed_cols:
        if c and c in filtered.columns and c not in display_cols:
            display_cols.append(c)

    for c in selected_columns:
        if c in filtered.columns and c not in display_cols:
            display_cols.append(c)

    if "Fantasy Points" in filtered.columns and "Fantasy Points" not in display_cols:
        display_cols.append("Fantasy Points")

    view = filtered[display_cols].copy() if all(c in filtered.columns for c in display_cols) else filtered.copy()

    if "Fantasy Points" in view.columns:
        try:
            view = view.sort_values(by="Fantasy Points", ascending=False)
        except Exception:
            pass

    def _col_config_for(df: pd.DataFrame) -> dict:
        config: dict = {}
        # Pin Name only (Fantasy Points not pinned so it stays at the far right)
        if "Name" in df.columns:
            config["Name"] = st.column_config.TextColumn(pinned=True)
        elif name_col and name_col in df.columns:
            config[name_col] = st.column_config.TextColumn(pinned=True)

        for c in ["Batting Strike Rate", "Batting Average", "Economy", "Bowling Strike Rate", "Bowling Average"]:
            if c in df.columns:
                config[c] = st.column_config.NumberColumn(format="%.2f")

        # Do not pin Fantasy Points (ensures it stays the last visible column)
        if "Fantasy Points" in df.columns:
            config["Fantasy Points"] = st.column_config.NumberColumn()

        return config

    st.data_editor(
        view,
        width="stretch",
        hide_index=True,
        disabled=True,
        column_config=_col_config_for(view),
    )

# ============================
# TAB 5: HISTORICAL STATS
# ============================
if selected_tab == "Historical Stats":
    st.subheader("Historical Stats")

    hist_a = getattr(data, "history_A_25_26", None)
    hist_b = getattr(data, "history_B_24_25", None)

    if hist_a is None and hist_b is None:
        st.info("No historical tables found in the workbook.")
    else:
        def _normalize_name(name: str) -> str:
            return " ".join(str(name).split()).casefold()

        # Combine by normalized name, sum counting stats, and recompute rate stats from base columns.
        frames: list[pd.DataFrame] = []
        name_cols: list[str] = []
        pid_cols: list[str] = []

        for df, source in [(hist_a, "A_25_26"), (hist_b, "B_24_25")]:
            if df is None or df.empty:
                continue
            tmp = df.copy()
            tmp.columns = [str(c).strip() for c in tmp.columns]
            name_col = _find_col(tmp, ["Name", "Player", "Player Name"])
            if not name_col:
                continue
            pid_col = _find_col(tmp, ["PlayerID", "Player Id", "Player ID"])
            name_cols.append(name_col)
            if pid_col:
                pid_cols.append(pid_col)
            tmp["_name"] = tmp[name_col].astype(str).str.strip()
            tmp["_norm_name"] = tmp["_name"].apply(_normalize_name)
            tmp["_player_id"] = tmp[pid_col].astype(str).str.strip() if pid_col else ""
            tmp["_source"] = source
            frames.append(tmp)

        combined_view = None
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            combined = combined[combined["_norm_name"] != ""]

            rate_keywords = ["avg", "average", "sr", "strike", "economy", "econ", "rate", "%"]
            rate_cols = [
                c for c in combined.columns if any(k in str(c).casefold() for k in rate_keywords)
            ]

            internal_cols = {"_name", "_norm_name", "_player_id", "_source"}
            exclude_cols = set(name_cols + pid_cols) | internal_cols | set(rate_cols)

            counting_cols: list[str] = []
            for c in combined.columns:
                if c in exclude_cols:
                    continue
                if any(k in str(c).casefold() for k in rate_keywords):
                    continue
                series = pd.to_numeric(combined[c], errors="coerce")
                if series.notna().any():
                    counting_cols.append(c)

            grouped = combined.groupby("_norm_name", dropna=False)
            summed = grouped[counting_cols].agg(
                lambda s: pd.to_numeric(s, errors="coerce").sum(min_count=1)
            )

            name_display = grouped["_name"].agg(
                lambda s: s.dropna().astype(str).str.strip().mode().iat[0]
                if not s.dropna().empty
                else ""
            )

            def _pick_player_id(sub: pd.DataFrame) -> str:
                preferred = sub[sub["_source"] == "A_25_26"]["_player_id"]
                for val in preferred:
                    if val:
                        return str(val).strip()
                for val in sub["_player_id"]:
                    if val:
                        return str(val).strip()
                return ""

            pid_display = grouped.apply(_pick_player_id)

            result = summed.reset_index().rename(columns={"_norm_name": "Norm Name"})
            result["PlayerID"] = pid_display.values
            result["Name"] = name_display.values

            def _first_col(candidates: list[str]) -> str | None:
                for c in candidates:
                    if c in result.columns:
                        return c
                return None

            runs_col = _first_col(["Runs Scored", "Runs"])
            inns_col = _first_col(["Innings Played", "Innings"])
            not_out_col = _first_col(["Not Out's", "Not Outs", "Not Out", "NO"])
            balls_faced_col = _first_col(["Balls Faced", "Balls", "BF"])
            runs_conceded_col = _first_col(["Runs Conceded"])
            wickets_col = _first_col(["Wickets", "Wkts"])
            overs_col = _first_col(["Overs", "Overs Bowled"])
            balls_bowled_col = _first_col(["Balls Bowled", "Balls Bowled (Bowling)"])

            if "Batting Average" in rate_cols:
                if runs_col and inns_col and not_out_col:
                    outs = (result[inns_col] - result[not_out_col]).fillna(0.0)
                    outs = outs.where(outs > 0, 1.0)
                    result["Batting Average"] = result[runs_col] / outs
                else:
                    result["Batting Average"] = pd.NA

            if "Batting Strike Rate" in rate_cols:
                if runs_col and balls_faced_col:
                    denom = result[balls_faced_col].fillna(0.0)
                    denom = denom.where(denom > 0, pd.NA)
                    result["Batting Strike Rate"] = (result[runs_col] / denom) * 100
                else:
                    result["Batting Strike Rate"] = pd.NA

            if "Bowling Average" in rate_cols:
                if runs_conceded_col and wickets_col:
                    denom = result[wickets_col].fillna(0.0)
                    denom = denom.where(denom > 0, pd.NA)
                    result["Bowling Average"] = result[runs_conceded_col] / denom
                else:
                    result["Bowling Average"] = pd.NA

            if "Bowling Strike Rate" in rate_cols:
                if balls_bowled_col and wickets_col:
                    denom = result[wickets_col].fillna(0.0)
                    denom = denom.where(denom > 0, pd.NA)
                    result["Bowling Strike Rate"] = result[balls_bowled_col] / denom
                else:
                    result["Bowling Strike Rate"] = pd.NA

            if "Economy" in rate_cols:
                if runs_conceded_col and overs_col:
                    denom = result[overs_col].fillna(0.0)
                    denom = denom.where(denom > 0, pd.NA)
                    result["Economy"] = result[runs_conceded_col] / denom
                elif runs_conceded_col and balls_bowled_col:
                    overs = result[balls_bowled_col] / 6.0
                    denom = overs.fillna(0.0)
                    denom = denom.where(denom > 0, pd.NA)
                    result["Economy"] = result[runs_conceded_col] / denom
                else:
                    result["Economy"] = pd.NA

            base_order: list[str] = []
            for df in [hist_a, hist_b]:
                if df is None or df.empty:
                    continue
                base_order.extend([str(c).strip() for c in df.columns])
            ordered_cols: list[str] = []
            if "PlayerID" in result.columns:
                ordered_cols.append("PlayerID")
            if "Name" in result.columns:
                ordered_cols.append("Name")
            for c in base_order:
                if c in name_cols or c in pid_cols:
                    continue
                if c in result.columns and c not in ordered_cols:
                    ordered_cols.append(c)
            for c in result.columns:
                if c not in ordered_cols and c not in {"Norm Name"}:
                    ordered_cols.append(c)

            combined_view = _normalize_playerid_for_display(result[ordered_cols])

        datasets: dict[str, pd.DataFrame] = {}
        if hist_a is not None and not hist_a.empty:
            datasets["Sem A 25/26"] = _normalize_playerid_for_display(hist_a)
        if hist_b is not None and not hist_b.empty:
            datasets["Sem B 24/25"] = _normalize_playerid_for_display(hist_b)
        if combined_view is not None and not combined_view.empty:
            datasets["All-time"] = combined_view

        if not datasets:
            st.info("Historical tables are missing player names.")
        else:
            dataset_order = []
            if "All-time" in datasets:
                dataset_order.append("All-time")
            for label in ["Sem A 25/26", "Sem B 24/25"]:
                if label in datasets:
                    dataset_order.append(label)
            for label in datasets.keys():
                if label not in dataset_order:
                    dataset_order.append(label)

            selected_dataset = st.selectbox(
                "Historic Leagues",
                dataset_order,
                key="hs_dataset",
            )
            league = datasets[selected_dataset].copy()
            league.columns = [str(c).strip() for c in league.columns]

            name_col = _find_col(league, ["Name", "Player", "Player Name"])
            if not name_col:
                st.info("Historical tables do not include a Name column.")
            else:
                # Coerce numeric columns so Streamlit sorts numerically (not as strings)
                numeric_cols = [
                    "Runs Scored",
                    "Balls Faced",
                    "6s",
                    "Retirements",
                    "Batting Strike Rate",
                    "Batting Average",
                    "Highest Score",
                    "Innings Played",
                    "Not Out's",
                    "Total Overs",
                    "Overs",
                    "Balls Bowled",
                    "Maidens",
                    "Runs Conceded",
                    "Wickets",
                    "Wides",
                    "No Balls",
                    "Economy",
                    "Bowling Strike Rate",
                    "Bowling Average",
                    "Catches",
                    "Run Outs",
                    "Stumpings",
                    "Fantasy Points",
                ]
                for col in numeric_cols:
                    if col in league.columns:
                        league[col] = pd.to_numeric(league[col], errors="coerce")

                player_options = (
                    league[name_col]
                    .dropna()
                    .astype(str)
                    .map(str.strip)
                )
                player_options = sorted([p for p in player_options.unique().tolist() if p != ""])

                current_players = st.session_state.get("hs_players", [])
                current_players = [p for p in current_players if p in player_options]
                st.session_state["hs_players"] = current_players

                selected_players = st.multiselect(
                    "Players – Leave blank for all players",
                    player_options,
                    key="hs_players",
                )

                filtered = league.copy()

                if selected_players:
                    filtered = filtered[filtered[name_col].astype(str).str.strip().isin(selected_players)]

                BATTING_STATS = [
                    "Runs Scored",
                    "Balls Faced",
                    "6s",
                    "Retirements",
                    "Batting Strike Rate",
                    "Batting Average",
                    "Highest Score",
                    "Innings Played",
                    "Not Out's",
                ]

                BOWLING_STATS = [
                    "Total Overs",
                    "Overs",
                    "Balls Bowled",
                    "Maidens",
                    "Runs Conceded",
                    "Wickets",
                    "Wides",
                    "No Balls",
                    "Economy",
                    "Bowling Strike Rate",
                    "Bowling Average",
                    "Best Figures",
                ]

                FIELDING_STATS = [
                    "Catches",
                    "Run Outs",
                    "Stumpings",
                ]

                batting_options = [c for c in BATTING_STATS if c in filtered.columns]
                bowling_options = [c for c in BOWLING_STATS if c in filtered.columns]
                fielding_options = [c for c in FIELDING_STATS if c in filtered.columns]

                default_batting = [c for c in ["Runs Scored", "Batting Average"] if c in batting_options]
                default_bowling = [c for c in ["Wickets", "Economy"] if c in bowling_options]
                default_fielding: list[str] = []

                st.markdown("#### Select Stats To Display")
                d1, d2, d3 = st.columns(3)

                DEFAULT_BATTING = ["Runs Scored", "Batting Average"]
                DEFAULT_BOWLING = ["Wickets", "Economy"]
                DEFAULT_FIELDING: list[str] = []

                hs_batting_key = "hs_batting_cols_select"
                hs_bowling_key = "hs_bowling_cols_select"
                hs_fielding_key = "hs_fielding_cols_select"

                if f"__prev_{hs_batting_key}" not in st.session_state:
                    st.session_state[f"__prev_{hs_batting_key}"] = DEFAULT_BATTING
                if f"__prev_{hs_bowling_key}" not in st.session_state:
                    st.session_state[f"__prev_{hs_bowling_key}"] = DEFAULT_BOWLING
                if f"__prev_{hs_fielding_key}" not in st.session_state:
                    st.session_state[f"__prev_{hs_fielding_key}"] = DEFAULT_FIELDING

                with d1:
                    hs_batting_options = [ALL] + batting_options
                    selected_batting = st.multiselect(
                        "Batting stats",
                        options=hs_batting_options,
                        default=DEFAULT_BATTING,
                        key=hs_batting_key,
                        on_change=lambda: enforce_all_exclusive(hs_batting_key),
                    )
                with d2:
                    hs_bowling_options = [ALL] + bowling_options
                    selected_bowling = st.multiselect(
                        "Bowling stats",
                        options=hs_bowling_options,
                        default=DEFAULT_BOWLING,
                        key=hs_bowling_key,
                        on_change=lambda: enforce_all_exclusive(hs_bowling_key),
                    )
                with d3:
                    hs_fielding_options = [ALL] + fielding_options
                    selected_fielding = st.multiselect(
                        "Fielding stats",
                        options=hs_fielding_options,
                        default=DEFAULT_FIELDING,
                        key=hs_fielding_key,
                        on_change=lambda: enforce_all_exclusive(hs_fielding_key),
                    )

                resolved_batting = _resolved_selection(hs_batting_key, batting_options, DEFAULT_BATTING)
                resolved_bowling = _resolved_selection(hs_bowling_key, bowling_options, DEFAULT_BOWLING)
                resolved_fielding = _resolved_selection(hs_fielding_key, fielding_options, DEFAULT_FIELDING)

                st.session_state[f"__prev_{hs_batting_key}"] = st.session_state.get(hs_batting_key) or []
                st.session_state[f"__prev_{hs_bowling_key}"] = st.session_state.get(hs_bowling_key) or []
                st.session_state[f"__prev_{hs_fielding_key}"] = st.session_state.get(hs_fielding_key) or []

                selected_columns = resolved_batting + resolved_bowling + resolved_fielding

                fixed_cols: list[str] = []
                if name_col in filtered.columns:
                    fixed_cols.append(name_col)

                display_cols: list[str] = []
                for c in fixed_cols:
                    if c and c in filtered.columns and c not in display_cols:
                        display_cols.append(c)

                for c in selected_columns:
                    if c in filtered.columns and c not in display_cols:
                        display_cols.append(c)

                if "Fantasy Points" in filtered.columns and "Fantasy Points" not in display_cols:
                    display_cols.append("Fantasy Points")

                view = filtered[display_cols].copy() if all(c in filtered.columns for c in display_cols) else filtered.copy()

                if "Fantasy Points" in view.columns:
                    try:
                        view = view.sort_values(by="Fantasy Points", ascending=False)
                    except Exception:
                        pass

                col_config: dict = {}
                if name_col in view.columns:
                    col_config[name_col] = st.column_config.TextColumn(pinned=True)

                for c in ["Batting Strike Rate", "Batting Average", "Economy", "Bowling Strike Rate", "Bowling Average"]:
                    if c in view.columns:
                        col_config[c] = st.column_config.NumberColumn(format="%.2f")

                if "Fantasy Points" in view.columns:
                    col_config["Fantasy Points"] = st.column_config.NumberColumn()

                st.markdown("#### Player Stats")
                st.data_editor(
                    view,
                    width="stretch",
                    hide_index=True,
                    disabled=True,
                    column_config=col_config,
                )

                st.markdown("#### Totals")
                base = filtered.copy()

                def _sum(col: str) -> float | None:
                    if col not in base.columns:
                        return None
                    s = pd.to_numeric(base[col], errors="coerce").fillna(0).sum()
                    return float(s)

                totals_row: dict = {}
                totals_row[name_col] = "Totals"

                for col in [
                    "Runs Scored", "Balls Faced", "6s", "Retirements",
                    "Innings Played", "Not Out's",
                    "Total Overs", "Overs", "Balls Bowled", "Maidens", "Runs Conceded", "Wickets", "Wides", "No Balls",
                    "Catches", "Run Outs", "Stumpings", "Fantasy Points",
                ]:
                    val = _sum(col)
                    if val is not None and col in view.columns:
                        totals_row[col] = val

                if "Batting Strike Rate" in view.columns:
                    rs = _sum("Runs Scored") or 0.0
                    bf = _sum("Balls Faced") or 0.0
                    totals_row["Batting Strike Rate"] = (rs / bf) * 100 if bf > 0 else pd.NA

                if "Batting Average" in view.columns:
                    rs = _sum("Runs Scored") or 0.0
                    inn = _sum("Innings Played")
                    no = _sum("Not Out's")
                    if inn is not None and no is not None:
                        outs = inn - no
                        outs = outs if outs > 0 else 1.0
                        totals_row["Batting Average"] = rs / outs
                    else:
                        totals_row["Batting Average"] = pd.NA

                if "Economy" in view.columns:
                    rc = _sum("Runs Conceded") or 0.0
                    ov = _sum("Overs") or 0.0
                    totals_row["Economy"] = (rc / ov) if ov > 0 else pd.NA

                if "Bowling Strike Rate" in view.columns:
                    bb = _sum("Balls Bowled") or 0.0
                    wk = _sum("Wickets") or 0.0
                    totals_row["Bowling Strike Rate"] = (bb / wk) if wk > 0 else pd.NA

                if "Bowling Average" in view.columns:
                    rc = _sum("Runs Conceded") or 0.0
                    wk = _sum("Wickets") or 0.0
                    totals_row["Bowling Average"] = (rc / wk) if wk > 0 else pd.NA

                totals_df = pd.DataFrame([{c: totals_row.get(c, pd.NA) for c in view.columns}])

                st.data_editor(
                    totals_df,
                    width="stretch",
                    hide_index=True,
                    disabled=True,
                    column_config=col_config,
                )
# ============================
# TAB 6: SCORECARDS
# ============================
if selected_tab == "Scorecards":
    st.subheader("Scorecards")

    st.markdown("---")

    if "MatchID" not in fixtures.columns:
        st.info("Scorecards are not available because this workbook does not contain a 'MatchID' column.")
        st.stop()

    # Build a friendly fixture selector (Option A)
    fsel = fixtures.copy()
    fsel.columns = [str(c).strip() for c in fsel.columns]

    # Format date/time for display if present
    if "Date" in fsel.columns:
        fsel["Date"] = _format_date_dd_mmm(fsel["Date"])
    if "Time" in fsel.columns:
        fsel["Time"] = _format_time_ampm(fsel["Time"])

    def _safe(v) -> str:
        if pd.isna(v):
            return ""
        return str(v).strip()


    # Build all fixture options
    options: list[str] = []
    option_to_match: dict[str, str] = {}

    for _, r in fsel.iterrows():
        mid = _safe(r.get("MatchID"))
        if not mid:
            continue

        # Dropdown label for normal users: "01-Jan - 7 PM - Home vs Away"
        date_txt = _safe(r.get("Date")) if "Date" in fsel.columns else ""

        # Time is already formatted earlier via _format_time_ampm; reduce to "H AM/PM"
        time_txt = _safe(r.get("Time")) if "Time" in fsel.columns else ""
        if time_txt:
            # Examples handled: "7:00 PM" -> "7 PM", "7 PM" -> "7 PM"
            t = time_txt.replace(".", "").strip()
            if ":" in t:
                # "7:00 PM" -> ["7", "00 PM"] -> hour="7", ampm="PM"
                hour_part = t.split(":", 1)[0].strip()
                ampm_part = t.split(" ", 1)[-1].strip().upper()  # "PM"/"AM"
                time_txt = f"{hour_part} {ampm_part}"
            else:
                # Ensure spacing/case is consistent if already "7 PM"
                parts = t.split()
                if len(parts) >= 2:
                    time_txt = f"{parts[0]} {parts[-1].upper()}"

        match_txt = ""
        if "Home Team" in fsel.columns and "Away Team" in fsel.columns:
            match_txt = f"{_safe(r.get('Home Team'))} vs {_safe(r.get('Away Team'))}"

        label = " - ".join([p for p in [date_txt, time_txt, match_txt] if p])

        options.append(label)
        option_to_match[label] = mid

    if not options:
        st.info("No fixtures with a valid MatchID were found.")
        st.stop()

    # -------------------------------------------------
    # Fast filter: one DB query for all MatchIDs that have scorecards
    # -------------------------------------------------
    match_ids_with_scorecards = set(list_scorecard_match_ids())

    filtered_options = [label for label in options if option_to_match[label] in match_ids_with_scorecards]

    if not filtered_options:
        st.info("No scorecards have been uploaded for any fixtures yet.")
        st.stop()

    selected_fixture = st.selectbox(
        "Select a fixture to view available scorecards",
        filtered_options,
        key="fixtures_scorecard_select",
    )
    selected_match_id = option_to_match[selected_fixture]

    available = sorted(
        list_scorecards(selected_match_id),
        key=lambda r: (str(r.get("uploaded_at") or ""), int(r.get("scorecard_id") or 0)),
    )
    if not available:
        st.info("No scorecards have been uploaded for this fixture yet.")
        st.stop()

    st.caption(f"{len(available)} file(s) available")

    # -----------------------------
    # Image viewer (press & hold on mobile) - buttons only
    # -----------------------------
    image_rows = []
    for row in available:
        fname = (row.get("file_name") or "").strip()
        if fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            image_rows.append(row)

    if image_rows:
        st.caption("Mobile (iPhone): press and hold the image to ‘Save to Photos’.")

        # Persistent index per match
        idx_key = f"scorecard_img_idx_{selected_match_id}"
        if idx_key not in st.session_state:
            st.session_state[idx_key] = 0

        # Clamp index (in case images were added/removed)
        n = len(image_rows)
        st.session_state[idx_key] = max(0, min(int(st.session_state[idx_key]), n - 1))
        idx = int(st.session_state[idx_key])

        # Render current image
        row = image_rows[idx]
        raw_fname = (row.get("file_name") or f"scorecard_{idx+1}").strip()

        # Remove file extension for display only
        fname = raw_fname.rsplit(".", 1)[0] if "." in raw_fname else raw_fname
        dbx_path = row.get("dropbox_path")

        if dbx_path:
            try:
                img_bytes = _download_scorecard_bytes(app_key, app_secret, refresh_token, dbx_path)
                st.markdown(f"**{fname}**")
                st.image(img_bytes, width="stretch")
            except Exception as e:
                st.warning(f"Could not load image '{fname}': {e}")

        # Image position indicator directly under the image
        st.caption(f"Image {idx + 1} of {n}")

        # Navigation buttons BELOW the caption
        c_prev, c_next = st.columns([1, 1])

        with c_prev:
            if st.button(
                "◀ Previous",
                width="stretch",
                disabled=(idx == 0),
                key=f"img_prev_{selected_match_id}",
            ):
                st.session_state[idx_key] = max(0, idx - 1)

        with c_next:
            if st.button(
                "Next ▶",
                width="stretch",
                disabled=(idx >= n - 1),
                key=f"img_next_{selected_match_id}",
            ):
                st.session_state[idx_key] = min(n - 1, idx + 1)

    # -----------------------------
    # PDFs (open in a new tab via Dropbox temporary link)
    # -----------------------------
    pdf_rows = []
    for row in available:
        fname = (row.get("file_name") or "").strip()
        if fname.lower().endswith(".pdf"):
            pdf_rows.append(row)

    if pdf_rows:
        st.markdown("#### PDFs")
        st.caption("Tap/click a PDF to open it in a new tab. Links are temporary.")

        for i, row in enumerate(pdf_rows):
            fname = (row.get("file_name") or f"scorecard_{i+1}.pdf").strip()
            dbx_path = row.get("dropbox_path")
            if not dbx_path:
                continue

            try:
                url = _get_temp_link(app_key, app_secret, refresh_token, dbx_path)
                # (1) Explicit key to prevent duplicate widget ID issues
                st.link_button(
                    f"{fname}",
                    url,
                    width="stretch",
                )
            except Exception as e:
                st.warning(f"Could not create link for '{fname}': {e}")
