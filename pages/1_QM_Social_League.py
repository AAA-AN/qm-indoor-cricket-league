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

# ------------------------------------------------------------
# App setup
# ------------------------------------------------------------
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


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


# ------------------------------------------------------------
# Load data
# ------------------------------------------------------------
try:
    app_key = _get_secret("DROPBOX_APP_KEY")
    app_secret = _get_secret("DROPBOX_APP_SECRET")
    refresh_token = _get_secret("DROPBOX_REFRESH_TOKEN")
    dropbox_path = _get_secret("DROPBOX_FILE_PATH")
except Exception as e:
    st.error(str(e))
    st.stop()

with st.spinner("Loading latest league workbook from Dropbox..."):
    data = _load_from_dropbox(app_key, app_secret, refresh_token, dropbox_path)

fixtures = data.fixture_results.copy()
fixtures.columns = [str(c).strip() for c in fixtures.columns]

league_table = data.league_table.copy() if data.league_table is not None else pd.DataFrame()
if not league_table.empty:
    league_table.columns = [str(c).strip() for c in league_table.columns]


# ------------------------------------------------------------
# Stateful tab navigation (radio-based)
# ------------------------------------------------------------
selected_tab = st.radio(
    "",
    ["Player Stats", "Fixtures & Results", "League Table", "Teams"],
    horizontal=True,
    key="main_tab",
    label_visibility="collapsed",
)

# ------------------------------------------------------------
# Tab styling (FULL, FINAL, WORKING)
# ------------------------------------------------------------
st.markdown(
    """
    <style>
    /* ================= TAB BAR ================= */

    div[role="radiogroup"] {
        display: flex !important;
        gap: 1.25rem !important;
        margin-bottom: 1.5rem;
    }

    div[role="radiogroup"] > label {
        display: inline-flex !important;
        align-items: center !important;
        cursor: pointer !important;
        border-bottom: 2px solid transparent !important;
        padding-bottom: 0.4rem !important;
    }

    /* Hide radio controls */
    div[role="radiogroup"] input,
    div[role="radiogroup"] svg,
    div[role="radiogroup"] > label > div:first-child,
    div[role="radiogroup"] > label > span:first-child {
        display: none !important;
    }

    /* Text */
    div[role="radiogroup"] > label > div,
    div[role="radiogroup"] > label > span {
        font-weight: 500;
        color: rgba(49, 51, 63, 0.75);
    }

    /* Selected (light) */
    div[role="radiogroup"] > label:has(input:checked) {
        border-bottom-color: rgba(255, 0, 0, 0.9);
    }

    div[role="radiogroup"] > label:has(input:checked) > div,
    div[role="radiogroup"] > label:has(input:checked) > span {
        color: rgba(255, 0, 0, 0.9);
        font-weight: 600;
    }

    /* ================= DARK MODE FIX ================= */

    html[data-theme="dark"] div[role="radiogroup"] > label > div,
    html[data-theme="dark"] div[role="radiogroup"] > label > span {
        color: #FFFFFF !important;
        opacity: 1 !important;
        font-weight: 600;
        text-shadow: 0 1px 2px rgba(0,0,0,0.85);
    }

    html[data-theme="dark"] div[role="radiogroup"] > label:has(input:checked) > div,
    html[data-theme="dark"] div[role="radiogroup"] > label:has(input:checked) > span {
        color: rgba(255, 0, 0, 0.95) !important;
        font-weight: 700;
    }

    html[data-theme="dark"] div[role="radiogroup"] > label:has(input:checked) {
        border-bottom-color: rgba(255, 0, 0, 0.95) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------
# PLAYER STATS
# ------------------------------------------------------------
if selected_tab == "Player Stats":
    st.subheader("Player Stats")

    league = data.league_data.copy()
    league.columns = [str(c).strip() for c in league.columns]

    # Team mapping
    teams = data.teams.copy()
    teams.columns = [str(c).strip() for c in teams.columns]

    team_id_col = _find_col(league, ["TeamID"])
    name_col = _find_col(league, ["Name"])

    team_map = dict(
        zip(
            teams["TeamID"].astype(str).str.strip(),
            teams["Team Names"].astype(str).str.strip(),
        )
    )

    league["Team"] = league[team_id_col].astype(str).str.strip().map(team_map)

    # Filters
    team_choice = st.selectbox("Team", ["All"] + sorted(team_map.values()))
    if team_choice != "All":
        league = league[league["Team"] == team_choice]

    players = st.multiselect("Players (optional)", sorted(league[name_col].dropna().unique()))
    if players:
        league = league[league[name_col].isin(players)]

    # Stat selectors
    batting = ["Runs Scored", "Batting Average"]
    bowling = ["Wickets", "Economy"]

    selected_cols = ["Name"] + batting + bowling + ["Fantasy Points"]
    selected_cols = [c for c in selected_cols if c in league.columns]

    league[selected_cols] = league[selected_cols].apply(pd.to_numeric, errors="ignore")
    league = league.sort_values(by="Fantasy Points", ascending=False)

    st.data_editor(
        league[selected_cols],
        hide_index=True,
        disabled=True,
        column_config={
            "Batting Average": st.column_config.NumberColumn(format="%.2f"),
            "Economy": st.column_config.NumberColumn(format="%.2f"),
        },
    )

# ------------------------------------------------------------
# FIXTURES
# ------------------------------------------------------------
elif selected_tab == "Fixtures & Results":
    st.subheader("Fixtures & Results")
    st.dataframe(fixtures, hide_index=True)

# ------------------------------------------------------------
# LEAGUE TABLE
# ------------------------------------------------------------
elif selected_tab == "League Table":
    st.subheader("League Table")

    lt = league_table.copy()

    hide_cols = [
        "Runs Scored",
        "Runs Conceeded",
        "Wickets Taken",
        "Wickets Lost",
        "Overs Faced",
        "Overs Bowled",
    ]
    lt = lt.drop(columns=[c for c in hide_cols if c in lt.columns], errors="ignore")

    lt.insert(0, "Position", range(1, len(lt) + 1))

    if "NRR" in lt.columns:
        lt["NRR"] = pd.to_numeric(lt["NRR"], errors="coerce").round(2)

    html = lt.to_html(index=False)

    st.markdown(
        """
        <style>
        .league-table table {
            width: 100%;
            border-collapse: collapse;
            margin: 0;
        }
        .league-table th, .league-table td {
            padding: 0.6rem;
            text-align: center;
            border-bottom: 1px solid rgba(49,51,63,0.15);
        }
        .league-table tr:nth-child(1) { background: rgba(255,215,0,0.08); }
        .league-table tr:nth-child(2) { background: rgba(192,192,192,0.22); }
        .league-table tr:nth-child(3) { background: rgba(205,127,50,0.12); }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(f"<div class='league-table'>{html}</div>", unsafe_allow_html=True)

# ------------------------------------------------------------
# TEAMS
# ------------------------------------------------------------
elif selected_tab == "Teams":
    st.subheader("Teams")

    teams = data.teams.copy()
    teams.columns = [str(c).strip() for c in teams.columns]

    team_name = st.selectbox("Team", ["All"] + teams["Team Names"].tolist())

    if team_name == "All":
        st.dataframe(teams, hide_index=True)
    else:
        team_row = teams[teams["Team Names"] == team_name].iloc[0]
        st.write(team_row)
