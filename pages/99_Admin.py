import streamlit as st
import pandas as pd
import posixpath
import re
from datetime import datetime, timezone

from src.guard import (
    APP_TITLE,
    require_admin,
    hide_home_page_when_logged_in,
    hide_admin_page_for_non_admins,
    render_sidebar_header,
    render_logout_button,
)
from src.db import (
    list_users,
    get_user_by_username,
    count_admins,
    set_user_active,
    set_user_role,
    delete_user,
    # Scorecard DB helpers (Step 1)
    add_scorecard,
    list_scorecards,
    delete_scorecard_by_path,
)
from src.auth import admin_reset_password

from src.dropbox_api import (
    get_access_token,
    download_file,
    ensure_folder,
    upload_file,
    delete_path,
    list_folder,
)
from src.excel_io import load_league_workbook_from_bytes


st.set_page_config(page_title=f"{APP_TITLE} - Admin", layout="wide")

require_admin()
hide_home_page_when_logged_in()
hide_admin_page_for_non_admins()
render_sidebar_header()
render_logout_button()


def _get_secret(name: str) -> str:
    val = st.secrets.get(name, "")
    if not val:
        raise RuntimeError(f"Missing Streamlit secret: {name}")
    return str(val)


@st.cache_data(ttl=60, show_spinner=False)
def _load_workbook_fixture_results(app_key: str, app_secret: str, refresh_token: str, dropbox_path: str) -> pd.DataFrame:
    """
    Loads the league workbook from Dropbox and returns the fixture_results dataframe.
    Cached briefly to keep Admin UI responsive.
    """
    access_token = get_access_token(app_key, app_secret, refresh_token)
    xbytes = download_file(access_token, dropbox_path)
    data = load_league_workbook_from_bytes(xbytes)
    fixtures = data.fixture_results.copy()
    fixtures.columns = [str(c).strip() for c in fixtures.columns]
    return fixtures


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

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

st.title("Admin")

tab_users, tab_scorecards = st.tabs(["User Management", "Scorecard Management"])

# =========================================================
# TAB 1: USER MANAGEMENT (existing functionality, unchanged)
# =========================================================
with tab_users:
    st.subheader("User Management")

    users = list_users()
    if not users:
        st.info("No users found.")
        st.stop()

    df = pd.DataFrame(users)
    df_display = df.copy()
    df_display["is_active"] = df_display["is_active"].map({1: "Active", 0: "Disabled"})

    st.markdown("### All users")
    st.dataframe(
        df_display[["username", "first_name", "last_name", "role", "is_active", "created_at"]],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")
    st.markdown("### Manage a user")

    usernames = df_display["username"].tolist()
    selected_username = st.selectbox("Select user", usernames, key="admin_user_select")

    selected = get_user_by_username(selected_username)
    if not selected:
        st.error("Selected user could not be found (it may have been deleted).")
        st.stop()

    selected_role = selected["role"]
    selected_active = bool(selected["is_active"])

    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Name:** {selected['first_name']} {selected['last_name']}")
        st.write(f"**Username:** {selected['username']}")
    with col2:
        st.write(f"**Role:** {selected_role}")
        st.write(f"**Status:** {'Active' if selected_active else 'Disabled'}")

    admins_total = count_admins(active_only=False)

    def is_last_admin_target() -> bool:
        return selected_role == "admin" and admins_total == 1

    st.markdown("### Actions")

    with st.expander("Enable / Disable user", expanded=False):
        desired_active = st.radio(
            "Set account status",
            ["Active", "Disabled"],
            index=0 if selected_active else 1,
            horizontal=True,
            key="admin_user_status_radio",
        )
        make_active = desired_active == "Active"

        if st.button("Apply status change", use_container_width=True, key="admin_apply_status"):
            if not make_active and is_last_admin_target():
                st.error("Blocked: You cannot disable the last remaining admin.")
            else:
                set_user_active(selected_username, make_active)
                st.success("User status updated.")
                st.rerun()

    with st.expander("Reset password", expanded=False):
        new_pw = st.text_input("New password", type="password", key="admin_new_pw")
        new_pw2 = st.text_input("Confirm new password", type="password", key="admin_new_pw2")
        if st.button("Reset password", use_container_width=True, key="admin_reset_pw_btn"):
            if not new_pw or not new_pw2:
                st.error("Please enter and confirm the new password.")
            elif new_pw != new_pw2:
                st.error("Passwords do not match.")
            else:
                try:
                    admin_reset_password(selected_username, new_pw)
                    st.success("Password reset successfully.")
                except Exception as e:
                    st.error(str(e))

    with st.expander("Change role", expanded=False):
        desired_role = st.selectbox(
            "Role",
            ["player", "admin"],
            index=0 if selected_role == "player" else 1,
            key="admin_role_select",
        )

        if st.button("Apply role change", use_container_width=True, key="admin_apply_role"):
            if desired_role == selected_role:
                st.info("No change to apply.")
            else:
                if selected_role == "admin" and desired_role == "player" and is_last_admin_target():
                    st.error("Blocked: You cannot demote the last remaining admin.")
                else:
                    set_user_role(selected_username, desired_role)
                    st.success("Role updated.")
                    st.rerun()

    with st.expander("Delete user", expanded=False):
        st.warning("This permanently deletes the user account. This cannot be undone.")
        confirm = st.checkbox("I understand and want to delete this user", key="admin_delete_user_confirm")

        if st.button("Delete user", use_container_width=True, disabled=not confirm, key="admin_delete_user_btn"):
            if is_last_admin_target():
                st.error("Blocked: You cannot delete the last remaining admin.")
            else:
                delete_user(selected_username)
                st.success("User deleted.")
                st.rerun()


# =========================================================
# TAB 2: SCORECARD MANAGEMENT
# =========================================================
with tab_scorecards:
    st.subheader("Scorecard Management")

    # ---- Read Dropbox secrets (same as other pages) ----
    try:
        app_key = _get_secret("DROPBOX_APP_KEY")
        app_secret = _get_secret("DROPBOX_APP_SECRET")
        refresh_token = _get_secret("DROPBOX_REFRESH_TOKEN")
        dropbox_file_path = _get_secret("DROPBOX_FILE_PATH")  # Excel workbook path
    except Exception as e:
        st.error(str(e))
        st.stop()

    # Derive "app folder" from the workbook path, then add /scorecards
    app_folder = posixpath.dirname(dropbox_file_path.rstrip("/"))
    scorecards_root = posixpath.join(app_folder, "scorecards")

    # Load fixtures so admins can pick a MatchID confidently
    with st.spinner("Loading fixtures from Dropbox..."):
        try:
            fixtures_df = _load_workbook_fixture_results(app_key, app_secret, refresh_token, dropbox_file_path)
        except Exception as e:
            st.error(f"Failed to load fixtures from Dropbox: {e}")
            st.stop()

    if "MatchID" not in fixtures_df.columns:
        st.error("Cannot find required column 'MatchID' in fixtures. Please confirm it exists in the workbook.")
        st.stop()

    # Build a friendly label if columns exist
    cols = fixtures_df.columns.tolist()
    has_date = "Date" in cols
    has_time = "Time" in cols
    has_home = "Home Team" in cols
    has_away = "Away Team" in cols

    fixture_rows = fixtures_df.copy()

    # Format Admin fixture selector display to match main app
    if has_date:
        fixture_rows["Date"] = _format_date_dd_mmm(fixture_rows["Date"])
    if has_time:
        fixture_rows["Time"] = _format_time_ampm(fixture_rows["Time"])

    def _safe_str(v) -> str:
        if pd.isna(v):
            return ""
        return str(v).strip()
    
    def _clean_name_for_path(s: str) -> str:
        """
        Make a safe-ish filename component for Dropbox:
        - remove slashes
        - collapse whitespace
        - strip
        """
        s = (s or "").replace("/", "-").replace("\\", "-")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _next_named_filename(existing_names: set[str], base: str, ext: str) -> str:
        """
        For PDFs: base + ext (first), then base + ' 2' + ext, base + ' 3' + ext...
        For images (or any base that already includes a number placeholder in the base),
        you can pass base like '... Image' and it will find the next integer suffix.
        """
        base = base.strip()
        ext = ext if ext.startswith(".") else f".{ext}"

        # PDF-style: "Base.ext" then "Base 2.ext" ...
        # We will treat "Base.ext" as number 1.
        pattern = re.compile(rf"^{re.escape(base)}(?: (\d+))?{re.escape(ext)}$", re.IGNORECASE)

        max_n = 0
        for name in existing_names:
            m = pattern.match(name)
            if not m:
                continue
            n_txt = m.group(1)
            n = 1 if n_txt is None else int(n_txt)
            max_n = max(max_n, n)

        next_n = max_n + 1
        if next_n == 1:
            return f"{base}{ext}"
        return f"{base} {next_n}{ext}"

    def _next_image_filename(existing_names: set[str], base_prefix: str, ext: str) -> str:
        """
        Images: "BasePrefix 1.ext", "BasePrefix 2.ext"...
        """
        base_prefix = base_prefix.strip()
        ext = ext if ext.startswith(".") else f".{ext}"

        pattern = re.compile(rf"^{re.escape(base_prefix)} (\d+){re.escape(ext)}$", re.IGNORECASE)

        max_n = 0
        for name in existing_names:
            m = pattern.match(name)
            if not m:
                continue
            max_n = max(max_n, int(m.group(1)))

        return f"{base_prefix} {max_n + 1}{ext}"
    
    options = []
    option_to_match_id = {}

    for _, r in fixture_rows.iterrows():
        mid = _safe_str(r.get("MatchID"))
        if not mid:
            continue

        parts = [mid]
        if has_date:
            parts.append(_safe_str(r.get("Date")))
        if has_time:
            parts.append(_safe_str(r.get("Time")))
        if has_home and has_away:
            parts.append(f"{_safe_str(r.get('Home Team'))} vs {_safe_str(r.get('Away Team'))}")
        label = " — ".join([p for p in parts if p])

        options.append(label)
        option_to_match_id[label] = mid

    if not options:
        st.info("No fixtures with a valid MatchID were found.")
        st.stop()

    selected_label = st.selectbox("Select fixture", options, key="scorecard_match_select")
    match_id = option_to_match_id[selected_label]

    st.caption(f"Dropbox scorecard folder: {posixpath.join(scorecards_root, match_id)}")

    st.markdown("### Upload files")
        # Used to clear the file_uploader after successful upload
    if "scorecard_uploader_nonce" not in st.session_state:
        st.session_state["scorecard_uploader_nonce"] = 0

    uploader_key = f"scorecard_uploader_{match_id}_{st.session_state['scorecard_uploader_nonce']}"

    uploaded_files = st.file_uploader(
        "Upload scorecard PDFs or screenshots (you can select multiple files)",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key=uploader_key,
    )

    colu1, colu2 = st.columns([1, 2])
    with colu1:
        do_upload = st.button("Upload to Match", use_container_width=True, disabled=not uploaded_files, key="scorecard_upload_btn")
    with colu2:
        st.write("Uploads are appended (existing files are not removed). Filenames may be auto-renamed if duplicates exist.")

    if do_upload:
        try:
            access_token = get_access_token(app_key, app_secret, refresh_token)

            # Ensure /scorecards and /scorecards/<MatchID> exist
            ensure_folder(access_token, scorecards_root)
            match_folder = posixpath.join(scorecards_root, match_id)
            ensure_folder(access_token, match_folder)

            uploader_username = (st.session_state.get("user") or {}).get("username", "")

            # Pull Home/Away names for this MatchID (for renaming)
            fx = fixtures_df.copy()
            fx["MatchID"] = fx["MatchID"].astype(str).str.strip()
            fx_row = fx[fx["MatchID"] == str(match_id).strip()]

            home = ""
            away = ""
            if not fx_row.empty:
                r0 = fx_row.iloc[0]
                home = _safe_str(r0.get("Home Team"))
                away = _safe_str(r0.get("Away Team"))

            match_desc = _clean_name_for_path(f"{home} vs {away}".strip(" vs "))

            # Read existing Dropbox filenames in this match folder to pick next numbers consistently
            existing_entries = []
            try:
                existing_entries = list_folder(access_token, match_folder) or []
            except Exception:
                existing_entries = []

            existing_names = set()
            for e in existing_entries:
                nm = e.get("name")
                if nm:
                    existing_names.add(str(nm))

            for f in uploaded_files:
                original_name = f.name
                content = f.getvalue()

                # Extension handling
                ext = ""
                if "." in original_name:
                    ext = "." + original_name.split(".")[-1].lower().strip(".")
                else:
                    ext = ""

                is_pdf = ext == ".pdf"
                is_image = ext in [".png", ".jpg", ".jpeg", ".webp"]

                # Default fallback if we can't determine teams
                if not match_desc:
                    match_desc = _clean_name_for_path(f"Match {match_id}")

                # Build the new filename
                if is_pdf:
                    base = f"{match_desc} Scorecard"
                    new_name = _next_named_filename(existing_names, base=base, ext=ext)
                elif is_image:
                    # Normalise jpeg extension style to .jpeg if desired; keep original if you prefer.
                    if ext == ".jpg":
                        ext_use = ".jpeg"
                    else:
                        ext_use = ext

                    base_prefix = f"{match_desc} Scorecard Image"
                    new_name = _next_image_filename(existing_names, base_prefix=base_prefix, ext=ext_use)
                else:
                    # Unknown type: keep original name but still avoid collisions via Dropbox autorename
                    new_name = original_name

                # Ensure our set updates so multiple uploads in one click increment properly
                existing_names.add(new_name)

                dropbox_target_path = posixpath.join(match_folder, new_name)

                meta = upload_file(
                    access_token,
                    dropbox_target_path,
                    content,
                    mode="add",
                    autorename=True,  # still keep as a final backstop
                )

                dbx_path = meta.get("path_display") or meta.get("path_lower") or dropbox_target_path
                stored_name = meta.get("name") or new_name

                add_scorecard(
                    match_id=match_id,
                    file_name=stored_name,
                    dropbox_path=dbx_path,
                    uploaded_at=_utc_now_iso(),
                    uploaded_by=uploader_username,
                )

            st.success("Upload complete.")
            st.session_state["scorecard_uploader_nonce"] += 1
            st.rerun()

        except Exception as e:
            st.error(f"Upload failed: {e}")

        st.markdown("---")

    # =========================
    # Collapsible: Uploaded files
    # =========================
    with st.expander("Uploaded scorecards for this fixture", expanded=False):

        existing = list_scorecards(match_id)

        # Show in upload order (oldest first)
        existing = sorted(
            existing,
            key=lambda r: (str(r.get("uploaded_at") or ""), int(r.get("scorecard_id") or 0)),
        )
        # --- Reconcile SQLite records with what actually exists in Dropbox ---
        # If a file was deleted directly in Dropbox, remove the stale DB record
        # so the UI does not show phantom uploads.
        try:
            access_token = get_access_token(app_key, app_secret, refresh_token)
            match_folder = posixpath.join(scorecards_root, match_id)

            dbx_entries = list_folder(access_token, match_folder)

            # Normalise to a comparable set of paths.
            # Dropbox may return path_display and/or path_lower.
            dbx_paths = set()
            for e in dbx_entries:
                p_disp = e.get("path_display")
                p_low = e.get("path_lower")
                if p_disp:
                    dbx_paths.add(str(p_disp))
                    dbx_paths.add(str(p_disp).lower())
                if p_low:
                    dbx_paths.add(str(p_low))
                    dbx_paths.add(str(p_low).lower())

            stale = []
            for row in existing:
                p = str(row.get("dropbox_path", "") or "")
                if not p:
                    continue
                if p not in dbx_paths and p.lower() not in dbx_paths:
                    stale.append(p)

            # Auto-clean stale records (Dropbox file already gone)
            if stale:
                for p in stale:
                    delete_scorecard_by_path(p)

                # Re-load now-clean list for display
                existing = list_scorecards(match_id)

                # Show in upload order (oldest first)
                existing = sorted(
                    existing,
                    key=lambda r: (str(r.get("uploaded_at") or ""), int(r.get("scorecard_id") or 0)),
                )
                st.warning(
                    f"Cleaned up {len(stale)} stale scorecard record(s) (they were deleted directly in Dropbox)."
                )

        except Exception as e:
            # If Dropbox check fails, we still show DB list rather than breaking Admin.
            st.info(f"Dropbox cross-check unavailable (showing DB records only): {e}")

        if not existing:
            st.info("No scorecards uploaded yet for this Match.")
        else:
            for row in existing:
                fname = row.get("file_name", "")
                uploaded_at = row.get("uploaded_at", "")
                uploaded_by = row.get("uploaded_by", "")
                dbx_path = row.get("dropbox_path", "")
                scorecard_id = row.get("scorecard_id", "")

                with st.expander(f"{fname}", expanded=False):
                    st.write(f"**Uploaded at:** {uploaded_at}")
                    if uploaded_by:
                        st.write(f"**Uploaded by:** {uploaded_by}")
                    st.write(f"**Dropbox path:** `{dbx_path}`")

                    confirm_del = st.checkbox(
                        "I want to delete this file from Dropbox",
                        key=f"scorecard_del_confirm_{scorecard_id}",
                    )

                    if st.button(
                        "Delete file",
                        type="primary",
                        use_container_width=True,
                        disabled=not confirm_del,
                        key=f"scorecard_del_btn_{scorecard_id}",
                    ):
                        try:
                            access_token = get_access_token(app_key, app_secret, refresh_token)
                            delete_path(access_token, dbx_path)          # remove from Dropbox
                            delete_scorecard_by_path(dbx_path)           # remove from SQLite
                            st.success("Deleted.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Delete failed: {e}")

    # =========================
    # Collapsible: Delete all
    # =========================
    with st.expander("Delete all files for this Match", expanded=False):
        st.warning(
            "This will permanently delete ALL uploaded scorecard files for this Match"
            "and remove their records from the database. This cannot be undone."
        )

        confirm_del_all = st.checkbox(
            "I understand and want to delete ALL scorecard files for this Match",
            key=f"scorecard_delete_all_confirm_{match_id}",
        )

        if st.button(
            "Delete ALL files for this Match",
            type="primary",
            use_container_width=True,
            disabled=not confirm_del_all,
            key=f"scorecard_delete_all_btn_{match_id}",
        ):
            try:
                access_token = get_access_token(app_key, app_secret, refresh_token)

                # 1) Delete all SQLite rows for this match
                existing_rows = list_scorecards(match_id)
                for row in existing_rows:
                    p = str(row.get("dropbox_path", "") or "")
                    if p:
                        delete_scorecard_by_path(p)

                # 2) Delete the entire Dropbox folder for this match (removes all files inside)
                match_folder = posixpath.join(scorecards_root, match_id)
                try:
                    delete_path(access_token, match_folder)
                except Exception:
                    pass  # Folder already gone is acceptable

                st.success("All scorecard files and database records for this Match have been deleted.")
                st.rerun()
            except Exception as e:
                st.error(f"Delete-all failed: {e}")