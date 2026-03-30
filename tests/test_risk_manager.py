"""Unit tests for engine.risk_manager module."""

import pytest
from alpaca_trader.engine.risk_manager import RiskManager, RiskConfig, RiskCheckResult


def make_rm(**kwargs) -> RiskManager:
    cfg = RiskConfig(
        max_position_pct=0.10,
        max_daily_loss_pct=-0.05,
        max_open_positions=5,
        min_cash_reserve_pct=0.10,
        max_order_value=50_000.0,
        min_order_value=10.0,
        max_trades_per_day=10,
        slippage_tolerance_pct=0.02,
        **kwargs,
    )
    return RiskManager(cfg)


PORTFOLIO = 100_000.0
CASH = 50_000.0


def good_order(rm: RiskManager, **overrides) -> RiskCheckResult:
    params = dict(
        symbol="AAPL",
        qty=10,
        price=150.0,
        side="buy",
        portfolio_value=PORTFOLIO,
        cash=CASH,
        open_positions=2,
        daily_pnl=-200.0,
        trades_today=3,
        existing_position_value=0.0,
    )
    params.update(overrides)
    return rm.check_order(**params)


class TestRiskConfig:
    def test_defaults(self):
        cfg = RiskConfig()
        assert cfg.max_position_pct == 0.10
        assert cfg.max_daily_loss_pct == -0.05
        assert cfg.max_open_positions == 10
        assert cfg.max_trades_per_day == 50

    def test_custom_values(self):
        cfg = RiskConfig(max_position_pct=0.20, max_trades_per_day=100)
        assert cfg.max_position_pct == 0.20
        assert cfg.max_trades_per_day == 100


class TestRiskCheckResult:
    def test_approved_flag(self):
        result = RiskCheckResult(approved=True, reason="OK", adjusted_qty=5, adjusted_value=750.0)
        assert result.approved is True
        assert result.rejected is False

    def test_rejected_flag(self):
        result = RiskCheckResult(approved=False, reason="Too risky")
        assert result.approved is False
        assert result.rejected is True


class TestHappyPath:
    def test_valid_buy_order_approved(self):
        rm = make_rm()
        result = good_order(rm)
        assert result.approved
        assert result.adjusted_qty == 10
        assert result.adjusted_value == 1500.0

    def test_valid_sell_order_approved(self):
        rm = make_rm()
        result = good_order(rm, side="sell")
        assert result.approved

    def test_sell_bypasses_position_checks(self):
        rm = make_rm()
        result = good_order(rm, side="sell", open_positions=5)
        assert result.approved

    def test_buy_with_existing_position(self):
        rm = make_rm()
        result = good_order(rm, existing_position_value=5_000.0, qty=10, price=100.0)
        assert result.approved


class TestInvalidParameters:
    def test_zero_qty_rejected(self):
        rm = make_rm()
        result = good_order(rm, qty=0)
        assert result.rejected
        assert "Invalid" in result.reason

    def test_zero_price_rejected(self):
        rm = make_rm()
        result = good_order(rm, price=0)
        assert result.rejected

    def test_zero_portfolio_value_rejected(self):
        rm = make_rm()
        result = good_order(rm, portfolio_value=0)
        assert result.rejected


class TestCircuitBreaker:
    def test_circuit_breaker_trips_on_daily_loss(self):
        rm = make_rm(max_daily_loss_pct=-0.05)
        result = good_order(rm, daily_pnl=-5_001.0)
        assert result.rejected
        assert rm.is_circuit_broken
        assert "Daily loss" in result.reason

    def test_circuit_breaker_at_exact_threshold_is_tripped(self):
        rm = make_rm(max_daily_loss_pct=-0.05)
        result = good_order(rm, daily_pnl=-5_000.0)
        assert result.rejected
        assert rm.is_circuit_broken

    def test_daily_loss_below_threshold_allowed(self):
        rm = make_rm(max_daily_loss_pct=-0.05)
        result = good_order(rm, daily_pnl=-4_999.0)
        assert result.approved

    def test_manual_circuit_breaker_trip(self):
        rm = make_rm()
        rm.trip_circuit_breaker("Manual test")
        result = good_order(rm)
        assert result.rejected
        assert "Manual test" in result.reason

    def test_circuit_breaker_reset(self):
        rm = make_rm()
        rm.trip_circuit_breaker("test")
        assert rm.is_circuit_broken
        rm.reset_circuit_breaker()
        assert not rm.is_circuit_broken
        result = good_order(rm)
        assert result.approved

    def test_all_orders_blocked_after_trip(self):
        rm = make_rm()
        rm.trip_circuit_breaker("market crash")
        result1 = good_order(rm, side="buy")
        result2 = good_order(rm, side="sell")
        assert result1.rejected
        assert result2.rejected


class TestTradeCountLimit:
    def test_trade_limit_blocks_order(self):
        rm = make_rm(max_trades_per_day=10)
        result = good_order(rm, trades_today=10)
        assert result.rejected
        assert "Daily trade limit" in result.reason

    def test_one_below_limit_allowed(self):
        rm = make_rm(max_trades_per_day=10)
        result = good_order(rm, trades_today=9)
        assert result.approved

    def test_zero_trades_allowed(self):
        rm = make_rm()
        result = good_order(rm, trades_today=0)
        assert result.approved


class TestMaxOpenPositions:
    def test_at_max_positions_blocks_new_symbol(self):
        rm = make_rm(max_open_positions=5)
        result = good_order(rm, open_positions=5, existing_position_value=0.0)
        assert result.rejected
        assert "Max open positions" in result.reason

    def test_at_max_positions_allows_adding_to_existing(self):
        rm = make_rm(max_open_positions=5)
        result = good_order(rm, open_positions=5, existing_position_value=1000.0)
        assert result.approved

    def test_below_max_positions_allowed(self):
        rm = make_rm(max_open_positions=5)
        result = good_order(rm, open_positions=4, existing_position_value=0.0)
        assert result.approved


class TestCashReserve:
    def test_order_depleting_cash_below_reserve_rejected(self):
        rm = make_rm(min_cash_reserve_pct=0.10)
        result = good_order(rm, cash=12_000.0, qty=30, price=100.0)
        assert result.rejected
        assert "cash reserve" in result.reason.lower()

    def test_order_leaving_adequate_cash_allowed(self):
        rm = make_rm(min_cash_reserve_pct=0.10)
        result = good_order(rm, cash=15_000.0, qty=10, price=100.0)
        assert result.approved


class TestPositionSizing:
    def test_oversized_order_quantity_reduced(self):
        rm = make_rm(max_position_pct=0.10)
        result = good_order(rm, qty=200, price=100.0, cash=80_000.0)
        assert result.approved
        assert result.adjusted_qty < 200
        assert result.adjusted_qty == 100

    def test_within_size_limit_not_reduced(self):
        rm = make_rm(max_position_pct=0.10)
        result = good_order(rm, qty=50, price=100.0, cash=80_000.0)
        assert result.approved
        assert result.adjusted_qty == 50

    def test_position_full_rejects(self):
        rm = make_rm(max_position_pct=0.10)
        result = good_order(rm, qty=1, price=100.0, existing_position_value=10_000.0, cash=80_000.0)
        assert result.rejected

    def test_calculate_position_size(self):
        rm = make_rm(max_position_pct=0.10)
        size = rm.calculate_position_size(price=50.0, portfolio_value=100_000.0)
        assert size == 200

    def test_calculate_position_size_with_existing(self):
        rm = make_rm(max_position_pct=0.10)
        size = rm.calculate_position_size(price=50.0, portfolio_value=100_000.0, existing_position_value=5_000.0)
        assert size == 100

    def test_calculate_position_size_zero_price(self):
        rm = make_rm()
        assert rm.calculate_position_size(price=0, portfolio_value=100_000.0) == 0


class TestOrderValueBounds:
    def test_order_above_max_rejected(self):
        rm = make_rm(max_order_value=5_000.0)
        result = good_order(rm, qty=100, price=100.0, cash=80_000.0)
        assert result.rejected
        assert "exceeds max" in result.reason

    def test_order_below_min_rejected(self):
        rm = make_rm(min_order_value=10.0)
        result = good_order(rm, qty=1, price=1.0, cash=50_000.0)
        assert result.rejected
        assert "below minimum" in result.reason


class TestSlippage:
    def test_acceptable_slippage(self):
        rm = make_rm(slippage_tolerance_pct=0.02)
        assert rm.check_slippage(signal_price=100.0, fill_price=101.0) is True

    def test_excessive_slippage(self):
        rm = make_rm(slippage_tolerance_pct=0.02)
        assert rm.check_slippage(signal_price=100.0, fill_price=103.5) is False

    def test_exact_threshold_slippage(self):
        rm = make_rm(slippage_tolerance_pct=0.02)
        assert rm.check_slippage(signal_price=100.0, fill_price=102.0) is True

    def test_zero_signal_price(self):
        rm = make_rm()
        assert rm.check_slippage(signal_price=0.0, fill_price=100.0) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
