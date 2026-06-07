"""
deps.py — Shared FastAPI dependencies
=====================================
Resolves the current user from the JWT cookie (or Bearer header),
and the user's currently-active broker account.
"""

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import BrokerAccount, User
from .security import decode_access_token

ACCESS_COOKIE = "access_token"


def get_current_user(
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> User:
    token = access_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]

    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    user = db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


def get_active_account(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BrokerAccount:
    account = db.scalar(
        select(BrokerAccount).where(
            BrokerAccount.user_id == user.id,
            BrokerAccount.is_active.is_(True),
        )
    )
    if not account:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No active broker account. Bind and select a Settrade account first.",
        )
    return account
