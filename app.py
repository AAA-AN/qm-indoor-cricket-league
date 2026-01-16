import json
import posixpath
import streamlit as st

from src.db import init_db, count_users, export_users_backup_payload, restore_users_from_backup_payload
from src.auth import create_user, authenticate_user, change_password, hash_password
from src.guard import APP_TITLE, hide_sidebar
from src.dropbox_api import get_access_token, download_file, ensure_folder, upload_file

st.set_page_config(page_title=APP_TITLE, layout="wide")


def _get_secret(name: str) -> str:
    val = st.secrets.get(name, "")
    if not val:
        raise RuntimeError(f"Missing Streamlit secret: {name}")
    return str(val)


def _dropbox_users_backup_path() -> str:
    """
    Stores backups next to your league workbook, under /app_data/users_backup.json
    (same “app folder” approach you use elsewhere).
    """
    dropbox_file_path = _get_secret("DROPBOX_FILE_PATH")
    app_folder = posixpath.dirname(dropbox_file_path.rstrip("/"))
    data_folder = posixpath.join(app_folder, "app_data")
    return posixpath.join(data_folder, "users_backup.json")


def backup_users_to_dropbox() -> None:
    app_key = _get_secret("DROPBOX_APP_KEY")
    app_secret = _get_secret("DROPBOX_APP_SECRET")
    refresh_token = _get_secret("DROPBOX_REFRESH_TOKEN")

    access_token = get_access_token(app_key, app_secret, refresh_token)

    backup_path = _dropbox_users_backup_path()
    backup_folder = posixpath.dirname(backup_path)

    ensure_folder(access_token, backup_folder)

    payload = export_users_backup_payload()
    content = json.dumps(payload, indent=2).encode("utf-8")

    # Overwrite the single backup file each time
    upload_file(access_token, backup_path, content, mode="overwrite", autorename=False)


def restore_users_from_dropbox_if_needed() -> None:
    # Only restore into an empty DB
    if count_users() != 0:
        return

    try:
        app_key = _get_secret("DROPBOX_APP_KEY")
        app_secret = _get_secret("DROPBOX_APP_SECRET")
        refresh_token = _get_secret("DROPBOX_REFRESH_TOKEN")
        default_pw = str(st.secrets.get("DEFAULT_RESET_PASSWORD", "ResetMe123!"))

        access_token = get_access_token(app_key, app_secret, refresh_token)
        backup_path = _dropbox_users_backup_path()

        raw = download_file(access_token, backup_path)
        payload = json.loads(raw.decode("utf-8"))

        default_hash = hash_password(default_pw)
        restored = restore_users_from_backup_payload(
            payload,
            default_password_hash=default_hash,
            force_reset=True,
        )

        if restored > 0:
            # Optional: surface a single warning so you know a restore occurred
            st.session_state["restored_users_count"] = restored

    except Exception:
        # If no backup exists yet (or Dropbox is unreachable), just continue normally.
        return


def ensure_session_state():
    if "user" not in st.session_state:
        st.session_state["user"] = None
    if "home_view" not in st.session_state:
        st.session_state["home_view"] = "welcome"
    if "pending_reset_username" not in st.session_state:
        st.session_state["pending_reset_username"] = ""


def home_welcome():
    st.title(APP_TITLE)

    # Optional informational banner if a restore happened this boot
    restored_n = int(st.session_state.get("restored_users_count") or 0)
    if restored_n:
        st.warning(
            f"User accounts were restored from Dropbox ({restored_n} user(s)). "
            "All restored accounts must reset their password on next login."
        )

    st.write(
        "Welcome to the QM Indoor Cricket League app.\n\n"
        "Log in to view fixtures, results, league tables, and player statistics."
    )

    st.markdown("---")
    st.subheader("Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        user = authenticate_user(username, password)
        if user:
            # If restored (or admin-forced), require password change before continuing
            if int(user.get("must_reset_password") or 0) == 1:
                st.session_state["pending_reset_username"] = user["username"]
                st.session_state["home_view"] = "force_reset"
                st.rerun()

            st.session_state["user"] = user
            st.switch_page("pages/1_QM_Social_League.py")
        else:
            st.error("Invalid username or password, or the account is disabled.")

    st.markdown("---")
    if st.button("Create an account"):
        st.session_state["home_view"] = "signup"
        st.rerun()


def home_force_reset():
    st.title("Password reset required")
    u = (st.session_state.get("pending_reset_username") or "").strip()
    if not u:
        st.session_state["home_view"] = "welcome"
        st.rerun()

    st.info(f"User '{u}' must set a new password before continuing.")

    with st.form("force_reset_form"):
        pw1 = st.text_input("New password", type="password")
        pw2 = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Update password")

    if submitted:
        if not pw1 or not pw2:
            st.error("Please enter and confirm your new password.")
            return
        if pw1 != pw2:
            st.error("Passwords do not match.")
            return

        try:
            change_password(u, pw1)
            # Back up immediately so we don’t lose the cleared reset flag
            backup_users_to_dropbox()

            # Re-authenticate the user into session and continue
            user = authenticate_user(u, pw1)
            st.session_state["user"] = user
            st.session_state["pending_reset_username"] = ""
            st.session_state["home_view"] = "welcome"
            st.switch_page("pages/1_QM_Social_League.py")

        except Exception as e:
            st.error(str(e))

    if st.button("Back to Login"):
        st.session_state["home_view"] = "welcome"
        st.session_state["pending_reset_username"] = ""
        st.rerun()


def home_signup():
    st.title("Sign up")

    with st.form("signup_form"):
        first = st.text_input("First name")
        last = st.text_input("Last name")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        password2 = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create account")

    if submitted:
        if password != password2:
            st.error("Passwords do not match.")
        else:
            try:
                create_user(first, last, username, password)
                # Back up after every successful signup
                backup_users_to_dropbox()

                st.success("Account created. You can now log in.")
                st.session_state["home_view"] = "welcome"
                st.rerun()
            except Exception as e:
                st.error(str(e))

    if st.button("Back to Welcome"):
        st.session_state["home_view"] = "welcome"
        st.rerun()


def main():
    init_db()
    ensure_session_state()

    # Restore users from Dropbox if this is a fresh boot (empty DB)
    restore_users_from_dropbox_if_needed()

    if st.session_state.get("user") is None:
        hide_sidebar()

    view = st.session_state["home_view"]
    if view == "welcome":
        home_welcome()
    elif view == "force_reset":
        home_force_reset()
    else:
        home_signup()


if __name__ == "__main__":
    main()