import streamlit as st
import pandas as pd

from src.guard import (
    APP_TITLE,
    require_admin,
    hide_home_page_when_logged_in,
    hide_admin_page_for_non_admins,
    render_sidebar_header,
    render_logout_button,
)
from src.db import (
    list_users,
    get_user_by_username,
    count_admins,
    set_user_active,
    set_user_role,
    delete_user,
)
from src.auth import admin_reset_password


st.set_page_config(page_title=f"{APP_TITLE} - Admin", layout="wide")

require_admin()
hide_home_page_when_logged_in()
hide_admin_page_for_non_admins()
render_sidebar_header()
render_logout_button()

st.title("Admin – User Management")

# -----------------------------
# Load users
# -----------------------------
users = list_users()
if not users:
    st.info("No users found.")
    st.stop()

df = pd.DataFrame(users)
df_display = df.copy()
df_display["is_active"] = df_display["is_active"].map({1: "Active", 0: "Disabled"})

st.subheader("All users")
st.dataframe(
    df_display[["username", "first_name", "last_name", "role", "is_active", "created_at"]],
    use_container_width=True,
    hide_index=True,
)

st.markdown("---")
st.subheader("Manage a user")

usernames = df_display["username"].tolist()
selected_username = st.selectbox("Select user", usernames)

selected = get_user_by_username(selected_username)
if not selected:
    st.error("Selected user could not be found (it may have been deleted).")
    st.stop()

selected_role = selected["role"]
selected_active = bool(selected["is_active"])

col1, col2 = st.columns(2)
with col1:
    st.write(f"**Name:** {selected['first_name']} {selected['last_name']}")
    st.write(f"**Username:** {selected['username']}")
with col2:
    st.write(f"**Role:** {selected_role}")
    st.write(f"**Status:** {'Active' if selected_active else 'Disabled'}")

# Helper for safety rules
admins_total = count_admins(active_only=False)

def is_last_admin_target() -> bool:
    return selected_role == "admin" and admins_total == 1

st.markdown("### Actions")

# -----------------------------
# Enable/Disable
# -----------------------------
with st.expander("Enable / Disable user", expanded=False):
    desired_active = st.radio(
        "Set account status",
        ["Active", "Disabled"],
        index=0 if selected_active else 1,
        horizontal=True,
    )
    make_active = desired_active == "Active"

    if st.button("Apply status change", use_container_width=True):
        if not make_active and is_last_admin_target():
            st.error("Blocked: You cannot disable the last remaining admin.")
        else:
            set_user_active(selected_username, make_active)
            st.success("User status updated.")
            st.rerun()

# -----------------------------
# Reset password
# -----------------------------
with st.expander("Reset password", expanded=False):
    new_pw = st.text_input("New password", type="password")
    new_pw2 = st.text_input("Confirm new password", type="password")
    if st.button("Reset password", use_container_width=True):
        if not new_pw or not new_pw2:
            st.error("Please enter and confirm the new password.")
        elif new_pw != new_pw2:
            st.error("Passwords do not match.")
        else:
            try:
                admin_reset_password(selected_username, new_pw)
                st.success("Password reset successfully.")
            except Exception as e:
                st.error(str(e))

# -----------------------------
# Change role
# -----------------------------
with st.expander("Change role", expanded=False):
    desired_role = st.selectbox("Role", ["player", "admin"], index=0 if selected_role == "player" else 1)

    if st.button("Apply role change", use_container_width=True):
        if desired_role == selected_role:
            st.info("No change to apply.")
        else:
            if selected_role == "admin" and desired_role == "player" and is_last_admin_target():
                st.error("Blocked: You cannot demote the last remaining admin.")
            else:
                set_user_role(selected_username, desired_role)
                st.success("Role updated.")
                st.rerun()

# -----------------------------
# Delete user
# -----------------------------
with st.expander("Delete user", expanded=False):
    st.warning("This permanently deletes the user account. This cannot be undone.")
    confirm = st.checkbox("I understand and want to delete this user")

    if st.button("Delete user", use_container_width=True, disabled=not confirm):
        if is_last_admin_target():
            st.error("Blocked: You cannot delete the last remaining admin.")
        else:
            delete_user(selected_username)
            st.success("User deleted.")
            st.rerun()
