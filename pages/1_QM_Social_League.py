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

# Robustness: strip whitespace from all column names
fixtures.columns = [str(c).strip() for c in fixtures.columns]

# ----------------------------
# Tabs
# ----------------------------
tab1, tab2, tab3 = st.tabs(["Fixtures & Results", "Teams", "Player Stats"])


def compute_points_table(fixtures_df: pd.DataFrame) -> pd.DataFrame:
    """
    Points rules:
      Win = 3, Tie = 1, Loss = 0, No Result/Abandoned = 0

    Won By contains:
      - Home Team name OR Away Team name OR "Tied" OR "No Result"
    """
    df = fixtures_df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    home_col = "Home Team"
    away_col = "Away Team"
    winner_col = "Won By"
    status_col = "Status" if "Status" in df.columns else None

    missing = [c for c in [home_col, away_col, winner_col] if c not in df.columns]
    if missing:
        raise ValueError(f"Fixtures table missing required columns: {missing}. Columns found: {list(df.columns)}")

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
        return pd.DataFrame(columns=["Team", "Played", "Points"])

    pts = pd.DataFrame(rows).groupby("Team", as_index=False).sum(numeric_only=True)
    pts = pts.sort_values(by=["Points", "Team"], ascending=[False, True]).reset_index(drop=True)
    pts.insert(0, "Pos", range(1, len(pts) + 1))
    return pts


with tab1:
    st.subheader("Fixtures & Results")

    preferred_cols = [
        "MatchID",
        "Date",
        "Time",
        "Home Team",
        "Away Team",
        "Won By",
        "Status",
    ]
    show_cols = [c for c in preferred_cols if c in fixtures.columns]
    st.dataframe(fixtures[show_cols] if show_cols else fixtures, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("League Table (Win 3, Tie 1, Loss 0, Abandoned 0)")

    table = compute_points_table(fixtures)
    if table.empty:
        st.info("No completed matches found yet.")
    else:
        st.dataframe(table, use_container_width=True, hide_index=True)


with tab2:
    st.subheader("Teams")
    st.info("Next: display each team roster and team totals from Players/League_Data.")


with tab3:
    st.subheader("Player Stats")
    st.info("Next: show League_Data with search/filter and player profiles.")
