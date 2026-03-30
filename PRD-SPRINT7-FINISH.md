# PRD: Finish Sprint 7 — Auto-Trading Engine Completion

## Context

The alpaca-trader project has 7 sprints built. Sprint 7 (auto-trading engine) is partially complete:
- ✅ `src/alpaca_trader/engine/risk_manager.py` — RiskManager with circuit breakers, position sizing, loss limits
- ✅ `src/alpaca_trader/engine/order_executor.py` — OrderExecutor with retry logic, dry-run, slippage tracking
- ❌ Missing: PositionManager, TradeJournal, AutoTrader orchestrator, CLI commands, cron script

## What Needs to Be Built

### 1. Trade Journal (`src/alpaca_trader/engine/trade_journal.py`)

SQLite-based trade logging. Add table to existing database schema.

```python
class TradeJournal:
    """Log all trades with entry/exit prices, timestamps, P&L, strategy used."""
    
    async def log_entry(symbol, side, qty, price, strategy, signal_details) -> int  # trade_id
    async def log_exit(trade_id, price, reason) -> None
    async def get_trades(limit=50, strategy=None) -> list[dict]
    async def get_stats() -> dict  # win_rate, avg_pnl, total_trades, sharpe
    async def get_trade_count() -> int  # for 50-trade paper lockout
```

Database table (add via `init_db()` in `src/alpaca_trader/core/database.py`):
```sql
CREATE TABLE IF NOT EXISTS trade_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    strategy TEXT,
    signal_details TEXT,  -- JSON
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    pnl REAL,
    pnl_pct REAL,
    exit_reason TEXT,
    status TEXT DEFAULT 'open'  -- open, closed
);
```

### 2. Position Manager (`src/alpaca_trader/engine/position_manager.py`)

Monitors open positions and applies exit rules.

```python
class PositionManager:
    """Monitor positions and enforce exit rules."""
    
    # Exit rules (configurable):
    stop_loss_pct: float = -0.30        # -30% from entry
    take_profit_pct: float = 0.50       # +50% from entry
    trailing_stop_trigger: float = 0.25  # activate trailing stop at +25%
    trailing_stop_pct: float = 0.15     # trail by 15%
    max_hold_days: int = 30             # time-based exit
    
    def check_exits(positions: list[dict], journal: TradeJournal) -> list[dict]
        """Return list of positions that should be exited, with reason."""
    
    def should_exit(position, entry_price, entry_time, high_water_mark) -> tuple[bool, str]
        """Check if a single position meets any exit criteria."""
```

Uses the Alpaca client (`src/alpaca_trader/core/client.py`) to get current positions. The client already has `get_positions()` and `get_account()`.

### 3. AutoTrader Orchestrator (`src/alpaca_trader/engine/auto_trader.py`)

The main orchestration loop that ties everything together.

```python
class AutoTrader:
    """Main auto-trading orchestrator. Runs as a cron job every 5 minutes during market hours."""
    
    def __init__(self, risk_manager, order_executor, position_manager, trade_journal):
        self.enabled: bool = False  # persisted in settings table
        
    async def run_cycle(self) -> dict:
        """One auto-trade cycle:
        1. Check if enabled + market hours
        2. Check existing positions for exits (PositionManager)
        3. Execute any exit orders
        4. Get new signals from scanner
        5. Run risk checks on each signal
        6. Execute approved entry orders
        7. Log everything to journal
        8. Return summary dict for Telegram delivery
        """
    
    async def enable(self) -> None  # persist to DB settings
    async def disable(self) -> None
    async def status(self) -> dict  # enabled, circuit_breaker, trades_today, etc.
```

Settings persistence: use the existing `settings` table in SQLite (`src/alpaca_trader/core/database.py` already has `get_setting`/`set_setting`).

### 4. CLI Commands (add to `src/alpaca_trader/cli.py`)

Register a new `auto` command group:

```
alpaca-trader auto status    — Show engine state (enabled, circuit breaker, trades today, journal stats)
alpaca-trader auto enable    — Enable auto-trading
alpaca-trader auto disable   — Disable auto-trading
alpaca-trader auto run       — Run one auto-trade cycle manually (for testing)
alpaca-trader journal list   — Show recent trades from journal
alpaca-trader journal stats  — Show win rate, P&L, trade count
```

### 5. Cron Script (`scripts/auto_trade.py`)

Standalone script that runs as OpenClaw cron job every 5 minutes during market hours (6:30 AM - 1:00 PM PT / 9:30 AM - 4:00 PM ET).

```python
"""Auto-trade cron script.
- Checks if market is open
- Runs AutoTrader.run_cycle()
- Outputs summary for Telegram alert delivery
- Records equity snapshot
"""
```

### 6. Update `engine/__init__.py`

Export all new classes so they're importable:
```python
from .risk_manager import RiskManager, RiskConfig, RiskCheckResult
from .order_executor import OrderExecutor, ExecutorConfig, OrderResult
from .position_manager import PositionManager
from .trade_journal import TradeJournal
from .auto_trader import AutoTrader
```

## Existing Code to Reference

- **Client API:** `src/alpaca_trader/core/client.py` — has `get_account()`, `get_positions()`, `place_market_order()`, `place_limit_order()`, `get_stock_bars()` etc.
- **Database:** `src/alpaca_trader/core/database.py` — has `init_db()`, `get_setting()`/`set_setting()`, alert management
- **Scanner:** `src/alpaca_trader/strategies/scanner.py` — `WatchlistScanner.scan()` returns Signal objects
- **CLI pattern:** `src/alpaca_trader/cli.py` — uses Typer, Rich tables, existing command groups (`alert`, `watchlist`, `monitor`)
- **Alert delivery:** `src/alpaca_trader/alerts/delivery.py` — `TelegramDeliveryQueue` for queuing alerts

## Important Constraints

1. **Paper trading only** — The account is a paper trading account. The 50-trade lockout before "live" is a safety gate.
2. **All tests must pass** — Run `pytest` before considering done. Current: 182 passing.
3. **Write new tests** — Add tests for TradeJournal, PositionManager, AutoTrader (at least basic unit tests).
4. **Don't break existing code** — The fixes I already made to `client.py` (enum serialization, BarSet access, start date default) must be preserved.
5. **Market hours check** — US market hours: 9:30 AM - 4:00 PM ET. Use `datetime` with timezone awareness.
6. **Dry-run by default** — AutoTrader should default to `dry_run=True` in the OrderExecutor until explicitly enabled.

## Definition of Done

- [ ] TradeJournal with SQLite persistence
- [ ] PositionManager with stop-loss, take-profit, trailing stop, time-based exits
- [ ] AutoTrader orchestrator tying scanner → risk → execution → journal
- [ ] CLI commands: `auto status/enable/disable/run` + `journal list/stats`
- [ ] Cron script `scripts/auto_trade.py`
- [ ] All existing tests still pass (182+)
- [ ] New tests for the above modules
- [ ] `engine/__init__.py` updated with exports
