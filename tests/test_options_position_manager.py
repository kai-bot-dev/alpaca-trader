"""Unit tests for engine.options_position_manager module."""

import pytest
from datetime import date, timedelta

from alpaca_trader.engine.options_position_manager import OptionsPositionManager


def expiry_in(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def make_opm(**kwargs) -> OptionsPositionManager:
    defaults = dict(
        time_stop_dte=3,
        hard_stop_pct=-0.40,
        trailing_trigger_pct=0.30,
        trailing_stop_pct=0.20,
        take_profit_pct=0.50,
    )
    defaults.update(kwargs)
    return OptionsPositionManager(**defaults)


class TestTimeStop:
    def test_triggers_when_dte_below_threshold(self):
        opm = make_opm(time_stop_dte=3)
        should, reason = opm.should_exit("OPT", current_price=2.0, premium_paid=2.0, expiry_date=expiry_in(2))
        assert should is True
        assert "time_stop" in reason

    def test_does_not_trigger_when_dte_at_threshold(self):
        opm = make_opm(time_stop_dte=3)
        should, _ = opm.should_exit("OPT", current_price=2.0, premium_paid=2.0, expiry_date=expiry_in(3))
        assert should is False

    def test_does_not_trigger_with_plenty_of_dte(self):
        opm = make_opm(time_stop_dte=3)
        should, _ = opm.should_exit("OPT", current_price=2.0, premium_paid=2.0, expiry_date=expiry_in(10))
        assert should is False


class TestHardStop:
    def test_triggers_at_40pct_loss(self):
        opm = make_opm(hard_stop_pct=-0.40)
        # bought at 3.00, now 1.75 → -41.67% (clearly past threshold, avoids float boundary)
        should, reason = opm.should_exit("OPT", current_price=1.75, premium_paid=3.00, expiry_date=expiry_in(10))
        assert should is True
        assert "hard_stop" in reason

    def test_triggers_below_40pct_loss(self):
        opm = make_opm(hard_stop_pct=-0.40)
        should, reason = opm.should_exit("OPT", current_price=1.50, premium_paid=3.00, expiry_date=expiry_in(10))
        assert should is True
        assert "hard_stop" in reason

    def test_does_not_trigger_just_above_threshold(self):
        opm = make_opm(hard_stop_pct=-0.40)
        # -39%: 3.00 * 0.61 = 1.83
        should, _ = opm.should_exit("OPT", current_price=1.83, premium_paid=3.00, expiry_date=expiry_in(10))
        assert should is False


class TestTrailingStop:
    def test_trailing_not_active_below_trigger(self):
        opm = make_opm(trailing_trigger_pct=0.30, trailing_stop_pct=0.20)
        # +20% gain, trigger is +30% → trailing not active
        should, _ = opm.should_exit("OPT", current_price=3.60, premium_paid=3.00, expiry_date=expiry_in(10))
        assert should is False

    def test_trailing_activates_and_triggers(self):
        opm = make_opm(trailing_trigger_pct=0.30, trailing_stop_pct=0.20)
        # First: +33% (hwm=4.00, trigger=3.00*1.30=3.90 → activated)
        opm.should_exit("OPT", current_price=4.00, premium_paid=3.00, expiry_date=expiry_in(10))
        # Second: price drops to 4.00*(1-0.20)=3.20 → triggered
        should, reason = opm.should_exit("OPT", current_price=3.20, premium_paid=3.00, expiry_date=expiry_in(10))
        assert should is True
        assert "trailing_stop" in reason

    def test_trailing_not_triggered_price_above_trail(self):
        opm = make_opm(trailing_trigger_pct=0.30, trailing_stop_pct=0.20)
        # hwm=4.00, trail=3.20; current=3.50 > 3.20 → no exit
        opm.should_exit("OPT", current_price=4.00, premium_paid=3.00, expiry_date=expiry_in(10))
        should, _ = opm.should_exit("OPT", current_price=3.50, premium_paid=3.00, expiry_date=expiry_in(10))
        assert should is False

    def test_high_water_mark_tracked_per_symbol(self):
        opm = make_opm()
        opm.should_exit("OPT1", current_price=5.0, premium_paid=3.0, expiry_date=expiry_in(10))
        opm.should_exit("OPT1", current_price=6.0, premium_paid=3.0, expiry_date=expiry_in(10))
        opm.should_exit("OPT1", current_price=4.5, premium_paid=3.0, expiry_date=expiry_in(10))
        assert opm._high_water_marks["OPT1"] == 6.0

    def test_separate_high_water_marks_per_symbol(self):
        opm = make_opm()
        opm.update_high_water_mark("OPT1", 5.0)
        opm.update_high_water_mark("OPT2", 3.0)
        assert opm._high_water_marks["OPT1"] == 5.0
        assert opm._high_water_marks["OPT2"] == 3.0


class TestTakeProfit:
    def test_triggers_at_50pct_gain(self):
        opm = make_opm(take_profit_pct=0.50)
        # bought at 3.00, now 4.50 → +50%
        should, reason = opm.should_exit("OPT", current_price=4.50, premium_paid=3.00, expiry_date=expiry_in(10))
        assert should is True
        assert "take_profit" in reason

    def test_does_not_trigger_just_below_50pct(self):
        opm = make_opm(take_profit_pct=0.50)
        should, _ = opm.should_exit("OPT", current_price=4.49, premium_paid=3.00, expiry_date=expiry_in(10))
        assert should is False

    def test_triggers_above_50pct(self):
        opm = make_opm(take_profit_pct=0.50)
        should, reason = opm.should_exit("OPT", current_price=5.00, premium_paid=3.00, expiry_date=expiry_in(10))
        assert should is True
        assert "take_profit" in reason


class TestExitPriority:
    def test_time_stop_takes_priority_over_profit(self):
        opm = make_opm(time_stop_dte=3, take_profit_pct=0.50)
        # DTE=2 (time stop) AND +100% gain (take_profit) → time stop wins
        should, reason = opm.should_exit("OPT", current_price=6.00, premium_paid=3.00, expiry_date=expiry_in(2))
        assert should is True
        assert "time_stop" in reason

    def test_hard_stop_takes_priority_over_trailing(self):
        opm = make_opm(hard_stop_pct=-0.40, trailing_trigger_pct=0.30, trailing_stop_pct=0.20)
        # Activate trailing, then drop past hard stop
        opm.should_exit("OPT", current_price=4.00, premium_paid=3.00, expiry_date=expiry_in(10))
        # price at 1.50 = -50% (hard stop) AND trailing (4.00*0.80=3.20 > 1.50 would also trail)
        should, reason = opm.should_exit("OPT", current_price=1.50, premium_paid=3.00, expiry_date=expiry_in(10))
        assert should is True
        assert "hard_stop" in reason


class TestInvalidInputs:
    def test_zero_premium_returns_false(self):
        opm = make_opm()
        should, _ = opm.should_exit("OPT", current_price=2.0, premium_paid=0.0)
        assert should is False

    def test_zero_current_price_returns_false(self):
        opm = make_opm()
        should, _ = opm.should_exit("OPT", current_price=0.0, premium_paid=3.0)
        assert should is False

    def test_no_expiry_skips_time_stop(self):
        opm = make_opm(time_stop_dte=3)
        # No expiry — time stop cannot fire, price unchanged from entry
        should, reason = opm.should_exit("OPT", current_price=3.0, premium_paid=3.0, expiry_date=None)
        assert should is False
        assert reason == "hold"


class TestCheckExits:
    def test_identifies_hard_stop(self):
        opm = make_opm(hard_stop_pct=-0.40)
        positions = [
            {"symbol": "OPT1", "current_price": "1.80", "avg_entry_price": "3.00", "qty": "1"},
        ]
        journal = [{"option_symbol": "OPT1", "premium_paid": 3.00, "expiry_date": expiry_in(10)}]
        exits = opm.check_exits(positions, journal_entries=journal)
        assert len(exits) == 1
        assert "hard_stop" in exits[0]["exit_reason"]

    def test_identifies_take_profit(self):
        opm = make_opm(take_profit_pct=0.50)
        positions = [
            {"symbol": "OPT1", "current_price": "4.60", "avg_entry_price": "3.00", "qty": "2"},
        ]
        journal = [{"option_symbol": "OPT1", "premium_paid": 3.00, "expiry_date": expiry_in(10)}]
        exits = opm.check_exits(positions, journal_entries=journal)
        assert len(exits) == 1
        assert "take_profit" in exits[0]["exit_reason"]

    def test_no_exit_signal(self):
        opm = make_opm()
        positions = [
            {"symbol": "OPT1", "current_price": "3.20", "avg_entry_price": "3.00", "qty": "1"},
        ]
        journal = [{"option_symbol": "OPT1", "premium_paid": 3.00, "expiry_date": expiry_in(10)}]
        exits = opm.check_exits(positions, journal_entries=journal)
        assert exits == []

    def test_empty_positions_returns_empty(self):
        opm = make_opm()
        assert opm.check_exits([]) == []

    def test_skips_invalid_price(self):
        opm = make_opm()
        positions = [
            {"symbol": "OPT1", "current_price": None, "avg_entry_price": "3.00", "qty": "1"},
            {"symbol": "OPT2", "current_price": "0", "avg_entry_price": "0", "qty": "1"},
        ]
        exits = opm.check_exits(positions)
        assert exits == []

    def test_falls_back_to_avg_entry_price_without_journal(self):
        opm = make_opm(hard_stop_pct=-0.40)
        positions = [
            {"symbol": "OPT1", "current_price": "1.50", "avg_entry_price": "3.00", "qty": "1"},
        ]
        # No journal — should still detect hard stop using avg_entry_price
        exits = opm.check_exits(positions, journal_entries=None)
        assert len(exits) == 1
        assert "hard_stop" in exits[0]["exit_reason"]

    def test_time_stop_from_journal_expiry(self):
        opm = make_opm(time_stop_dte=3)
        positions = [
            {"symbol": "OPT1", "current_price": "3.00", "avg_entry_price": "3.00", "qty": "1"},
        ]
        journal = [{"option_symbol": "OPT1", "premium_paid": 3.00, "expiry_date": expiry_in(1)}]
        exits = opm.check_exits(positions, journal_entries=journal)
        assert len(exits) == 1
        assert "time_stop" in exits[0]["exit_reason"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
