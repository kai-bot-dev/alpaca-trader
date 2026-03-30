"""Shared technical indicator calculations for Bollinger Band strategies."""

import numpy as np
import pandas as pd


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI using Wilder's smoothing.

    Args:
        close: Series of closing prices
        period: RSI lookback period (default 14)

    Returns:
        pd.Series of RSI values (0-100)
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate ADX (Average Directional Index).

    Args:
        df: OHLCV DataFrame with columns: high, low, close
        period: ADX smoothing period (default 14)

    Returns:
        pd.Series of ADX values
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
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx


def calc_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate MACD line, signal line, and histogram.

    Args:
        close: Series of closing prices
        fast: Fast EMA period (default 12)
        slow: Slow EMA period (default 26)
        signal: Signal line EMA period (default 9)

    Returns:
        Tuple of (macd_line, signal_line, histogram) as pd.Series
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range.

    Args:
        df: OHLCV DataFrame with columns: high, low, close
        period: ATR smoothing period (default 14)

    Returns:
        pd.Series of ATR values
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

    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return atr


def calc_volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    """Calculate simple moving average of volume.

    Args:
        volume: Series of volume values
        period: SMA lookback period (default 20)

    Returns:
        pd.Series of volume SMA values
    """
    return volume.rolling(window=period).mean()
