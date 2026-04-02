"""Unit tests for models module."""

import pytest
from decimal import Decimal
from datetime import datetime

from alpaca_trader.core.models import (
    OrderSide,
    OrderType,
    OrderStatus,
    TimeInForce,
    OptionType,
    AccountInfo,
    Position,
    Order,
)


class TestEnums:
    """Tests for model enums."""

    def test_order_side_enum(self):
        """Test OrderSide enum values."""
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_type_enum(self):
        """Test OrderType enum values."""
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP.value == "stop"
        assert OrderType.STOP_LIMIT.value == "stop_limit"

    def test_order_status_enum(self):
        """Test OrderStatus enum values."""
        assert OrderStatus.NEW.value == "new"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELED.value == "canceled"

    def test_time_in_force_enum(self):
        """Test TimeInForce enum values."""
        assert TimeInForce.DAY.value == "day"
        assert TimeInForce.GTC.value == "gtc"
        assert TimeInForce.IOC.value == "ioc"
        assert TimeInForce.FOK.value == "fok"

    def test_option_type_enum(self):
        """Test OptionType enum values."""
        assert OptionType.CALL.value == "call"
        assert OptionType.PUT.value == "put"


class TestAccountInfo:
    """Tests for AccountInfo model."""

    def test_account_info_creation(self):
        """Test creating an AccountInfo instance."""
        account = AccountInfo(
            id="test-id",
            account_number="123456",
            status="active",
            buying_power=Decimal("10000.00"),
            cash=Decimal("5000.00"),
            portfolio_value=Decimal("15000.00"),
            equity=Decimal("15000.00"),
        )
        assert account.id == "test-id"
        assert account.account_number == "123456"
        assert account.status == "active"
        assert account.buying_power == Decimal("10000.00")
        assert account.cash == Decimal("5000.00")

    def test_account_info_default_currency(self):
        """Test that AccountInfo defaults currency to USD."""
        account = AccountInfo(
            id="test-id",
            account_number="123456",
            status="active",
            buying_power=Decimal("10000.00"),
            cash=Decimal("5000.00"),
            portfolio_value=Decimal("15000.00"),
            equity=Decimal("15000.00"),
        )
        assert account.currency == "USD"

    def test_account_info_pattern_day_trader_default(self):
        """Test that pattern_day_trader defaults to False."""
        account = AccountInfo(
            id="test-id",
            account_number="123456",
            status="active",
            buying_power=Decimal("10000.00"),
            cash=Decimal("5000.00"),
            portfolio_value=Decimal("15000.00"),
            equity=Decimal("15000.00"),
        )
        assert account.pattern_day_trader is False


class TestPosition:
    """Tests for Position model."""

    def test_position_creation(self):
        """Test creating a Position instance."""
        position = Position(
            asset_id="test-asset-id",
            symbol="AAPL",
            exchange="NASDAQ",
            asset_class="us_equity",
            avg_entry_price=Decimal("150.00"),
            qty=10,
            side="long",
            market_value=Decimal("1510.00"),
            cost_basis=Decimal("1500.00"),
            unrealized_pl=Decimal("10.00"),
            unrealized_plpc=Decimal("0.0067"),
            current_price=Decimal("151.00"),
            lastday_price=Decimal("150.00"),
            change_today=Decimal("1.00"),
        )
        assert position.symbol == "AAPL"
        assert position.qty == 10
        assert position.side == "long"
        assert position.avg_entry_price == Decimal("150.00")


class TestOrder:
    """Tests for Order model."""

    def test_order_creation(self):
        """Test creating an Order instance."""
        now = datetime.now()
        order = Order(
            id="order-123",
            client_order_id="client-123",
            created_at=now,
            updated_at=now,
            submitted_at=now,
            filled_at=None,
            expired_at=None,
            canceled_at=None,
            failed_at=None,
            replaced_at=None,
            replaced_by=None,
            replaces=None,
            asset_id="asset-123",
            symbol="AAPL",
            asset_class="us_equity",
            qty=Decimal("10"),
            filled_qty=Decimal("0"),
            order_type="limit",
            side="buy",
            time_in_force="day",
            limit_price=Decimal("150.00"),
            stop_price=None,
            trail_percent=None,
            trail_price=None,
            hwm=None,
            status="new",
            extended_hours=False,
            legs=None,
            order_class=None,
            filled_avg_price=None,
        )
        assert order.symbol == "AAPL"
        assert order.qty == Decimal("10")
        assert order.side == "buy"
        assert order.status == "new"
        assert order.order_type == "limit"
        assert order.limit_price == Decimal("150.00")

    def test_order_minimal_creation(self):
        """Test creating an Order with minimal required fields."""
        order = Order(
            id="order-456",
            symbol="TSLA",
            order_type="market",
            side="sell",
            time_in_force="day",
            status="filled",
        )
        assert order.id == "order-456"
        assert order.symbol == "TSLA"
        assert order.order_type == "market"
        assert order.side == "sell"
        assert order.extended_hours is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
