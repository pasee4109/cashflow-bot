"""
state_manager.py — SQLite Persistence Layer
=============================================
Tracks all grid orders, their status, and relationships
so the bot can resume cleanly after restart.
"""

import sqlite3
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from config import DB_PATH


_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    """Create tables if not present."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS grid_sessions (
            session_id   TEXT PRIMARY KEY,
            symbol       TEXT NOT NULL,
            market_type  TEXT NOT NULL,  -- 'equity' or 'derivative'
            base_price   REAL NOT NULL,
            atr_value    REAL,
            allocation_pct REAL,
            grid_levels  INTEGER,
            status       TEXT DEFAULT 'active',  -- active, paused, closed
            created_at   TEXT DEFAULT (datetime('now','localtime')),
            updated_at   TEXT DEFAULT (datetime('now','localtime')),
            config_json  TEXT  -- full config snapshot
        );

        CREATE TABLE IF NOT EXISTS grid_orders (
            order_id     TEXT PRIMARY KEY,        -- internal tracking ID
            session_id   TEXT NOT NULL,
            broker_order_no TEXT,                  -- Settrade order number
            symbol       TEXT NOT NULL,
            side         TEXT NOT NULL,            -- 'BUY' or 'SELL'
            price        REAL NOT NULL,
            volume       INTEGER NOT NULL,
            grid_level   INTEGER,                  -- 1..N for sell ladder
            status       TEXT DEFAULT 'pending',   -- pending, placed, matched, cancelled, failed
            parent_order TEXT,                      -- links buyback to its parent sell
            matched_price REAL,
            matched_volume INTEGER,
            pnl          REAL,
            created_at   TEXT DEFAULT (datetime('now','localtime')),
            updated_at   TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (session_id) REFERENCES grid_sessions(session_id)
        );

        CREATE TABLE IF NOT EXISTS bot_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (datetime('now','localtime')),
            level     TEXT DEFAULT 'INFO',
            source    TEXT,
            message   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_orders_session
            ON grid_orders(session_id);
        CREATE INDEX IF NOT EXISTS idx_orders_status
            ON grid_orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_broker
            ON grid_orders(broker_order_no);
    """)
    conn.commit()


# ─── Session CRUD ──────────────────────────────────────────────────

def create_session(session_id: str, symbol: str, market_type: str,
                   base_price: float, atr_value: float,
                   allocation_pct: float, grid_levels: int,
                   config: dict) -> None:
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO grid_sessions
        (session_id, symbol, market_type, base_price, atr_value,
         allocation_pct, grid_levels, config_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (session_id, symbol, market_type, base_price, atr_value,
          allocation_pct, grid_levels, json.dumps(config)))
    conn.commit()


def get_session(session_id: str) -> Optional[Dict]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM grid_sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    return dict(row) if row else None


def get_active_sessions() -> List[Dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM grid_sessions WHERE status = 'active'"
    ).fetchall()
    return [dict(r) for r in rows]


def update_session_status(session_id: str, status: str) -> None:
    conn = _get_conn()
    conn.execute("""
        UPDATE grid_sessions
        SET status = ?, updated_at = datetime('now','localtime')
        WHERE session_id = ?
    """, (status, session_id))
    conn.commit()


# ─── Order CRUD ────────────────────────────────────────────────────

def upsert_order(order_id: str, session_id: str, symbol: str,
                 side: str, price: float, volume: int,
                 grid_level: int = 0, parent_order: str = None,
                 broker_order_no: str = None,
                 status: str = "pending") -> None:
    conn = _get_conn()
    conn.execute("""
        INSERT INTO grid_orders
        (order_id, session_id, broker_order_no, symbol, side, price,
         volume, grid_level, status, parent_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(order_id) DO UPDATE SET
            broker_order_no = COALESCE(excluded.broker_order_no, broker_order_no),
            status = excluded.status,
            updated_at = datetime('now','localtime')
    """, (order_id, session_id, broker_order_no, symbol, side, price,
          volume, grid_level, status, parent_order))
    conn.commit()


def update_order_status(order_id: str, status: str,
                        broker_order_no: str = None,
                        matched_price: float = None,
                        matched_volume: int = None,
                        pnl: float = None) -> None:
    conn = _get_conn()
    sets = ["status = ?", "updated_at = datetime('now','localtime')"]
    params: list = [status]

    if broker_order_no:
        sets.append("broker_order_no = ?")
        params.append(broker_order_no)
    if matched_price is not None:
        sets.append("matched_price = ?")
        params.append(matched_price)
    if matched_volume is not None:
        sets.append("matched_volume = ?")
        params.append(matched_volume)
    if pnl is not None:
        sets.append("pnl = ?")
        params.append(pnl)

    params.append(order_id)
    conn.execute(
        f"UPDATE grid_orders SET {', '.join(sets)} WHERE order_id = ?",
        params
    )
    conn.commit()


def get_orders_by_session(session_id: str,
                          status: str = None) -> List[Dict]:
    conn = _get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM grid_orders WHERE session_id = ? AND status = ?",
            (session_id, status)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM grid_orders WHERE session_id = ?",
            (session_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_order_by_broker_no(broker_order_no: str) -> Optional[Dict]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM grid_orders WHERE broker_order_no = ?",
        (broker_order_no,)
    ).fetchone()
    return dict(row) if row else None


def get_placed_sell_orders(session_id: str) -> List[Dict]:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT * FROM grid_orders
        WHERE session_id = ? AND side = 'SELL' AND status = 'placed'
        ORDER BY price ASC
    """, (session_id,)).fetchall()
    return [dict(r) for r in rows]


def get_placed_buy_orders(session_id: str) -> List[Dict]:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT * FROM grid_orders
        WHERE session_id = ? AND side = 'BUY' AND status = 'placed'
        ORDER BY price DESC
    """, (session_id,)).fetchall()
    return [dict(r) for r in rows]


# ─── Logging ───────────────────────────────────────────────────────

def log_event(level: str, source: str, message: str) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO bot_log (level, source, message) VALUES (?, ?, ?)",
        (level, source, message)
    )
    conn.commit()


def get_recent_logs(limit: int = 100) -> List[Dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM bot_log ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_session_pnl(session_id: str) -> Dict[str, Any]:
    """Aggregate PnL for a session."""
    conn = _get_conn()
    row = conn.execute("""
        SELECT
            COUNT(*) FILTER (WHERE side='SELL' AND status='matched') AS sells_matched,
            COUNT(*) FILTER (WHERE side='BUY' AND status='matched') AS buys_matched,
            COALESCE(SUM(pnl), 0) AS total_pnl,
            COUNT(*) FILTER (WHERE status='placed') AS orders_active
        FROM grid_orders WHERE session_id = ?
    """, (session_id,)).fetchone()
    return dict(row) if row else {}


# ─── Cleanup ───────────────────────────────────────────────────────

def purge_old_logs(days: int = 7) -> int:
    conn = _get_conn()
    cur = conn.execute("""
        DELETE FROM bot_log
        WHERE timestamp < datetime('now', 'localtime', ?)
    """, (f"-{days} days",))
    conn.commit()
    return cur.rowcount
