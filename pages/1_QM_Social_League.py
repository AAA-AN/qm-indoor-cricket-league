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
from src.dropbox_api import get_access_token, download_file
from src.excel_io import load_league_workbook_from_bytes

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

fixtures = data.fixture_results.copy()
fixtures.columns = [str(c).strip() for c in fixtures.columns]  # robust header cleanup


def _format_date_dd_mmm(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce", dayfirst=True)
    return dt.dt.strftime("%d-%b").fillna(series.astype(str))


def _format_time_ampm(series: pd.Series) -> pd.Series:
    t = pd.to_datetime(series.astype(str), errors="coerce")
    t2 = pd.to_datetime("2000-01-01 " + series.astype(str), errors="coerce")
    out = t.fillna(t2)

    formatted = out.dt.strftime("%-I %p")
    formatted = formatted.where(formatted.notna(), out.dt.strftime("%I %p").str.lstrip("0"))

    mins = out.dt.minute
    with_mins = out.dt.strftime("%-I:%M %p")
    with_mins = with_mins.where(with_mins.notna(), out.dt.strftime("%I:%M %p").str.lstrip("0"))

    formatted = formatted.where((mins == 0) | (mins.isna()), with_mins)
    return formatted.fillna(series.astype(str))


def compute_points_table(fixtures_df: pd.DataFrame) -> pd.DataFrame:
    df = fixtures_df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    home_col = "Home Team"
    away_col = "Away Team"
    winner_col = "Won By"
    status_col = "Status" if "Status" in df.columns else None

    required = [home_col, away_col, winner_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.DataFrame(columns=["Pos", "Team", "Played", "Points"])

    if status_col:
        played_mask = df[status_col].astype(str).str.strip().isin(["Played", "Abandoned"])
    else:
        played_mask = df[winner_col].notna() & (df[winner_col].astype(str).str.strip() != "")

    played = df.loc[played_mask].copy()

    rows = []
    for _, r in played.iterrows():
        home = str(r[home_col]).strip()
        away = str(r[away_col]).strip()
        winner = "" if pd.isna(r[winner_col]) else str(r[winner_col]).strip()

        home_pts = 0
        away_pts = 0

        if winner == "No Result":
            home_pts = 0
            away_pts = 0
        elif winner == "Tied":
            home_pts = 1
            away_pts = 1
        elif winner == home:
            home_pts = 3
            away_pts = 0
        elif winner == away:
            home_pts = 0
            away_pts = 3

        rows.append({"Team": home, "Played": 1, "Points": home_pts})
        rows.append({"Team": away, "Played": 1, "Points": away_pts})

    if not rows:
        return pd.DataFrame(columns=["Pos", "Team", "Played", "Points"])

    pts = pd.DataFrame(rows).groupby("Team", as_index=False).sum(numeric_only=True)
    pts = pts.sort_values(by=["Points", "Team"], ascending=[False, True]).reset_index(drop=True)
    pts.insert(0, "Pos", range(1, len(pts) + 1))
    return pts


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = list(df.columns)
    for c in candidates:
        if c in cols:
            return c
    return None


# ----------------------------
# Tabs (Player Stats first)
# ----------------------------
tab_stats, tab_fixtures, tab_teams = st.tabs(["Player Stats", "Fixtures & Results", "Teams"])


# ============================
# TAB 1: PLAYER STATS
# ============================
with tab_stats:
    st.subheader("Player Stats")

    league_df = data.league_data
    if league_df is None or league_df.empty:
        st.info("No player stats found yet (League_Data_Stats table not loaded).")
        st.stop()

    league = league_df.copy()
    league.columns = [str(c).strip() for c in league.columns]

    # -----------------------------
    # Map TeamID -> Team Names via Teams_Table (exact headers)
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

        # Your Teams_Table headers:
        # TeamID | Team Names | Active | Captain's Name | Captain's PlayerID | Player 1..8
        team_id_col_teams = _find_col(teams, ["TeamID"])
        team_name_col_teams = _find_col(teams, ["Team Names"])

        if team_id_col_teams and team_name_col_teams:
            ttmp = teams[[team_id_col_teams, team_name_col_teams]].copy()

            # Treat TeamID as string (important)
            ttmp[team_id_col_teams] = ttmp[team_id_col_teams].astype(str).str.strip()
            ttmp[team_name_col_teams] = ttmp[team_name_col_teams].astype(str).str.strip()

            # Drop blanks and duplicates
            ttmp = ttmp[
                (ttmp[team_id_col_teams] != "") &
                (ttmp[team_name_col_teams] != "")
            ].drop_duplicates()

            team_id_to_name = dict(zip(ttmp[team_id_col_teams], ttmp[team_name_col_teams]))
            team_name_to_id = dict(zip(ttmp[team_name_col_teams], ttmp[team_id_col_teams]))

    # Add a friendly Team name column to league (TeamID never shown in the UI)
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
        "Sum of Overs",
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

    # Use last-selected team to scope the player list (so player selection is team-aware)
    current_team_name = st.session_state.get("ps_team_name", "All")
    current_team_id = team_name_to_id.get(current_team_name) if current_team_name != "All" else None

    player_options_df = league
    if current_team_id is not None and team_id_col_league and team_id_col_league in league.columns:
        player_options_df = league[
            league[team_id_col_league].astype(str).str.strip() == str(current_team_id).strip()
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

    with st.form("player_stats_filters", clear_on_submit=False):
        c1, c2 = st.columns([2, 1])

        with c2:
            st.selectbox(
                "Team",
                team_dropdown_options if team_dropdown_options else ["All"],
                key="ps_team_name",
            )

        with c1:
            st.multiselect(
                "Players (optional)",
                player_options,
                default=st.session_state.get("ps_players", []),
                key="ps_players",
            )

        st.form_submit_button("Apply")

    selected_team_name = st.session_state.get("ps_team_name", "All")
    selected_team_id = team_name_to_id.get(selected_team_name) if selected_team_name != "All" else None
    selected_players = st.session_state.get("ps_players", [])

    filtered = league.copy()

    # Filter by TeamID internally based on the Team name selection
    if selected_team_id is not None and team_id_col_league and team_id_col_league in filtered.columns:
        filtered = filtered[
            filtered[team_id_col_league].astype(str).str.strip() == str(selected_team_id).strip()
        ]

    # If players chosen, further restrict; if blank, show whole team (or everyone if Team=All)
    if name_col and name_col in filtered.columns and selected_players:
        filtered = filtered[filtered[name_col].astype(str).str.strip().isin(selected_players)]

    # -----------------------------
    # Three selectors + single table (no "Key Stats" table)
    # Defaults match old Key Stats:
    # Name, Runs Scored, Batting Average, Wickets, Economy, Fantasy Points
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
        "Sum of Overs",
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

    # Keep only columns that exist
    batting_options = [c for c in BATTING_STATS if c in filtered.columns]
    bowling_options = [c for c in BOWLING_STATS if c in filtered.columns]
    fielding_options = [c for c in FIELDING_STATS if c in filtered.columns]

    # Defaults = old Key Stats (where they live)
    default_batting = [c for c in ["Runs Scored", "Batting Average"] if c in batting_options]
    default_bowling = [c for c in ["Wickets", "Economy"] if c in bowling_options]
    default_fielding: list[str] = []  # old key stats had no fielding columns by default

        # Reset invalid prior selections if the available options change (e.g. team filter changes)
    def _init_or_sanitize_multiselect_state(key: str, options: list[str], defaults: list[str]) -> None:
        if key not in st.session_state:
            st.session_state[key] = defaults
            return
        current = st.session_state.get(key, [])
        current = [c for c in current if c in options]
        st.session_state[key] = current if current else defaults

    _init_or_sanitize_multiselect_state("ps_batting_cols", batting_options, default_batting)
    _init_or_sanitize_multiselect_state("ps_bowling_cols", bowling_options, default_bowling)
    _init_or_sanitize_multiselect_state("ps_fielding_cols", fielding_options, default_fielding)

    st.markdown("#### Select Stats To Display")
    d1, d2, d3 = st.columns(3)

    with d1:
        selected_batting = st.multiselect(
            "Batting Stats",
            options=batting_options,
            key="ps_batting_cols",
        )

    with d2:
        selected_bowling = st.multiselect(
            "Bowling Stats",
            options=bowling_options,
            key="ps_bowling_cols",
        )

    with d3:
        selected_fielding = st.multiselect(
            "Fielding Stats",
            options=fielding_options,
            key="ps_fielding_cols",
        )

    # Always keep Name first and Fantasy Points included by default (to match old Key Stats)
    display_cols = ["Name"]
    for c in selected_columns:
        if c not in display_cols:
            display_cols.append(c)

    if "Fantasy Points" in filtered.columns and "Fantasy Points" not in display_cols:
        display_cols.append("Fantasy Points")

    # Build view
    view = filtered[display_cols] if all(c in filtered.columns for c in display_cols) else filtered

    # Default sort by Fantasy Points (users can still click to sort)
    if "Fantasy Points" in view.columns:
        try:
            view = view.sort_values(by="Fantasy Points", ascending=False)
        except Exception:
            pass

    # Column config: pin Name, 2dp formatting for specified metrics
    def _col_config_for(df: pd.DataFrame) -> dict:
        config: dict = {}

        if "Name" in df.columns:
            config["Name"] = st.column_config.TextColumn(pinned=True)

        for c in [
            "Batting Strike Rate",
            "Batting Average",
            "Economy",
            "Bowling Strike Rate",
            "Bowling Average",
        ]:
            if c in df.columns:
                config[c] = st.column_config.NumberColumn(format="%.2f")

        return config

    st.data_editor(
        view,
        width="stretch",
        hide_index=True,
        disabled=True,
        column_config=_col_config_for(view),
    )


# ============================
# TAB 2: FIXTURES & RESULTS
# ============================

with tab_fixtures:
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

    st.markdown("---")
    st.subheader("League Table")

    table = compute_points_table(fixtures)
    if table.empty:
        st.info("No completed matches found yet.")
    else:
        st.dataframe(table, width="stretch", hide_index=True)


# ============================
# TAB 3: TEAMS
# ============================
with tab_teams:
    st.subheader("Teams")
    st.info("Teams page will be built next (rosters + team totals).")
