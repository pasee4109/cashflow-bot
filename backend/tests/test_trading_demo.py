"""Order placement, fill detection, buyback and PnL — via the demo broker."""

import app.services.demo as demo
from app.database import SessionLocal
from app.services import crud, trading
from app.services.demo import build_demo_contexts
from app.services.grid_logic import generate_sell_ladder


def test_fill_triggers_buyback_and_books_pnl(monkeypatch):
    monkeypatch.setattr(demo, "_FILL_PROB", 1.0)  # deterministic fills
    db = SessionLocal()
    _, deriv, _ = build_demo_contexts("derivative")

    crud.create_session(db, session_id="T1", user_id=1, account_id=1,
                        symbol="S50M24", market_type="derivative", base_price=920.0,
                        atr_value=8.0, allocation_pct=50, grid_levels=3,
                        config={"buyback_ticks": 3})

    orders = generate_sell_ladder("S50M24", 920.0, 8.0, 3, is_equity=False,
                                  grid_levels=3, ladder_weights=[1, 1, 1])
    res = trading.place_sell_ladder(db, deriv, session_id="T1", account_id=1,
                                    orders=orders, is_equity=False, pin="DEMO")
    assert all(r["status"] == "placed" for r in res)

    ev1 = trading.poll_and_process(db, deriv, session_id="T1", account_id=1,
                                   is_equity=False, pin="DEMO", buyback_ticks=3)
    assert any(e["type"] == "sell_matched" for e in ev1)

    # second poll guarantees the buyback orders are seen as matched
    trading.poll_and_process(db, deriv, session_id="T1", account_id=1,
                             is_equity=False, pin="DEMO", buyback_ticks=3)

    pnl = crud.session_pnl(db, "T1")
    assert pnl["sells_matched"] == 3
    assert pnl["buys_matched"] >= 1
    # each buyback captures 3 ticks * 0.1 = 0.30 per contract
    assert pnl["total_pnl"] > 0
    db.close()


def test_cancel_marks_orders_cancelled():
    db = SessionLocal()
    _, deriv, _ = build_demo_contexts("derivative")
    crud.create_session(db, session_id="T2", user_id=1, account_id=1,
                        symbol="S50M24", market_type="derivative", base_price=920.0,
                        atr_value=8.0, allocation_pct=50, grid_levels=2,
                        config={"buyback_ticks": 3})
    orders = generate_sell_ladder("S50M24", 920.0, 8.0, 2, is_equity=False,
                                  grid_levels=2, ladder_weights=[1, 1])
    trading.place_sell_ladder(db, deriv, session_id="T2", account_id=1,
                              orders=orders, is_equity=False, pin="DEMO")
    n = trading.cancel_session_orders(db, deriv, session_id="T2", pin="DEMO")
    assert n == 2
    assert crud.get_placed_sell_orders(db, "T2") == []
    db.close()
