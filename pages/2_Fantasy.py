import streamlit as st
from src.guard import (
    APP_TITLE,
    require_login,
    apply_sidebar_layout_css,
    hide_home_page_when_logged_in,
    hide_admin_page_for_non_admins,
    render_sidebar_header_fixed,
    render_logout_button,
)

st.set_page_config(page_title=f"{APP_TITLE} - Fantasy", layout="wide")

require_login()
apply_sidebar_layout_css()
hide_home_page_when_logged_in()
hide_admin_page_for_non_admins()
render_sidebar_header_fixed()
render_logout_button()

st.title("Fantasy")
st.info("Fantasy will be added after the league section is stable.")
