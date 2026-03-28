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
