"""Tests for WatchlistScanner.scan_async() — concurrent async scanning."""

import asyncio
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from alpaca_trader.strategies.scanner import WatchlistScanner


def make_ohlcv(n=60, start_price=100.0, volatility=0.02, seed=42):
    """Create synthetic OHLCV DataFrame for testing."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=0, scale=volatility, size=n)
    close = start_price * np.cumprod(1 + returns)
    open_ = np.roll(close, 1)
    open_[0] = start_price
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.005, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.005, n))
    volume = (1e6 * (1 + rng.normal(0, 0.3, n))).clip(100)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestScanAsync(unittest.TestCase):
    """Test that scan_async works correctly and runs concurrently."""

    @patch("alpaca_trader.strategies.scanner.alpaca")
    def test_scan_async_returns_same_as_sync(self, mock_alpaca):
        """scan_async should produce the same results as sync scan."""
        mock_alpaca.get_stock_bars_df.return_value = make_ohlcv(60)

        scanner = WatchlistScanner()
        symbols = ["AAPL", "TSLA", "GOOG"]

        sync_results = scanner.scan(symbols, strategy="squeeze")
        async_results = run(scanner.scan_async(symbols, strategy="squeeze"))

        self.assertEqual(len(sync_results), len(async_results))
        for s, a in zip(sync_results, async_results):
            self.assertEqual(s.symbol, a.symbol)
            self.assertEqual(s.strategy, a.strategy)
            self.assertEqual(s.detected, a.detected)
            self.assertEqual(s.direction, a.direction)

    @patch("alpaca_trader.strategies.scanner.alpaca")
    def test_scan_async_handles_errors(self, mock_alpaca):
        """scan_async should handle per-symbol errors gracefully."""

        def side_effect(symbol, period="1D", limit=60):
            if symbol == "BAD":
                raise RuntimeError("API error")
            return make_ohlcv(60)

        mock_alpaca.get_stock_bars_df.side_effect = side_effect

        scanner = WatchlistScanner()
        results = run(scanner.scan_async(["AAPL", "BAD", "GOOG"], strategy="bounce"))

        self.assertEqual(len(results), 3)
        bad_result = [r for r in results if r.symbol == "BAD"][0]
        self.assertFalse(bad_result.detected)
        self.assertIn("error", bad_result.details)

    @patch("alpaca_trader.strategies.scanner.alpaca")
    def test_scan_async_empty_symbols(self, mock_alpaca):
        """scan_async with no symbols returns empty list."""
        scanner = WatchlistScanner()
        results = run(scanner.scan_async([], strategy="squeeze"))
        self.assertEqual(results, [])

    @patch("alpaca_trader.strategies.scanner.alpaca")
    def test_scan_async_single_symbol(self, mock_alpaca):
        """scan_async works with just one symbol."""
        mock_alpaca.get_stock_bars_df.return_value = make_ohlcv(60)

        scanner = WatchlistScanner()
        results = run(scanner.scan_async(["AAPL"], strategy="trend"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].symbol, "AAPL")

    @patch("alpaca_trader.strategies.scanner.alpaca")
    def test_scan_async_runs_concurrently(self, mock_alpaca):
        """Verify scan_async actually runs symbols in parallel, not sequentially."""
        call_times = []

        def slow_bars(symbol, period="1D", limit=60):
            call_times.append(
                (symbol, threading.current_thread().name, time.monotonic())
            )
            time.sleep(0.05)  # 50ms per call
            return make_ohlcv(60, seed=hash(symbol) % 1000)

        mock_alpaca.get_stock_bars_df.side_effect = slow_bars

        scanner = WatchlistScanner()
        scanner.MAX_CONCURRENCY = 10  # Allow full concurrency for this test

        symbols = [f"SYM{i}" for i in range(5)]
        start = time.monotonic()
        results = run(scanner.scan_async(symbols, strategy="squeeze"))
        elapsed = time.monotonic() - start

        self.assertEqual(len(results), 5)
        # Sequential would take ~250ms (5 * 50ms). Concurrent should be ~50-100ms.
        # Use generous threshold to avoid flaky tests.
        self.assertLess(
            elapsed, 0.25, f"scan_async took {elapsed:.3f}s — likely not concurrent"
        )

    @patch("alpaca_trader.strategies.scanner.alpaca")
    def test_scan_async_respects_semaphore(self, mock_alpaca):
        """Verify the concurrency semaphore limits parallel calls."""
        active = {"count": 0, "max_seen": 0}
        lock = threading.Lock()

        def tracked_bars(symbol, period="1D", limit=60):
            with lock:
                active["count"] += 1
                active["max_seen"] = max(active["max_seen"], active["count"])
            time.sleep(0.03)
            with lock:
                active["count"] -= 1
            return make_ohlcv(60, seed=hash(symbol) % 1000)

        mock_alpaca.get_stock_bars_df.side_effect = tracked_bars

        scanner = WatchlistScanner()
        scanner.MAX_CONCURRENCY = 3

        symbols = [f"SYM{i}" for i in range(10)]
        results = run(scanner.scan_async(symbols, strategy="squeeze"))

        self.assertEqual(len(results), 10)
        # Max concurrent should not exceed our semaphore limit
        self.assertLessEqual(
            active["max_seen"],
            3,
            f"Max concurrent was {active['max_seen']}, expected <= 3",
        )

    @patch("alpaca_trader.strategies.scanner.alpaca")
    def test_scan_async_sorted_detected_first(self, mock_alpaca):
        """Results should be sorted: detected first, then alphabetical."""

        def bars_for(symbol, period="1D", limit=60):
            # Use different seeds to get different detection outcomes
            if symbol == "AAPL":
                return make_ohlcv(60, volatility=0.001, seed=1)  # Low vol = no squeeze
            return make_ohlcv(60, seed=42)

        mock_alpaca.get_stock_bars_df.side_effect = bars_for

        scanner = WatchlistScanner()
        results = run(scanner.scan_async(["ZZAA", "AAPL", "BBCC"], strategy="squeeze"))

        self.assertEqual(len(results), 3)
        # Verify sorting: detected ones first, then alphabetical within each group
        detected = [r for r in results if r.detected]
        not_detected = [r for r in results if not r.detected]
        all_sorted = detected + not_detected
        self.assertEqual([r.symbol for r in results], [r.symbol for r in all_sorted])

    @patch("alpaca_trader.strategies.scanner.alpaca")
    def test_scan_async_all_strategies(self, mock_alpaca):
        """scan_async works with all supported strategies."""
        mock_alpaca.get_stock_bars_df.return_value = make_ohlcv(60)

        scanner = WatchlistScanner()
        for strategy in ("squeeze", "bounce", "trend", "bb_rsi_reversal"):
            results = run(scanner.scan_async(["AAPL"], strategy=strategy))
            self.assertEqual(len(results), 1, f"Failed for strategy={strategy}")
            self.assertEqual(results[0].strategy, strategy)

    @patch("alpaca_trader.strategies.scanner.alpaca")
    def test_scan_async_insufficient_data(self, mock_alpaca):
        """scan_async handles insufficient data (< 21 bars)."""
        mock_alpaca.get_stock_bars_df.return_value = make_ohlcv(10)

        scanner = WatchlistScanner()
        results = run(scanner.scan_async(["AAPL"], strategy="squeeze"))
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].detected)
        self.assertIn("Insufficient", results[0].details.get("error", ""))


if __name__ == "__main__":
    unittest.main()
