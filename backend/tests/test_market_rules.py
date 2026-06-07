"""Tick-size, volume and tick-counting rules (SET + TFEX)."""

from decimal import Decimal

from app.services import market_rules as mr


def test_set_equity_tick_sizes():
    assert mr.get_equity_tick_size(1.5) == Decimal("0.01")
    assert mr.get_equity_tick_size(3) == Decimal("0.02")
    assert mr.get_equity_tick_size(35) == Decimal("0.25")   # 25–50 band
    assert mr.get_equity_tick_size(130) == Decimal("1.00")
    assert mr.get_equity_tick_size(1000) == Decimal("6.00")


def test_tfex_tick_sizes_longest_prefix_wins():
    assert mr.get_tfex_tick_size("S50M24") == Decimal("0.1")
    assert mr.get_tfex_tick_size("GF10Z24") == Decimal("1")   # GF10 beats GF
    assert mr.get_tfex_tick_size("GFG24") == Decimal("10")
    assert mr.get_tfex_tick_size("UNKNOWN") == Decimal("0.5")  # default


def test_tick_up_down_recompute_per_level():
    # crossing the 5 THB boundary changes tick from 0.02 to 0.05
    assert mr.tick_up(4.98, 2, is_equity=True) == Decimal("5.05")
    assert mr.tick_down(920.0, 3, is_equity=False, symbol="S50M24") == Decimal("919.7")


def test_volume_normalization():
    assert mr.normalize_volume(250, is_equity=True) == 200      # board lot of 100
    assert mr.normalize_volume(50, is_equity=True) == 100       # floor of one lot
    assert mr.normalize_volume(3.9, is_equity=False) == 3       # integer contracts
    assert mr.normalize_volume(0, is_equity=False) == 1         # min 1


def test_count_ticks_in_range():
    assert mr.count_ticks_in_range(920.0, 921.0, is_equity=False, symbol="S50M24") == 10
