"""Bollinger Band + RSI Reversal strategy detection."""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from alpaca_trader.strategies.bollinger import BollingerBands
from alpaca_trader.strategies.indicators import calc_rsi, calc_volume_sma


@dataclass
class BBRSIReversalSignal:
    """Signal produced by BBRSIReversalDetector.

    Attributes:
        detected: True if a reversal signal is present.
        direction: 'long', 'short', or 'none'.
        strength: Confidence score from 0.0 to 1.0 based on confirmations.
        rsi: Current RSI value.
        bb_pct: %B value — where price sits relative to the bands.
        confirmations: List of confirmation names that were met.
        entry_price: Suggested entry price (current close).
        target_price: Mean-reversion target (middle band).
        stop_price: Stop-loss price (2x distance from entry to middle band,
            on the far side of entry).
        risk_reward: Absolute risk/reward ratio (target_dist / stop_dist).
    """

    detected: bool
    direction: str
    strength: float
    rsi: float
    bb_pct: float
    confirmations: list[str]
    entry_price: float
    target_price: float
    stop_price: float
    risk_reward: float


class BBRSIReversalDetector:
    """Detects Bollinger Band + RSI reversal (mean-reversion) signals.

    Identifies high-probability reversal points when price overextends beyond
    the Bollinger Bands while RSI is at an extreme. Entry is taken in the
    direction of the expected mean reversion (back toward the middle band).

    Entry criteria:
      Long:  close < lower BB  AND  RSI < 30  AND  >= 1 confirmation
      Short: close > upper BB  AND  RSI > 70  AND  >= 1 confirmation

    Confirmations (each adds 1/3 to strength score):
      - Extreme oversold/overbought: RSI < 20 (long) or RSI > 80 (short)
      - Volume spike: current volume > 1.2x 20-bar average
      - Candle pattern: green close after lower-band touch (long) or
                        red close after upper-band touch (short)
      - RSI divergence: price making new extreme but RSI pulling back

    Note: if RSI < 25 (long) or RSI > 75 (short), signal fires without
    requiring any confirmations — these are extremely oversold setups.

    Exit rules (used by backtester):
      - Primary:   price crosses middle band
      - Stop-loss: 2x the distance from entry to middle band
      - Time exit: after 10 bars if neither target nor stop hit

    Attributes:
        bb: BollingerBands instance.
        rsi_period: RSI calculation period (default 14).
        rsi_oversold: RSI threshold for long entry (default 30).
        rsi_overbought: RSI threshold for short entry (default 70).
        volume_spike_mult: Volume multiplier to qualify a spike (default 1.2).
        volume_sma_period: Period for volume SMA baseline (default 20).
        divergence_lookback: Number of bars to check for RSI divergence (default 5).

    Example:
        >>> from alpaca_trader.strategies.bb_rsi_reversal import BBRSIReversalDetector
        >>> detector = BBRSIReversalDetector()
        >>> signal = detector.detect(ohlcv_df)
        >>> if signal.detected:
        ...     print(f"{signal.direction} reversal — strength={signal.strength:.2f}")
        ...     print(f"Entry={signal.entry_price:.2f}, Target={signal.target_price:.2f}, Stop={signal.stop_price:.2f}")
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std_dev: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        volume_spike_mult: float = 1.2,
        volume_sma_period: int = 20,
        divergence_lookback: int = 5,
    ):
        self.bb = BollingerBands(period=bb_period, std_dev=bb_std_dev)
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.volume_spike_mult = volume_spike_mult
        self.volume_sma_period = volume_sma_period
        self.divergence_lookback = divergence_lookback

    def detect(self, df: pd.DataFrame) -> BBRSIReversalSignal:
        """Detect a BB+RSI reversal signal on the most recent bar.

        Args:
            df: OHLCV DataFrame with columns: open, high, low, close, volume.
                Minimum 25 rows required.

        Returns:
            BBRSIReversalSignal with detection details.
        """
        min_rows = max(self.bb.period, self.rsi_period, self.volume_sma_period) + 1
        no_signal = BBRSIReversalSignal(
            detected=False, direction="none", strength=0.0,
            rsi=50.0, bb_pct=0.5, confirmations=[],
            entry_price=0.0, target_price=0.0, stop_price=0.0, risk_reward=0.0,
        )

        if len(df) < min_rows:
            return no_signal

        enriched = self.bb.calc(df)
        rsi_series = calc_rsi(df["close"], self.rsi_period)

        latest = enriched.iloc[-1]
        close = float(latest["close"])
        upper = float(latest["bb_upper"])
        lower = float(latest["bb_lower"])
        middle = float(latest["bb_middle"])
        bb_pct = float(latest["bb_pct"]) if not pd.isna(latest["bb_pct"]) else 0.5
        rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0

        # Determine primary condition
        if close < lower and rsi < self.rsi_oversold:
            direction = "long"
        elif close > upper and rsi > self.rsi_overbought:
            direction = "short"
        else:
            return BBRSIReversalSignal(
                detected=False, direction="none", strength=0.0,
                rsi=rsi, bb_pct=bb_pct, confirmations=[],
                entry_price=close, target_price=middle, stop_price=0.0, risk_reward=0.0,
            )

        # Gather confirmations
        confirmations: list[str] = []

        # Extreme RSI fires as its own confirmation (RSI < 20 long, > 80 short)
        if direction == "long" and rsi < 20:
            confirmations.append("extreme_oversold")
        elif direction == "short" and rsi > 80:
            confirmations.append("extreme_overbought")

        if self._check_volume_spike(df):
            confirmations.append("volume_spike")

        if self._check_candle_pattern(df, direction):
            confirmations.append("candle_pattern")

        if self._check_rsi_divergence(df, rsi_series, direction):
            confirmations.append("rsi_divergence")

        # If RSI is extremely oversold/overbought, bypass the confirmation requirement
        extreme_rsi = (direction == "long" and rsi < 25) or (direction == "short" and rsi > 75)
        if not confirmations and not extreme_rsi:
            return BBRSIReversalSignal(
                detected=False, direction="none", strength=0.0,
                rsi=rsi, bb_pct=bb_pct, confirmations=[],
                entry_price=close, target_price=middle, stop_price=0.0, risk_reward=0.0,
            )

        # Strength: confirmations / 3, minimum 0.25 when bypassing confirmation check
        raw_strength = len(confirmations) / 3.0
        strength = raw_strength if confirmations else 0.25
        entry_price, target_price, stop_price, risk_reward = self._calc_targets(
            close, middle, direction
        )

        return BBRSIReversalSignal(
            detected=True,
            direction=direction,
            strength=round(strength, 4),
            rsi=rsi,
            bb_pct=bb_pct,
            confirmations=confirmations,
            entry_price=entry_price,
            target_price=target_price,
            stop_price=stop_price,
            risk_reward=risk_reward,
        )

    def _check_volume_spike(self, df: pd.DataFrame, threshold: float | None = None) -> bool:
        """Return True if the latest bar has a volume spike vs 20-bar SMA.

        Args:
            df: OHLCV DataFrame.
            threshold: Override for volume_spike_mult.

        Returns:
            bool
        """
        if "volume" not in df.columns:
            return False
        mult = threshold if threshold is not None else self.volume_spike_mult
        vol_sma = calc_volume_sma(df["volume"], self.volume_sma_period)
        if pd.isna(vol_sma.iloc[-1]) or vol_sma.iloc[-1] == 0:
            return False
        return float(df["volume"].iloc[-1]) > mult * float(vol_sma.iloc[-1])

    def _check_candle_pattern(self, df: pd.DataFrame, direction: str) -> bool:
        """Return True if the latest candle matches the expected reversal pattern.

        Long: green candle (close > open) — exhaustion of selling.
        Short: red candle (close < open) — exhaustion of buying.

        Args:
            df: OHLCV DataFrame with 'open' and 'close' columns.
            direction: 'long' or 'short'.

        Returns:
            bool
        """
        if "open" not in df.columns:
            return False
        latest_open = float(df["open"].iloc[-1])
        latest_close = float(df["close"].iloc[-1])
        if direction == "long":
            return latest_close > latest_open
        else:
            return latest_close < latest_open

    def _check_rsi_divergence(
        self,
        df: pd.DataFrame,
        rsi_series: pd.Series,
        direction: str,
        lookback: int | None = None,
    ) -> bool:
        """Return True if bullish or bearish RSI divergence is present.

        Bullish divergence (long): price makes a lower low but RSI makes a
        higher low in the last N bars — selling momentum is weakening.

        Bearish divergence (short): price makes a higher high but RSI makes a
        lower high — buying momentum is weakening.

        Args:
            df: OHLCV DataFrame.
            rsi_series: Pre-calculated RSI series aligned to df.
            direction: 'long' or 'short'.
            lookback: Number of previous bars to compare against (default:
                self.divergence_lookback).

        Returns:
            bool
        """
        n = lookback if lookback is not None else self.divergence_lookback
        if len(df) < n + 1:
            return False

        close = df["close"]
        prev_closes = close.iloc[-(n + 1):-1]
        prev_rsi = rsi_series.iloc[-(n + 1):-1]

        current_close = float(close.iloc[-1])
        current_rsi = float(rsi_series.iloc[-1])

        if pd.isna(current_rsi) or prev_rsi.isna().all():
            return False

        prev_closes_valid = prev_closes.dropna()
        prev_rsi_valid = prev_rsi.dropna()

        if len(prev_closes_valid) == 0 or len(prev_rsi_valid) == 0:
            return False

        if direction == "long":
            # Price lower low, RSI higher low
            price_lower_low = current_close < float(prev_closes_valid.min())
            rsi_higher_low = current_rsi > float(prev_rsi_valid.min())
            return price_lower_low and rsi_higher_low
        else:
            # Price higher high, RSI lower high
            price_higher_high = current_close > float(prev_closes_valid.max())
            rsi_lower_high = current_rsi < float(prev_rsi_valid.max())
            return price_higher_high and rsi_lower_high

    def _calc_targets(
        self,
        close: float,
        middle: float,
        direction: str,
    ) -> tuple[float, float, float, float]:
        """Calculate entry, target, and stop-loss prices.

        Target is the middle band. Stop is 2x the distance from entry to middle
        band, placed on the far side of the entry.

        Args:
            close: Current closing price (entry price).
            middle: Middle Bollinger Band (target).
            direction: 'long' or 'short'.

        Returns:
            Tuple of (entry_price, target_price, stop_price, risk_reward).
            risk_reward is target_dist / stop_dist, or 0.0 if stop_dist == 0.
        """
        entry_price = close
        target_price = middle
        target_dist = abs(target_price - entry_price)
        stop_dist = 2.0 * target_dist

        if direction == "long":
            stop_price = entry_price - stop_dist
        else:
            stop_price = entry_price + stop_dist

        risk_reward = (target_dist / stop_dist) if stop_dist > 0 else 0.0

        return (
            round(entry_price, 4),
            round(target_price, 4),
            round(stop_price, 4),
            round(risk_reward, 4),
        )
