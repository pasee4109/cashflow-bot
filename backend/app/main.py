"""
main.py — FastAPI application entrypoint
========================================
Run: uvicorn app.main:app --reload  (from the backend/ directory)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .database import SessionLocal, init_db
from .models import BrokerAccount, GridSession
from .routers import accounts, auth, grid, logs, portfolio
from .services.monitor import manager as monitor_manager
from .services.settrade_manager import manager as settrade_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cashflow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _resume_active_sessions()
    yield


app = FastAPI(title=settings.app_name, version="2.0.0", lifespan=lifespan)

# Authlib stores the OAuth state in this signed session cookie.
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key,
                   same_site=settings.cookie_samesite, https_only=settings.cookie_secure)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(portfolio.router)
app.include_router(grid.router)
app.include_router(logs.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.app_name,
            "google_enabled": settings.google_enabled,
            "active_monitors": monitor_manager.active_count()}


def _resume_active_sessions():
    """Reconnect accounts and restart monitors for sessions left active."""
    db = SessionLocal()
    try:
        active = db.query(GridSession).filter(GridSession.status == "active").all()
        for sess in active:
            account = db.get(BrokerAccount, sess.account_id)
            if not account:
                continue
            try:
                client = settrade_manager.get_or_connect(account)
            except Exception as e:  # noqa: BLE001
                logger.warning("Could not resume session %s: %s", sess.session_id, e)
                continue
            monitor_manager.start(
                session_id=sess.session_id, account_id=account.id,
                is_equity=sess.market_type == "equity",
                pin=client.pin, buyback_ticks=_buyback_ticks(sess),
            )
            logger.info("Resumed monitor for %s", sess.session_id)
    finally:
        db.close()


def _buyback_ticks(sess: GridSession) -> int:
    import json
    try:
        return int(json.loads(sess.config_json or "{}").get(
            "buyback_ticks", settings.default_buyback_ticks))
    except Exception:  # noqa: BLE001
        return settings.default_buyback_ticks
