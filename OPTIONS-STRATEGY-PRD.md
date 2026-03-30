# Options Trading Strategy PRD — Sprint 9

## Goal
Replace stock-based auto-trading with an options-first strategy. When the scanner detects a signal (bounce, bb_rsi_reversal, squeeze), instead of buying shares, buy options contracts with proper Greeks filtering, strike selection, and exit management.

## Current State
- Scanner detects signals on underlying stocks (bounce, bb_rsi_reversal, squeeze, trend)
- Auto-trader buys shares via market orders
- Options infrastructure exists: chain lookup, spreads, multi-leg orders, Greeks via snapshots
- Paper trading account: ~$111K equity

## Strategy Design

### 1. Entry Strategy: Directional Calls/Puts on Mean Reversion Signals

**When scanner detects a LONG signal (oversold bounce):**
- Buy **call options** on the underlying
- Strike: slightly OTM to ATM (delta 0.35-0.55 range — the "sweet spot")
- Expiry: 7-14 DTE (days to expiration) — enough theta runway, not too expensive
  - Prefer weekly options (Friday expiry) 
  - If < 5 DTE available, skip to next week
- Max contracts per trade: sized so total premium <= 2% of portfolio ($2,200)
- Entry filter: only buy if IV rank < 50% (don't buy expensive options)

**When scanner detects a SHORT signal (overbought):**
- Buy **put options** on the underlying
- Same strike/expiry logic but inverted (delta -0.35 to -0.55)

### 2. Greeks Filters (Pre-Trade)

Before placing any options trade, verify:
- **Delta:** 0.30-0.55 for calls, -0.55 to -0.30 for puts (directional exposure without overpaying)
- **Theta:** Skip if theta decay > 5% of option price per day (too expensive to hold)
- **IV:** Prefer IV < 50% rank. If IV > 70%, consider selling premium instead (future enhancement)
- **Open Interest:** Minimum 10 OI for liquidity (avoid illiquid strikes)
- **Bid-Ask Spread:** Max 15% of mid price (avoid wide spreads eating profits)
- **Gamma:** Track but don't filter — useful for understanding P&L acceleration

### 3. Strike Selection Algorithm

```
Given: underlying_price, signal_direction, available_chain

1. Filter chain to: expiry 7-14 DTE, correct type (call/put)
2. For each contract, fetch snapshot (greeks, bid/ask)
3. Filter by: delta range, OI >= 10, spread <= 15% of mid
4. Score remaining contracts:
   - Delta proximity to 0.45: weight 40%
   - Lower theta decay: weight 30% 
   - Higher OI (liquidity): weight 20%
   - Tighter spread: weight 10%
5. Select top-scoring contract
6. If no contracts pass filters, SKIP trade (log reason)
```

### 4. Position Sizing

- **Max premium per trade:** 2% of portfolio value (~$2,200)
- **Max total options exposure:** 10% of portfolio (~$11K in premiums)
- **Max concurrent option positions:** 5
- **Contract quantity:** floor(max_premium / (ask_price * 100))
  - Minimum 1 contract
  - Maximum 10 contracts per position

### 5. Exit Rules

**Take Profit:**
- Primary: +50% gain on premium (if bought for $3.00, sell at $4.50)
- Secondary: underlying reaches middle Bollinger Band (mean reversion target)

**Stop Loss:**
- Hard stop: -40% of premium (if bought for $3.00, stop at $1.80)
- Time stop: close if < 3 DTE remaining (avoid last-day theta crush)

**Trailing Stop:**
- Activate at +30% gain
- Trail at 20% from high-water mark of option price

**Exit Priority Order:**
1. Time stop (< 3 DTE) — always close, no exceptions
2. Hard stop (-40%)
3. Trailing stop (if activated)
4. Take profit (+50%)
5. Mean reversion target reached

### 6. Risk Management

- Never sell naked options (only buying calls/puts for now)
- Maximum 2% of portfolio at risk per trade
- If 3 consecutive losers, pause for 1 hour
- Circuit breaker: if daily options P&L < -5% of portfolio, stop trading for the day
- Track: win rate, avg gain, avg loss, profit factor, theta burn vs realized

## Implementation Plan

### New Files
- `src/alpaca_trader/engine/options_trader.py` — Options-specific auto-trader
- `src/alpaca_trader/engine/strike_selector.py` — Strike selection + scoring
- `src/alpaca_trader/engine/options_position_manager.py` — Options exit rules

### Modified Files  
- `src/alpaca_trader/engine/auto_trader.py` — Add `trading_mode: str = "options" | "stocks"` param
- `src/alpaca_trader/engine/trade_journal.py` — Add option-specific fields (strike, expiry, premium, greeks at entry)
- `src/alpaca_trader/core/database.py` — Extend journal schema for options trades
- `src/alpaca_trader/cli.py` — Add `auto mode options/stocks` command, `--mode` flag to `auto run`
- `scripts/auto_trade.py` — Pass trading mode from settings

### CLI Commands
- `alpaca-trader auto mode options` — Switch to options trading
- `alpaca-trader auto mode stocks` — Switch back to stocks
- `alpaca-trader auto status` — Show current mode + options-specific stats
- `alpaca-trader chain SYMBOL --smart` — Show chain with our scoring applied

### Database Schema Additions
```sql
ALTER TABLE trade_journal ADD COLUMN option_symbol TEXT;
ALTER TABLE trade_journal ADD COLUMN option_type TEXT;  -- 'call' or 'put'
ALTER TABLE trade_journal ADD COLUMN strike_price REAL;
ALTER TABLE trade_journal ADD COLUMN expiry_date TEXT;
ALTER TABLE trade_journal ADD COLUMN premium_paid REAL;
ALTER TABLE trade_journal ADD COLUMN contracts INTEGER;
ALTER TABLE trade_journal ADD COLUMN delta_at_entry REAL;
ALTER TABLE trade_journal ADD COLUMN theta_at_entry REAL;
ALTER TABLE trade_journal ADD COLUMN iv_at_entry REAL;
```

### Flow: Signal -> Options Trade

```
1. Scanner detects signal (e.g., GOOGL long bounce, RSI=17)
2. OptionsTrader receives signal
3. StrikeSelector:
   a. Fetch options chain for GOOGL calls, expiry 7-14 DTE
   b. Fetch snapshots for Greeks on matching contracts
   c. Filter by delta, theta, OI, spread
   d. Score and select best contract
4. RiskManager checks: portfolio exposure, position count, recent P&L
5. If approved: place market order for N contracts
6. Log to journal with full Greeks snapshot
7. OptionsPositionManager monitors:
   - Check option price every 5 min
   - Apply exit rules (profit, loss, time, trailing)
   - Execute exit when triggered
8. Alert to Telegram on entry AND exit
```

## Testing Strategy
- Unit tests for StrikeSelector scoring
- Unit tests for options exit rules  
- Integration test: mock chain -> mock trade -> verify journal entry
- Paper trade validation: run for 50 trades before any live consideration

## Success Metrics
- Win rate > 50%
- Average winner > average loser (profit factor > 1.5)
- Max drawdown per week < 5% of portfolio
- Theta burn < 20% of total losses
