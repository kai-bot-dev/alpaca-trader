"""Unit tests for engine.order_executor module."""

import pytest
from unittest.mock import MagicMock

from alpaca_trader.engine.order_executor import (
    OrderExecutor,
    ExecutorConfig,
    OrderResult,
    OrderStatus,
)


def mock_broker_ok(symbol, qty, side, limit_price=None, **kwargs):
    return {"id": f"mock-{symbol}-{side}", "status": "accepted"}


def make_executor(dry_run=False, max_retries=3, retry_delay_ms=0) -> OrderExecutor:
    cfg = ExecutorConfig(
        dry_run=dry_run, max_retries=max_retries, retry_delay_ms=retry_delay_ms
    )
    return OrderExecutor(broker_fn=mock_broker_ok, config=cfg)


class TestExecutorConfig:
    def test_defaults(self):
        cfg = ExecutorConfig()
        assert cfg.max_retries == 3
        assert cfg.retry_delay_ms == 200
        assert cfg.dry_run is False
        assert cfg.max_slippage_pct == 0.02

    def test_custom(self):
        cfg = ExecutorConfig(dry_run=True, max_retries=5)
        assert cfg.dry_run is True
        assert cfg.max_retries == 5


class TestOrderResult:
    def test_fields(self):
        result = OrderResult(
            success=True,
            order_id="abc",
            status=OrderStatus.SUBMITTED,
            symbol="TSLA",
            qty=5,
            side="buy",
            order_type="market",
        )
        assert result.success
        assert result.order_id == "abc"
        assert result.retries == 0
        assert result.error == ""
        assert result.submitted_at is not None


class TestMarketOrders:
    def test_market_buy_success(self):
        ex = make_executor()
        result = ex.place_market_order("AAPL", 10, "buy")
        assert result.success
        assert result.symbol == "AAPL"
        assert result.qty == 10
        assert result.side == "buy"
        assert result.order_type == "market"
        assert result.status == OrderStatus.SUBMITTED

    def test_market_sell_success(self):
        ex = make_executor()
        result = ex.place_market_order("TSLA", 5, "sell")
        assert result.success
        assert result.side == "sell"

    def test_market_order_recorded_in_history(self):
        ex = make_executor()
        ex.place_market_order("AAPL", 10, "buy")
        assert len(ex.order_history) == 1

    def test_multiple_orders_in_history(self):
        ex = make_executor()
        ex.place_market_order("AAPL", 10, "buy")
        ex.place_market_order("TSLA", 5, "sell")
        assert len(ex.order_history) == 2


class TestLimitOrders:
    def test_limit_buy_success(self):
        ex = make_executor()
        result = ex.place_limit_order("AAPL", 10, "buy", limit_price=149.50)
        assert result.success
        assert result.order_type == "limit"
        assert result.limit_price == 149.50

    def test_limit_sell_success(self):
        ex = make_executor()
        result = ex.place_limit_order("AAPL", 10, "sell", limit_price=155.00)
        assert result.success
        assert result.side == "sell"
        assert result.limit_price == 155.00

    def test_limit_price_passed_to_broker(self):
        captured_kwargs = {}

        def capturing_broker(symbol, qty, side, limit_price=None, **kwargs):
            captured_kwargs.update({"limit_price": limit_price})
            return {"id": "cap-001", "status": "accepted"}

        cfg = ExecutorConfig(retry_delay_ms=0)
        ex = OrderExecutor(broker_fn=capturing_broker, config=cfg)
        ex.place_limit_order("AAPL", 5, "buy", limit_price=123.45)
        assert captured_kwargs["limit_price"] == 123.45


class TestRetryLogic:
    def test_retries_on_transient_error(self):
        call_count = 0

        def flaky_broker(symbol, qty, side, limit_price=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network timeout")
            return {"id": "retry-success", "status": "accepted"}

        cfg = ExecutorConfig(max_retries=3, retry_delay_ms=0)
        ex = OrderExecutor(broker_fn=flaky_broker, config=cfg)
        result = ex.place_market_order("AAPL", 10, "buy")
        assert result.success
        assert call_count == 3
        assert result.retries == 2

    def test_fails_after_max_retries(self):
        def always_fails(symbol, qty, side, **kwargs):
            raise RuntimeError("Server error")

        cfg = ExecutorConfig(max_retries=2, retry_delay_ms=0)
        ex = OrderExecutor(broker_fn=always_fails, config=cfg)
        result = ex.place_market_order("AAPL", 10, "buy")
        assert not result.success
        assert result.status == OrderStatus.FAILED
        assert "Server error" in result.error
        assert result.retries == 3

    def test_no_retry_on_immediate_success(self):
        call_count = 0

        def first_try_broker(symbol, qty, side, **kwargs):
            nonlocal call_count
            call_count += 1
            return {"id": "instant", "status": "accepted"}

        cfg = ExecutorConfig(max_retries=3, retry_delay_ms=0)
        ex = OrderExecutor(broker_fn=first_try_broker, config=cfg)
        result = ex.place_market_order("AAPL", 10, "buy")
        assert result.success
        assert call_count == 1
        assert result.retries == 0


class TestDryRunMode:
    def test_dry_run_does_not_call_broker(self):
        real_broker = MagicMock(return_value={"id": "real", "status": "accepted"})
        cfg = ExecutorConfig(dry_run=True)
        ex = OrderExecutor(broker_fn=real_broker, config=cfg)
        result = ex.place_market_order("AAPL", 10, "buy")
        real_broker.assert_not_called()
        assert result.success

    def test_dry_run_returns_dry_run_id(self):
        cfg = ExecutorConfig(dry_run=True)
        ex = OrderExecutor(broker_fn=None, config=cfg)
        result = ex.place_market_order("AAPL", 10, "buy")
        assert result.order_id.startswith("dry-run-")

    def test_dry_run_increments_order_id(self):
        cfg = ExecutorConfig(dry_run=True)
        ex = OrderExecutor(broker_fn=None, config=cfg)
        r1 = ex.place_market_order("AAPL", 1, "buy")
        r2 = ex.place_market_order("TSLA", 1, "buy")
        assert r1.order_id != r2.order_id

    def test_dry_run_still_records_history(self):
        cfg = ExecutorConfig(dry_run=True)
        ex = OrderExecutor(broker_fn=None, config=cfg)
        ex.place_market_order("AAPL", 10, "buy")
        ex.place_limit_order("TSLA", 5, "sell", limit_price=300.0)
        assert len(ex.order_history) == 2

    def test_dry_run_limit_order(self):
        cfg = ExecutorConfig(dry_run=True)
        ex = OrderExecutor(broker_fn=None, config=cfg)
        result = ex.place_limit_order("AAPL", 5, "buy", limit_price=148.75)
        assert result.success
        assert result.order_type == "limit"
        assert result.limit_price == 148.75


class TestOrderHistoryAndLookup:
    def test_get_order_by_id(self):
        ex = make_executor()
        result = ex.place_market_order("AAPL", 10, "buy")
        found = ex.get_order(result.order_id)
        assert found is not None
        assert found.order_id == result.order_id

    def test_get_order_not_found(self):
        ex = make_executor()
        assert ex.get_order("nonexistent-id") is None

    def test_order_history_is_copy(self):
        ex = make_executor()
        ex.place_market_order("AAPL", 10, "buy")
        history = ex.order_history
        history.clear()
        assert len(ex.order_history) == 1


class TestSlippageRecording:
    def test_record_fill_updates_slippage(self):
        ex = make_executor()
        result = ex.place_market_order("AAPL", 10, "buy")
        slippage = ex.record_fill(result.order_id, fill_price=151.0, signal_price=150.0)
        assert slippage is not None
        assert abs(slippage - 0.00667) < 0.0001

    def test_record_fill_updates_status(self):
        ex = make_executor()
        result = ex.place_market_order("AAPL", 10, "buy")
        ex.record_fill(result.order_id, fill_price=150.0, signal_price=150.0)
        updated = ex.get_order(result.order_id)
        assert updated.status == OrderStatus.FILLED

    def test_record_fill_returns_slippage_for_unknown_id(self):
        """record_fill calculates slippage even if order_id is not found."""
        ex = make_executor()
        slippage = ex.record_fill("unknown-id", fill_price=150.0, signal_price=150.0)
        assert slippage == 0.0

    def test_record_fill_warns_on_high_slippage(self, caplog):
        import logging

        ex = make_executor()
        result = ex.place_market_order("AAPL", 10, "buy")
        with caplog.at_level(
            logging.WARNING, logger="alpaca_trader.engine.order_executor"
        ):
            ex.record_fill(result.order_id, fill_price=160.0, signal_price=150.0)
        assert any("slippage" in record.message.lower() for record in caplog.records)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
