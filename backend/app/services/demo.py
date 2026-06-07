"""
demo.py — Simulated Settrade client for Demo mode
=================================================
Provides objects that mimic the settrade_v2 trading/market-data
contexts (get_portfolios / get_quote_symbol / get_candlestick /
place_order / get_order / cancel_order) backed by synthetic data and
a probabilistic fill engine. This lets the whole app — portfolio,
grid preview, deploy, monitor, buyback, PnL — run end to end without
a real broker account.
"""

import random
import uuid

# Base last-price per demo symbol.
_PRICES = {
    "S50M24": 920.0, "S50U24": 925.0, "GFG24": 2400.0,
    "PTT": 35.25, "KBANK": 130.5, "ADVANC": 210.0,
}

# Demo holdings, in the raw shape the Settrade API returns.
_DERIV_POSITIONS = [
    {"symbol": "S50M24", "longPosition": 10, "shortPosition": 0,
     "avgCost": 915.0, "marketPrice": 920.0, "unrealizedPL": 250.0},
    {"symbol": "GFG24", "longPosition": 3, "shortPosition": 0,
     "avgCost": 2380.0, "marketPrice": 2400.0, "unrealizedPL": 600.0},
]
_EQUITY_POSITIONS = [
    {"symbol": "PTT", "actualVol": 2000, "avgCost": 34.5,
     "marketPrice": 35.25, "unrealizedPL": 1500.0},
    {"symbol": "KBANK", "actualVol": 500, "avgCost": 128.0,
     "marketPrice": 130.5, "unrealizedPL": 1250.0},
]

# Probability that an open demo order fills on a given status poll.
_FILL_PROB = 0.4


def base_price(symbol: str) -> float:
    return _PRICES.get(symbol.upper(), _PRICES.get(symbol, 100.0))


class DemoMarket:
    """Stands in for the MarketData context."""

    def get_quote_symbol(self, symbol: str):
        return {"last": base_price(symbol)}

    def get_candlestick(self, symbol: str, timeframe: str = "1D", limit: int = 30):
        rng = random.Random(hash(symbol) & 0xFFFFFFFF)
        price = base_price(symbol)
        vol = max(price * 0.01, 0.1)  # ~1% daily range
        rows = []
        for _ in range(max(limit, 20)):
            drift = rng.uniform(-vol, vol)
            close = max(price + drift, vol)
            high = close + abs(rng.uniform(0, vol))
            low = max(close - abs(rng.uniform(0, vol)), vol * 0.5)
            rows.append({"open": price, "high": high, "low": low,
                         "close": close, "volume": rng.randint(1000, 5000)})
            price = close
        return rows


class DemoBroker:
    """Stands in for an Equity/Derivatives trading context.

    `positions` is what this side reports; `store` is shared across the
    equity & derivatives sides of one account so the monitor sees fills
    regardless of which context it polls.
    """

    def __init__(self, positions: list, store: dict):
        self._positions = positions
        self._store = store

    def get_portfolios(self):
        return list(self._positions)

    def place_order(self, *, pin=None, symbol, side, price, volume,
                    price_type="LIMIT", validity_type="DAY"):
        order_no = f"DEMO-{uuid.uuid4().hex[:8].upper()}"
        self._store[order_no] = {
            "symbol": symbol, "side": side, "price": float(price),
            "volume": int(volume), "status": "open",
        }
        return {"order_no": order_no}

    def get_order(self, *, order_no):
        o = self._store.get(order_no)
        if not o:
            return {"status": "open"}
        if o["status"] == "open" and random.random() < _FILL_PROB:
            o["status"] = "matched"
        return {"status": o["status"], "matched_price": o["price"],
                "matched_vol": o["volume"]}

    def cancel_order(self, *, pin=None, order_no):
        o = self._store.get(order_no)
        if o and o["status"] == "open":
            o["status"] = "cancelled"
        return {"order_no": order_no, "status": "cancelled"}


def build_demo_contexts(account_type: str):
    """Return (equity_ctx, deriv_ctx, market_ctx) wired to a shared store."""
    store: dict = {}
    if account_type == "equity":
        equity = DemoBroker(_EQUITY_POSITIONS, store)
        deriv = DemoBroker([], store)
    else:
        equity = DemoBroker([], store)
        deriv = DemoBroker(_DERIV_POSITIONS, store)
    return equity, deriv, DemoMarket()
