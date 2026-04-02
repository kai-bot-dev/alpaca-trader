"""Tests for shared indicator calculations in indicators.py."""

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


def _make_ohlcv(n: int = 60, trend: float = 0.5) -> pd.DataFrame:
    """Create synthetic OHLCV data."""
    np.random.seed(42)
    close = 100 + trend * np.arange(n) + np.random.randn(n)
    high = close + np.abs(np.random.randn(n)) * 0.5
    low = close - np.abs(np.random.randn(n)) * 0.5
    open_ = close - np.random.randn(n) * 0.3
    volume = 1_000_000 + np.random.randint(0, 500_000, n)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume.astype(float),
        }
    )


class TestCalcRSI:
    def test_returns_series_same_length(self):
        df = _make_ohlcv(60)
        rsi = calc_rsi(df["close"])
        assert isinstance(rsi, pd.Series)
        assert len(rsi) == 60

    def test_values_between_0_and_100(self):
        df = _make_ohlcv(60)
        rsi = calc_rsi(df["close"])
        valid = rsi.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_trending_up_gives_high_rsi(self):
        # Pattern: mostly up moves with a few down moves so RSI is computable and high
        prices = []
        v = 100.0
        for i in range(50):
            v += 1.0 if i % 5 != 0 else -0.2  # 4 up for every 1 small down
            prices.append(v)
        close = pd.Series(prices)
        rsi = calc_rsi(close)
        valid = rsi.dropna()
        assert len(valid) > 0
        assert float(valid.iloc[-1]) > 70

    def test_trending_down_gives_low_rsi(self):
        # Pattern: mostly down moves with a few up moves so RSI is low
        prices = []
        v = 100.0
        for i in range(50):
            v -= 1.0 if i % 5 != 0 else -0.2  # 4 down for every 1 small up
            prices.append(v)
        close = pd.Series(prices)
        rsi = calc_rsi(close)
        valid = rsi.dropna()
        assert len(valid) > 0
        assert float(valid.iloc[-1]) < 30

    def test_custom_period(self):
        df = _make_ohlcv(60)
        rsi_9 = calc_rsi(df["close"], period=9)
        rsi_14 = calc_rsi(df["close"], period=14)
        # Different periods produce different values
        assert not rsi_9.equals(rsi_14)

    def test_first_values_are_nan(self):
        close = pd.Series([float(i) for i in range(20)])
        rsi = calc_rsi(close, period=14)
        # First `period` values should be NaN
        assert rsi.iloc[0:14].isna().all()


class TestCalcADX:
    def test_returns_series(self):
        df = _make_ohlcv(60)
        adx = calc_adx(df)
        assert isinstance(adx, pd.Series)
        assert len(adx) == 60

    def test_values_non_negative(self):
        df = _make_ohlcv(60)
        adx = calc_adx(df)
        valid = adx.dropna()
        assert (valid >= 0).all()

    def test_strong_trend_gives_high_adx(self):
        # Clear uptrend → ADX should be well above the 25 threshold
        n = 60
        close = pd.Series([100 + i * 2 for i in range(n)])
        high = close + 1
        low = close - 1
        df = pd.DataFrame({"high": high, "low": low, "close": close})
        adx = calc_adx(df)
        assert float(adx.dropna().iloc[-1]) > 25


class TestCalcMACD:
    def test_returns_three_series(self):
        df = _make_ohlcv(60)
        macd_line, signal_line, hist = calc_macd(df["close"])
        assert isinstance(macd_line, pd.Series)
        assert isinstance(signal_line, pd.Series)
        assert isinstance(hist, pd.Series)

    def test_histogram_is_macd_minus_signal(self):
        df = _make_ohlcv(60)
        macd_line, signal_line, hist = calc_macd(df["close"])
        expected = macd_line - signal_line
        pd.testing.assert_series_equal(hist, expected)

    def test_custom_periods(self):
        df = _make_ohlcv(60)
        m1, s1, h1 = calc_macd(df["close"], fast=5, slow=10, signal=3)
        m2, s2, h2 = calc_macd(df["close"], fast=12, slow=26, signal=9)
        assert not h1.equals(h2)

    def test_uptrend_positive_histogram(self):
        # Strongly trending up → fast EMA > slow EMA → positive MACD
        close = pd.Series([100 + i * 0.5 for i in range(60)])
        _, _, hist = calc_macd(close)
        assert float(hist.dropna().iloc[-1]) > 0


class TestCalcATR:
    def test_returns_series(self):
        df = _make_ohlcv(60)
        atr = calc_atr(df)
        assert isinstance(atr, pd.Series)
        assert len(atr) == 60

    def test_values_positive(self):
        df = _make_ohlcv(60)
        atr = calc_atr(df)
        valid = atr.dropna()
        assert (valid > 0).all()

    def test_high_volatility_gives_larger_atr(self):
        n = 60
        low_vol = pd.DataFrame(
            {
                "high": [100 + 0.5] * n,
                "low": [100 - 0.5] * n,
                "close": [100.0] * n,
            }
        )
        high_vol = pd.DataFrame(
            {
                "high": [100 + 5.0] * n,
                "low": [100 - 5.0] * n,
                "close": [100.0] * n,
            }
        )
        atr_low = calc_atr(low_vol).dropna().iloc[-1]
        atr_high = calc_atr(high_vol).dropna().iloc[-1]
        assert atr_high > atr_low


class TestCalcVolumeSMA:
    def test_returns_series(self):
        df = _make_ohlcv(60)
        vsma = calc_volume_sma(df["volume"])
        assert isinstance(vsma, pd.Series)
        assert len(vsma) == 60

    def test_first_values_nan(self):
        df = _make_ohlcv(60)
        vsma = calc_volume_sma(df["volume"], period=20)
        assert vsma.iloc[:19].isna().all()

    def test_correct_average(self):
        volume = pd.Series([float(i) for i in range(1, 11)])
        vsma = calc_volume_sma(volume, period=5)
        # Average of [6,7,8,9,10] = 8.0
        assert float(vsma.iloc[-1]) == pytest.approx(8.0)
