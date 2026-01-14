import streamlit as st
from src.db import init_db

APP_TITLE = "QM Indoor Cricket League"


def hide_sidebar():
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def hide_home_page_when_logged_in():
    """
    Hides the Home/app.py entry from the Streamlit multipage sidebar list
    when the user is logged in.

    Note: Streamlit does not provide an official API for conditionally
    hiding pages, so CSS is the standard workaround.
    """
    if st.session_state.get("user") is None:
        return

    st.markdown(
        """
        <style>
        /* Hide the first page in the sidebar page list (Home/app.py) */
        section[data-testid="stSidebar"] ul li:first-child {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def require_login():
    """Ensure DB exists, then require login."""
    init_db()
    if st.session_state.get("user") is None:
        hide_sidebar()
        st.warning("Please log in to access this page.")
        if st.button("Go to Welcome / Login"):
            st.switch_page("app.py")
        st.stop()


def require_admin():
    """Requires login first, then admin role."""
    require_login()
    user = st.session_state.get("user") or {}
    if user.get("role") != "admin":
        st.error("Admin access required.")
        st.stop()


def render_sidebar_header():
    """Sidebar header shown only when logged in."""
    user = st.session_state.get("user")
    if not user:
        return

    st.sidebar.markdown(f"### {APP_TITLE}")
    st.sidebar.write(f"**{user['first_name']} {user['last_name']}**")

    # Only show role if admin (per your requirement)
    if user.get("role") == "admin":
        st.sidebar.caption("Role: admin")

    st.sidebar.markdown("---")


def render_logout_button():
    """Logout button in sidebar (separate from pages list)."""
    if st.session_state.get("user") is None:
        return

    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state["user"] = None
        st.switch_page("app.py")
