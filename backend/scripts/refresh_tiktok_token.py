#!/usr/bin/env python3
"""
Refresh TikTok access token using the stored refresh token.
Run from a cron job every 23h:
  0 */23 * * * cd /srv/social-media-cms && python -m backend.scripts.refresh_tiktok_token >> logs/tiktok_refresh.log 2>&1

Reads TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN from .env.
Writes new TIKTOK_ACCESS_TOKEN and TIKTOK_REFRESH_TOKEN back to .env.
"""
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


def _update_env(key: str, value: str) -> None:
    text = ENV_FILE.read_text()
    pattern = rf"^{re.escape(key)}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, text, re.MULTILINE):
        text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + f"\n{replacement}\n"
    ENV_FILE.write_text(text)


def main() -> None:
    load_dotenv(ENV_FILE)

    client_key = os.environ.get("TIKTOK_CLIENT_KEY", "")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    refresh_token = os.environ.get("TIKTOK_REFRESH_TOKEN", "")

    if not all([client_key, client_secret, refresh_token]):
        print("Missing TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET / TIKTOK_REFRESH_TOKEN")
        sys.exit(1)

    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=15,
    ).json()

    if not resp.get("access_token"):
        print(f"Refresh failed: {resp}")
        sys.exit(1)

    _update_env("TIKTOK_ACCESS_TOKEN", resp["access_token"])
    if resp.get("refresh_token"):
        _update_env("TIKTOK_REFRESH_TOKEN", resp["refresh_token"])

    print(f"TikTok token refreshed. New access token expires in {resp.get('expires_in', '?')}s")


if __name__ == "__main__":
    main()
