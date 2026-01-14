import streamlit as st
from src.guard import (
    APP_TITLE,
    require_admin,
    hide_home_page_when_logged_in,
    render_sidebar_header,
    render_logout_button,
)

st.set_page_config(page_title=f"{APP_TITLE} - Admin", layout="wide")

require_admin()
hide_home_page_when_logged_in()
render_sidebar_header()
render_logout_button()

st.title("Admin")
st.info("Admin tools will be added next (manage users, reset passwords).")
