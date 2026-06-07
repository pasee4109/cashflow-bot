"""
trading.py — Order placement, cancellation & polling
====================================================
Bridges the pure grid logic to the Settrade API and persists
every order through the crud layer. DB-session aware so it runs
inside both request handlers and the background monitor.
"""

import logging

from sqlalchemy.orm import Session

from . import crud
from .grid_logic import (
    GridOrder, extract_order_no, generate_buyback_order, normalize_status,
)

logger = logging.getLogger(__name__)


def _place(trading_ctx, *, pin: str, symbol: str, side: str, price: float,
           volume: int, is_equity: bool):
    """Submit one limit order. TFEX uses LONG/SHORT, equity uses BUY/SELL."""
    if is_equity:
        api_side = side  # BUY / SELL
    else:
        api_side = "LONG" if side == "BUY" else "SHORT"
    return trading_ctx.place_order(
        pin=pin, symbol=symbol, side=api_side, price=price,
        volume=volume, price_type="LIMIT", validity_type="DAY",
    )


def place_sell_ladder(db: Session, trading_ctx, *, session_id: str, account_id: int,
                      orders: list[GridOrder], is_equity: bool, pin: str) -> list[dict]:
    results = []
    for order in orders:
        try:
            resp = _place(trading_ctx, pin=pin, symbol=order.symbol, side="SELL",
                          price=float(order.price), volume=order.volume, is_equity=is_equity)
            broker_no = extract_order_no(resp)
            order.broker_order_no = broker_no
            crud.upsert_order(
                db, order_id=order.order_id, session_id=session_id, account_id=account_id,
                symbol=order.symbol, side="SELL", price=float(order.price),
                volume=order.volume, grid_level=order.grid_level,
                broker_order_no=broker_no, status="placed",
            )
            results.append({"order_id": order.order_id, "status": "placed",
                            "broker_no": broker_no, "price": float(order.price),
                            "volume": order.volume, "level": order.grid_level})
            logger.info("SELL placed %s L%s @ %s x%s [%s]",
                        order.symbol, order.grid_level, order.price, order.volume, broker_no)
        except Exception as e:  # noqa: BLE001
            crud.upsert_order(
                db, order_id=order.order_id, session_id=session_id, account_id=account_id,
                symbol=order.symbol, side="SELL", price=float(order.price),
                volume=order.volume, grid_level=order.grid_level, status="failed",
            )
            crud.log_event(db, "ERROR", "trading", f"SELL place failed {order.symbol}: {e}",
                           account_id=account_id, session_id=session_id)
            results.append({"order_id": order.order_id, "status": "failed", "error": str(e)})
    return results


def place_buyback_order(db: Session, trading_ctx, *, session_id: str, account_id: int,
                        order: GridOrder, is_equity: bool, pin: str) -> dict:
    try:
        resp = _place(trading_ctx, pin=pin, symbol=order.symbol, side="BUY",
                      price=float(order.price), volume=order.volume, is_equity=is_equity)
        broker_no = extract_order_no(resp)
        order.broker_order_no = broker_no
        crud.upsert_order(
            db, order_id=order.order_id, session_id=session_id, account_id=account_id,
            symbol=order.symbol, side="BUY", price=float(order.price),
            volume=order.volume, parent_order=order.parent_order,
            broker_order_no=broker_no, status="placed",
        )
        logger.info("BUY placed %s @ %s x%s [%s]", order.symbol, order.price, order.volume, broker_no)
        return {"order_id": order.order_id, "status": "placed", "broker_no": broker_no}
    except Exception as e:  # noqa: BLE001
        crud.log_event(db, "ERROR", "trading", f"BUY place failed {order.symbol}: {e}",
                       account_id=account_id, session_id=session_id)
        return {"order_id": order.order_id, "status": "failed", "error": str(e)}


def cancel_session_orders(db: Session, trading_ctx, *, session_id: str, pin: str) -> int:
    cancelled = 0
    for order in crud.get_orders_by_session(db, session_id, status="placed"):
        if not order.broker_order_no:
            continue
        try:
            trading_ctx.cancel_order(pin=pin, order_no=order.broker_order_no)
            crud.update_order_status(db, order.order_id, "cancelled")
            cancelled += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("cancel failed %s: %s", order.broker_order_no, e)
    return cancelled


def _check_status(trading_ctx, broker_order_no: str) -> dict:
    try:
        status = trading_ctx.get_order(order_no=broker_order_no)
        if isinstance(status, dict):
            return status
        return {
            "status": getattr(status, "status", "unknown"),
            "matched_vol": getattr(status, "matched_vol",
                                   getattr(status, "matched_volume", 0)),
            "matched_price": getattr(status, "matched_price", 0),
        }
    except Exception as e:  # noqa: BLE001
        logger.error("status check failed %s: %s", broker_order_no, e)
        return {"status": "error", "error": str(e)}


def poll_and_process(db: Session, trading_ctx, *, session_id: str, account_id: int,
                     is_equity: bool, pin: str, buyback_ticks: int, notifier=None) -> list[dict]:
    """Detect fills; trigger buybacks on sells; book PnL on buys."""
    events: list[dict] = []

    for sell in crud.get_placed_sell_orders(db, session_id):
        if not sell.broker_order_no:
            continue
        info = _check_status(trading_ctx, sell.broker_order_no)
        if normalize_status(info.get("status", "")) != "matched":
            continue

        matched_price = float(info.get("matched_price", info.get("matchedPrice", sell.price)))
        matched_vol = int(info.get("matched_vol",
                          info.get("matchedVol", info.get("matched_volume", sell.volume))))
        crud.update_order_status(db, sell.order_id, "matched",
                                 matched_price=matched_price, matched_volume=matched_vol)
        crud.log_event(db, "INFO", "trading",
                       f"SELL MATCHED {sell.symbol} @ {matched_price} x{matched_vol}",
                       account_id=account_id, session_id=session_id)

        buyback = generate_buyback_order(
            {"symbol": sell.symbol, "order_id": sell.order_id, "price": sell.price,
             "volume": sell.volume, "matched_price": matched_price,
             "matched_volume": matched_vol},
            buyback_ticks=buyback_ticks, is_equity=is_equity,
        )
        result = place_buyback_order(db, trading_ctx, session_id=session_id,
                                     account_id=account_id, order=buyback,
                                     is_equity=is_equity, pin=pin)
        events.append({"type": "sell_matched", "symbol": sell.symbol,
                       "price": matched_price, "volume": matched_vol,
                       "buyback_price": float(buyback.price),
                       "buyback_status": result["status"]})
        if notifier:
            notifier.order_matched(sell.symbol, "SELL", matched_price, matched_vol)
            if result["status"] == "placed":
                notifier.buyback_triggered(sell.symbol, matched_price,
                                           float(buyback.price), buyback.volume)

    for buy in crud.get_placed_buy_orders(db, session_id):
        if not buy.broker_order_no:
            continue
        info = _check_status(trading_ctx, buy.broker_order_no)
        if normalize_status(info.get("status", "")) != "matched":
            continue

        matched_price = float(info.get("matched_price", info.get("matchedPrice", buy.price)))
        matched_vol = int(info.get("matched_vol",
                          info.get("matchedVol", info.get("matched_volume", buy.volume))))
        pnl = 0.0
        if buy.parent_order:
            parent = next((o for o in crud.get_orders_by_session(db, session_id)
                           if o.order_id == buy.parent_order), None)
            if parent and parent.matched_price:
                pnl = (parent.matched_price - matched_price) * matched_vol
        crud.update_order_status(db, buy.order_id, "matched",
                                 matched_price=matched_price, matched_volume=matched_vol, pnl=pnl)
        crud.log_event(db, "INFO", "trading",
                       f"BUY MATCHED {buy.symbol} @ {matched_price} x{matched_vol} PnL {pnl:+,.2f}",
                       account_id=account_id, session_id=session_id)
        events.append({"type": "buy_matched", "symbol": buy.symbol,
                       "price": matched_price, "volume": matched_vol, "pnl": pnl})
        if notifier:
            notifier.order_matched(buy.symbol, "BUY", matched_price, matched_vol, pnl)

    return events
