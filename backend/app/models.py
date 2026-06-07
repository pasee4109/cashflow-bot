"""
models.py — ORM models
=======================
Everything is scoped to a User. Settrade credentials live on
BrokerAccount with the sensitive fields encrypted at rest.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    picture: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    accounts: Mapped[list["BrokerAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class BrokerAccount(Base):
    """A bound Settrade Open-API account. Secrets are stored encrypted."""

    __tablename__ = "broker_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    label: Mapped[str] = mapped_column(String(120))          # friendly name
    broker_id: Mapped[str] = mapped_column(String(40))
    app_id: Mapped[str] = mapped_column(String(255))
    app_secret_enc: Mapped[str] = mapped_column(Text)        # encrypted
    app_code: Mapped[str] = mapped_column(String(40))
    account_no: Mapped[str] = mapped_column(String(40))
    pin_enc: Mapped[str | None] = mapped_column(Text)        # encrypted, optional
    account_type: Mapped[str] = mapped_column(String(20), default="derivative")  # derivative | equity

    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)     # simulated, no real broker
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)   # the selected account
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="accounts")


class GridSession(Base):
    __tablename__ = "grid_sessions"

    session_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("broker_accounts.id"), index=True)

    symbol: Mapped[str] = mapped_column(String(40))
    market_type: Mapped[str] = mapped_column(String(20))     # equity | derivative
    base_price: Mapped[float] = mapped_column(Float)
    atr_value: Mapped[float | None] = mapped_column(Float)
    allocation_pct: Mapped[float | None] = mapped_column(Float)
    grid_levels: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | paused | closed
    config_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class GridOrder(Base):
    __tablename__ = "grid_orders"

    order_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("grid_sessions.session_id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("broker_accounts.id"), index=True)

    broker_order_no: Mapped[str | None] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(40))
    side: Mapped[str] = mapped_column(String(8))             # BUY | SELL
    price: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)
    grid_level: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    parent_order: Mapped[str | None] = mapped_column(String(40))
    matched_price: Mapped[float | None] = mapped_column(Float)
    matched_volume: Mapped[int | None] = mapped_column(Integer)
    pnl: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class BotLog(Base):
    __tablename__ = "bot_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, index=True)
    session_id: Mapped[str | None] = mapped_column(String(40), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    level: Mapped[str] = mapped_column(String(12), default="INFO")
    source: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
