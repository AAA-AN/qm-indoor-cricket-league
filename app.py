import streamlit as st

from src.db import init_db
from src.auth import create_user, authenticate_user
from src.pages import (
    APP_TITLE,
    page_welcome,
    page_signup,
    page_login,
    page_league_placeholder,
    page_fantasy_placeholder,
    page_admin_placeholder,
)

st.set_page_config(page_title=APP_TITLE, layout="wide")

def ensure_session_state():
    if "user" not in st.session_state:
        st.session_state["user"] = None

def logout():
    st.session_state["user"] = None
    st.rerun()

def main():
    init_db()
    ensure_session_state()

    user = st.session_state["user"]

    if user is None:
        # Pre-login simple navigation
        st.sidebar.title(APP_TITLE)
        nav = st.sidebar.radio("Menu", ["Welcome", "Login", "Sign up"])

        if nav == "Welcome":
            page_welcome()
        elif nav == "Login":
            data = page_login()
            if data["submitted"]:
                u = authenticate_user(data["username"], data["password"])
                if u:
                    st.session_state["user"] = u
                    st.success("Logged in.")
                    st.rerun()
                else:
                    st.error("Invalid username/password, or the account is disabled.")
        else:  # Sign up
            data = page_signup()
            if data["submitted"]:
                if data["password"] != data["password2"]:
                    st.error("Passwords do not match.")
                else:
                    try:
                        u = create_user(
                            first_name=data["first"],
                            last_name=data["last"],
                            username=data["username"],
                            password=data["password"],
                        )
                        st.success(
                            f"Account created. You are {'an admin' if u['role']=='admin' else 'a player'}."
                        )
                        st.info("You can now log in.")
                    except Exception as e:
                        st.error(str(e))

        return

    # Post-login navigation
    st.sidebar.title(APP_TITLE)
    st.sidebar.write(f"Logged in as: **{user['first_name']} {user['last_name']}**")
    st.sidebar.write(f"Role: **{user['role']}**")

    menu_items = ["League", "Fantasy"]
    if user["role"] == "admin":
        menu_items.append("Admin")
    menu_items.append("Logout")

    nav = st.sidebar.radio("Menu", menu_items)

    if nav == "League":
        page_league_placeholder()
    elif nav == "Fantasy":
        page_fantasy_placeholder()
    elif nav == "Admin":
        page_admin_placeholder()
    else:
        logout()

if __name__ == "__main__":
    main()
