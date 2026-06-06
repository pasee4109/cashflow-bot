"""
telegram.py — Telegram alerts + per-account notifier registry
=============================================================
"""

import logging
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)
_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)
        self._session = requests.Session() if self.enabled else None

    def _send(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            resp = self._session.post(
                _TELEGRAM_API.format(token=self.bot_token),
                json={
                    "chat_id": self.chat_id, "text": text,
                    "parse_mode": "HTML", "disable_web_page_preview": True,
                },
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:  # noqa: BLE001
            logger.warning("Telegram send failed: %s", e)
            return False

    @staticmethod
    def _ts() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def bot_started(self, symbols: list):
        self._send(f"🟢 <b>Grid Bot Started</b>\n⏰ {self._ts()}\n"
                   f"📊 {', '.join(symbols)}")

    def bot_stopped(self):
        self._send(f"🔴 <b>Bot Stopped</b>\n⏰ {self._ts()}")

    def orders_placed(self, symbol: str, side: str, count: int, price_range: str):
        emoji = "📤" if side == "SELL" else "📥"
        self._send(f"{emoji} <b>{side} Orders Placed</b>\nSymbol: <code>{symbol}</code>\n"
                   f"Count: {count}\nRange: {price_range}\n⏰ {self._ts()}")

    def order_matched(self, symbol: str, side: str, price: float, volume: int,
                      pnl: Optional[float] = None):
        emoji = "✅" if side == "SELL" else "🔄"
        pnl_line = f"\n💰 PnL: {pnl:+,.2f}" if pnl is not None else ""
        self._send(f"{emoji} <b>{side} Matched</b>\nSymbol: <code>{symbol}</code>\n"
                   f"Price: {price:,.2f} × {volume:,}{pnl_line}\n⏰ {self._ts()}")

    def buyback_triggered(self, symbol: str, sell_price: float, buy_price: float, volume: int):
        self._send(f"🔄 <b>Buyback Triggered</b>\nSymbol: <code>{symbol}</code>\n"
                   f"Sold @ {sell_price:,.2f} → Buy @ {buy_price:,.2f}\n"
                   f"Volume: {volume:,}\nSpread: {sell_price - buy_price:,.2f}\n⏰ {self._ts()}")

    def error_alert(self, source: str, message: str):
        self._send(f"🚨 <b>Error — {source}</b>\n<pre>{message[:500]}</pre>\n⏰ {self._ts()}")

    def heartbeat(self, active_sessions: int, open_orders: int):
        self._send(f"💓 <b>Heartbeat</b>\nSessions: {active_sessions}\n"
                   f"Open Orders: {open_orders}\n⏰ {self._ts()}")


# Per-account notifier registry (configured via the API, defaults disabled).
_registry: dict[int, TelegramNotifier] = {}
_DISABLED = TelegramNotifier()


def set_notifier(account_id: int, bot_token: str, chat_id: str) -> TelegramNotifier:
    notifier = TelegramNotifier(bot_token, chat_id)
    _registry[account_id] = notifier
    return notifier


def get_notifier(account_id: int) -> TelegramNotifier:
    return _registry.get(account_id, _DISABLED)
