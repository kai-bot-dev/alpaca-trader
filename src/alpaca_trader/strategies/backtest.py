"""Backtester — simulates entries/exits based on Bollinger Band strategy signals."""

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from alpaca_trader.core import client as alpaca
from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.squeeze import SqueezeDetector
from alpaca_trader.strategies.bounce import BounceDetector
from alpaca_trader.strategies.trend import TrendDetector
from alpaca_trader.strategies.bb_rsi_reversal import BBRSIReversalDetector


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    direction: str  # 'long' or 'short'
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return: float  # Percentage
    win_rate: float  # 0.0–1.0
    sharpe: float
    max_drawdown: float  # Percentage (negative)
    trades: list[Trade] = field(default_factory=list)
    num_trades: int = 0


class Backtester:
    """Simulates strategy entries and exits on historical price data.

    Entry signals come from the strategy detector.
    Exit rules per strategy:
      - squeeze: exit on close back inside bands
      - bounce: exit when price crosses middle band
      - trend: exit when price crosses middle band
    """

    def run(
        self,
        symbol: str,
        strategy: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 10000.0,
        period: str = "1D",
    ) -> BacktestResult:
        """Run backtest.

        Args:
            symbol: Ticker symbol
            strategy: 'squeeze', 'bounce', or 'trend'
            start_date: ISO date string (YYYY-MM-DD)
            end_date: ISO date string (YYYY-MM-DD)
            initial_capital: Starting capital in USD
            period: Bar timeframe (default '1D')

        Returns:
            BacktestResult with trade details and summary statistics
        """
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)

        df = alpaca.get_stock_bars_df(
            symbol, period=period, limit=500, start=start_dt, end=end_dt
        )

        empty_result = BacktestResult(
            symbol=symbol,
            strategy=strategy,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            final_capital=initial_capital,
            total_return=0.0,
            win_rate=0.0,
            sharpe=0.0,
            max_drawdown=0.0,
            trades=[],
            num_trades=0,
        )

        if df.empty or len(df) < 25:
            empty_result.trades = []
            return empty_result

        # Compute signals over entire dataset using rolling window
        trades = self._simulate(df, strategy, initial_capital)

        if not trades:
            return empty_result

        # Simpler capital tracking: each trade invests full capital, compounds
        capital = initial_capital
        for t in trades:
            capital *= 1 + t.pnl_pct / 100

        wins = [t for t in trades if t.pnl > 0]
        win_rate = len(wins) / len(trades) if trades else 0.0
        total_return = (capital - initial_capital) / initial_capital * 100

        # Sharpe ratio (annualized, assuming 252 trading days)
        returns = [t.pnl_pct / 100 for t in trades]
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = (np.mean(returns) / np.std(returns)) * math.sqrt(252)
        else:
            sharpe = 0.0

        # Max drawdown
        equity = initial_capital
        peak = initial_capital
        max_dd = 0.0
        for t in trades:
            equity *= 1 + t.pnl_pct / 100
            peak = max(peak, equity)
            dd = (equity - peak) / peak * 100
            max_dd = min(max_dd, dd)

        return BacktestResult(
            symbol=symbol,
            strategy=strategy,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            final_capital=round(capital, 2),
            total_return=round(total_return, 2),
            win_rate=round(win_rate, 4),
            sharpe=round(sharpe, 3),
            max_drawdown=round(max_dd, 2),
            trades=trades,
            num_trades=len(trades),
        )

    def _simulate(
        self, df: pd.DataFrame, strategy: str, initial_capital: float
    ) -> list[Trade]:
        """Walk through bars, generating entry/exit signals."""
        trades = []
        in_trade = False
        entry_idx = None
        entry_price = None
        direction = "none"
        entry_middle = None  # middle band at entry (used by bb_rsi_reversal exit)
        min_rows = 25

        for i in range(min_rows, len(df)):
            window = df.iloc[: i + 1]
            latest = df.iloc[i]
            close = float(latest["close"])
            ts = str(latest.name)

            if not in_trade:
                # Check for entry signal
                sig_detected, sig_direction = self._get_signal(window, strategy)
                if sig_detected and sig_direction in ("long", "short"):
                    in_trade = True
                    entry_idx = i
                    entry_price = close
                    direction = sig_direction
                    # Record middle band at entry for bb_rsi_reversal stop calc
                    if strategy == "bb_rsi_reversal":
                        try:
                            enriched = BollingerBands().calc(window)
                            entry_middle = float(enriched.iloc[-1]["bb_middle"])
                        except Exception:
                            entry_middle = None
                    else:
                        entry_middle = None
            else:
                # Check for exit
                bars_in_trade = i - entry_idx
                should_exit = self._check_exit(
                    window,
                    strategy,
                    direction,
                    entry_price=entry_price,
                    entry_middle=entry_middle,
                    bars_in_trade=bars_in_trade,
                )
                if should_exit or i == len(df) - 1:
                    exit_price = close
                    pnl_pct = (
                        (exit_price - entry_price) / entry_price * 100
                        if direction == "long"
                        else (entry_price - exit_price) / entry_price * 100
                    )
                    pnl = (
                        (exit_price - entry_price)
                        if direction == "long"
                        else (entry_price - exit_price)
                    )

                    trades.append(
                        Trade(
                            entry_date=str(df.index[entry_idx]),
                            exit_date=ts,
                            direction=direction,
                            entry_price=round(entry_price, 4),
                            exit_price=round(exit_price, 4),
                            pnl=round(pnl, 4),
                            pnl_pct=round(pnl_pct, 4),
                        )
                    )
                    in_trade = False
                    entry_idx = None
                    entry_price = None
                    entry_middle = None
                    direction = "none"

        return trades

    def _get_signal(self, df: pd.DataFrame, strategy: str) -> tuple[bool, str]:
        """Get entry signal from strategy detector."""
        try:
            if strategy == "squeeze":
                sig = SqueezeDetector().detect(df)
                return sig.detected and sig.candle_outside, sig.direction
            elif strategy == "bounce":
                sig = BounceDetector().detect(df)
                return sig.detected, sig.direction
            elif strategy == "trend":
                sig = TrendDetector().detect(df)
                return sig.detected, sig.direction
            elif strategy == "bb_rsi_reversal":
                sig = BBRSIReversalDetector().detect(df)
                return sig.detected, sig.direction
        except Exception:
            pass
        return False, "none"

    def _check_exit(
        self,
        df: pd.DataFrame,
        strategy: str,
        direction: str,
        entry_price: float | None = None,
        entry_middle: float | None = None,
        bars_in_trade: int = 0,
    ) -> bool:
        """Check exit condition based on strategy rules.

        Args:
            df: Rolling window DataFrame up to current bar.
            strategy: Strategy name.
            direction: 'long' or 'short'.
            entry_price: Price at entry (used for bb_rsi_reversal stop).
            entry_middle: Middle band at entry (used for bb_rsi_reversal stop).
            bars_in_trade: Number of bars since entry (for time exit).

        Returns:
            True if exit condition is met.
        """
        try:
            bb = BollingerBands()
            enriched = bb.calc(df)
            latest = enriched.iloc[-1]
            close = float(latest["close"])
            middle = float(latest["bb_middle"])
            upper = float(latest["bb_upper"])
            lower = float(latest["bb_lower"])

            if strategy == "squeeze":
                # Exit when price returns inside bands
                if direction == "long":
                    return close < upper
                else:
                    return close > lower

            elif strategy in ("bounce", "trend"):
                # Exit at middle band cross
                if direction == "long":
                    return close >= middle
                else:
                    return close <= middle

            elif strategy == "bb_rsi_reversal":
                # Primary: price crosses middle band (take profit)
                if direction == "long" and close >= middle:
                    return True
                if direction == "short" and close <= middle:
                    return True

                # Time-based exit: 10 bars
                if bars_in_trade >= 10:
                    return True

                # Stop loss: 2x the distance from entry to middle band
                if entry_price is not None and entry_middle is not None:
                    target_dist = abs(entry_middle - entry_price)
                    stop_dist = 2.0 * target_dist
                    if direction == "long":
                        stop_price = entry_price - stop_dist
                        if close <= stop_price:
                            return True
                    else:
                        stop_price = entry_price + stop_dist
                        if close >= stop_price:
                            return True

        except Exception:
            pass
        return False
