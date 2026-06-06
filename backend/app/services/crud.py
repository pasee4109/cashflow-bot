"""
crud.py — Persistence helpers for sessions, orders & logs
=========================================================
All functions take an explicit SQLAlchemy Session so they work
both in request handlers and in background monitor threads.
"""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BotLog, GridOrder, GridSession


# ─── Sessions ──────────────────────────────────────────────────────

def create_session(db: Session, *, session_id: str, user_id: int, account_id: int,
                   symbol: str, market_type: str, base_price: float,
                   atr_value: float, allocation_pct: float, grid_levels: int,
                   config: dict) -> GridSession:
    sess = GridSession(
        session_id=session_id, user_id=user_id, account_id=account_id,
        symbol=symbol, market_type=market_type, base_price=base_price,
        atr_value=atr_value, allocation_pct=allocation_pct,
        grid_levels=grid_levels, status="active",
        config_json=json.dumps(config),
    )
    db.merge(sess)
    db.commit()
    return sess


def get_session(db: Session, session_id: str) -> GridSession | None:
    return db.get(GridSession, session_id)


def get_active_sessions(db: Session, account_id: int | None = None) -> list[GridSession]:
    stmt = select(GridSession).where(GridSession.status == "active")
    if account_id is not None:
        stmt = stmt.where(GridSession.account_id == account_id)
    return list(db.scalars(stmt))


def get_sessions_for_account(db: Session, account_id: int) -> list[GridSession]:
    return list(db.scalars(
        select(GridSession).where(GridSession.account_id == account_id)
        .order_by(GridSession.created_at.desc())
    ))


def update_session_status(db: Session, session_id: str, status: str) -> None:
    sess = db.get(GridSession, session_id)
    if sess:
        sess.status = status
        db.commit()


# ─── Orders ────────────────────────────────────────────────────────

def upsert_order(db: Session, *, order_id: str, session_id: str, account_id: int,
                 symbol: str, side: str, price: float, volume: int,
                 grid_level: int = 0, parent_order: str | None = None,
                 broker_order_no: str | None = None, status: str = "pending") -> None:
    existing = db.get(GridOrder, order_id)
    if existing:
        existing.status = status
        if broker_order_no:
            existing.broker_order_no = broker_order_no
    else:
        db.add(GridOrder(
            order_id=order_id, session_id=session_id, account_id=account_id,
            symbol=symbol, side=side, price=price, volume=volume,
            grid_level=grid_level, parent_order=parent_order,
            broker_order_no=broker_order_no, status=status,
        ))
    db.commit()


def update_order_status(db: Session, order_id: str, status: str, *,
                        broker_order_no: str | None = None,
                        matched_price: float | None = None,
                        matched_volume: int | None = None,
                        pnl: float | None = None) -> None:
    order = db.get(GridOrder, order_id)
    if not order:
        return
    order.status = status
    if broker_order_no:
        order.broker_order_no = broker_order_no
    if matched_price is not None:
        order.matched_price = matched_price
    if matched_volume is not None:
        order.matched_volume = matched_volume
    if pnl is not None:
        order.pnl = pnl
    db.commit()


def get_orders_by_session(db: Session, session_id: str,
                          status: str | None = None) -> list[GridOrder]:
    stmt = select(GridOrder).where(GridOrder.session_id == session_id)
    if status:
        stmt = stmt.where(GridOrder.status == status)
    return list(db.scalars(stmt))


def get_placed_sell_orders(db: Session, session_id: str) -> list[GridOrder]:
    return list(db.scalars(
        select(GridOrder).where(
            GridOrder.session_id == session_id,
            GridOrder.side == "SELL", GridOrder.status == "placed",
        ).order_by(GridOrder.price.asc())
    ))


def get_placed_buy_orders(db: Session, session_id: str) -> list[GridOrder]:
    return list(db.scalars(
        select(GridOrder).where(
            GridOrder.session_id == session_id,
            GridOrder.side == "BUY", GridOrder.status == "placed",
        ).order_by(GridOrder.price.desc())
    ))


def session_pnl(db: Session, session_id: str) -> dict[str, Any]:
    orders = get_orders_by_session(db, session_id)
    return {
        "sells_matched": sum(1 for o in orders if o.side == "SELL" and o.status == "matched"),
        "buys_matched": sum(1 for o in orders if o.side == "BUY" and o.status == "matched"),
        "total_pnl": sum(o.pnl or 0.0 for o in orders),
        "orders_active": sum(1 for o in orders if o.status == "placed"),
    }


# ─── Logs ──────────────────────────────────────────────────────────

def log_event(db: Session, level: str, source: str, message: str, *,
              user_id: int | None = None, account_id: int | None = None,
              session_id: str | None = None) -> None:
    db.add(BotLog(
        level=level, source=source, message=message,
        user_id=user_id, account_id=account_id, session_id=session_id,
    ))
    db.commit()


def recent_logs(db: Session, *, account_id: int | None = None,
                limit: int = 200) -> list[BotLog]:
    stmt = select(BotLog).order_by(BotLog.id.desc()).limit(limit)
    if account_id is not None:
        stmt = select(BotLog).where(BotLog.account_id == account_id) \
            .order_by(BotLog.id.desc()).limit(limit)
    return list(db.scalars(stmt))
