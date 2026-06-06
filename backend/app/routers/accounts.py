"""
accounts.py — Bind & manage Settrade accounts
==============================================
Each user can bind multiple Settrade Open-API accounts. Secrets are
encrypted at rest; one account is "active" at a time and drives all
trading endpoints.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import BrokerAccount, User
from ..schemas import (
    BrokerAccountCreate, BrokerAccountOut, BrokerAccountUpdate, TelegramConfig,
)
from ..security import decrypt, encrypt
from ..services import crud
from ..services.monitor import manager as monitor_manager
from ..services.settrade_manager import manager as settrade_manager
from ..services.telegram import set_notifier

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return f"{value[:2]}{'•' * (len(value) - 4)}{value[-2:]}"


def _to_out(acc: BrokerAccount) -> BrokerAccountOut:
    return BrokerAccountOut(
        id=acc.id, label=acc.label, broker_id=acc.broker_id,
        app_id_masked=_mask(acc.app_id), account_no=acc.account_no,
        account_type=acc.account_type, is_active=acc.is_active,
        has_pin=bool(acc.pin_enc), last_connected_at=acc.last_connected_at,
        created_at=acc.created_at,
    )


def _get_owned(db: Session, user: User, account_id: int) -> BrokerAccount:
    acc = db.get(BrokerAccount, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return acc


@router.get("", response_model=list[BrokerAccountOut])
def list_accounts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    accounts = db.scalars(
        select(BrokerAccount).where(BrokerAccount.user_id == user.id)
        .order_by(BrokerAccount.created_at.asc())
    )
    return [_to_out(a) for a in accounts]


@router.post("", response_model=BrokerAccountOut, status_code=201)
def create_account(payload: BrokerAccountCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    first = db.scalar(select(BrokerAccount).where(BrokerAccount.user_id == user.id)) is None
    acc = BrokerAccount(
        user_id=user.id, label=payload.label, broker_id=payload.broker_id,
        app_id=payload.app_id, app_secret_enc=encrypt(payload.app_secret),
        app_code=payload.app_code, account_no=payload.account_no,
        pin_enc=encrypt(payload.pin) if payload.pin else None,
        account_type=payload.account_type, is_active=first,  # first bound becomes active
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return _to_out(acc)


@router.patch("/{account_id}", response_model=BrokerAccountOut)
def update_account(account_id: int, payload: BrokerAccountUpdate,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    acc = _get_owned(db, user, account_id)
    data = payload.model_dump(exclude_unset=True)
    if "app_secret" in data:
        acc.app_secret_enc = encrypt(data.pop("app_secret"))
    if "pin" in data:
        pin = data.pop("pin")
        acc.pin_enc = encrypt(pin) if pin else None
    for field, value in data.items():
        setattr(acc, field, value)
    db.commit()
    settrade_manager.disconnect(acc.id)  # force reconnect with new creds
    db.refresh(acc)
    return _to_out(acc)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    acc = _get_owned(db, user, account_id)
    monitor_manager.stop_account(acc.id)
    settrade_manager.disconnect(acc.id)
    db.delete(acc)
    db.commit()


@router.post("/{account_id}/activate", response_model=BrokerAccountOut)
def activate_account(account_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Switch the active account. Only one active per user."""
    acc = _get_owned(db, user, account_id)
    for other in db.scalars(select(BrokerAccount).where(
            BrokerAccount.user_id == user.id, BrokerAccount.is_active.is_(True))):
        other.is_active = False
    acc.is_active = True
    db.commit()
    db.refresh(acc)
    return _to_out(acc)


@router.post("/{account_id}/connect")
def connect_account(account_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Authenticate against Settrade to verify the bound credentials."""
    acc = _get_owned(db, user, account_id)
    try:
        client = settrade_manager.connect(acc)
    except ImportError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "settrade-v2 not installed on the server")
    except Exception as e:  # noqa: BLE001
        crud.log_event(db, "ERROR", "accounts", f"connect failed: {e}",
                       user_id=user.id, account_id=acc.id)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Connection failed: {e}")

    acc.last_connected_at = datetime.utcnow()
    db.commit()
    crud.log_event(db, "INFO", "accounts", f"Connected account '{acc.label}'",
                   user_id=user.id, account_id=acc.id)
    return {
        "status": "ok",
        "equity": client.equity_ctx is not None,
        "derivatives": client.deriv_ctx is not None,
        "market_data": client.market_data_ctx is not None,
    }


@router.post("/{account_id}/telegram")
def configure_telegram(account_id: int, cfg: TelegramConfig,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    acc = _get_owned(db, user, account_id)
    notifier = set_notifier(acc.id, cfg.bot_token, cfg.chat_id)
    return {"status": "ok", "enabled": notifier.enabled}
