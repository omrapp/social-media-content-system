#!/usr/bin/env python3
"""
One-time helper: exchange TikTok authorization code for access + refresh tokens.

Usage:
  1. Create a TikTok for Developers app with scope: video.publish,video.upload
  2. Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET in .env (or export them)
  3. python -m backend.scripts.auth_tiktok
  4. Open the printed URL, authorize, paste the code parameter back
  5. Add printed tokens to .env

Note: TikTok access tokens expire every 24h. The refresh token lasts 365 days.
Add a cron job or systemd timer to refresh: python -m backend.scripts.refresh_tiktok_token
"""
import base64
import hashlib
import os
import secrets
import sys
import urllib.parse

import httpx

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
AUTH_BASE = "https://www.tiktok.com/v2/auth/authorize/"
SCOPE = "video.publish,video.upload"


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    client_key = os.environ.get("TIKTOK_CLIENT_KEY") or input("TIKTOK_CLIENT_KEY: ").strip()
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET") or input("TIKTOK_CLIENT_SECRET: ").strip()
    redirect_uri = input("Redirect URI (must match TikTok app config, e.g. https://yourdomain.com/callback): ").strip()

    state = secrets.token_urlsafe(16)

    # PKCE: TikTok requires code_challenge for web/desktop apps.
    code_verifier = secrets.token_urlsafe(64)[:128]
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")

    auth_url = AUTH_BASE + "?" + urllib.parse.urlencode({
        "client_key": client_key,
        "scope": SCOPE,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })

    print(f"\n1. Open this URL in a browser:\n\n   {auth_url}\n")
    print("2. Log in and authorize the app.")
    print("3. You'll be redirected — copy the `code` query parameter from the URL.\n")

    code = input("Paste authorization code: ").strip()

    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        timeout=15,
    ).json()

    if "error" in resp or not resp.get("access_token"):
        print(f"\nError from TikTok: {resp}")
        sys.exit(1)

    expires_in = resp.get("expires_in", "?")
    refresh_expires = resp.get("refresh_expires_in", "?")

    print("\n✓ Authorization complete. Add to .env:\n")
    print(f"TIKTOK_ACCESS_TOKEN={resp['access_token']}")
    if resp.get("refresh_token"):
        print(f"TIKTOK_REFRESH_TOKEN={resp['refresh_token']}")
    print(f"\nAccess token expires in: {expires_in}s (~24h)")
    print(f"Refresh token expires in: {refresh_expires}s (~365 days)")
    print("\nSet up token refresh: python -m backend.scripts.refresh_tiktok_token")


if __name__ == "__main__":
    main()
