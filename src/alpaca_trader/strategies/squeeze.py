"""Squeeze (breakout) detection using Bollinger Band width contraction."""

from dataclasses import dataclass

import pandas as pd

from alpaca_trader.strategies.bollinger import BollingerBands


@dataclass
class SqueezeSignal:
    detected: bool
    width: float  # Current BB width (relative to price)
    candle_outside: bool  # Most recent close is outside a band
    direction: str  # 'long', 'short', or 'none'
    strength: float  # 0.0–1.0: how far outside the band the close is


class SqueezeDetector:
    """Detects Bollinger Band squeeze (breakout setup).

    A squeeze occurs when Bollinger Band width contracts below a threshold,
    indicating low volatility. When price then closes outside the band with
    volume confirmation, it signals a potential breakout.

    The detection pipeline:
    1. Check if BB width < threshold (squeeze active)
    2. Check if latest close is outside upper or lower band
    3. Confirm with volume spike (current vol > 1.5x 20-bar avg)
    4. Determine direction (long if above upper, short if below lower)

    Attributes:
        bb: BollingerBands instance used for band calculations.

    Example:
        >>> import pandas as pd
        >>> from alpaca_trader.strategies.squeeze import SqueezeDetector
        >>> detector = SqueezeDetector(bb_period=20, bb_std_dev=2.0)
        >>> df = pd.DataFrame({
        ...     'close': [...],  # OHLCV data
        ...     'volume': [...]
        ... })
        >>> signal = detector.detect(df, threshold=0.05)
        >>> if signal.detected and signal.direction == 'long':
        ...     print(f'Squeeze breakout long, strength={signal.strength:.2f}')
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
            return SqueezeSignal(
                detected=False,
                width=0.0,
                candle_outside=False,
                direction="none",
                strength=0.0,
            )

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
            return SqueezeSignal(
                detected=False,
                width=width,
                candle_outside=False,
                direction="none",
                strength=0.0,
            )

        # Check candle outside band
        candle_outside = close > upper or close < lower

        if not candle_outside:
            return SqueezeSignal(
                detected=True,
                width=width,
                candle_outside=False,
                direction="none",
                strength=0.0,
            )

        # Volume confirmation: current volume > 1.5x average
        if "volume" in df.columns:
            avg_vol = float(df["volume"].rolling(window=20).mean().iloc[-1])
            current_vol = float(df["volume"].iloc[-1])
            volume_confirmed = current_vol > 1.5 * avg_vol if avg_vol > 0 else False
        else:
            volume_confirmed = True  # No volume data → skip check

        if not volume_confirmed:
            return SqueezeSignal(
                detected=True,
                width=width,
                candle_outside=True,
                direction="none",
                strength=0.0,
            )

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
