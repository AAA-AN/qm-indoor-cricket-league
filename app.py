import streamlit as st

from src.db import init_db
from src.auth import create_user, authenticate_user
from src.guard import APP_TITLE, hide_sidebar

st.set_page_config(page_title=APP_TITLE, layout="wide")


def ensure_session_state():
    if "user" not in st.session_state:
        st.session_state["user"] = None
    if "home_view" not in st.session_state:
        st.session_state["home_view"] = "welcome"


def home_welcome():
    st.title(APP_TITLE)
    st.write(
        "Welcome to the QM Indoor Cricket League app.\n\n"
        "Log in to view fixtures, results, league tables, and player statistics."
    )

    st.markdown("---")
    st.subheader("Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        user = authenticate_user(username, password)
        if user:
            st.session_state["user"] = user
            st.switch_page("pages/1_League.py")
        else:
            st.error("Invalid username or password, or the account is disabled.")

    st.markdown("---")
    if st.button("Create an account"):
        st.session_state["home_view"] = "signup"
        st.rerun()


def home_signup():
    st.title("Sign up")

    with st.form("signup_form"):
        first = st.text_input("First name")
        last = st.text_input("Last name")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        password2 = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create account")

    if submitted:
        if password != password2:
            st.error("Passwords do not match.")
        else:
            try:
                create_user(first, last, username, password)
                st.success("Account created. You can now log in.")
                st.session_state["home_view"] = "welcome"
                st.rerun()
            except Exception as e:
                st.error(str(e))

    if st.button("Back to Welcome"):
        st.session_state["home_view"] = "welcome"
        st.rerun()


def main():
    init_db()
    ensure_session_state()

    # Hide sidebar pre-login (your prior requirement)
    if st.session_state.get("user") is None:
        hide_sidebar()

    if st.session_state["home_view"] == "welcome":
        home_welcome()
    else:
        home_signup()


if __name__ == "__main__":
    main()
