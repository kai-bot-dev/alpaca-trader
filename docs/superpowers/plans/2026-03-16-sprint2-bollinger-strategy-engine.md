# Sprint 2: Bollinger Band Strategy Engine Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Bollinger Band strategy engine with squeeze, bounce, and trend detectors, a watchlist scanner, backtester, and CLI commands.

**Architecture:** Pure pandas/numpy for all TA calculations (no pandas-ta). Historical OHLCV bars fetched from Alpaca's StockHistoricalDataClient. Each strategy module is self-contained with dataclass signal outputs. Scanner and backtester compose the strategy modules.

**Tech Stack:** Python, pandas, numpy, alpaca-py (StockHistoricalDataClient), typer (CLI)

---

## Chunk 1: Dependencies + Historical Data Fetching

### Task 1: Add pandas/numpy to pyproject.toml and add get_stock_bars to client.py

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/alpaca_trader/core/client.py`

- [ ] **Step 1: Add pandas and numpy to dependencies in pyproject.toml**

In the `dependencies` list, add:
```toml
"pandas>=2.0.0",
"numpy>=1.24.0",
```

- [ ] **Step 2: Install the new dependencies**

Run: `cd /Users/tonylesmb/claw-workspace/alpaca-trader && pip install pandas numpy -q`
Expected: Success

- [ ] **Step 3: Add get_stock_bars function to client.py**

Add these imports at the top of `src/alpaca_trader/core/client.py`:
```python
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
```

Add this function at the bottom of client.py (before the Helper section):
```python
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
    import pandas as pd

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

    request = StockBarsRequest(
        symbol_or_symbols=symbol.upper(),
        timeframe=timeframe,
        limit=limit,
        start=start,
        end=end,
    )
    bars = client.get_stock_bars(request)

    result = []
    bar_data = bars.get(symbol.upper(), bars.get(symbol, []))
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
```

- [ ] **Step 4: Verify import works**

Run: `cd /Users/tonylesmb/claw-workspace/alpaca-trader && python -c "from alpaca_trader.core.client import get_stock_bars_df; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd /Users/tonylesmb/claw-workspace/alpaca-trader
git add pyproject.toml src/alpaca_trader/core/client.py
git commit -m "feat: add pandas/numpy deps and stock bars fetching to client"
```

---

## Chunk 2: Core Strategy Modules

### Task 2: Create strategies/__init__.py and bollinger.py

**Files:**
- Create: `src/alpaca_trader/strategies/__init__.py`
- Create: `src/alpaca_trader/strategies/bollinger.py`

- [ ] **Step 1: Create `src/alpaca_trader/strategies/__init__.py`**

```python
"""Bollinger Band strategy modules for alpaca-trader."""

from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.squeeze import SqueezeDetector, SqueezeSignal
from alpaca_trader.strategies.bounce import BounceDetector, BounceSignal
from alpaca_trader.strategies.trend import TrendDetector, TrendSignal
from alpaca_trader.strategies.scanner import WatchlistScanner
from alpaca_trader.strategies.backtest import Backtester, BacktestResult

__all__ = [
    "BollingerBands",
    "SqueezeDetector", "SqueezeSignal",
    "BounceDetector", "BounceSignal",
    "TrendDetector", "TrendSignal",
    "WatchlistScanner",
    "Backtester", "BacktestResult",
]
```

- [ ] **Step 2: Create `src/alpaca_trader/strategies/bollinger.py`**

```python
"""Bollinger Band calculations using pure pandas/numpy."""

import numpy as np
import pandas as pd


class BollingerBands:
    """Calculates Bollinger Bands for OHLCV price data.

    Parameters:
        period: Rolling window for SMA/std (default 20)
        std_dev: Number of standard deviations for bands (default 2.0)
    """

    def __init__(self, period: int = 20, std_dev: float = 2.0):
        self.period = period
        self.std_dev = std_dev

    def calc(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate Bollinger Bands.

        Args:
            df: DataFrame with at least a 'close' column (OHLCV format)

        Returns:
            Input DataFrame with added columns:
                bb_middle: Simple moving average of close
                bb_upper: Upper band (middle + std_dev * rolling_std)
                bb_lower: Lower band (middle - std_dev * rolling_std)
                bb_width: Band width relative to price: (upper - lower) / middle
                bb_pct: %B — position of price within bands: (close - lower) / (upper - lower)
        """
        if "close" not in df.columns:
            raise ValueError("DataFrame must have a 'close' column")
        if len(df) < self.period:
            raise ValueError(
                f"DataFrame has {len(df)} rows, need at least {self.period} for period={self.period}"
            )

        close = df["close"]
        rolling = close.rolling(window=self.period)
        middle = rolling.mean()
        std = rolling.std(ddof=1)

        upper = middle + self.std_dev * std
        lower = middle - self.std_dev * std

        result = df.copy()
        result["bb_middle"] = middle
        result["bb_upper"] = upper
        result["bb_lower"] = lower
        result["bb_width"] = (upper - lower) / middle
        result["bb_pct"] = (close - lower) / (upper - lower)
        return result
```

- [ ] **Step 3: Verify bollinger.py works**

```python
import pandas as pd
import numpy as np
from alpaca_trader.strategies.bollinger import BollingerBands
df = pd.DataFrame({"close": np.random.uniform(100, 110, 30)})
bb = BollingerBands()
result = bb.calc(df)
assert "bb_upper" in result.columns
assert "bb_lower" in result.columns
assert "bb_width" in result.columns
assert "bb_pct" in result.columns
print("BollingerBands OK")
```

Run: `cd /Users/tonylesmb/claw-workspace/alpaca-trader && python -c "$(cat above)"`
Expected: `BollingerBands OK`

- [ ] **Step 4: Commit**

```bash
cd /Users/tonylesmb/claw-workspace/alpaca-trader
git add src/alpaca_trader/strategies/
git commit -m "feat: add strategies package with BollingerBands calculator"
```

---

### Task 3: Create squeeze.py

**Files:**
- Create: `src/alpaca_trader/strategies/squeeze.py`

- [ ] **Step 1: Create `src/alpaca_trader/strategies/squeeze.py`**

```python
"""Squeeze (breakout) detection using Bollinger Band width contraction."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from alpaca_trader.strategies.bollinger import BollingerBands


@dataclass
class SqueezeSignal:
    detected: bool
    width: float          # Current BB width (relative to price)
    candle_outside: bool  # Most recent close is outside a band
    direction: str        # 'long', 'short', or 'none'
    strength: float       # 0.0–1.0: how far outside the band the close is


class SqueezeDetector:
    """Detects Bollinger Band squeeze (breakout setup).

    A squeeze is when BB width contracts below a threshold AND then price
    closes outside the band with volume confirmation.
    """

    def __init__(self, bb_period: int = 20, bb_std_dev: float = 2.0):
        self.bb = BollingerBands(period=bb_period, std_dev=bb_std_dev)

    def detect(self, df: pd.DataFrame, threshold: float = 0.05) -> SqueezeSignal:
        """Detect squeeze signal.

        Args:
            df: OHLCV DataFrame (must have close, volume columns)
            threshold: BB width threshold for squeeze detection (relative to price)

        Returns:
            SqueezeSignal with detection details
        """
        if len(df) < self.bb.period + 1:
            return SqueezeSignal(detected=False, width=0.0, candle_outside=False,
                                 direction="none", strength=0.0)

        enriched = self.bb.calc(df)

        latest = enriched.iloc[-1]
        width = float(latest["bb_width"]) if not pd.isna(latest["bb_width"]) else 0.0
        close = float(latest["close"])
        upper = float(latest["bb_upper"])
        lower = float(latest["bb_lower"])
        middle = float(latest["bb_middle"])

        # Check for squeeze: width is below threshold
        squeeze_active = width < threshold

        if not squeeze_active:
            return SqueezeSignal(detected=False, width=width, candle_outside=False,
                                 direction="none", strength=0.0)

        # Check candle outside band
        candle_outside = close > upper or close < lower

        if not candle_outside:
            return SqueezeSignal(detected=True, width=width, candle_outside=False,
                                 direction="none", strength=0.0)

        # Volume confirmation: current volume > 1.5x average
        if "volume" in df.columns:
            avg_vol = float(df["volume"].rolling(window=20).mean().iloc[-1])
            current_vol = float(df["volume"].iloc[-1])
            volume_confirmed = current_vol > 1.5 * avg_vol if avg_vol > 0 else False
        else:
            volume_confirmed = True  # No volume data → skip check

        if not volume_confirmed:
            return SqueezeSignal(detected=True, width=width, candle_outside=True,
                                 direction="none", strength=0.0)

        # Direction and strength
        if close > upper:
            direction = "long"
            band_range = upper - middle if upper != middle else 1.0
            strength = min(1.0, (close - upper) / band_range)
        else:
            direction = "short"
            band_range = middle - lower if middle != lower else 1.0
            strength = min(1.0, (lower - close) / band_range)

        return SqueezeSignal(
            detected=True,
            width=width,
            candle_outside=True,
            direction=direction,
            strength=float(strength),
        )
```

- [ ] **Step 2: Verify squeeze.py works**

Run: `cd /Users/tonylesmb/claw-workspace/alpaca-trader && python -c "from alpaca_trader.strategies.squeeze import SqueezeDetector, SqueezeSignal; print('SqueezeDetector OK')"`
Expected: `SqueezeDetector OK`

- [ ] **Step 3: Commit**

```bash
cd /Users/tonylesmb/claw-workspace/alpaca-trader
git add src/alpaca_trader/strategies/squeeze.py
git commit -m "feat: add SqueezeDetector for breakout signal detection"
```

---

### Task 4: Create bounce.py

**Files:**
- Create: `src/alpaca_trader/strategies/bounce.py`

- [ ] **Step 1: Create `src/alpaca_trader/strategies/bounce.py`**

```python
"""Bollinger Bounce (mean reversion) detection."""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from alpaca_trader.strategies.bollinger import BollingerBands


@dataclass
class BounceSignal:
    detected: bool
    direction: str       # 'long', 'short', or 'none'
    band_touched: str    # 'upper', 'lower', or 'none'
    rsi: float           # Current RSI value
    adx: float           # Current ADX value (range-bound if < 25)


def _calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI using Wilder's smoothing."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate ADX (Average Directional Index)."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    # True Range
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Directional Movement
    up_move = high.diff()
    down_move = -low.diff()
    pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    pos_dm_s = pd.Series(pos_dm, index=df.index)
    neg_dm_s = pd.Series(neg_dm, index=df.index)

    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    pos_di = 100 * pos_dm_s.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr.replace(0, np.nan)
    neg_di = 100 * neg_dm_s.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr.replace(0, np.nan)

    dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx


class BounceDetector:
    """Detects Bollinger Bounce (mean reversion) signals.

    Signals when price touches the lower or upper band in a range-bound market
    (ADX < 25). Confirmed by RSI being oversold/overbought.
    """

    def __init__(self, bb_period: int = 20, bb_std_dev: float = 2.0,
                 rsi_period: int = 14, adx_period: int = 14):
        self.bb = BollingerBands(period=bb_period, std_dev=bb_std_dev)
        self.rsi_period = rsi_period
        self.adx_period = adx_period

    def detect(self, df: pd.DataFrame) -> BounceSignal:
        """Detect bounce signal.

        Args:
            df: OHLCV DataFrame with columns: open, high, low, close, volume

        Returns:
            BounceSignal with detection details
        """
        min_rows = max(self.bb.period, self.rsi_period, self.adx_period) + 1
        if len(df) < min_rows:
            return BounceSignal(detected=False, direction="none",
                                band_touched="none", rsi=50.0, adx=0.0)

        enriched = self.bb.calc(df)
        rsi_series = _calc_rsi(df["close"], self.rsi_period)
        adx_series = _calc_adx(df, self.adx_period)

        latest = enriched.iloc[-1]
        close = float(latest["close"])
        upper = float(latest["bb_upper"])
        lower = float(latest["bb_lower"])
        rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0
        adx = float(adx_series.iloc[-1]) if not pd.isna(adx_series.iloc[-1]) else 0.0

        # Must be range-bound (ADX < 25)
        if adx >= 25:
            return BounceSignal(detected=False, direction="none",
                                band_touched="none", rsi=rsi, adx=adx)

        # Check band touch with RSI confirmation
        if close <= lower and rsi < 35:
            return BounceSignal(detected=True, direction="long",
                                band_touched="lower", rsi=rsi, adx=adx)
        elif close >= upper and rsi > 65:
            return BounceSignal(detected=True, direction="short",
                                band_touched="upper", rsi=rsi, adx=adx)

        return BounceSignal(detected=False, direction="none",
                            band_touched="none", rsi=rsi, adx=adx)
```

- [ ] **Step 2: Verify bounce.py works**

Run: `cd /Users/tonylesmb/claw-workspace/alpaca-trader && python -c "from alpaca_trader.strategies.bounce import BounceDetector, BounceSignal; print('BounceDetector OK')"`
Expected: `BounceDetector OK`

- [ ] **Step 3: Commit**

```bash
cd /Users/tonylesmb/claw-workspace/alpaca-trader
git add src/alpaca_trader/strategies/bounce.py
git commit -m "feat: add BounceDetector with RSI and ADX confirmation"
```

---

### Task 5: Create trend.py

**Files:**
- Create: `src/alpaca_trader/strategies/trend.py`

- [ ] **Step 1: Create `src/alpaca_trader/strategies/trend.py`**

```python
"""Trend (walking the bands) detection using Bollinger Bands + MACD."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from alpaca_trader.strategies.bollinger import BollingerBands


@dataclass
class TrendSignal:
    detected: bool
    direction: str    # 'long', 'short', or 'none'
    strength: float   # 0.0–1.0: proportion of last N candles along the band
    macd_hist: float  # Current MACD histogram value (positive = bullish)


def _calc_macd(close: pd.Series,
               fast: int = 12, slow: int = 26, signal: int = 9
               ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate MACD line, signal line, and histogram."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


class TrendDetector:
    """Detects 'walking the bands' — sustained price action along an outer BB.

    Uses MACD to confirm trend direction and strength.
    Looks back N candles to see if price consistently hugs the upper or lower band.
    """

    def __init__(self, bb_period: int = 20, bb_std_dev: float = 2.0,
                 lookback: int = 5,
                 macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9):
        self.bb = BollingerBands(period=bb_period, std_dev=bb_std_dev)
        self.lookback = lookback
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal_period = macd_signal

    def detect(self, df: pd.DataFrame) -> TrendSignal:
        """Detect trend (band-walking) signal.

        Args:
            df: OHLCV DataFrame with columns: open, high, low, close

        Returns:
            TrendSignal with detection details
        """
        min_rows = max(self.bb.period, self.macd_slow) + self.lookback
        if len(df) < min_rows:
            return TrendSignal(detected=False, direction="none",
                               strength=0.0, macd_hist=0.0)

        enriched = self.bb.calc(df)
        _, _, histogram = _calc_macd(
            df["close"], self.macd_fast, self.macd_slow, self.macd_signal_period
        )

        macd_hist = float(histogram.iloc[-1]) if not pd.isna(histogram.iloc[-1]) else 0.0

        # Check last N candles: price hugging upper or lower band
        recent = enriched.iloc[-self.lookback:]

        # Count candles where close >= bb_middle (upper walk) or <= bb_middle (lower walk)
        upper_hugging = (recent["close"] >= recent["bb_middle"]).sum()
        lower_hugging = (recent["close"] <= recent["bb_middle"]).sum()

        upper_strength = upper_hugging / self.lookback
        lower_strength = lower_hugging / self.lookback

        # Require at least 60% of candles hugging a band AND MACD confirmation
        if upper_strength >= 0.6 and macd_hist > 0:
            return TrendSignal(detected=True, direction="long",
                               strength=float(upper_strength), macd_hist=macd_hist)
        elif lower_strength >= 0.6 and macd_hist < 0:
            return TrendSignal(detected=True, direction="short",
                               strength=float(lower_strength), macd_hist=macd_hist)

        return TrendSignal(detected=False, direction="none",
                           strength=0.0, macd_hist=macd_hist)
```

- [ ] **Step 2: Verify trend.py works**

Run: `cd /Users/tonylesmb/claw-workspace/alpaca-trader && python -c "from alpaca_trader.strategies.trend import TrendDetector, TrendSignal; print('TrendDetector OK')"`
Expected: `TrendDetector OK`

- [ ] **Step 3: Commit**

```bash
cd /Users/tonylesmb/claw-workspace/alpaca-trader
git add src/alpaca_trader/strategies/trend.py
git commit -m "feat: add TrendDetector for band-walking with MACD confirmation"
```

---

## Chunk 3: Scanner and Backtester

### Task 6: Create scanner.py

**Files:**
- Create: `src/alpaca_trader/strategies/scanner.py`

- [ ] **Step 1: Create `src/alpaca_trader/strategies/scanner.py`**

```python
"""Watchlist scanner — runs a strategy across all symbols in the watchlist."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from alpaca_trader.core import client as alpaca
from alpaca_trader.core import database as db
from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.squeeze import SqueezeDetector
from alpaca_trader.strategies.bounce import BounceDetector
from alpaca_trader.strategies.trend import TrendDetector


@dataclass
class Signal:
    symbol: str
    strategy: str
    detected: bool
    direction: str
    strength: float
    details: dict
    timestamp: str


class WatchlistScanner:
    """Scans all watchlist symbols using a chosen strategy.

    Fetches historical bars from Alpaca, runs the strategy, and returns
    a list of Signal objects (one per symbol).
    """

    def scan(
        self,
        symbols: list[str],
        strategy: str,
        period: str = "1D",
        limit: int = 60,
    ) -> list[Signal]:
        """Run a strategy scan across all symbols.

        Args:
            symbols: List of ticker symbols to scan
            strategy: One of 'squeeze', 'bounce', 'trend'
            period: Bar timeframe ('1D', '1H', '15Min', '5Min', '1Min')
            limit: Number of historical bars to fetch per symbol

        Returns:
            List of Signal objects, sorted by detected=True first
        """
        results = []
        for symbol in symbols:
            signal = self._scan_symbol(symbol, strategy, period, limit)
            results.append(signal)

        # Sort: detected signals first
        results.sort(key=lambda s: (not s.detected, s.symbol))
        return results

    def _scan_symbol(
        self,
        symbol: str,
        strategy: str,
        period: str,
        limit: int,
    ) -> Signal:
        timestamp = datetime.utcnow().isoformat()
        try:
            df = alpaca.get_stock_bars_df(symbol, period=period, limit=limit)
        except EnvironmentError:
            raise
        except Exception as e:
            return Signal(
                symbol=symbol, strategy=strategy, detected=False,
                direction="none", strength=0.0,
                details={"error": str(e)}, timestamp=timestamp,
            )

        if df.empty or len(df) < 21:
            return Signal(
                symbol=symbol, strategy=strategy, detected=False,
                direction="none", strength=0.0,
                details={"error": f"Insufficient data: {len(df)} bars"},
                timestamp=timestamp,
            )

        try:
            if strategy == "squeeze":
                detector = SqueezeDetector()
                sig = detector.detect(df)
                return Signal(
                    symbol=symbol, strategy=strategy,
                    detected=sig.detected, direction=sig.direction,
                    strength=sig.strength,
                    details={
                        "width": round(sig.width, 4),
                        "candle_outside": sig.candle_outside,
                    },
                    timestamp=timestamp,
                )
            elif strategy == "bounce":
                detector = BounceDetector()
                sig = detector.detect(df)
                return Signal(
                    symbol=symbol, strategy=strategy,
                    detected=sig.detected, direction=sig.direction,
                    strength=0.5 if sig.detected else 0.0,
                    details={
                        "band_touched": sig.band_touched,
                        "rsi": round(sig.rsi, 1),
                        "adx": round(sig.adx, 1),
                    },
                    timestamp=timestamp,
                )
            elif strategy == "trend":
                detector = TrendDetector()
                sig = detector.detect(df)
                return Signal(
                    symbol=symbol, strategy=strategy,
                    detected=sig.detected, direction=sig.direction,
                    strength=sig.strength,
                    details={"macd_hist": round(sig.macd_hist, 4)},
                    timestamp=timestamp,
                )
            else:
                return Signal(
                    symbol=symbol, strategy=strategy, detected=False,
                    direction="none", strength=0.0,
                    details={"error": f"Unknown strategy: {strategy}"},
                    timestamp=timestamp,
                )
        except Exception as e:
            return Signal(
                symbol=symbol, strategy=strategy, detected=False,
                direction="none", strength=0.0,
                details={"error": str(e)}, timestamp=timestamp,
            )
```

- [ ] **Step 2: Verify scanner.py imports work**

Run: `cd /Users/tonylesmb/claw-workspace/alpaca-trader && python -c "from alpaca_trader.strategies.scanner import WatchlistScanner, Signal; print('WatchlistScanner OK')"`
Expected: `WatchlistScanner OK`

- [ ] **Step 3: Commit**

```bash
cd /Users/tonylesmb/claw-workspace/alpaca-trader
git add src/alpaca_trader/strategies/scanner.py
git commit -m "feat: add WatchlistScanner for multi-symbol strategy scans"
```

---

### Task 7: Create backtest.py

**Files:**
- Create: `src/alpaca_trader/strategies/backtest.py`

- [ ] **Step 1: Create `src/alpaca_trader/strategies/backtest.py`**

```python
"""Backtester — simulates entries/exits based on Bollinger Band strategy signals."""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from alpaca_trader.core import client as alpaca
from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.squeeze import SqueezeDetector
from alpaca_trader.strategies.bounce import BounceDetector
from alpaca_trader.strategies.trend import TrendDetector


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    direction: str      # 'long' or 'short'
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return: float     # Percentage
    win_rate: float         # 0.0–1.0
    sharpe: float
    max_drawdown: float     # Percentage (negative)
    trades: list[Trade] = field(default_factory=list)
    num_trades: int = 0


class Backtester:
    """Simulates strategy entries and exits on historical price data.

    Entry signals come from the strategy detector.
    Exit rules per strategy:
      - squeeze: exit on close back inside bands
      - bounce: exit when price crosses middle band
      - trend: exit when price crosses middle band
    """

    def run(
        self,
        symbol: str,
        strategy: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 10000.0,
        period: str = "1D",
    ) -> BacktestResult:
        """Run backtest.

        Args:
            symbol: Ticker symbol
            strategy: 'squeeze', 'bounce', or 'trend'
            start_date: ISO date string (YYYY-MM-DD)
            end_date: ISO date string (YYYY-MM-DD)
            initial_capital: Starting capital in USD
            period: Bar timeframe (default '1D')

        Returns:
            BacktestResult with trade details and summary statistics
        """
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)

        df = alpaca.get_stock_bars_df(symbol, period=period, limit=500,
                                      start=start_dt, end=end_dt)

        empty_result = BacktestResult(
            symbol=symbol, strategy=strategy,
            start_date=start_date, end_date=end_date,
            initial_capital=initial_capital,
            final_capital=initial_capital,
            total_return=0.0, win_rate=0.0,
            sharpe=0.0, max_drawdown=0.0,
            trades=[], num_trades=0,
        )

        if df.empty or len(df) < 25:
            empty_result.trades = []
            return empty_result

        # Compute signals over entire dataset using rolling window
        trades = self._simulate(df, strategy, initial_capital)

        if not trades:
            return empty_result

        # Calculate aggregate stats
        capital = initial_capital
        equity_curve = [capital]
        for t in trades:
            capital += t.pnl * (capital / t.entry_price) if t.entry_price else 0
            equity_curve.append(capital)

        # Simpler capital tracking: each trade invests full capital, compounds
        capital = initial_capital
        for t in trades:
            capital *= (1 + t.pnl_pct / 100)

        wins = [t for t in trades if t.pnl > 0]
        win_rate = len(wins) / len(trades) if trades else 0.0
        total_return = (capital - initial_capital) / initial_capital * 100

        # Sharpe ratio (annualized, assuming 252 trading days)
        returns = [t.pnl_pct / 100 for t in trades]
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = (np.mean(returns) / np.std(returns)) * math.sqrt(252)
        else:
            sharpe = 0.0

        # Max drawdown
        equity = initial_capital
        peak = initial_capital
        max_dd = 0.0
        for t in trades:
            equity *= (1 + t.pnl_pct / 100)
            peak = max(peak, equity)
            dd = (equity - peak) / peak * 100
            max_dd = min(max_dd, dd)

        return BacktestResult(
            symbol=symbol, strategy=strategy,
            start_date=start_date, end_date=end_date,
            initial_capital=initial_capital,
            final_capital=round(capital, 2),
            total_return=round(total_return, 2),
            win_rate=round(win_rate, 4),
            sharpe=round(sharpe, 3),
            max_drawdown=round(max_dd, 2),
            trades=trades,
            num_trades=len(trades),
        )

    def _simulate(self, df: pd.DataFrame, strategy: str,
                  initial_capital: float) -> list[Trade]:
        """Walk through bars, generating entry/exit signals."""
        trades = []
        in_trade = False
        entry_idx = None
        entry_price = None
        direction = "none"
        min_rows = 25

        bb = BollingerBands()

        for i in range(min_rows, len(df)):
            window = df.iloc[:i + 1]
            latest = df.iloc[i]
            close = float(latest["close"])
            ts = str(latest.name)

            if not in_trade:
                # Check for entry signal
                sig_detected, sig_direction = self._get_signal(window, strategy)
                if sig_detected and sig_direction in ("long", "short"):
                    in_trade = True
                    entry_idx = i
                    entry_price = close
                    direction = sig_direction
            else:
                # Check for exit
                should_exit = self._check_exit(window, strategy, direction)
                if should_exit or i == len(df) - 1:
                    exit_price = close
                    pnl_pct = ((exit_price - entry_price) / entry_price * 100
                               if direction == "long"
                               else (entry_price - exit_price) / entry_price * 100)
                    pnl = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)

                    trades.append(Trade(
                        entry_date=str(df.index[entry_idx]),
                        exit_date=ts,
                        direction=direction,
                        entry_price=round(entry_price, 4),
                        exit_price=round(exit_price, 4),
                        pnl=round(pnl, 4),
                        pnl_pct=round(pnl_pct, 4),
                    ))
                    in_trade = False
                    entry_idx = None
                    entry_price = None
                    direction = "none"

        return trades

    def _get_signal(self, df: pd.DataFrame, strategy: str) -> tuple[bool, str]:
        """Get entry signal from strategy detector."""
        try:
            if strategy == "squeeze":
                sig = SqueezeDetector().detect(df)
                return sig.detected and sig.candle_outside, sig.direction
            elif strategy == "bounce":
                sig = BounceDetector().detect(df)
                return sig.detected, sig.direction
            elif strategy == "trend":
                sig = TrendDetector().detect(df)
                return sig.detected, sig.direction
        except Exception:
            pass
        return False, "none"

    def _check_exit(self, df: pd.DataFrame, strategy: str, direction: str) -> bool:
        """Check exit condition based on strategy rules."""
        try:
            bb = BollingerBands()
            enriched = bb.calc(df)
            latest = enriched.iloc[-1]
            close = float(latest["close"])
            middle = float(latest["bb_middle"])
            upper = float(latest["bb_upper"])
            lower = float(latest["bb_lower"])

            if strategy == "squeeze":
                # Exit when price returns inside bands
                if direction == "long":
                    return close < upper
                else:
                    return close > lower

            elif strategy in ("bounce", "trend"):
                # Exit at middle band cross
                if direction == "long":
                    return close >= middle
                else:
                    return close <= middle
        except Exception:
            pass
        return False
```

- [ ] **Step 2: Verify backtest.py imports work**

Run: `cd /Users/tonylesmb/claw-workspace/alpaca-trader && python -c "from alpaca_trader.strategies.backtest import Backtester, BacktestResult; print('Backtester OK')"`
Expected: `Backtester OK`

- [ ] **Step 3: Commit**

```bash
cd /Users/tonylesmb/claw-workspace/alpaca-trader
git add src/alpaca_trader/strategies/backtest.py
git commit -m "feat: add Backtester with trade simulation and performance stats"
```

---

## Chunk 4: CLI Commands

### Task 8: Add scan and backtest commands to cli.py

**Files:**
- Modify: `src/alpaca_trader/cli.py`

- [ ] **Step 1: Add scan command to cli.py**

Add these imports to the top of cli.py (after existing imports):
```python
import asyncio  # already imported
from alpaca_trader.strategies.scanner import WatchlistScanner
from alpaca_trader.strategies.backtest import Backtester
```

Add the scan command before the `serve` command:
```python
# --- scan command ---

@app.command()
def scan(
    strategy: str = typer.Option("squeeze", "--strategy", help="Strategy: squeeze, bounce, trend"),
    period: str = typer.Option("1D", "--period", help="Bar timeframe: 1D, 1H, 15Min, 5Min, 1Min"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Scan watchlist symbols with a Bollinger Band strategy."""
    valid_strategies = ("squeeze", "bounce", "trend")
    if strategy not in valid_strategies:
        console.print(f"[red]Invalid strategy.[/red] Choose from: {', '.join(valid_strategies)}")
        raise typer.Exit(1)

    asyncio.run(db.init_db())
    watchlist_items = asyncio.run(db.watchlist_list())
    symbols = [item["symbol"] for item in watchlist_items]

    if not symbols:
        msg = {"error": "Watchlist is empty. Add symbols with: alpaca-trader watchlist add TICKER"}
        if json_output:
            _print_json(msg)
        else:
            console.print("[yellow]Watchlist is empty.[/yellow] Add symbols with: alpaca-trader watchlist add TICKER")
        raise typer.Exit(0)

    try:
        scanner = WatchlistScanner()
        signals = scanner.scan(symbols, strategy=strategy, period=period)
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Scan error:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        _print_json([
            {
                "symbol": s.symbol,
                "strategy": s.strategy,
                "detected": s.detected,
                "direction": s.direction,
                "strength": s.strength,
                "details": s.details,
                "timestamp": s.timestamp,
            }
            for s in signals
        ])
        return

    table = Table(title=f"Bollinger Scan: {strategy.upper()} ({len(signals)} symbols, {period})")
    table.add_column("Symbol", style="bold cyan")
    table.add_column("Signal")
    table.add_column("Direction")
    table.add_column("Strength", justify="right")
    table.add_column("Details")

    for s in signals:
        detected_str = "[green]YES[/green]" if s.detected else "[dim]no[/dim]"
        direction_str = (
            f"[green]{s.direction}[/green]" if s.direction == "long"
            else f"[red]{s.direction}[/red]" if s.direction == "short"
            else f"[dim]{s.direction}[/dim]"
        )
        strength_str = f"{s.strength:.2f}" if s.detected else "—"
        detail_str = ", ".join(f"{k}={v}" for k, v in s.details.items()) if s.details else "—"

        table.add_row(s.symbol, detected_str, direction_str, strength_str, detail_str)

    console.print(table)
```

- [ ] **Step 2: Add backtest command to cli.py**

Add the backtest command (after the scan command, before `serve`):
```python
# --- backtest command ---

@app.command()
def backtest(
    ticker: str = typer.Argument(..., help="Ticker symbol to backtest"),
    strategy: str = typer.Option(..., "--strategy", help="Strategy: squeeze, bounce, trend"),
    start: str = typer.Option(..., "--start", help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option(..., "--end", help="End date (YYYY-MM-DD)"),
    capital: float = typer.Option(10000.0, "--capital", help="Initial capital (default $10,000)"),
    period: str = typer.Option("1D", "--period", help="Bar timeframe: 1D, 1H, 15Min"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Run a Bollinger Band strategy backtest on a ticker."""
    valid_strategies = ("squeeze", "bounce", "trend")
    if strategy not in valid_strategies:
        console.print(f"[red]Invalid strategy.[/red] Choose from: {', '.join(valid_strategies)}")
        raise typer.Exit(1)

    # Validate dates
    try:
        datetime.fromisoformat(start)
        datetime.fromisoformat(end)
    except ValueError as e:
        console.print(f"[red]Invalid date:[/red] {e}")
        raise typer.Exit(1)

    try:
        bt = Backtester()
        result = bt.run(
            symbol=ticker.upper(),
            strategy=strategy,
            start_date=start,
            end_date=end,
            initial_capital=capital,
            period=period,
        )
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Backtest error:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        import dataclasses
        _print_json(dataclasses.asdict(result))
        return

    # Human-readable output
    console.print(Panel(
        f"[bold]{ticker.upper()}[/bold] — {strategy.upper()} strategy\n"
        f"{start} → {end}  |  {result.num_trades} trades",
        title="Backtest Result",
    ))

    summary = Table(show_header=False, box=None)
    summary.add_column("Metric", style="dim", width=22)
    summary.add_column("Value")

    summary.add_row("Initial Capital", f"${result.initial_capital:,.2f}")
    summary.add_row("Final Capital", f"${result.final_capital:,.2f}")
    rtn_color = "green" if result.total_return >= 0 else "red"
    summary.add_row("Total Return", f"[{rtn_color}]{result.total_return:+.2f}%[/{rtn_color}]")
    summary.add_row("Win Rate", f"{result.win_rate*100:.1f}%")
    summary.add_row("Sharpe Ratio", f"{result.sharpe:.3f}")
    dd_color = "red" if result.max_drawdown < -5 else "yellow" if result.max_drawdown < 0 else "green"
    summary.add_row("Max Drawdown", f"[{dd_color}]{result.max_drawdown:.2f}%[/{dd_color}]")
    console.print(summary)

    if result.trades:
        console.print(f"\n[dim]Last 5 trades:[/dim]")
        trade_table = Table()
        trade_table.add_column("Entry Date", style="dim")
        trade_table.add_column("Exit Date", style="dim")
        trade_table.add_column("Dir")
        trade_table.add_column("Entry", justify="right")
        trade_table.add_column("Exit", justify="right")
        trade_table.add_column("P&L %", justify="right")

        for t in result.trades[-5:]:
            pnl_color = "green" if t.pnl_pct >= 0 else "red"
            trade_table.add_row(
                t.entry_date[:10],
                t.exit_date[:10],
                f"[green]{t.direction}[/green]" if t.direction == "long" else f"[red]{t.direction}[/red]",
                f"${t.entry_price:.2f}",
                f"${t.exit_price:.2f}",
                f"[{pnl_color}]{t.pnl_pct:+.2f}%[/{pnl_color}]",
            )
        console.print(trade_table)
```

- [ ] **Step 3: Test CLI help commands work**

Run: `cd /Users/tonylesmb/claw-workspace/alpaca-trader && alpaca-trader scan --help`
Expected: Shows scan command help with --strategy, --period, --json options

Run: `cd /Users/tonylesmb/claw-workspace/alpaca-trader && alpaca-trader backtest --help`
Expected: Shows backtest command help with TICKER argument and all options

- [ ] **Step 4: Commit**

```bash
cd /Users/tonylesmb/claw-workspace/alpaca-trader
git add src/alpaca_trader/cli.py
git commit -m "feat: add scan and backtest CLI commands"
```

---

## Chunk 5: Final Integration

### Task 9: Verify full import chain and run completion event

- [ ] **Step 1: Verify full strategies package imports**

Run: `cd /Users/tonylesmb/claw-workspace/alpaca-trader && python -c "from alpaca_trader.strategies import BollingerBands, SqueezeDetector, BounceDetector, TrendDetector, WatchlistScanner, Backtester; print('All strategies imported OK')"`
Expected: `All strategies imported OK`

- [ ] **Step 2: Verify CLI commands are registered**

Run: `cd /Users/tonylesmb/claw-workspace/alpaca-trader && alpaca-trader --help`
Expected: Shows both `scan` and `backtest` in the command list

- [ ] **Step 3: Run completion event**

Run: `openclaw system event --text "Done: alpaca-trader Sprint 2 complete — Bollinger Band strategy engine built" --mode now`

---

*Plan saved: 2026-03-16*
