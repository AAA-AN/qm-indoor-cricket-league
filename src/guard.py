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


def apply_sidebar_layout_css():
    """
    Makes a fixed header area at the top of the sidebar, and pushes
    Streamlit's built-in page list down beneath it.
    """
    if st.session_state.get("user") is None:
        return

    st.markdown(
        """
        <style>
        /* Reserve space at the top of the sidebar for our fixed header */
        section[data-testid="stSidebar"] div[data-testid="stSidebarContent"] {
            padding-top: 165px !important;
        }

        /* Fixed header container */
        #qm-sidebar-header {
            position: absolute;
            top: 12px;
            left: 16px;
            right: 16px;
            z-index: 9999;
        }

        /* Tighten header typography slightly */
        #qm-sidebar-header .qm-title {
            font-size: 18px;
            font-weight: 700;
            margin: 0 0 8px 0;
        }
        #qm-sidebar-header .qm-user {
            font-size: 14px;
            font-weight: 700;
            margin: 0 0 2px 0;
        }
        #qm-sidebar-header .qm-role {
            font-size: 12px;
            opacity: 0.8;
            margin: 0;
        }
        #qm-sidebar-header hr {
            margin: 12px 0 0 0;
            opacity: 0.25;
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


def render_sidebar_header_fixed():
    """
    Renders the header HTML into the sidebar; CSS positions it at the top.
    Must be called after apply_sidebar_layout_css().
    """
    user = st.session_state.get("user")
    if not user:
        return

    role_line = ""
    if user.get("role") == "admin":
        role_line = '<p class="qm-role">Role: admin</p>'

    st.sidebar.markdown(
        f"""
        <div id="qm-sidebar-header">
            <div class="qm-title">{APP_TITLE}</div>
            <div class="qm-user">{user['first_name']} {user['last_name']}</div>
            {role_line}
            <hr/>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_logout_button():
    """Logout button in sidebar (separate from pages list)."""
    if st.session_state.get("user") is None:
        return

    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state["user"] = None
        st.switch_page("app.py")
