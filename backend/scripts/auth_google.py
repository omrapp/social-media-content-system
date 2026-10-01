#!/usr/bin/env python3
"""
One-time helper: run OAuth2 flow and print GOOGLE_REFRESH_TOKEN.

Mints a single refresh token for the account owner, used by the Download page
Google Drive + Google Photos import feature (backend/pipeline/google_import.py).

Scopes:
  - drive.readonly                 — list + download the owner's Drive videos
  - photospicker.mediaitems.readonly — Google Photos Picker API (the classic
    Library list API was restricted for third-party apps in 2025; the Picker is
    the supported path to read user-selected Photos media)

Usage:
  1. In Google Cloud: create an OAuth client (Desktop app), enable the Drive API
     and the Photos Picker API.
  2. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env (or export them).
  3. python -m backend.scripts.auth_google
  4. Browser opens — log in and authorize both scopes.
  5. Copy the printed GOOGLE_REFRESH_TOKEN into .env.
"""
import os
import sys


SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/photospicker.mediaitems.readonly",
]
REDIRECT_PORT = 8091


def main() -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing dependency. Run: pip install google-auth-oauthlib")
        sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv()

    client_id = os.environ.get("GOOGLE_CLIENT_ID") or input("GOOGLE_CLIENT_ID: ").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET") or input("GOOGLE_CLIENT_SECRET: ").strip()

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [f"http://localhost:{REDIRECT_PORT}"],
            }
        },
        scopes=SCOPES,
    )
    creds = flow.run_local_server(port=REDIRECT_PORT, access_type="offline", prompt="consent")

    print("\n✓ Authorization complete. Add to .env:\n")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
