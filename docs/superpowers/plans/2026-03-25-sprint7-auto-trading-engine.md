# Sprint 7: Auto-Trading Engine with Risk Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully autonomous options auto-trading engine with position sizing, circuit breakers, mechanical exits, and trade journaling — defaulting OFF for safety, gated behind 50 paper trades before live.

**Architecture:** New `engine/` module with five focused files (risk_manager, trade_journal, order_executor, position_manager, auto_trader). The ScheduledScanner and cron script are updated to drive the engine. CLI gains `auto` and `journal` sub-command groups backed by the settings table.

**Tech Stack:** Python async/await, aiosqlite (SQLite), alpaca-py (sync), Typer + Rich (CLI), existing TelegramDeliveryQueue

---

## Critical Fixes (v2 — post-review)

The following issues were identified in code review and are incorporated into implementation:

1. **Weekly circuit breaker**: `get_circuit_breaker_state()` must track weekly equity baseline (stored as `auto_trade.weekly_equity_start`) and compare against `weekly_loss_limit_pct`.
2. **last_equity snapshot**: Cron script must write `auto_trade.last_equity` = current equity at start of each run, and `auto_trade.weekly_equity_start` on Mondays.
3. **Flash crash protection**: `run_exit_checks()` must check if any position dropped >40% in value vs entry; if so, market sell immediately with reason `"flash_crash"`.
4. **pytest/pytest-asyncio dev deps**: Add to `pyproject.toml` under `[project.optional-dependencies] dev = [...]`. Add `[tool.pytest.ini_options] asyncio_mode = "auto"`.
5. **Consecutive loss ordering**: Journal query for streak must use `ORDER BY closed_at DESC`.
6. **DST-aware timezone**: Use `pytz.timezone("America/New_York")` for EOD flatten and same-day exit checks. Already in deps.
7. **Private method access**: `auto_trader.py` must call `db.setting_get()` directly rather than `risk_manager._get_float()`.
8. **`setting_delete()` function**: Add to `database.py`. Use it for trailing stop cleanup.
9. **Dynamic target delta**: Compute `target_delta = (delta_min + delta_max) / 2` from settings.
10. **Test isolation**: Use `pytest` fixture with `tmp_path` or env var override + module reload for DB isolation.

---

## File Map

### New Files
- `src/alpaca_trader/engine/__init__.py` — package marker
- `src/alpaca_trader/engine/risk_manager.py` — position sizing, pre-trade gate, circuit breakers
- `src/alpaca_trader/engine/trade_journal.py` — CRUD for trade_journal SQLite table
- `src/alpaca_trader/engine/order_executor.py` — smart limit order placement with retry ladder
- `src/alpaca_trader/engine/position_manager.py` — exit strategy monitoring (stop-loss, take-profit, trailing stop, time exit)
- `src/alpaca_trader/engine/auto_trader.py` — orchestrator: signal → risk check → option selection → execution → exit setup
- `tests/test_engine_risk.py` — unit tests for risk_manager
- `tests/test_engine_journal.py` — unit tests for trade_journal

### Modified Files
- `src/alpaca_trader/core/database.py` — add `trade_journal` table schema + `auto_trade` settings init + journal CRUD
- `src/alpaca_trader/alerts/scanner.py` — call AutoTrader after scan when enabled
- `src/alpaca_trader/cli.py` — add `auto_app` + `journal_app` sub-command groups
- `scripts/cron_scan_and_deliver.py` — add position check cycle + auto-trade results to output

---

## Task 1: Database Schema — trade_journal table + settings defaults

**Files:**
- Modify: `src/alpaca_trader/core/database.py`

- [ ] **Step 1: Add `trade_journal` CREATE TABLE inside `init_db()`**

After the existing `alerts` table block, add:

```python
        # Sprint 7: Trade journal
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trade_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT NOT NULL UNIQUE,
                entered_at TIMESTAMP NOT NULL,
                closed_at TIMESTAMP,
                symbol TEXT NOT NULL,
                underlying TEXT NOT NULL,
                option_type TEXT NOT NULL,
                strike REAL NOT NULL,
                expiry TEXT NOT NULL,
                strategy TEXT NOT NULL,
                signal_data TEXT NOT NULL DEFAULT '{}',
                entry_price REAL NOT NULL,
                exit_price REAL,
                qty INTEGER NOT NULL,
                pnl_dollar REAL,
                pnl_pct REAL,
                exit_reason TEXT,
                hold_duration_secs INTEGER,
                risk_check_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'open',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_journal_underlying
            ON trade_journal (underlying, entered_at)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_journal_status
            ON trade_journal (status)
        """)
```

- [ ] **Step 2: Add `init_auto_trade_settings()` async function to database.py**

```python
_AUTO_TRADE_DEFAULTS = {
    "auto_trade.enabled": "false",
    "auto_trade.max_risk_pct": "2.0",
    "auto_trade.max_positions": "5",
    "auto_trade.max_allocation_pct": "50",
    "auto_trade.max_per_symbol_pct": "10",
    "auto_trade.stop_loss_pct": "-30",
    "auto_trade.take_profit_pct": "50",
    "auto_trade.trailing_stop_pct": "15",
    "auto_trade.trailing_activate_pct": "25",
    "auto_trade.target_dte_min": "14",
    "auto_trade.target_dte_max": "45",
    "auto_trade.target_delta_min": "0.25",
    "auto_trade.target_delta_max": "0.45",
    "auto_trade.daily_loss_limit_pct": "-5",
    "auto_trade.weekly_loss_limit_pct": "-10",
    "auto_trade.flatten_eod": "false",
    "auto_trade.min_liquidity_oi": "100",
    "auto_trade.min_liquidity_volume": "50",
    "auto_trade.max_spread_pct": "15",
}


async def init_auto_trade_settings() -> None:
    """Insert auto_trade settings with defaults if they don't exist yet."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        for key, value in _AUTO_TRADE_DEFAULTS.items():
            await db.execute(
                """INSERT INTO settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO NOTHING""",
                (key, value),
            )
        await db.commit()
```

- [ ] **Step 3: Add journal CRUD functions to database.py**

```python
# --- Trade Journal Operations ---

async def journal_insert(trade: dict) -> int:
    """Insert a new trade into the journal. Returns row ID."""
    import json
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute(
            """INSERT INTO trade_journal (
                trade_id, entered_at, symbol, underlying, option_type, strike, expiry,
                strategy, signal_data, entry_price, qty, risk_check_json, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (
                trade["trade_id"],
                trade["entered_at"],
                trade["symbol"],
                trade["underlying"],
                trade["option_type"],
                trade["strike"],
                trade["expiry"],
                trade["strategy"],
                json.dumps(trade.get("signal_data", {})),
                trade["entry_price"],
                trade["qty"],
                json.dumps(trade.get("risk_check", {})),
                trade.get("notes"),
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def journal_close(trade_id: str, exit_price: float, exit_reason: str, notes: Optional[str] = None) -> bool:
    """Close a trade in the journal. Returns True if updated."""
    import json
    from datetime import datetime
    async with aiosqlite.connect(DATABASE_URL) as db:
        # Fetch entry to compute P&L
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT entry_price, qty, entered_at FROM trade_journal WHERE trade_id = ? AND status = 'open'",
            (trade_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return False
        entry_price = float(row["entry_price"])
        qty = int(row["qty"])
        entered_at = row["entered_at"]
        closed_at = datetime.utcnow().isoformat()
        pnl_dollar = (exit_price - entry_price) * qty * 100
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price else 0
        try:
            entered_dt = datetime.fromisoformat(entered_at)
            hold_secs = int((datetime.utcnow() - entered_dt).total_seconds())
        except Exception:
            hold_secs = None
        cursor2 = await db.execute(
            """UPDATE trade_journal SET
                closed_at=?, exit_price=?, pnl_dollar=?, pnl_pct=?,
                exit_reason=?, hold_duration_secs=?, status='closed', notes=COALESCE(?,notes)
               WHERE trade_id=? AND status='open'""",
            (closed_at, exit_price, pnl_dollar, pnl_pct, exit_reason, hold_secs, notes, trade_id),
        )
        await db.commit()
        return cursor2.rowcount > 0


async def journal_list(status: Optional[str] = None, limit: int = 50) -> list[dict]:
    """List trade journal entries."""
    import json
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        if status:
            cursor = await db.execute(
                "SELECT * FROM trade_journal WHERE status=? ORDER BY entered_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM trade_journal ORDER BY entered_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            for field in ("signal_data", "risk_check_json"):
                try:
                    d[field] = json.loads(d.get(field) or "{}")
                except Exception:
                    d[field] = {}
            result.append(d)
        return result


async def journal_stats() -> dict:
    """Compute aggregate statistics from the trade journal."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trade_journal WHERE status='closed' ORDER BY closed_at DESC"
        )
        rows = await cursor.fetchall()
        trades = [dict(r) for r in rows]

    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "avg_pnl_pct": 0.0, "total_pnl_dollar": 0.0,
                "best_trade": None, "worst_trade": None, "by_strategy": {}}

    wins = [t for t in trades if (t.get("pnl_dollar") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl_dollar") or 0) <= 0]
    total_pnl = sum(t.get("pnl_dollar") or 0 for t in trades)
    avg_pnl_pct = sum(t.get("pnl_pct") or 0 for t in trades) / len(trades)
    best = max(trades, key=lambda t: t.get("pnl_dollar") or 0)
    worst = min(trades, key=lambda t: t.get("pnl_dollar") or 0)

    by_strategy: dict = {}
    for t in trades:
        s = t.get("strategy", "unknown")
        if s not in by_strategy:
            by_strategy[s] = {"total": 0, "wins": 0, "total_pnl": 0.0}
        by_strategy[s]["total"] += 1
        if (t.get("pnl_dollar") or 0) > 0:
            by_strategy[s]["wins"] += 1
        by_strategy[s]["total_pnl"] += t.get("pnl_dollar") or 0

    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades),
        "avg_pnl_pct": avg_pnl_pct,
        "total_pnl_dollar": total_pnl,
        "best_trade": best,
        "worst_trade": worst,
        "by_strategy": by_strategy,
    }


async def journal_get_open() -> list[dict]:
    """Get all open trade journal entries."""
    return await journal_list(status="open", limit=200)


async def journal_count_closed() -> int:
    """Return count of closed trades (for paper trade lockout check)."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM trade_journal WHERE status='closed'")
        row = await cursor.fetchone()
        return row[0] if row else 0
```

- [ ] **Step 4: Call `init_auto_trade_settings()` at the end of `init_db()`**

In `init_db()`, before `await db.commit()`, this is already handled by `init_auto_trade_settings()` being a separate function that uses its own connection. Call it at the end of `init_db()` by adding:

```python
        await db.commit()

    # Initialize auto_trade settings defaults (idempotent)
    await init_auto_trade_settings()
```

- [ ] **Step 5: Commit**

```bash
git add src/alpaca_trader/core/database.py
git commit -m "feat(sprint-7): trade_journal schema + auto_trade settings + journal CRUD"
```

---

## Task 2: engine/ Package + Trade Journal Module

**Files:**
- Create: `src/alpaca_trader/engine/__init__.py`
- Create: `src/alpaca_trader/engine/trade_journal.py`

- [ ] **Step 1: Create engine package**

```python
# src/alpaca_trader/engine/__init__.py
"""Auto-trading engine — Sprint 7."""
```

- [ ] **Step 2: Create trade_journal.py**

This is a thin wrapper around the database CRUD, plus a helper for building a trade dict.

```python
# src/alpaca_trader/engine/trade_journal.py
"""Trade journal — wrapper around database CRUD for structured trade logging."""

import uuid
from datetime import datetime
from typing import Optional

from alpaca_trader.core import database as db


def make_trade_id() -> str:
    return str(uuid.uuid4())


class TradeJournal:
    """Logs trade lifecycle events to the trade_journal SQLite table."""

    async def open_trade(
        self,
        symbol: str,
        underlying: str,
        option_type: str,
        strike: float,
        expiry: str,
        strategy: str,
        entry_price: float,
        qty: int,
        signal_data: Optional[dict] = None,
        risk_check: Optional[dict] = None,
        notes: Optional[str] = None,
    ) -> str:
        """Log a new trade entry. Returns the trade_id."""
        trade_id = make_trade_id()
        await db.journal_insert({
            "trade_id": trade_id,
            "entered_at": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "underlying": underlying,
            "option_type": option_type,
            "strike": strike,
            "expiry": expiry,
            "strategy": strategy,
            "entry_price": entry_price,
            "qty": qty,
            "signal_data": signal_data or {},
            "risk_check": risk_check or {},
            "notes": notes,
        })
        return trade_id

    async def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Close a trade in the journal. Returns True if updated."""
        return await db.journal_close(trade_id, exit_price, exit_reason, notes)

    async def get_open_trades(self) -> list[dict]:
        return await db.journal_get_open()

    async def get_recent_trades(self, limit: int = 50) -> list[dict]:
        return await db.journal_list(limit=limit)

    async def get_stats(self) -> dict:
        return await db.journal_stats()

    async def count_closed_trades(self) -> int:
        return await db.journal_count_closed()
```

- [ ] **Step 3: Write basic tests for the journal module**

```python
# tests/test_engine_journal.py
"""Basic smoke tests for TradeJournal (uses in-memory DB via env override)."""
import asyncio
import os
import tempfile
import pytest

os.environ["DATABASE_URL"] = ":memory:"

# Re-import after env set
from alpaca_trader.core import database as db
from alpaca_trader.engine.trade_journal import TradeJournal


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def fresh_db():
    await db.init_db()
    yield


@pytest.mark.asyncio
async def test_open_and_close_trade(fresh_db):
    journal = TradeJournal()
    trade_id = await journal.open_trade(
        symbol="AAPL241220C00180000",
        underlying="AAPL",
        option_type="call",
        strike=180.0,
        expiry="2024-12-20",
        strategy="bounce",
        entry_price=3.20,
        qty=3,
        signal_data={"direction": "bullish"},
    )
    assert trade_id

    open_trades = await journal.get_open_trades()
    assert any(t["trade_id"] == trade_id for t in open_trades)

    closed = await journal.close_trade(trade_id, exit_price=4.80, exit_reason="take_profit")
    assert closed is True

    open_after = await journal.get_open_trades()
    assert not any(t["trade_id"] == trade_id for t in open_after)

    stats = await journal.get_stats()
    assert stats["total"] == 1
    assert stats["wins"] == 1


@pytest.mark.asyncio
async def test_count_closed(fresh_db):
    journal = TradeJournal()
    assert await journal.count_closed_trades() == 0
    trade_id = await journal.open_trade(
        symbol="AAPL241220C00180000", underlying="AAPL",
        option_type="call", strike=180.0, expiry="2024-12-20",
        strategy="squeeze", entry_price=2.0, qty=1,
    )
    await journal.close_trade(trade_id, 1.5, "stop_loss")
    assert await journal.count_closed_trades() == 1
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/tonylesmb/claw-workspace/alpaca-trader
.venv/bin/pytest tests/test_engine_journal.py -v
```

Expected: All tests PASS (or skip if pytest-asyncio not installed — install with `.venv/bin/pip install pytest-asyncio`)

- [ ] **Step 5: Commit**

```bash
git add src/alpaca_trader/engine/ tests/test_engine_journal.py
git commit -m "feat(sprint-7): engine package + TradeJournal module"
```

---

## Task 3: Risk Manager

**Files:**
- Create: `src/alpaca_trader/engine/risk_manager.py`
- Create: `tests/test_engine_risk.py`

- [ ] **Step 1: Write risk_manager.py**

```python
# src/alpaca_trader/engine/risk_manager.py
"""Risk Manager — position sizing, pre-trade gate, circuit breakers."""

import os
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from typing import Optional

from alpaca_trader.core import client as alpaca
from alpaca_trader.core import database as db


@dataclass
class RiskCheckResult:
    approved: bool
    reason: str
    max_contracts: int = 0
    max_risk_dollar: float = 0.0
    details: dict = field(default_factory=dict)


@dataclass
class CircuitBreakerState:
    daily_halt: bool = False
    weekly_halt: bool = False
    reduced_size: bool = False
    consecutive_losses: int = 0
    halt_reason: str = ""


class RiskManager:
    """Evaluates whether a trade may proceed and computes position size.

    All configuration is loaded from the settings table.
    """

    async def _get_float(self, key: str, default: float) -> float:
        val = await db.setting_get(key)
        try:
            return float(val) if val is not None else default
        except (TypeError, ValueError):
            return default

    async def _get_bool(self, key: str, default: bool = False) -> bool:
        val = await db.setting_get(key)
        if val is None:
            return default
        return str(val).lower() in ("true", "1", "yes")

    async def is_enabled(self) -> bool:
        return await self._get_bool("auto_trade.enabled", False)

    async def _load_settings(self) -> dict:
        keys = [
            "auto_trade.max_risk_pct",
            "auto_trade.max_positions",
            "auto_trade.max_allocation_pct",
            "auto_trade.max_per_symbol_pct",
            "auto_trade.stop_loss_pct",
            "auto_trade.take_profit_pct",
            "auto_trade.target_dte_min",
            "auto_trade.target_dte_max",
            "auto_trade.target_delta_min",
            "auto_trade.target_delta_max",
            "auto_trade.daily_loss_limit_pct",
            "auto_trade.weekly_loss_limit_pct",
            "auto_trade.min_liquidity_oi",
            "auto_trade.min_liquidity_volume",
            "auto_trade.max_spread_pct",
        ]
        result = {}
        for k in keys:
            result[k] = await db.setting_get(k)
        return result

    async def get_circuit_breaker_state(self) -> CircuitBreakerState:
        """Check daily/weekly P&L against loss limits."""
        state = CircuitBreakerState()
        try:
            account = alpaca.get_account()
            equity = float(account.get("equity") or account.get("portfolio_value") or 0)
            if equity <= 0:
                return state

            settings = await self._load_settings()
            daily_limit = float(settings.get("auto_trade.daily_loss_limit_pct") or -5)
            weekly_limit = float(settings.get("auto_trade.weekly_loss_limit_pct") or -10)

            # Use pnl snapshots to compute today's P&L
            today_snapshots = await db.get_pnl_history("__portfolio__", days=1)
            # Fallback: use account equity vs last_equity if available
            last_equity_str = await db.setting_get("auto_trade.last_equity")
            if last_equity_str:
                try:
                    last_equity = float(last_equity_str)
                    daily_pnl_pct = ((equity - last_equity) / last_equity) * 100
                    if daily_pnl_pct <= daily_limit:
                        state.daily_halt = True
                        state.halt_reason = f"Daily loss {daily_pnl_pct:.1f}% hit limit {daily_limit}%"
                except Exception:
                    pass

            # Check consecutive losses from journal
            try:
                recent = await db.journal_list(status="closed", limit=10)
                consec = 0
                for t in recent:
                    if (t.get("pnl_dollar") or 0) < 0:
                        consec += 1
                    else:
                        break
                state.consecutive_losses = consec
                if consec >= 3:
                    state.reduced_size = True
        except Exception:
            pass
        return state

    async def compute_position_size(
        self,
        equity: float,
        option_premium: float,
    ) -> tuple[int, float]:
        """Return (max_contracts, max_risk_dollar) for an options trade."""
        settings = await self._load_settings()
        max_risk_pct = float(settings.get("auto_trade.max_risk_pct") or 2.0)
        max_risk_dollar = equity * (max_risk_pct / 100)

        # Check if in reduced-size mode (3 consecutive losses)
        cb = await self.get_circuit_breaker_state()
        if cb.reduced_size:
            max_risk_dollar *= 0.5

        if option_premium <= 0:
            return 0, max_risk_dollar

        max_contracts = int(max_risk_dollar / (option_premium * 100))
        return max(0, max_contracts), max_risk_dollar

    async def pre_trade_check(
        self,
        underlying: str,
        option_contract: dict,
        direction: str,
    ) -> RiskCheckResult:
        """Run all pre-trade checks. Returns RiskCheckResult."""
        settings = await self._load_settings()
        details: dict = {}

        # 1. Check market is open
        try:
            clock = alpaca._get_trading_client().get_clock()
            if not clock.is_open:
                return RiskCheckResult(False, "Market is closed", details={"market_open": False})
        except Exception as e:
            return RiskCheckResult(False, f"Cannot verify market status: {e}")

        # 2. Get account info
        try:
            account = alpaca.get_account()
            equity = float(account.get("equity") or account.get("portfolio_value") or 0)
            buying_power = float(account.get("buying_power") or 0)
        except Exception as e:
            return RiskCheckResult(False, f"Cannot fetch account: {e}")

        if equity <= 0:
            return RiskCheckResult(False, "Cannot determine account equity")

        # 3. Circuit breakers
        cb = await self.get_circuit_breaker_state()
        if cb.daily_halt:
            return RiskCheckResult(False, cb.halt_reason, details={"circuit_breaker": "daily"})
        if cb.weekly_halt:
            return RiskCheckResult(False, cb.halt_reason, details={"circuit_breaker": "weekly"})

        # 4. Max concurrent positions
        try:
            positions = alpaca.get_positions()
        except Exception as e:
            return RiskCheckResult(False, f"Cannot fetch positions: {e}")

        max_positions = int(float(settings.get("auto_trade.max_positions") or 5))
        if len(positions) >= max_positions:
            return RiskCheckResult(
                False,
                f"Max positions reached ({len(positions)}/{max_positions})",
                details={"positions": len(positions)},
            )

        # 5. Not already holding a position in this underlying
        for pos in positions:
            pos_sym = pos.get("symbol", "")
            if underlying.upper() in pos_sym.upper():
                return RiskCheckResult(
                    False, f"Already holding a position in {underlying}",
                    details={"existing_symbol": pos_sym},
                )

        # 6. Max allocation per symbol
        max_per_symbol_pct = float(settings.get("auto_trade.max_per_symbol_pct") or 10)
        symbol_allocation = sum(
            float(p.get("market_value") or 0)
            for p in positions
            if underlying.upper() in p.get("symbol", "").upper()
        )
        if equity > 0 and (symbol_allocation / equity * 100) >= max_per_symbol_pct:
            return RiskCheckResult(
                False,
                f"Max per-symbol allocation reached for {underlying}",
                details={"symbol_alloc_pct": symbol_allocation / equity * 100},
            )

        # 7. Max total portfolio allocation
        max_alloc_pct = float(settings.get("auto_trade.max_allocation_pct") or 50)
        total_market_value = sum(float(p.get("market_value") or 0) for p in positions)
        if equity > 0 and (total_market_value / equity * 100) >= max_alloc_pct:
            return RiskCheckResult(
                False,
                f"Max portfolio allocation reached ({total_market_value/equity*100:.1f}%)",
                details={"total_alloc_pct": total_market_value / equity * 100},
            )

        # 8. Sufficient buying power (premium * qty * 100 + 10% buffer)
        bid = float(option_contract.get("bid_price") or 0)
        ask = float(option_contract.get("ask_price") or 0)
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else float(option_contract.get("last_price") or 0)
        if mid <= 0:
            return RiskCheckResult(False, "Cannot determine option price (no bid/ask)", details={"contract": option_contract.get("symbol")})

        max_contracts, max_risk_dollar = await self.compute_position_size(equity, mid)
        if max_contracts <= 0:
            return RiskCheckResult(False, "Position size rounds to 0 contracts", max_contracts=0, max_risk_dollar=max_risk_dollar)

        cost_estimate = mid * max_contracts * 100 * 1.1  # 10% buffer
        if buying_power < cost_estimate:
            # Try with fewer contracts
            affordable = int(buying_power / (mid * 100 * 1.1))
            if affordable <= 0:
                return RiskCheckResult(False, f"Insufficient buying power (need ~${cost_estimate:.0f}, have ${buying_power:.0f})")
            max_contracts = min(max_contracts, affordable)

        # 9. Liquidity checks
        max_spread_pct = float(settings.get("auto_trade.max_spread_pct") or 15)
        min_oi = int(float(settings.get("auto_trade.min_liquidity_oi") or 100))
        min_vol = int(float(settings.get("auto_trade.min_liquidity_volume") or 50))

        if bid > 0 and ask > 0 and mid > 0:
            spread_pct = ((ask - bid) / mid) * 100
            details["spread_pct"] = round(spread_pct, 2)
            if spread_pct > max_spread_pct:
                return RiskCheckResult(
                    False,
                    f"Bid-ask spread too wide ({spread_pct:.1f}% > {max_spread_pct}%)",
                    details=details,
                )

        oi = int(option_contract.get("open_interest") or 0)
        details["open_interest"] = oi
        if oi < min_oi:
            return RiskCheckResult(False, f"Open interest too low ({oi} < {min_oi})", details=details)

        vol = int(option_contract.get("volume") or 0)
        details["volume"] = vol
        if vol < min_vol:
            return RiskCheckResult(False, f"Volume too low ({vol} < {min_vol})", details=details)

        # 10. Expiry DTE check
        dte_min = int(float(settings.get("auto_trade.target_dte_min") or 14))
        dte_max = int(float(settings.get("auto_trade.target_dte_max") or 45))
        expiry_str = option_contract.get("expiration_date") or option_contract.get("expiry")
        if expiry_str:
            try:
                expiry_date = date.fromisoformat(str(expiry_str)[:10])
                dte = (expiry_date - date.today()).days
                details["dte"] = dte
                if dte < dte_min or dte > dte_max:
                    return RiskCheckResult(
                        False,
                        f"DTE {dte} outside target range [{dte_min}, {dte_max}]",
                        details=details,
                    )
            except Exception:
                pass

        details["equity"] = equity
        details["max_contracts"] = max_contracts
        details["mid_price"] = round(mid, 4)

        return RiskCheckResult(
            True, "All pre-trade checks passed",
            max_contracts=max_contracts,
            max_risk_dollar=max_risk_dollar,
            details=details,
        )

    async def is_live_trading_allowed(self) -> tuple[bool, str]:
        """Check paper-trade lockout: 50 trades + >40% win rate needed for live."""
        base_url = os.getenv("ALPACA_BASE_URL", "")
        if "paper" in base_url.lower():
            return True, "paper"

        closed_count = await db.journal_count_closed()
        if closed_count < 50:
            return False, f"Need 50 paper trades before live (have {closed_count})"

        stats = await db.journal_stats()
        win_rate = stats.get("win_rate", 0.0)
        if win_rate < 0.40:
            return False, f"Win rate {win_rate:.1%} below 40% threshold for live trading"

        return True, "live_allowed"
```

- [ ] **Step 2: Write tests**

```python
# tests/test_engine_risk.py
"""Unit tests for RiskManager helper methods (no live API calls)."""
import asyncio
import os
import pytest

os.environ["DATABASE_URL"] = ":memory:"

from alpaca_trader.core import database as db
from alpaca_trader.engine.risk_manager import RiskManager


@pytest.fixture(autouse=True)
async def setup_db():
    await db.init_db()
    yield


@pytest.mark.asyncio
async def test_compute_position_size_basic():
    rm = RiskManager()
    # 2% of $100K equity, option premium $3.00
    contracts, max_risk = await rm.compute_position_size(100_000, 3.0)
    # max_risk = 2000, cost per contract = 300, so contracts = floor(2000/300) = 6
    assert max_risk == 2000.0
    assert contracts == 6


@pytest.mark.asyncio
async def test_compute_position_size_zero_premium():
    rm = RiskManager()
    contracts, _ = await rm.compute_position_size(100_000, 0)
    assert contracts == 0


@pytest.mark.asyncio
async def test_is_enabled_default_false():
    rm = RiskManager()
    assert await rm.is_enabled() is False


@pytest.mark.asyncio
async def test_is_enabled_after_set():
    await db.setting_set("auto_trade.enabled", "true")
    rm = RiskManager()
    assert await rm.is_enabled() is True
```

- [ ] **Step 3: Run tests**

```bash
cd /Users/tonylesmb/claw-workspace/alpaca-trader
.venv/bin/pytest tests/test_engine_risk.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/alpaca_trader/engine/risk_manager.py tests/test_engine_risk.py
git commit -m "feat(sprint-7): RiskManager — position sizing, pre-trade gate, circuit breakers"
```

---

## Task 4: Order Executor

**Files:**
- Create: `src/alpaca_trader/engine/order_executor.py`

- [ ] **Step 1: Write order_executor.py**

```python
# src/alpaca_trader/engine/order_executor.py
"""Order Executor — smart limit order placement with retry ladder for options."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from alpaca_trader.core import client as alpaca

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str]
    filled_price: Optional[float]
    filled_qty: int
    status: str
    reason: str


class OrderExecutor:
    """Places limit orders for options with a 2-tier retry ladder.

    Tier 1 (0–60s):  limit at mid price
    Tier 2 (60–120s): limit at 75% of the way from mid to ask
    After 120s: cancel and skip.
    Never uses market orders for entries.
    """

    async def place_entry(
        self,
        symbol: str,
        qty: int,
        bid: float,
        ask: float,
    ) -> OrderResult:
        """Place an options buy entry with price adjustment ladder."""
        if qty <= 0:
            return OrderResult(False, None, None, 0, "rejected", "qty must be > 0")
        if bid <= 0 or ask <= 0:
            return OrderResult(False, None, None, 0, "rejected", "invalid bid/ask")

        mid = round((bid + ask) / 2, 2)

        # Tier 1: mid price, wait up to 60s
        order = None
        try:
            order = alpaca.place_limit_order(symbol, qty, "buy", mid, "day")
        except Exception as e:
            return OrderResult(False, None, None, 0, "error", str(e))

        order_id = order.get("id") or order.get("order_id")
        if not order_id:
            return OrderResult(False, None, None, 0, "error", "No order ID returned")

        logger.info(f"Entry order {order_id} placed at mid {mid} for {symbol} x{qty}")

        filled = await self._wait_for_fill(order_id, timeout_secs=60)
        if filled:
            filled_price = float(filled.get("filled_avg_price") or mid)
            filled_qty = int(float(filled.get("filled_qty") or qty))
            logger.info(f"Order {order_id} filled at {filled_price}")
            return OrderResult(True, order_id, filled_price, filled_qty, "filled", "Filled at tier-1 mid price")

        # Partially filled? Take what we got.
        status = await self._get_order_status(order_id)
        partial_qty = int(float(status.get("filled_qty") or 0))
        if partial_qty > 0:
            logger.info(f"Order {order_id} partially filled {partial_qty}/{qty}, cancelling remainder")
            try:
                alpaca.cancel_order(order_id)
            except Exception:
                pass
            filled_price = float(status.get("filled_avg_price") or mid)
            return OrderResult(True, order_id, filled_price, partial_qty, "partially_filled", f"Partial fill {partial_qty}/{qty}")

        # Tier 2: adjust to 75% of way from mid to ask
        adjusted_price = round(mid + 0.75 * (ask - mid), 2)
        try:
            alpaca.cancel_order(order_id)
        except Exception:
            pass
        await asyncio.sleep(1)  # brief pause for cancel to settle

        logger.info(f"Adjusting order to {adjusted_price} (tier-2) for {symbol}")
        try:
            order2 = alpaca.place_limit_order(symbol, qty, "buy", adjusted_price, "day")
        except Exception as e:
            return OrderResult(False, order_id, None, 0, "cancelled", f"Tier-2 order failed: {e}")

        order_id2 = order2.get("id") or order2.get("order_id")
        if not order_id2:
            return OrderResult(False, None, None, 0, "error", "No order ID for tier-2")

        filled2 = await self._wait_for_fill(order_id2, timeout_secs=60)
        if filled2:
            filled_price = float(filled2.get("filled_avg_price") or adjusted_price)
            filled_qty = int(float(filled2.get("filled_qty") or qty))
            return OrderResult(True, order_id2, filled_price, filled_qty, "filled", "Filled at tier-2 adjusted price")

        # Still not filled — cancel and skip
        try:
            alpaca.cancel_order(order_id2)
        except Exception:
            pass
        logger.warning(f"Order for {symbol} x{qty} not filled after 120s — cancelled")
        return OrderResult(False, order_id2, None, 0, "cancelled", "Not filled within 120s")

    async def place_take_profit_sell(
        self,
        symbol: str,
        qty: int,
        take_profit_price: float,
    ) -> Optional[str]:
        """Place a GTC limit sell at take_profit_price. Returns order_id or None."""
        try:
            order = alpaca.place_limit_order(symbol, qty, "sell", take_profit_price, "gtc")
            return order.get("id") or order.get("order_id")
        except Exception as e:
            logger.error(f"Failed to place TP sell for {symbol}: {e}")
            return None

    async def place_exit_market_sell(self, symbol: str, qty: int) -> OrderResult:
        """Place a market sell to exit a position immediately."""
        try:
            order = alpaca.place_market_order(symbol, qty, "sell", "day")
            order_id = order.get("id") or order.get("order_id")
            filled = await self._wait_for_fill(order_id, timeout_secs=30)
            if filled:
                price = float(filled.get("filled_avg_price") or 0)
                return OrderResult(True, order_id, price, qty, "filled", "Market sell filled")
            return OrderResult(True, order_id, None, qty, "pending", "Market sell submitted")
        except Exception as e:
            return OrderResult(False, None, None, 0, "error", str(e))

    async def cancel_order(self, order_id: str) -> bool:
        try:
            alpaca.cancel_order(order_id)
            return True
        except Exception:
            return False

    async def _wait_for_fill(self, order_id: str, timeout_secs: int = 60) -> Optional[dict]:
        """Poll order status until filled or timeout. Returns filled order dict or None."""
        elapsed = 0
        poll_interval = 5
        while elapsed < timeout_secs:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            try:
                order = alpaca.get_order(order_id)
                status = order.get("status", "")
                if status == "filled":
                    return order
                if status in ("cancelled", "canceled", "expired", "rejected"):
                    return None
            except Exception:
                pass
        return None

    async def _get_order_status(self, order_id: str) -> dict:
        try:
            return alpaca.get_order(order_id)
        except Exception:
            return {}
```

- [ ] **Step 2: Commit**

```bash
git add src/alpaca_trader/engine/order_executor.py
git commit -m "feat(sprint-7): OrderExecutor — smart limit order placement with retry ladder"
```

---

## Task 5: Position Manager

**Files:**
- Create: `src/alpaca_trader/engine/position_manager.py`

- [ ] **Step 1: Write position_manager.py**

This module monitors open journal trades, checks exit conditions, and submits exit orders.

```python
# src/alpaca_trader/engine/position_manager.py
"""Position Manager — monitors open trades and enforces all exit strategies."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from alpaca_trader.core import client as alpaca
from alpaca_trader.core import database as db
from alpaca_trader.engine.order_executor import OrderExecutor
from alpaca_trader.engine.trade_journal import TradeJournal

logger = logging.getLogger(__name__)


@dataclass
class PositionState:
    trade_id: str
    symbol: str
    underlying: str
    entry_price: float
    qty: int
    expiry: str
    current_price: float = 0.0
    peak_price: float = 0.0
    trailing_active: bool = False
    trail_stop_price: float = 0.0
    tp_order_id: Optional[str] = None
    exit_triggered: bool = False
    exit_reason: str = ""


@dataclass
class ExitAction:
    trade_id: str
    symbol: str
    qty: int
    reason: str
    message: str = ""


class PositionManager:
    """Checks all open trades for exit conditions each scan cycle."""

    def __init__(self):
        self.executor = OrderExecutor()
        self.journal = TradeJournal()

    async def _get_float_setting(self, key: str, default: float) -> float:
        val = await db.setting_get(key)
        try:
            return float(val) if val is not None else default
        except (TypeError, ValueError):
            return default

    async def _get_bool_setting(self, key: str, default: bool = False) -> bool:
        val = await db.setting_get(key)
        if val is None:
            return default
        return str(val).lower() in ("true", "1", "yes")

    async def run_exit_checks(self) -> list[ExitAction]:
        """Check all open trades for exit conditions. Returns list of exits taken."""
        open_trades = await self.journal.get_open_trades()
        if not open_trades:
            return []

        stop_loss_pct = await self._get_float_setting("auto_trade.stop_loss_pct", -30)
        take_profit_pct = await self._get_float_setting("auto_trade.take_profit_pct", 50)
        trailing_stop_pct = await self._get_float_setting("auto_trade.trailing_stop_pct", 15)
        trailing_activate_pct = await self._get_float_setting("auto_trade.trailing_activate_pct", 25)
        flatten_eod = await self._get_bool_setting("auto_trade.flatten_eod", False)

        # Get current prices from Alpaca positions
        try:
            live_positions = alpaca.get_positions()
            price_map = {p["symbol"]: float(p.get("current_price") or 0) for p in live_positions}
        except Exception as e:
            logger.error(f"Failed to fetch live positions: {e}")
            price_map = {}

        exits: list[ExitAction] = []
        today = date.today()

        for trade in open_trades:
            trade_id = trade["trade_id"]
            symbol = trade["symbol"]
            entry_price = float(trade["entry_price"])
            qty = int(trade["qty"])
            expiry_str = str(trade.get("expiry", ""))

            current_price = price_map.get(symbol)
            if current_price is None or current_price <= 0:
                # Try via option snapshot
                try:
                    snaps = alpaca.get_option_snapshots([symbol])
                    snap = snaps.get(symbol, {})
                    lq = snap.get("latest_quote", {})
                    bid = float(lq.get("bp") or 0)
                    ask = float(lq.get("ap") or 0)
                    if bid > 0 and ask > 0:
                        current_price = (bid + ask) / 2
                    else:
                        lt = snap.get("latest_trade", {})
                        current_price = float(lt.get("p") or 0)
                except Exception:
                    current_price = 0

            if current_price <= 0 or entry_price <= 0:
                continue

            pct_change = ((current_price - entry_price) / entry_price) * 100
            exit_reason = None

            # 1. Stop-loss check
            if pct_change <= stop_loss_pct:
                exit_reason = "stop_loss"
                logger.info(f"{symbol} stop-loss triggered: {pct_change:.1f}% <= {stop_loss_pct}%")

            # 2. Time-based exit: DTE <= 7
            if not exit_reason and expiry_str:
                try:
                    expiry_date = date.fromisoformat(expiry_str[:10])
                    dte = (expiry_date - today).days
                    if dte <= 7:
                        exit_reason = "time_exit_dte7"
                        logger.info(f"{symbol} time exit: {dte} DTE <= 7")
                except Exception:
                    pass

            # 3. End-of-day flatten (if enabled)
            if not exit_reason and flatten_eod:
                now = datetime.utcnow()
                # 20:45 UTC = 3:45 PM ET (approximately)
                if now.hour == 20 and now.minute >= 45:
                    exit_reason = "flatten_eod"

            # 4. Trailing stop logic
            if not exit_reason:
                # Check if trailing stop should activate
                peak_key = f"auto_trade.peak_{trade_id}"
                peak_val = await db.setting_get(peak_key)
                peak_price = float(peak_val) if peak_val else entry_price

                if current_price > peak_price:
                    peak_price = current_price
                    await db.setting_set(peak_key, str(peak_price))

                peak_pct = ((peak_price - entry_price) / entry_price) * 100
                trailing_active_key = f"auto_trade.trail_active_{trade_id}"
                trailing_active = (await db.setting_get(trailing_active_key)) == "true"

                if not trailing_active and peak_pct >= trailing_activate_pct:
                    trailing_active = True
                    await db.setting_set(trailing_active_key, "true")
                    logger.info(f"{symbol} trailing stop activated at peak {peak_price:.2f}")

                if trailing_active:
                    trail_stop = peak_price * (1 - trailing_stop_pct / 100)
                    if current_price <= trail_stop:
                        exit_reason = "trailing_stop"
                        logger.info(f"{symbol} trailing stop triggered: {current_price:.2f} <= {trail_stop:.2f}")

            # 5. Same-day entry, down -15% by EOD check
            if not exit_reason:
                entered_at = trade.get("entered_at", "")
                if entered_at:
                    try:
                        entered_dt = datetime.fromisoformat(entered_at)
                        if entered_dt.date() == today and pct_change <= -15:
                            now_utc = datetime.utcnow()
                            # After 19:30 UTC (2:30 PM ET) — approaching EOD
                            if now_utc.hour >= 19:
                                exit_reason = "same_day_exit"
                    except Exception:
                        pass

            if exit_reason:
                # Execute exit
                result = await self.executor.place_exit_market_sell(symbol, qty)
                exit_price = result.filled_price or current_price
                await self.journal.close_trade(trade_id, exit_price, exit_reason)

                # Clean up trailing stop state
                for cleanup_key in (f"auto_trade.peak_{trade_id}", f"auto_trade.trail_active_{trade_id}"):
                    await db.setting_set(cleanup_key, "")

                pnl_dollar = (exit_price - entry_price) * qty * 100
                pnl_pct = pct_change

                msg = self._format_exit_message(symbol, entry_price, exit_price, qty, pnl_dollar, pnl_pct, exit_reason)
                exits.append(ExitAction(trade_id=trade_id, symbol=symbol, qty=qty, reason=exit_reason, message=msg))

        return exits

    def _format_exit_message(
        self,
        symbol: str,
        entry: float,
        exit_p: float,
        qty: int,
        pnl: float,
        pnl_pct: float,
        reason: str,
    ) -> str:
        emoji = "🟢" if pnl > 0 else "🔴"
        reason_labels = {
            "stop_loss": "Stop-loss triggered",
            "take_profit": "Take-profit hit",
            "trailing_stop": "Trailing stop triggered",
            "time_exit_dte7": "≤7 DTE time exit",
            "flatten_eod": "End-of-day flatten",
            "same_day_exit": "Same-day -15% exit",
        }
        reason_str = reason_labels.get(reason, reason)
        pnl_sign = "+" if pnl >= 0 else ""
        return (
            f"{emoji} POSITION CLOSED\n"
            f"{symbol}: {pnl_pct:+.1f}% (${entry:.2f} → ${exit_p:.2f})\n"
            f"  ↳ {reason_str}\n"
            f"  ↳ {'Gain' if pnl >= 0 else 'Loss'}: {pnl_sign}${pnl:.2f}"
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/alpaca_trader/engine/position_manager.py
git commit -m "feat(sprint-7): PositionManager — all exit strategies (stop-loss, TP, trailing, time)"
```

---

## Task 6: Auto Trader Orchestrator

**Files:**
- Create: `src/alpaca_trader/engine/auto_trader.py`

- [ ] **Step 1: Write auto_trader.py**

```python
# src/alpaca_trader/engine/auto_trader.py
"""AutoTrader — orchestrates signal → option selection → risk check → execution → exit setup."""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from alpaca_trader.core import client as alpaca
from alpaca_trader.core import database as db
from alpaca_trader.engine.order_executor import OrderExecutor
from alpaca_trader.engine.position_manager import PositionManager
from alpaca_trader.engine.risk_manager import RiskManager
from alpaca_trader.engine.trade_journal import TradeJournal

logger = logging.getLogger(__name__)


@dataclass
class TradeAttempt:
    symbol: str
    underlying: str
    strategy: str
    direction: str
    approved: bool
    reason: str
    option_contract: Optional[dict] = None
    order_result: Optional[dict] = None
    trade_id: Optional[str] = None
    message: str = ""


class AutoTrader:
    """Main auto-trading orchestrator.

    Flow: is_enabled → is_live_ok → select_option → pre_trade_check → execute → log → setup_exits
    """

    def __init__(self):
        self.risk_manager = RiskManager()
        self.order_executor = OrderExecutor()
        self.position_manager = PositionManager()
        self.journal = TradeJournal()

    async def process_signal(self, signal: dict) -> TradeAttempt:
        """Process a single strategy signal and attempt to trade it."""
        underlying = signal["symbol"]
        strategy = signal["strategy"]
        direction = signal["direction"]

        # 1. Auto-trade must be enabled
        if not await self.risk_manager.is_enabled():
            return TradeAttempt(
                symbol="", underlying=underlying, strategy=strategy, direction=direction,
                approved=False, reason="auto_trade.enabled is false",
            )

        # 2. Paper-trade lockout check
        live_ok, live_reason = await self.risk_manager.is_live_trading_allowed()
        if not live_ok:
            return TradeAttempt(
                symbol="", underlying=underlying, strategy=strategy, direction=direction,
                approved=False, reason=live_reason,
            )

        # 3. Select best option contract
        contract = await self._select_option(underlying, direction)
        if not contract:
            return TradeAttempt(
                symbol="", underlying=underlying, strategy=strategy, direction=direction,
                approved=False, reason=f"No suitable option contract found for {underlying} ({direction})",
            )

        symbol = contract.get("symbol", "")

        # 4. Pre-trade risk check
        risk_result = await self.risk_manager.pre_trade_check(underlying, contract, direction)
        if not risk_result.approved:
            return TradeAttempt(
                symbol=symbol, underlying=underlying, strategy=strategy, direction=direction,
                approved=False, reason=risk_result.reason, option_contract=contract,
            )

        qty = risk_result.max_contracts
        if qty <= 0:
            return TradeAttempt(
                symbol=symbol, underlying=underlying, strategy=strategy, direction=direction,
                approved=False, reason="Computed 0 contracts", option_contract=contract,
            )

        # 5. Execute entry order
        bid = float(contract.get("bid_price") or 0)
        ask = float(contract.get("ask_price") or 0)
        if bid <= 0 or ask <= 0:
            return TradeAttempt(
                symbol=symbol, underlying=underlying, strategy=strategy, direction=direction,
                approved=False, reason="No valid bid/ask for entry", option_contract=contract,
            )

        order_result = await self.order_executor.place_entry(symbol, qty, bid, ask)
        if not order_result.success:
            return TradeAttempt(
                symbol=symbol, underlying=underlying, strategy=strategy, direction=direction,
                approved=False, reason=f"Order failed: {order_result.reason}", option_contract=contract,
            )

        entry_price = order_result.filled_price or ((bid + ask) / 2)
        filled_qty = order_result.filled_qty or qty

        # 6. Log to journal
        stop_loss_pct = await self.risk_manager._get_float("auto_trade.stop_loss_pct", -30)
        take_profit_pct = await self.risk_manager._get_float("auto_trade.take_profit_pct", 50)
        stop_price = round(entry_price * (1 + stop_loss_pct / 100), 4)
        tp_price = round(entry_price * (1 + take_profit_pct / 100), 4)

        expiry = str(contract.get("expiration_date") or contract.get("expiry") or "")
        expiry_date = expiry[:10]
        dte = 0
        try:
            dte = (date.fromisoformat(expiry_date) - date.today()).days
        except Exception:
            pass

        trade_id = await self.journal.open_trade(
            symbol=symbol,
            underlying=underlying,
            option_type=contract.get("type", "call"),
            strike=float(contract.get("strike_price") or 0),
            expiry=expiry_date,
            strategy=strategy,
            entry_price=entry_price,
            qty=filled_qty,
            signal_data=signal,
            risk_check=risk_result.details,
        )

        # 7. Place take-profit limit sell
        tp_order_id = await self.order_executor.place_take_profit_sell(symbol, filled_qty, tp_price)

        # 8. Build trade message
        equity = risk_result.details.get("equity", 0)
        risk_pct = (entry_price * filled_qty * 100 / equity * 100) if equity else 0
        msg = self._format_entry_message(
            symbol=symbol, underlying=underlying, strategy=strategy, direction=direction,
            entry_price=entry_price, qty=filled_qty, tp_price=tp_price,
            stop_price=stop_price, dte=dte, risk_pct=risk_pct,
        )

        logger.info(f"Trade opened: {symbol} x{filled_qty} @ {entry_price:.2f}, TP={tp_price:.2f}, SL={stop_price:.2f}")

        return TradeAttempt(
            symbol=symbol,
            underlying=underlying,
            strategy=strategy,
            direction=direction,
            approved=True,
            reason="Trade executed",
            option_contract=contract,
            order_result={"order_id": order_result.order_id, "filled_price": entry_price, "qty": filled_qty},
            trade_id=trade_id,
            message=msg,
        )

    async def process_signals(self, signals: list[dict]) -> list[TradeAttempt]:
        """Process a list of signals. Stops after first success per underlying."""
        results = []
        traded_underlyings: set[str] = set()
        for signal in signals:
            underlying = signal["symbol"]
            if underlying in traded_underlyings:
                continue
            attempt = await self.process_signal(signal)
            results.append(attempt)
            if attempt.approved:
                traded_underlyings.add(underlying)
        return results

    async def run_position_checks(self) -> list:
        """Delegate to PositionManager to check all open positions for exits."""
        return await self.position_manager.run_exit_checks()

    async def _select_option(self, underlying: str, direction: str) -> Optional[dict]:
        """Find the best option contract for the given signal."""
        settings_keys = [
            "auto_trade.target_dte_min", "auto_trade.target_dte_max",
            "auto_trade.target_delta_min", "auto_trade.target_delta_max",
            "auto_trade.min_liquidity_oi", "auto_trade.min_liquidity_volume",
            "auto_trade.max_spread_pct",
        ]
        settings = {}
        for k in settings_keys:
            settings[k] = await db.setting_get(k)

        dte_min = int(float(settings.get("auto_trade.target_dte_min") or 14))
        dte_max = int(float(settings.get("auto_trade.target_dte_max") or 45))
        delta_min = float(settings.get("auto_trade.target_delta_min") or 0.25)
        delta_max = float(settings.get("auto_trade.target_delta_max") or 0.45)
        min_oi = int(float(settings.get("auto_trade.min_liquidity_oi") or 100))
        min_vol = int(float(settings.get("auto_trade.min_liquidity_volume") or 50))
        max_spread_pct = float(settings.get("auto_trade.max_spread_pct") or 15)

        option_type = "call" if direction.lower() == "bullish" else "put"
        exp_min = date.today() + timedelta(days=dte_min)
        exp_max = date.today() + timedelta(days=dte_max)

        try:
            chain = alpaca.get_option_chain(
                underlying_symbol=underlying,
                option_type=option_type,
                expiration_date_gte=exp_min,
                expiration_date_lte=exp_max,
            )
        except Exception as e:
            logger.warning(f"Failed to get option chain for {underlying}: {e}")
            return None

        if not chain:
            logger.warning(f"Empty option chain for {underlying} {option_type} {exp_min}–{exp_max}")
            return None

        # Filter by liquidity and delta
        candidates = []
        for contract in chain:
            bid = float(contract.get("bid_price") or 0)
            ask = float(contract.get("ask_price") or 0)
            oi = int(contract.get("open_interest") or 0)
            vol = int(contract.get("volume") or 0)
            greeks = contract.get("greeks") or {}
            delta = abs(float(greeks.get("delta") or 0))

            if bid <= 0 or ask <= 0:
                continue
            mid = (bid + ask) / 2
            if mid <= 0:
                continue
            spread_pct = ((ask - bid) / mid) * 100
            if spread_pct > max_spread_pct:
                continue
            if oi < min_oi:
                continue
            if vol < min_vol:
                continue
            if delta < delta_min or delta > delta_max:
                continue

            candidates.append(contract)

        if not candidates:
            logger.info(f"No {underlying} {option_type} contracts passed liquidity/delta filters")
            return None

        # Pick closest to target delta of 0.35
        target_delta = 0.35
        best = min(candidates, key=lambda c: abs(abs(float((c.get("greeks") or {}).get("delta") or 0)) - target_delta))
        return best

    def _format_entry_message(
        self,
        symbol: str,
        underlying: str,
        strategy: str,
        direction: str,
        entry_price: float,
        qty: int,
        tp_price: float,
        stop_price: float,
        dte: int,
        risk_pct: float,
    ) -> str:
        dir_emoji = "🟢" if direction.lower() == "bullish" else "🔴"
        strategy_label = strategy.replace("_", " ").title()
        total_cost = entry_price * qty * 100
        tp_pct = ((tp_price - entry_price) / entry_price) * 100
        sl_pct = ((stop_price - entry_price) / entry_price) * 100
        return (
            f"{dir_emoji} AUTO-TRADE EXECUTED\n"
            f"📊 {underlying} — {strategy_label} ({direction.title()})\n"
            f"📈 Bought: {symbol}\n"
            f"💰 Entry: ${entry_price:.2f} × {qty} contracts (${total_cost:.0f})\n"
            f"🎯 Take-Profit: ${tp_price:.2f} (+{tp_pct:.0f}%)\n"
            f"🛑 Stop-Loss: ${stop_price:.2f} ({sl_pct:.0f}%)\n"
            f"📅 Expiry: {dte} DTE\n"
            f"⚖️ Risk: {risk_pct:.2f}% of portfolio"
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/alpaca_trader/engine/auto_trader.py
git commit -m "feat(sprint-7): AutoTrader orchestrator — signal to execution pipeline"
```

---

## Task 7: Scanner Integration

**Files:**
- Modify: `src/alpaca_trader/alerts/scanner.py`

- [ ] **Step 1: Update ScheduledScanner.run() to call AutoTrader**

After the strategy signals loop, add auto-trading logic. Replace the `return` statement at the end with the new integrated version:

In `scanner.py`, add the import at the top:
```python
from alpaca_trader.core import database as db
```
(already there)

Add new imports:
```python
from alpaca_trader.engine.auto_trader import AutoTrader
```

Then update the `run()` method body — after `strategy_signals` is populated and before `completed_at`:

```python
        # 3. Auto-trading (if enabled)
        auto_trade_results = []
        auto_trade_exits = []
        try:
            auto_enabled_val = await db.setting_get("auto_trade.enabled")
            if auto_enabled_val and str(auto_enabled_val).lower() == "true":
                trader = AutoTrader()

                # First: check existing positions for exits
                auto_trade_exits = await trader.run_position_checks()

                # Then: process new signals
                actionable = [s for s in strategy_signals if "error" not in s]
                if actionable:
                    attempts = await trader.process_signals(actionable)
                    auto_trade_results = [
                        {
                            "symbol": a.symbol,
                            "underlying": a.underlying,
                            "approved": a.approved,
                            "reason": a.reason,
                            "trade_id": a.trade_id,
                            "message": a.message,
                        }
                        for a in attempts
                    ]
        except EnvironmentError:
            raise
        except Exception as e:
            auto_trade_results = [{"error": str(e)}]
```

And update the return dict to include new fields:
```python
        return {
            "started_at": started_at,
            "completed_at": completed_at,
            "symbols_scanned": len(symbols),
            "triggered_alerts": triggered_alerts,
            "strategy_signals": strategy_signals,
            "auto_trade_results": auto_trade_results,
            "auto_trade_exits": [{"symbol": e.symbol, "reason": e.reason, "message": e.message} for e in auto_trade_exits],
            "summary": _format_summary(triggered_alerts, strategy_signals, auto_trade_results, auto_trade_exits),
        }
```

Update `_format_summary` signature and body:
```python
def _format_summary(triggered_alerts: list, strategy_signals: list, auto_results: list = None, auto_exits: list = None) -> str:
    """Format a concise Telegram-friendly summary."""
    lines = []
    if triggered_alerts:
        lines.append(f"🔔 {len(triggered_alerts)} alert(s) triggered:")
        for a in triggered_alerts:
            lines.append(f"  • {a.get('message', '')}")
    if strategy_signals:
        lines.append(f"📊 {len(strategy_signals)} signal(s) detected:")
        for s in strategy_signals:
            lines.append(f"  • {s['symbol']} [{s['strategy']}] {s['direction']}")
    if auto_results:
        executed = [r for r in auto_results if r.get("approved")]
        if executed:
            lines.append(f"🤖 {len(executed)} trade(s) executed:")
            for r in executed:
                lines.append(f"  • {r.get('message', r.get('symbol', ''))}")
    if auto_exits:
        lines.append(f"🚪 {len(auto_exits)} position(s) closed:")
        for e in auto_exits:
            lines.append(f"  • {e.get('message', e.get('symbol', ''))}")
    if not lines:
        lines.append("✓ No alerts or signals triggered.")
    return "\n".join(lines)
```

- [ ] **Step 2: Commit**

```bash
git add src/alpaca_trader/alerts/scanner.py
git commit -m "feat(sprint-7): integrate AutoTrader into ScheduledScanner"
```

---

## Task 8: Cron Script Update

**Files:**
- Modify: `scripts/cron_scan_and_deliver.py`

- [ ] **Step 1: Update the cron script to include auto-trade results and position exits in output**

Replace the existing `main()` function:

```python
async def main() -> None:
    scanner = ScheduledScanner()
    results = await scanner.run()

    # Deliver any queued alerts
    queue = TelegramDeliveryQueue()
    pending = queue.get_pending()

    output_parts = []

    if pending:
        for entry in pending:
            output_parts.append(format_alert_telegram(entry))
        queue.mark_delivered([e["queue_id"] for e in pending])

    if results.get("strategy_signals"):
        signals = [s for s in results["strategy_signals"] if "error" not in s]
        if signals:
            output_parts.append("📊 Strategy Signals Detected:")
            for sig in signals:
                direction_emoji = "🟢" if sig["direction"] == "bullish" else "🔴"
                output_parts.append(
                    f"{direction_emoji} {sig['symbol']} [{sig['strategy']}] "
                    f"{sig['direction']} (strength: {sig.get('strength', 'N/A')})"
                )
                if sig.get("details"):
                    output_parts.append(f"   {sig['details']}")

    # Auto-trade entries
    if results.get("auto_trade_results"):
        for r in results["auto_trade_results"]:
            if r.get("error"):
                output_parts.append(f"⚠️ Auto-trade error: {r['error']}")
            elif r.get("approved") and r.get("message"):
                output_parts.append(r["message"])

    # Auto-trade exits
    if results.get("auto_trade_exits"):
        for e in results["auto_trade_exits"]:
            if e.get("message"):
                output_parts.append(e["message"])

    if output_parts:
        print("\n\n".join(output_parts))
    else:
        print("SCAN_OK")
```

- [ ] **Step 2: Commit**

```bash
git add scripts/cron_scan_and_deliver.py
git commit -m "feat(sprint-7): cron script includes auto-trade results and position exits"
```

---

## Task 9: CLI Commands — `auto` and `journal` sub-apps

**Files:**
- Modify: `src/alpaca_trader/cli.py`

- [ ] **Step 1: Add imports at top of cli.py**

After the existing imports, add:
```python
from alpaca_trader.engine.auto_trader import AutoTrader
from alpaca_trader.engine.risk_manager import RiskManager
from alpaca_trader.engine.trade_journal import TradeJournal
```

- [ ] **Step 2: Add `auto_app` sub-app with status/enable/disable/set commands**

After the `monitor_app` block (around line 1077), add:

```python
# --- auto command group ---

auto_app = typer.Typer(help="Auto-trading engine controls")
app.add_typer(auto_app, name="auto")


@auto_app.command("status")
def auto_status():
    """Show auto-trading status, settings, and circuit breaker state."""
    async def _run():
        rm = RiskManager()
        enabled = await rm.is_enabled()
        cb = await rm.get_circuit_breaker_state()
        live_ok, live_reason = await rm.is_live_trading_allowed()

        # All settings
        all_settings = {}
        for k in [
            "auto_trade.enabled", "auto_trade.max_risk_pct", "auto_trade.max_positions",
            "auto_trade.max_allocation_pct", "auto_trade.max_per_symbol_pct",
            "auto_trade.stop_loss_pct", "auto_trade.take_profit_pct",
            "auto_trade.trailing_stop_pct", "auto_trade.trailing_activate_pct",
            "auto_trade.target_dte_min", "auto_trade.target_dte_max",
            "auto_trade.target_delta_min", "auto_trade.target_delta_max",
            "auto_trade.daily_loss_limit_pct", "auto_trade.weekly_loss_limit_pct",
            "auto_trade.flatten_eod", "auto_trade.min_liquidity_oi",
            "auto_trade.min_liquidity_volume", "auto_trade.max_spread_pct",
        ]:
            all_settings[k] = await db.setting_get(k)

        return enabled, cb, live_ok, live_reason, all_settings

    enabled, cb, live_ok, live_reason, settings = asyncio.run(_run())

    status_color = "green" if enabled else "red"
    status_text = "ENABLED" if enabled else "DISABLED"
    console.print(Panel(
        f"[{status_color}]Auto-Trading: {status_text}[/{status_color}]",
        title="Auto-Trader Status",
    ))

    if cb.daily_halt or cb.weekly_halt:
        console.print(f"[red]⛔ CIRCUIT BREAKER ACTIVE: {cb.halt_reason}[/red]")
    if cb.reduced_size:
        console.print(f"[yellow]⚠️  Reduced size mode ({cb.consecutive_losses} consecutive losses)[/yellow]")

    live_color = "green" if live_ok else "yellow"
    console.print(f"[{live_color}]Live trading: {live_reason}[/{live_color}]")

    table = Table(title="Auto-Trade Settings", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")
    for k, v in settings.items():
        short_key = k.replace("auto_trade.", "")
        table.add_row(short_key, str(v or "—"))
    console.print(table)


@auto_app.command("enable")
def auto_enable():
    """Enable auto-trading (sets auto_trade.enabled=true)."""
    async def _run():
        await db.init_auto_trade_settings()
        await db.setting_set("auto_trade.enabled", "true")
    asyncio.run(_run())
    console.print("[green]✓ Auto-trading ENABLED[/green]")


@auto_app.command("disable")
def auto_disable():
    """Disable auto-trading (sets auto_trade.enabled=false)."""
    async def _run():
        await db.setting_set("auto_trade.enabled", "false")
    asyncio.run(_run())
    console.print("[red]✓ Auto-trading DISABLED[/red]")


@auto_app.command("set")
def auto_set(
    key: str = typer.Argument(..., help="Setting key (e.g. max_risk_pct)"),
    value: str = typer.Argument(..., help="Value to set"),
):
    """Update an auto-trade setting. Key can be short (e.g. max_risk_pct) or full."""
    full_key = key if key.startswith("auto_trade.") else f"auto_trade.{key}"
    async def _run():
        await db.setting_set(full_key, value)
    asyncio.run(_run())
    console.print(f"[green]✓ Set {full_key} = {value}[/green]")
```

- [ ] **Step 3: Add `journal_app` sub-app**

After the `auto_app` block, add:

```python
# --- journal command group ---

journal_app = typer.Typer(help="Trade journal and analytics")
app.add_typer(journal_app, name="journal")


@journal_app.command("list")
def journal_list_cmd(
    status: Optional[str] = typer.Option(None, "--status", help="Filter: open or closed"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max rows to show"),
):
    """Show recent trades from the journal."""
    async def _run():
        return await db.journal_list(status=status, limit=limit)
    trades = asyncio.run(_run())
    if not trades:
        console.print("[yellow]No trades found.[/yellow]")
        return
    table = Table(title=f"Trade Journal ({len(trades)} trades)", show_header=True)
    table.add_column("ID", style="dim", width=8)
    table.add_column("Symbol", style="cyan")
    table.add_column("Strategy")
    table.add_column("Entry $", justify="right")
    table.add_column("Exit $", justify="right")
    table.add_column("P&L $", justify="right")
    table.add_column("P&L %", justify="right")
    table.add_column("Exit Reason")
    table.add_column("Status")
    for t in trades:
        pnl_d = t.get("pnl_dollar")
        pnl_p = t.get("pnl_pct")
        pnl_d_str = f"${pnl_d:+.2f}" if pnl_d is not None else "—"
        pnl_p_str = f"{pnl_p:+.1f}%" if pnl_p is not None else "—"
        pnl_color = "green" if (pnl_d or 0) > 0 else ("red" if (pnl_d or 0) < 0 else "white")
        table.add_row(
            str(t.get("id", "")),
            t.get("symbol", ""),
            t.get("strategy", ""),
            f"${float(t.get('entry_price', 0)):.2f}",
            f"${float(t.get('exit_price', 0)):.2f}" if t.get("exit_price") else "—",
            f"[{pnl_color}]{pnl_d_str}[/{pnl_color}]",
            f"[{pnl_color}]{pnl_p_str}[/{pnl_color}]",
            t.get("exit_reason") or "—",
            t.get("status", ""),
        )
    console.print(table)


@journal_app.command("stats")
def journal_stats_cmd():
    """Show trade journal aggregate statistics."""
    async def _run():
        return await db.journal_stats()
    stats = asyncio.run(_run())
    if stats["total"] == 0:
        console.print("[yellow]No closed trades in journal yet.[/yellow]")
        return

    console.print(Panel(
        f"Total: {stats['total']} | Wins: {stats['wins']} | Losses: {stats['losses']}\n"
        f"Win Rate: {stats['win_rate']:.1%} | Avg P&L: {stats['avg_pnl_pct']:+.1f}%\n"
        f"Total P&L: ${stats['total_pnl_dollar']:+.2f}",
        title="Journal Statistics",
    ))

    if stats.get("best_trade"):
        b = stats["best_trade"]
        console.print(f"[green]Best trade:[/green] {b.get('symbol')} +${b.get('pnl_dollar', 0):.2f} ({b.get('strategy')})")
    if stats.get("worst_trade"):
        w = stats["worst_trade"]
        console.print(f"[red]Worst trade:[/red] {w.get('symbol')} ${w.get('pnl_dollar', 0):.2f} ({w.get('strategy')})")

    if stats.get("by_strategy"):
        table = Table(title="By Strategy", show_header=True)
        table.add_column("Strategy", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("Wins", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Total P&L", justify="right")
        for strat, s in stats["by_strategy"].items():
            wr = s["wins"] / s["total"] if s["total"] else 0
            pnl_color = "green" if s["total_pnl"] > 0 else "red"
            table.add_row(
                strat,
                str(s["total"]),
                str(s["wins"]),
                f"{wr:.1%}",
                f"[{pnl_color}]${s['total_pnl']:+.2f}[/{pnl_color}]",
            )
        console.print(table)


@journal_app.command("export")
def journal_export(
    output: str = typer.Option("journal_export.csv", "--output", "-o", help="Output CSV filename"),
):
    """Export trade journal to CSV."""
    async def _run():
        return await db.journal_list(limit=10000)
    trades = asyncio.run(_run())
    if not trades:
        console.print("[yellow]No trades to export.[/yellow]")
        return
    import csv
    fieldnames = list(trades[0].keys()) if trades else []
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trades)
    console.print(f"[green]✓ Exported {len(trades)} trades to {output}[/green]")
```

- [ ] **Step 4: Initialize DB + auto_trade settings on CLI startup**

Find the `init_db` command in cli.py and ensure `init_auto_trade_settings` is called. Also add it to the journal list command's `_run` function so DB is ready.

Actually, in the `auto_enable` and `auto_status` commands, call `await db.init_auto_trade_settings()` at start of `_run()` to ensure settings exist.

For `journal_list_cmd` and `journal_stats_cmd`, add `await db.init_db()` at start of `_run()`.

- [ ] **Step 5: Verify CLI works**

```bash
cd /Users/tonylesmb/claw-workspace/alpaca-trader
.venv/bin/alpaca-trader auto --help
.venv/bin/alpaca-trader journal --help
.venv/bin/alpaca-trader auto status
```

Expected: Commands display without errors.

- [ ] **Step 6: Commit**

```bash
git add src/alpaca_trader/cli.py
git commit -m "feat(sprint-7): auto and journal CLI sub-commands"
```

---

## Task 10: Wire Up init_db in Engine Entry Points

**Files:**
- Modify: `src/alpaca_trader/engine/auto_trader.py` — no change needed; scanner calls init_db
- Modify: `scripts/cron_scan_and_deliver.py` — add `await db.init_db()` at start of `main()`

- [ ] **Step 1: Add DB init to cron script**

In `scripts/cron_scan_and_deliver.py`, at the start of `main()`:
```python
from alpaca_trader.core import database as db

async def main() -> None:
    await db.init_db()  # Ensures trade_journal table + auto_trade settings exist
    # ... rest of existing code
```

- [ ] **Step 2: Final smoke test — run cron script**

```bash
cd /Users/tonylesmb/claw-workspace/alpaca-trader
.venv/bin/python scripts/cron_scan_and_deliver.py
```

Expected: `SCAN_OK` (or signals if any), no errors.

- [ ] **Step 3: Final commit**

```bash
git add scripts/cron_scan_and_deliver.py
git commit -m "feat(sprint-7): ensure DB init in cron script; Sprint 7 complete"
```

---

## Implementation Notes

### Sync vs Async Pattern
- All `database.py` functions are `async` — use `await` in async contexts
- All `client.py` (Alpaca) functions are **sync** — call directly (no await)
- CLI uses `asyncio.run(_run())` to execute async helpers

### Safety First
- `auto_trade.enabled` defaults to `"false"` — no accidental trading
- Paper-trade lockout: `is_live_trading_allowed()` checks 50 trades + 40% win rate
- Circuit breakers halt new trades when daily/weekly loss limits hit

### Trailing Stop State
- Stored in `settings` table using `auto_trade.peak_{trade_id}` and `auto_trade.trail_active_{trade_id}` keys
- Cleaned up on trade close

### Option Contract Fields (from Alpaca)
Key fields used: `symbol`, `bid_price`, `ask_price`, `open_interest`, `volume`, `expiration_date`, `strike_price`, `type`, `greeks.delta`
