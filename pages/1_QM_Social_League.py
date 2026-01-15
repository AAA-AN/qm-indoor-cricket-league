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
fixtures.columns = [str(c).strip() for c in fixtures.columns]


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

    if status_col:
        played_mask = df[status_col].astype(str).str.strip().isin(["Played", "Abandoned"])
    else:
        played_mask = df[winner_col].notna()

    played = df.loc[played_mask]

    rows = []
    for _, r in played.iterrows():
        home = str(r[home_col]).strip()
        away = str(r[away_col]).strip()
        winner = str(r[winner_col]).strip()

        home_pts, away_pts = 0, 0

        if winner == "Tied":
            home_pts = away_pts = 1
        elif winner == home:
            home_pts = 3
        elif winner == away:
            away_pts = 3

        rows.append({"Team": home, "Played": 1, "Points": home_pts})
        rows.append({"Team": away, "Played": 1, "Points": away_pts})

    if not rows:
        return pd.DataFrame(columns=["Pos", "Team", "Played", "Points"])

    pts = pd.DataFrame(rows).groupby("Team", as_index=False).sum()
    pts = pts.sort_values(by=["Points", "Team"], ascending=[False, True])
    pts.insert(0, "Pos", range(1, len(pts) + 1))
    return pts.reset_index(drop=True)


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


# ----------------------------
# Tabs (Player Stats FIRST)
# ----------------------------
tab_stats, tab_fixtures, tab_teams = st.tabs(
    ["Player Stats", "Fixtures & Results", "Teams"]
)

# ============================
# TAB 1: PLAYER STATS
# ============================
with tab_stats:
    st.subheader("Player Stats")

    league = data.league_data.copy()
    league.columns = [str(c).strip() for c in league.columns]

    numeric_cols = [
        "Runs Scored", "Balls Faced", "6s", "Retirements",
        "Batting Strike Rate", "Batting Average", "Highest Score",
        "Innings Played", "Not Out's", "Sum of Overs", "Overs",
        "Balls Bowled", "Maidens", "Runs Conceded", "Wickets",
        "Wides", "No Balls", "Economy",
        "Bowling Strike Rate", "Bowling Average",
        "Catches", "Run Outs", "Stumpings", "Fantasy Points",
    ]
    for c in numeric_cols:
        if c in league.columns:
            league[c] = pd.to_numeric(league[c], errors="coerce")

    name_col = _find_col(league, ["Name"])
    team_col = _find_col(league, ["Team", "Team Name"])

    with st.form("player_filters", clear_on_submit=False):
        c1, c2 = st.columns([2, 1])

        with c2:
            teams = ["All"]
            if team_col:
                teams += sorted(league[team_col].dropna().astype(str).unique())
            st.selectbox("Team", teams, key="team")

        with c1:
            names = []
            if name_col:
                names = sorted(league[name_col].dropna().astype(str).unique())
            st.multiselect("Players", names, key="players")

        st.form_submit_button("Apply")

    filtered = league.copy()

    if team_col and st.session_state.team != "All":
        filtered = filtered[filtered[team_col] == st.session_state.team]

    if name_col and st.session_state.players:
        filtered = filtered[filtered[name_col].isin(st.session_state.players)]

    main_cols = [
        "Name", "Runs Scored", "Batting Average",
        "Wickets", "Economy", "Fantasy Points",
    ]

    desired_cols = [
        "Name", "Runs Scored", "Balls Faced", "6s", "Retirements",
        "Batting Strike Rate", "Batting Average", "Highest Score",
        "Innings Played", "Not Out's", "Sum of Overs", "Overs",
        "Balls Bowled", "Maidens", "Runs Conceded", "Wickets",
        "Wides", "No Balls", "Economy",
        "Bowling Strike Rate", "Bowling Average",
        "Catches", "Run Outs", "Stumpings", "Fantasy Points",
    ]

    st.dataframe(filtered[main_cols], hide_index=True, use_container_width=True)

    with st.expander("Show all stats"):
        st.dataframe(filtered[desired_cols], hide_index=True, use_container_width=True)


# ============================
# TAB 2: FIXTURES
# ============================
with tab_fixtures:
    st.subheader("Fixtures & Results")

    display = fixtures.copy()
    if "Date" in display.columns:
        display["Date"] = _format_date_dd_mmm(display["Date"])
    if "Time" in display.columns:
        display["Time"] = _format_time_ampm(display["Time"])

    st.dataframe(display, hide_index=True, use_container_width=True)

    st.markdown("---")
    st.subheader("League Table")
    st.dataframe(compute_points_table(fixtures), hide_index=True, use_container_width=True)


# ============================
# TAB 3: TEAMS
# ============================
with tab_teams:
    st.subheader("Teams")
    st.info("Teams page will be built next (rosters + team totals).")
