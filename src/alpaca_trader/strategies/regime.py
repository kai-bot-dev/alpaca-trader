"""Market regime detection — determines if conditions favor longs, shorts, or cash."""

from dataclasses import dataclass
from alpaca_trader.core import client as alpaca
from alpaca_trader.strategies.indicators import calc_rsi


@dataclass
class MarketRegime:
    regime: str  # 'bullish', 'bearish', 'neutral'
    spy_above_sma20: bool
    spy_rsi: float
    vix_level: float  # 0.0 if unavailable
    confidence: float  # 0-1


def get_market_regime() -> MarketRegime:
    """Check SPY trend to determine market regime."""
    try:
        df = alpaca.get_stock_bars_df("SPY", period="1D", limit=25)
        if len(df) < 20:
            return MarketRegime("neutral", True, 50.0, 0.0, 0.0)

        sma20 = df["close"].rolling(20).mean().iloc[-1]
        rsi = float(calc_rsi(df["close"], 14).iloc[-1])
        close = float(df["close"].iloc[-1])
        above_sma = close > sma20

        if above_sma and rsi > 45:
            regime = "bullish"
            confidence = min(1.0, (rsi - 45) / 25)
        elif not above_sma and rsi < 55:
            regime = "bearish"
            confidence = min(1.0, (55 - rsi) / 25)
        else:
            regime = "neutral"
            confidence = 0.3

        return MarketRegime(regime, above_sma, rsi, 0.0, confidence)
    except Exception:
        return MarketRegime("neutral", True, 50.0, 0.0, 0.0)
