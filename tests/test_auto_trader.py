"""Unit tests for engine.auto_trader module."""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from alpaca_trader.engine.auto_trader import AutoTrader, is_market_open
from alpaca_trader.engine.risk_manager import RiskManager
from alpaca_trader.engine.order_executor import OrderExecutor, ExecutorConfig
from alpaca_trader.engine.position_manager import PositionManager
from alpaca_trader.engine.trade_journal import TradeJournal


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# is_market_open
# ---------------------------------------------------------------------------

class TestIsMarketOpen:
    _ET = ZoneInfo("America/New_York")

    def _make_et(self, hour: int, minute: int, weekday: int = 0) -> datetime:
        """Create a UTC datetime that is <hour>:<minute> ET on <weekday> (0=Mon)."""
        # Build a naive ET datetime and convert to UTC
        from datetime import date
        # Find a real date that has the right weekday
        base = datetime(2024, 1, 1, tzinfo=self._ET)  # Monday
        offset = weekday - base.weekday()
        d = base.date() + timedelta(days=offset)
        et_dt = datetime(d.year, d.month, d.day, hour, minute, tzinfo=self._ET)
        return et_dt.astimezone(timezone.utc)

    def test_open_during_market_hours(self):
        now = self._make_et(10, 0, weekday=0)  # 10:00 ET Monday
        assert is_market_open(now) is True

    def test_closed_before_market_open(self):
        now = self._make_et(9, 0, weekday=0)  # 9:00 ET Monday
        assert is_market_open(now) is False

    def test_closed_after_market_close(self):
        now = self._make_et(16, 30, weekday=0)  # 16:30 ET Monday
        assert is_market_open(now) is False

    def test_closed_at_open_time(self):
        now = self._make_et(9, 30, weekday=0)  # Exactly 9:30 ET
        assert is_market_open(now) is True

    def test_closed_at_close_time(self):
        now = self._make_et(16, 0, weekday=0)  # Exactly 16:00 ET
        assert is_market_open(now) is False

    def test_closed_on_saturday(self):
        now = self._make_et(12, 0, weekday=5)  # Saturday
        assert is_market_open(now) is False

    def test_closed_on_sunday(self):
        now = self._make_et(12, 0, weekday=6)  # Sunday
        assert is_market_open(now) is False

    def test_open_friday_afternoon(self):
        now = self._make_et(15, 30, weekday=4)  # Friday 3:30 PM
        assert is_market_open(now) is True


# ---------------------------------------------------------------------------
# AutoTrader helpers
# ---------------------------------------------------------------------------

def make_mock_journal(tmp_path):
    """Return a real TradeJournal backed by a temp DB."""
    import aiosqlite
    db_path = str(tmp_path / "test.db")

    async def _setup():
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trade_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL, side TEXT NOT NULL,
                    qty INTEGER NOT NULL, entry_price REAL NOT NULL,
                    exit_price REAL, strategy TEXT, signal_details TEXT,
                    entry_time TEXT NOT NULL, exit_time TEXT,
                    pnl REAL, pnl_pct REAL, exit_reason TEXT,
                    status TEXT DEFAULT 'open'
                )
            """)
            await db.commit()

    asyncio.get_event_loop().run_until_complete(_setup())
    return TradeJournal(db_url=db_path)


# ---------------------------------------------------------------------------
# AutoTrader enable / disable / status
# ---------------------------------------------------------------------------

class TestAutoTraderEnableDisable:
    def test_enable_sets_setting(self):
        trader = AutoTrader()
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db:
            mock_db.setting_set = AsyncMock()
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.setting_get_trade_count = AsyncMock(return_value=0)
            run(trader.enable())
            mock_db.setting_set.assert_called_once_with(AutoTrader.ENABLED_KEY, "true")

    def test_disable_sets_setting(self):
        trader = AutoTrader()
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db:
            mock_db.setting_set = AsyncMock()
            run(trader.disable())
            mock_db.setting_set.assert_called_once_with(AutoTrader.ENABLED_KEY, "false")

    def test_is_enabled_true(self):
        trader = AutoTrader()
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db:
            mock_db.setting_get = AsyncMock(return_value="true")
            assert run(trader.is_enabled()) is True

    def test_is_enabled_false(self):
        trader = AutoTrader()
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db:
            mock_db.setting_get = AsyncMock(return_value="false")
            assert run(trader.is_enabled()) is False

    def test_is_enabled_none_is_false(self):
        trader = AutoTrader()
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db:
            mock_db.setting_get = AsyncMock(return_value=None)
            assert run(trader.is_enabled()) is False


# ---------------------------------------------------------------------------
# AutoTrader status
# ---------------------------------------------------------------------------

class TestAutoTraderStatus:
    def test_status_returns_expected_keys(self, tmp_path):
        journal = make_mock_journal(tmp_path)
        trader = AutoTrader(trade_journal=journal)
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db:
            mock_db.setting_get = AsyncMock(return_value="false")
            status = run(trader.status())

        assert "enabled" in status
        assert "dry_run" in status
        assert "circuit_breaker" in status
        assert "trades_today" in status
        assert "closed_trades" in status
        assert "paper_lockout_remaining" in status
        assert "market_open" in status
        assert "journal_stats" in status

    def test_status_paper_lockout_remaining(self, tmp_path):
        journal = make_mock_journal(tmp_path)
        trader = AutoTrader(trade_journal=journal)
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db:
            mock_db.setting_get = AsyncMock(return_value="false")
            status = run(trader.status())
        assert status["paper_lockout_remaining"] == 50


# ---------------------------------------------------------------------------
# AutoTrader run_cycle guard conditions
# ---------------------------------------------------------------------------

class TestAutoTraderRunCycle:
    def test_cycle_skipped_when_disabled(self, tmp_path):
        journal = make_mock_journal(tmp_path)
        trader = AutoTrader(trade_journal=journal)
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db:
            mock_db.setting_get = AsyncMock(return_value="false")
            mock_db.watchlist_list = AsyncMock(return_value=[])
            summary = run(trader.run_cycle())
        assert summary["enabled"] is False
        assert summary["entries_executed"] == 0

    def test_cycle_skipped_when_market_closed(self, tmp_path):
        journal = make_mock_journal(tmp_path)
        trader = AutoTrader(trade_journal=journal)
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db, \
             patch("alpaca_trader.engine.auto_trader.is_market_open", return_value=False):
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[])
            summary = run(trader.run_cycle())
        assert summary["market_open"] is False
        assert summary["entries_executed"] == 0

    def test_cycle_skipped_when_circuit_broken(self, tmp_path):
        journal = make_mock_journal(tmp_path)
        rm = RiskManager()
        rm.trip_circuit_breaker("test")
        trader = AutoTrader(risk_manager=rm, trade_journal=journal)
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db, \
             patch("alpaca_trader.engine.auto_trader.is_market_open", return_value=True):
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[])
            summary = run(trader.run_cycle())
        assert any("Circuit breaker" in e for e in summary["errors"])
        assert summary["entries_executed"] == 0

    def test_cycle_errors_on_account_fetch_failure(self, tmp_path):
        journal = make_mock_journal(tmp_path)
        trader = AutoTrader(trade_journal=journal)
        import alpaca_trader.core.client as alpaca_client
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db, \
             patch("alpaca_trader.engine.auto_trader.is_market_open", return_value=True), \
             patch.object(alpaca_client, "get_account", side_effect=RuntimeError("API error")), \
             patch.object(alpaca_client, "get_positions", return_value=[]):
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[])
            summary = run(trader.run_cycle())
        assert len(summary["errors"]) > 0

    def test_cycle_dry_run_default(self, tmp_path):
        journal = make_mock_journal(tmp_path)
        trader = AutoTrader(trade_journal=journal, dry_run=True)
        assert trader._dry_run is True
        assert trader.order_executor.config.dry_run is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
