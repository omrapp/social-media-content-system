#!/usr/bin/env python3
"""
One-time helper: run OAuth2 flow and print YOUTUBE_REFRESH_TOKEN.

Usage:
  1. Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env (or export them)
  2. python -m backend.scripts.auth_youtube
  3. Browser opens — log in and authorize
  4. Copy the printed YOUTUBE_REFRESH_TOKEN into .env
"""
import os
import sys


SCOPES = ["https://www.googleapis.com/auth/youtube"]  # full scope: upload + playlist management
REDIRECT_PORT = 8090


def main() -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing dependency. Run: pip install google-auth-oauthlib")
        sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv()

    client_id = os.environ.get("YOUTUBE_CLIENT_ID") or input("YOUTUBE_CLIENT_ID: ").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET") or input("YOUTUBE_CLIENT_SECRET: ").strip()

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
    print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
