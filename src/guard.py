import streamlit as st

from src.db import init_db

APP_TITLE = "QM Indoor Cricket League"


def hide_sidebar():
    st.markdown(
        """
        <style>
            [data-testid="stSidebar"] {display: none;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def sidebar_divider_compact():
    st.sidebar.markdown(
        '<hr style="margin: 0.25rem 0; border: 0; border-top: 1px solid rgba(49, 51, 63, 0.2);" />',
        unsafe_allow_html=True,
    )


def require_login():
    """Ensure DB exists, then require login. If not logged in, redirect to app.py."""
    init_db()

    if st.session_state.get("user") is None:
        hide_sidebar()
        st.switch_page("app.py")
        st.stop()


def require_admin():
    """Require logged-in admin. Non-admins are redirected to app.py."""
    require_login()
    user = st.session_state.get("user") or {}
    if user.get("role") != "admin":
        st.switch_page("app.py")
        st.stop()


def hide_home_page_when_logged_in():
    """
    Hide app.py from sidebar once logged in.
    """
    if st.session_state.get("user") is not None:
        st.markdown(
            """
            <style>
                [data-testid="stSidebarNav"] ul li:first-child {display: none;}
            </style>
            """,
            unsafe_allow_html=True,
        )


def hide_admin_page_for_non_admins():
    """
    Hide the last page in the sidebar nav for non-admin users.
    Assumes the Admin page is the last page (e.g., pages/99_Admin.py).
    """
    user = st.session_state.get("user")
    if not user:
        return

    if user.get("role") != "admin":
        st.markdown(
            """
            <style>
                [data-testid="stSidebarNav"] ul li:last-child {display: none;}
            </style>
            """,
            unsafe_allow_html=True,
        )


ddef render_sidebar_header():
    """
    User block under the built-in sidebar nav.
    Do NOT add a divider here because Streamlit already shows one under the nav list.
    """
    user = st.session_state.get("user")
    if not user:
        return

    name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    st.sidebar.markdown(f"### {name}")

    if user.get("role") == "admin":
        st.sidebar.caption("Admin")

def render_logout_button():
    """Logout button directly under user block (no extra divider)."""
    if st.session_state.get("user") is None:
        return

    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state["user"] = None
        st.switch_page("app.py")
