"""
portfolio.py — Portfolio Fetching & Management
================================================
Retrieves equity and derivative holdings from Settrade API,
normalizes them into a unified format for the UI.
"""

import logging
import pandas as pd
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


def fetch_equity_portfolio(equity_ctx) -> pd.DataFrame:
    """
    Fetch equity portfolio from Settrade Equity context.
    Returns DataFrame with columns:
        symbol, market_type, volume, avg_cost, market_price,
        market_value, unrealized_pnl, pct_change
    """
    try:
        portfolio = equity_ctx.get_portfolios()

        if not portfolio:
            return pd.DataFrame()

        rows = []
        # The Settrade API returns portfolio as a list of dicts
        # or an object with a 'portfolio_list' attribute
        items = portfolio
        if hasattr(portfolio, 'portfolio_list'):
            items = portfolio.portfolio_list
        elif isinstance(portfolio, dict):
            items = portfolio.get('portfolio_list',
                     portfolio.get('portfolioList', []))

        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    row = _parse_equity_item(item)
                else:
                    row = _parse_equity_object(item)
                if row and row.get("volume", 0) > 0:
                    rows.append(row)

        df = pd.DataFrame(rows)
        if not df.empty:
            df["market_type"] = "equity"
        return df

    except Exception as e:
        logger.error(f"Failed to fetch equity portfolio: {e}")
        return pd.DataFrame()


def fetch_derivative_portfolio(deriv_ctx) -> pd.DataFrame:
    """
    Fetch derivative portfolio from Settrade Derivatives context.
    Returns DataFrame matching equity schema.
    """
    try:
        portfolio = deriv_ctx.get_portfolios()

        if not portfolio:
            return pd.DataFrame()

        rows = []
        items = portfolio
        if hasattr(portfolio, 'portfolio_list'):
            items = portfolio.portfolio_list
        elif isinstance(portfolio, dict):
            items = portfolio.get('portfolio_list',
                     portfolio.get('portfolioList', []))

        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    row = _parse_deriv_item(item)
                else:
                    row = _parse_deriv_object(item)
                if row and abs(row.get("volume", 0)) > 0:
                    rows.append(row)

        df = pd.DataFrame(rows)
        if not df.empty:
            df["market_type"] = "derivative"
        return df

    except Exception as e:
        logger.error(f"Failed to fetch derivative portfolio: {e}")
        return pd.DataFrame()


def fetch_combined_portfolio(equity_ctx, deriv_ctx) -> pd.DataFrame:
    """Fetch and merge both portfolios."""
    frames = []

    if equity_ctx:
        eq = fetch_equity_portfolio(equity_ctx)
        if not eq.empty:
            frames.append(eq)

    if deriv_ctx:
        dv = fetch_derivative_portfolio(deriv_ctx)
        if not dv.empty:
            frames.append(dv)

    if not frames:
        return pd.DataFrame(columns=[
            "symbol", "market_type", "volume", "avg_cost",
            "market_price", "market_value", "unrealized_pnl", "pct_change"
        ])

    return pd.concat(frames, ignore_index=True)


def get_last_price(market_data_ctx, symbol: str) -> Optional[float]:
    """Get the last traded price for a symbol."""
    try:
        quote = market_data_ctx.get_quote_symbol(symbol)
        if isinstance(quote, dict):
            return float(quote.get("last", quote.get("close", 0)))
        elif hasattr(quote, "last"):
            return float(quote.last)
        return None
    except Exception as e:
        logger.error(f"Failed to get last price for {symbol}: {e}")
        return None


def get_candlestick_data(market_data_ctx, symbol: str,
                         timeframe: str = "1D",
                         limit: int = 30) -> pd.DataFrame:
    """
    Fetch OHLCV candlestick data for ATR calculation.
    """
    try:
        candles = market_data_ctx.get_candlestick(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit
        )

        if isinstance(candles, list):
            df = pd.DataFrame(candles)
        elif isinstance(candles, dict) and "data" in candles:
            df = pd.DataFrame(candles["data"])
        elif hasattr(candles, "to_dataframe"):
            df = candles.to_dataframe()
        else:
            df = pd.DataFrame(candles)

        # Normalize column names
        col_map = {}
        for col in df.columns:
            lc = col.lower()
            if "high" in lc:
                col_map[col] = "high"
            elif "low" in lc:
                col_map[col] = "low"
            elif "close" in lc:
                col_map[col] = "close"
            elif "open" in lc:
                col_map[col] = "open"
            elif "vol" in lc:
                col_map[col] = "volume"

        df = df.rename(columns=col_map)
        return df

    except Exception as e:
        logger.error(f"Failed to get candlestick for {symbol}: {e}")
        return pd.DataFrame()


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Compute ATR from OHLCV DataFrame.
    Uses Wilder's smoothing (exponential).
    """
    if df.empty or len(df) < period + 1:
        return 0.0

    try:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        # True Range components
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Wilder's smoothing
        atr = tr.ewm(alpha=1.0 / period, min_periods=period).mean()

        return float(atr.iloc[-1])

    except Exception as e:
        logger.error(f"ATR calculation failed: {e}")
        return 0.0


# ─── Internal Parsers ──────────────────────────────────────────────

def _parse_equity_item(item: dict) -> dict:
    """Parse dict-format equity portfolio item."""
    return {
        "symbol": item.get("symbol", item.get("securitySymbol", "")),
        "volume": int(item.get("actualVol",
                       item.get("actual_vol",
                       item.get("volume", 0)))),
        "avg_cost": float(item.get("avgCost",
                          item.get("avg_cost",
                          item.get("averageCost", 0)))),
        "market_price": float(item.get("marketPrice",
                              item.get("market_price",
                              item.get("lastPrice", 0)))),
        "market_value": float(item.get("marketValue",
                              item.get("market_value", 0))),
        "unrealized_pnl": float(item.get("unrealizedPL",
                                item.get("unrealized_pl", 0))),
        "pct_change": float(item.get("percentChange",
                            item.get("pct_change", 0))),
    }


def _parse_equity_object(item) -> dict:
    """Parse object-format equity portfolio item."""
    return {
        "symbol": getattr(item, "symbol",
                  getattr(item, "security_symbol", "")),
        "volume": int(getattr(item, "actual_vol",
                      getattr(item, "volume", 0))),
        "avg_cost": float(getattr(item, "avg_cost",
                          getattr(item, "average_cost", 0))),
        "market_price": float(getattr(item, "market_price",
                              getattr(item, "last_price", 0))),
        "market_value": float(getattr(item, "market_value", 0)),
        "unrealized_pnl": float(getattr(item, "unrealized_pl", 0)),
        "pct_change": float(getattr(item, "percent_change", 0)),
    }


def _parse_deriv_item(item: dict) -> dict:
    """Parse dict-format derivative portfolio item."""
    long_pos = int(item.get("longPosition",
                   item.get("long_position",
                   item.get("longQty", 0))))
    short_pos = int(item.get("shortPosition",
                    item.get("short_position",
                    item.get("shortQty", 0))))
    net_pos = long_pos - short_pos

    return {
        "symbol": item.get("symbol", item.get("seriesSymbol", "")),
        "volume": net_pos,
        "avg_cost": float(item.get("avgCost",
                          item.get("avg_cost", 0))),
        "market_price": float(item.get("marketPrice",
                              item.get("market_price", 0))),
        "market_value": float(item.get("marketValue",
                              item.get("market_value", 0))),
        "unrealized_pnl": float(item.get("unrealizedPL",
                                item.get("unrealized_pl", 0))),
        "pct_change": float(item.get("percentChange",
                            item.get("pct_change", 0))),
    }


def _parse_deriv_object(item) -> dict:
    """Parse object-format derivative portfolio item."""
    long_pos = int(getattr(item, "long_position",
                   getattr(item, "long_qty", 0)))
    short_pos = int(getattr(item, "short_position",
                    getattr(item, "short_qty", 0)))

    return {
        "symbol": getattr(item, "symbol",
                  getattr(item, "series_symbol", "")),
        "volume": long_pos - short_pos,
        "avg_cost": float(getattr(item, "avg_cost", 0)),
        "market_price": float(getattr(item, "market_price", 0)),
        "market_value": float(getattr(item, "market_value", 0)),
        "unrealized_pnl": float(getattr(item, "unrealized_pl", 0)),
        "pct_change": float(getattr(item, "percent_change", 0)),
    }
