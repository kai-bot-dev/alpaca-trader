"""Bollinger Band strategy modules for alpaca-trader."""

from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.squeeze import SqueezeDetector, SqueezeSignal
from alpaca_trader.strategies.bounce import BounceDetector, BounceSignal
from alpaca_trader.strategies.trend import TrendDetector, TrendSignal
from alpaca_trader.strategies.bb_rsi_reversal import BBRSIReversalDetector, BBRSIReversalSignal
from alpaca_trader.strategies.scanner import WatchlistScanner
from alpaca_trader.strategies.backtest import Backtester, BacktestResult

__all__ = [
    "BollingerBands",
    "SqueezeDetector", "SqueezeSignal",
    "BounceDetector", "BounceSignal",
    "TrendDetector", "TrendSignal",
    "BBRSIReversalDetector", "BBRSIReversalSignal",
    "WatchlistScanner",
    "Backtester", "BacktestResult",
]
