"""Watchlist scanner — runs a strategy across all symbols in the watchlist."""
import asyncio
import logging

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from alpaca_trader.core import client as alpaca
from alpaca_trader.core import database as db
from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.squeeze import SqueezeDetector
from alpaca_trader.strategies.bounce import BounceDetector
from alpaca_trader.strategies.trend import TrendDetector
from alpaca_trader.strategies.bb_rsi_reversal import BBRSIReversalDetector
from alpaca_trader.strategies.momentum import MomentumDetector

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    symbol: str
    strategy: str
    detected: bool
    direction: str
    strength: float
    details: dict
    timestamp: str


class WatchlistScanner:
    """Scans all watchlist symbols using a chosen strategy.

    Fetches historical bars from Alpaca, runs the strategy, and returns
    a list of Signal objects (one per symbol).

    Supports both sync and async usage:
    - ``scan()`` — synchronous (blocking), for CLI and backward compat
    - ``scan_async()`` — async, fetches bars concurrently via asyncio
    """

    # Maximum concurrent API calls to avoid rate-limiting
    MAX_CONCURRENCY: int = 5

    def scan(
        self,
        symbols: list[str],
        strategy: str,
        period: str = "1D",
        limit: int = 60,
    ) -> list[Signal]:
        """Run a strategy scan across all symbols (synchronous).

        Args:
            symbols: List of ticker symbols to scan
            strategy: One of 'squeeze', 'bounce', 'trend', 'bb_rsi_reversal'
            period: Bar timeframe ('1D', '1H', '15Min', '5Min', '1Min')
            limit: Number of historical bars to fetch per symbol

        Returns:
            List of Signal objects, sorted by detected=True first
        """
        logger.info("Starting scan", extra={"strategy": strategy, "symbol_count": len(symbols), "period": period})
        results = []
        for symbol in symbols:
            signal = self._scan_symbol(symbol, strategy, period, limit)
            results.append(signal)

        results.sort(key=lambda s: (not s.detected, s.symbol))
        detected = [r for r in results if r.detected]
        if detected:
            logger.info("Scan complete", extra={"strategy": strategy, "detected": len(detected), "total": len(results)})
        else:
            logger.debug("Scan complete — no signals", extra={"strategy": strategy, "total": len(results)})
        return results

    async def scan_async(
        self,
        symbols: list[str],
        strategy: str,
        period: str = "1D",
        limit: int = 60,
    ) -> list[Signal]:
        """Run a strategy scan across all symbols concurrently (async).

        Uses ``asyncio.to_thread`` to run blocking Alpaca API calls in a
        thread pool, bounded by a semaphore to avoid rate-limit issues.

        Args:
            symbols: List of ticker symbols to scan
            strategy: One of 'squeeze', 'bounce', 'trend', 'bb_rsi_reversal'
            period: Bar timeframe ('1D', '1H', '15Min', '5Min', '1Min')
            limit: Number of historical bars to fetch per symbol

        Returns:
            List of Signal objects, sorted by detected=True first
        """
        logger.info(
            "Starting async scan",
            extra={"strategy": strategy, "symbol_count": len(symbols), "period": period},
        )

        semaphore = asyncio.Semaphore(self.MAX_CONCURRENCY)

        async def _bounded_scan(sym: str) -> Signal:
            async with semaphore:
                return await asyncio.to_thread(
                    self._scan_symbol, sym, strategy, period, limit
                )

        results = await asyncio.gather(
            *[_bounded_scan(sym) for sym in symbols]
        )
        results = list(results)

        # Sort: detected signals first, then alphabetical
        results.sort(key=lambda s: (not s.detected, s.symbol))
        detected = [r for r in results if r.detected]
        if detected:
            logger.info(
                "Async scan complete",
                extra={"strategy": strategy, "detected": len(detected), "total": len(results)},
            )
        else:
            logger.debug(
                "Async scan complete — no signals",
                extra={"strategy": strategy, "total": len(results)},
            )
        return results

    def _scan_symbol(
        self,
        symbol: str,
        strategy: str,
        period: str,
        limit: int,
    ) -> Signal:
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            df = alpaca.get_stock_bars_df(symbol, period=period, limit=limit)
        except EnvironmentError:
            raise
        except Exception as e:
            logger.warning("Scan error", extra={"symbol": symbol, "strategy": strategy, "error": str(e)})
            return Signal(
                symbol=symbol, strategy=strategy, detected=False,
                direction="none", strength=0.0,
                details={"error": str(e)}, timestamp=timestamp,
            )

        if df.empty or len(df) < 15:
            return Signal(
                symbol=symbol, strategy=strategy, detected=False,
                direction="none", strength=0.0,
                details={"error": f"Insufficient data: {len(df)} bars"},
                timestamp=timestamp,
            )

        try:
            if strategy == "squeeze":
                detector = SqueezeDetector()
                sig = detector.detect(df)
                return Signal(
                    symbol=symbol, strategy=strategy,
                    detected=sig.detected, direction=sig.direction,
                    strength=sig.strength,
                    details={
                        "width": round(sig.width, 4),
                        "candle_outside": sig.candle_outside,
                    },
                    timestamp=timestamp,
                )
            elif strategy == "bounce":
                detector = BounceDetector()
                sig = detector.detect(df)
                return Signal(
                    symbol=symbol, strategy=strategy,
                    detected=sig.detected, direction=sig.direction,
                    strength=0.5 if sig.detected else 0.0,
                    details={
                        "band_touched": sig.band_touched,
                        "rsi": round(sig.rsi, 1),
                        "adx": round(sig.adx, 1),
                    },
                    timestamp=timestamp,
                )
            elif strategy == "trend":
                detector = TrendDetector()
                sig = detector.detect(df)
                return Signal(
                    symbol=symbol, strategy=strategy,
                    detected=sig.detected, direction=sig.direction,
                    strength=sig.strength,
                    details={"macd_hist": round(sig.macd_hist, 4)},
                    timestamp=timestamp,
                )
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
            elif strategy == "momentum":
                detector = MomentumDetector()
                sig = detector.detect(df)
                return Signal(
                    symbol=symbol, strategy=strategy,
                    detected=sig.detected, direction=sig.direction,
                    strength=sig.strength,
                    details={
                        "rsi": round(sig.rsi, 1),
                        "ema_fast": round(sig.ema_fast, 4),
                        "ema_slow": round(sig.ema_slow, 4),
                        "sma": round(sig.sma, 4),
                    },
                    timestamp=timestamp,
                )
            else:
                return Signal(
                    symbol=symbol, strategy=strategy, detected=False,
                    direction="none", strength=0.0,
                    details={"error": f"Unknown strategy: {strategy}"},
                    timestamp=timestamp,
                )
        except Exception as e:
            return Signal(
                symbol=symbol, strategy=strategy, detected=False,
                direction="none", strength=0.0,
                details={"error": str(e)}, timestamp=timestamp,
            )
