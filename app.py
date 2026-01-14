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
    if "nav" not in st.session_state:
        st.session_state["nav"] = "League"


def logout():
    st.session_state["user"] = None
    st.session_state["prelogin_page"] = "welcome"
    st.session_state["nav"] = "League"
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
            st.error("Invalid username or password, or the account is disabled.")

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


def sidebar_nav_list_style():
    """
    CSS to make a sidebar radio look like a simple page list:
    - no radio circles
    - selected item highlighted
    - spacing similar to Streamlit multipage sidebar
    """
    st.markdown(
        """
        <style>
        /* Sidebar title spacing */
        section[data-testid="stSidebar"] h1, 
        section[data-testid="stSidebar"] h2, 
        section[data-testid="stSidebar"] h3 {
            margin-bottom: 0.25rem;
        }

        /* Make radio group look like a page list */
        section[data-testid="stSidebar"] div[role="radiogroup"] > label {
            width: 100%;
            border-radius: 0.4rem;
            padding: 0.35rem 0.5rem;
            margin: 0.1rem 0;
        }

        /* Hide the radio circle */
        section[data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child {
            display: none !important;
        }

        /* Ensure the text spans nicely */
        section[data-testid="stSidebar"] div[role="radiogroup"] > label > div:last-child {
            width: 100%;
        }

        /* Highlight the selected item (Streamlit uses aria-checked on the label) */
        section[data-testid="stSidebar"] div[role="radiogroup"] > label[aria-checked="true"] {
            background: rgba(255, 255, 255, 0.12);
            font-weight: 600;
        }

        /* Slight hover affordance */
        section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
            background: rgba(255, 255, 255, 0.06);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
    sidebar_nav_list_style()

    st.sidebar.markdown(f"### {APP_TITLE}")
    st.sidebar.write(f"**{user['first_name']} {user['last_name']}**")
    if user["role"] == "admin":
        st.sidebar.caption("Role: admin")

    # Pages list
    menu_items = ["League", "Fantasy"]
    if user["role"] == "admin":
        menu_items.append("Admin")

    nav = st.sidebar.radio(
        "Navigation",
        menu_items,
        index=menu_items.index(st.session_state.get("nav", "League")),
        label_visibility="collapsed",
    )
    st.session_state["nav"] = nav

    # Separate logout button
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", use_container_width=True):
        logout()

    # Routing
    if nav == "League":
        page_league_placeholder()
    elif nav == "Fantasy":
        page_fantasy_placeholder()
    elif nav == "Admin":
        page_admin_placeholder()


if __name__ == "__main__":
    main()
