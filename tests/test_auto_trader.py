"""Unit tests for engine.auto_trader module."""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from alpaca_trader.engine.auto_trader import AutoTrader, is_market_open
from alpaca_trader.engine.risk_manager import RiskManager, RiskConfig
from alpaca_trader.engine.order_executor import OrderExecutor, ExecutorConfig
from alpaca_trader.engine.position_manager import PositionManager
from alpaca_trader.engine.trade_journal import TradeJournal
from alpaca_trader.strategies.scanner import Signal


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
                    status TEXT DEFAULT 'open',
                    option_symbol TEXT, option_type TEXT, strike_price REAL,
                    expiry_date TEXT, premium_paid REAL, contracts INTEGER,
                    delta_at_entry REAL, theta_at_entry REAL, iv_at_entry REAL
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
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db, patch(
            "alpaca_trader.engine.auto_trader.is_market_open", return_value=False
        ):
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
        with patch("alpaca_trader.engine.auto_trader.db") as mock_db, patch(
            "alpaca_trader.engine.auto_trader.is_market_open", return_value=True
        ):
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[])
            summary = run(trader.run_cycle())
        assert any("Circuit breaker" in e for e in summary["errors"])
        assert summary["entries_executed"] == 0

    def test_cycle_errors_on_account_fetch_failure(self, tmp_path):
        journal = make_mock_journal(tmp_path)
        trader = AutoTrader(trade_journal=journal)
        import alpaca_trader.core.client as alpaca_client

        with patch("alpaca_trader.engine.auto_trader.db") as mock_db, patch(
            "alpaca_trader.engine.auto_trader.is_market_open", return_value=True
        ), patch.object(
            alpaca_client, "get_account", side_effect=RuntimeError("API error")
        ), patch.object(alpaca_client, "get_positions", return_value=[]):
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


def make_signal(
    symbol, strategy="bb_rsi_reversal", detected=True, strength=0.8, direction="bullish"
):
    """Create a Signal for testing."""
    return Signal(
        symbol=symbol,
        strategy=strategy,
        detected=detected,
        direction=direction,
        strength=strength,
        details={"target": 160.0, "stop": 140.0},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Full pipeline: signal -> risk -> order -> journal
# ---------------------------------------------------------------------------


class TestAutoTraderPipeline:
    """Test the full signal -> risk check -> order execution -> journal logging flow."""

    def _setup_trader(self, tmp_path, dry_run=True, risk_config=None):
        journal = make_mock_journal(tmp_path)
        rm = RiskManager(
            risk_config
            or RiskConfig(
                max_position_pct=0.10,
                max_open_positions=5,
                min_cash_reserve_pct=0.10,
                max_order_value=50_000.0,
                min_order_value=10.0,
                max_trades_per_day=10,
            )
        )
        executor = OrderExecutor(
            config=ExecutorConfig(dry_run=dry_run, retry_delay_ms=0)
        )
        pm = PositionManager()
        scanner = MagicMock()
        trader = AutoTrader(
            risk_manager=rm,
            order_executor=executor,
            position_manager=pm,
            trade_journal=journal,
            scanner=scanner,
            dry_run=dry_run,
        )
        return trader, journal, scanner

    def _mock_account_and_market(self):
        import alpaca_trader.core.client as alpaca_client
        import pandas as pd

        def mock_bars(symbol, period="1D", limit=2):
            return pd.DataFrame(
                {
                    "open": [148.0, 149.0],
                    "high": [152.0, 153.0],
                    "low": [147.0, 148.0],
                    "close": [150.0, 151.0],
                    "volume": [1000000, 1100000],
                }
            )

        return {
            "db": patch("alpaca_trader.engine.auto_trader.db"),
            "market": patch(
                "alpaca_trader.engine.auto_trader.is_market_open", return_value=True
            ),
            "account": patch.object(
                alpaca_client,
                "get_account",
                return_value={
                    "portfolio_value": "100000.0",
                    "cash": "50000.0",
                    "equity": "100000.0",
                },
            ),
            "positions": patch.object(alpaca_client, "get_positions", return_value=[]),
            "bars": patch.object(
                alpaca_client, "get_stock_bars_df", side_effect=mock_bars
            ),
        }

    def test_single_signal_executes_entry(self, tmp_path):
        trader, journal, scanner = self._setup_trader(tmp_path)
        patches = self._mock_account_and_market()
        signal = make_signal("AAPL", strategy="bb_rsi_reversal", strength=0.9)
        scanner.scan = MagicMock(return_value=[signal])

        with patches["db"] as mock_db, patches["market"], patches["account"], patches[
            "positions"
        ], patches["bars"]:
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[{"symbol": "AAPL"}])
            summary = run(trader.run_cycle())

        assert summary["enabled"] is True
        assert summary["entries_executed"] >= 1
        assert len(summary["errors"]) == 0
        trades = run(journal.get_trades(limit=10))
        assert len(trades) == 1
        assert trades[0]["symbol"] == "AAPL"
        assert trades[0]["status"] == "open"
        assert trades[0]["strategy"] == "bb_rsi_reversal"

    def test_no_signal_means_no_entry(self, tmp_path):
        trader, journal, scanner = self._setup_trader(tmp_path)
        patches = self._mock_account_and_market()
        signal = make_signal("AAPL", detected=False, strength=0.0)
        scanner.scan = MagicMock(return_value=[signal])

        with patches["db"] as mock_db, patches["market"], patches["account"], patches[
            "positions"
        ], patches["bars"]:
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[{"symbol": "AAPL"}])
            summary = run(trader.run_cycle())

        assert summary["signals_found"] == 0
        assert summary["entries_executed"] == 0

    def test_risk_rejection_blocks_entry(self, tmp_path):
        risk_cfg = RiskConfig(
            max_open_positions=1,
            max_position_pct=0.10,
            min_cash_reserve_pct=0.10,
            max_order_value=50_000.0,
            min_order_value=10.0,
            max_trades_per_day=10,
        )
        trader, journal, scanner = self._setup_trader(tmp_path, risk_config=risk_cfg)
        patches = self._mock_account_and_market()
        signal = make_signal("TSLA", strategy="bounce", strength=0.7)
        scanner.scan = MagicMock(return_value=[signal])

        import alpaca_trader.core.client as alpaca_client

        existing = [
            {
                "symbol": "AAPL",
                "current_price": "150.0",
                "avg_entry_price": "140.0",
                "qty": "10",
            }
        ]

        with patches["db"] as mock_db, patches["market"], patches[
            "account"
        ], patch.object(alpaca_client, "get_positions", return_value=existing), patches[
            "bars"
        ]:
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[{"symbol": "TSLA"}])
            summary = run(trader.run_cycle())

        assert summary["signals_found"] >= 1
        assert summary["entries_executed"] == 0

    def test_skip_already_held_symbol(self, tmp_path):
        trader, journal, scanner = self._setup_trader(tmp_path)
        patches = self._mock_account_and_market()
        signal = make_signal("AAPL", strength=0.95)
        scanner.scan = MagicMock(return_value=[signal])

        import alpaca_trader.core.client as alpaca_client

        existing = [
            {
                "symbol": "AAPL",
                "current_price": "155.0",
                "avg_entry_price": "145.0",
                "qty": "10",
            }
        ]

        with patches["db"] as mock_db, patches["market"], patches[
            "account"
        ], patch.object(alpaca_client, "get_positions", return_value=existing), patches[
            "bars"
        ]:
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[{"symbol": "AAPL"}])
            summary = run(trader.run_cycle())

        assert summary["entries_executed"] == 0

    def test_multiple_signals_strongest_wins(self, tmp_path):
        trader, journal, scanner = self._setup_trader(tmp_path)
        patches = self._mock_account_and_market()
        weak = make_signal("AAPL", strategy="bounce", strength=0.3)
        strong = make_signal("AAPL", strategy="bb_rsi_reversal", strength=0.9)

        def mock_scan(symbols, strategy, period="1D", limit=60):
            if strategy == "bb_rsi_reversal" and period == "1D":
                return [strong]
            if strategy == "bounce" and period == "1D":
                return [weak]
            return []

        scanner.scan = mock_scan

        with patches["db"] as mock_db, patches["market"], patches["account"], patches[
            "positions"
        ], patches["bars"]:
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[{"symbol": "AAPL"}])
            summary = run(trader.run_cycle())

        assert summary["entries_executed"] == 1
        trades = run(journal.get_trades())
        assert trades[0]["strategy"] == "bb_rsi_reversal"

    def test_multiple_symbols_enter_approved(self, tmp_path):
        trader, journal, scanner = self._setup_trader(tmp_path)
        patches = self._mock_account_and_market()
        sig_aapl = make_signal("AAPL", strength=0.8)
        sig_tsla = make_signal("TSLA", strength=0.7)

        def mock_scan(symbols, strategy, period="1D", limit=60):
            if strategy == "bb_rsi_reversal" and period == "1D":
                return [s for s in [sig_aapl, sig_tsla] if s.symbol in symbols]
            return []

        scanner.scan = mock_scan

        with patches["db"] as mock_db, patches["market"], patches["account"], patches[
            "positions"
        ], patches["bars"]:
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(
                return_value=[{"symbol": "AAPL"}, {"symbol": "TSLA"}]
            )
            summary = run(trader.run_cycle())

        assert summary["entries_executed"] == 2
        syms = {t["symbol"] for t in run(journal.get_trades())}
        assert "AAPL" in syms and "TSLA" in syms

    def test_trade_count_increments(self, tmp_path):
        trader, journal, scanner = self._setup_trader(tmp_path)
        patches = self._mock_account_and_market()
        scanner.scan = MagicMock(return_value=[make_signal("AAPL")])

        with patches["db"] as mock_db, patches["market"], patches["account"], patches[
            "positions"
        ], patches["bars"]:
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[{"symbol": "AAPL"}])
            run(trader.run_cycle())

        assert trader._trades_today >= 1

    def test_empty_watchlist_skips_scan(self, tmp_path):
        trader, journal, scanner = self._setup_trader(tmp_path)
        patches = self._mock_account_and_market()

        with patches["db"] as mock_db, patches["market"], patches["account"], patches[
            "positions"
        ], patches["bars"]:
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[])
            summary = run(trader.run_cycle())

        assert summary["signals_found"] == 0
        assert summary["entries_executed"] == 0


# ---------------------------------------------------------------------------
# Exit pipeline tests
# ---------------------------------------------------------------------------


class TestAutoTraderExitPipeline:
    def test_stop_loss_exit_executes(self, tmp_path):
        journal = make_mock_journal(tmp_path)
        rm = RiskManager()
        executor = OrderExecutor(config=ExecutorConfig(dry_run=True, retry_delay_ms=0))
        pm = PositionManager(stop_loss_pct=-0.30)
        scanner = MagicMock()
        trader = AutoTrader(
            risk_manager=rm,
            order_executor=executor,
            position_manager=pm,
            trade_journal=journal,
            scanner=scanner,
            dry_run=True,
        )
        run(
            journal.log_entry(
                symbol="AAPL",
                side="buy",
                qty=10,
                price=100.0,
                strategy="bb_rsi_reversal",
                signal_details={},
            )
        )

        import alpaca_trader.core.client as alpaca_client

        positions = [
            {
                "symbol": "AAPL",
                "current_price": "65.0",
                "avg_entry_price": "100.0",
                "qty": "10",
            }
        ]

        with patch("alpaca_trader.engine.auto_trader.db") as mock_db, patch(
            "alpaca_trader.engine.auto_trader.is_market_open", return_value=True
        ), patch.object(
            alpaca_client,
            "get_account",
            return_value={
                "portfolio_value": "100000.0",
                "cash": "50000.0",
                "equity": "100000.0",
            },
        ), patch.object(
            alpaca_client, "get_positions", return_value=positions
        ), patch.object(
            alpaca_client, "get_stock_bars_df", return_value=MagicMock(empty=True)
        ):
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[])
            summary = run(trader.run_cycle())

        assert summary["exits_checked"] == 1
        assert summary["exits_executed"] == 1
        trades = run(journal.get_trades(status="closed"))
        assert len(trades) == 1
        assert "stop_loss" in trades[0]["exit_reason"]

    def test_healthy_position_not_exited(self, tmp_path):
        journal = make_mock_journal(tmp_path)
        pm = PositionManager(stop_loss_pct=-0.30, take_profit_pct=0.50)
        executor = OrderExecutor(config=ExecutorConfig(dry_run=True))
        trader = AutoTrader(
            position_manager=pm,
            order_executor=executor,
            trade_journal=journal,
            dry_run=True,
        )
        run(
            journal.log_entry(
                symbol="AAPL",
                side="buy",
                qty=10,
                price=100.0,
                strategy="bounce",
                signal_details={},
            )
        )

        import alpaca_trader.core.client as alpaca_client

        positions = [
            {
                "symbol": "AAPL",
                "current_price": "110.0",
                "avg_entry_price": "100.0",
                "qty": "10",
            }
        ]

        with patch("alpaca_trader.engine.auto_trader.db") as mock_db, patch(
            "alpaca_trader.engine.auto_trader.is_market_open", return_value=True
        ), patch.object(
            alpaca_client,
            "get_account",
            return_value={
                "portfolio_value": "100000.0",
                "cash": "50000.0",
                "equity": "100000.0",
            },
        ), patch.object(alpaca_client, "get_positions", return_value=positions):
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[])
            summary = run(trader.run_cycle())

        assert summary["exits_executed"] == 0
        assert len(run(journal.get_trades(status="open"))) == 1

    def test_take_profit_exit_executes(self, tmp_path):
        journal = make_mock_journal(tmp_path)
        pm = PositionManager(stop_loss_pct=-0.30, take_profit_pct=0.50)
        executor = OrderExecutor(config=ExecutorConfig(dry_run=True))
        trader = AutoTrader(
            position_manager=pm,
            order_executor=executor,
            trade_journal=journal,
            dry_run=True,
        )
        run(
            journal.log_entry(
                symbol="TSLA",
                side="buy",
                qty=5,
                price=200.0,
                strategy="squeeze",
                signal_details={},
            )
        )

        import alpaca_trader.core.client as alpaca_client

        positions = [
            {
                "symbol": "TSLA",
                "current_price": "310.0",
                "avg_entry_price": "200.0",
                "qty": "5",
            }
        ]

        with patch("alpaca_trader.engine.auto_trader.db") as mock_db, patch(
            "alpaca_trader.engine.auto_trader.is_market_open", return_value=True
        ), patch.object(
            alpaca_client,
            "get_account",
            return_value={
                "portfolio_value": "100000.0",
                "cash": "50000.0",
                "equity": "100000.0",
            },
        ), patch.object(alpaca_client, "get_positions", return_value=positions):
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[])
            summary = run(trader.run_cycle())

        assert summary["exits_executed"] == 1
        trades = run(journal.get_trades(status="closed"))
        assert len(trades) == 1
        assert "take_profit" in trades[0]["exit_reason"]


class TestAutoTraderDailyLimit:
    def test_daily_trade_limit_blocks_further_entries(self, tmp_path):
        risk_cfg = RiskConfig(
            max_trades_per_day=1,
            max_position_pct=0.10,
            min_cash_reserve_pct=0.10,
            max_order_value=50_000.0,
            min_order_value=10.0,
            max_open_positions=10,
        )
        journal = make_mock_journal(tmp_path)
        rm = RiskManager(risk_cfg)
        executor = OrderExecutor(config=ExecutorConfig(dry_run=True, retry_delay_ms=0))
        scanner = MagicMock()
        trader = AutoTrader(
            risk_manager=rm,
            order_executor=executor,
            trade_journal=journal,
            scanner=scanner,
            dry_run=True,
        )
        trader._trades_today = 1

        import alpaca_trader.core.client as alpaca_client
        import pandas as pd

        scanner.scan = MagicMock(return_value=[make_signal("AAPL")])

        def mock_bars(symbol, period="1D", limit=2):
            return pd.DataFrame(
                {
                    "open": [148.0, 149.0],
                    "high": [152.0, 153.0],
                    "low": [147.0, 148.0],
                    "close": [150.0, 151.0],
                    "volume": [1000000, 1100000],
                }
            )

        with patch("alpaca_trader.engine.auto_trader.db") as mock_db, patch(
            "alpaca_trader.engine.auto_trader.is_market_open", return_value=True
        ), patch.object(
            alpaca_client,
            "get_account",
            return_value={
                "portfolio_value": "100000.0",
                "cash": "50000.0",
                "equity": "100000.0",
            },
        ), patch.object(alpaca_client, "get_positions", return_value=[]), patch.object(
            alpaca_client, "get_stock_bars_df", side_effect=mock_bars
        ):
            mock_db.setting_get = AsyncMock(return_value="true")
            mock_db.watchlist_list = AsyncMock(return_value=[{"symbol": "AAPL"}])
            summary = run(trader.run_cycle())

        assert summary["entries_executed"] == 0
