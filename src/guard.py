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


def hide_admin_page_for_non_admins():
    """
    Hides the Admin page from the sidebar for non-admin users.
    Assumes Admin is the LAST page in the multipage list.
    """
    user = st.session_state.get("user")

    if not user or user.get("role") == "admin":
        return

    st.markdown(
        """
        <style>
        /* Hide last page (Admin) from sidebar for non-admins */
        section[data-testid="stSidebar"] ul li:last-child {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def sidebar_divider_compact():
    """A tighter divider than st.sidebar.markdown('---') to reduce vertical whitespace."""
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
    """Requires login first, then admin role."""
    require_login()
    user = st.session_state.get("user") or {}
    if user.get("role") != "admin":
        st.error("Admin access required.")
        st.stop()


def render_sidebar_header():
    """Sidebar user info shown only when logged in."""
    user = st.session_state.get("user")
    if not user:
        return

    st.sidebar.write(f"**{user['first_name']} {user['last_name']}**")

    # Only show role if admin
    if user.get("role") == "admin":
        st.sidebar.caption("Role: admin")

    sidebar_divider_compact()


def render_logout_button():
    """Logout button in sidebar (separate from pages list)."""
    if st.session_state.get("user") is None:
        return

    sidebar_divider_compact()
    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state["user"] = None
        st.switch_page("app.py")
