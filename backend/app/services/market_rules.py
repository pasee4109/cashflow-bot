"""
market_rules.py — Thai SET/TFEX Market Microstructure Rules
============================================================
Tick-size tables, board-lot normalization, and price-level
generators compliant with SET and TFEX rules.
"""

from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import List, Tuple

# ─── SET Equity Tick-Size Table ────────────────────────────────────
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
    p = Decimal(str(price))
    for ceiling, tick in SET_TICK_TABLE:
        if p < ceiling:
            return tick
    return SET_TICK_TABLE[-1][1]


def get_tfex_tick_size(symbol: str) -> Decimal:
    upper = symbol.upper()
    # Longest prefix wins (GF10 before GF) for correctness.
    matches = [
        (prefix, tick)
        for prefix, tick in TFEX_TICK_TABLE.items()
        if prefix != "DEFAULT" and upper.startswith(prefix)
    ]
    if matches:
        prefix, tick = max(matches, key=lambda kv: len(kv[0]))
        return tick
    return TFEX_TICK_TABLE["DEFAULT"]


def get_tick_size(price: float, is_equity: bool, symbol: str) -> Decimal:
    return get_equity_tick_size(price) if is_equity else get_tfex_tick_size(symbol)


def tick_up(price: float, n_ticks: int, is_equity: bool = True, symbol: str = "") -> Decimal:
    p = Decimal(str(price))
    for _ in range(n_ticks):
        p += get_tick_size(float(p), is_equity, symbol)
    return p


def tick_down(price: float, n_ticks: int, is_equity: bool = True, symbol: str = "") -> Decimal:
    p = Decimal(str(price))
    for _ in range(n_ticks):
        tick = get_tick_size(float(p), is_equity, symbol)
        p -= tick
        if p <= 0:
            p = tick
            break
    return p


def normalize_equity_volume(raw_volume: float) -> int:
    lots = int(raw_volume // EQUITY_BOARD_LOT)
    return max(lots * EQUITY_BOARD_LOT, EQUITY_BOARD_LOT)


def normalize_tfex_volume(raw_volume: float) -> int:
    return max(1, int(raw_volume))


def normalize_volume(raw_volume: float, is_equity: bool = True) -> int:
    return normalize_equity_volume(raw_volume) if is_equity else normalize_tfex_volume(raw_volume)


def count_ticks_in_range(price_low: float, price_high: float,
                         is_equity: bool = True, symbol: str = "") -> int:
    p = Decimal(str(price_low))
    target = Decimal(str(price_high))
    count = 0
    while p < target:
        p += get_tick_size(float(p), is_equity, symbol)
        count += 1
        if count > 10000:
            break
    return count


def snap_price_to_tick(price: float, direction: str = "down",
                       is_equity: bool = True, symbol: str = "") -> Decimal:
    p = Decimal(str(price))
    tick = get_tick_size(price, is_equity, symbol)
    if direction == "down":
        return (p / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    return (p / tick).to_integral_value(rounding=ROUND_UP) * tick
