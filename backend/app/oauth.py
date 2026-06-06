"""
oauth.py — Google OIDC client (Authlib)
=======================================
"""

from authlib.integrations.starlette_client import OAuth

from .config import settings

oauth = OAuth()

if settings.google_enabled:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
