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


def sidebar_header_above_pages():
    """
    Visually pushes the built-in multipage list down so our custom header
    appears above it.
    """
    if st.session_state.get("user") is None:
        return

    st.markdown(
        """
        <style>
        /* Push the built-in pages list down */
        section[data-testid="stSidebar"] ul {
            margin-top: 140px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def hide_home_page_when_logged_in():
    """Hide Home (app.py) from sidebar when logged in."""
    if st.session_state.get("user") is None:
        return

    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] ul li:first-child {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def hide_admin_page_for_non_admins():
    """Hide Admin page from sidebar for non-admin users."""
    user = st.session_state.get("user")

    if not user or user.get("role") == "admin":
        return

    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] ul li:last-child {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def require_login():
    init_db()

    if st.session_state.get("user") is None:
        hide_sidebar()
        st.warning("Please log in to access this page.")
        if st.button("Go to Welcome / Login"):
            st.switch_page("app.py")
        st.stop()


def require_admin():
    require_login()
    user = st.session_state.get("user") or {}
    if user.get("role") != "admin":
        st.error("Admin access required.")
        st.stop()


def render_sidebar_header():
    """Renders header content that should appear above the pages list."""
    user = st.session_state.get("user")
    if not user:
        return

    st.sidebar.markdown(f"### {APP_TITLE}")
    st.sidebar.write(f"**{user['first_name']} {user['last_name']}**")

    # Only show role if admin
    if user.get("role") == "admin":
        st.sidebar.caption("Role: admin")

    st.sidebar.markdown("---")


def render_logout_button():
    """Logout button in sidebar."""
    if st.session_state.get("user") is None:
        return

    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state["user"] = None
        st.switch_page("app.py")
