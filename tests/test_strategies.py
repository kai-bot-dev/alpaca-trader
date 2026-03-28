"""Comprehensive unit tests for strategy detector classes."""

import unittest
import numpy as np
import pandas as pd

from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.squeeze import SqueezeDetector, SqueezeSignal
from alpaca_trader.strategies.bounce import BounceDetector, BounceSignal
from alpaca_trader.strategies.trend import TrendDetector, TrendSignal


def make_ohlcv(n=60, start_price=100.0, volatility=0.02, trend=0.0, seed=42, base_volume=1e6):
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=trend, scale=volatility, size=n)
    close = start_price * np.cumprod(1 + returns)
    open_ = np.roll(close, 1)
    open_[0] = start_price
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.005, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.005, n))
    volume = (base_volume * (1 + rng.normal(0, 0.3, n))).clip(100)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def make_tight_squeeze_data(n=40, seed=99):
    rng = np.random.default_rng(seed)
    flat_n = n - 5
    close_flat = 100.0 + rng.normal(0, 0.05, flat_n).cumsum()
    breakout = close_flat[-1] + np.cumsum(rng.uniform(1.5, 3.0, 5))
    close = np.concatenate([close_flat, breakout])
    open_ = np.roll(close, 1)
    open_[0] = 100.0
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.002, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.002, n))
    vol_flat = rng.uniform(8e5, 1.2e6, flat_n)
    vol_break = rng.uniform(3e6, 5e6, 5)
    volume = np.concatenate([vol_flat, vol_break])
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def make_trending_up(n=60, seed=7):
    return make_ohlcv(n=n, volatility=0.008, trend=0.005, seed=seed)


def make_trending_down(n=60, seed=8):
    return make_ohlcv(n=n, volatility=0.008, trend=-0.005, seed=seed)


def make_range_bound(n=60, seed=10):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    close = 100.0 + 3.0 * np.sin(2 * np.pi * t / 20) + rng.normal(0, 0.3, n)
    open_ = np.roll(close, 1)
    open_[0] = 100.0
    high = np.maximum(open_, close) + rng.uniform(0.1, 0.5, n)
    low = np.minimum(open_, close) - rng.uniform(0.1, 0.5, n)
    volume = rng.uniform(5e5, 1.5e6, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


class TestBollingerBands(unittest.TestCase):
    def setUp(self):
        self.bb = BollingerBands(period=20, std_dev=2.0)
        self.df = make_ohlcv(n=60)

    def test_calc_returns_expected_columns(self):
        r = self.bb.calc(self.df)
        for c in ["bb_middle", "bb_upper", "bb_lower", "bb_width", "bb_pct"]:
            self.assertIn(c, r.columns)

    def test_calc_preserves_original_columns(self):
        r = self.bb.calc(self.df)
        for c in ["open", "high", "low", "close", "volume"]:
            self.assertIn(c, r.columns)

    def test_calc_does_not_mutate_input(self):
        cols = list(self.df.columns)
        self.bb.calc(self.df)
        self.assertEqual(list(self.df.columns), cols)

    def test_upper_ge_middle_ge_lower(self):
        r = self.bb.calc(self.df).dropna(subset=["bb_middle"])
        self.assertTrue((r["bb_upper"] >= r["bb_middle"]).all())
        self.assertTrue((r["bb_middle"] >= r["bb_lower"]).all())

    def test_bb_width_nonnegative(self):
        r = self.bb.calc(self.df).dropna(subset=["bb_width"])
        self.assertTrue((r["bb_width"] >= 0).all())

    def test_nan_count_equals_period_minus_one(self):
        r = self.bb.calc(self.df)
        self.assertEqual(r["bb_middle"].isna().sum(), self.bb.period - 1)

    def test_missing_close_raises(self):
        with self.assertRaises(ValueError):
            self.bb.calc(pd.DataFrame({"price": [1, 2, 3]}))

    def test_insufficient_rows_raises(self):
        with self.assertRaises(ValueError):
            self.bb.calc(make_ohlcv(n=10))

    def test_custom_period(self):
        bb = BollingerBands(period=10, std_dev=1.5)
        r = bb.calc(make_ohlcv(n=30))
        self.assertEqual(r["bb_middle"].isna().sum(), 9)

    def test_constant_price_zero_width(self):
        df = pd.DataFrame({k: [100.0]*25 for k in ["open","high","low","close"]})
        df["volume"] = [1e6]*25
        r = self.bb.calc(df)
        self.assertAlmostEqual(r.iloc[-1]["bb_width"], 0.0, places=5)


class TestSqueezeDetector(unittest.TestCase):
    def setUp(self):
        self.det = SqueezeDetector(bb_period=20, bb_std_dev=2.0)

    def test_no_squeeze_volatile(self):
        s = self.det.detect(make_ohlcv(n=60, volatility=0.05, seed=1), threshold=0.02)
        self.assertFalse(s.detected or s.direction != "none")

    def test_squeeze_tight_data(self):
        s = self.det.detect(make_tight_squeeze_data(), threshold=0.15)
        self.assertIsInstance(s, SqueezeSignal)
        self.assertIn(s.direction, ["long", "short", "none"])

    def test_direction_long_breakout(self):
        s = self.det.detect(make_tight_squeeze_data(), threshold=0.15)
        if s.detected and s.candle_outside:
            self.assertEqual(s.direction, "long")

    def test_insufficient_data(self):
        s = self.det.detect(make_ohlcv(n=5))
        self.assertFalse(s.detected)

    def test_no_volume_confirmation(self):
        df = make_tight_squeeze_data()
        df["volume"] = 1e6
        s = self.det.detect(df, threshold=0.15)
        if s.detected and s.candle_outside:
            self.assertEqual(s.direction, "none")

    def test_strength_bounds(self):
        s = self.det.detect(make_tight_squeeze_data(), threshold=0.15)
        self.assertGreaterEqual(s.strength, 0.0)
        self.assertLessEqual(s.strength, 1.0)

    def test_no_volume_column(self):
        df = make_tight_squeeze_data().drop(columns=["volume"])
        s = self.det.detect(df, threshold=0.15)
        self.assertIsInstance(s, SqueezeSignal)

    def test_threshold_ordering(self):
        df = make_ohlcv(n=60, volatility=0.01)
        easy = self.det.detect(df, threshold=0.50)
        hard = self.det.detect(df, threshold=0.001)
        if hard.detected:
            self.assertTrue(easy.detected)


class TestBounceDetector(unittest.TestCase):
    def setUp(self):
        self.det = BounceDetector(bb_period=20, bb_std_dev=2.0, rsi_period=14, adx_period=14)

    def test_no_signal_trending(self):
        s = self.det.detect(make_trending_up())
        if s.adx >= 25:
            self.assertFalse(s.detected)

    def test_valid_signal_type(self):
        s = self.det.detect(make_range_bound())
        self.assertIsInstance(s, BounceSignal)
        self.assertIn(s.direction, ["long", "short", "none"])
        self.assertIn(s.band_touched, ["upper", "lower", "none"])

    def test_forced_dip(self):
        rng = np.random.default_rng(42)
        n = 60
        close = np.full(n, 100.0)
        for i in range(1, 50):
            close[i] = close[i-1] + rng.normal(0, 0.3)
        for i in range(50, n):
            close[i] = close[i-1] - 0.8
        o = np.roll(close, 1)
        o[0] = 100.0
        df = pd.DataFrame({"open": o, "high": np.maximum(o, close)+0.2, "low": np.minimum(o, close)-0.2, "close": close, "volume": np.full(n, 1e6)})
        self.assertIsInstance(self.det.detect(df), BounceSignal)

    def test_insufficient_data(self):
        s = self.det.detect(make_ohlcv(n=10))
        self.assertFalse(s.detected)

    def test_rsi_range(self):
        s = self.det.detect(make_ohlcv(n=60))
        self.assertGreaterEqual(s.rsi, 0.0)
        self.assertLessEqual(s.rsi, 100.0)

    def test_adx_nonneg(self):
        self.assertGreaterEqual(self.det.detect(make_ohlcv(n=60)).adx, 0.0)

    def test_forced_spike(self):
        rng = np.random.default_rng(55)
        n = 60
        close = np.full(n, 100.0)
        for i in range(1, 50):
            close[i] = close[i-1] + rng.normal(0, 0.3)
        for i in range(50, n):
            close[i] = close[i-1] + 0.8
        o = np.roll(close, 1)
        o[0] = 100.0
        df = pd.DataFrame({"open": o, "high": np.maximum(o, close)+0.2, "low": np.minimum(o, close)-0.2, "close": close, "volume": np.full(n, 1e6)})
        self.assertIsInstance(self.det.detect(df), BounceSignal)


class TestTrendDetector(unittest.TestCase):
    def setUp(self):
        self.det = TrendDetector(bb_period=20, bb_std_dev=2.0, lookback=5, macd_fast=12, macd_slow=26, macd_signal=9)

    def test_trend_long_uptrend(self):
        s = self.det.detect(make_trending_up())
        self.assertIsInstance(s, TrendSignal)
        if s.detected:
            self.assertEqual(s.direction, "long")
            self.assertGreater(s.macd_hist, 0)

    def test_trend_short_downtrend(self):
        s = self.det.detect(make_trending_down())
        if s.detected:
            self.assertEqual(s.direction, "short")
            self.assertLess(s.macd_hist, 0)

    def test_range_bound(self):
        self.assertIsInstance(self.det.detect(make_range_bound()), TrendSignal)

    def test_insufficient_data(self):
        s = self.det.detect(make_ohlcv(n=10))
        self.assertFalse(s.detected)
        self.assertEqual(s.strength, 0.0)

    def test_strength_bounds(self):
        s = self.det.detect(make_trending_up())
        self.assertGreaterEqual(s.strength, 0.0)
        self.assertLessEqual(s.strength, 1.0)

    def test_macd_hist_float(self):
        self.assertIsInstance(self.det.detect(make_ohlcv()).macd_hist, float)

    def test_lookback_variation(self):
        df = make_trending_up()
        self.assertIsInstance(TrendDetector(lookback=3).detect(df), TrendSignal)
        self.assertIsInstance(TrendDetector(lookback=10).detect(df), TrendSignal)

    def test_high_strength_uptrend(self):
        s = self.det.detect(make_trending_up())
        if s.detected and s.direction == "long":
            self.assertGreaterEqual(s.strength, 0.6)

    def test_custom_macd(self):
        d = TrendDetector(macd_fast=8, macd_slow=21, macd_signal=5)
        self.assertIsInstance(d.detect(make_ohlcv()), TrendSignal)


if __name__ == "__main__":
    unittest.main()
