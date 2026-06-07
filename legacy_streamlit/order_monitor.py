"""
order_monitor.py — Background Order Monitor
=============================================
Runs a polling loop that checks order statuses
and triggers buy-back orders when sells match.
"""

import time
import logging
import threading
from typing import Dict, List, Optional, Callable
from datetime import datetime

import state_manager as sm
from grid_engine import poll_and_process_orders
from config import ORDER_POLL_INTERVAL_SEC, HEARTBEAT_INTERVAL_SEC

logger = logging.getLogger(__name__)


class OrderMonitor:
    """
    Background thread that polls order statuses and
    dispatches buy-back orders when sells are filled.
    """

    def __init__(self, trading_ctx, session_id: str,
                 is_equity: bool = True, pin: str = "",
                 buyback_ticks: int = 3, notifier=None,
                 on_event: Optional[Callable] = None):
        self.trading_ctx = trading_ctx
        self.session_id = session_id
        self.is_equity = is_equity
        self.pin = pin
        self.buyback_ticks = buyback_ticks
        self.notifier = notifier
        self.on_event = on_event  # callback for UI updates

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._poll_interval = ORDER_POLL_INTERVAL_SEC
        self._heartbeat_interval = HEARTBEAT_INTERVAL_SEC
        self._last_heartbeat = 0.0
        self._event_log: List[Dict] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def events(self) -> List[Dict]:
        return list(self._event_log)

    def start(self):
        """Start the monitoring thread."""
        if self._running:
            logger.warning("Monitor already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"monitor-{self.session_id[:8]}",
            daemon=True,
        )
        self._thread.start()

        sm.log_event("INFO", "monitor",
                     f"Monitor started for session {self.session_id}")
        logger.info(f"Order monitor started: {self.session_id}")

    def stop(self):
        """Signal the monitor to stop."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

        sm.log_event("INFO", "monitor",
                     f"Monitor stopped for session {self.session_id}")
        logger.info(f"Order monitor stopped: {self.session_id}")

    def _run_loop(self):
        """Main polling loop."""
        while self._running:
            try:
                # Check if session is still active
                session = sm.get_session(self.session_id)
                if not session or session.get("status") != "active":
                    logger.info("Session no longer active, stopping monitor")
                    self._running = False
                    break

                # Poll and process
                events = poll_and_process_orders(
                    trading_ctx=self.trading_ctx,
                    session_id=self.session_id,
                    is_equity=self.is_equity,
                    pin=self.pin,
                    buyback_ticks=self.buyback_ticks,
                    notifier=self.notifier,
                )

                if events:
                    self._event_log.extend(events)
                    if self.on_event:
                        try:
                            self.on_event(events)
                        except Exception:
                            pass

                # Heartbeat
                now = time.time()
                if now - self._last_heartbeat > self._heartbeat_interval:
                    self._send_heartbeat()
                    self._last_heartbeat = now

            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                sm.log_event("ERROR", "monitor",
                             f"Poll error: {e}")
                if self.notifier:
                    self.notifier.error_alert("Monitor", str(e))

            time.sleep(self._poll_interval)

    def _send_heartbeat(self):
        """Send periodic heartbeat via Telegram."""
        try:
            active = len(sm.get_active_sessions())
            placed_sells = len(
                sm.get_placed_sell_orders(self.session_id))
            placed_buys = len(
                sm.get_placed_buy_orders(self.session_id))
            total_open = placed_sells + placed_buys

            if self.notifier:
                self.notifier.heartbeat(active, total_open)

            sm.log_event("DEBUG", "monitor",
                         f"Heartbeat: {active} sessions, "
                         f"{total_open} open orders")
        except Exception:
            pass


class MonitorManager:
    """Manages multiple OrderMonitor instances."""

    def __init__(self):
        self._monitors: Dict[str, OrderMonitor] = {}

    def start_monitor(self, session_id: str, **kwargs) -> OrderMonitor:
        """Create and start a monitor for a session."""
        if session_id in self._monitors:
            existing = self._monitors[session_id]
            if existing.is_running:
                return existing
            # Cleanup dead monitor
            del self._monitors[session_id]

        monitor = OrderMonitor(session_id=session_id, **kwargs)
        monitor.start()
        self._monitors[session_id] = monitor
        return monitor

    def stop_monitor(self, session_id: str):
        """Stop a specific monitor."""
        if session_id in self._monitors:
            self._monitors[session_id].stop()
            del self._monitors[session_id]

    def stop_all(self):
        """Stop all monitors."""
        for sid in list(self._monitors.keys()):
            self.stop_monitor(sid)

    def get_monitor(self, session_id: str) -> Optional[OrderMonitor]:
        return self._monitors.get(session_id)

    @property
    def active_count(self) -> int:
        return sum(1 for m in self._monitors.values() if m.is_running)
