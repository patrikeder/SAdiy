import pytest

from sadiy.core.freqplan import OUT_MIN_HZ, build_sweep, lo_for_rf, plan_pll

PFD = 25e6


def check_consistent(plan):
    n = plan.int_n + plan.frac / plan.mod
    assert plan.f_actual_hz == pytest.approx(n * PFD / plan.rf_div, rel=1e-12)
    assert 2.2e9 <= plan.f_vco_hz <= 4.4e9
    assert plan.mod >= 2 and 0 <= plan.frac < plan.mod <= 4095


def test_integer_case():
    p = plan_pll(100e6, PFD)
    assert (p.rf_div, p.int_n, p.frac) == (32, 128, 0)
    assert p.f_actual_hz == 100e6
    check_consistent(p)


def test_fractional_case_error_is_small():
    p = plan_pll(433.92e6, PFD)
    assert p.rf_div == 8
    assert abs(p.f_actual_hz - 433.92e6) < 800
    check_consistent(p)


def test_range_edges():
    low = plan_pll(OUT_MIN_HZ, PFD)
    assert low.rf_div == 64
    check_consistent(low)
    high = plan_pll(500e6, PFD)
    assert high.rf_div == 8
    check_consistent(high)
    with pytest.raises(ValueError):
        plan_pll(30e6, PFD)
    with pytest.raises(ValueError):
        plan_pll(4.5e9, PFD)


def test_divider_is_always_lowest_that_fits():
    for f in (40e6, 75e6, 150e6, 300e6, 480e6, 1e9, 3e9):
        p = plan_pll(f, PFD)
        assert p.f_vco_hz >= 2.2e9
        if p.rf_div > 1:
            assert f * (p.rf_div // 2) < 2.2e9


def test_lo_for_rf():
    assert lo_for_rf(100e6, 10.7e6, "high") == pytest.approx(110.7e6)
    assert lo_for_rf(100e6, 10.7e6, "low") == pytest.approx(89.3e6)
    with pytest.raises(ValueError):
        lo_for_rf(100e6, 10.7e6, "mid")


def test_build_sweep():
    pts = build_sweep(60e6, 140e6, 5, 10.7e6, "high", PFD)
    assert [p.f_rf_hz for p in pts] == pytest.approx([60e6, 80e6, 100e6, 120e6, 140e6])
    assert pts[2].f_lo_hz == pytest.approx(110.7e6)
    assert abs(pts[2].pll.f_actual_hz - 110.7e6) < 800
