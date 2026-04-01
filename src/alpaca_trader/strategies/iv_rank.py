"""IV Rank tracking — determines if current IV is cheap or expensive relative to recent history."""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional
import asyncio

from alpaca_trader.core import client as alpaca
from alpaca_trader.core import database as db


@dataclass
class IVRankResult:
    symbol: str
    current_iv: float  # current implied volatility (from option chain)
    iv_rank: float  # 0-100, where current IV sits in its 30-day range
    iv_high_30d: float
    iv_low_30d: float
    is_cheap: bool  # IV rank < 40
    is_expensive: bool  # IV rank > 60


def get_iv_from_chain(symbol: str) -> Optional[float]:
    """Get current IV from the nearest ATM option."""
    try:
        bars = alpaca.get_stock_bars(symbol, period='1D', limit=2)
        if not bars:
            return None
        price = bars[-1]['close']

        from datetime import date, timedelta
        today = date.today()
        expiry_start = today + timedelta(days=5)
        expiry_end = today + timedelta(days=14)

        contracts = alpaca.get_option_chain(
            underlying_symbol=symbol,
            expiration_date_gte=expiry_start,
            expiration_date_lte=expiry_end,
            option_type='call',
            strike_price_gte=price * 0.97,
            strike_price_lte=price * 1.03,
            limit=10,
        )

        ivs = []
        for c in contracts:
            greeks = c.get('greeks') or {}
            iv = greeks.get('implied_volatility')
            if iv and float(iv) > 0:
                ivs.append(float(iv))

        return sum(ivs) / len(ivs) if ivs else None
    except Exception:
        return None


async def get_iv_rank(symbol: str) -> IVRankResult:
    """Calculate IV rank for a symbol using stored IV history."""
    await db.init_db()
    current_iv = get_iv_from_chain(symbol)

    if current_iv is None:
        return IVRankResult(symbol=symbol, current_iv=0, iv_rank=50,
                            iv_high_30d=0, iv_low_30d=0, is_cheap=False, is_expensive=False)

    # Store current IV
    key = f"iv_history_{symbol}"
    import json
    history_raw = await db.setting_get(key)
    history = json.loads(history_raw) if history_raw else []

    # Add today's reading
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    # Don't duplicate same-day entries
    if not history or history[-1].get('date') != today:
        history.append({'date': today, 'iv': current_iv})
    else:
        history[-1]['iv'] = current_iv

    # Keep last 60 days
    history = history[-60:]
    await db.setting_set(key, json.dumps(history))

    # Calculate rank
    ivs = [h['iv'] for h in history]
    iv_high = max(ivs)
    iv_low = min(ivs)

    if iv_high == iv_low:
        rank = 50.0
    else:
        rank = ((current_iv - iv_low) / (iv_high - iv_low)) * 100

    return IVRankResult(
        symbol=symbol, current_iv=current_iv, iv_rank=rank,
        iv_high_30d=iv_high, iv_low_30d=iv_low,
        is_cheap=rank < 40, is_expensive=rank > 60
    )
