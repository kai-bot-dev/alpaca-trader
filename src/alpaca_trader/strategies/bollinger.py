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
