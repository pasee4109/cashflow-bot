"""
app.py — Cashflow Ladder Grid Trading Bot
===========================================
Streamlit web application for automated grid trading
on SET/TFEX via the settrade-v2 API.

Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import uuid
import time
import json
import logging
from datetime import datetime
from decimal import Decimal

# ─── Page Config (must be first Streamlit call) ────────────────────
st.set_page_config(
    page_title="Cashflow Ladder Grid Bot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Local Imports ─────────────────────────────────────────────────
from auth import SettradeAuth
from portfolio import (
    fetch_combined_portfolio, get_last_price,
    get_candlestick_data, calculate_atr,
)
from grid_engine import (
    generate_sell_ladder, calculate_allocation_volume,
    place_sell_ladder, cancel_session_orders,
)
from order_monitor import MonitorManager
from telegram_notifier import TelegramNotifier
import state_manager as sm
from config import (
    DEFAULT_ALLOCATION_PCT, DEFAULT_GRID_LEVELS,
    DEFAULT_BUYBACK_TICKS, DEFAULT_LADDER_WEIGHTS,
    ATR_PERIOD,
)
from market_rules import (
    get_equity_tick_size, get_tfex_tick_size, normalize_volume,
)

# ─── Initialize DB ─────────────────────────────────────────────────
sm.init_db()

# ─── Logging ───────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cashflow_ladder")

# ─── Custom CSS ────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=DM+Sans:wght@400;500;700&display=swap');

    .stApp {
        font-family: 'DM Sans', sans-serif;
    }

    .main-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0d9488 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .main-header h1 {
        margin: 0;
        font-size: 1.8rem;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    .main-header p {
        margin: 0.3rem 0 0 0;
        opacity: 0.8;
        font-size: 0.95rem;
    }

    .status-badge {
        display: inline-block;
        padding: 3px 12px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .badge-connected { background: #059669; color: white; }
    .badge-disconnected { background: #dc2626; color: white; }
    .badge-active { background: #2563eb; color: white; }
    .badge-paused { background: #d97706; color: white; }

    .metric-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        text-align: center;
    }
    .metric-card .value {
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.5rem;
        font-weight: 600;
        color: #0f172a;
    }
    .metric-card .label {
        font-size: 0.8rem;
        color: #64748b;
        margin-top: 2px;
    }

    .log-terminal {
        background: #0f172a;
        color: #94a3b8;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.78rem;
        padding: 1rem;
        border-radius: 8px;
        max-height: 400px;
        overflow-y: auto;
        line-height: 1.6;
        border: 1px solid #1e293b;
    }
    .log-info { color: #38bdf8; }
    .log-warn { color: #fbbf24; }
    .log-error { color: #f87171; }
    .log-success { color: #4ade80; }

    div[data-testid="stSidebar"] {
        background: #0f172a;
    }
    div[data-testid="stSidebar"] .stMarkdown,
    div[data-testid="stSidebar"] label,
    div[data-testid="stSidebar"] .stText {
        color: #e2e8f0 !important;
    }

    .grid-preview-table th {
        background: #1e293b;
        color: #e2e8f0;
        padding: 8px 12px;
        font-size: 0.8rem;
    }
    .grid-preview-table td {
        padding: 6px 12px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.82rem;
    }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# SESSION STATE INITIALIZATION
# ═══════════════════════════════════════════════════════════════════

def init_session_state():
    defaults = {
        "auth": SettradeAuth(),
        "monitor_mgr": MonitorManager(),
        "notifier": TelegramNotifier(),
        "portfolio_df": pd.DataFrame(),
        "selected_symbols": [],
        "active_sessions": {},
        "log_messages": [],
        "bot_running": False,
        "pin": "",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_session_state()


def add_log(message: str, level: str = "INFO"):
    """Add a message to the in-memory log and DB."""
    ts = datetime.now().strftime("%H:%M:%S")
    entry = {"time": ts, "level": level, "message": message}
    st.session_state.log_messages.insert(0, entry)
    # Keep last 500
    st.session_state.log_messages = st.session_state.log_messages[:500]
    sm.log_event(level, "app", message)


# ═══════════════════════════════════════════════════════════════════
# SIDEBAR — Authentication & Settings
# ═══════════════════════════════════════════════════════════════════

def render_sidebar():
    auth: SettradeAuth = st.session_state.auth

    with st.sidebar:
        st.markdown("### 🔐 Settrade API Login")

        if auth.is_connected:
            st.markdown(
                '<span class="status-badge badge-connected">● Connected</span>',
                unsafe_allow_html=True,
            )
            st.caption(
                f"Account: {auth.get_account_info()} | "
                f"Broker: {auth.get_broker_id()}"
            )
            if st.button("🔌 Disconnect", use_container_width=True):
                st.session_state.monitor_mgr.stop_all()
                auth.disconnect()
                st.session_state.bot_running = False
                st.session_state.portfolio_df = pd.DataFrame()
                add_log("Disconnected from Settrade API", "WARN")
                st.rerun()
        else:
            st.markdown(
                '<span class="status-badge badge-disconnected">'
                '● Disconnected</span>',
                unsafe_allow_html=True,
            )

            with st.form("login_form"):
                broker_id = st.text_input("Broker ID", placeholder="e.g., SANDBOX")
                app_id = st.text_input("App ID")
                app_secret = st.text_input("App Secret", type="password")
                app_code = st.text_input("App Code")
                account_no = st.text_input("Account No")
                pin = st.text_input("PIN", type="password")

                submitted = st.form_submit_button(
                    "🔑 Connect", use_container_width=True
                )

                if submitted:
                    if not all([broker_id, app_id, app_secret, app_code]):
                        st.error("Please fill all required fields")
                    else:
                        with st.spinner("Authenticating..."):
                            result = auth.connect(
                                app_id=app_id,
                                app_secret=app_secret,
                                app_code=app_code,
                                broker_id=broker_id,
                                account_no=account_no,
                            )
                        if result["status"] == "ok":
                            st.session_state.pin = pin
                            add_log("Connected to Settrade API", "INFO")
                            st.success("Connected!")
                            st.rerun()
                        else:
                            st.error(f"Failed: {result['message']}")

        st.markdown("---")

        # ─── Telegram Settings ─────────────────────────────────────
        st.markdown("### 📬 Telegram Alerts")
        with st.expander("Configure", expanded=False):
            tg_token = st.text_input(
                "Bot Token", type="password",
                value=st.session_state.notifier.bot_token,
                key="tg_token",
            )
            tg_chat = st.text_input(
                "Chat ID",
                value=st.session_state.notifier.chat_id,
                key="tg_chat",
            )
            if st.button("💾 Save Telegram Config"):
                st.session_state.notifier = TelegramNotifier(
                    tg_token, tg_chat
                )
                if st.session_state.notifier.enabled:
                    st.success("Telegram configured!")
                    add_log("Telegram notifications enabled")
                else:
                    st.warning("Provide both token and chat ID")

        st.markdown("---")

        # ─── Grid Parameters ──────────────────────────────────────
        st.markdown("### ⚙️ Grid Parameters")

        st.session_state["grid_levels"] = st.slider(
            "Grid Levels", 2, 10, DEFAULT_GRID_LEVELS, key="sl_levels"
        )
        st.session_state["buyback_ticks"] = st.slider(
            "Buyback Ticks Below", 1, 10, DEFAULT_BUYBACK_TICKS,
            key="sl_buyback",
        )
        st.session_state["allocation_pct"] = st.slider(
            "Allocation %", 5, 100, DEFAULT_ALLOCATION_PCT,
            key="sl_alloc",
        )

        weights_str = st.text_input(
            "Ladder Weights (comma-sep)",
            value=",".join(str(w) for w in DEFAULT_LADDER_WEIGHTS),
            key="inp_weights",
        )
        try:
            st.session_state["ladder_weights"] = [
                int(w.strip()) for w in weights_str.split(",") if w.strip()
            ]
        except ValueError:
            st.session_state["ladder_weights"] = DEFAULT_LADDER_WEIGHTS

        st.session_state["poll_interval"] = st.number_input(
            "Poll Interval (sec)", 3, 60, 5, key="inp_poll"
        )


# ═══════════════════════════════════════════════════════════════════
# MAIN CONTENT — Header
# ═══════════════════════════════════════════════════════════════════

def render_header():
    st.markdown("""
    <div class="main-header">
        <h1>📈 Cashflow Ladder Grid Bot</h1>
        <p>Automated sell-ladder & buyback engine for SET/TFEX via Settrade v2 API</p>
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# PORTFOLIO DASHBOARD
# ═══════════════════════════════════════════════════════════════════

def render_portfolio():
    auth: SettradeAuth = st.session_state.auth

    st.markdown("## 📊 Portfolio & Asset Selection")

    if not auth.is_connected:
        st.info("🔑 Connect to Settrade API in the sidebar to view your portfolio.")
        return

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("🔄 Refresh Portfolio", use_container_width=True):
            with st.spinner("Fetching portfolio..."):
                df = fetch_combined_portfolio(
                    auth.equity_ctx, auth.deriv_ctx
                )
                st.session_state.portfolio_df = df
                add_log(f"Portfolio refreshed: {len(df)} positions")

    df = st.session_state.portfolio_df

    if df.empty:
        st.warning("No portfolio data. Click 'Refresh Portfolio' above.")
        return

    # ─── Display Portfolio Table ───────────────────────────────────
    st.markdown("#### Holdings")

    # Format for display
    display_df = df.copy()
    for col in ["avg_cost", "market_price", "market_value", "unrealized_pnl"]:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(
                lambda x: f"{x:,.2f}" if pd.notnull(x) else "—"
            )

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "symbol": st.column_config.TextColumn("Symbol", width="medium"),
            "market_type": st.column_config.TextColumn("Market", width="small"),
            "volume": st.column_config.NumberColumn("Volume", format="%d"),
            "avg_cost": st.column_config.TextColumn("Avg Cost"),
            "market_price": st.column_config.TextColumn("Mkt Price"),
            "market_value": st.column_config.TextColumn("Mkt Value"),
            "unrealized_pnl": st.column_config.TextColumn("Unrealized P&L"),
        },
    )

    # ─── Symbol Selection ──────────────────────────────────────────
    st.markdown("#### Select Assets for Grid Trading")

    symbols = df["symbol"].unique().tolist()

    col_sel, col_btn = st.columns([4, 1])
    with col_btn:
        if st.button("☑️ Select All"):
            st.session_state.selected_symbols = symbols
            st.rerun()

    with col_sel:
        selected = st.multiselect(
            "Choose symbols:",
            options=symbols,
            default=st.session_state.selected_symbols,
            key="ms_symbols",
        )
        st.session_state.selected_symbols = selected


# ═══════════════════════════════════════════════════════════════════
# GRID PREVIEW & DEPLOYMENT
# ═══════════════════════════════════════════════════════════════════

def render_grid_preview():
    auth: SettradeAuth = st.session_state.auth
    selected = st.session_state.selected_symbols
    df = st.session_state.portfolio_df

    if not selected or df.empty:
        return

    st.markdown("## 🎯 Grid Preview & Deployment")

    allocation_pct = st.session_state.get("allocation_pct", DEFAULT_ALLOCATION_PCT)
    grid_levels = st.session_state.get("grid_levels", DEFAULT_GRID_LEVELS)
    ladder_weights = st.session_state.get("ladder_weights", DEFAULT_LADDER_WEIGHTS)
    buyback_ticks = st.session_state.get("buyback_ticks", DEFAULT_BUYBACK_TICKS)

    tabs = st.tabs(selected)

    for tab, symbol in zip(tabs, selected):
        with tab:
            row = df[df["symbol"] == symbol].iloc[0]
            is_equity = row["market_type"] == "equity"
            total_holding = abs(int(row["volume"]))

            # Get current price and ATR
            last_price = None
            atr_value = 0.0

            if auth.market_data_ctx:
                last_price = get_last_price(auth.market_data_ctx, symbol)
                candles = get_candlestick_data(
                    auth.market_data_ctx, symbol, limit=ATR_PERIOD + 5
                )
                if not candles.empty:
                    atr_value = calculate_atr(candles, ATR_PERIOD)

            if last_price is None:
                last_price = float(row.get("market_price", 0) or 0)

            if last_price <= 0:
                st.error(f"Cannot determine price for {symbol}")
                continue

            # Calculate allocation
            alloc_volume = calculate_allocation_volume(
                total_holding, allocation_pct, is_equity
            )

            # Show metrics
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1:
                st.metric("Last Price", f"{last_price:,.2f}")
            with c2:
                st.metric("ATR(14)", f"{atr_value:,.2f}")
            with c3:
                tick = (get_equity_tick_size(last_price) if is_equity
                        else get_tfex_tick_size(symbol))
                st.metric("Tick Size", f"{tick}")
            with c4:
                st.metric("Holding", f"{total_holding:,}")
            with c5:
                st.metric(f"Alloc ({allocation_pct}%)",
                          f"{alloc_volume:,}")

            # Generate preview
            if atr_value <= 0:
                # Fallback ATR estimate: 2% of price
                atr_value = last_price * 0.02
                st.caption(f"⚠️ ATR unavailable — using estimate: {atr_value:.2f}")

            orders = generate_sell_ladder(
                symbol=symbol,
                last_price=last_price,
                atr_value=atr_value,
                total_volume=alloc_volume,
                is_equity=is_equity,
                grid_levels=grid_levels,
                ladder_weights=ladder_weights,
            )

            # Preview table
            preview_data = []
            for o in orders:
                spread = float(o.price) - last_price
                spread_pct = (spread / last_price) * 100
                from market_rules import tick_down
                bb_price = tick_down(
                    float(o.price), buyback_ticks, is_equity, symbol
                )
                preview_data.append({
                    "Level": f"L{o.grid_level}",
                    "Sell Price": f"{float(o.price):,.2f}",
                    "Volume": f"{o.volume:,}",
                    "Spread": f"+{spread:.2f} ({spread_pct:+.2f}%)",
                    "Buyback @": f"{float(bb_price):,.2f}",
                    "Cashflow/unit": f"{float(o.price) - float(bb_price):.2f}",
                })

            st.dataframe(
                pd.DataFrame(preview_data),
                use_container_width=True,
                hide_index=True,
            )

            total_vol = sum(o.volume for o in orders)
            if orders:
                price_range = (
                    f"{float(orders[0].price):,.2f} — "
                    f"{float(orders[-1].price):,.2f}"
                )
            else:
                price_range = "N/A"

            st.caption(
                f"Total sell volume: **{total_vol:,}** | "
                f"Price range: **{price_range}** | "
                f"Max range: ±1 ATR = **{atr_value:.2f}**"
            )

            # Store preview for deployment
            st.session_state[f"preview_{symbol}"] = {
                "orders": orders,
                "last_price": last_price,
                "atr_value": atr_value,
                "is_equity": is_equity,
                "alloc_volume": alloc_volume,
            }


# ═══════════════════════════════════════════════════════════════════
# DEPLOYMENT CONTROLS
# ═══════════════════════════════════════════════════════════════════

def render_deployment():
    auth: SettradeAuth = st.session_state.auth
    selected = st.session_state.selected_symbols

    if not selected or not auth.is_connected:
        return

    st.markdown("## 🚀 Deployment Controls")

    col1, col2, col3 = st.columns(3)

    with col1:
        deploy_btn = st.button(
            "🟢 Deploy All Grids",
            use_container_width=True,
            disabled=st.session_state.bot_running,
            type="primary",
        )

    with col2:
        stop_btn = st.button(
            "🔴 Stop All Monitors",
            use_container_width=True,
            disabled=not st.session_state.bot_running,
        )

    with col3:
        cancel_btn = st.button(
            "❌ Cancel All Orders",
            use_container_width=True,
        )

    buyback_ticks = st.session_state.get("buyback_ticks", DEFAULT_BUYBACK_TICKS)
    pin = st.session_state.get("pin", "")

    # ─── Deploy ────────────────────────────────────────────────────
    if deploy_btn:
        notifier: TelegramNotifier = st.session_state.notifier
        notifier.bot_started(selected)

        progress = st.progress(0.0)
        status_text = st.empty()

        for i, symbol in enumerate(selected):
            preview = st.session_state.get(f"preview_{symbol}")
            if not preview or not preview["orders"]:
                add_log(f"No preview for {symbol}, skipping", "WARN")
                continue

            is_equity = preview["is_equity"]
            orders = preview["orders"]

            # Determine trading context
            trading_ctx = (auth.equity_ctx if is_equity
                           else auth.deriv_ctx)
            if not trading_ctx:
                add_log(f"No trading context for {symbol}", "ERROR")
                continue

            # Create session
            session_id = f"GS-{uuid.uuid4().hex[:8].upper()}"
            sm.create_session(
                session_id=session_id,
                symbol=symbol,
                market_type="equity" if is_equity else "derivative",
                base_price=preview["last_price"],
                atr_value=preview["atr_value"],
                allocation_pct=st.session_state.get(
                    "allocation_pct", DEFAULT_ALLOCATION_PCT),
                grid_levels=len(orders),
                config={
                    "ladder_weights": st.session_state.get(
                        "ladder_weights", DEFAULT_LADDER_WEIGHTS),
                    "buyback_ticks": buyback_ticks,
                    "alloc_volume": preview["alloc_volume"],
                },
            )

            status_text.text(f"Placing {len(orders)} sell orders for {symbol}...")

            # Place orders
            results = place_sell_ladder(
                trading_ctx=trading_ctx,
                session_id=session_id,
                orders=orders,
                is_equity=is_equity,
                pin=pin,
            )

            placed = sum(1 for r in results if r["status"] == "placed")
            failed = sum(1 for r in results if r["status"] == "failed")

            add_log(
                f"📤 {symbol}: {placed} placed, {failed} failed "
                f"(session: {session_id})"
            )

            if orders:
                price_range = (
                    f"{float(orders[0].price):,.2f}-"
                    f"{float(orders[-1].price):,.2f}"
                )
                notifier.orders_placed(symbol, "SELL", placed, price_range)

            # Start monitor
            monitor = st.session_state.monitor_mgr.start_monitor(
                session_id=session_id,
                trading_ctx=trading_ctx,
                is_equity=is_equity,
                pin=pin,
                buyback_ticks=buyback_ticks,
                notifier=notifier,
            )

            st.session_state.active_sessions[session_id] = {
                "symbol": symbol,
                "is_equity": is_equity,
                "placed": placed,
                "failed": failed,
                "started_at": datetime.now().strftime("%H:%M:%S"),
            }

            progress.progress((i + 1) / len(selected))

        status_text.text("✅ All grids deployed!")
        st.session_state.bot_running = True
        add_log("🟢 Bot deployed — all monitors active")
        time.sleep(1)
        st.rerun()

    # ─── Stop ──────────────────────────────────────────────────────
    if stop_btn:
        st.session_state.monitor_mgr.stop_all()
        st.session_state.bot_running = False

        for sid in st.session_state.active_sessions:
            sm.update_session_status(sid, "paused")

        add_log("🔴 All monitors stopped", "WARN")
        st.session_state.notifier.bot_stopped()
        st.rerun()

    # ─── Cancel ────────────────────────────────────────────────────
    if cancel_btn:
        total_cancelled = 0
        for sid, info in st.session_state.active_sessions.items():
            is_equity = info["is_equity"]
            trading_ctx = (auth.equity_ctx if is_equity
                           else auth.deriv_ctx)
            if trading_ctx:
                n = cancel_session_orders(
                    trading_ctx, sid, is_equity, pin
                )
                total_cancelled += n
                sm.update_session_status(sid, "closed")

        st.session_state.monitor_mgr.stop_all()
        st.session_state.bot_running = False
        add_log(f"❌ Cancelled {total_cancelled} orders", "WARN")
        st.rerun()


# ═══════════════════════════════════════════════════════════════════
# ACTIVE SESSIONS DASHBOARD
# ═══════════════════════════════════════════════════════════════════

def render_active_sessions():
    sessions = st.session_state.active_sessions

    if not sessions:
        return

    st.markdown("## 📋 Active Sessions")

    for sid, info in sessions.items():
        session_data = sm.get_session(sid)
        if not session_data:
            continue

        status = session_data.get("status", "unknown")
        badge_class = "badge-active" if status == "active" else "badge-paused"

        with st.expander(
            f"**{info['symbol']}** — `{sid}` | {status.upper()}",
            expanded=(status == "active"),
        ):
            # Session metrics
            pnl_data = sm.get_session_pnl(sid)
            orders = sm.get_orders_by_session(sid)

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                sells_matched = pnl_data.get("sells_matched", 0)
                st.metric("Sells Matched", sells_matched)
            with c2:
                buys_matched = pnl_data.get("buys_matched", 0)
                st.metric("Buybacks Matched", buys_matched)
            with c3:
                total_pnl = pnl_data.get("total_pnl", 0)
                st.metric("Total PnL",
                          f"{total_pnl:+,.2f}",
                          delta=f"{total_pnl:+,.2f}" if total_pnl else None)
            with c4:
                active_orders = pnl_data.get("orders_active", 0)
                st.metric("Open Orders", active_orders)

            # Order table
            if orders:
                order_df = pd.DataFrame(orders)
                cols_to_show = [
                    "order_id", "side", "price", "volume",
                    "grid_level", "status", "matched_price", "pnl",
                ]
                cols_to_show = [c for c in cols_to_show
                                if c in order_df.columns]
                st.dataframe(
                    order_df[cols_to_show],
                    use_container_width=True,
                    hide_index=True,
                )


# ═══════════════════════════════════════════════════════════════════
# LIVE LOG TERMINAL
# ═══════════════════════════════════════════════════════════════════

def render_log_terminal():
    st.markdown("## 📟 Activity Log")

    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("🗑️ Clear Logs"):
            st.session_state.log_messages = []
            st.rerun()
        if st.button("🔄 Refresh"):
            st.rerun()

    logs = st.session_state.log_messages
    if not logs:
        # Load from DB
        db_logs = sm.get_recent_logs(100)
        for entry in db_logs:
            logs.append({
                "time": entry.get("timestamp", "")[-8:],
                "level": entry.get("level", "INFO"),
                "message": entry.get("message", ""),
            })

    if not logs:
        st.caption("No log entries yet.")
        return

    log_html_lines = []
    for entry in logs[:200]:
        level = entry["level"]
        css_class = {
            "INFO": "log-info",
            "WARN": "log-warn",
            "WARNING": "log-warn",
            "ERROR": "log-error",
            "SUCCESS": "log-success",
            "DEBUG": "",
        }.get(level, "")

        line = (
            f'<span style="color:#475569">{entry["time"]}</span> '
            f'<span class="{css_class}">[{level:5s}]</span> '
            f'{entry["message"]}'
        )
        log_html_lines.append(line)

    log_content = "<br>".join(log_html_lines)
    st.markdown(
        f'<div class="log-terminal">{log_content}</div>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════════
# MAIN LAYOUT
# ═══════════════════════════════════════════════════════════════════

def main():
    render_sidebar()
    render_header()

    # ─── Status Bar ────────────────────────────────────────────────
    auth: SettradeAuth = st.session_state.auth
    monitor_mgr: MonitorManager = st.session_state.monitor_mgr

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        conn_status = "Connected" if auth.is_connected else "Disconnected"
        st.markdown(f"""
        <div class="metric-card">
            <div class="value">{"🟢" if auth.is_connected else "🔴"}</div>
            <div class="label">API: {conn_status}</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        tg_status = "On" if st.session_state.notifier.enabled else "Off"
        st.markdown(f"""
        <div class="metric-card">
            <div class="value">{"📬" if st.session_state.notifier.enabled else "📭"}</div>
            <div class="label">Telegram: {tg_status}</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="value">{monitor_mgr.active_count}</div>
            <div class="label">Active Monitors</div>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        n_sessions = len(st.session_state.active_sessions)
        st.markdown(f"""
        <div class="metric-card">
            <div class="value">{n_sessions}</div>
            <div class="label">Grid Sessions</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # ─── Main Sections ─────────────────────────────────────────────
    render_portfolio()

    if st.session_state.selected_symbols:
        st.markdown("---")
        render_grid_preview()
        st.markdown("---")
        render_deployment()

    if st.session_state.active_sessions:
        st.markdown("---")
        render_active_sessions()

    st.markdown("---")
    render_log_terminal()

    # ─── Auto-refresh when bot is running ──────────────────────────
    if st.session_state.bot_running:
        poll_sec = st.session_state.get("poll_interval", 5)
        time.sleep(poll_sec)
        st.rerun()


if __name__ == "__main__":
    main()
