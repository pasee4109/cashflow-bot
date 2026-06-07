"""
auth.py — Authentication routes
===============================
Google OIDC sign-in (Authlib) plus an optional dev login for local
use before Google credentials are configured. A successful login
issues a JWT stored in an httpOnly cookie.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import ACCESS_COOKIE, get_current_user
from ..models import User
from ..oauth import oauth
from ..schemas import UserOut
from ..security import create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE, token, httponly=True,
        secure=settings.cookie_secure, samesite=settings.cookie_samesite,
        max_age=settings.jwt_expire_minutes * 60, path="/",
    )


def _upsert_user(db: Session, *, sub: str | None, email: str,
                 name: str | None, picture: str | None) -> User:
    user = None
    if sub:
        user = db.scalar(select(User).where(User.google_sub == sub))
    if not user:
        user = db.scalar(select(User).where(User.email == email))
    if user:
        user.google_sub = sub or user.google_sub
        user.name = name or user.name
        user.picture = picture or user.picture
    else:
        user = User(google_sub=sub, email=email, name=name, picture=picture)
        db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/config")
def auth_config():
    """Tells the frontend which login methods are available."""
    return {"google_enabled": settings.google_enabled,
            "dev_login_enabled": settings.allow_dev_login}


@router.get("/google/login")
async def google_login(request: Request):
    if not settings.google_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google login not configured")
    return await oauth.google.authorize_redirect(request, settings.oauth_redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    if not settings.google_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google login not configured")
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"OAuth failed: {e}")

    info = token.get("userinfo") or {}
    if not info.get("email"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google account has no email")

    user = _upsert_user(db, sub=info.get("sub"), email=info["email"],
                        name=info.get("name"), picture=info.get("picture"))
    access = create_access_token(user.id)

    response = RedirectResponse(url=settings.frontend_url)
    _set_cookie(response, access)
    return response


@router.post("/dev-login")
def dev_login(response: Response, email: str = "dev@example.com",
              db: Session = Depends(get_db)):
    """Local-only shortcut. Disabled unless ALLOW_DEV_LOGIN is true."""
    if not settings.allow_dev_login:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Dev login disabled")
    user = _upsert_user(db, sub=None, email=email, name="Dev User", picture=None)
    _set_cookie(response, create_access_token(user.id))
    return {"status": "ok", "user": UserOut.model_validate(user)}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(ACCESS_COOKIE, path="/")
    return {"status": "ok"}
