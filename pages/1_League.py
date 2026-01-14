import streamlit as st
from src.guard import (
    APP_TITLE,
    require_login,
    sidebar_header_above_pages,
    hide_home_page_when_logged_in,
    hide_admin_page_for_non_admins,
    render_sidebar_header,
    render_logout_button,
)

st.set_page_config(page_title=f"{APP_TITLE} - League", layout="wide")

require_login()
sidebar_header_above_pages()
hide_home_page_when_logged_in()
hide_admin_page_for_non_admins()
render_sidebar_header()
render_logout_button()

st.title("League")
st.info("League pages will be added next.")
