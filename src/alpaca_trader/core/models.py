"""Pydantic models for alpaca-trader."""

from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --- Enums ---


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    DONE_FOR_DAY = "done_for_day"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REPLACED = "replaced"
    PENDING_CANCEL = "pending_cancel"
    PENDING_REPLACE = "pending_replace"
    ACCEPTED = "accepted"
    PENDING_NEW = "pending_new"
    ACCEPTED_FOR_BIDDING = "accepted_for_bidding"
    STOPPED = "stopped"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    CALCULATED = "calculated"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


class OptionStyle(str, Enum):
    AMERICAN = "american"
    EUROPEAN = "european"


# --- Account Models ---


class AccountInfo(BaseModel):
    id: str
    account_number: str
    status: str
    currency: str = "USD"
    buying_power: Decimal
    regt_buying_power: Optional[Decimal] = None
    daytrading_buying_power: Optional[Decimal] = None
    non_marginable_buying_power: Optional[Decimal] = None
    cash: Decimal
    portfolio_value: Decimal
    equity: Decimal
    last_equity: Optional[Decimal] = None
    long_market_value: Optional[Decimal] = None
    short_market_value: Optional[Decimal] = None
    initial_margin: Optional[Decimal] = None
    maintenance_margin: Optional[Decimal] = None
    pattern_day_trader: bool = False
    trading_blocked: bool = False
    transfers_blocked: bool = False
    account_blocked: bool = False
    created_at: Optional[datetime] = None
    trade_suspended_by_user: bool = False
    multiplier: Optional[str] = None
    shorting_enabled: bool = False
    day_trade_count: int = 0

    class Config:
        from_attributes = True


# --- Position Models ---


class Position(BaseModel):
    asset_id: str
    symbol: str
    exchange: Optional[str] = None
    asset_class: str
    avg_entry_price: Decimal
    qty: Decimal
    side: str
    market_value: Optional[Decimal] = None
    cost_basis: Optional[Decimal] = None
    unrealized_pl: Optional[Decimal] = None
    unrealized_plpc: Optional[Decimal] = None
    unrealized_intraday_pl: Optional[Decimal] = None
    unrealized_intraday_plpc: Optional[Decimal] = None
    current_price: Optional[Decimal] = None
    lastday_price: Optional[Decimal] = None
    change_today: Optional[Decimal] = None

    class Config:
        from_attributes = True


# --- Order Models ---


class Order(BaseModel):
    id: str
    client_order_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    replaced_at: Optional[datetime] = None
    replaced_by: Optional[str] = None
    replaces: Optional[str] = None
    asset_id: Optional[str] = None
    symbol: str
    asset_class: Optional[str] = None
    notional: Optional[Decimal] = None
    qty: Optional[Decimal] = None
    filled_qty: Optional[Decimal] = None
    filled_avg_price: Optional[Decimal] = None
    order_class: Optional[str] = None
    order_type: str
    type: Optional[str] = None
    side: str
    time_in_force: str
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    status: str
    extended_hours: bool = False
    legs: Optional[list] = None
    trail_percent: Optional[Decimal] = None
    trail_price: Optional[Decimal] = None
    hwm: Optional[Decimal] = None

    class Config:
        from_attributes = True


class PlaceOptionOrderRequest(BaseModel):
    symbol: str = Field(
        ..., description="Option contract symbol (e.g. AAPL241220C00180000)"
    )
    qty: int = Field(..., gt=0, description="Number of contracts")
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: Optional[Decimal] = Field(
        None, description="Required for limit orders"
    )


# --- Options Chain Models ---


class OptionGreeks(BaseModel):
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    rho: Optional[float] = None
    implied_volatility: Optional[float] = None


class OptionContract(BaseModel):
    id: Optional[str] = None
    symbol: str
    underlying_symbol: str
    expiration_date: date
    strike_price: Decimal
    option_type: OptionType
    style: Optional[OptionStyle] = None
    open_interest: Optional[int] = None
    open_interest_date: Optional[date] = None
    close_price: Optional[Decimal] = None
    close_price_date: Optional[date] = None

    # Market data (from snapshot)
    bid_price: Optional[Decimal] = None
    ask_price: Optional[Decimal] = None
    last_price: Optional[Decimal] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    volume: Optional[int] = None
    vwap: Optional[Decimal] = None

    # Greeks
    greeks: Optional[OptionGreeks] = None
    implied_volatility: Optional[float] = None

    class Config:
        from_attributes = True


class OptionsChainResponse(BaseModel):
    underlying_symbol: str
    contracts: list[OptionContract]
    total: int


# --- Watchlist Models ---


class WatchlistItem(BaseModel):
    id: Optional[int] = None
    symbol: str
    added_at: Optional[datetime] = None
    notes: Optional[str] = None


class WatchlistResponse(BaseModel):
    items: list[WatchlistItem]
    total: int


# --- Alert Config Models ---


class AlertConfig(BaseModel):
    id: Optional[int] = None
    symbol: str
    alert_type: str  # pnl_threshold, expiry_warning, price_target, bollinger_signal
    threshold_value: Optional[float] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    triggered_at: Optional[datetime] = None
    notes: Optional[str] = None


# --- Multi-Leg Order Models ---


class SpreadType(str, Enum):
    VERTICAL = "vertical"
    CONDOR = "condor"
    STRADDLE = "straddle"
    STRANGLE = "strangle"


class SpreadLeg(BaseModel):
    symbol: str = Field(..., description="Option contract symbol")
    ratio_qty: float = Field(1.0, description="Proportional quantity for this leg")
    side: OrderSide
    position_intent: str = Field(
        ..., description="buy_to_open, buy_to_close, sell_to_open, sell_to_close"
    )


class SpreadOrderRequest(BaseModel):
    leg1: SpreadLeg
    leg2: SpreadLeg
    qty: int = Field(1, gt=0)
    time_in_force: TimeInForce = TimeInForce.DAY


class IronCondorRequest(BaseModel):
    legs: list[SpreadLeg] = Field(..., min_length=4, max_length=4)
    qty: int = Field(1, gt=0)
    time_in_force: TimeInForce = TimeInForce.DAY


class StraddleRequest(BaseModel):
    symbol: str
    expiry: date
    strike: float
    qty: int = Field(1, gt=0)
    time_in_force: TimeInForce = TimeInForce.DAY


class StrangleRequest(BaseModel):
    symbol: str
    expiry: date
    call_strike: float
    put_strike: float
    qty: int = Field(1, gt=0)
    time_in_force: TimeInForce = TimeInForce.DAY


# --- P&L Tracking Models ---


class PositionSnapshot(BaseModel):
    id: Optional[int] = None
    symbol: str
    timestamp: datetime
    qty: float
    avg_entry: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float = 0.0


class PositionPnL(BaseModel):
    symbol: str
    qty: float
    avg_entry: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    pct_change: float
    market_value: float
    cost_basis: float


# --- API Response Models ---


class SuccessResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[dict] = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None
