"""Reusable small page fragments used by the home/login flow."""

import streamlit as st

APP_TITLE = "QM Indoor Cricket League"

def page_welcome():
    st.title(APP_TITLE)
    st.write(
        "Welcome to the QM Indoor Cricket League app.\n\n"
        "Use the navigation below to sign up or log in."
    )

def page_signup():
    st.header("Sign up")
    with st.form("signup_form", clear_on_submit=False):
        first = st.text_input("First name")
        last = st.text_input("Last name")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        password2 = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create account")

    return {
        "submitted": submitted,
        "first": first,
        "last": last,
        "username": username,
        "password": password,
        "password2": password2,
    }

def page_login():
    st.header("Login")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    return {"submitted": submitted, "username": username, "password": password}

def page_league_placeholder():
    st.title("League")
    st.info("League pages will be added next (Fixtures & Results, Teams, Player Stats).")

def page_fantasy_placeholder():
    st.title("Fantasy")
    st.info("Fantasy will be added after the league section is stable.")

def page_admin_placeholder():
    st.title("Admin")
    st.info("Admin tools will be added next (manage users, reset passwords).")
