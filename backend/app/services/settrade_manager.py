"""
settrade_manager.py — Per-account Settrade connection cache
==========================================================
Builds a settrade_v2 Investor for a bound BrokerAccount and caches
the live trading/market-data contexts, keyed by account id, so we
don't re-authenticate on every request.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..models import BrokerAccount
from ..security import decrypt

logger = logging.getLogger(__name__)


@dataclass
class SettradeClient:
    account_id: int
    pin: str = ""
    investor: Any = None
    equity_ctx: Any = None
    deriv_ctx: Any = None
    market_data_ctx: Any = None
    connected_at: float = field(default_factory=time.time)

    def trading_ctx(self, is_equity: bool):
        return self.equity_ctx if is_equity else self.deriv_ctx


class SettradeManager:
    def __init__(self) -> None:
        self._clients: dict[int, SettradeClient] = {}
        self._lock = threading.Lock()

    def get(self, account_id: int) -> SettradeClient | None:
        return self._clients.get(account_id)

    def connect(self, account: BrokerAccount) -> SettradeClient:
        """(Re)build and cache a client for the given account."""
        if account.is_demo:
            return self._connect_demo(account)

        from settrade_v2 import Investor  # imported lazily so dev w/o pkg still boots

        app_secret = decrypt(account.app_secret_enc)
        pin = decrypt(account.pin_enc) if account.pin_enc else ""

        investor = Investor(
            app_id=account.app_id,
            app_secret=app_secret,
            app_code=account.app_code,
            broker_id=account.broker_id,
            is_auto_queue=False,
        )

        client = SettradeClient(account_id=account.id, pin=pin, investor=investor)

        try:
            client.equity_ctx = investor.Equity(account_no=account.account_no)
        except Exception as e:  # noqa: BLE001
            logger.info("Equity context unavailable for acct %s: %s", account.id, e)
        try:
            client.deriv_ctx = investor.Derivatives(account_no=account.account_no)
        except Exception as e:  # noqa: BLE001
            logger.info("Derivatives context unavailable for acct %s: %s", account.id, e)
        try:
            client.market_data_ctx = investor.MarketData()
        except Exception as e:  # noqa: BLE001
            logger.info("MarketData context unavailable for acct %s: %s", account.id, e)

        with self._lock:
            self._clients[account.id] = client
        return client

    def _connect_demo(self, account: BrokerAccount) -> SettradeClient:
        from .demo import build_demo_contexts

        equity, deriv, market = build_demo_contexts(account.account_type)
        client = SettradeClient(account_id=account.id, pin="DEMO")
        client.investor = object()  # non-None marks it "connected"
        client.equity_ctx = equity
        client.deriv_ctx = deriv
        client.market_data_ctx = market
        with self._lock:
            self._clients[account.id] = client
        return client

    def get_or_connect(self, account: BrokerAccount) -> SettradeClient:
        client = self._clients.get(account.id)
        if client is not None and client.investor is not None:
            return client
        return self.connect(account)

    def disconnect(self, account_id: int) -> None:
        with self._lock:
            self._clients.pop(account_id, None)


# Process-wide singleton — survives across requests within one worker.
manager = SettradeManager()
