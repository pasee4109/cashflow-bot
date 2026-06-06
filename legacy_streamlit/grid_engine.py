"""
grid_engine.py — Cashflow Ladder Grid Engine
==============================================
Computes grid levels, generates orders, executes via
Settrade API, and manages the buy-back cycle.
"""

import uuid
import logging
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from market_rules import (
    tick_up, tick_down, normalize_volume,
    snap_price_to_tick, get_equity_tick_size, get_tfex_tick_size,
    count_ticks_in_range,
)
from config import (
    DEFAULT_GRID_LEVELS, DEFAULT_LADDER_WEIGHTS,
    DEFAULT_BUYBACK_TICKS, ATR_GRID_LIMIT,
)
import state_manager as sm

logger = logging.getLogger(__name__)


class GridOrder:
    """Represents a single grid order."""
    def __init__(self, symbol: str, side: str, price: Decimal,
                 volume: int, grid_level: int = 0,
                 parent_order: str = None):
        self.order_id = f"GL-{uuid.uuid4().hex[:8].upper()}"
        self.symbol = symbol
        self.side = side
        self.price = price
        self.volume = volume
        self.grid_level = grid_level
        self.parent_order = parent_order
        self.broker_order_no = None
        self.status = "pending"

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "price": float(self.price),
            "volume": self.volume,
            "grid_level": self.grid_level,
            "parent_order": self.parent_order,
            "status": self.status,
        }


def generate_sell_ladder(
    symbol: str,
    last_price: float,
    atr_value: float,
    total_volume: int,
    is_equity: bool = True,
    grid_levels: int = DEFAULT_GRID_LEVELS,
    ladder_weights: List[int] = None,
) -> List[GridOrder]:
    """
    Generate laddered sell orders above the current price.

    Strategy:
    - Place sells at incremental ticks above last_price
    - Cap at +1 ATR from last_price
    - Volume distribution: increasing (1x, 2x, 3x, 4x, 5x)
    - All volumes normalized to board lots / contracts

    Returns list of GridOrder objects.
    """
    if ladder_weights is None:
        ladder_weights = DEFAULT_LADDER_WEIGHTS[:grid_levels]

    # Ensure we have the right number of weights
    while len(ladder_weights) < grid_levels:
        ladder_weights.append(ladder_weights[-1] + 1)
    ladder_weights = ladder_weights[:grid_levels]

    # Calculate ATR ceiling
    atr_ceiling = last_price + (atr_value * ATR_GRID_LIMIT)

    # Count available ticks in the range
    total_ticks = count_ticks_in_range(
        last_price, atr_ceiling, is_equity, symbol
    )

    if total_ticks < grid_levels:
        # Not enough room — compress grid
        grid_levels = max(1, total_ticks)
        ladder_weights = ladder_weights[:grid_levels]

    # Calculate tick spacing between levels
    ticks_per_level = max(1, total_ticks // grid_levels)

    # Distribute volume by weights
    weight_sum = sum(ladder_weights)
    orders: List[GridOrder] = []

    for i, weight in enumerate(ladder_weights):
        level = i + 1

        # Price = base + (level * ticks_per_level) ticks up
        n_ticks = level * ticks_per_level
        price = tick_up(last_price, n_ticks, is_equity, symbol)

        # Cap at ATR ceiling
        if float(price) > atr_ceiling:
            price = snap_price_to_tick(
                atr_ceiling, "down", is_equity, symbol
            )

        # Volume for this level
        raw_vol = (weight / weight_sum) * total_volume
        vol = normalize_volume(raw_vol, is_equity)

        order = GridOrder(
            symbol=symbol,
            side="SELL",
            price=price,
            volume=vol,
            grid_level=level,
        )
        orders.append(order)

    # Verify total volume doesn't exceed allocation
    total_allocated = sum(o.volume for o in orders)
    if total_allocated > total_volume:
        _trim_excess_volume(orders, total_volume, is_equity)

    return orders


def generate_buyback_order(
    sell_order: Dict,
    buyback_ticks: int = DEFAULT_BUYBACK_TICKS,
    is_equity: bool = True,
) -> GridOrder:
    """
    Generate a buy-back order below the sell execution price.
    Uses the matched price (or placed price) to compute entry.
    """
    exec_price = sell_order.get("matched_price") or sell_order["price"]
    exec_vol = sell_order.get("matched_volume") or sell_order["volume"]

    buy_price = tick_down(
        exec_price, buyback_ticks,
        is_equity, sell_order["symbol"]
    )

    volume = normalize_volume(exec_vol, is_equity)

    order = GridOrder(
        symbol=sell_order["symbol"],
        side="BUY",
        price=buy_price,
        volume=volume,
        parent_order=sell_order["order_id"],
    )
    return order


def calculate_allocation_volume(
    total_holding: int,
    allocation_pct: float,
    is_equity: bool = True,
) -> int:
    """
    Calculate the volume to use based on allocation percentage.
    Returns normalized volume.
    """
    raw = total_holding * (allocation_pct / 100.0)
    return normalize_volume(raw, is_equity)


# ─── Execution Layer ───────────────────────────────────────────────

def place_sell_ladder(
    trading_ctx,
    session_id: str,
    orders: List[GridOrder],
    is_equity: bool = True,
    pin: str = "",
) -> List[Dict]:
    """
    Place all sell ladder orders via Settrade API.
    Persists each order to state DB.
    """
    results = []

    for order in orders:
        try:
            if is_equity:
                resp = trading_ctx.place_order(
                    pin=pin,
                    symbol=order.symbol,
                    side="SELL",
                    price=float(order.price),
                    volume=order.volume,
                    price_type="LIMIT",
                    validity_type="DAY",
                )
            else:
                resp = trading_ctx.place_order(
                    pin=pin,
                    symbol=order.symbol,
                    side="SHORT",  # TFEX short sell
                    price=float(order.price),
                    volume=order.volume,
                    price_type="LIMIT",
                    validity_type="DAY",
                )

            # Parse response
            broker_no = _extract_order_no(resp)
            order.broker_order_no = broker_no
            order.status = "placed"

            # Persist
            sm.upsert_order(
                order_id=order.order_id,
                session_id=session_id,
                symbol=order.symbol,
                side="SELL",
                price=float(order.price),
                volume=order.volume,
                grid_level=order.grid_level,
                broker_order_no=broker_no,
                status="placed",
            )

            results.append({
                "order_id": order.order_id,
                "broker_no": broker_no,
                "status": "placed",
                "price": float(order.price),
                "volume": order.volume,
                "level": order.grid_level,
            })

            logger.info(
                f"SELL placed: {order.symbol} "
                f"L{order.grid_level} @ {order.price} × {order.volume} "
                f"[{broker_no}]"
            )

        except Exception as e:
            order.status = "failed"
            sm.upsert_order(
                order_id=order.order_id,
                session_id=session_id,
                symbol=order.symbol,
                side="SELL",
                price=float(order.price),
                volume=order.volume,
                grid_level=order.grid_level,
                status="failed",
            )
            sm.log_event("ERROR", "grid_engine",
                         f"SELL place failed {order.symbol}: {e}")
            results.append({
                "order_id": order.order_id,
                "status": "failed",
                "error": str(e),
            })

    return results


def place_buyback_order(
    trading_ctx,
    session_id: str,
    order: GridOrder,
    is_equity: bool = True,
    pin: str = "",
) -> Dict:
    """Place a single buyback (BUY) order."""
    try:
        if is_equity:
            resp = trading_ctx.place_order(
                pin=pin,
                symbol=order.symbol,
                side="BUY",
                price=float(order.price),
                volume=order.volume,
                price_type="LIMIT",
                validity_type="DAY",
            )
        else:
            resp = trading_ctx.place_order(
                pin=pin,
                symbol=order.symbol,
                side="LONG",
                price=float(order.price),
                volume=order.volume,
                price_type="LIMIT",
                validity_type="DAY",
            )

        broker_no = _extract_order_no(resp)
        order.broker_order_no = broker_no
        order.status = "placed"

        sm.upsert_order(
            order_id=order.order_id,
            session_id=session_id,
            symbol=order.symbol,
            side="BUY",
            price=float(order.price),
            volume=order.volume,
            parent_order=order.parent_order,
            broker_order_no=broker_no,
            status="placed",
        )

        logger.info(
            f"BUY placed: {order.symbol} "
            f"@ {order.price} × {order.volume} "
            f"[{broker_no}] (parent: {order.parent_order})"
        )

        return {
            "order_id": order.order_id,
            "broker_no": broker_no,
            "status": "placed",
            "price": float(order.price),
            "volume": order.volume,
        }

    except Exception as e:
        sm.log_event("ERROR", "grid_engine",
                     f"BUY place failed {order.symbol}: {e}")
        return {"order_id": order.order_id, "status": "failed",
                "error": str(e)}


def cancel_session_orders(
    trading_ctx,
    session_id: str,
    is_equity: bool = True,
    pin: str = "",
) -> int:
    """Cancel all open orders for a session."""
    placed = sm.get_orders_by_session(session_id, status="placed")
    cancelled = 0

    for order in placed:
        broker_no = order.get("broker_order_no")
        if not broker_no:
            continue
        try:
            trading_ctx.cancel_order(
                pin=pin,
                order_no=broker_no,
            )
            sm.update_order_status(order["order_id"], "cancelled")
            cancelled += 1
        except Exception as e:
            logger.warning(f"Cancel failed for {broker_no}: {e}")

    return cancelled


# ─── Order Status Checking ─────────────────────────────────────────

def check_order_status(
    trading_ctx,
    broker_order_no: str,
) -> Dict:
    """Query single order status from broker."""
    try:
        status = trading_ctx.get_order(order_no=broker_order_no)
        if isinstance(status, dict):
            return status
        # Convert object to dict
        return {
            "order_no": getattr(status, "order_no", broker_order_no),
            "status": getattr(status, "status", "unknown"),
            "matched_vol": getattr(status, "matched_vol",
                           getattr(status, "matched_volume", 0)),
            "matched_price": getattr(status, "matched_price", 0),
        }
    except Exception as e:
        logger.error(f"Status check failed for {broker_order_no}: {e}")
        return {"order_no": broker_order_no, "status": "error",
                "error": str(e)}


def poll_and_process_orders(
    trading_ctx,
    session_id: str,
    is_equity: bool = True,
    pin: str = "",
    buyback_ticks: int = DEFAULT_BUYBACK_TICKS,
    notifier=None,
) -> List[Dict]:
    """
    Poll all placed orders for a session.
    If sells matched → trigger buyback.
    If buys matched → log PnL.

    Returns list of events that occurred.
    """
    events = []

    # Check sell orders
    sell_orders = sm.get_placed_sell_orders(session_id)
    for sell in sell_orders:
        broker_no = sell.get("broker_order_no")
        if not broker_no:
            continue

        status_info = check_order_status(trading_ctx, broker_no)
        broker_status = _normalize_status(status_info.get("status", ""))

        if broker_status == "matched":
            matched_price = float(
                status_info.get("matched_price",
                status_info.get("matchedPrice", sell["price"]))
            )
            matched_vol = int(
                status_info.get("matched_vol",
                status_info.get("matchedVol",
                status_info.get("matched_volume", sell["volume"])))
            )

            # Update sell order
            sm.update_order_status(
                sell["order_id"], "matched",
                matched_price=matched_price,
                matched_volume=matched_vol,
            )

            sm.log_event("INFO", "grid_engine",
                         f"SELL MATCHED: {sell['symbol']} "
                         f"@ {matched_price} × {matched_vol}")

            # Generate and place buyback
            buyback = generate_buyback_order(
                {**sell, "matched_price": matched_price,
                 "matched_volume": matched_vol},
                buyback_ticks=buyback_ticks,
                is_equity=is_equity,
            )

            result = place_buyback_order(
                trading_ctx, session_id, buyback,
                is_equity=is_equity, pin=pin,
            )

            event = {
                "type": "sell_matched",
                "symbol": sell["symbol"],
                "price": matched_price,
                "volume": matched_vol,
                "buyback_price": float(buyback.price),
                "buyback_status": result["status"],
            }
            events.append(event)

            if notifier:
                notifier.order_matched(
                    sell["symbol"], "SELL", matched_price, matched_vol
                )
                if result["status"] == "placed":
                    notifier.buyback_triggered(
                        sell["symbol"], matched_price,
                        float(buyback.price), buyback.volume
                    )

    # Check buy orders
    buy_orders = sm.get_placed_buy_orders(session_id)
    for buy in buy_orders:
        broker_no = buy.get("broker_order_no")
        if not broker_no:
            continue

        status_info = check_order_status(trading_ctx, broker_no)
        broker_status = _normalize_status(status_info.get("status", ""))

        if broker_status == "matched":
            matched_price = float(
                status_info.get("matched_price",
                status_info.get("matchedPrice", buy["price"]))
            )
            matched_vol = int(
                status_info.get("matched_vol",
                status_info.get("matchedVol",
                status_info.get("matched_volume", buy["volume"])))
            )

            # Calculate PnL from parent sell
            parent = buy.get("parent_order")
            pnl = 0.0
            if parent:
                parent_order = sm.get_orders_by_session(session_id)
                parent_data = next(
                    (o for o in parent_order
                     if o["order_id"] == parent), None
                )
                if parent_data and parent_data.get("matched_price"):
                    spread = parent_data["matched_price"] - matched_price
                    pnl = spread * matched_vol

            sm.update_order_status(
                buy["order_id"], "matched",
                matched_price=matched_price,
                matched_volume=matched_vol,
                pnl=pnl,
            )

            sm.log_event("INFO", "grid_engine",
                         f"BUY MATCHED: {buy['symbol']} "
                         f"@ {matched_price} × {matched_vol} "
                         f"PnL: {pnl:+,.2f}")

            event = {
                "type": "buy_matched",
                "symbol": buy["symbol"],
                "price": matched_price,
                "volume": matched_vol,
                "pnl": pnl,
            }
            events.append(event)

            if notifier:
                notifier.order_matched(
                    buy["symbol"], "BUY", matched_price, matched_vol, pnl
                )

    return events


# ─── Helpers ───────────────────────────────────────────────────────

def _extract_order_no(resp) -> str:
    """Extract order number from various API response formats."""
    if isinstance(resp, dict):
        return str(resp.get("order_no",
                   resp.get("orderNo",
                   resp.get("orderno", ""))))
    if hasattr(resp, "order_no"):
        return str(resp.order_no)
    return str(resp)


def _normalize_status(status: str) -> str:
    """Normalize various status strings to our internal format."""
    s = status.lower().strip()
    if s in ("m", "matched", "fully_matched", "full_matched", "fm"):
        return "matched"
    if s in ("pm", "partially_matched", "partial"):
        return "partially_matched"
    if s in ("o", "open", "pending", "queued", "q"):
        return "placed"
    if s in ("c", "cancelled", "canceled", "x", "expired"):
        return "cancelled"
    if s in ("r", "rejected", "rejected_order"):
        return "failed"
    return s


def _trim_excess_volume(orders: List[GridOrder], max_total: int,
                        is_equity: bool) -> None:
    """Trim orders from the top level down to fit max_total."""
    total = sum(o.volume for o in orders)
    for order in reversed(orders):
        if total <= max_total:
            break
        excess = total - max_total
        reduction = min(excess, order.volume)
        order.volume = normalize_volume(
            order.volume - reduction, is_equity
        )
        total = sum(o.volume for o in orders)
