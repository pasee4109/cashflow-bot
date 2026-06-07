"""End-to-end API checks through the HTTP layer (Demo mode)."""


def test_requires_auth():
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get("/api/accounts").status_code == 401


def test_full_demo_flow(client):
    # bind + connect a demo account
    r = client.post("/api/accounts/demo", params={"account_type": "derivative"})
    assert r.status_code == 201 and r.json()["is_demo"]
    aid = r.json()["id"]
    assert client.post(f"/api/accounts/{aid}/connect").json()["status"] == "ok"

    # portfolio
    pf = client.get("/api/portfolio").json()
    assert any(p["symbol"] == "S50M24" for p in pf)

    # preview
    params = {"grid_levels": 5, "buyback_ticks": 3, "allocation_pct": 50,
              "ladder_weights": [1, 2, 3, 4, 5]}
    prev = client.post("/api/grid/preview", json={"symbol": "S50M24", **params}).json()
    assert prev["tick_size"] == 0.1
    assert len(prev["levels"]) == 5
    assert all(abs(l["cashflow_per_unit"] - 0.3) < 1e-6 for l in prev["levels"])

    # deploy → active session
    dep = client.post("/api/grid/deploy", json={"symbols": ["S50M24"], **params}).json()
    assert dep[0]["status"] == "active"
    sid = dep[0]["session_id"]

    # cancel cleans up
    assert client.post(f"/api/grid/sessions/{sid}/cancel").json()["status"] == "closed"


def test_switch_active_account_changes_portfolio(client):
    eq = client.post("/api/accounts/demo",
                     params={"account_type": "equity", "label": "Demo SET"}).json()
    client.post(f"/api/accounts/{eq['id']}/activate")
    pf = client.get("/api/portfolio").json()
    assert {p["symbol"] for p in pf} == {"PTT", "KBANK"}


def test_telegram_config_endpoint(client):
    acc = client.post("/api/accounts/demo", params={"account_type": "derivative"}).json()
    r = client.post(f"/api/accounts/{acc['id']}/telegram",
                    json={"bot_token": "", "chat_id": ""})
    assert r.status_code == 200 and r.json()["enabled"] is False
