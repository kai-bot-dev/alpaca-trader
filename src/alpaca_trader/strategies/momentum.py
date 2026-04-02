"""Momentum strategy — EMA crossover + RSI-50 + SMA confirmation.

Designed for Alpaca free tier which returns ~22 daily bars.
All indicators use short lookback periods that work with 15+ bars.
"""

from dataclasses import dataclass

import pandas as pd

from alpaca_trader.strategies.indicators import calc_rsi


@dataclass
class MomentumSignal:
    """Signal produced by MomentumDetector.

    Attributes:
        detected: True if a momentum signal is present.
        direction: 'long', 'short', or 'none'.
        strength: Confidence score from 0.0 to 1.0.
            Based on RSI distance from 50, normalised over 30 points.
        rsi: Current RSI value.
        ema_fast: Current 5-period EMA value.
        ema_slow: Current 12-period EMA value.
        sma: Current 8-period SMA value.
    """

    detected: bool
    direction: str
    strength: float
    rsi: float
    ema_fast: float
    ema_slow: float
    sma: float


class MomentumDetector:
    """Detects momentum signals via RSI-50 crossover + EMA5/EMA12 + SMA8 confirmation.

    Designed to work with as few as 15 bars (Alpaca free tier returns ~22).

    Signal fires when:
    - LONG:  RSI > 50 AND RSI was < 50 within last 3 bars (crossover)
             AND EMA5 > EMA12 AND close > SMA8
    - SHORT: RSI < 50 AND RSI was > 50 within last 3 bars
             AND EMA5 < EMA12 AND close < SMA8

    Strength = abs(RSI - 50) / 30, capped at 1.0.

    Example:
        >>> from alpaca_trader.strategies.momentum import MomentumDetector
        >>> detector = MomentumDetector()
        >>> signal = detector.detect(ohlcv_df)
        >>> if signal.detected:
        ...     print(f"{signal.direction} momentum -- strength={signal.strength:.2f}")
    """

    def __init__(
        self,
        rsi_period: int = 10,
        ema_fast_period: int = 5,
        ema_slow_period: int = 12,
        sma_period: int = 8,
        min_rows: int = 15,
    ) -> None:
        self.rsi_period = rsi_period
        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period
        self.sma_period = sma_period
        self.min_rows = min_rows

    def detect(self, df: pd.DataFrame) -> MomentumSignal:
        """Detect a momentum signal on the most recent bar.

        Args:
            df: OHLCV DataFrame with at least a 'close' column.
                Minimum ``min_rows`` rows required (default 15).

        Returns:
            MomentumSignal with detection details.
        """
        no_signal = MomentumSignal(
            detected=False,
            direction="none",
            strength=0.0,
            rsi=50.0,
            ema_fast=0.0,
            ema_slow=0.0,
            sma=0.0,
        )

        if len(df) < self.min_rows:
            return no_signal

        close = df["close"]

        rsi_series = calc_rsi(close, self.rsi_period)
        ema_fast_series = close.ewm(span=self.ema_fast_period, adjust=False).mean()
        ema_slow_series = close.ewm(span=self.ema_slow_period, adjust=False).mean()
        sma_series = close.rolling(window=self.sma_period).mean()

        rsi_curr = float(rsi_series.iloc[-1])
        ema_fast = float(ema_fast_series.iloc[-1])
        ema_slow = float(ema_slow_series.iloc[-1])
        sma = float(sma_series.iloc[-1])
        current_close = float(close.iloc[-1])

        if pd.isna(rsi_curr) or pd.isna(ema_fast) or pd.isna(ema_slow) or pd.isna(sma):
            return no_signal

        # Look back up to 3 bars for RSI crossover (excluding current bar)
        lookback = min(3, len(rsi_series) - 1)
        recent_rsi = rsi_series.iloc[-(lookback + 1) : -1]

        # RSI was below 50 recently -> bullish crossover
        rsi_was_below_50 = any(v < 50.0 for v in recent_rsi if not pd.isna(v))
        # RSI was above 50 recently -> bearish crossover
        rsi_was_above_50 = any(v > 50.0 for v in recent_rsi if not pd.isna(v))

        strength = min(1.0, abs(rsi_curr - 50.0) / 30.0)

        # Bullish: RSI > 50 (crossover from below) + EMA5 > EMA12 + close > SMA8
        if (
            rsi_curr > 50.0
            and rsi_was_below_50
            and ema_fast > ema_slow
            and current_close > sma
        ):
            return MomentumSignal(
                detected=True,
                direction="long",
                strength=round(strength, 4),
                rsi=round(rsi_curr, 2),
                ema_fast=round(ema_fast, 4),
                ema_slow=round(ema_slow, 4),
                sma=round(sma, 4),
            )

        # Bearish: RSI < 50 (crossover from above) + EMA5 < EMA12 + close < SMA8
        if (
            rsi_curr < 50.0
            and rsi_was_above_50
            and ema_fast < ema_slow
            and current_close < sma
        ):
            return MomentumSignal(
                detected=True,
                direction="short",
                strength=round(strength, 4),
                rsi=round(rsi_curr, 2),
                ema_fast=round(ema_fast, 4),
                ema_slow=round(ema_slow, 4),
                sma=round(sma, 4),
            )

        return MomentumSignal(
            detected=False,
            direction="none",
            strength=0.0,
            rsi=round(rsi_curr, 2),
            ema_fast=round(ema_fast, 4),
            ema_slow=round(ema_slow, 4),
            sma=round(sma, 4),
        )
