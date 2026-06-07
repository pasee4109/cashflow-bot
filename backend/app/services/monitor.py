"""
monitor.py — Background order-monitor threads
=============================================
One daemon thread per active grid session. Each thread owns its own
DB session and pulls the live Settrade client from the manager every
iteration so reconnects propagate transparently.
"""

import logging
import threading
import time

from ..config import settings
from ..database import SessionLocal
from . import crud, trading
from .settrade_manager import manager as settrade_manager
from .telegram import get_notifier

logger = logging.getLogger(__name__)


class OrderMonitor:
    def __init__(self, *, session_id: str, account_id: int, is_equity: bool,
                 pin: str, buyback_ticks: int):
        self.session_id = session_id
        self.account_id = account_id
        self.is_equity = is_equity
        self.pin = pin
        self.buyback_ticks = buyback_ticks
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_heartbeat = 0.0

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name=f"mon-{self.session_id[:8]}", daemon=True
        )
        self._thread.start()
        logger.info("monitor started: %s", self.session_id)

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("monitor stopped: %s", self.session_id)

    def _loop(self):
        db = SessionLocal()
        notifier = get_notifier(self.account_id)
        try:
            while self._running:
                try:
                    db.expire_all()  # avoid stale reads across the long-lived session
                    sess = crud.get_session(db, self.session_id)
                    if not sess or sess.status != "active":
                        self._running = False
                        break

                    client = settrade_manager.get(self.account_id)
                    if client is None:
                        crud.log_event(db, "WARN", "monitor",
                                       "Settrade client not connected; pausing poll",
                                       account_id=self.account_id, session_id=self.session_id)
                    else:
                        trading.poll_and_process(
                            db, client.trading_ctx(self.is_equity),
                            session_id=self.session_id, account_id=self.account_id,
                            is_equity=self.is_equity, pin=self.pin or client.pin,
                            buyback_ticks=self.buyback_ticks, notifier=notifier,
                        )

                    now = time.time()
                    if now - self._last_heartbeat > settings.heartbeat_interval_sec:
                        self._heartbeat(db, notifier)
                        self._last_heartbeat = now
                except Exception as e:  # noqa: BLE001
                    logger.error("monitor loop error: %s", e)
                    crud.log_event(db, "ERROR", "monitor", f"poll error: {e}",
                                   account_id=self.account_id, session_id=self.session_id)
                time.sleep(settings.order_poll_interval_sec)
        finally:
            db.close()

    def _heartbeat(self, db, notifier):
        try:
            open_orders = (len(crud.get_placed_sell_orders(db, self.session_id))
                           + len(crud.get_placed_buy_orders(db, self.session_id)))
            active = len(crud.get_active_sessions(db, self.account_id))
            if notifier:
                notifier.heartbeat(active, open_orders)
        except Exception:  # noqa: BLE001
            pass


class MonitorManager:
    def __init__(self):
        self._monitors: dict[str, OrderMonitor] = {}
        self._lock = threading.Lock()

    def start(self, **kwargs) -> OrderMonitor:
        sid = kwargs["session_id"]
        with self._lock:
            existing = self._monitors.get(sid)
            if existing and existing.is_running:
                return existing
            monitor = OrderMonitor(**kwargs)
            monitor.start()
            self._monitors[sid] = monitor
            return monitor

    def stop(self, session_id: str):
        with self._lock:
            m = self._monitors.pop(session_id, None)
        if m:
            m.stop()

    def stop_account(self, account_id: int):
        for sid, m in list(self._monitors.items()):
            if m.account_id == account_id:
                self.stop(sid)

    def stop_all(self):
        for sid in list(self._monitors.keys()):
            self.stop(sid)

    def active_count(self, account_id: int | None = None) -> int:
        return sum(
            1 for m in self._monitors.values()
            if m.is_running and (account_id is None or m.account_id == account_id)
        )


manager = MonitorManager()
