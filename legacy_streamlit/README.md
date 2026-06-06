# 📈 Cashflow Ladder Grid Bot

Automated sell-ladder & buyback grid trading engine for the Thai stock market (SET) and derivatives exchange (TFEX), powered by the **settrade-v2** Python API.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  Streamlit UI (app.py)               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ Auth     │ │Portfolio │ │Grid      │ │Log     │ │
│  │ Sidebar  │ │Dashboard │ │Preview   │ │Terminal │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ │
├───────┼────────────┼────────────┼────────────┼──────┤
│       ▼            ▼            ▼            ▼      │
│  ┌─────────┐  ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │auth.py  │  │portfolio │ │grid_     │ │state_  │ │
│  │         │  │.py       │ │engine.py │ │manager │ │
│  └────┬────┘  └────┬─────┘ └────┬─────┘ └───┬────┘ │
│       │            │            │            │      │
│       ▼            ▼            ▼            ▼      │
│  ┌──────────────────────────────────────────────┐   │
│  │           settrade-v2 API Layer              │   │
│  │  Investor → Equity / Derivatives / MarketData│   │
│  └──────────────────────────────────────────────┘   │
│       │                                    │        │
│  ┌────▼─────┐  ┌──────────┐  ┌─────────────▼─────┐ │
│  │order_    │  │market_   │  │telegram_notifier  │ │
│  │monitor.py│  │rules.py  │  │.py                │ │
│  └──────────┘  └──────────┘  └───────────────────┘ │
│       │                                             │
│       ▼                                             │
│  ┌──────────┐                                       │
│  │state.db  │  (SQLite — order persistence)         │
│  └──────────┘                                       │
└─────────────────────────────────────────────────────┘
```

## Module Map

| File | Purpose |
|------|---------|
| `app.py` | Streamlit entry point — UI layout, controls, auto-refresh |
| `auth.py` | Settrade v2 `Investor` initialization and context management |
| `portfolio.py` | Fetch equity/derivative holdings, candlestick data, ATR calculation |
| `grid_engine.py` | Core ladder logic — order generation, placement, buyback cycle |
| `market_rules.py` | SET tick-size table, TFEX ticks, board-lot normalization |
| `order_monitor.py` | Background thread polling order statuses, triggering buybacks |
| `state_manager.py` | SQLite persistence — sessions, orders, logs |
| `telegram_notifier.py` | Telegram Bot API alerts for all bot events |
| `config.py` | Constants, defaults, file paths |

---

## Trading Logic — How the Cashflow Ladder Works

### 1. Grid Sizing (ATR-Based)
The bot calculates the 14-period ATR of the selected asset. Sell orders are placed **only within ±1 ATR** from the last traded price, ensuring the grid adapts to current volatility rather than using fixed spacing.

### 2. Ladder Volume Distribution
Volume is distributed with **increasing weight** at higher price levels:

```
Level 1 (closest):  1× weight  →  smallest volume
Level 2:            2× weight
Level 3:            3× weight
Level 4:            4× weight
Level 5 (farthest): 5× weight  →  largest volume
```

This means more shares/contracts are sold at higher (better) prices.

### 3. Volume Normalization
- **Equity (SET):** All volumes rounded down to board lots of **100 shares**
- **Derivatives (TFEX):** All volumes are **integer contracts ≥ 1**

### 4. Tick-Size Compliance
The SET tick-size table is fully implemented:

| Price Range (THB) | Tick Size |
|---|---|
| < 2 | 0.01 |
| < 5 | 0.02 |
| < 10 | 0.05 |
| < 25 | 0.10 |
| < 50 | 0.25 |
| < 100 | 0.50 |
| < 200 | 1.00 |
| < 400 | 2.00 |
| < 800 | 4.00 |
| ≥ 800 | 6.00 |

### 5. Buyback Cycle
When a sell order is filled, the bot immediately places a **BUY limit order** N ticks below the execution price. This captures the spread as cashflow:

```
SELL filled @ 25.50  →  BUY placed @ 25.20  (3 ticks below)
                        Cashflow = 0.30 × volume
```

---

## Setup & Deployment

### Prerequisites
- Python 3.10+
- A Settrade Open API account (broker app credentials)

### Option A — Local (Recommended for Development)

```bash
# Clone or copy the project
cd cashflow_ladder

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

# Install dependencies
pip install -r requirements.txt

# Run
streamlit run app.py
```

The app opens at `http://localhost:8501`.

### Option B — Docker (Recommended for VPS)

```bash
# Build and run
docker compose up -d --build

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Option C — Ubuntu VPS from Scratch

```bash
# 1. Update system
sudo apt update && sudo apt upgrade -y

# 2. Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# 3. Install Docker Compose
sudo apt install docker-compose-plugin -y

# 4. Clone project
git clone <your-repo> cashflow_ladder
cd cashflow_ladder

# 5. (Optional) Set Telegram env vars
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# 6. Deploy
docker compose up -d --build

# 7. (Optional) Set up systemd auto-restart
sudo tee /etc/systemd/system/cashflow-ladder.service << 'EOF'
[Unit]
Description=Cashflow Ladder Grid Bot
After=docker.service
Requires=docker.service

[Service]
WorkingDirectory=/home/ubuntu/cashflow_ladder
ExecStart=/usr/bin/docker compose up
ExecStop=/usr/bin/docker compose down
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable cashflow-ladder
sudo systemctl start cashflow-ladder
```

---

## Telegram Setup

1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot`
2. Copy the **Bot Token**
3. Message your new bot, then visit:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Find your **Chat ID** in the response JSON
5. Enter both in the app sidebar under "Telegram Alerts"

---

## Configuration Reference

All defaults are in `config.py`:

| Parameter | Default | Description |
|---|---|---|
| `DEFAULT_ALLOCATION_PCT` | 30 | % of holding used per symbol |
| `DEFAULT_GRID_LEVELS` | 5 | Number of sell ladder rungs |
| `DEFAULT_BUYBACK_TICKS` | 3 | Ticks below execution for buyback |
| `DEFAULT_LADDER_WEIGHTS` | [1,2,3,4,5] | Volume multipliers per level |
| `ATR_PERIOD` | 14 | Bars for ATR calculation |
| `ATR_GRID_LIMIT` | 1.0 | Max ± ATR from last price |
| `ORDER_POLL_INTERVAL_SEC` | 5 | Order status check frequency |

---

## Safety Notes

- **Credentials are held in memory only** — never written to disk or logs
- The SQLite database stores order IDs and prices but **no credentials**
- The bot uses **DAY validity** orders — all unfilled orders expire at session close
- Use the **Allocation %** slider to limit exposure (default 30%)
- Always test with a **sandbox/demo account** first
- The bot does **not** use market orders — all orders are limit orders

---

## License

For personal/educational use. Not financial advice. Trading involves risk of loss.
