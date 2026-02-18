from __future__ import annotations

# Dropbox API helpers used by the app for workbook, backup, and scorecard I/O.

import json
import requests

TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
DOWNLOAD_URL = "https://content.dropboxapi.com/2/files/download"
TEMP_LINK_URL = "https://api.dropboxapi.com/2/files/get_temporary_link"
UPLOAD_URL = "https://content.dropboxapi.com/2/files/upload"
LIST_FOLDER_URL = "https://api.dropboxapi.com/2/files/list_folder"
DELETE_URL = "https://api.dropboxapi.com/2/files/delete_v2"
CREATE_FOLDER_URL = "https://api.dropboxapi.com/2/files/create_folder_v2"

def get_access_token(app_key: str, app_secret: str, refresh_token: str, timeout_s: int = 30) -> str:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": app_key,
        "client_secret": app_secret,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=timeout_s)
    if not r.ok:
        raise RuntimeError(f"Dropbox token error {r.status_code}: {r.text}")
    payload = r.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError(f"Dropbox token response missing access_token: {payload}")
    return token


def download_file(access_token: str, dropbox_path: str, timeout_s: int = 60) -> bytes:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Dropbox-API-Arg": json.dumps({"path": dropbox_path}),
    }
    r = requests.post(DOWNLOAD_URL, headers=headers, timeout=timeout_s)

    # If Dropbox returns a structured error, expose it (this is what you need)
    if not r.ok:
        raise RuntimeError(f"Dropbox download error {r.status_code}: {r.text}")

    return r.content

def ensure_folder(access_token: str, dropbox_folder_path: str, timeout_s: int = 30) -> None:
    """
    Create a folder if it doesn't exist. Safe to call repeatedly.
    """
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {"path": dropbox_folder_path, "autorename": False}

    r = requests.post(CREATE_FOLDER_URL, headers=headers, json=payload, timeout=timeout_s)

    # 409 is commonly returned if the folder already exists; treat as OK.
    if r.status_code == 409:
        return

    if not r.ok:
        raise RuntimeError(f"Dropbox create_folder error {r.status_code}: {r.text}")


def upload_file(
    access_token: str,
    dropbox_path: str,
    content_bytes: bytes,
    *,
    mode: str = "add",
    autorename: bool = True,
    mute: bool = False,
    timeout_s: int = 120,
) -> dict:
    """
    Upload a file to Dropbox.

    mode:
      - "add" (recommended for your use case: append files)
      - "overwrite" (if you ever want replacement behaviour later)

    Returns: Dropbox metadata dict for the uploaded file.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/octet-stream",
        "Dropbox-API-Arg": json.dumps(
            {
                "path": dropbox_path,
                "mode": mode,
                "autorename": autorename,
                "mute": mute,
                "strict_conflict": False,
            }
        ),
    }

    r = requests.post(UPLOAD_URL, headers=headers, data=content_bytes, timeout=timeout_s)
    if not r.ok:
        raise RuntimeError(f"Dropbox upload error {r.status_code}: {r.text}")

    return r.json()


def list_folder(access_token: str, dropbox_folder_path: str, timeout_s: int = 30) -> list[dict]:
    """
    List files in a Dropbox folder. Returns a list of entry dicts.
    If the folder doesn't exist, returns an empty list (so the UI stays clean).
    """
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {"path": dropbox_folder_path, "recursive": False, "include_deleted": False}

    r = requests.post(LIST_FOLDER_URL, headers=headers, json=payload, timeout=timeout_s)

    # If folder doesn't exist, Dropbox commonly returns 409; treat as "no files yet"
    if r.status_code == 409:
        return []

    if not r.ok:
        raise RuntimeError(f"Dropbox list_folder error {r.status_code}: {r.text}")

    data = r.json()
    entries = data.get("entries", [])
    return entries


def delete_path(access_token: str, dropbox_path: str, timeout_s: int = 30) -> None:
    """
    Delete a file (or folder) from Dropbox by path.
    """
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {"path": dropbox_path}

    r = requests.post(DELETE_URL, headers=headers, json=payload, timeout=timeout_s)

    # If it's already gone, Dropbox may return 409; treat as OK for idempotency
    if r.status_code == 409:
        return

    if not r.ok:
        raise RuntimeError(f"Dropbox delete error {r.status_code}: {r.text}")
def get_temporary_link(access_token: str, dropbox_path: str, timeout_s: int = 30) -> str:
    """
    Returns a short-lived HTTPS link to a Dropbox file.
    Ideal for opening PDFs in a new tab (avoids data: URL restrictions).
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {"path": dropbox_path}

    r = requests.post(TEMP_LINK_URL, headers=headers, json=payload, timeout=timeout_s)
    if not r.ok:
        raise RuntimeError(f"Dropbox get_temporary_link error {r.status_code}: {r.text}")

    data = r.json()
    link = data.get("link")
    if not link:
        raise RuntimeError("Dropbox get_temporary_link returned no link.")
    return link
