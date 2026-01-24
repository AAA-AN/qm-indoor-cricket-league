import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

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
from src.db import (
    rebuild_blocks_from_fixtures_if_missing,
    get_current_block_number,
    get_effective_block_state,
    get_block_fixtures,
    list_blocks_with_fixtures,
    get_block_prices,
    ensure_block_prices_default,
    save_fantasy_entry,
    get_fantasy_entry,
    get_latest_scored_block_number,
    get_user_block_points,
    get_block_player_points,
    list_block_user_points,
    get_season_user_totals,
    get_user_block_points_history,
    list_scored_blocks,
)

st.set_page_config(page_title=f"{APP_TITLE} - QM Fantasy Social League", layout="wide")

require_login()
hide_home_page_when_logged_in()
hide_admin_page_for_non_admins()
render_sidebar_header()
render_logout_button()

st.title("QM Fantasy Social League")


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
    cols = list(df.columns)
    for c in candidates:
        if c in cols:
            return c
    return None


def _format_dt_dd_mmm_hhmm(dt_val: str | None) -> str | None:
    if dt_val is None:
        return None
    s = str(dt_val).strip()
    if not s:
        return s
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt.strftime("%d-%b %H:%M")
    except Exception:
        return str(dt_val)


def _is_active_value(v) -> bool:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    s = str(v).strip().lower()
    if s in ("0", "false", "no", "n", "inactive", ""):
        return False
    return True


try:
    app_key = _get_secret("DROPBOX_APP_KEY")
    app_secret = _get_secret("DROPBOX_APP_SECRET")
    refresh_token = _get_secret("DROPBOX_REFRESH_TOKEN")
    dropbox_path = _get_secret("DROPBOX_FILE_PATH")
except Exception as e:
    st.error(str(e))
    st.stop()

with st.spinner("Loading latest league workbook from Dropbox..."):
    try:
        data = _load_from_dropbox(app_key, app_secret, refresh_token, dropbox_path)
    except Exception as e:
        st.error(f"Failed to load workbook from Dropbox: {e}")
        st.stop()

fixtures_df = data.fixture_results.copy()
fixtures_df.columns = [str(c).strip() for c in fixtures_df.columns]

rebuild_blocks_from_fixtures_if_missing(fixtures_df)

current_block = get_current_block_number()
if current_block is None:
    st.info("No active fantasy blocks available yet.")
    st.stop()

now_london = datetime.now(ZoneInfo("Europe/London"))
state = get_effective_block_state(current_block, now_london)

blocks = list_blocks_with_fixtures()
current_block_row = next(
    (b for b in blocks if int(b.get("block_number") or 0) == int(current_block)),
    None,
)
lock_at = current_block_row.get("lock_at") if current_block_row else None

st.subheader(f"Current Block: {current_block}")

block_fixtures = get_block_fixtures(current_block)
if block_fixtures:
    st.markdown("**Fixtures in this block:**")
    for fx in block_fixtures:
        match_id = fx.get("match_id", "")
        start_at = _format_dt_dd_mmm_hhmm(fx.get("start_at"))
        st.write(f"- {match_id} — {start_at}")
else:
    st.info("No fixtures found for this block.")

lock_at_fmt = _format_dt_dd_mmm_hhmm(lock_at)
st.write(f"**Lock time:** {lock_at_fmt}")
st.write(f"**Selections:** {state}")

is_locked = state == "LOCKED"
is_scored = state == "SCORED"

if is_locked:
    st.info("Selections are locked.")

league_df = data.league_data
if league_df is None or league_df.empty:
    st.info("No player data found (League_Data_Stats table not loaded).")
    st.stop()

league = league_df.copy()
league.columns = [str(c).strip() for c in league.columns]

player_id_col = _find_col(league, ["PlayerID", "Player Id", "Player ID"])
name_col = _find_col(league, ["Name"])
team_id_col_league = _find_col(league, ["TeamID", "Team Id", "Team ID"])
active_col = _find_col(league, ["Active"])

if not player_id_col or not name_col:
    st.error("League_Data_Stats must include PlayerID and Name columns.")
    st.stop()

teams_df = getattr(data, "teams_table", None)
if teams_df is None:
    teams_df = getattr(data, "teams", None)
if teams_df is None:
    teams_df = getattr(data, "teams_data", None)

team_id_to_name: dict[str, str] = {}
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

league[player_id_col] = league[player_id_col].astype(str).str.strip()
league[name_col] = league[name_col].astype(str).str.strip()

league = league[league[player_id_col] != ""].copy()

if active_col and active_col in league.columns:
    league = league[league[active_col].apply(_is_active_value)].copy()

if team_id_col_league and team_id_col_league in league.columns and team_id_to_name:
    league[team_id_col_league] = league[team_id_col_league].astype(str).str.strip()
    league["Team"] = league[team_id_col_league].map(team_id_to_name)
else:
    league["Team"] = None

player_ids = league[player_id_col].astype(str).str.strip().tolist()

prices = get_block_prices(current_block)
if not prices:
    ensure_block_prices_default(current_block, player_ids, default_price=7.5)
    prices = get_block_prices(current_block)

player_rows = []
player_label_by_id: dict[str, str] = {}
player_team_by_id: dict[str, str] = {}
player_name_by_id: dict[str, str] = {}
player_price_by_id: dict[str, float] = {}

for _, r in league.iterrows():
    pid = str(r.get(player_id_col, "")).strip()
    if not pid:
        continue
    name = str(r.get(name_col, "")).strip()
    team = str(r.get("Team", "")).strip() or "Unknown"
    price = float(prices.get(pid, 7.5))
    label = f"{price:.1f} – {name} – {team}"
    player_label_by_id[pid] = label
    player_team_by_id[pid] = team
    player_name_by_id[pid] = name
    player_price_by_id[pid] = price
    player_rows.append({"player_id": pid, "label": label})

player_rows = sorted(player_rows, key=lambda x: x["label"])
player_labels = [r["label"] for r in player_rows]
player_id_by_label = {r["label"]: r["player_id"] for r in player_rows}

user = st.session_state.get("user") or {}
user_id = user.get("user_id")
if not user_id:
    st.error("User ID not found in session.")
    st.stop()

entry = get_fantasy_entry(current_block, int(user_id))
default_squad_ids = entry.get("squad_player_ids", []) if entry else []
default_starting_ids = entry.get("starting_player_ids", []) if entry else []
default_bench1 = entry.get("bench1") if entry else None
default_bench2 = entry.get("bench2") if entry else None
default_captain = entry.get("captain_id") if entry else None
default_vice = entry.get("vice_captain_id") if entry else None

default_squad_labels = [player_label_by_id.get(pid) for pid in default_squad_ids if pid in player_label_by_id]
default_starting_labels = [player_label_by_id.get(pid) for pid in default_starting_ids if pid in player_label_by_id]

controls_disabled = is_locked or is_scored
editing_key = f"fantasy_editing_block_{current_block}"
if controls_disabled:
    st.session_state[editing_key] = False
else:
    if entry is None:
        st.session_state[editing_key] = True
    elif editing_key not in st.session_state:
        st.session_state[editing_key] = False
editing = bool(st.session_state.get(editing_key))

st.markdown("---")
tab_team, tab_results, tab_leaderboard = st.tabs(["Team selector", "Results", "Leaderboard"])
with tab_team:
    st.subheader("Team selector")

    def _player_label(pid: str) -> str:
        return player_label_by_id.get(pid, pid)

    if not editing:
        if entry:
            st.markdown(f"### Selected Team (Block: {state})")
            squad_ids = entry.get("squad_player_ids", [])
            starting_ids = entry.get("starting_player_ids", [])
            bench1_id = entry.get("bench1")
            bench2_id = entry.get("bench2")
            captain_id = entry.get("captain_id")
            vice_id = entry.get("vice_captain_id")

            rows = []
            for pid in starting_ids:
                rows.append(
                    {
                        "Role": "Starting",
                        "Multiplier": "Captain (x2)" if pid == captain_id else "Vice (x1.5)" if pid == vice_id else "",
                        "Player": _player_label(pid),
                    }
                )
            if bench1_id:
                rows.append(
                    {
                        "Role": "Bench 1",
                        "Multiplier": "Captain (x2)" if bench1_id == captain_id else "Vice (x1.5)" if bench1_id == vice_id else "",
                        "Player": _player_label(bench1_id),
                    }
                )
            if bench2_id:
                rows.append(
                    {
                        "Role": "Bench 2",
                        "Multiplier": "Captain (x2)" if bench2_id == captain_id else "Vice (x1.5)" if bench2_id == vice_id else "",
                        "Player": _player_label(bench2_id),
                    }
                )

            df_selected = pd.DataFrame(rows, columns=["Role", "Player", "Multiplier"])
            st.dataframe(df_selected, use_container_width=True, hide_index=True)

            budget_used = sum(player_price_by_id.get(pid, 0.0) for pid in squad_ids)
            budget_remaining = 60.0 - budget_used
            st.markdown(f"**Budget used:** {budget_used:.1f} / 60.0")
            st.markdown(f"**Budget remaining:** {budget_remaining:.1f}")

            if not controls_disabled:
                if st.button("Edit team", use_container_width=True):
                    st.session_state[editing_key] = True
                    st.rerun()
        else:
            st.info(
                "Selections are locked and you have not submitted a team for this block."
                if controls_disabled
                else "No team submitted yet."
            )
    else:
        budget_placeholder = st.empty()

        squad_labels = st.multiselect(
            "Squad (pick 8)",
            options=player_labels,
            default=default_squad_labels,
            max_selections=8,
            key=f"fantasy_squad_{current_block}",
            disabled=controls_disabled,
        )

        squad_ids = [player_id_by_label.get(lbl) for lbl in squad_labels if lbl in player_id_by_label]
        squad_ids = [pid for pid in squad_ids if pid]

        starting_labels = st.multiselect(
            "Starting XI (pick 6)",
            options=squad_labels,
            default=[lbl for lbl in default_starting_labels if lbl in squad_labels],
            max_selections=6,
            key=f"fantasy_starting_{current_block}",
            disabled=controls_disabled,
        )

        starting_ids = [player_id_by_label.get(lbl) for lbl in starting_labels if lbl in player_id_by_label]
        starting_ids = [pid for pid in starting_ids if pid]

        remaining_labels = [lbl for lbl in squad_labels if lbl not in starting_labels]
        bench_options = remaining_labels if remaining_labels else ["(select)"]

        bench1_label = st.selectbox(
            "Bench 1",
            options=bench_options,
            index=bench_options.index(player_label_by_id.get(default_bench1)) if default_bench1 in player_label_by_id and player_label_by_id.get(default_bench1) in bench_options else 0,
            key=f"fantasy_bench1_{current_block}",
            disabled=controls_disabled,
        )

        bench2_label = st.selectbox(
            "Bench 2",
            options=bench_options,
            index=bench_options.index(player_label_by_id.get(default_bench2)) if default_bench2 in player_label_by_id and player_label_by_id.get(default_bench2) in bench_options else 0,
            key=f"fantasy_bench2_{current_block}",
            disabled=controls_disabled,
        )

        bench1_id = player_id_by_label.get(bench1_label) if bench1_label in player_id_by_label else ""
        bench2_id = player_id_by_label.get(bench2_label) if bench2_label in player_id_by_label else ""

        captain_options = starting_labels if starting_labels else ["(select)"]
        captain_label = st.selectbox(
            "Captain (x2)",
            options=captain_options,
            index=captain_options.index(player_label_by_id.get(default_captain)) if default_captain in player_label_by_id and player_label_by_id.get(default_captain) in captain_options else 0,
            key=f"fantasy_captain_{current_block}",
            disabled=controls_disabled,
        )

        vice_options = [lbl for lbl in captain_options if lbl != captain_label] or ["(select)"]
        vice_label = st.selectbox(
            "Vice-captain (x1.5)",
            options=vice_options,
            index=vice_options.index(player_label_by_id.get(default_vice)) if default_vice in player_label_by_id and player_label_by_id.get(default_vice) in vice_options else 0,
            key=f"fantasy_vice_{current_block}",
            disabled=controls_disabled,
        )

        captain_id = player_id_by_label.get(captain_label) if captain_label in player_id_by_label else ""
        vice_id = player_id_by_label.get(vice_label) if vice_label in player_id_by_label else ""

        budget_used = sum(player_price_by_id.get(pid, 0.0) for pid in squad_ids)
        budget_remaining = 60.0 - budget_used

        budget_placeholder.markdown(f"**Budget used:** {budget_used:.1f} / 60.0")
        budget_placeholder.markdown(f"**Budget remaining:** {budget_remaining:.1f}")

        errors = []
        if len(squad_ids) != 8:
            errors.append("Squad must include exactly 8 players.")

        if len(starting_ids) != 6 or not set(starting_ids).issubset(set(squad_ids)):
            errors.append("Starting lineup must include exactly 6 players from the squad.")

        remaining_ids = [pid for pid in squad_ids if pid not in starting_ids]
        if len(remaining_ids) == 2:
            if set([bench1_id, bench2_id]) != set(remaining_ids) or bench1_id == bench2_id:
                errors.append("Bench 1 and Bench 2 must be the two remaining squad players.")
        else:
            errors.append("Bench selections require exactly 2 remaining squad players.")

        if not captain_id or captain_id not in starting_ids:
            errors.append("Captain must be selected from the starting lineup.")
        if not vice_id or vice_id not in starting_ids:
            errors.append("Vice-captain must be selected from the starting lineup.")
        if captain_id and vice_id and captain_id == vice_id:
            errors.append("Captain and Vice-captain must be different players.")

        if budget_used > 60.0:
            errors.append("Total budget exceeds 60.0.")

        team_counts: dict[str, int] = {}
        for pid in squad_ids:
            team = player_team_by_id.get(pid, "Unknown") or "Unknown"
            team_counts[team] = team_counts.get(team, 0) + 1
        if any(n > 4 for n in team_counts.values()):
            errors.append("No more than 4 players can be selected from the same team.")

        if errors:
            for msg in errors:
                st.warning(msg)

        if not controls_disabled:
            if st.button("Submit Team", use_container_width=True):
                if errors:
                    st.error("Please fix the issues above before submitting.")
                else:
                    submitted_at_iso = now_london.isoformat()
                    save_fantasy_entry(
                        block_number=current_block,
                        user_id=int(user_id),
                        squad_player_ids=squad_ids,
                        starting_player_ids=starting_ids,
                        bench1=bench1_id,
                        bench2=bench2_id,
                        captain_id=captain_id,
                        vice_captain_id=vice_id,
                        budget_used=budget_used,
                        submitted_at_iso=submitted_at_iso,
                    )
                    st.session_state[editing_key] = False
                    st.success("Fantasy team submitted.")
                    st.rerun()

with tab_results:
    st.markdown("---")
    st.subheader("Results")

    latest_block = get_latest_scored_block_number()
    if latest_block is None:
        st.info("No results yet.")
    else:
        st.markdown(f"### Latest Results (Block {latest_block})")
        user_points = get_user_block_points(latest_block, int(user_id))
        if user_points is None:
            st.info("You did not submit a team for this block.")
        else:
            st.markdown(f"**Your total:** {user_points:.1f}")

            entry_latest = get_fantasy_entry(latest_block, int(user_id))
            if not entry_latest:
                st.info("You did not submit a team for this block.")
            else:
                points_by_player = get_block_player_points(latest_block)
                prices_latest = get_block_prices(latest_block)

                def _label_for_block(pid: str) -> str:
                    price = float(prices_latest.get(pid, 7.5))
                    name = player_name_by_id.get(pid, pid)
                    team = player_team_by_id.get(pid, "Unknown") or "Unknown"
                    return f"{price:.1f} – {name} – {team}"

                starting_ids = entry_latest.get("starting_player_ids", [])
                bench1_id = entry_latest.get("bench1")
                bench2_id = entry_latest.get("bench2")
                captain_id = entry_latest.get("captain_id")
                vice_id = entry_latest.get("vice_captain_id")
                squad_ids_latest = entry_latest.get("squad_player_ids", [])

                bench_queue = []
                for bid in [bench1_id, bench2_id]:
                    if bid and bid in points_by_player:
                        bench_queue.append(bid)

                final_on_field = []
                subbed_in = set()
                auto_subs_applied = False

                for sid in starting_ids:
                    if sid in points_by_player:
                        final_on_field.append(sid)
                    else:
                        if bench_queue:
                            sub = bench_queue.pop(0)
                            final_on_field.append(sub)
                            subbed_in.add(sub)
                            auto_subs_applied = True
                        else:
                            final_on_field.append(None)

                rows = []
                for sid in starting_ids:
                    rows.append(
                        {
                            "Role": "Starting",
                            "Multiplier": "C" if sid == captain_id else "VC" if sid == vice_id else "",
                            "Player": _label_for_block(sid),
                            "Points": float(points_by_player.get(sid, 0.0)),
                        }
                    )

                if bench1_id:
                    rows.append(
                        {
                            "Role": "Subbed In" if bench1_id in subbed_in else "Bench",
                            "Multiplier": "C" if bench1_id == captain_id else "VC" if bench1_id == vice_id else "",
                            "Player": _label_for_block(bench1_id),
                            "Points": float(points_by_player.get(bench1_id, 0.0)),
                        }
                    )
                if bench2_id:
                    rows.append(
                        {
                            "Role": "Subbed In" if bench2_id in subbed_in else "Bench",
                            "Multiplier": "C" if bench2_id == captain_id else "VC" if bench2_id == vice_id else "",
                            "Player": _label_for_block(bench2_id),
                            "Points": float(points_by_player.get(bench2_id, 0.0)),
                        }
                    )

                df_results = pd.DataFrame(rows, columns=["Role", "Multiplier", "Player", "Points"])
                st.dataframe(df_results, use_container_width=True, hide_index=True)

                budget_used_latest = sum(float(prices_latest.get(pid, 7.5)) for pid in squad_ids_latest)
                budget_remaining_latest = 60.0 - budget_used_latest
                st.markdown(f"**Budget used:** {budget_used_latest:.1f} / 60.0")
                st.markdown(f"**Budget remaining:** {budget_remaining_latest:.1f}")

                if auto_subs_applied:
                    st.caption("Auto-subs were applied based on DNP starters.")

    st.markdown("---")
    st.subheader("My Past Teams")

    scored_blocks = list_scored_blocks()
    scored_blocks = sorted(scored_blocks, reverse=True)

    if not scored_blocks:
        st.info("No past teams yet.")
    else:
        selected_past_block = st.selectbox(
            "Select block",
            options=scored_blocks,
            index=0,
            key="fantasy_past_team_block_select",
        )

        past_entry = get_fantasy_entry(int(selected_past_block), int(user_id))
        if not past_entry:
            st.info("No team submitted for this block.")
        else:
            past_prices = get_block_prices(int(selected_past_block))
            past_points = get_block_player_points(int(selected_past_block))

            def _past_label(pid: str) -> str:
                price = float(past_prices.get(pid, 7.5))
                name = player_name_by_id.get(pid, pid)
                team = player_team_by_id.get(pid, "Unknown") or "Unknown"
                return f"{price:.1f} – {name} – {team}"

            starting_ids = past_entry.get("starting_player_ids", [])
            bench1_id = past_entry.get("bench1")
            bench2_id = past_entry.get("bench2")
            captain_id = past_entry.get("captain_id")
            vice_id = past_entry.get("vice_captain_id")

            rows = []
            for pid in starting_ids:
                row = {
                    "Role": "Starting",
                    "Player": _past_label(pid),
                    "Multiplier": "Captain" if pid == captain_id else "Vice" if pid == vice_id else "",
                }
                if past_points:
                    row["Points"] = float(past_points.get(pid, 0.0))
                rows.append(row)

            if bench1_id:
                row = {
                    "Role": "Bench 1",
                    "Player": _past_label(bench1_id),
                    "Multiplier": "Captain" if bench1_id == captain_id else "Vice" if bench1_id == vice_id else "",
                }
                if past_points:
                    row["Points"] = float(past_points.get(bench1_id, 0.0))
                rows.append(row)
            if bench2_id:
                row = {
                    "Role": "Bench 2",
                    "Player": _past_label(bench2_id),
                    "Multiplier": "Captain" if bench2_id == captain_id else "Vice" if bench2_id == vice_id else "",
                }
                if past_points:
                    row["Points"] = float(past_points.get(bench2_id, 0.0))
                rows.append(row)

            cols = ["Role", "Player", "Multiplier"]
            if past_points:
                cols.append("Points")
            st.dataframe(
                pd.DataFrame(rows, columns=cols),
                use_container_width=True,
                hide_index=True,
            )

with tab_leaderboard:
    st.markdown("---")
    st.subheader("Leaderboard")

    latest_block_for_lb = get_latest_scored_block_number()
    if latest_block_for_lb is None:
        st.info("No results yet.")
    else:
        scored_blocks = []
        all_blocks = list_blocks_with_fixtures()
        for b in all_blocks:
            if b.get("scored_at"):
                scored_blocks.append(int(b.get("block_number")))
        scored_blocks = sorted(set(scored_blocks), reverse=True)

        if not scored_blocks:
            st.info("No results yet.")
        else:
            default_index = 0
            if latest_block_for_lb in scored_blocks:
                default_index = scored_blocks.index(latest_block_for_lb)

            selected_block = st.selectbox(
                "Select block",
                options=scored_blocks,
                index=default_index,
                key="fantasy_leaderboard_block_select",
            )

            rows = list_block_user_points(int(selected_block))
            if not rows:
                st.info("No user points recorded for this block yet.")
            else:
                display_rows = []
                rank = 1
                for r in rows:
                    first_name = str(r.get("first_name") or "").strip()
                    last_name = str(r.get("last_name") or "").strip()
                    username = str(r.get("username") or "").strip()
                    if first_name or last_name:
                        name = f"{first_name} {last_name}".strip()
                    else:
                        name = username
                    display_rows.append(
                        {
                            "Rank": rank,
                            "Name": name,
                            "Points": float(r.get("points_total") or 0.0),
                        }
                    )
                    rank += 1

            st.dataframe(
                pd.DataFrame(display_rows),
                use_container_width=True,
                hide_index=True,
            )

    st.markdown("---")
    st.subheader("Season")

    season_rows = get_season_user_totals()
    if not season_rows:
        st.info("No season totals yet.")
    else:
        season_display = []
        rank = 1
        for r in season_rows:
            first_name = str(r.get("first_name") or "").strip()
            last_name = str(r.get("last_name") or "").strip()
            username = str(r.get("username") or "").strip()
            if first_name or last_name:
                name = f"{first_name} {last_name}".strip()
            else:
                name = username
            season_display.append(
                {
                    "Rank": rank,
                    "Name": name,
                    "Total Points": float(r.get("total_points") or 0.0),
                }
            )
            rank += 1

        st.markdown("### Season Leaderboard")
        st.dataframe(
            pd.DataFrame(season_display),
            use_container_width=True,
            hide_index=True,
        )

        user_rank = None
        user_total = 0.0
        for idx, r in enumerate(season_rows, start=1):
            if int(r.get("user_id") or 0) == int(user_id):
                user_rank = idx
                user_total = float(r.get("total_points") or 0.0)
                break

        history = get_user_block_points_history(int(user_id))
        blocks_played = len(history)
        total_users = len(season_rows)

        st.markdown("### My Season Summary")
        st.markdown(f"**Your total:** {user_total:.1f}")
        if user_rank is not None:
            st.markdown(f"**Your rank:** {user_rank} of {total_users}")
        else:
            st.markdown(f"**Your rank:** - of {total_users}")
        st.markdown(f"**Blocks played:** {blocks_played}")

        if history:
            hist_rows = [
                {"Block": int(h.get("block_number")), "Points": float(h.get("points_total") or 0.0)}
                for h in history
            ]
            st.markdown("### Block-by-block History")
            st.dataframe(
                pd.DataFrame(hist_rows),
                use_container_width=True,
                hide_index=True,
            )
