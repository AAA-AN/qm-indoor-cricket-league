from __future__ import annotations

import json
import requests

TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
DOWNLOAD_URL = "https://content.dropboxapi.com/2/files/download"


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
