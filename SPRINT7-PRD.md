# Sprint 7 PRD: Auto-Trading Engine with Risk Management

## Context
Tony wants the alpaca-trader to go from **alert-only** to **fully autonomous auto-trading** with proper exit strategies and risk management. Real money deployment is targeted for next week, so this must be bulletproof.

## Design Principles
1. **Capital preservation first** — never risk more than we can afford to lose
2. **Defined risk on every trade** — no open-ended exposure
3. **Mechanical exits** — emotions don't enter the equation
4. **Paper trade validation** — prove it works before real money

---

## Architecture

### New Module: `alpaca_trader/engine/`

```
engine/
├── __init__.py
├── auto_trader.py      # Core auto-trading orchestrator
├── position_manager.py # Exit strategy management & monitoring
├── risk_manager.py     # Position sizing, portfolio limits, risk checks
├── order_executor.py   # Smart order execution with retries
└── trade_journal.py    # Trade logging for analysis
```

---

## 1. Risk Manager (`risk_manager.py`)

### Position Sizing
- **Max risk per trade:** 2% of portfolio equity (configurable, default 2%)
  - On $100K account, max risk = $2,000 per trade
- **Position size calculation:**
  - For options: max_contracts = floor(max_risk / (option_premium * 100))
  - Never buy more than max_contracts regardless of signal strength
- **Max concurrent positions:** 5 (configurable)
- **Max allocation per symbol:** 10% of portfolio
- **Max total portfolio allocation:** 50% (keep 50% cash minimum)

### Pre-Trade Checks (Gate)
Before any trade executes, ALL must pass:
1. ✅ Market is open (no after-hours trading)
2. ✅ Sufficient buying power (with buffer)
3. ✅ Not exceeding max concurrent positions
4. ✅ Not exceeding max allocation per symbol
5. ✅ Not exceeding total portfolio allocation
6. ✅ Option has sufficient liquidity (bid-ask spread < 20% of mid price)
7. ✅ Option has sufficient open interest (> 100)
8. ✅ Option expiry is 14-45 days out (avoid extreme theta decay)
9. ✅ Not already holding a position in this underlying
10. ✅ Daily loss limit not exceeded (-5% of portfolio per day)

### Circuit Breakers
- **Daily loss limit:** -5% of portfolio value → halt all new trades for the day
- **Weekly loss limit:** -10% of portfolio value → halt all new trades, alert Tony
- **Max consecutive losses:** 3 → reduce position size by 50% for next 3 trades
- **Flash crash protection:** If any position drops >40% in <5 min, close immediately

---

## 2. Auto Trader (`auto_trader.py`)

### Signal-to-Trade Flow
```
Scanner detects signal
  → Risk Manager pre-trade checks
    → Option Selection (find best contract)
      → Order Executor places trade
        → Position Manager tracks & manages exits
          → Trade Journal logs everything
```

### Option Selection Logic
When a signal fires (e.g., bullish bounce on AAPL):
1. Get options chain for the underlying
2. Filter: calls only for bullish, puts only for bearish
3. Target expiry: 21-30 days out (sweet spot for theta/gamma)
4. Target strike: slightly OTM (delta 0.30-0.40 for better risk/reward)
5. Filter by liquidity: bid-ask spread < 15%, OI > 100, volume > 50
6. Select the contract with best liquidity at target delta
7. If no contract meets criteria → skip trade, log reason

### Trade Entry
- Use limit orders at the mid price (between bid and ask)
- If not filled in 60 seconds, adjust to 75% mark (closer to ask)
- If not filled in 120 seconds, cancel and skip
- Never use market orders for options (spreads are too wide)

---

## 3. Position Manager (`position_manager.py`)

### Exit Strategy (Every Position Gets ALL of These)

#### Stop-Loss (Mandatory)
- **Default:** -30% of entry price
- **Hard stop:** If option value drops to 30% of what we paid, sell immediately
- Example: Bought at $3.00 → stop-loss triggers at $2.10
- Implementation: Monitor every scan cycle (5 min), submit market sell if triggered

#### Take-Profit (Mandatory)
- **Default:** +50% of entry price (1.5:1 reward-to-risk ratio minimum)
- Example: Bought at $3.00 → take-profit triggers at $4.50
- Implementation: Submit limit sell order at take-profit price on entry

#### Trailing Stop (After Profit Threshold)
- **Activation:** Once position is +25% profitable
- **Trail distance:** 15% from peak
- Example: Bought at $3.00, hits $4.00 (+33%), trailing stop activates
  - Peak tracks at $4.00, trail at $3.40
  - Price goes to $5.00, trail moves to $4.25
  - Price drops to $4.20, sell triggered at ~$4.25
- **Overrides take-profit** once activated (lets winners run)

#### Time-Based Exit (Theta Protection)
- **7 DTE rule:** Close any position with ≤7 days to expiration
  - Options lose value exponentially in the last week
  - Check expiry on every scan cycle
- **Same-day exit:** If we enter and the position is down -15% by end of day, close it
  - Bad entries are best cut quickly

#### End-of-Day Flatten (Optional, Configurable)
- Default: OFF
- If enabled: close all positions 15 minutes before market close (3:45 PM ET)
- Prevents overnight gap risk
- Can be per-symbol or portfolio-wide

### Position Monitoring Loop
Every 5 minutes (aligned with scanner cron):
1. Fetch all open positions
2. For each position:
   a. Check stop-loss → if triggered, market sell immediately
   b. Check time-based exit (DTE ≤ 7) → if triggered, market sell
   c. Update trailing stop if applicable
   d. Check trailing stop → if triggered, market sell
   e. Check daily loss limit
3. Log all position states to trade journal

---

## 4. Order Executor (`order_executor.py`)

### Smart Execution
- Retry logic: 3 attempts with exponential backoff
- Order status tracking: pending → filled / partially_filled / cancelled / failed
- Partial fill handling: if only partially filled after 3 min, cancel remainder
- Error handling: API errors, insufficient funds, contract not found

### Order Types Used
- **Entry:** Limit order at mid price (with adjustment ladder)
- **Stop-loss:** Monitored locally (Alpaca doesn't support stop orders on options well)
  - Position Manager checks prices every 5 min and submits market sells
- **Take-profit:** Limit sell order placed immediately after entry fill
- **Trailing stop:** Monitored locally, market sell when triggered

---

## 5. Trade Journal (`trade_journal.py`)

### What Gets Logged (SQLite: `trade_journal` table)
- Trade ID, timestamp
- Symbol, underlying, option type, strike, expiry
- Strategy that generated the signal
- Signal details (strength, direction, indicators)
- Entry price, exit price, quantity
- P&L (dollar and percentage)
- Exit reason (stop_loss, take_profit, trailing_stop, time_exit, manual, circuit_breaker)
- Hold duration
- Pre-trade risk check results
- Notes/errors

### Analytics (CLI Commands)
- `alpaca-trader journal` → show recent trades
- `alpaca-trader journal stats` → win rate, avg P&L, best/worst trades, by strategy
- `alpaca-trader journal export` → CSV export

---

## 6. Configuration (`settings` table + CLI)

### New Settings
```
auto_trade.enabled = false          # Master switch (start disabled!)
auto_trade.max_risk_pct = 2.0       # Max risk per trade (% of equity)
auto_trade.max_positions = 5        # Max concurrent positions
auto_trade.max_allocation_pct = 50  # Max total portfolio in positions
auto_trade.max_per_symbol_pct = 10  # Max per symbol
auto_trade.stop_loss_pct = -30      # Stop-loss threshold
auto_trade.take_profit_pct = 50     # Take-profit threshold
auto_trade.trailing_stop_pct = 15   # Trailing stop distance
auto_trade.trailing_activate_pct = 25  # Trailing stop activation
auto_trade.target_dte_min = 14      # Min days to expiry
auto_trade.target_dte_max = 45      # Max days to expiry
auto_trade.target_delta_min = 0.25  # Min delta for option selection
auto_trade.target_delta_max = 0.45  # Max delta for option selection
auto_trade.daily_loss_limit_pct = -5  # Daily loss circuit breaker
auto_trade.weekly_loss_limit_pct = -10  # Weekly loss circuit breaker
auto_trade.flatten_eod = false      # Close all positions end-of-day
auto_trade.min_liquidity_oi = 100   # Min open interest
auto_trade.min_liquidity_volume = 50  # Min volume
auto_trade.max_spread_pct = 15      # Max bid-ask spread %
```

### CLI Commands
- `alpaca-trader auto status` → show auto-trading status, settings, circuit breaker state
- `alpaca-trader auto enable` → turn on auto-trading
- `alpaca-trader auto disable` → turn off auto-trading
- `alpaca-trader auto set <key> <value>` → update a setting

---

## 7. Integration with Existing Scanner

### Modified Flow
The `ScheduledScanner` gets updated:
```python
# Current: scan → queue alerts → deliver to Telegram
# New: scan → queue alerts → IF auto_trade.enabled: execute trades → deliver results to Telegram
```

The cron script (`cron_scan_and_deliver.py`) becomes:
```python
# 1. Run scanner (existing)
# 2. If auto_trade enabled AND signals found:
#    a. Run risk checks
#    b. Select options contracts
#    c. Place trades
#    d. Set up exit management
# 3. Check existing positions for exits
# 4. Report everything to Telegram
```

### Telegram Alert Format (Enhanced)
```
🟢 AUTO-TRADE EXECUTED
📊 AAPL — Bollinger Bounce (Bullish)
📈 Bought: AAPL 250418C00180000 (Apr 18 $180 Call)
💰 Entry: $3.20 × 3 contracts ($960)
🎯 Take-Profit: $4.80 (+50%)
🛑 Stop-Loss: $2.24 (-30%)
📅 Expiry: 24 DTE
⚖️ Risk: 0.96% of portfolio

---

📋 POSITION UPDATE
NVDA Apr 25 $140 Call: +22% ($2.80 → $3.42)
  ↳ Trailing stop activated, trail at $2.91

---

🔴 POSITION CLOSED
AMD Apr 11 $120 Call: -30% ($4.10 → $2.87)
  ↳ Stop-loss triggered
  ↳ Loss: -$369
```

---

## 8. Safety Features

### Master Kill Switch
- `auto_trade.enabled` must be explicitly set to `true`
- Starts as `false` — no auto-trading until Tony enables it
- Can be disabled via CLI, API, or Telegram command

### Paper Trading Lockout
- First 50 trades MUST be on paper account
- System counts trades in journal
- If `ALPACA_BASE_URL` contains "paper", no restrictions
- If live, check trade count >= 50 AND win rate > 40% before allowing

### Telegram Commands (Future)
- "Stop trading" → disables auto-trading
- "Status" → shows current positions, P&L, circuit breaker state
- "Close all" → closes all positions immediately

---

## 9. Implementation Order

1. **Risk Manager** — the foundation, everything depends on this
2. **Trade Journal** — need logging before we trade
3. **Order Executor** — smart order placement
4. **Position Manager** — exit strategy management
5. **Auto Trader** — orchestrator that ties it all together
6. **Scanner Integration** — connect to existing cron
7. **CLI Commands** — auto status/enable/disable/set, journal
8. **Testing** — paper trade for at least 2-3 days before real money

---

## 10. Success Criteria (Paper Trading Phase)

Before going live:
- [ ] 50+ paper trades executed
- [ ] Win rate > 40%
- [ ] No bugs in exit strategy execution
- [ ] Circuit breakers tested and working
- [ ] All risk checks passing correctly
- [ ] Telegram alerts delivering accurately
- [ ] Position Manager correctly managing all exit types
- [ ] No missed exits (every position has a defined exit path)

---

## Technical Notes
- All prices in USD, quantities as integers (option contracts)
- Use asyncio for concurrent position monitoring
- SQLite for trade journal (same DB as existing)
- All settings stored in `settings` table (existing infrastructure)
- Error handling: log and continue, never crash the scanner loop
- Timezone: all timestamps in UTC, display in ET for market context
