import streamlit as st
from src.guard import (
    APP_TITLE,
    require_login,
    hide_home_page_when_logged_in,
    hide_admin_page_for_non_admins,
    render_sidebar_header,
    render_logout_button,
)

st.set_page_config(page_title=f"{APP_TITLE} - QM Fantasy Social League", layout="wide")

require_login()
hide_home_page_when_logged_in()
hide_admin_page_for_non_admins()
render_sidebar_header()
render_logout_button()

st.title("QM Fantasy Social League")
st.info("Fantasy will be added after the league section is stable.")
