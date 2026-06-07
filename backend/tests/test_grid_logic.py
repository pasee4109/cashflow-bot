"""Pure grid math — ladder shape, ATR cap, buyback, allocation."""

from app.services.grid_logic import (
    calculate_allocation_volume, generate_buyback_order, generate_sell_ladder,
)
from app.services.market_rules import tick_down


def _ladder(**kw):
    base = dict(symbol="S50M24", last_price=920.0, atr_value=8.0, total_volume=5,
                is_equity=False, grid_levels=5, ladder_weights=[1, 2, 3, 4, 5])
    base.update(kw)
    return generate_sell_ladder(**base)


def test_ladder_prices_strictly_ascending():
    orders = _ladder()
    prices = [float(o.price) for o in orders]
    assert prices == sorted(prices)
    assert len(set(prices)) == len(prices)  # no duplicates


def test_ladder_capped_within_one_atr():
    last, atr = 920.0, 8.0
    for o in _ladder(last_price=last, atr_value=atr):
        assert float(o.price) <= last + atr + 1e-9


def test_total_volume_never_exceeds_allocation():
    orders = _ladder(total_volume=5)
    assert sum(o.volume for o in orders) <= 5


def test_allocation_volume():
    assert calculate_allocation_volume(10, 50, is_equity=False) == 5
    assert calculate_allocation_volume(2000, 30, is_equity=True) == 600  # board-lot rounded


def test_buyback_sits_n_ticks_below_fill():
    sell = {"symbol": "S50M24", "order_id": "X", "price": 920.0,
            "volume": 2, "matched_price": 920.0, "matched_volume": 2}
    bb = generate_buyback_order(sell, buyback_ticks=3, is_equity=False)
    assert bb.side == "BUY"
    assert float(bb.price) == float(tick_down(920.0, 3, is_equity=False, symbol="S50M24"))
    assert bb.parent_order == "X"
