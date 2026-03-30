# Sprint 8 PRD — Bollinger Band + RSI Reversal Strategy

## Goal
Build a production-grade **Bollinger Band + RSI reversal** strategy that identifies trend change points when price breaks outside the Bollinger Bands, confirmed by RSI extremes. This is the primary money-making strategy for the alpaca-trader system.

## Background
The existing strategies (squeeze, bounce, trend) are good building blocks but:
- `bounce` requires ADX < 25 (range-bound only) — too restrictive
- `squeeze` is breakout-focused, not reversal
- `trend` follows existing trends, doesn't catch reversals

Tony wants a strategy that catches the **turning points** — when price overextends beyond the Bollinger Bands and is about to reverse. RSI confirms the extremes.

## Strategy Logic: BB + RSI Reversal

### Core Concept
When price closes outside the Bollinger Bands AND RSI is at an extreme, the probability of a mean reversion (reversal) is high. We enter in the direction of the expected reversal.

### Entry Signals

**LONG (Bullish Reversal):**
1. Price closes BELOW the lower Bollinger Band (20-period SMA, 2 std dev)
2. RSI(14) is below 30 (oversold)
3. Confirmation: at least one of:
   - Volume spike (current volume > 1.5x 20-bar average) — panic selling exhaustion
   - Bullish candle pattern: current close > current open (green candle after touching lower band)
   - RSI divergence: price making lower low but RSI making higher low (last 5 bars)
4. Strength score (0.0-1.0) based on how many confirmations are met

**SHORT (Bearish Reversal):**
1. Price closes ABOVE the upper Bollinger Band
2. RSI(14) is above 70 (overbought)
3. Confirmation: at least one of:
   - Volume spike
   - Bearish candle: current close < current open (red candle after touching upper band)
   - RSI divergence: price making higher high but RSI making lower high
4. Strength score based on confirmations

### Exit Rules
- **Primary exit:** Price crosses back through the middle band (20-period SMA) — take profit at the mean
- **Stop loss:** Price moves further against the trade by 2x the distance from entry to the middle band
- **Time-based exit:** Close after 10 bars if neither target nor stop is hit
- **Trailing stop:** Once price moves 50%+ toward middle band, trail a stop at the entry band

### Risk Parameters
- Position size: Based on RiskManager (max 10% of portfolio per position)
- Max concurrent positions from this strategy: 5
- Only trade during market hours
- Minimum bar count: 25 (to have enough data for BB + RSI)

## Implementation Plan

### 1. New Strategy File: `src/alpaca_trader/strategies/bb_rsi_reversal.py`

Create a new `BBRSIReversalDetector` class with:

```python
@dataclass
class BBRSIReversalSignal:
    detected: bool
    direction: str          # 'long', 'short', 'none'
    strength: float         # 0.0-1.0
    rsi: float             # Current RSI value
    bb_pct: float          # %B value (where price is relative to bands)
    confirmations: list[str]  # Which confirmations were met
    entry_price: float     # Suggested entry (current close)
    target_price: float    # Middle band (mean reversion target)
    stop_price: float      # Stop loss price
    risk_reward: float     # Risk/reward ratio
```

Key methods:
- `detect(df: pd.DataFrame) -> BBRSIReversalSignal` — main detection
- `_check_rsi_divergence(df, direction, lookback=5) -> bool` — RSI divergence check
- `_check_volume_spike(df, threshold=1.5) -> bool` — volume confirmation
- `_check_candle_pattern(df, direction) -> bool` — candle pattern check
- `_calc_targets(close, middle, direction) -> tuple[float, float, float]` — entry/target/stop

Reuse `_calc_rsi` from `bounce.py` (or extract to a shared `indicators.py` module).

### 2. Shared Indicators: `src/alpaca_trader/strategies/indicators.py`

Extract common indicator calculations to avoid duplication:
- `calc_rsi(close, period=14) -> pd.Series`
- `calc_adx(df, period=14) -> pd.Series`
- `calc_macd(close, fast=12, slow=26, signal=9) -> tuple`
- `calc_atr(df, period=14) -> pd.Series` (new — useful for stops)
- `calc_volume_sma(volume, period=20) -> pd.Series`

Update `bounce.py` and `trend.py` to import from `indicators.py` instead of having private copies.

### 3. Integrate into Scanner (`scanner.py`)

Add `"bb_rsi_reversal"` as a strategy option in `WatchlistScanner._scan_symbol()`:

```python
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
```

### 4. Integrate into Backtester (`backtest.py`)

Add `bb_rsi_reversal` to `_get_signal()` and `_check_exit()`:
- Entry: use `BBRSIReversalDetector.detect()`
- Exit: use the exit rules defined above (middle band cross, stop loss, time exit)

### 5. Integrate into ScheduledScanner (`alerts/scanner.py`)

Add `"bb_rsi_reversal"` to the strategy loop in `ScheduledScanner.run()`.

### 6. Update CLI (`cli.py`)

- Update `scan` command's valid_strategies to include `"bb_rsi_reversal"`
- Update `backtest` command's valid_strategies
- Update help text

### 7. Update `__init__.py`

Export `BBRSIReversalDetector` and `BBRSIReversalSignal`.

### 8. Tests

Create `tests/test_bb_rsi_reversal.py`:
- Test signal detection with synthetic data (price below lower BB + RSI < 30)
- Test no signal when conditions aren't met
- Test strength scoring with different confirmation counts
- Test target/stop price calculations
- Test RSI divergence detection
- Test edge cases (insufficient data, missing columns)

Also create `tests/test_indicators.py`:
- Test RSI calculation against known values
- Test ATR calculation
- Test volume SMA

### 9. Alert Integration

Add a new alert type `"bb_rsi_reversal"` to the alert system so users can get notified when this specific strategy triggers.

## File Changes Summary

| File | Action |
|------|--------|
| `src/alpaca_trader/strategies/bb_rsi_reversal.py` | **CREATE** — new strategy |
| `src/alpaca_trader/strategies/indicators.py` | **CREATE** — shared indicators |
| `src/alpaca_trader/strategies/__init__.py` | **EDIT** — add exports |
| `src/alpaca_trader/strategies/scanner.py` | **EDIT** — add bb_rsi_reversal |
| `src/alpaca_trader/strategies/backtest.py` | **EDIT** — add bb_rsi_reversal |
| `src/alpaca_trader/strategies/bounce.py` | **EDIT** — import from indicators.py |
| `src/alpaca_trader/strategies/trend.py` | **EDIT** — import from indicators.py |
| `src/alpaca_trader/alerts/scanner.py` | **EDIT** — add bb_rsi_reversal to scan loop |
| `src/alpaca_trader/cli.py` | **EDIT** — add bb_rsi_reversal to valid strategies |
| `tests/test_bb_rsi_reversal.py` | **CREATE** — strategy tests |
| `tests/test_indicators.py` | **CREATE** — indicator tests |

## Success Criteria
1. `alpaca-trader scan --strategy bb_rsi_reversal` works and shows signals
2. `alpaca-trader backtest AAPL --strategy bb_rsi_reversal --start 2025-01-01 --end 2025-12-31` shows trades
3. All existing tests still pass
4. New tests pass with >90% coverage on new code
5. Strategy produces signals with meaningful strength scores and risk/reward ratios
6. Exit logic properly handles stop loss, target, and time-based exits

## Important Implementation Notes
- Use the existing BollingerBands class from `bollinger.py` (20-period, 2 std dev defaults)
- RSI period: 14 (standard)
- All new code must have docstrings and type hints
- Follow the same code style as existing strategies (dataclass signals, detector classes)
- The strategy should work with daily (1D), hourly (1H), and 15-minute (15Min) timeframes
- Don't break any existing functionality
