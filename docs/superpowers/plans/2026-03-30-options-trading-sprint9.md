# Options Trading Sprint 9 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an options-first auto-trading path that buys calls/puts on scanner signals with Greeks filtering, strike scoring, and options-specific exit management.

**Architecture:** Parallel path to stocks — same scanner, same CLI surface, mode stored in DB settings key `trading_mode`. StrikeSelector filters/scores the option chain; OptionsPositionManager applies DTE/hard-stop/trailing/take-profit exit rules; OptionsTrader orchestrates the cycle.

**Tech Stack:** Alpaca SDK (`get_option_chain`, `get_option_snapshots`, `place_market_order`), aiosqlite, Typer CLI, pytest.

---

### File Map

| File | Status | Responsibility |
|------|--------|---------------|
| `src/alpaca_trader/engine/strike_selector.py` | Create | Filter + score option chain, return best contract dict |
| `src/alpaca_trader/engine/options_position_manager.py` | Create | Options exit rules with DTE/hard-stop/trailing/take-profit |
| `src/alpaca_trader/engine/options_trader.py` | Create | Orchestrator: scan → strike → risk → execute → journal |
| `src/alpaca_trader/core/database.py` | Modify | ALTER TABLE migration for 9 option columns |
| `src/alpaca_trader/engine/trade_journal.py` | Modify | log_entry/log_exit accept option kwargs |
| `src/alpaca_trader/cli.py` | Modify | `auto mode options/stocks`, update status/run |
| `scripts/auto_trade.py` | Modify | Read mode setting, dispatch OptionsTrader |
| `tests/test_strike_selector.py` | Create | Unit tests for scoring and filtering |
| `tests/test_options_position_manager.py` | Create | Unit tests for exit rules |

---

### Task 1: StrikeSelector

**Files:** Create `src/alpaca_trader/engine/strike_selector.py`

Key logic:
- Filter: `option_type` matches direction, DTE 5–14, abs(delta) 0.30–0.55, OI >= 10, spread_pct <= 15%
- Score: 40% delta proximity to 0.45, 30% theta (lower burn), 20% OI (normalized), 10% spread
- contracts_to_buy = floor(portfolio_value * 0.02 / (ask * 100)), capped 1–10

### Task 2: OptionsPositionManager

**Files:** Create `src/alpaca_trader/engine/options_position_manager.py`

Exit priority (highest to lowest):
1. Time stop: expiry DTE < 3
2. Hard stop: pnl_pct <= -0.40
3. Trailing stop: activate at +30%, trail 20% from HWM option price
4. Take profit: pnl_pct >= +0.50

### Task 3: OptionsTrader

**Files:** Create `src/alpaca_trader/engine/options_trader.py`

run_cycle() steps:
1. Guard: enabled + market open + no circuit breaker
2. Fetch account (portfolio_value, cash)
3. Fetch open option positions, check exits
4. Scan watchlist signals
5. For each signal: get_option_chain → StrikeSelector.select_contract → risk check → place_market_order → journal

### Task 4: Database migration

**Files:** Modify `src/alpaca_trader/core/database.py`

Add to `init_db()` after existing CREATE TABLE: 9 ALTER TABLE statements in try/except blocks (migration-safe — skip if column exists).

### Task 5: TradeJournal option fields

**Files:** Modify `src/alpaca_trader/engine/trade_journal.py`

Add optional kwargs to `log_entry` and new method `log_option_exit`.

### Task 6: CLI mode commands

**Files:** Modify `src/alpaca_trader/cli.py`

Add `auto_app.command("mode")` and update `auto_status` to show trading_mode.

### Task 7: scripts/auto_trade.py

**Files:** Modify `scripts/auto_trade.py`

After `db.init_db()`, read `trading_mode` setting, instantiate OptionsTrader when mode=options.

### Task 8: Tests

**Files:** Create `tests/test_strike_selector.py`, `tests/test_options_position_manager.py`
