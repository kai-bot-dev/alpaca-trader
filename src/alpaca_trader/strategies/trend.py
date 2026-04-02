"""Trend (walking the bands) detection using Bollinger Bands + MACD."""

from dataclasses import dataclass

import pandas as pd

from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.indicators import calc_macd


@dataclass
class TrendSignal:
    detected: bool
    direction: str  # 'long', 'short', or 'none'
    strength: float  # 0.0–1.0: proportion of last N candles along the band
    macd_hist: float  # Current MACD histogram value (positive = bullish)


# Keep private alias for backward compatibility
_calc_macd = calc_macd


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

    def __init__(
        self,
        bb_period: int = 20,
        bb_std_dev: float = 2.0,
        lookback: int = 5,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
    ):
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
            return TrendSignal(
                detected=False, direction="none", strength=0.0, macd_hist=0.0
            )

        enriched = self.bb.calc(df)
        _, _, histogram = _calc_macd(
            df["close"], self.macd_fast, self.macd_slow, self.macd_signal_period
        )

        macd_hist = (
            float(histogram.iloc[-1]) if not pd.isna(histogram.iloc[-1]) else 0.0
        )

        # Check last N candles: price hugging upper or lower band
        recent = enriched.iloc[-self.lookback :]

        # Count candles where close >= bb_middle (upper walk) or <= bb_middle (lower walk)
        upper_hugging = (recent["close"] >= recent["bb_middle"]).sum()
        lower_hugging = (recent["close"] <= recent["bb_middle"]).sum()

        upper_strength = upper_hugging / self.lookback
        lower_strength = lower_hugging / self.lookback

        # Require at least 60% of candles hugging a band AND MACD confirmation
        if upper_strength >= 0.6 and macd_hist > 0:
            return TrendSignal(
                detected=True,
                direction="long",
                strength=float(upper_strength),
                macd_hist=macd_hist,
            )
        elif lower_strength >= 0.6 and macd_hist < 0:
            return TrendSignal(
                detected=True,
                direction="short",
                strength=float(lower_strength),
                macd_hist=macd_hist,
            )

        return TrendSignal(
            detected=False, direction="none", strength=0.0, macd_hist=macd_hist
        )
