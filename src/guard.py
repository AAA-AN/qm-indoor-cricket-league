import streamlit as st

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

def require_login():
    """If not logged in, hide sidebar and show a message."""
    if st.session_state.get("user") is None:
        hide_sidebar()
        st.warning("Please log in to access this page.")
        st.stop()

def require_admin():
    """Requires login first, then admin role."""
    require_login()
    user = st.session_state.get("user")
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

    # Only show role if admin (your requirement)
    if user.get("role") == "admin":
        st.sidebar.caption("Role: admin")

    st.sidebar.markdown("---")

def render_logout_button():
    """Logout button in sidebar (separate from pages list)."""
    if st.session_state.get("user") is None:
        return

    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state["user"] = None
        st.rerun()
