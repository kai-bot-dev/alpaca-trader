"""Earnings filter — skip trading around earnings events."""
from dataclasses import dataclass
from typing import Optional
import json
import asyncio

from alpaca_trader.core import client as alpaca
from alpaca_trader.core import database as db


# Known earnings months for major stocks (approximate — Q1 reports in April, Q2 in July, etc.)
# This is a heuristic; real implementation would use an earnings calendar API
_EARNINGS_SKIP_SYMBOLS: set = set()  # populated from DB


async def load_earnings_skip_list() -> set[str]:
    """Load manually maintained earnings skip list from DB."""
    await db.init_db()
    raw = await db.setting_get("earnings_skip_symbols")
    if raw:
        return set(json.loads(raw))
    return set()


async def add_to_earnings_skip(symbol: str) -> None:
    """Add a symbol to the earnings skip list."""
    await db.init_db()
    current = await load_earnings_skip_list()
    current.add(symbol.upper())
    await db.setting_set("earnings_skip_symbols", json.dumps(list(current)))


async def remove_from_earnings_skip(symbol: str) -> None:
    """Remove a symbol from the earnings skip list."""
    await db.init_db()
    current = await load_earnings_skip_list()
    current.discard(symbol.upper())
    await db.setting_set("earnings_skip_symbols", json.dumps(list(current)))


def has_unusual_volume(symbol: str, threshold: float = 2.5) -> bool:
    """Check if recent volume is unusually high (possible earnings/event approaching)."""
    try:
        df = alpaca.get_stock_bars_df(symbol, period='1D', limit=22)
        if len(df) < 20:
            return False
        avg_vol = df['volume'].iloc[:-1].mean()
        latest_vol = df['volume'].iloc[-1]
        return latest_vol > avg_vol * threshold
    except Exception:
        return False


@dataclass
class EarningsCheckResult:
    should_skip: bool
    reason: str


async def check_earnings(symbol: str) -> EarningsCheckResult:
    """Check if we should skip trading this symbol due to earnings."""
    skip_list = await load_earnings_skip_list()
    if symbol.upper() in skip_list:
        return EarningsCheckResult(True, f"{symbol} in earnings skip list")

    if has_unusual_volume(symbol):
        return EarningsCheckResult(True, f"{symbol} has unusual volume (possible event)")

    return EarningsCheckResult(False, "")
