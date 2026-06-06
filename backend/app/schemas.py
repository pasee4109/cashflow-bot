"""
schemas.py — Pydantic request/response models
==============================================
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ─── Auth ──────────────────────────────────────────────────────────

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str | None = None
    picture: str | None = None


# ─── Broker accounts ───────────────────────────────────────────────

class BrokerAccountCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
    broker_id: str
    app_id: str
    app_secret: str
    app_code: str
    account_no: str
    pin: str | None = None
    account_type: str = "derivative"      # derivative | equity


class BrokerAccountUpdate(BaseModel):
    label: str | None = None
    broker_id: str | None = None
    app_id: str | None = None
    app_secret: str | None = None         # only re-stored when provided
    app_code: str | None = None
    account_no: str | None = None
    pin: str | None = None
    account_type: str | None = None


class BrokerAccountOut(BaseModel):
    """Never exposes secrets — only metadata + masked fields."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    broker_id: str
    app_id_masked: str
    account_no: str
    account_type: str
    is_active: bool
    has_pin: bool
    last_connected_at: datetime | None = None
    created_at: datetime


# ─── Portfolio ─────────────────────────────────────────────────────

class PortfolioRow(BaseModel):
    symbol: str
    market_type: str
    volume: float
    avg_cost: float = 0.0
    market_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    pct_change: float = 0.0


# ─── Grid ──────────────────────────────────────────────────────────

class GridParams(BaseModel):
    grid_levels: int = 5
    buyback_ticks: int = 3
    allocation_pct: int = 30
    ladder_weights: list[int] = [1, 2, 3, 4, 5]


class GridPreviewRequest(GridParams):
    symbol: str


class GridLevelOut(BaseModel):
    level: int
    sell_price: float
    volume: int
    spread: float
    spread_pct: float
    buyback_price: float
    cashflow_per_unit: float


class GridPreviewOut(BaseModel):
    symbol: str
    market_type: str
    last_price: float
    atr_value: float
    tick_size: float
    holding: int
    alloc_volume: int
    total_sell_volume: int
    price_range: str
    levels: list[GridLevelOut]


class GridDeployRequest(GridParams):
    symbols: list[str]


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    session_id: str
    symbol: str
    market_type: str
    status: str
    base_price: float
    atr_value: float | None = None
    grid_levels: int | None = None
    created_at: datetime
    sells_matched: int = 0
    buys_matched: int = 0
    total_pnl: float = 0.0
    orders_active: int = 0


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    order_id: str
    session_id: str
    side: str
    symbol: str
    price: float
    volume: int
    grid_level: int
    status: str
    matched_price: float | None = None
    pnl: float | None = None


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    timestamp: datetime
    level: str
    source: str | None = None
    message: str


# ─── Telegram ──────────────────────────────────────────────────────

class TelegramConfig(BaseModel):
    bot_token: str = ""
    chat_id: str = ""
