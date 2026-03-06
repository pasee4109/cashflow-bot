"""
telegram_notifier.py — Telegram Bot Integration
=================================================
Sends structured alerts for bot events.
"""

import requests
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """Non-blocking Telegram alert sender."""

    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)
        self._session = requests.Session() if self.enabled else None

    def _send(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.enabled:
            return False
        try:
            url = _TELEGRAM_API.format(token=self.bot_token)
            resp = self._session.post(url, json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")
            return False

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    # ─── Event Methods ─────────────────────────────────────────────

    def bot_started(self, symbols: list):
        syms = ", ".join(symbols)
        self._send(
            f"🟢 <b>Cashflow Ladder Bot Started</b>\n"
            f"⏰ {self._ts()}\n"
            f"📊 Symbols: <code>{syms}</code>"
        )

    def bot_stopped(self):
        self._send(
            f"🔴 <b>Bot Stopped</b>\n"
            f"⏰ {self._ts()}"
        )

    def orders_placed(self, symbol: str, side: str, count: int,
                      price_range: str):
        emoji = "📤" if side == "SELL" else "📥"
        self._send(
            f"{emoji} <b>{side} Orders Placed</b>\n"
            f"Symbol: <code>{symbol}</code>\n"
            f"Count: {count}\n"
            f"Range: {price_range}\n"
            f"⏰ {self._ts()}"
        )

    def order_matched(self, symbol: str, side: str, price: float,
                      volume: int, pnl: Optional[float] = None):
        emoji = "✅" if side == "SELL" else "🔄"
        pnl_line = f"\n💰 PnL: {pnl:+,.2f}" if pnl is not None else ""
        self._send(
            f"{emoji} <b>{side} Order Matched</b>\n"
            f"Symbol: <code>{symbol}</code>\n"
            f"Price: {price:,.2f} × {volume:,}{pnl_line}\n"
            f"⏰ {self._ts()}"
        )

    def buyback_triggered(self, symbol: str, sell_price: float,
                          buy_price: float, volume: int):
        self._send(
            f"🔄 <b>Buyback Triggered</b>\n"
            f"Symbol: <code>{symbol}</code>\n"
            f"Sold @ {sell_price:,.2f} → Buy @ {buy_price:,.2f}\n"
            f"Volume: {volume:,}\n"
            f"Spread: {sell_price - buy_price:,.2f}\n"
            f"⏰ {self._ts()}"
        )

    def error_alert(self, source: str, message: str):
        self._send(
            f"🚨 <b>Error — {source}</b>\n"
            f"<pre>{message[:500]}</pre>\n"
            f"⏰ {self._ts()}"
        )

    def session_summary(self, symbol: str, sells: int, buys: int,
                        total_pnl: float):
        self._send(
            f"📊 <b>Session Summary: {symbol}</b>\n"
            f"Sells Matched: {sells}\n"
            f"Buybacks Matched: {buys}\n"
            f"Total PnL: {total_pnl:+,.2f} THB\n"
            f"⏰ {self._ts()}"
        )

    def heartbeat(self, active_sessions: int, open_orders: int):
        self._send(
            f"💓 <b>Heartbeat</b>\n"
            f"Sessions: {active_sessions}\n"
            f"Open Orders: {open_orders}\n"
            f"⏰ {self._ts()}"
        )
