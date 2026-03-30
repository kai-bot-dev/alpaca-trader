"""Unit tests for engine.position_manager module."""

import pytest
from datetime import datetime, timezone, timedelta

from alpaca_trader.engine.position_manager import PositionManager


def make_pm(**kwargs) -> PositionManager:
    defaults = dict(
        stop_loss_pct=-0.30,
        take_profit_pct=0.50,
        trailing_stop_trigger=0.25,
        trailing_stop_pct=0.15,
        max_hold_days=30,
    )
    defaults.update(kwargs)
    return PositionManager(**defaults)


def recent_entry() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def old_entry(days: int = 35) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class TestStopLoss:
    def test_stop_loss_triggers(self):
        pm = make_pm(stop_loss_pct=-0.30)
        should, reason = pm.should_exit("AAPL", current_price=70.0, entry_price=100.0, entry_time=recent_entry())
        assert should is True
        assert "stop_loss" in reason

    def test_stop_loss_at_exact_threshold(self):
        pm = make_pm(stop_loss_pct=-0.30)
        should, reason = pm.should_exit("AAPL", current_price=70.0, entry_price=100.0, entry_time=recent_entry())
        assert should is True

    def test_stop_loss_just_above_threshold(self):
        pm = make_pm(stop_loss_pct=-0.30)
        should, _ = pm.should_exit("AAPL", current_price=71.0, entry_price=100.0, entry_time=recent_entry())
        assert should is False


class TestTakeProfit:
    def test_take_profit_triggers(self):
        pm = make_pm(take_profit_pct=0.50)
        should, reason = pm.should_exit("AAPL", current_price=151.0, entry_price=100.0, entry_time=recent_entry())
        assert should is True
        assert "take_profit" in reason

    def test_take_profit_at_exact_threshold(self):
        pm = make_pm(take_profit_pct=0.50)
        should, reason = pm.should_exit("AAPL", current_price=150.0, entry_price=100.0, entry_time=recent_entry())
        assert should is True

    def test_take_profit_just_below_threshold(self):
        pm = make_pm(take_profit_pct=0.50)
        should, _ = pm.should_exit("AAPL", current_price=149.0, entry_price=100.0, entry_time=recent_entry())
        assert should is False


class TestTrailingStop:
    def test_trailing_stop_not_active_below_trigger(self):
        pm = make_pm(trailing_stop_trigger=0.25, trailing_stop_pct=0.15)
        # Only +10% gain, trigger is +25%
        should, _ = pm.should_exit("AAPL", current_price=110.0, entry_price=100.0, entry_time=recent_entry())
        assert should is False

    def test_trailing_stop_activates_and_triggers(self):
        pm = make_pm(trailing_stop_trigger=0.25, trailing_stop_pct=0.15)
        # First call: price goes to +30% (trigger activated, hwm=130)
        pm.should_exit("TSLA", current_price=130.0, entry_price=100.0, entry_time=recent_entry())
        # Second call: price drops to 130*(1-0.15)=110.5 (should trigger)
        should, reason = pm.should_exit("TSLA", current_price=110.0, entry_price=100.0, entry_time=recent_entry())
        assert should is True
        assert "trailing_stop" in reason

    def test_trailing_stop_updates_high_water_mark(self):
        pm = make_pm(trailing_stop_trigger=0.25, trailing_stop_pct=0.15)
        pm.should_exit("MSFT", current_price=130.0, entry_price=100.0, entry_time=recent_entry())
        pm.should_exit("MSFT", current_price=140.0, entry_price=100.0, entry_time=recent_entry())
        hwm = pm._high_water_marks.get("MSFT")
        assert hwm == 140.0

    def test_trailing_stop_not_triggered_price_above_trail(self):
        pm = make_pm(trailing_stop_trigger=0.25, trailing_stop_pct=0.15)
        pm.should_exit("AAPL", current_price=130.0, entry_price=100.0, entry_time=recent_entry())
        # Price still above trail (130 * 0.85 = 110.5, current=125 > 110.5)
        should, _ = pm.should_exit("AAPL", current_price=125.0, entry_price=100.0, entry_time=recent_entry())
        assert should is False


class TestTimeBasedExit:
    def test_max_hold_days_triggers(self):
        pm = make_pm(max_hold_days=30)
        should, reason = pm.should_exit("AAPL", current_price=100.0, entry_price=100.0, entry_time=old_entry(35))
        assert should is True
        assert "max_hold_days" in reason

    def test_within_hold_days_ok(self):
        pm = make_pm(max_hold_days=30)
        should, _ = pm.should_exit("AAPL", current_price=100.0, entry_price=100.0, entry_time=recent_entry())
        assert should is False

    def test_invalid_entry_time_handled(self):
        pm = make_pm(max_hold_days=30)
        # Should not raise
        should, _ = pm.should_exit("AAPL", current_price=100.0, entry_price=100.0, entry_time="not-a-date")
        assert isinstance(should, bool)


class TestInvalidInputs:
    def test_zero_entry_price_returns_false(self):
        pm = make_pm()
        should, _ = pm.should_exit("AAPL", current_price=100.0, entry_price=0.0, entry_time=recent_entry())
        assert should is False


class TestCheckExits:
    def test_check_exits_identifies_stop_loss(self):
        pm = make_pm(stop_loss_pct=-0.30)
        positions = [
            {"symbol": "AAPL", "current_price": "65.0", "avg_entry_price": "100.0", "qty": "10"},
        ]
        exits = pm.check_exits(positions)
        assert len(exits) == 1
        assert exits[0]["symbol"] == "AAPL"
        assert "stop_loss" in exits[0]["exit_reason"]

    def test_check_exits_no_trigger(self):
        pm = make_pm(stop_loss_pct=-0.30)
        positions = [
            {"symbol": "AAPL", "current_price": "105.0", "avg_entry_price": "100.0", "qty": "10"},
        ]
        exits = pm.check_exits(positions)
        assert exits == []

    def test_check_exits_multiple_positions(self):
        pm = make_pm(stop_loss_pct=-0.30, take_profit_pct=0.50)
        positions = [
            {"symbol": "AAPL", "current_price": "65.0", "avg_entry_price": "100.0", "qty": "10"},
            {"symbol": "TSLA", "current_price": "155.0", "avg_entry_price": "100.0", "qty": "5"},
            {"symbol": "MSFT", "current_price": "105.0", "avg_entry_price": "100.0", "qty": "20"},
        ]
        exits = pm.check_exits(positions)
        assert len(exits) == 2
        symbols = {e["symbol"] for e in exits}
        assert "AAPL" in symbols
        assert "TSLA" in symbols

    def test_check_exits_uses_journal_entry_time(self):
        pm = make_pm(max_hold_days=30)
        positions = [
            {"symbol": "AAPL", "current_price": "100.0", "avg_entry_price": "100.0", "qty": "5"},
        ]
        journal_entries = [{"symbol": "AAPL", "entry_time": old_entry(35)}]
        exits = pm.check_exits(positions, journal_entries=journal_entries)
        assert len(exits) == 1
        assert "max_hold_days" in exits[0]["exit_reason"]

    def test_check_exits_skips_bad_prices(self):
        pm = make_pm()
        positions = [
            {"symbol": "AAPL", "current_price": None, "avg_entry_price": "100.0", "qty": "5"},
            {"symbol": "TSLA", "current_price": "0", "avg_entry_price": "0", "qty": "5"},
        ]
        exits = pm.check_exits(positions)
        assert exits == []

    def test_check_exits_empty_positions(self):
        pm = make_pm()
        assert pm.check_exits([]) == []


class TestHighWaterMark:
    def test_update_high_water_mark(self):
        pm = make_pm()
        hwm = pm.update_high_water_mark("AAPL", 100.0)
        assert hwm == 100.0
        hwm = pm.update_high_water_mark("AAPL", 120.0)
        assert hwm == 120.0
        hwm = pm.update_high_water_mark("AAPL", 110.0)
        assert hwm == 120.0  # Doesn't go back down


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
