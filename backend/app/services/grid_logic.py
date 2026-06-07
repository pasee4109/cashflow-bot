"""
grid_logic.py — Pure cashflow-ladder grid math (no I/O)
=======================================================
Generates the sell ladder and buyback orders. Free of any DB or
broker dependency so it is trivially testable.
"""

import uuid
from decimal import Decimal
from typing import Dict, List

from ..config import settings
from .market_rules import (
    count_ticks_in_range, normalize_volume, snap_price_to_tick,
    tick_down, tick_up,
)


class GridOrder:
    def __init__(self, symbol: str, side: str, price: Decimal,
                 volume: int, grid_level: int = 0, parent_order: str | None = None):
        self.order_id = f"GL-{uuid.uuid4().hex[:8].upper()}"
        self.symbol = symbol
        self.side = side
        self.price = price
        self.volume = volume
        self.grid_level = grid_level
        self.parent_order = parent_order
        self.broker_order_no: str | None = None
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


def calculate_allocation_volume(total_holding: int, allocation_pct: float,
                                is_equity: bool = True) -> int:
    raw = total_holding * (allocation_pct / 100.0)
    return normalize_volume(raw, is_equity)


def generate_sell_ladder(
    symbol: str,
    last_price: float,
    atr_value: float,
    total_volume: int,
    is_equity: bool = True,
    grid_levels: int = 5,
    ladder_weights: List[int] | None = None,
) -> List[GridOrder]:
    """Laddered sell orders above the current price, capped at +1 ATR."""
    if ladder_weights is None:
        ladder_weights = settings.ladder_weights[:grid_levels]
    ladder_weights = list(ladder_weights)

    while len(ladder_weights) < grid_levels:
        ladder_weights.append(ladder_weights[-1] + 1)
    ladder_weights = ladder_weights[:grid_levels]

    atr_ceiling = last_price + (atr_value * settings.atr_grid_limit)
    total_ticks = count_ticks_in_range(last_price, atr_ceiling, is_equity, symbol)

    if total_ticks < grid_levels:
        grid_levels = max(1, total_ticks)
        ladder_weights = ladder_weights[:grid_levels] or [1]

    ticks_per_level = max(1, total_ticks // max(1, grid_levels))
    weight_sum = sum(ladder_weights) or 1
    orders: List[GridOrder] = []

    for i, weight in enumerate(ladder_weights):
        level = i + 1
        n_ticks = level * ticks_per_level
        price = tick_up(last_price, n_ticks, is_equity, symbol)
        if float(price) > atr_ceiling:
            price = snap_price_to_tick(atr_ceiling, "down", is_equity, symbol)

        raw_vol = (weight / weight_sum) * total_volume
        vol = normalize_volume(raw_vol, is_equity)
        orders.append(GridOrder(symbol, "SELL", price, vol, grid_level=level))

    total_allocated = sum(o.volume for o in orders)
    if total_allocated > total_volume:
        _trim_excess_volume(orders, total_volume, is_equity)

    return orders


def generate_buyback_order(sell_order: Dict, buyback_ticks: int = 3,
                           is_equity: bool = True) -> GridOrder:
    exec_price = sell_order.get("matched_price") or sell_order["price"]
    exec_vol = sell_order.get("matched_volume") or sell_order["volume"]
    buy_price = tick_down(exec_price, buyback_ticks, is_equity, sell_order["symbol"])
    volume = normalize_volume(exec_vol, is_equity)
    return GridOrder(
        symbol=sell_order["symbol"], side="BUY", price=buy_price,
        volume=volume, parent_order=sell_order["order_id"],
    )


def _trim_excess_volume(orders: List[GridOrder], max_total: int, is_equity: bool) -> None:
    total = sum(o.volume for o in orders)
    for order in reversed(orders):
        if total <= max_total:
            break
        excess = total - max_total
        reduction = min(excess, order.volume)
        order.volume = normalize_volume(order.volume - reduction, is_equity)
        total = sum(o.volume for o in orders)


# ─── Response parsing helpers (shared with trading layer) ──────────

def extract_order_no(resp) -> str:
    if isinstance(resp, dict):
        return str(resp.get("order_no", resp.get("orderNo", resp.get("orderno", ""))))
    if hasattr(resp, "order_no"):
        return str(resp.order_no)
    return str(resp)


def normalize_status(status: str) -> str:
    s = str(status).lower().strip()
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
