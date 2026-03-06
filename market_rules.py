"""
market_rules.py — Thai SET/TFEX Market Microstructure Rules
============================================================
Implements tick-size tables, board-lot normalization, and
price-level generators compliant with SET and TFEX rules.
"""

from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import List, Tuple

# ─── SET Equity Tick-Size Table ────────────────────────────────────
# Price Range (THB)        Tick Size (THB)
SET_TICK_TABLE: List[Tuple[Decimal, Decimal]] = [
    (Decimal("2"),      Decimal("0.01")),
    (Decimal("5"),      Decimal("0.02")),
    (Decimal("10"),     Decimal("0.05")),
    (Decimal("25"),     Decimal("0.10")),
    (Decimal("50"),     Decimal("0.25")),
    (Decimal("100"),    Decimal("0.50")),
    (Decimal("200"),    Decimal("1.00")),
    (Decimal("400"),    Decimal("2.00")),
    (Decimal("800"),    Decimal("4.00")),
    (Decimal("999999"), Decimal("6.00")),
]

# TFEX tick sizes for common instruments
TFEX_TICK_TABLE = {
    "S50":   Decimal("0.1"),   # SET50 Index Futures
    "GF":    Decimal("10"),    # Gold Futures (THB)
    "GF10":  Decimal("1"),     # Gold Futures 10 Baht
    "SI":    Decimal("1"),     # Silver Futures
    "CU":    Decimal("0.01"),  # USD Futures
    "JY":    Decimal("0.01"),  # JPY Futures (per 100 JPY)
    "DEFAULT": Decimal("0.5"),
}

EQUITY_BOARD_LOT = 100  # Shares per board lot


def get_equity_tick_size(price: float) -> Decimal:
    """Return the SET tick size for a given equity price."""
    p = Decimal(str(price))
    for ceiling, tick in SET_TICK_TABLE:
        if p < ceiling:
            return tick
    return SET_TICK_TABLE[-1][1]


def get_tfex_tick_size(symbol: str) -> Decimal:
    """Return TFEX tick size based on symbol prefix."""
    upper = symbol.upper()
    for prefix, tick in TFEX_TICK_TABLE.items():
        if prefix != "DEFAULT" and upper.startswith(prefix):
            return tick
    return TFEX_TICK_TABLE["DEFAULT"]


def tick_up(price: float, n_ticks: int, is_equity: bool = True,
            symbol: str = "") -> Decimal:
    """Move price UP by n ticks, recalculating tick size at each level."""
    p = Decimal(str(price))
    for _ in range(n_ticks):
        if is_equity:
            tick = get_equity_tick_size(float(p))
        else:
            tick = get_tfex_tick_size(symbol)
        p += tick
    return p


def tick_down(price: float, n_ticks: int, is_equity: bool = True,
              symbol: str = "") -> Decimal:
    """Move price DOWN by n ticks, recalculating tick size at each level."""
    p = Decimal(str(price))
    for _ in range(n_ticks):
        if is_equity:
            tick = get_equity_tick_size(float(p))
        else:
            tick = get_tfex_tick_size(symbol)
        p -= tick
        if p <= 0:
            p = tick  # floor at 1 tick
            break
    return p


def normalize_equity_volume(raw_volume: float) -> int:
    """Round DOWN to nearest board lot (100 shares)."""
    lots = int(raw_volume // EQUITY_BOARD_LOT)
    return max(lots * EQUITY_BOARD_LOT, EQUITY_BOARD_LOT)


def normalize_tfex_volume(raw_volume: float) -> int:
    """TFEX contracts must be integers ≥ 1."""
    return max(1, int(raw_volume))


def normalize_volume(raw_volume: float, is_equity: bool = True) -> int:
    """Unified volume normalizer."""
    if is_equity:
        return normalize_equity_volume(raw_volume)
    return normalize_tfex_volume(raw_volume)


def count_ticks_in_range(price_low: float, price_high: float,
                         is_equity: bool = True, symbol: str = "") -> int:
    """Count number of ticks between two price levels."""
    p = Decimal(str(price_low))
    target = Decimal(str(price_high))
    count = 0
    while p < target:
        if is_equity:
            tick = get_equity_tick_size(float(p))
        else:
            tick = get_tfex_tick_size(symbol)
        p += tick
        count += 1
        if count > 10000:  # safety
            break
    return count


def snap_price_to_tick(price: float, direction: str = "down",
                       is_equity: bool = True, symbol: str = "") -> Decimal:
    """Snap a float price to the nearest valid tick level."""
    p = Decimal(str(price))
    if is_equity:
        tick = get_equity_tick_size(price)
    else:
        tick = get_tfex_tick_size(symbol)

    if direction == "down":
        return (p / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    else:
        return (p / tick).to_integral_value(rounding=ROUND_UP) * tick
