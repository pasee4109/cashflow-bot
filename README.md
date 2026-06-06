# 📈 TFEX Cashflow Ladder — Grid Trading Web App

Multi-user web app for **automated grid trading on TFEX** (and SET) through the
**Settrade Open API** (`settrade-v2`).

- 🔐 **Login with Google** (OIDC). Multi-user — every person signs in with their own Google account.
- 🔗 **Bind multiple Settrade accounts** per user. Credentials are **encrypted at rest** (Fernet) and you can **switch the active account** any time.
- 📊 Portfolio dashboard, ATR-based grid preview, one-click deploy.
- 🪜 Cashflow ladder engine: laddered sell orders capped at ±1 ATR, automatic **buyback** N ticks below each fill — ported from the original engine.
- 🤖 Background monitors poll fills and trigger buybacks per session; optional **Telegram** alerts per account.

> ⚠️ Trading involves real money and risk of loss. Test against a **sandbox/demo** broker account first. Not financial advice.

---

## Architecture

```
┌──────────────┐      /api (cookie auth)      ┌─────────────────────────────┐
│  React (Vite)│ ───────────────────────────▶ │        FastAPI backend       │
│  frontend    │ ◀─────────────────────────── │                              │
└──────────────┘                              │  auth (Google OIDC + JWT)    │
   Login · Accounts · Dashboard               │  accounts vault (encrypted)  │
                                              │  portfolio · grid · monitor  │
                                              └───────────────┬──────────────┘
                                                              │ settrade-v2
                                                ┌─────────────▼─────────────┐
                                                │  Settrade Open API         │
                                                │  Investor → Equity /        │
                                                │  Derivatives / MarketData   │
                                                └────────────────────────────┘
                                                  SQLite/Postgres (users,
                                                  accounts, sessions, orders, logs)
```

### Backend module map (`backend/app`)

| Path | Purpose |
|------|---------|
| `main.py` | FastAPI app, middleware, router wiring, monitor resume on startup |
| `config.py` | Env-driven settings (`pydantic-settings`) |
| `database.py` / `models.py` | SQLAlchemy engine + ORM (User, BrokerAccount, GridSession, GridOrder, BotLog) |
| `security.py` | Fernet encryption for credentials + JWT issue/verify |
| `oauth.py` | Google OIDC client (Authlib) |
| `deps.py` | `get_current_user`, `get_active_account` dependencies |
| `routers/auth.py` | Google login/callback, dev-login, `/me`, logout |
| `routers/accounts.py` | Bind / list / update / delete / **activate** / test-connect / telegram |
| `routers/portfolio.py` | Portfolio of the active account |
| `routers/grid.py` | Preview, deploy, sessions, stop/cancel |
| `routers/logs.py` | Activity log feed |
| `services/grid_logic.py` | Pure ladder/buyback math (tick-aware) |
| `services/market_rules.py` | SET tick table + TFEX ticks + board-lot rules |
| `services/trading.py` | Order placement / cancel / fill-polling |
| `services/monitor.py` | Per-session background monitor threads |
| `services/settrade_manager.py` | Per-account Settrade connection cache |
| `services/portfolio.py` | Portfolio + ATR/candle fetch |
| `services/telegram.py` | Per-account Telegram notifier |
| `services/crud.py` | DB helpers for sessions/orders/logs |

The original Streamlit single-user app is preserved under [`legacy_streamlit/`](./legacy_streamlit).

---

## Quick start (local dev)

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then edit (see below)
uvicorn app.main:app --reload # http://localhost:8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

The Vite dev server proxies `/api` → `http://localhost:8000`, so the auth cookie
stays same-origin. Open **http://localhost:5173**.

Without Google credentials configured you can use the **“Continue (dev)”** button
(enabled by `ALLOW_DEV_LOGIN=true`) to sign in and exercise the full account-binding
and grid flow.

---

## Configuring Google Sign-In

1. Go to the [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials).
2. Create an **OAuth 2.0 Client ID** (type: *Web application*).
3. Add an **Authorised redirect URI** that matches `OAUTH_REDIRECT_URI`:
   - Local dev: `http://localhost:8000/api/auth/google/callback`
   - Docker compose: `http://localhost:8080/api/auth/google/callback`
4. Put the client id/secret in `backend/.env`:

```ini
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxx
OAUTH_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
FRONTEND_URL=http://localhost:5173
ALLOW_DEV_LOGIN=false          # turn off dev login once Google works
```

Generate real secrets:

```bash
python -c "import secrets;print(secrets.token_urlsafe(48))"               # SECRET_KEY
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # APP_ENCRYPTION_KEY
```

> `APP_ENCRYPTION_KEY` encrypts stored Settrade secrets. **If you change it, previously
> stored credentials can no longer be decrypted** — rebind those accounts.

---

## Binding a Settrade account

1. Sign in → go to **Accounts**.
2. Click **Bind a new account** and fill in your Settrade Open API app credentials:
   `Broker ID`, `App ID`, `App Secret`, `App Code`, `Account No`, and `PIN`
   (the PIN is required to place/cancel orders). Pick `Derivative (TFEX)` or `Equity (SET)`.
3. The first account you bind becomes **active** automatically. Bind as many as you like
   and use **Set active** to switch. **Test connect** verifies the credentials against Settrade.

Secrets and PIN are stored encrypted; the API only ever returns a **masked** App ID and never the secret.

---

## Using the bot

On the **Dashboard** (drives the active account):

1. **Refresh portfolio** to load your holdings.
2. Tick the symbols you want to trade.
3. Tune grid parameters (levels, buyback ticks, allocation %, ladder weights).
4. **Preview grid** to see the sell ladder, buyback prices and cashflow per unit.
5. **🚀 Deploy grids** — places the sell ladder and starts a background monitor per symbol.
6. Watch **Grid sessions** (fills, buybacks, open orders, PnL) and the **Activity log**.
   Pause/cancel individual sessions or **Stop all monitors**.

Active monitors are resumed automatically when the backend restarts.

---

## Docker (both services)

```bash
# from repo root
SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))") \
APP_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())") \
docker compose up -d --build
```

Frontend on **http://localhost:8080** (nginx serves the SPA and proxies `/api`
to the backend). Set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` env vars (and the
matching redirect URI) to enable Google login; otherwise leave `ALLOW_DEV_LOGIN=true`.

---

## Security notes

- Settrade **App Secret** and **PIN** are encrypted with Fernet before being written to the DB; they are never returned by the API or logged.
- Sessions use a short-lived signed **JWT** in an `httpOnly` cookie.
- Set `COOKIE_SECURE=true` and serve over HTTPS in production.
- All orders are **LIMIT / DAY** — no market orders; unfilled orders expire at session close.
- Use the **Allocation %** control to cap exposure per symbol.

## Trading logic (unchanged from the original engine)

- **ATR-based sizing** — sells are placed only within **+1 ATR** of the last price.
- **Weighted ladder** — more volume at higher (better) prices (`1×,2×,…`).
- **Tick compliance** — full SET tick table; TFEX per-instrument ticks (S50, GF, …).
- **Volume rules** — SET rounds down to 100-share board lots; TFEX integer contracts ≥ 1.
- **Buyback cycle** — each filled sell places a BUY `N` ticks below the fill, capturing the spread as cashflow.

For the detailed engine writeup see [`legacy_streamlit/README.md`](./legacy_streamlit/README.md).
