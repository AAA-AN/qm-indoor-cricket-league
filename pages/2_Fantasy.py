import streamlit as st
from src.guard import APP_TITLE, require_login, render_sidebar_header, render_logout_button

st.set_page_config(page_title=f"{APP_TITLE} - Fantasy", layout="wide")

require_login()
render_sidebar_header()
render_logout_button()

st.title("Fantasy")
st.info("Fantasy will be added after the league section is stable.")
