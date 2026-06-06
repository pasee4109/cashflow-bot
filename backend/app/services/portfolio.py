"""
portfolio.py — Portfolio & market-data fetching
===============================================
Retrieves equity/derivative holdings and OHLCV data from the
Settrade API and normalizes them for the API layer.
"""

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _parse_equity(item) -> dict:
    g = item.get if isinstance(item, dict) else (lambda k, d=None: getattr(item, k, d))
    return {
        "symbol": g("symbol") or g("securitySymbol") or g("security_symbol") or "",
        "volume": int(g("actualVol") or g("actual_vol") or g("volume") or 0),
        "avg_cost": float(g("avgCost") or g("avg_cost") or g("averageCost") or 0),
        "market_price": float(g("marketPrice") or g("market_price") or g("lastPrice") or 0),
        "market_value": float(g("marketValue") or g("market_value") or 0),
        "unrealized_pnl": float(g("unrealizedPL") or g("unrealized_pl") or 0),
        "pct_change": float(g("percentChange") or g("pct_change") or 0),
        "market_type": "equity",
    }


def _parse_deriv(item) -> dict:
    g = item.get if isinstance(item, dict) else (lambda k, d=None: getattr(item, k, d))
    long_pos = int(g("longPosition") or g("long_position") or g("longQty") or g("long_qty") or 0)
    short_pos = int(g("shortPosition") or g("short_position") or g("shortQty") or g("short_qty") or 0)
    return {
        "symbol": g("symbol") or g("seriesSymbol") or g("series_symbol") or "",
        "volume": long_pos - short_pos,
        "avg_cost": float(g("avgCost") or g("avg_cost") or 0),
        "market_price": float(g("marketPrice") or g("market_price") or 0),
        "market_value": float(g("marketValue") or g("market_value") or 0),
        "unrealized_pnl": float(g("unrealizedPL") or g("unrealized_pl") or 0),
        "pct_change": float(g("percentChange") or g("pct_change") or 0),
        "market_type": "derivative",
    }


def _extract_items(portfolio):
    if not portfolio:
        return []
    if hasattr(portfolio, "portfolio_list"):
        return portfolio.portfolio_list
    if isinstance(portfolio, dict):
        return portfolio.get("portfolio_list", portfolio.get("portfolioList", []))
    if isinstance(portfolio, list):
        return portfolio
    return []


def fetch_portfolio(equity_ctx, deriv_ctx) -> list[dict]:
    rows: list[dict] = []
    if equity_ctx:
        try:
            for item in _extract_items(equity_ctx.get_portfolios()):
                row = _parse_equity(item)
                if row["volume"] > 0:
                    rows.append(row)
        except Exception as e:  # noqa: BLE001
            logger.error("equity portfolio fetch failed: %s", e)
    if deriv_ctx:
        try:
            for item in _extract_items(deriv_ctx.get_portfolios()):
                row = _parse_deriv(item)
                if abs(row["volume"]) > 0:
                    rows.append(row)
        except Exception as e:  # noqa: BLE001
            logger.error("derivative portfolio fetch failed: %s", e)
    return rows


def get_last_price(market_data_ctx, symbol: str) -> Optional[float]:
    if not market_data_ctx:
        return None
    try:
        quote = market_data_ctx.get_quote_symbol(symbol)
        if isinstance(quote, dict):
            return float(quote.get("last", quote.get("close", 0)))
        if hasattr(quote, "last"):
            return float(quote.last)
    except Exception as e:  # noqa: BLE001
        logger.error("last price fetch failed for %s: %s", symbol, e)
    return None


def _candles_df(market_data_ctx, symbol: str, limit: int) -> pd.DataFrame:
    try:
        candles = market_data_ctx.get_candlestick(symbol=symbol, timeframe="1D", limit=limit)
        if isinstance(candles, dict) and "data" in candles:
            df = pd.DataFrame(candles["data"])
        elif hasattr(candles, "to_dataframe"):
            df = candles.to_dataframe()
        else:
            df = pd.DataFrame(candles)
        col_map = {}
        for col in df.columns:
            lc = str(col).lower()
            for key in ("high", "low", "close", "open"):
                if key in lc:
                    col_map[col] = key
            if "vol" in lc:
                col_map[col] = "volume"
        return df.rename(columns=col_map)
    except Exception as e:  # noqa: BLE001
        logger.error("candlestick fetch failed for %s: %s", symbol, e)
        return pd.DataFrame()


def calculate_atr(market_data_ctx, symbol: str, period: int = 14) -> float:
    df = _candles_df(market_data_ctx, symbol, limit=period + 5)
    if df.empty or len(df) < period + 1 or "high" not in df:
        return 0.0
    try:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1.0 / period, min_periods=period).mean()
        return float(atr.iloc[-1])
    except Exception as e:  # noqa: BLE001
        logger.error("ATR calc failed for %s: %s", symbol, e)
        return 0.0
