import streamlit as st

from src.db import init_db
from src.auth import create_user, authenticate_user
from src.pages import (
    APP_TITLE,
    page_league_placeholder,
    page_fantasy_placeholder,
    page_admin_placeholder,
)

st.set_page_config(page_title=APP_TITLE, layout="wide")


def ensure_session_state():
    if "user" not in st.session_state:
        st.session_state["user"] = None
    if "prelogin_page" not in st.session_state:
        st.session_state["prelogin_page"] = "welcome"


def logout():
    st.session_state["user"] = None
    st.session_state["prelogin_page"] = "welcome"
    st.rerun()


def prelogin_welcome():
    st.title(APP_TITLE)
    st.write(
        "Welcome to the QM Indoor Cricket League app.\n\n"
        "View fixtures, results, league tables, and player statistics."
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
            st.success("Logged in successfully.")
            st.rerun()
        else:
            st.error("Invalid username or password.")

    st.markdown("---")
    if st.button("Create an account"):
        st.session_state["prelogin_page"] = "signup"
        st.rerun()


def prelogin_signup():
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
                st.session_state["prelogin_page"] = "welcome"
                st.rerun()
            except Exception as e:
                st.error(str(e))

    if st.button("Back to Welcome"):
        st.session_state["prelogin_page"] = "welcome"
        st.rerun()


def main():
    init_db()
    ensure_session_state()

    user = st.session_state["user"]

    # -------------------------
    # PRE-LOGIN (NO SIDEBAR)
    # -------------------------
    if user is None:
        if st.session_state["prelogin_page"] == "welcome":
            prelogin_welcome()
        else:
            prelogin_signup()
        return

    # -------------------------
    # POST-LOGIN (SIDEBAR)
    # -------------------------
    st.sidebar.title(APP_TITLE)
    st.sidebar.write(f"**{user['first_name']} {user['last_name']}**")

    if user["role"] == "admin":
        st.sidebar.caption("Role: admin")

    menu_items = ["League", "Fantasy"]
    if user["role"] == "admin":
        menu_items.append("Admin")

    nav = st.sidebar.radio("Menu", menu_items)

    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", use_container_width=True):
        logout()

    if nav == "League":
        page_league_placeholder()
    elif nav == "Fantasy":
        page_fantasy_placeholder()
    elif nav == "Admin":
        page_admin_placeholder()


if __name__ == "__main__":
    main()
