"""
verify_demo.py — Automated end-to-end correctness check (Demo mode)
===================================================================
Runs the whole app in-process against a throwaway DB using Demo mode
(no real broker needed) and asserts every step behaves correctly:

    login → bind demo account → connect → portfolio → grid preview
    (tick/ATR/buyback math) → deploy → simulated fills → buyback → PnL

Run from the backend/ directory:

    python verify_demo.py

Exits 0 and prints a PASS report if everything checks out, else exits 1.
"""

import os
import sys
import tempfile
import time

os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.mktemp(suffix=".db"))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

PASS, FAIL = "\033[92m✓\033[0m", "\033[91m✗\033[0m"
checks = []


def check(label, ok, detail=""):
    checks.append(ok)
    print(f"  {PASS if ok else FAIL} {label}" + (f"  → {detail}" if detail else ""))


def main():
    init_db()
    c = TestClient(app)

    print("\n1) Auth")
    r = c.post("/api/auth/dev-login", params={"email": "verify@example.com"})
    check("dev login issues session", r.status_code == 200, r.json().get("user", {}).get("email"))
    check("authenticated /me works", c.get("/api/auth/me").status_code == 200)

    print("\n2) Bind & connect demo account")
    r = c.post("/api/accounts/demo", params={"account_type": "derivative"})
    acc = r.json()
    check("demo account created", r.status_code == 201 and acc["is_demo"], acc["label"])
    check("first account auto-activated", acc["is_active"] is True)
    conn = c.post(f"/api/accounts/{acc['id']}/connect").json()
    check("connect reports contexts", conn.get("status") == "ok" and conn.get("derivatives"))

    print("\n3) Portfolio")
    pf = c.get("/api/portfolio").json()
    syms = {p["symbol"] for p in pf}
    check("portfolio returns demo holdings", "S50M24" in syms, ", ".join(sorted(syms)))

    print("\n4) Grid preview — tick / ATR / buyback math")
    params = {"grid_levels": 5, "buyback_ticks": 3, "allocation_pct": 50,
              "ladder_weights": [1, 2, 3, 4, 5]}
    p = c.post("/api/grid/preview", json={"symbol": "S50M24", **params}).json()
    check("S50 tick size = 0.1", abs(p["tick_size"] - 0.1) < 1e-9, p["tick_size"])
    check("ATR computed (> 0)", p["atr_value"] > 0, p["atr_value"])
    check("5 ladder levels generated", len(p["levels"]) == 5)
    asc = all(p["levels"][i]["sell_price"] < p["levels"][i + 1]["sell_price"]
              for i in range(len(p["levels"]) - 1))
    check("sell prices strictly ascending", asc)
    within_atr = all(l["sell_price"] <= p["last_price"] + p["atr_value"] + 1e-6
                     for l in p["levels"])
    check("all levels within +1 ATR", within_atr)
    # buyback should sit exactly buyback_ticks below the sell (3 × 0.1 = 0.30)
    expected_cf = round(params["buyback_ticks"] * p["tick_size"], 4)
    cf_ok = all(abs(l["cashflow_per_unit"] - expected_cf) < 1e-6 for l in p["levels"])
    check(f"buyback = {params['buyback_ticks']} ticks below "
          f"(cashflow/unit = {expected_cf})", cf_ok)

    print("\n5) Deploy")
    dep = c.post("/api/grid/deploy", json={"symbols": ["S50M24"], **params}).json()
    sess = dep[0]
    check("session created & active", sess["status"] == "active", sess["session_id"])
    check("sell orders placed", sess["orders_active"] > 0, f"{sess['orders_active']} open")

    print("\n6) Simulated fills → buyback → PnL  (polling up to 30s)")
    s = sess
    for _ in range(15):
        time.sleep(2)
        s = c.get("/api/grid/sessions").json()[0]
        if s["buys_matched"] > 0:
            break
    check("sells matched (fills detected)", s["sells_matched"] > 0, f"{s['sells_matched']} sells")
    check("buybacks placed & matched", s["buys_matched"] > 0, f"{s['buys_matched']} buys")
    check("PnL accrued from spread", s["total_pnl"] > 0, f"{s['total_pnl']:.2f} THB")

    print("\n7) Account switching & isolation")
    r2 = c.post("/api/accounts/demo", params={"account_type": "equity"})
    a2 = r2.json()
    check("second account NOT auto-active", a2["is_active"] is False)
    c.post(f"/api/accounts/{a2['id']}/activate")
    lst = c.get("/api/accounts").json()
    active = [a for a in lst if a["is_active"]]
    check("exactly one active after switch", len(active) == 1 and active[0]["id"] == a2["id"])
    pf2 = c.get("/api/portfolio").json()
    check("active switch changes portfolio", {x["symbol"] for x in pf2} == {"PTT", "KBANK"},
          ", ".join(sorted(x["symbol"] for x in pf2)))

    print("\n8) Security at rest")
    c.post("/api/auth/logout")
    check("unauthenticated request blocked (401)",
          TestClient(app).get("/api/accounts").status_code == 401)

    total, passed = len(checks), sum(checks)
    print("\n" + "=" * 60)
    if passed == total:
        print(f"\033[92mPASS\033[0m — {passed}/{total} checks succeeded. "
              f"The app runs correctly end to end.")
        return 0
    print(f"\033[91mFAIL\033[0m — {passed}/{total} checks passed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
