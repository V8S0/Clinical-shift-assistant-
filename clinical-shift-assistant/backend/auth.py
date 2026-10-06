from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


DEMO_USERNAME = "nurse"
DEMO_PASSWORD = "Nurse123!"

SESSION_DURATION_MINUTES = 60

active_sessions: dict[str, datetime] = {}

security = HTTPBearer()


def authenticate_user(username: str, password: str) -> str:
    if username != DEMO_USERNAME or password != DEMO_PASSWORD:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
        )

    token = token_urlsafe(32)

    active_sessions[token] = (
        datetime.now(timezone.utc)
        + timedelta(minutes=SESSION_DURATION_MINUTES)
    )

    return token


def verify_session(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    token = credentials.credentials

    expires_at = active_sessions.get(token)

    if expires_at is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid session",
        )

    if datetime.now(timezone.utc) >= expires_at:
        active_sessions.pop(token, None)

        raise HTTPException(
            status_code=401,
            detail="Session expired",
        )

    return token


def logout_user(token: str) -> None:
    active_sessions.pop(token, None)