"""
auth.py — Settrade v2 API Authentication
==========================================
Wraps the settrade_v2 Investor class initialization
with credential validation and context management.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SettradeAuth:
    """Manages settrade-v2 API authentication lifecycle."""

    def __init__(self):
        self.investor = None
        self.equity_ctx = None
        self.deriv_ctx = None
        self.market_data_ctx = None
        self.realtime_ctx = None
        self._credentials: Dict[str, str] = {}
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self.investor is not None

    def connect(self, app_id: str, app_secret: str, app_code: str,
                broker_id: str, account_no: str = "",
                is_auto_queue: bool = False) -> Dict[str, Any]:
        """
        Initialize Investor and obtain trading contexts.

        Returns dict with status and any error message.
        """
        try:
            from settrade_v2 import Investor

            self.investor = Investor(
                app_id=app_id,
                app_secret=app_secret,
                app_code=app_code,
                broker_id=broker_id,
                is_auto_queue=is_auto_queue,
            )

            self._credentials = {
                "app_id": app_id,
                "broker_id": broker_id,
                "account_no": account_no,
            }

            # Initialize trading contexts
            try:
                self.equity_ctx = self.investor.Equity(
                    account_no=account_no
                )
                logger.info("Equity context initialized")
            except Exception as e:
                logger.warning(f"Equity context unavailable: {e}")

            try:
                self.deriv_ctx = self.investor.Derivatives(
                    account_no=account_no
                )
                logger.info("Derivatives context initialized")
            except Exception as e:
                logger.warning(f"Derivatives context unavailable: {e}")

            try:
                self.market_data_ctx = self.investor.MarketData()
                logger.info("MarketData context initialized")
            except Exception as e:
                logger.warning(f"MarketData context unavailable: {e}")

            try:
                self.realtime_ctx = self.investor.RealtimeDataConnection()
                logger.info("RealtimeData context initialized")
            except Exception as e:
                logger.warning(f"RealtimeData context unavailable: {e}")

            self._connected = True
            return {"status": "ok", "message": "Connected successfully"}

        except ImportError:
            return {
                "status": "error",
                "message": "settrade_v2 package not installed. "
                           "Run: pip install settrade-v2"
            }
        except Exception as e:
            self._connected = False
            logger.error(f"Connection failed: {e}")
            return {"status": "error", "message": str(e)}

    def disconnect(self):
        """Clean up connections."""
        self.investor = None
        self.equity_ctx = None
        self.deriv_ctx = None
        self.market_data_ctx = None
        self.realtime_ctx = None
        self._connected = False
        self._credentials = {}
        logger.info("Disconnected from Settrade API")

    def get_account_info(self) -> str:
        return self._credentials.get("account_no", "N/A")

    def get_broker_id(self) -> str:
        return self._credentials.get("broker_id", "N/A")
