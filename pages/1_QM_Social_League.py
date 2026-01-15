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
# Tabs
# ----------------------------
tab1, tab2, tab3 = st.tabs(["Fixtures & Results", "Teams", "Player Stats"])

with tab1:
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


with tab2:
    st.subheader("Teams")
    st.info("Teams page will be built next (rosters + team totals).")


with tab3:
    st.subheader("Player Stats")

    league_df = data.league_data
    if league_df is None or league_df.empty:
        st.info("No player stats found yet (League_Data_Stats table not loaded).")
        st.stop()

    league = league_df.copy()
    league.columns = [str(c).strip() for c in league.columns]

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

    # Filters
    name_col = _find_col(league, ["Name"])
    team_col = _find_col(league, ["Team", "TeamName", "Team Name"])

    c1, c2 = st.columns([2, 1])
    with c1:
        q = st.text_input("Search players", placeholder="Type a player name...").strip().lower()
    with c2:
        if team_col:
            teams = sorted([t for t in league[team_col].dropna().astype(str).unique().tolist() if t.strip() != ""])
            team_choice = st.selectbox("Team", ["All"] + teams)
        else:
            team_choice = "All"

    filtered = league.copy()

    if team_col and team_choice != "All":
        filtered = filtered[filtered[team_col].astype(str) == team_choice]

    if q and name_col and name_col in filtered.columns:
        filtered = filtered[filtered[name_col].astype(str).str.lower().str.contains(q, na=False)]
    elif q:
        mask = False
        for c in filtered.columns:
            mask = mask | filtered[c].astype(str).str.lower().str.contains(q, na=False)
        filtered = filtered[mask]

    # Only show requested columns, in the exact order provided
    desired_cols = [
        "Name",
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
        "Best Figures",
        "Catches",
        "Run Outs",
        "Stumpings",
        "Fantasy Points",
    ]

    show_cols = [c for c in desired_cols if c in filtered.columns]
    filtered_view = filtered[show_cols] if show_cols else filtered

    # Optional: sort by Fantasy Points if present
    if "Fantasy Points" in filtered_view.columns:
        try:
            filtered_view = filtered_view.sort_values(by="Fantasy Points", ascending=False)
        except Exception:
            pass

    two_dp_cols = [
    "Batting Strike Rate",
    "Batting Average",
    "Economy",
    "Bowling Strike Rate",
    "Bowling Average",
]

col_config = {
    c: st.column_config.NumberColumn(format="%.2f")
    for c in two_dp_cols
    if c in filtered_view.columns
}

st.dataframe(
    filtered_view,
    width="stretch",
    hide_index=True,
    column_config=col_config,
)

