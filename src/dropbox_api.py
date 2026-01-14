from __future__ import annotations

import requests


TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
DOWNLOAD_URL = "https://content.dropboxapi.com/2/files/download"


def get_access_token(app_key: str, app_secret: str, refresh_token: str, timeout_s: int = 30) -> str:
    """
    Exchange refresh token for a short-lived access token.
    """
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": app_key,
        "client_secret": app_secret,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=timeout_s)
    r.raise_for_status()
    payload = r.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Dropbox token response missing access_token.")
    return token


def download_file(access_token: str, dropbox_path: str, timeout_s: int = 60) -> bytes:
    """
    Download a file from Dropbox by path using /2/files/download.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Dropbox-API-Arg": f'{{"path": "{dropbox_path}"}}',
    }
    r = requests.post(DOWNLOAD_URL, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    return r.content
