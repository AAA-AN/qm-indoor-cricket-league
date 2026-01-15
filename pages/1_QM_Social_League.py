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


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = list(df.columns)
    for c in candidates:
        if c in cols:
            return c
    return None


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
fixtures.columns = [str(c).strip() for c in fixtures.columns]  # robust header cleanup

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
    label="",
    options=["Player Stats", "Fixtures & Results", "League Table", "Teams"],
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

        /* Unselected (dark mode) – force high contrast and override any parent opacity */
        div[role="radiogroup"] > label:not(:has(input:checked)) {
            opacity: 1 !important;
            filter: none !important;
        }

        div[role="radiogroup"] > label:not(:has(input:checked)) > div,
        div[role="radiogroup"] > label:not(:has(input:checked)) > span {
            opacity: 1 !important;
            color: #FFFFFF !important;
            font-weight: 700 !important;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.85);
        }

        /* Hover */
        div[role="radiogroup"] > label:hover > div,
        div[role="radiogroup"] > label:hover > span {
            color: rgba(255, 255, 255, 3) !important;
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
# TAB 1: PLAYER STATS
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

        team_id_col_teams = _find_col(teams, ["TeamID"])
        team_name_col_teams = _find_col(teams, ["Team Names"])

        if team_id_col_teams and team_name_col_teams:
            ttmp = teams[[team_id_col_teams, team_name_col_teams]].copy()

            ttmp[team_id_col_teams] = ttmp[team_id_col_teams].astype(str).str.strip()
            ttmp[team_name_col_teams] = ttmp[team_name_col_teams].astype(str).str.strip()

            ttmp = ttmp[
                (ttmp[team_id_col_teams] != "") &
                (ttmp[team_name_col_teams] != "")
            ].drop_duplicates()

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

    if selected_team_id is not None and team_id_col_league and team_id_col_league in filtered.columns:
        filtered = filtered[
            filtered[team_id_col_league].astype(str).str.strip() == str(selected_team_id).strip()
        ]

    if name_col and name_col in filtered.columns and selected_players:
        filtered = filtered[filtered[name_col].astype(str).str.strip().isin(selected_players)]

    # -----------------------------
    # Stat selectors + single table
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

    batting_options = [c for c in BATTING_STATS if c in filtered.columns]
    bowling_options = [c for c in BOWLING_STATS if c in filtered.columns]
    fielding_options = [c for c in FIELDING_STATS if c in filtered.columns]

    default_batting = [c for c in ["Runs Scored", "Batting Average"] if c in batting_options]
    default_bowling = [c for c in ["Wickets", "Economy"] if c in bowling_options]
    default_fielding: list[str] = []

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

    selected_columns = selected_batting + selected_bowling + selected_fielding

    display_cols = ["Name"]
    for c in selected_columns:
        if c not in display_cols:
            display_cols.append(c)

    if "Fantasy Points" in filtered.columns and "Fantasy Points" not in display_cols:
        display_cols.append("Fantasy Points")

    view = filtered[display_cols] if all(c in filtered.columns for c in display_cols) else filtered

    if "Fantasy Points" in view.columns:
        try:
            view = view.sort_values(by="Fantasy Points", ascending=False)
        except Exception:
            pass

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
# TAB 3: LEAGUE TABLE
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

        # Hide requested columns (if present)
        cols_to_hide = [
            "Runs Scored",
            "Runs Conceeded",
            "Wickets Taken",
            "Wickets Lost",
            "Overs Faced",
            "Overs Bowled",
        ]
        lt = lt.drop(columns=[c for c in cols_to_hide if c in lt.columns], errors="ignore")

        # Add Position as the first column (fixed to current displayed order)
        lt.insert(0, "Position", range(1, len(lt) + 1))

        # Format NRR to 2dp (render as text to lock formatting)
        if "NRR" in lt.columns:
            nrr = pd.to_numeric(lt["NRR"], errors="coerce")
            lt["NRR"] = nrr.map(lambda x: f"{x:.2f}" if pd.notna(x) else "")

        # Build HTML table (non-interactive; prevents user sorting)
        html_table = lt.to_html(index=False, escape=True)

        st.markdown(
            """
            <style>
              /* Container styled to resemble Streamlit's dataframe */
                .lt-wrap {
                width: 100%;
                border: 1px solid rgba(49, 51, 63, 0.15);
                border-radius: 0.5rem;
                overflow: hidden;
                background: white;
                padding-bottom: 0;   /* remove extra space under last row */
              }

              /* Horizontal scroll like st.dataframe when needed */
                .lt-scroll {
                width: 100%;
                overflow-x: auto;
                overflow-y: hidden;
              }

              /* Table base */
                .lt-wrap table {
                width: 100%;
                border-collapse: separate;
                border-spacing: 0;
                font-size: 0.95rem;
                border-top: none !important;
                border-bottom: none !important;
                margin: 0 !important;           /* remove extra white space below table */
                padding: 0 !important;
              }

              /* Header */
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

                /* Cells */
                .lt-wrap tbody td {
                padding: 0.6rem 0.75rem;
                border-bottom: 1px solid rgba(49, 51, 63, 0.08);
                color: rgba(49, 51, 63, 0.95);
                white-space: nowrap;
              }

              /* Centre-align numeric columns (all except Team) */
                .lt-wrap tbody td:not(:nth-child(2)),
                .lt-wrap thead th:not(:nth-child(2)) {
                text-align: center;
              }

              /* Medal colouring for top 3 positions */
                .lt-wrap tbody tr:nth-child(1) td {
                background: rgba(255, 215, 0, 0.08); /* gold */
              }

                .lt-wrap tbody tr:nth-child(2) td {
                background: rgba(192, 192, 192, 0.22); /* clearer silver */
              }

              .lt-wrap tbody tr:nth-child(3) td {
                background: rgba(205, 127, 50, 0.10); /* bronze */
              }

              /* Remove bottom border from final row */
                .lt-wrap tbody tr:last-child td {
                border-bottom: 1px solid transparent;
              }

                /* Medal colouring for top 3 positions only */
                .lt-wrap tbody tr:nth-child(1) td {
                background: rgba(255, 215, 0, 0.08); /* gold */
              }

                .lt-wrap tbody tr:nth-child(2) td {
                background: rgba(192, 192, 192, 0.22); /* clearer silver */
              }

                .lt-wrap tbody tr:nth-child(3) td {
                background: rgba(205, 127, 50, 0.10); /* bronze */
              }

              /* Hover similar to Streamlit row hover (no persistent colour for rows 4+) */
                .lt-wrap tbody tr:hover td {
                background: rgba(240, 242, 246, 1);
              }
              
              /* Remove pandas default borders */
                .lt-wrap table, .lt-wrap th, .lt-wrap td {
                border-left: none !important;
                border-right: none !important;
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
# TAB 4: TEAMS
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

    # Expected Teams_Table headers:
    # TeamID | Team Names | Active | Captain's Name | Captain's PlayerID | Player 1..8
    team_id_col = _find_col(teams, ["TeamID", "Team Id", "Team ID"])
    team_name_col = _find_col(teams, ["Team Names", "Team Name"])
    active_col = _find_col(teams, ["Active"])
    captain_name_col = _find_col(teams, ["Captain's Name", "Captains Name", "Captain Name"])

    if not team_name_col:
        st.error("Teams_Table is missing 'Team Names'.")
        st.stop()

    # Clean key columns
    teams[team_name_col] = teams[team_name_col].astype(str).str.strip()

    if team_id_col and team_id_col in teams.columns:
        teams[team_id_col] = teams[team_id_col].astype(str).str.strip()

    if active_col and active_col in teams.columns:
        teams[active_col] = teams[active_col].astype(str).str.strip()

    if captain_name_col and captain_name_col in teams.columns:
        teams[captain_name_col] = teams[captain_name_col].astype(str).str.strip()

    # Team dropdown options (no TeamID displayed)
    team_names = sorted([t for t in teams[team_name_col].dropna().unique().tolist() if str(t).strip() != ""], key=str.lower)
    team_choice = st.selectbox("Team", ["All Teams"] + team_names, key="ts_team_name")

    # ---------- All Teams overview ----------
    if team_choice == "All Teams":
        # Build base from league_table if available; otherwise show Teams_Table basics
        overview = None

        if league_table is not None and not league_table.empty:
            lt = league_table.copy()
            lt.columns = [str(c).strip() for c in lt.columns]

            # Ensure NRR displays to 2dp in overview too (keep numeric for sorting)
            if "NRR" in lt.columns:
                lt["NRR"] = pd.to_numeric(lt["NRR"], errors="coerce").round(2)

            # Attempt to join captain/active by Team name
            if "Team" in lt.columns:
                join_cols = [team_name_col]
                add_cols = []
                if active_col:
                    add_cols.append(active_col)
                if captain_name_col:
                    add_cols.append(captain_name_col)

                if add_cols:
                    tmini = teams[[team_name_col] + add_cols].drop_duplicates()
                    overview = lt.merge(tmini, left_on="Team", right_on=team_name_col, how="left")
                    overview = overview.drop(columns=[team_name_col], errors="ignore")
                else:
                    overview = lt
            else:
                overview = lt

            # Hide any raw stat columns you previously hid in League Table display
            cols_to_hide = [
                "Runs Scored",
                "Runs Conceeded",
                "Wickets Taken",
                "Wickets Lost",
                "Overs Faced",
                "Overs Bowled",
            ]
            overview = overview.drop(columns=[c for c in cols_to_hide if c in overview.columns], errors="ignore")

            # If Position not present, add it based on current order
            if "Position" not in overview.columns:
                overview.insert(0, "Position", range(1, len(overview) + 1))

        if overview is None:
            # Fallback: simple overview from Teams_Table
            cols = [team_name_col]
            if active_col:
                cols.append(active_col)
            if captain_name_col:
                cols.append(captain_name_col)
            overview = teams[cols].copy()
            overview.insert(0, "Position", range(1, len(overview) + 1))

        st.data_editor(
            overview,
            width="stretch",
            hide_index=True,
            disabled=True,
        )

        st.markdown("---")
        st.caption("Select a team above to view roster and team totals.")
        st.stop()

    # ---------- Single Team view ----------
    team_row = teams.loc[teams[team_name_col] == team_choice]
    if team_row.empty:
        st.info("Selected team not found in Teams_Table.")
        st.stop()

    team_row = team_row.iloc[0]

    # Basic team metadata
    meta_c1, meta_c2, meta_c3 = st.columns([2, 1, 2])
    with meta_c1:
        st.markdown(f"**Team:** {team_choice}")

    with meta_c2:
        if active_col and active_col in teams.columns:
            st.markdown(f"**Active:** {team_row.get(active_col, '')}")
        else:
            st.markdown("**Active:** —")

    with meta_c3:
        if captain_name_col and captain_name_col in teams.columns:
            st.markdown(f"**Captain:** {team_row.get(captain_name_col, '')}")
        else:
            st.markdown("**Captain:** —")

    # Show league position/points if available
    if league_table is not None and not league_table.empty and "Team" in league_table.columns:
        lt_lookup = league_table.copy()
        lt_lookup.columns = [str(c).strip() for c in lt_lookup.columns]

        lt_team = lt_lookup[lt_lookup["Team"].astype(str).str.strip() == str(team_choice).strip()]
        if not lt_team.empty:
            r = lt_team.iloc[0].to_dict()
            # Common cols
            played = r.get("Played", "—")
            points = r.get("Points", "—")
            nrr_val = r.get("NRR", "—")
            try:
                nrr_val = f"{float(nrr_val):.2f}"
            except Exception:
                pass

            st.markdown(f"**Played:** {played} &nbsp;&nbsp; **Points:** {points} &nbsp;&nbsp; **NRR:** {nrr_val}")

    st.markdown("---")

    # Build roster from Player 1..8 columns + captain (if not already present)
    roster_cols = [c for c in teams.columns if str(c).strip().lower().startswith("player ")]
    roster = []
    for c in roster_cols:
        v = team_row.get(c, None)
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() != "nan":
            roster.append(s)

    cap_name = ""
    if captain_name_col and captain_name_col in teams.columns:
        cap_name = str(team_row.get(captain_name_col, "")).strip()

    if cap_name and cap_name.lower() != "nan" and cap_name not in roster:
        roster.insert(0, cap_name)

    roster = [p for i, p in enumerate(roster) if p and p not in roster[:i]]  # de-dupe, preserve order

    # Display roster
    roster_df = pd.DataFrame({"Player": roster}) if roster else pd.DataFrame({"Player": []})
    st.markdown("#### Roster")
    st.data_editor(
        roster_df,
        width="stretch",
        hide_index=True,
        disabled=True,
    )

    # If no league data, stop after roster
    if league_df is None or league_df.empty:
        st.info("No League_Data_Stats found yet, so team totals cannot be calculated.")
        st.stop()

    league = league_df.copy()
    league.columns = [str(c).strip() for c in league.columns]

    name_col = _find_col(league, ["Name"])
    team_id_col_league = _find_col(league, ["TeamID", "Team Id", "Team ID"])

    # Filter league stats to this team by TeamID when possible, otherwise by roster names
    filtered_team = league.copy()

    if team_id_col and team_id_col_league and team_id_col in teams.columns and team_id_col_league in league.columns:
        selected_team_id = str(team_row.get(team_id_col, "")).strip()
        filtered_team[team_id_col_league] = filtered_team[team_id_col_league].astype(str).str.strip()
        if selected_team_id:
            filtered_team = filtered_team[filtered_team[team_id_col_league] == selected_team_id]

    # If TeamID filter yields nothing, fall back to roster name match (if possible)
    if filtered_team.empty and name_col and roster:
        filtered_team[name_col] = filtered_team[name_col].astype(str).str.strip()
        filtered_team = filtered_team[filtered_team[name_col].isin(roster)]

    if filtered_team.empty:
        st.info("No matching player stats found for this team yet.")
        st.stop()

    # Coerce numeric where appropriate (safe if columns missing)
    numeric_cols = [
        "Runs Scored",
        "Balls Faced",
        "6s",
        "Retirements",
        "Innings Played",
        "Not Out's",
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
    for c in numeric_cols:
        if c in filtered_team.columns:
            filtered_team[c] = pd.to_numeric(filtered_team[c], errors="coerce")

    st.markdown("#### Player Stats (Team)")
    # Show similar to Player Stats but scoped to team, with simple defaults
    default_cols = [c for c in ["Name", "Runs Scored", "Batting Average", "Wickets", "Economy", "Fantasy Points"] if c in filtered_team.columns]
    if not default_cols:
        default_cols = [name_col] if name_col else list(filtered_team.columns)

    team_players_view = filtered_team[default_cols].copy() if all(c in filtered_team.columns for c in default_cols) else filtered_team.copy()

    if "Fantasy Points" in team_players_view.columns:
        try:
            team_players_view = team_players_view.sort_values(by="Fantasy Points", ascending=False)
        except Exception:
            pass

    # 2dp formatting for key rate stats if present
    col_config = {}
    if "Name" in team_players_view.columns:
        col_config["Name"] = st.column_config.TextColumn(pinned=True)
    for c in ["Batting Strike Rate", "Batting Average", "Economy", "Bowling Strike Rate", "Bowling Average"]:
        if c in team_players_view.columns:
            col_config[c] = st.column_config.NumberColumn(format="%.2f")

    st.data_editor(
        team_players_view,
        width="stretch",
        hide_index=True,
        disabled=True,
        column_config=col_config,
    )

    # ---------- Team totals ----------
    st.markdown("#### Team Totals")

    totals = {}

    # Straight sums
    for c in [
        "Runs Scored",
        "Balls Faced",
        "6s",
        "Retirements",
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
    ]:
        if c in filtered_team.columns:
            totals[c] = float(pd.to_numeric(filtered_team[c], errors="coerce").fillna(0).sum())

    # Derived team batting SR = (runs/balls)*100
    if "Runs Scored" in totals and "Balls Faced" in totals and totals["Balls Faced"] > 0:
        totals["Team Batting Strike Rate"] = (totals["Runs Scored"] / totals["Balls Faced"]) * 100

    # Derived team economy = runs conceded / overs (overs may be decimal; if 0 skip)
    if "Runs Conceded" in totals and "Overs" in totals and totals["Overs"] > 0:
        totals["Team Economy"] = totals["Runs Conceded"] / totals["Overs"]

    # Present totals in a tidy two-column layout
    totals_df = (
        pd.DataFrame([totals])
        if totals
        else pd.DataFrame([{"Info": "No numeric totals available"}])
    )

    # Order a few key totals first if present
    preferred = [
        "Runs Scored",
        "Balls Faced",
        "Team Batting Strike Rate",
        "Wickets",
        "Runs Conceded",
        "Overs",
        "Team Economy",
        "Catches",
        "Run Outs",
        "Stumpings",
        "Fantasy Points",
    ]
    ordered_cols = [c for c in preferred if c in totals_df.columns] + [c for c in totals_df.columns if c not in preferred]
    totals_df = totals_df[ordered_cols]

    totals_col_config = {}
    for c in totals_df.columns:
        if c in ["Team Batting Strike Rate", "Team Economy"]:
            totals_col_config[c] = st.column_config.NumberColumn(format="%.2f")
        elif c != "Info":
            totals_col_config[c] = st.column_config.NumberColumn()

    st.data_editor(
        totals_df,
        width="stretch",
        hide_index=True,
        disabled=True,
        column_config=totals_col_config,
    )

