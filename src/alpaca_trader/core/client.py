"""Alpaca API client wrapper for alpaca-trader."""

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    GetOptionContractsRequest,
    OptionLegRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    OrderType,
    TimeInForce,
    QueryOrderStatus,
    ContractType,
    ExerciseStyle,
    OrderClass,
    PositionIntent,
)
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import OptionSnapshotRequest, OptionChainRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from dotenv import load_dotenv

load_dotenv()

_ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
_ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
_ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")


def _get_trading_client() -> TradingClient:
    """Create and return an Alpaca TradingClient."""
    if not _ALPACA_API_KEY or not _ALPACA_SECRET_KEY:
        raise EnvironmentError(
            "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in your .env file. "
            "Copy .env.example to .env and fill in your Alpaca paper trading credentials."
        )
    paper = "paper" in _ALPACA_BASE_URL.lower()
    return TradingClient(
        api_key=_ALPACA_API_KEY,
        secret_key=_ALPACA_SECRET_KEY,
        paper=paper,
    )


def _get_data_client() -> OptionHistoricalDataClient:
    """Create and return an Alpaca OptionHistoricalDataClient."""
    if not _ALPACA_API_KEY or not _ALPACA_SECRET_KEY:
        raise EnvironmentError(
            "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in your .env file."
        )
    return OptionHistoricalDataClient(
        api_key=_ALPACA_API_KEY,
        secret_key=_ALPACA_SECRET_KEY,
    )


def _serialize(obj) -> dict:
    """Convert an Alpaca SDK object to a plain dict."""
    from enum import Enum
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, "__dict__"):
        result = {}
        for k, v in obj.__dict__.items():
            if k.startswith("_"):
                continue
            if isinstance(v, Enum):
                result[k] = v.value
            elif isinstance(v, (datetime, date)):
                result[k] = v.isoformat()
            elif isinstance(v, Decimal):
                result[k] = str(v)
            elif hasattr(v, "__dict__"):
                result[k] = _serialize(v)
            elif isinstance(v, list):
                result[k] = [_serialize(i) if hasattr(i, "__dict__") else i for i in v]
            else:
                result[k] = v
        return result
    return obj


# --- Account ---

def get_account() -> dict:
    """Get account information."""
    client = _get_trading_client()
    account = client.get_account()
    return _serialize(account)


# --- Positions ---

def get_positions() -> list[dict]:
    """Get all open positions."""
    client = _get_trading_client()
    positions = client.get_all_positions()
    return [_serialize(p) for p in positions]


def get_position(symbol_or_id: str) -> dict:
    """Get a specific position by symbol or asset ID."""
    client = _get_trading_client()
    position = client.get_open_position(symbol_or_id)
    return _serialize(position)


def close_position(symbol_or_id: str) -> dict:
    """Close a specific position."""
    client = _get_trading_client()
    order = client.close_position(symbol_or_id)
    return _serialize(order)


# --- Orders ---

def get_orders(
    status: Optional[str] = None,
    limit: int = 100,
    after: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> list[dict]:
    """Get orders with optional filtering."""
    client = _get_trading_client()

    query_status = None
    if status == "open":
        query_status = QueryOrderStatus.OPEN
    elif status == "closed":
        query_status = QueryOrderStatus.CLOSED
    elif status == "all":
        query_status = QueryOrderStatus.ALL

    request = GetOrdersRequest(
        status=query_status or QueryOrderStatus.ALL,
        limit=limit,
        after=after,
        until=until,
    )
    orders = client.get_orders(request)
    return [_serialize(o) for o in orders]


def get_order(order_id: str) -> dict:
    """Get a specific order by ID."""
    client = _get_trading_client()
    order = client.get_order_by_id(order_id)
    return _serialize(order)


def place_market_order(
    symbol: str,
    qty: int,
    side: str,
    time_in_force: str = "day",
) -> dict:
    """Place a market order."""
    client = _get_trading_client()
    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
    tif = _parse_tif(time_in_force)
    request = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=order_side,
        time_in_force=tif,
    )
    order = client.submit_order(request)
    return _serialize(order)


def place_limit_order(
    symbol: str,
    qty: int,
    side: str,
    limit_price: float,
    time_in_force: str = "day",
) -> dict:
    """Place a limit order."""
    client = _get_trading_client()
    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
    tif = _parse_tif(time_in_force)
    request = LimitOrderRequest(
        symbol=symbol,
        qty=qty,
        side=order_side,
        limit_price=limit_price,
        time_in_force=tif,
    )
    order = client.submit_order(request)
    return _serialize(order)


def cancel_order(order_id: str) -> bool:
    """Cancel an order by ID. Returns True if cancelled."""
    client = _get_trading_client()
    client.cancel_order_by_id(order_id)
    return True


def cancel_all_orders() -> list[str]:
    """Cancel all open orders. Returns list of cancelled order IDs."""
    client = _get_trading_client()
    result = client.cancel_orders()
    return [_serialize(r) for r in result]


# --- Options Chain ---

def get_options_contracts(
    underlying_symbol: str,
    expiration_date: Optional[date] = None,
    expiration_date_gte: Optional[date] = None,
    expiration_date_lte: Optional[date] = None,
    strike_price_gte: Optional[float] = None,
    strike_price_lte: Optional[float] = None,
    option_type: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Get options contracts for an underlying symbol."""
    client = _get_trading_client()

    contract_type = None
    if option_type:
        if option_type.lower() == "call":
            contract_type = ContractType.CALL
        elif option_type.lower() == "put":
            contract_type = ContractType.PUT

    request = GetOptionContractsRequest(
        underlying_symbols=[underlying_symbol.upper()],
        expiration_date=expiration_date,
        expiration_date_gte=expiration_date_gte,
        expiration_date_lte=expiration_date_lte,
        strike_price_gte=str(strike_price_gte) if strike_price_gte else None,
        strike_price_lte=str(strike_price_lte) if strike_price_lte else None,
        type=contract_type,
        limit=limit,
    )
    response = client.get_option_contracts(request)
    contracts = response.option_contracts if hasattr(response, "option_contracts") else []
    return [_serialize(c) for c in contracts]


def get_option_snapshots(symbols: list[str]) -> dict:
    """Get market snapshots (bid/ask, Greeks) for option symbols."""
    if not symbols:
        return {}
    data_client = _get_data_client()
    request = OptionSnapshotRequest(symbol_or_symbols=symbols)
    snapshots = data_client.get_option_snapshot(request)
    result = {}
    for symbol, snap in snapshots.items():
        result[symbol] = _serialize(snap)
    return result


def get_option_chain(
    underlying_symbol: str,
    expiration_date: Optional[date] = None,
    option_type: Optional[str] = None,
    strike_price_gte: Optional[float] = None,
    strike_price_lte: Optional[float] = None,
    limit: int = 100,
) -> list[dict]:
    """Get full options chain with Greeks/snapshots for an underlying."""
    # Step 1: Get contracts
    contracts = get_options_contracts(
        underlying_symbol=underlying_symbol,
        expiration_date=expiration_date,
        strike_price_gte=strike_price_gte,
        strike_price_lte=strike_price_lte,
        option_type=option_type,
        limit=limit,
    )

    if not contracts:
        return []

    # Step 2: Get snapshots for all contract symbols
    symbols = [c["symbol"] for c in contracts if c.get("symbol")]
    snapshots = {}
    if symbols:
        try:
            # Batch in groups of 50 to avoid URL length limits
            for i in range(0, len(symbols), 50):
                batch = symbols[i : i + 50]
                batch_snaps = get_option_snapshots(batch)
                snapshots.update(batch_snaps)
        except Exception:
            # Snapshots are optional - contracts without them still useful
            pass

    # Step 3: Merge snapshot data into contracts
    enriched = []
    for contract in contracts:
        sym = contract.get("symbol")
        snap = snapshots.get(sym, {})
        merged = {**contract}

        # Extract greeks from snapshot
        greeks = snap.get("greeks", {})
        if greeks:
            merged["greeks"] = {
                "delta": greeks.get("delta"),
                "gamma": greeks.get("gamma"),
                "theta": greeks.get("theta"),
                "vega": greeks.get("vega"),
                "rho": greeks.get("rho"),
                "implied_volatility": snap.get("implied_volatility"),
            }

        # Extract quote data
        latest_quote = snap.get("latest_quote", {})
        if latest_quote:
            merged["bid_price"] = latest_quote.get("bp")
            merged["ask_price"] = latest_quote.get("ap")
            merged["bid_size"] = latest_quote.get("bs")
            merged["ask_size"] = latest_quote.get("as")

        # Extract trade data
        latest_trade = snap.get("latest_trade", {})
        if latest_trade:
            merged["last_price"] = latest_trade.get("p")
            merged["volume"] = latest_trade.get("s")

        enriched.append(merged)

    return enriched


# --- Multi-Leg Orders ---

def _build_leg(symbol: str, ratio_qty: float, side: str, position_intent: str) -> OptionLegRequest:
    """Build an OptionLegRequest from plain params."""
    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
    intent_map = {
        "buy_to_open": PositionIntent.BUY_TO_OPEN,
        "buy_to_close": PositionIntent.BUY_TO_CLOSE,
        "sell_to_open": PositionIntent.SELL_TO_OPEN,
        "sell_to_close": PositionIntent.SELL_TO_CLOSE,
    }
    intent = intent_map.get(position_intent.lower(), PositionIntent.BUY_TO_OPEN)
    return OptionLegRequest(symbol=symbol, ratio_qty=ratio_qty, side=order_side, position_intent=intent)


def _submit_mleg(legs: list[OptionLegRequest], qty: int, time_in_force: str = "day") -> dict:
    """Submit a multi-leg market order."""
    client = _get_trading_client()
    tif = _parse_tif(time_in_force)
    request = MarketOrderRequest(
        order_class=OrderClass.MLEG,
        qty=qty,
        time_in_force=tif,
        legs=legs,
    )
    order = client.submit_order(request)
    return _serialize(order)


def place_spread_order(
    leg1: dict,
    leg2: dict,
    qty: int = 1,
    time_in_force: str = "day",
) -> dict:
    """Place a 2-leg vertical spread order.

    Each leg dict: {symbol, ratio_qty, side, position_intent}
    """
    legs = [
        _build_leg(leg1["symbol"], leg1.get("ratio_qty", 1.0), leg1["side"], leg1["position_intent"]),
        _build_leg(leg2["symbol"], leg2.get("ratio_qty", 1.0), leg2["side"], leg2["position_intent"]),
    ]
    return _submit_mleg(legs, qty, time_in_force)


def place_iron_condor(
    legs: list[dict],
    qty: int = 1,
    time_in_force: str = "day",
) -> dict:
    """Place a 4-leg iron condor order.

    legs: list of 4 dicts each with {symbol, ratio_qty, side, position_intent}
    """
    if len(legs) != 4:
        raise ValueError("Iron condor requires exactly 4 legs")
    built = [_build_leg(l["symbol"], l.get("ratio_qty", 1.0), l["side"], l["position_intent"]) for l in legs]
    return _submit_mleg(built, qty, time_in_force)


def place_straddle(
    symbol: str,
    expiry: date,
    strike: float,
    qty: int = 1,
    time_in_force: str = "day",
) -> dict:
    """Buy a straddle: call + put at the same strike and expiry."""
    call_sym = build_option_symbol(symbol, expiry, "call", strike)
    put_sym = build_option_symbol(symbol, expiry, "put", strike)
    legs = [
        _build_leg(call_sym, 1.0, "buy", "buy_to_open"),
        _build_leg(put_sym, 1.0, "buy", "buy_to_open"),
    ]
    return _submit_mleg(legs, qty, time_in_force)


def place_strangle(
    symbol: str,
    expiry: date,
    call_strike: float,
    put_strike: float,
    qty: int = 1,
    time_in_force: str = "day",
) -> dict:
    """Buy a strangle: OTM call + OTM put at different strikes, same expiry."""
    call_sym = build_option_symbol(symbol, expiry, "call", call_strike)
    put_sym = build_option_symbol(symbol, expiry, "put", put_strike)
    legs = [
        _build_leg(call_sym, 1.0, "buy", "buy_to_open"),
        _build_leg(put_sym, 1.0, "buy", "buy_to_open"),
    ]
    return _submit_mleg(legs, qty, time_in_force)


# --- P&L Calculations ---

def calculate_position_pnl(position: dict) -> dict:
    """Calculate unrealized/realized/total P&L for a position dict.

    Returns a dict with: unrealized_pnl, realized_pnl, total_pnl, pct_change,
    market_value, cost_basis, avg_entry, current_price, qty, symbol.
    """
    qty = float(position.get("qty", 0))
    avg_entry = float(position.get("avg_entry_price", 0))
    current_price = float(position.get("current_price", 0) or 0)
    market_value = float(position.get("market_value", 0) or current_price * qty)
    cost_basis = float(position.get("cost_basis", 0) or avg_entry * qty)

    unrealized_pnl = float(position.get("unrealized_pl", 0) or (market_value - cost_basis))
    realized_pnl = 0.0  # Alpaca positions only show unrealized; realized tracked via snapshots
    total_pnl = unrealized_pnl + realized_pnl
    pct_change = float(position.get("unrealized_plpc", 0) or (unrealized_pnl / cost_basis if cost_basis else 0))

    return {
        "symbol": position.get("symbol", ""),
        "qty": qty,
        "avg_entry": avg_entry,
        "current_price": current_price,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "unrealized_pnl": unrealized_pnl,
        "realized_pnl": realized_pnl,
        "total_pnl": total_pnl,
        "pct_change": pct_change,
    }


async def take_position_snapshot() -> list[dict]:
    """Fetch current positions and save a P&L snapshot to the database.

    Returns the list of snapshots saved.
    """
    from alpaca_trader.core.database import save_position_snapshot

    positions = get_positions()
    snapshots = []
    for pos in positions:
        pnl = calculate_position_pnl(pos)
        snapshot = {
            "symbol": pnl["symbol"],
            "qty": pnl["qty"],
            "avg_entry": pnl["avg_entry"],
            "current_price": pnl["current_price"],
            "unrealized_pnl": pnl["unrealized_pnl"],
            "realized_pnl": pnl["realized_pnl"],
        }
        await save_position_snapshot(snapshot)
        snapshots.append(snapshot)
    return snapshots


# --- Historical Stock Data ---

def _get_stock_data_client() -> StockHistoricalDataClient:
    """Create and return an Alpaca StockHistoricalDataClient."""
    if not _ALPACA_API_KEY or not _ALPACA_SECRET_KEY:
        raise EnvironmentError(
            "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in your .env file."
        )
    return StockHistoricalDataClient(
        api_key=_ALPACA_API_KEY,
        secret_key=_ALPACA_SECRET_KEY,
    )


def get_stock_bars(
    symbol: str,
    period: str = "1D",
    limit: int = 100,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> list[dict]:
    """Fetch historical OHLCV bars for a stock symbol.

    period: '1D' (1 day), '1H' (1 hour), '15Min', '5Min', '1Min'
    Returns list of dicts with keys: timestamp, open, high, low, close, volume
    """
    client = _get_stock_data_client()

    # Parse period string to TimeFrame
    period_map = {
        "1D": TimeFrame.Day,
        "1H": TimeFrame.Hour,
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "1Min": TimeFrame.Minute,
    }
    timeframe = period_map.get(period, TimeFrame.Day)

    # If no start date given, default to enough history for Bollinger Bands (20-period)
    if start is None and end is None:
        from datetime import timedelta
        # For daily bars, go back ~6 months; for intraday, 30 days
        if timeframe == TimeFrame.Day:
            start = datetime.now(timezone.utc) - timedelta(days=180)
        else:
            start = datetime.now(timezone.utc) - timedelta(days=30)

    request = StockBarsRequest(
        symbol_or_symbols=symbol.upper(),
        timeframe=timeframe,
        limit=limit,
        start=start,
        end=end,
    )
    bars = client.get_stock_bars(request)

    result = []
    try:
        bar_data = bars[symbol.upper()]
    except (KeyError, IndexError):
        try:
            bar_data = bars[symbol]
        except (KeyError, IndexError):
            bar_data = []
    for bar in bar_data:
        b = _serialize(bar)
        result.append({
            "timestamp": b.get("timestamp"),
            "open": float(b.get("open", 0)),
            "high": float(b.get("high", 0)),
            "low": float(b.get("low", 0)),
            "close": float(b.get("close", 0)),
            "volume": float(b.get("volume", 0)),
        })
    return result


def get_stock_bars_df(
    symbol: str,
    period: str = "1D",
    limit: int = 100,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
):
    """Fetch historical bars and return as a pandas DataFrame with OHLCV columns."""
    import pandas as pd
    bars = get_stock_bars(symbol, period=period, limit=limit, start=start, end=end)
    if not bars:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(bars)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    return df


# --- Helper ---

def _parse_tif(tif: str) -> TimeInForce:
    mapping = {
        "day": TimeInForce.DAY,
        "gtc": TimeInForce.GTC,
        "ioc": TimeInForce.IOC,
        "fok": TimeInForce.FOK,
    }
    return mapping.get(tif.lower(), TimeInForce.DAY)


def build_option_symbol(
    underlying: str,
    expiry: date,
    option_type: str,
    strike: float,
) -> str:
    """Build an OCC option symbol.
    Format: SYMBOL + YYMMDD + C/P + 8-digit strike (padded, 3 decimal places)
    Example: AAPL241220C00180000 = AAPL, Dec 20 2024, Call, $180.00
    """
    underlying = underlying.upper().ljust(6)
    date_str = expiry.strftime("%y%m%d")
    cp = "C" if option_type.lower() == "call" else "P"
    strike_int = int(round(strike * 1000))
    strike_str = f"{strike_int:08d}"
    return f"{underlying.strip()}{date_str}{cp}{strike_str}"
