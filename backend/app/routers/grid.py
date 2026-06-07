"""
grid.py — Grid preview, deployment & session control
====================================================
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_active_account, get_current_user
from ..models import BrokerAccount, User
from ..schemas import (
    GridDeployRequest, GridLevelOut, GridPreviewOut, GridPreviewRequest,
    OrderOut, SessionOut,
)
from ..services import crud, portfolio as pf, trading
from ..services.grid_logic import (
    calculate_allocation_volume, generate_sell_ladder,
)
from ..services.market_rules import get_tick_size, tick_down
from ..services.monitor import manager as monitor_manager
from ..services.settrade_manager import manager as settrade_manager
from ..services.telegram import get_notifier

router = APIRouter(prefix="/api/grid", tags=["grid"])


def _client_for(account: BrokerAccount):
    try:
        return settrade_manager.get_or_connect(account)
    except ImportError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "settrade-v2 not installed on the server")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Connection failed: {e}")


def _holding_for(client, account: BrokerAccount, symbol: str):
    """Return (holding_volume, is_equity, market_price) for a symbol."""
    rows = pf.fetch_portfolio(client.equity_ctx, client.deriv_ctx)
    for r in rows:
        if r["symbol"] == symbol:
            return abs(int(r["volume"])), r["market_type"] == "equity", r["market_price"]
    # Not held — fall back to account's declared type, no market price.
    return 0, account.account_type == "equity", 0.0


def _build_preview(client, account: BrokerAccount, symbol: str, params) -> GridPreviewOut:
    holding, is_equity, mkt_price = _holding_for(client, account, symbol)

    last_price = pf.get_last_price(client.market_data_ctx, symbol) or mkt_price
    if not last_price or last_price <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Cannot determine price for {symbol}")

    atr_value = pf.calculate_atr(client.market_data_ctx, symbol, settings.atr_period)
    if atr_value <= 0:
        atr_value = last_price * 0.02  # fallback estimate

    alloc_volume = calculate_allocation_volume(holding, params.allocation_pct, is_equity)
    orders = generate_sell_ladder(
        symbol=symbol, last_price=last_price, atr_value=atr_value,
        total_volume=alloc_volume, is_equity=is_equity,
        grid_levels=params.grid_levels, ladder_weights=params.ladder_weights,
    )

    levels = []
    for o in orders:
        sell_price = float(o.price)
        spread = sell_price - last_price
        bb = float(tick_down(sell_price, params.buyback_ticks, is_equity, symbol))
        levels.append(GridLevelOut(
            level=o.grid_level, sell_price=sell_price, volume=o.volume,
            spread=round(spread, 4), spread_pct=round((spread / last_price) * 100, 4),
            buyback_price=bb, cashflow_per_unit=round(sell_price - bb, 4),
        ))

    price_range = (f"{float(orders[0].price):,.2f} — {float(orders[-1].price):,.2f}"
                   if orders else "N/A")
    return GridPreviewOut(
        symbol=symbol, market_type="equity" if is_equity else "derivative",
        last_price=last_price, atr_value=round(atr_value, 4),
        tick_size=float(get_tick_size(last_price, is_equity, symbol)),
        holding=holding, alloc_volume=alloc_volume,
        total_sell_volume=sum(o.volume for o in orders),
        price_range=price_range, levels=levels,
    )


@router.post("/preview", response_model=GridPreviewOut)
def preview(req: GridPreviewRequest, account: BrokerAccount = Depends(get_active_account),
            user: User = Depends(get_current_user)):
    client = _client_for(account)
    return _build_preview(client, account, req.symbol, req)


@router.post("/deploy", response_model=list[SessionOut])
def deploy(req: GridDeployRequest, db: Session = Depends(get_db),
           account: BrokerAccount = Depends(get_active_account),
           user: User = Depends(get_current_user)):
    if not req.symbols:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No symbols supplied")

    client = _client_for(account)
    notifier = get_notifier(account.id)
    notifier.bot_started(req.symbols)
    created: list[SessionOut] = []

    for symbol in req.symbols:
        preview_out = _build_preview(client, account, symbol, req)
        if not preview_out.levels:
            crud.log_event(db, "WARN", "grid", f"No grid levels for {symbol}; skipped",
                           user_id=user.id, account_id=account.id)
            continue

        is_equity = preview_out.market_type == "equity"
        trading_ctx = client.trading_ctx(is_equity)
        if trading_ctx is None:
            crud.log_event(db, "ERROR", "grid", f"No trading context for {symbol}",
                           user_id=user.id, account_id=account.id)
            continue

        orders = generate_sell_ladder(
            symbol=symbol, last_price=preview_out.last_price,
            atr_value=preview_out.atr_value, total_volume=preview_out.alloc_volume,
            is_equity=is_equity, grid_levels=req.grid_levels,
            ladder_weights=req.ladder_weights,
        )

        session_id = f"GS-{uuid.uuid4().hex[:8].upper()}"
        crud.create_session(
            db, session_id=session_id, user_id=user.id, account_id=account.id,
            symbol=symbol, market_type=preview_out.market_type,
            base_price=preview_out.last_price, atr_value=preview_out.atr_value,
            allocation_pct=req.allocation_pct, grid_levels=len(orders),
            config={"ladder_weights": req.ladder_weights,
                    "buyback_ticks": req.buyback_ticks,
                    "alloc_volume": preview_out.alloc_volume},
        )

        results = trading.place_sell_ladder(
            db, trading_ctx, session_id=session_id, account_id=account.id,
            orders=orders, is_equity=is_equity, pin=client.pin,
        )
        placed = sum(1 for r in results if r["status"] == "placed")
        failed = sum(1 for r in results if r["status"] == "failed")
        crud.log_event(db, "INFO", "grid",
                       f"{symbol}: {placed} placed, {failed} failed ({session_id})",
                       user_id=user.id, account_id=account.id, session_id=session_id)
        notifier.orders_placed(symbol, "SELL", placed, preview_out.price_range)

        monitor_manager.start(
            session_id=session_id, account_id=account.id, is_equity=is_equity,
            pin=client.pin, buyback_ticks=req.buyback_ticks,
        )
        created.append(_session_out(db, crud.get_session(db, session_id)))

    return created


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(db: Session = Depends(get_db),
                  account: BrokerAccount = Depends(get_active_account)):
    return [_session_out(db, s) for s in crud.get_sessions_for_account(db, account.id)]


@router.get("/sessions/{session_id}/orders", response_model=list[OrderOut])
def session_orders(session_id: str, db: Session = Depends(get_db),
                   account: BrokerAccount = Depends(get_active_account)):
    sess = crud.get_session(db, session_id)
    if not sess or sess.account_id != account.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return crud.get_orders_by_session(db, session_id)


@router.post("/sessions/{session_id}/stop")
def stop_session(session_id: str, db: Session = Depends(get_db),
                 account: BrokerAccount = Depends(get_active_account)):
    sess = _owned_session(db, account, session_id)
    monitor_manager.stop(session_id)
    crud.update_session_status(db, session_id, "paused")
    crud.log_event(db, "WARN", "grid", f"Session {session_id} paused", account_id=account.id)
    return {"status": "paused"}


@router.post("/sessions/{session_id}/cancel")
def cancel_session(session_id: str, db: Session = Depends(get_db),
                   account: BrokerAccount = Depends(get_active_account)):
    sess = _owned_session(db, account, session_id)
    client = _client_for(account)
    is_equity = sess.market_type == "equity"
    n = trading.cancel_session_orders(
        db, client.trading_ctx(is_equity), session_id=session_id, pin=client.pin)
    monitor_manager.stop(session_id)
    crud.update_session_status(db, session_id, "closed")
    crud.log_event(db, "WARN", "grid", f"Cancelled {n} orders for {session_id}",
                   account_id=account.id)
    return {"status": "closed", "cancelled": n}


@router.post("/stop-all")
def stop_all(db: Session = Depends(get_db),
             account: BrokerAccount = Depends(get_active_account)):
    monitor_manager.stop_account(account.id)
    for s in crud.get_active_sessions(db, account.id):
        crud.update_session_status(db, s.session_id, "paused")
    get_notifier(account.id).bot_stopped()
    return {"status": "stopped"}


# ─── helpers ───────────────────────────────────────────────────────

def _owned_session(db: Session, account: BrokerAccount, session_id: str):
    sess = crud.get_session(db, session_id)
    if not sess or sess.account_id != account.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return sess


def _session_out(db: Session, sess) -> SessionOut:
    pnl = crud.session_pnl(db, sess.session_id)
    return SessionOut(
        session_id=sess.session_id, symbol=sess.symbol, market_type=sess.market_type,
        status=sess.status, base_price=sess.base_price, atr_value=sess.atr_value,
        grid_levels=sess.grid_levels, created_at=sess.created_at,
        sells_matched=pnl["sells_matched"], buys_matched=pnl["buys_matched"],
        total_pnl=pnl["total_pnl"], orders_active=pnl["orders_active"],
    )
