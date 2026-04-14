"""Unit tests for engine.trade_journal module."""

import asyncio
import pytest

import aiosqlite

from alpaca_trader.engine.trade_journal import TradeJournal


@pytest.fixture
def tmp_db(tmp_path):
    """Return a path to a temp SQLite DB with the trade_journal table created."""
    db_path = str(tmp_path / "test.db")
    asyncio.get_event_loop().run_until_complete(_setup_db(db_path))
    return db_path


async def _setup_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trade_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                strategy TEXT,
                signal_details TEXT,
                entry_time TEXT NOT NULL,
                exit_time TEXT,
                pnl REAL,
                pnl_pct REAL,
                exit_reason TEXT,
                status TEXT DEFAULT 'open',
                option_symbol TEXT,
                option_type TEXT,
                strike_price REAL,
                expiry_date TEXT,
                premium_paid REAL,
                contracts INTEGER,
                delta_at_entry REAL,
                theta_at_entry REAL,
                iv_at_entry REAL
            )
        """)
        await db.commit()


@pytest.fixture
def journal(tmp_db):
    return TradeJournal(db_url=tmp_db)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestLogEntry:
    def test_log_entry_returns_trade_id(self, journal):
        trade_id = run(journal.log_entry("AAPL", "buy", 10, 150.0, "bb_rsi_reversal"))
        assert isinstance(trade_id, int)
        assert trade_id >= 1

    def test_log_entry_stores_fields(self, journal):
        run(journal.log_entry("TSLA", "buy", 5, 200.0, "squeeze", {"rsi": 28}))
        trades = run(journal.get_trades(limit=1))
        assert len(trades) == 1
        t = trades[0]
        assert t["symbol"] == "TSLA"
        assert t["side"] == "buy"
        assert t["qty"] == 5
        assert t["entry_price"] == 200.0
        assert t["strategy"] == "squeeze"
        assert t["status"] == "open"
        assert t["signal_details"] == {"rsi": 28}

    def test_log_entry_symbol_uppercased(self, journal):
        run(journal.log_entry("aapl", "buy", 1, 100.0, "trend"))
        trades = run(journal.get_trades(limit=1))
        assert trades[0]["symbol"] == "AAPL"

    def test_log_entry_multiple(self, journal):
        run(journal.log_entry("AAPL", "buy", 10, 150.0, "s1"))
        run(journal.log_entry("TSLA", "buy", 5, 200.0, "s2"))
        trades = run(journal.get_trades(limit=10))
        assert len(trades) == 2


class TestLogExit:
    def test_log_exit_closes_trade(self, journal):
        trade_id = run(journal.log_entry("AAPL", "buy", 10, 100.0, "test"))
        run(journal.log_exit(trade_id, 120.0, "take_profit"))
        trades = run(journal.get_trades(status="closed"))
        assert len(trades) == 1
        t = trades[0]
        assert t["status"] == "closed"
        assert t["exit_price"] == 120.0
        assert t["exit_reason"] == "take_profit"

    def test_log_exit_computes_pnl_buy(self, journal):
        trade_id = run(journal.log_entry("AAPL", "buy", 10, 100.0, "test"))
        run(journal.log_exit(trade_id, 110.0, "take_profit"))
        trades = run(journal.get_trades(status="closed"))
        t = trades[0]
        assert t["pnl"] == pytest.approx(100.0)  # (110-100)*10
        assert t["pnl_pct"] == pytest.approx(0.10)

    def test_log_exit_computes_loss_buy(self, journal):
        trade_id = run(journal.log_entry("AAPL", "buy", 10, 100.0, "test"))
        run(journal.log_exit(trade_id, 90.0, "stop_loss"))
        trades = run(journal.get_trades(status="closed"))
        t = trades[0]
        assert t["pnl"] == pytest.approx(-100.0)
        assert t["pnl_pct"] == pytest.approx(-0.10)

    def test_log_exit_nonexistent_trade_no_crash(self, journal):
        # Should log warning but not raise
        run(journal.log_exit(9999, 100.0, "test"))

    def test_log_exit_already_closed_no_change(self, journal):
        trade_id = run(journal.log_entry("AAPL", "buy", 10, 100.0, "test"))
        run(journal.log_exit(trade_id, 110.0, "take_profit"))
        # Calling again should not crash or reopen
        run(journal.log_exit(trade_id, 90.0, "stop_loss"))
        trades = run(journal.get_trades(status="closed"))
        assert len(trades) == 1
        assert trades[0]["exit_price"] == 110.0


class TestGetTrades:
    def test_get_trades_default_limit(self, journal):
        for i in range(5):
            run(journal.log_entry(f"SYM{i}", "buy", 1, float(100 + i), "s"))
        trades = run(journal.get_trades(limit=50))
        assert len(trades) == 5

    def test_get_trades_filter_strategy(self, journal):
        run(journal.log_entry("AAPL", "buy", 1, 100.0, "squeeze"))
        run(journal.log_entry("TSLA", "buy", 1, 200.0, "bounce"))
        trades = run(journal.get_trades(strategy="squeeze"))
        assert len(trades) == 1
        assert trades[0]["strategy"] == "squeeze"

    def test_get_trades_filter_status(self, journal):
        tid = run(journal.log_entry("AAPL", "buy", 1, 100.0, "test"))
        run(journal.log_entry("TSLA", "buy", 1, 200.0, "test"))
        run(journal.log_exit(tid, 110.0, "tp"))
        open_trades = run(journal.get_trades(status="open"))
        closed_trades = run(journal.get_trades(status="closed"))
        assert len(open_trades) == 1
        assert len(closed_trades) == 1


class TestGetStats:
    def test_stats_empty(self, journal):
        stats = run(journal.get_stats())
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0.0
        assert stats["avg_pnl"] == 0.0

    def test_stats_with_trades(self, journal):
        # 2 winners, 1 loser
        t1 = run(journal.log_entry("A", "buy", 10, 100.0, "test"))
        t2 = run(journal.log_entry("B", "buy", 10, 100.0, "test"))
        t3 = run(journal.log_entry("C", "buy", 10, 100.0, "test"))
        run(journal.log_exit(t1, 110.0, "tp"))  # +100
        run(journal.log_exit(t2, 115.0, "tp"))  # +150
        run(journal.log_exit(t3, 90.0, "sl"))  # -100
        stats = run(journal.get_stats())
        assert stats["total_trades"] == 3
        assert stats["win_rate"] == pytest.approx(2 / 3)
        assert stats["avg_pnl"] == pytest.approx((100 + 150 - 100) / 3)
        assert stats["total_pnl"] == pytest.approx(150.0)

    def test_stats_sharpe_zero_std(self, journal):
        # All same P&L → std=0 → sharpe=0
        for i in range(3):
            t = run(journal.log_entry(f"X{i}", "buy", 1, 100.0, "test"))
            run(journal.log_exit(t, 110.0, "tp"))
        stats = run(journal.get_stats())
        assert stats["sharpe"] == 0.0


class TestGetTradeCount:
    def test_count_only_closed(self, journal):
        t1 = run(journal.log_entry("AAPL", "buy", 1, 100.0, "test"))
        run(journal.log_entry("TSLA", "buy", 1, 200.0, "test"))  # stays open
        run(journal.log_exit(t1, 110.0, "tp"))
        count = run(journal.get_trade_count())
        assert count == 1

    def test_count_empty(self, journal):
        assert run(journal.get_trade_count()) == 0


class TestGetOpenTradeForSymbol:
    def test_returns_open_trade(self, journal):
        run(journal.log_entry("AAPL", "buy", 10, 150.0, "test"))
        trade = run(journal.get_open_trade_for_symbol("AAPL"))
        assert trade is not None
        assert trade["symbol"] == "AAPL"

    def test_returns_none_when_closed(self, journal):
        tid = run(journal.log_entry("AAPL", "buy", 10, 150.0, "test"))
        run(journal.log_exit(tid, 160.0, "tp"))
        trade = run(journal.get_open_trade_for_symbol("AAPL"))
        assert trade is None

    def test_returns_none_for_unknown_symbol(self, journal):
        trade = run(journal.get_open_trade_for_symbol("ZZZZ"))
        assert trade is None

    def test_case_insensitive(self, journal):
        run(journal.log_entry("AAPL", "buy", 10, 150.0, "test"))
        trade = run(journal.get_open_trade_for_symbol("aapl"))
        assert trade is not None


class TestGetStatsByStrategy:
    def test_empty_returns_empty_dict(self, journal):
        result = run(journal.get_stats_by_strategy())
        assert result == {}

    def test_multiple_strategies(self, journal):
        # strategy_a: 2 wins, 1 loss
        t1 = run(journal.log_entry("A", "buy", 10, 100.0, "strategy_a"))
        t2 = run(journal.log_entry("B", "buy", 10, 100.0, "strategy_a"))
        t3 = run(journal.log_entry("C", "buy", 10, 100.0, "strategy_a"))
        run(journal.log_exit(t1, 110.0, "tp"))  # +100
        run(journal.log_exit(t2, 115.0, "tp"))  # +150
        run(journal.log_exit(t3, 90.0, "sl"))  # -100

        # strategy_b: 1 win
        t4 = run(journal.log_entry("D", "buy", 5, 200.0, "strategy_b"))
        run(journal.log_exit(t4, 220.0, "tp"))  # +100

        result = run(journal.get_stats_by_strategy())
        assert "strategy_a" in result
        assert "strategy_b" in result

        a = result["strategy_a"]
        assert a["total_trades"] == 3
        assert a["win_rate"] == pytest.approx(2 / 3)
        assert a["total_pnl"] == pytest.approx(150.0)
        assert a["avg_pnl"] == pytest.approx(50.0)
        assert a["best_trade"] == pytest.approx(150.0)
        assert a["worst_trade"] == pytest.approx(-100.0)

        b = result["strategy_b"]
        assert b["total_trades"] == 1
        assert b["win_rate"] == pytest.approx(1.0)
        assert b["total_pnl"] == pytest.approx(100.0)

    def test_open_trades_excluded(self, journal):
        # Log one closed trade and one open trade for the same strategy
        t1 = run(journal.log_entry("A", "buy", 10, 100.0, "my_strat"))
        run(journal.log_exit(t1, 110.0, "tp"))  # closed
        run(journal.log_entry("B", "buy", 10, 100.0, "my_strat"))  # open — not exited

        result = run(journal.get_stats_by_strategy())
        assert "my_strat" in result
        assert result["my_strat"]["total_trades"] == 1  # only the closed one

    def test_sorting_by_total_pnl(self, journal):
        # strategy_low has small total_pnl, strategy_high has large total_pnl
        t1 = run(journal.log_entry("A", "buy", 1, 100.0, "strategy_low"))
        run(journal.log_exit(t1, 105.0, "tp"))  # +5

        t2 = run(journal.log_entry("B", "buy", 10, 100.0, "strategy_high"))
        run(journal.log_exit(t2, 200.0, "tp"))  # +1000

        result = run(journal.get_stats_by_strategy())
        assert (
            result["strategy_high"]["total_pnl"] > result["strategy_low"]["total_pnl"]
        )
        # Verify the actual values
        assert result["strategy_low"]["total_pnl"] == pytest.approx(5.0)
        assert result["strategy_high"]["total_pnl"] == pytest.approx(1000.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
