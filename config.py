"""
config.py — Application Configuration & Defaults
==================================================
"""

import os
from pathlib import Path

# ─── Paths ─────────────────────────────────────────────────────────
APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "state.db"
LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ─── Grid Defaults ─────────────────────────────────────────────────
DEFAULT_ALLOCATION_PCT = 30          # % of holding to use
DEFAULT_GRID_LEVELS = 5              # Number of sell ladder rungs
DEFAULT_BUYBACK_TICKS = 3            # Ticks below execution price for buyback
DEFAULT_LADDER_WEIGHTS = [1, 2, 3, 4, 5]  # Volume multipliers per level
ATR_PERIOD = 14                      # Bars for ATR calculation
ATR_GRID_LIMIT = 1.0                 # Max ± ATR from last price
PRICE_DATA_TIMEFRAME = "1D"          # For ATR calc

# ─── Polling / Monitor ────────────────────────────────────────────
ORDER_POLL_INTERVAL_SEC = 5          # How often to check order status
HEARTBEAT_INTERVAL_SEC = 60          # Telegram heartbeat interval

# ─── Telegram ─────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Market Session (ICT +7) ──────────────────────────────────────
EQUITY_MORNING_OPEN = "09:30"
EQUITY_MORNING_CLOSE = "12:30"
EQUITY_AFTERNOON_OPEN = "14:00"
EQUITY_AFTERNOON_CLOSE = "16:30"

TFEX_MORNING_OPEN = "09:45"
TFEX_MORNING_CLOSE = "12:30"
TFEX_AFTERNOON_OPEN = "14:15"
TFEX_AFTERNOON_CLOSE = "16:55"
TFEX_NIGHT_OPEN = "19:15"
TFEX_NIGHT_CLOSE = "23:55"

# ─── Settrade API Base ────────────────────────────────────────────
SETTRADE_OPEN_API_URL = "https://open-api.settrade.com/api"
