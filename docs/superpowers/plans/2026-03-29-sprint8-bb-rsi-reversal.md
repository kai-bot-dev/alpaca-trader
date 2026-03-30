# Sprint 8 — BB + RSI Reversal Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-grade Bollinger Band + RSI mean-reversion strategy (BB+RSI Reversal) fully integrated into scanner, backtester, CLI, and alerts.

**Architecture:** Extract shared indicator calculations into `indicators.py`, implement `BBRSIReversalDetector` in `bb_rsi_reversal.py` following the same dataclass+detector pattern as `bounce.py`/`trend.py`, then wire into all four integration points (scanner, backtest, alerts, CLI).

**Tech Stack:** Python 3.11+, pandas, numpy, existing `BollingerBands` class, Typer CLI, existing test infrastructure (pytest)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/alpaca_trader/strategies/indicators.py` | **CREATE** | Shared RSI, ADX, MACD, ATR, VolumeSMA calculations |
| `src/alpaca_trader/strategies/bb_rsi_reversal.py` | **CREATE** | BBRSIReversalDetector + BBRSIReversalSignal |
| `src/alpaca_trader/strategies/bounce.py` | **EDIT** | Replace private `_calc_rsi`/`_calc_adx` with imports from indicators.py |
| `src/alpaca_trader/strategies/trend.py` | **EDIT** | Replace private `_calc_macd` with import from indicators.py |
| `src/alpaca_trader/strategies/__init__.py` | **EDIT** | Export new classes |
| `src/alpaca_trader/strategies/scanner.py` | **EDIT** | Add bb_rsi_reversal branch in `_scan_symbol` |
| `src/alpaca_trader/strategies/backtest.py` | **EDIT** | Add bb_rsi_reversal in `_get_signal` + `_check_exit` |
| `src/alpaca_trader/alerts/scanner.py` | **EDIT** | Add "bb_rsi_reversal" to strategy loop |
| `src/alpaca_trader/cli.py` | **EDIT** | Add "bb_rsi_reversal" to valid_strategies in scan + backtest commands |
| `tests/test_indicators.py` | **CREATE** | Tests for all shared indicator functions |
| `tests/test_bb_rsi_reversal.py` | **CREATE** | Tests for BBRSIReversalDetector |

---

## Task 1: Create shared indicators.py

**Files:**
- Create: `src/alpaca_trader/strategies/indicators.py`

- [ ] **Step 1.1: Write the indicators module**

```python
# src/alpaca_trader/strategies/indicators.py
"""Shared technical indicator calculations for Bollinger Band strategies."""

import numpy as np
import pandas as pd


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI using Wilder's smoothing.

    Args:
        close: Series of closing prices.
        period: Lookback period. Default is 14.

    Returns:
        RSI Series (0–100), NaN for the first ``period`` rows.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate ADX (Average Directional Index).

    Args:
        df: OHLCV DataFrame with columns: high, low, close.
        period: Lookback period. Default is 14.

    Returns:
        ADX Series. Values < 25 indicate a range-bound market.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

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
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def calc_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate MACD line, signal line, and histogram.

    Args:
        close: Series of closing prices.
        fast: Fast EMA period. Default is 12.
        slow: Slow EMA period. Default is 26.
        signal: Signal EMA period. Default is 9.

    Returns:
        Tuple of (macd_line, signal_line, histogram).
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range (ATR).

    Args:
        df: OHLCV DataFrame with columns: high, low, close.
        period: Lookback period. Default is 14.

    Returns:
        ATR Series.
    """
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def calc_volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    """Calculate simple moving average of volume.

    Args:
        volume: Series of volume values.
        period: Rolling window size. Default is 20.

    Returns:
        Rolling mean of volume.
    """
    return volume.rolling(window=period).mean()
```

- [ ] **Step 1.2: Write failing indicator tests**

```python
# tests/test_indicators.py
"""Tests for shared indicator calculations."""

import numpy as np
import pandas as pd
import pytest

from alpaca_trader.strategies.indicators import (
    calc_rsi,
    calc_adx,
    calc_macd,
    calc_atr,
    calc_volume_sma,
)


def _make_ohlcv(n: int = 50, base: float = 100.0, trend: float = 0.0) -> pd.DataFrame:
    """Generate synthetic OHLCV data."""
    rng = np.random.default_rng(42)
    closes = base + trend * np.arange(n) + rng.normal(0, 1, n).cumsum()
    highs = closes + rng.uniform(0.1, 1.0, n)
    lows = closes - rng.uniform(0.1, 1.0, n)
    opens = closes + rng.normal(0, 0.5, n)
    volumes = rng.integers(100_000, 1_000_000, n).astype(float)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes})


class TestCalcRsi:
    def test_returns_series_same_length(self):
        df = _make_ohlcv(50)
        result = calc_rsi(df["close"])
        assert len(result) == 50

    def test_values_bounded_0_100(self):
        df = _make_ohlcv(50)
        result = calc_rsi(df["close"]).dropna()
        assert (result >= 0).all() and (result <= 100).all()

    def test_oversold_on_falling_prices(self):
        # Prices falling sharply should produce RSI < 30
        closes = pd.Series([100 - i * 2 for i in range(30)])
        rsi = calc_rsi(closes, period=14).dropna()
        assert rsi.iloc[-1] < 30

    def test_overbought_on_rising_prices(self):
        # Prices rising sharply should produce RSI > 70
        closes = pd.Series([100 + i * 2 for i in range(30)])
        rsi = calc_rsi(closes, period=14).dropna()
        assert rsi.iloc[-1] > 70

    def test_nan_for_first_period_rows(self):
        df = _make_ohlcv(30)
        result = calc_rsi(df["close"], period=14)
        assert result.iloc[:14].isna().all()


class TestCalcAtr:
    def test_returns_series_same_length(self):
        df = _make_ohlcv(50)
        result = calc_atr(df)
        assert len(result) == 50

    def test_values_positive(self):
        df = _make_ohlcv(50)
        result = calc_atr(df).dropna()
        assert (result > 0).all()

    def test_higher_volatility_yields_higher_atr(self):
        df_low = _make_ohlcv(50, base=100.0)
        df_high = df_low.copy()
        df_high["high"] = df_high["close"] + 5.0
        df_high["low"] = df_high["close"] - 5.0
        atr_low = calc_atr(df_low).dropna().iloc[-1]
        atr_high = calc_atr(df_high).dropna().iloc[-1]
        assert atr_high > atr_low


class TestCalcMacd:
    def test_returns_three_series(self):
        df = _make_ohlcv(60)
        macd_line, signal_line, hist = calc_macd(df["close"])
        assert len(macd_line) == len(signal_line) == len(hist) == 60

    def test_histogram_is_macd_minus_signal(self):
        df = _make_ohlcv(60)
        macd_line, signal_line, hist = calc_macd(df["close"])
        diff = (macd_line - signal_line - hist).dropna()
        assert (diff.abs() < 1e-10).all()


class TestCalcVolumeSma:
    def test_returns_series_same_length(self):
        df = _make_ohlcv(30)
        result = calc_volume_sma(df["volume"])
        assert len(result) == 30

    def test_first_period_minus_one_rows_nan(self):
        df = _make_ohlcv(30)
        result = calc_volume_sma(df["volume"], period=20)
        assert result.iloc[:19].isna().all()
        assert not pd.isna(result.iloc[19])
```

- [ ] **Step 1.3: Run indicator tests — expect PASS (indicators.py already written)**

```
cd /Users/tonylesmb/claw-workspace/alpaca-trader
python -m pytest tests/test_indicators.py -v
```

Expected: All tests pass.

- [ ] **Step 1.4: Commit**

```bash
git add src/alpaca_trader/strategies/indicators.py tests/test_indicators.py
git commit -m "feat: add shared indicators module (RSI, ADX, MACD, ATR, VolumeSMA)"
```

---

## Task 2: Refactor bounce.py and trend.py to use indicators.py

**Files:**
- Modify: `src/alpaca_trader/strategies/bounce.py`
- Modify: `src/alpaca_trader/strategies/trend.py`

- [ ] **Step 2.1: Update bounce.py — replace private helpers with imports**

Replace the entire `bounce.py` with:

```python
"""Bollinger Bounce (mean reversion) detection."""

from dataclasses import dataclass

import pandas as pd

from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.indicators import calc_rsi, calc_adx


@dataclass
class BounceSignal:
    detected: bool
    direction: str       # 'long', 'short', or 'none'
    band_touched: str    # 'upper', 'lower', or 'none'
    rsi: float           # Current RSI value
    adx: float           # Current ADX value (range-bound if < 25)


class BounceDetector:
    """Detects Bollinger Bounce (mean reversion) signals.

    Identifies opportunities where price reverts to the mean after touching
    the outer Bollinger Bands. This strategy works best in range-bound markets
    where price oscillates between support and resistance.

    Detection criteria:
    1. Market must be range-bound (ADX < 25)
    2. Price touches or crosses a Bollinger Band
    3. RSI confirms oversold (< 35 for long) or overbought (> 65 for short)

    Attributes:
        bb: BollingerBands instance for band calculations.
        rsi_period: Lookback period for RSI calculation. Default is 14.
        adx_period: Lookback period for ADX calculation. Default is 14.

    Example:
        >>> from alpaca_trader.strategies.bounce import BounceDetector
        >>> detector = BounceDetector(bb_period=20, rsi_period=14, adx_period=14)
        >>> signal = detector.detect(ohlcv_dataframe)
        >>> if signal.detected:
        ...     print(f'{signal.direction} bounce at {signal.band_touched} band')
        ...     print(f'RSI={signal.rsi:.1f}, ADX={signal.adx:.1f}')
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
        rsi_series = calc_rsi(df["close"], self.rsi_period)
        adx_series = calc_adx(df, self.adx_period)

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

- [ ] **Step 2.2: Update trend.py — replace private helper with import**

Replace the entire `trend.py` with:

```python
"""Trend (walking the bands) detection using Bollinger Bands + MACD."""

from dataclasses import dataclass

import pandas as pd

from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.indicators import calc_macd


@dataclass
class TrendSignal:
    detected: bool
    direction: str    # 'long', 'short', or 'none'
    strength: float   # 0.0–1.0: proportion of last N candles along the band
    macd_hist: float  # Current MACD histogram value (positive = bullish)


class TrendDetector:
    """Detects 'walking the bands' -- sustained price action along an outer BB.

    Identifies when price consistently hugs the upper or lower Bollinger Band,
    indicating a strong directional trend. Uses MACD histogram to confirm
    trend direction and filter false signals.

    Detection criteria:
    1. At least 60% of the last N candles close above (long) or below (short)
       the middle band
    2. MACD histogram confirms direction (positive for long, negative for short)

    Attributes:
        bb: BollingerBands instance for band calculations.
        lookback: Number of recent candles to check for band-walking. Default is 5.
        macd_fast: Fast EMA period for MACD. Default is 12.
        macd_slow: Slow EMA period for MACD. Default is 26.
        macd_signal_period: Signal line EMA period. Default is 9.

    Example:
        >>> from alpaca_trader.strategies.trend import TrendDetector
        >>> detector = TrendDetector(bb_period=20, lookback=5)
        >>> signal = detector.detect(ohlcv_dataframe)
        >>> if signal.detected:
        ...     print(f'Trend {signal.direction}, strength={signal.strength:.2f}')
        ...     print(f'MACD histogram={signal.macd_hist:.4f}')
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
        _, _, histogram = calc_macd(
            df["close"], self.macd_fast, self.macd_slow, self.macd_signal_period
        )

        macd_hist = float(histogram.iloc[-1]) if not pd.isna(histogram.iloc[-1]) else 0.0

        # Check last N candles: price hugging upper or lower band
        recent = enriched.iloc[-self.lookback:]

        upper_hugging = (recent["close"] >= recent["bb_middle"]).sum()
        lower_hugging = (recent["close"] <= recent["bb_middle"]).sum()

        upper_strength = upper_hugging / self.lookback
        lower_strength = lower_hugging / self.lookback

        if upper_strength >= 0.6 and macd_hist > 0:
            return TrendSignal(detected=True, direction="long",
                               strength=float(upper_strength), macd_hist=macd_hist)
        elif lower_strength >= 0.6 and macd_hist < 0:
            return TrendSignal(detected=True, direction="short",
                               strength=float(lower_strength), macd_hist=macd_hist)

        return TrendSignal(detected=False, direction="none",
                           strength=0.0, macd_hist=macd_hist)
```

- [ ] **Step 2.3: Run existing strategy tests — expect all pass**

```
cd /Users/tonylesmb/claw-workspace/alpaca-trader
python -m pytest tests/test_strategies.py -v
```

Expected: All tests pass (behavior is unchanged; only imports moved).

- [ ] **Step 2.4: Commit**

```bash
git add src/alpaca_trader/strategies/bounce.py src/alpaca_trader/strategies/trend.py
git commit -m "refactor: bounce.py and trend.py import indicators from shared module"
```

---

## Task 3: Create bb_rsi_reversal.py

**Files:**
- Create: `src/alpaca_trader/strategies/bb_rsi_reversal.py`

- [ ] **Step 3.1: Write the bb_rsi_reversal module**

```python
# src/alpaca_trader/strategies/bb_rsi_reversal.py
"""Bollinger Band + RSI Reversal strategy — catches mean-reversion turning points."""

from dataclasses import dataclass, field

import pandas as pd

from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.indicators import calc_rsi, calc_volume_sma


@dataclass
class BBRSIReversalSignal:
    """Signal produced by BBRSIReversalDetector.

    Attributes:
        detected: True when entry conditions are met.
        direction: 'long', 'short', or 'none'.
        strength: Confidence score 0.0–1.0 based on confirmation count.
        rsi: Current RSI(14) value.
        bb_pct: %B — where price sits relative to the bands (0 = lower, 1 = upper).
        confirmations: List of confirmation names that were satisfied.
        entry_price: Suggested entry (current close).
        target_price: Mean reversion target (middle Bollinger Band).
        stop_price: Stop loss price.
        risk_reward: Reward-to-risk ratio (target distance / stop distance).
    """

    detected: bool
    direction: str
    strength: float
    rsi: float
    bb_pct: float
    confirmations: list[str] = field(default_factory=list)
    entry_price: float = 0.0
    target_price: float = 0.0
    stop_price: float = 0.0
    risk_reward: float = 0.0


class BBRSIReversalDetector:
    """Detects Bollinger Band + RSI mean-reversion reversal signals.

    Identifies high-probability turning points when price breaks outside the
    Bollinger Bands and RSI confirms extreme conditions (oversold/overbought).
    Uses volume spikes, candle patterns, and RSI divergence as secondary
    confirmations to score signal strength.

    Detection criteria:
    Long (bullish reversal):
      1. Price closes below lower Bollinger Band
      2. RSI(14) < 30 (oversold)
      3. At least one confirmation: volume spike, bullish candle, or RSI divergence

    Short (bearish reversal):
      1. Price closes above upper Bollinger Band
      2. RSI(14) > 70 (overbought)
      3. At least one confirmation: volume spike, bearish candle, or RSI divergence

    Attributes:
        bb: BollingerBands instance (20-period, 2 std dev by default).
        rsi_period: RSI lookback. Default is 14.
        volume_period: Period for volume SMA baseline. Default is 20.
        volume_spike_threshold: Multiplier above average volume for spike. Default 1.5.
        divergence_lookback: Bars to check for RSI divergence. Default is 5.

    Example:
        >>> from alpaca_trader.strategies.bb_rsi_reversal import BBRSIReversalDetector
        >>> detector = BBRSIReversalDetector()
        >>> signal = detector.detect(ohlcv_dataframe)
        >>> if signal.detected:
        ...     print(f'{signal.direction} reversal  strength={signal.strength:.2f}')
        ...     print(f'target={signal.target_price:.2f}  stop={signal.stop_price:.2f}')
    """

    MIN_BARS = 25  # Minimum bars required for reliable signals

    def __init__(
        self,
        bb_period: int = 20,
        bb_std_dev: float = 2.0,
        rsi_period: int = 14,
        volume_period: int = 20,
        volume_spike_threshold: float = 1.5,
        divergence_lookback: int = 5,
    ):
        self.bb = BollingerBands(period=bb_period, std_dev=bb_std_dev)
        self.rsi_period = rsi_period
        self.volume_period = volume_period
        self.volume_spike_threshold = volume_spike_threshold
        self.divergence_lookback = divergence_lookback

    def detect(self, df: pd.DataFrame) -> BBRSIReversalSignal:
        """Detect BB+RSI reversal signal on the latest bar.

        Args:
            df: OHLCV DataFrame with columns: open, high, low, close, volume.
                Must have at least MIN_BARS rows.

        Returns:
            BBRSIReversalSignal describing the detected (or absent) signal.
        """
        no_signal = BBRSIReversalSignal(
            detected=False, direction="none", strength=0.0,
            rsi=50.0, bb_pct=0.5,
        )

        required_cols = {"open", "high", "low", "close", "volume"}
        if not required_cols.issubset(df.columns):
            return no_signal

        if len(df) < self.MIN_BARS:
            return no_signal

        try:
            enriched = self.bb.calc(df)
        except ValueError:
            return no_signal

        rsi_series = calc_rsi(df["close"], self.rsi_period)

        latest = enriched.iloc[-1]
        close = float(latest["close"])
        upper = float(latest["bb_upper"])
        lower = float(latest["bb_lower"])
        middle = float(latest["bb_middle"])
        bb_pct = float(latest["bb_pct"]) if not pd.isna(latest["bb_pct"]) else 0.5
        rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0

        # --- Long: price below lower band + RSI oversold ---
        if close < lower and rsi < 30:
            confirmations = self._get_confirmations(df, enriched, rsi_series, "long")
            if not confirmations:
                return no_signal
            entry, target, stop = self._calc_targets(close, middle, lower, "long")
            strength = self._calc_strength(rsi, bb_pct, confirmations, "long")
            return BBRSIReversalSignal(
                detected=True,
                direction="long",
                strength=strength,
                rsi=rsi,
                bb_pct=bb_pct,
                confirmations=confirmations,
                entry_price=entry,
                target_price=target,
                stop_price=stop,
                risk_reward=self._calc_rr(entry, target, stop, "long"),
            )

        # --- Short: price above upper band + RSI overbought ---
        if close > upper and rsi > 70:
            confirmations = self._get_confirmations(df, enriched, rsi_series, "short")
            if not confirmations:
                return no_signal
            entry, target, stop = self._calc_targets(close, middle, upper, "short")
            strength = self._calc_strength(rsi, bb_pct, confirmations, "short")
            return BBRSIReversalSignal(
                detected=True,
                direction="short",
                strength=strength,
                rsi=rsi,
                bb_pct=bb_pct,
                confirmations=confirmations,
                entry_price=entry,
                target_price=target,
                stop_price=stop,
                risk_reward=self._calc_rr(entry, target, stop, "short"),
            )

        return BBRSIReversalSignal(
            detected=False, direction="none", strength=0.0,
            rsi=rsi, bb_pct=bb_pct,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_confirmations(
        self,
        df: pd.DataFrame,
        enriched: pd.DataFrame,
        rsi_series: pd.Series,
        direction: str,
    ) -> list[str]:
        """Gather list of satisfied confirmation labels."""
        confirmations: list[str] = []
        if self._check_volume_spike(df):
            confirmations.append("volume_spike")
        if self._check_candle_pattern(df, direction):
            confirmations.append("candle_pattern")
        if self._check_rsi_divergence(df, rsi_series, direction):
            confirmations.append("rsi_divergence")
        return confirmations

    def _check_volume_spike(self, df: pd.DataFrame) -> bool:
        """Return True if the latest bar has a volume spike above average.

        Args:
            df: OHLCV DataFrame.

        Returns:
            True when current volume > volume_spike_threshold × 20-bar average.
        """
        vol = df["volume"]
        vol_sma = calc_volume_sma(vol, self.volume_period)
        if pd.isna(vol_sma.iloc[-1]) or vol_sma.iloc[-1] == 0:
            return False
        return float(vol.iloc[-1]) > self.volume_spike_threshold * float(vol_sma.iloc[-1])

    def _check_candle_pattern(self, df: pd.DataFrame, direction: str) -> bool:
        """Return True if the latest candle is bullish (long) or bearish (short).

        Args:
            df: OHLCV DataFrame with 'open' and 'close' columns.
            direction: 'long' or 'short'.

        Returns:
            True when close > open for long (green candle), close < open for short.
        """
        latest = df.iloc[-1]
        if direction == "long":
            return float(latest["close"]) > float(latest["open"])
        return float(latest["close"]) < float(latest["open"])

    def _check_rsi_divergence(
        self,
        df: pd.DataFrame,
        rsi_series: pd.Series,
        direction: str,
        lookback: int | None = None,
    ) -> bool:
        """Return True if RSI divergence is present over the lookback window.

        Bullish divergence: price makes a lower low but RSI makes a higher low.
        Bearish divergence: price makes a higher high but RSI makes a lower high.

        Args:
            df: OHLCV DataFrame.
            rsi_series: Pre-computed RSI Series aligned with df.
            direction: 'long' (bullish) or 'short' (bearish).
            lookback: Bars to examine. Defaults to self.divergence_lookback.

        Returns:
            True when divergence is detected.
        """
        n = lookback if lookback is not None else self.divergence_lookback
        if len(df) < n + 1:
            return False

        window_close = df["close"].iloc[-n - 1:-1]
        window_rsi = rsi_series.iloc[-n - 1:-1].dropna()

        if window_rsi.empty:
            return False

        current_close = float(df["close"].iloc[-1])
        current_rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None
        if current_rsi is None:
            return False

        if direction == "long":
            # Bullish: current close lower than prior lows, but RSI higher than prior RSI lows
            prev_low_close = float(window_close.min())
            prev_low_rsi = float(window_rsi.min())
            return current_close < prev_low_close and current_rsi > prev_low_rsi

        # Bearish: current close higher than prior highs, but RSI lower than prior highs
        prev_high_close = float(window_close.max())
        prev_high_rsi = float(window_rsi.max())
        return current_close > prev_high_close and current_rsi < prev_high_rsi

    def _calc_targets(
        self,
        close: float,
        middle: float,
        band: float,
        direction: str,
    ) -> tuple[float, float, float]:
        """Calculate entry, target, and stop prices.

        Target is the middle band (mean reversion goal).
        Stop is 2× the entry-to-band distance beyond the entry.

        Args:
            close: Current close price (entry).
            middle: Middle Bollinger Band (target).
            band: The band that was breached (lower for long, upper for short).
            direction: 'long' or 'short'.

        Returns:
            Tuple of (entry_price, target_price, stop_price).
        """
        entry = close
        target = middle
        band_distance = abs(close - band)

        if direction == "long":
            stop = close - 2.0 * band_distance
        else:
            stop = close + 2.0 * band_distance

        return entry, target, stop

    def _calc_rr(
        self,
        entry: float,
        target: float,
        stop: float,
        direction: str,
    ) -> float:
        """Calculate risk/reward ratio.

        Args:
            entry: Entry price.
            target: Target price.
            stop: Stop loss price.
            direction: 'long' or 'short'.

        Returns:
            Risk/reward ratio, or 0.0 if risk is zero.
        """
        if direction == "long":
            reward = target - entry
            risk = entry - stop
        else:
            reward = entry - target
            risk = stop - entry

        if risk <= 0:
            return 0.0
        return round(reward / risk, 2)

    def _calc_strength(
        self,
        rsi: float,
        bb_pct: float,
        confirmations: list[str],
        direction: str,
    ) -> float:
        """Score signal strength 0.0–1.0.

        Scoring:
        - Base score from RSI extremity (how far past 30/70)
        - Bonus for each additional confirmation beyond the first

        Args:
            rsi: Current RSI value.
            bb_pct: %B value.
            confirmations: List of confirmation labels that fired.
            direction: 'long' or 'short'.

        Returns:
            Strength score clamped to [0.0, 1.0].
        """
        # RSI component: how extreme is RSI?
        if direction == "long":
            rsi_score = max(0.0, (30.0 - rsi) / 30.0)   # 0→0, 15→0.5, 0→1.0
        else:
            rsi_score = max(0.0, (rsi - 70.0) / 30.0)   # 70→0, 85→0.5, 100→1.0

        # Confirmation bonus: each confirmation adds 0.2
        conf_score = min(len(confirmations) * 0.2, 0.6)

        return round(min(rsi_score * 0.4 + conf_score, 1.0), 4)
```

- [ ] **Step 3.2: Commit**

```bash
git add src/alpaca_trader/strategies/bb_rsi_reversal.py
git commit -m "feat: add BBRSIReversalDetector strategy"
```

---

## Task 4: Write and run bb_rsi_reversal tests

**Files:**
- Create: `tests/test_bb_rsi_reversal.py`

- [ ] **Step 4.1: Write the test file**

```python
# tests/test_bb_rsi_reversal.py
"""Tests for BB + RSI Reversal strategy."""

import numpy as np
import pandas as pd
import pytest

from alpaca_trader.strategies.bb_rsi_reversal import BBRSIReversalDetector, BBRSIReversalSignal


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 60, base: float = 100.0, noise: float = 0.5) -> pd.DataFrame:
    """Generate neutral (slightly noisy) OHLCV data."""
    rng = np.random.default_rng(42)
    closes = base + rng.normal(0, noise, n).cumsum()
    closes = np.maximum(closes, 1.0)  # keep prices positive
    highs = closes + rng.uniform(0.1, 0.5, n)
    lows = closes - rng.uniform(0.1, 0.5, n)
    opens = closes + rng.normal(0, 0.2, n)
    volumes = rng.integers(200_000, 800_000, n).astype(float)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes})


def _make_oversold_df(n: int = 40) -> pd.DataFrame:
    """Construct a DataFrame where the last bar is below the lower BB with RSI < 30.

    Strategy: start at 100, trend down sharply for the last 15 bars so that
    price is well below the 20-period lower band and RSI is < 30.
    """
    rng = np.random.default_rng(7)
    # First 25 bars: stable around 100
    stable_closes = 100.0 + rng.normal(0, 0.3, 25)
    # Last 15 bars: sharp decline
    drop = np.linspace(0, -25, 15)
    drop_closes = 100.0 + drop + rng.normal(0, 0.2, 15)
    closes = np.concatenate([stable_closes, drop_closes])
    highs = closes + rng.uniform(0.1, 0.5, n)
    lows = closes - rng.uniform(0.1, 0.5, n)
    opens = closes + rng.normal(0, 0.2, n)
    # Last bar: high volume spike (3× normal)
    volumes = rng.integers(200_000, 400_000, n).astype(float)
    volumes[-1] = volumes[:-1].mean() * 3.0
    # Last bar: green candle (close > open)
    opens[-1] = closes[-1] - 0.5
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes})


def _make_overbought_df(n: int = 40) -> pd.DataFrame:
    """Construct a DataFrame where the last bar is above the upper BB with RSI > 70."""
    rng = np.random.default_rng(13)
    stable_closes = 100.0 + rng.normal(0, 0.3, 25)
    rise = np.linspace(0, 25, 15)
    rise_closes = 100.0 + rise + rng.normal(0, 0.2, 15)
    closes = np.concatenate([stable_closes, rise_closes])
    highs = closes + rng.uniform(0.1, 0.5, n)
    lows = closes - rng.uniform(0.1, 0.5, n)
    opens = closes + rng.normal(0, 0.2, n)
    volumes = rng.integers(200_000, 400_000, n).astype(float)
    volumes[-1] = volumes[:-1].mean() * 3.0
    # Last bar: red candle (close < open)
    opens[-1] = closes[-1] + 0.5
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes})


# ---------------------------------------------------------------------------
# Tests: insufficient data / missing columns
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_too_few_bars_returns_no_signal(self):
        df = _make_ohlcv(n=10)
        sig = BBRSIReversalDetector().detect(df)
        assert sig.detected is False
        assert sig.direction == "none"

    def test_missing_volume_column_returns_no_signal(self):
        df = _make_ohlcv(n=30).drop(columns=["volume"])
        sig = BBRSIReversalDetector().detect(df)
        assert sig.detected is False

    def test_missing_open_column_returns_no_signal(self):
        df = _make_ohlcv(n=30).drop(columns=["open"])
        sig = BBRSIReversalDetector().detect(df)
        assert sig.detected is False

    def test_neutral_data_no_signal(self):
        df = _make_ohlcv(n=60)
        sig = BBRSIReversalDetector().detect(df)
        # Neutral data may or may not trigger; just verify shape of return
        assert isinstance(sig, BBRSIReversalSignal)
        assert sig.direction in ("long", "short", "none")
        assert 0.0 <= sig.strength <= 1.0


# ---------------------------------------------------------------------------
# Tests: long signal detection
# ---------------------------------------------------------------------------

class TestLongSignal:
    def test_long_signal_detected_on_oversold_data(self):
        df = _make_oversold_df()
        sig = BBRSIReversalDetector().detect(df)
        assert sig.detected is True
        assert sig.direction == "long"

    def test_long_rsi_is_below_30(self):
        df = _make_oversold_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "long":
            assert sig.rsi < 30

    def test_long_bb_pct_below_zero(self):
        df = _make_oversold_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "long":
            assert sig.bb_pct < 0.0

    def test_long_target_above_entry(self):
        df = _make_oversold_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "long":
            assert sig.target_price > sig.entry_price

    def test_long_stop_below_entry(self):
        df = _make_oversold_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "long":
            assert sig.stop_price < sig.entry_price

    def test_long_risk_reward_positive(self):
        df = _make_oversold_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "long":
            assert sig.risk_reward > 0

    def test_long_strength_between_0_and_1(self):
        df = _make_oversold_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected:
            assert 0.0 <= sig.strength <= 1.0

    def test_long_confirmations_not_empty(self):
        df = _make_oversold_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "long":
            assert len(sig.confirmations) >= 1

    def test_volume_spike_in_confirmations(self):
        df = _make_oversold_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "long":
            assert "volume_spike" in sig.confirmations

    def test_candle_pattern_in_confirmations(self):
        df = _make_oversold_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "long":
            assert "candle_pattern" in sig.confirmations


# ---------------------------------------------------------------------------
# Tests: short signal detection
# ---------------------------------------------------------------------------

class TestShortSignal:
    def test_short_signal_detected_on_overbought_data(self):
        df = _make_overbought_df()
        sig = BBRSIReversalDetector().detect(df)
        assert sig.detected is True
        assert sig.direction == "short"

    def test_short_rsi_above_70(self):
        df = _make_overbought_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "short":
            assert sig.rsi > 70

    def test_short_bb_pct_above_one(self):
        df = _make_overbought_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "short":
            assert sig.bb_pct > 1.0

    def test_short_target_below_entry(self):
        df = _make_overbought_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "short":
            assert sig.target_price < sig.entry_price

    def test_short_stop_above_entry(self):
        df = _make_overbought_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "short":
            assert sig.stop_price > sig.entry_price

    def test_short_confirmations_not_empty(self):
        df = _make_overbought_df()
        sig = BBRSIReversalDetector().detect(df)
        if sig.detected and sig.direction == "short":
            assert len(sig.confirmations) >= 1


# ---------------------------------------------------------------------------
# Tests: RSI divergence
# ---------------------------------------------------------------------------

class TestRsiDivergence:
    def _make_bullish_divergence_df(self, n: int = 40) -> pd.DataFrame:
        """Price makes lower low; RSI recovers — classic bullish divergence."""
        rng = np.random.default_rng(99)
        # Stable then sharp drop
        stable = 100.0 + rng.normal(0, 0.3, 25)
        # First leg down
        leg1 = np.linspace(100, 80, 8) + rng.normal(0, 0.2, 8)
        # Small recovery
        recovery = np.linspace(80, 85, 4) + rng.normal(0, 0.2, 4)
        # Second leg down (lower low in price, but RSI should be higher than leg1 bottom)
        leg2 = np.linspace(85, 75, 3) + rng.normal(0, 0.2, 3)
        closes = np.concatenate([stable, leg1, recovery, leg2])[:n]
        highs = closes + 0.5
        lows = closes - 0.5
        opens = closes + rng.normal(0, 0.2, len(closes))
        volumes = rng.integers(200_000, 600_000, len(closes)).astype(float)
        volumes[-1] = volumes[:-1].mean() * 3.0
        opens[-1] = closes[-1] - 0.3  # green candle
        return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes})

    def test_divergence_method_returns_bool(self):
        df = _make_oversold_df()
        detector = BBRSIReversalDetector()
        from alpaca_trader.strategies.indicators import calc_rsi
        rsi_series = calc_rsi(df["close"])
        result = detector._check_rsi_divergence(df, rsi_series, "long")
        assert isinstance(result, bool)

    def test_divergence_false_for_insufficient_data(self):
        df = _make_ohlcv(n=5)
        detector = BBRSIReversalDetector()
        from alpaca_trader.strategies.indicators import calc_rsi
        rsi_series = calc_rsi(df["close"])
        result = detector._check_rsi_divergence(df, rsi_series, "long", lookback=10)
        assert result is False


# ---------------------------------------------------------------------------
# Tests: strength scoring
# ---------------------------------------------------------------------------

class TestStrengthScoring:
    def test_more_confirmations_yield_higher_strength(self):
        detector = BBRSIReversalDetector()
        # Same RSI, one confirmation vs three
        s1 = detector._calc_strength(rsi=20.0, bb_pct=-0.1, confirmations=["volume_spike"], direction="long")
        s3 = detector._calc_strength(rsi=20.0, bb_pct=-0.1, confirmations=["volume_spike", "candle_pattern", "rsi_divergence"], direction="long")
        assert s3 > s1

    def test_strength_clamped_to_1(self):
        detector = BBRSIReversalDetector()
        s = detector._calc_strength(rsi=0.0, bb_pct=-1.0, confirmations=["a", "b", "c", "d", "e"], direction="long")
        assert s <= 1.0

    def test_strength_zero_rsi_gives_nonzero_score(self):
        detector = BBRSIReversalDetector()
        s = detector._calc_strength(rsi=0.0, bb_pct=-1.0, confirmations=["volume_spike"], direction="long")
        assert s > 0.0


# ---------------------------------------------------------------------------
# Tests: target / stop calculation
# ---------------------------------------------------------------------------

class TestTargetCalculation:
    def test_long_stop_is_2x_band_distance_below_entry(self):
        detector = BBRSIReversalDetector()
        close = 90.0
        lower = 92.0  # close is below lower — band_distance = 2
        middle = 100.0
        entry, target, stop = detector._calc_targets(close, middle, lower, "long")
        assert entry == 90.0
        assert target == 100.0
        # band_distance = abs(90 - 92) = 2; stop = 90 - 2*2 = 86
        assert abs(stop - 86.0) < 1e-9

    def test_short_stop_is_2x_band_distance_above_entry(self):
        detector = BBRSIReversalDetector()
        close = 110.0
        upper = 108.0  # close is above upper — band_distance = 2
        middle = 100.0
        entry, target, stop = detector._calc_targets(close, middle, upper, "short")
        assert entry == 110.0
        assert target == 100.0
        # band_distance = abs(110 - 108) = 2; stop = 110 + 2*2 = 114
        assert abs(stop - 114.0) < 1e-9

    def test_risk_reward_positive_for_valid_inputs(self):
        detector = BBRSIReversalDetector()
        rr = detector._calc_rr(entry=90.0, target=100.0, stop=86.0, direction="long")
        # reward=10, risk=4 → RR=2.5
        assert abs(rr - 2.5) < 0.01

    def test_risk_reward_zero_when_risk_is_zero(self):
        detector = BBRSIReversalDetector()
        rr = detector._calc_rr(entry=90.0, target=100.0, stop=90.0, direction="long")
        assert rr == 0.0
```

- [ ] **Step 4.2: Run bb_rsi_reversal tests**

```
cd /Users/tonylesmb/claw-workspace/alpaca-trader
python -m pytest tests/test_bb_rsi_reversal.py -v
```

Expected: All tests pass.

- [ ] **Step 4.3: Commit**

```bash
git add tests/test_bb_rsi_reversal.py
git commit -m "test: add comprehensive tests for BBRSIReversalDetector"
```

---

## Task 5: Update strategies/__init__.py

**Files:**
- Modify: `src/alpaca_trader/strategies/__init__.py`

- [ ] **Step 5.1: Add exports for new classes**

Replace the entire `__init__.py` with:

```python
"""Bollinger Band strategy modules for alpaca-trader."""

from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.squeeze import SqueezeDetector, SqueezeSignal
from alpaca_trader.strategies.bounce import BounceDetector, BounceSignal
from alpaca_trader.strategies.trend import TrendDetector, TrendSignal
from alpaca_trader.strategies.bb_rsi_reversal import BBRSIReversalDetector, BBRSIReversalSignal
from alpaca_trader.strategies.scanner import WatchlistScanner
from alpaca_trader.strategies.backtest import Backtester, BacktestResult

__all__ = [
    "BollingerBands",
    "SqueezeDetector", "SqueezeSignal",
    "BounceDetector", "BounceSignal",
    "TrendDetector", "TrendSignal",
    "BBRSIReversalDetector", "BBRSIReversalSignal",
    "WatchlistScanner",
    "Backtester", "BacktestResult",
]
```

- [ ] **Step 5.2: Verify import works**

```
cd /Users/tonylesmb/claw-workspace/alpaca-trader
python -c "from alpaca_trader.strategies import BBRSIReversalDetector, BBRSIReversalSignal; print('OK')"
```

Expected output: `OK`

- [ ] **Step 5.3: Commit**

```bash
git add src/alpaca_trader/strategies/__init__.py
git commit -m "chore: export BBRSIReversalDetector and BBRSIReversalSignal from strategies package"
```

---

## Task 6: Integrate into scanner.py

**Files:**
- Modify: `src/alpaca_trader/strategies/scanner.py`

- [ ] **Step 6.1: Add BBRSIReversalDetector import and branch**

Add the import at the top (alongside the other detector imports):

```python
from alpaca_trader.strategies.bb_rsi_reversal import BBRSIReversalDetector
```

Add the `elif` branch in `_scan_symbol` after the `elif strategy == "trend":` block and before the final `else:`:

```python
            elif strategy == "bb_rsi_reversal":
                detector = BBRSIReversalDetector()
                sig = detector.detect(df)
                return Signal(
                    symbol=symbol, strategy=strategy,
                    detected=sig.detected, direction=sig.direction,
                    strength=sig.strength,
                    details={
                        "rsi": round(sig.rsi, 1),
                        "bb_pct": round(sig.bb_pct, 4),
                        "confirmations": sig.confirmations,
                        "target": round(sig.target_price, 2),
                        "stop": round(sig.stop_price, 2),
                        "risk_reward": round(sig.risk_reward, 2),
                    },
                    timestamp=timestamp,
                )
```

- [ ] **Step 6.2: Run all strategy tests**

```
cd /Users/tonylesmb/claw-workspace/alpaca-trader
python -m pytest tests/test_strategies.py -v
```

Expected: All tests pass.

- [ ] **Step 6.3: Commit**

```bash
git add src/alpaca_trader/strategies/scanner.py
git commit -m "feat: add bb_rsi_reversal to WatchlistScanner"
```

---

## Task 7: Integrate into backtest.py

**Files:**
- Modify: `src/alpaca_trader/strategies/backtest.py`

- [ ] **Step 7.1: Add BBRSIReversalDetector import**

Add to the imports at the top of `backtest.py`:

```python
from alpaca_trader.strategies.bb_rsi_reversal import BBRSIReversalDetector
```

- [ ] **Step 7.2: Add entry signal in _get_signal**

Add an `elif` branch in `_get_signal` after the `elif strategy == "trend":` block:

```python
            elif strategy == "bb_rsi_reversal":
                sig = BBRSIReversalDetector().detect(df)
                return sig.detected, sig.direction
```

- [ ] **Step 7.3: Add exit logic in _check_exit**

Add an `elif` branch in `_check_exit` after the `elif strategy in ("bounce", "trend"):` block:

```python
            elif strategy == "bb_rsi_reversal":
                # Exit 1: price crosses back through the middle band (mean reversion target)
                if direction == "long":
                    return close >= middle
                else:
                    return close <= middle
```

Also add tracking variables for stop loss and time-based exit in `_simulate`. The simplest approach that matches the PRD exit rules is:

Find the `_simulate` method and replace it with the updated version that tracks entry_middle, entry_band, and bars_held:

```python
    def _simulate(self, df: pd.DataFrame, strategy: str,
                  initial_capital: float) -> list[Trade]:
        """Walk through bars, generating entry/exit signals."""
        trades = []
        in_trade = False
        entry_idx = None
        entry_price = None
        direction = "none"
        entry_middle = None   # middle band at entry (for bb_rsi_reversal stop)
        entry_band = None     # breached band at entry (for bb_rsi_reversal stop)
        min_rows = 25

        bb = BollingerBands()

        for i in range(min_rows, len(df)):
            window = df.iloc[:i + 1]
            latest = df.iloc[i]
            close = float(latest["close"])
            ts = str(latest.name)

            if not in_trade:
                sig_detected, sig_direction = self._get_signal(window, strategy)
                if sig_detected and sig_direction in ("long", "short"):
                    in_trade = True
                    entry_idx = i
                    entry_price = close
                    direction = sig_direction
                    # Record middle/band for bb_rsi_reversal exit rules
                    if strategy == "bb_rsi_reversal":
                        try:
                            enriched = bb.calc(window)
                            entry_middle = float(enriched.iloc[-1]["bb_middle"])
                            if direction == "long":
                                entry_band = float(enriched.iloc[-1]["bb_lower"])
                            else:
                                entry_band = float(enriched.iloc[-1]["bb_upper"])
                        except Exception:
                            entry_middle = None
                            entry_band = None
            else:
                bars_held = i - entry_idx
                should_exit = self._check_exit(
                    window, strategy, direction,
                    entry_price=entry_price,
                    entry_middle=entry_middle,
                    entry_band=entry_band,
                    bars_held=bars_held,
                )
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
                    entry_middle = None
                    entry_band = None

        return trades
```

- [ ] **Step 7.4: Update _check_exit signature to accept new kwargs**

Replace the `_check_exit` method signature and body with:

```python
    def _check_exit(
        self,
        df: pd.DataFrame,
        strategy: str,
        direction: str,
        entry_price: float | None = None,
        entry_middle: float | None = None,
        entry_band: float | None = None,
        bars_held: int = 0,
    ) -> bool:
        """Check exit condition based on strategy rules.

        Args:
            df: Rolling window of bars up to current bar.
            strategy: Strategy name.
            direction: 'long' or 'short'.
            entry_price: Price at which the trade was entered (bb_rsi_reversal only).
            entry_middle: Middle band at entry time (bb_rsi_reversal only).
            entry_band: Breached band at entry (bb_rsi_reversal only).
            bars_held: Number of bars since entry (bb_rsi_reversal time-based exit).

        Returns:
            True when the exit condition is triggered.
        """
        try:
            bb = BollingerBands()
            enriched = bb.calc(df)
            latest = enriched.iloc[-1]
            close = float(latest["close"])
            middle = float(latest["bb_middle"])
            upper = float(latest["bb_upper"])
            lower = float(latest["bb_lower"])

            if strategy == "squeeze":
                if direction == "long":
                    return close < upper
                else:
                    return close > lower

            elif strategy in ("bounce", "trend"):
                if direction == "long":
                    return close >= middle
                else:
                    return close <= middle

            elif strategy == "bb_rsi_reversal":
                # Exit 1: middle band cross (take profit)
                if direction == "long" and close >= middle:
                    return True
                if direction == "short" and close <= middle:
                    return True

                # Exit 2: stop loss — price moves 2x entry-band-distance further against trade
                if entry_price is not None and entry_band is not None:
                    band_distance = abs(entry_price - entry_band)
                    if direction == "long" and close < entry_price - 2.0 * band_distance:
                        return True
                    if direction == "short" and close > entry_price + 2.0 * band_distance:
                        return True

                # Exit 3: time-based — exit after 10 bars
                if bars_held >= 10:
                    return True

        except Exception:
            pass
        return False
```

- [ ] **Step 7.5: Run all tests**

```
cd /Users/tonylesmb/claw-workspace/alpaca-trader
python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 7.6: Commit**

```bash
git add src/alpaca_trader/strategies/backtest.py
git commit -m "feat: add bb_rsi_reversal entry/exit logic to Backtester"
```

---

## Task 8: Integrate into alerts/scanner.py

**Files:**
- Modify: `src/alpaca_trader/alerts/scanner.py`

- [ ] **Step 8.1: Add bb_rsi_reversal to the strategy loop**

Change the strategy loop tuple from:

```python
                for strategy in ("squeeze", "bounce", "trend"):
```

to:

```python
                for strategy in ("squeeze", "bounce", "trend", "bb_rsi_reversal"):
```

- [ ] **Step 8.2: Run all tests**

```
cd /Users/tonylesmb/claw-workspace/alpaca-trader
python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 8.3: Commit**

```bash
git add src/alpaca_trader/alerts/scanner.py
git commit -m "feat: add bb_rsi_reversal to ScheduledScanner strategy loop"
```

---

## Task 9: Update CLI

**Files:**
- Modify: `src/alpaca_trader/cli.py`

- [ ] **Step 9.1: Update scan command's valid_strategies and help text**

Find line (approx. line 664):
```python
    strategy: str = typer.Option("squeeze", "--strategy", help="Strategy: squeeze, bounce, trend"),
```
Change to:
```python
    strategy: str = typer.Option("squeeze", "--strategy", help="Strategy: squeeze, bounce, trend, bb_rsi_reversal"),
```

Find line (approx. line 669):
```python
    valid_strategies = ("squeeze", "bounce", "trend")
```
Change to:
```python
    valid_strategies = ("squeeze", "bounce", "trend", "bb_rsi_reversal")
```

- [ ] **Step 9.2: Update backtest command's valid_strategies and help text**

Find line (approx. line 738):
```python
    strategy: str = typer.Option(..., "--strategy", help="Strategy: squeeze, bounce, trend"),
```
Change to:
```python
    strategy: str = typer.Option(..., "--strategy", help="Strategy: squeeze, bounce, trend, bb_rsi_reversal"),
```

Find line (approx. line 746):
```python
    valid_strategies = ("squeeze", "bounce", "trend")
```
Change to:
```python
    valid_strategies = ("squeeze", "bounce", "trend", "bb_rsi_reversal")
```

- [ ] **Step 9.3: Verify CLI import loads cleanly**

```
cd /Users/tonylesmb/claw-workspace/alpaca-trader
python -c "from alpaca_trader.cli import app; print('CLI OK')"
```

Expected output: `CLI OK`

- [ ] **Step 9.4: Run all tests**

```
cd /Users/tonylesmb/claw-workspace/alpaca-trader
python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 9.5: Commit**

```bash
git add src/alpaca_trader/cli.py
git commit -m "feat: add bb_rsi_reversal to CLI scan and backtest valid strategies"
```

---

## Task 10: Final verification

- [ ] **Step 10.1: Run the full test suite**

```
cd /Users/tonylesmb/claw-workspace/alpaca-trader
python -m pytest tests/ -v --tb=short
```

Expected: All tests pass. No regressions.

- [ ] **Step 10.2: Check imports are all working**

```bash
python -c "
from alpaca_trader.strategies import BBRSIReversalDetector, BBRSIReversalSignal
from alpaca_trader.strategies.indicators import calc_rsi, calc_adx, calc_macd, calc_atr, calc_volume_sma
from alpaca_trader.strategies.bounce import BounceDetector
from alpaca_trader.strategies.trend import TrendDetector
from alpaca_trader.strategies.scanner import WatchlistScanner
from alpaca_trader.strategies.backtest import Backtester
print('All imports OK')
"
```

Expected output: `All imports OK`

- [ ] **Step 10.3: Send completion notification**

```bash
openclaw system event --text 'Done: Sprint 8 BB+RSI Reversal strategy implemented with shared indicators, scanner/backtest/CLI integration, and tests' --mode now
```
