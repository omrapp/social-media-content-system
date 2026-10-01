import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import PyJWKClient

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
ALGORITHM = "HS256"

security = HTTPBearer()

# Cache keyed by URL so tests that patch SUPABASE_URL get a fresh client
_jwks_cache: dict[str, PyJWKClient] = {}


def _jwks_client() -> PyJWKClient | None:
    if not SUPABASE_URL:
        return None
    if SUPABASE_URL not in _jwks_cache:
        _jwks_cache[SUPABASE_URL] = PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")
    return _jwks_cache[SUPABASE_URL]


def _decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises jwt.InvalidTokenError on failure."""
    alg = jwt.get_unverified_header(token).get("alg", "HS256")
    if alg == "ES256":
        client = _jwks_client()
        if not client:
            raise jwt.InvalidTokenError("SUPABASE_URL not configured")
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key, algorithms=["ES256"], audience="authenticated")
    return jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    if not SUPABASE_JWT_SECRET and not SUPABASE_URL:
        return {"sub": "dev", "role": "authenticated"}

    token = credentials.credentials

    try:
        alg = jwt.get_unverified_header(token).get("alg", "HS256")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        return _decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def verify_ws_token(token: str | None) -> bool:
    """Validate a raw JWT string for WebSocket connections. Returns True on success."""
    if not SUPABASE_JWT_SECRET and not SUPABASE_URL:
        return True  # dev mode — no auth configured
    if not token:
        return False
    try:
        _decode_token(token)
        return True
    except jwt.InvalidTokenError:
        return False
