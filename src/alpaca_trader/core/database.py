"""SQLite database setup and operations for alpaca-trader."""

import os
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "./alpaca_trader.db")


async def get_db() -> aiosqlite.Connection:
    """Get a database connection."""
    db = await aiosqlite.connect(DATABASE_URL)
    db.row_factory = aiosqlite.Row
    return db


async def init_db() -> None:
    """Initialize the database schema."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        # Watchlist table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        """)

        # Order history cache table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS order_history (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL,
                filled_qty REAL,
                order_type TEXT NOT NULL,
                status TEXT NOT NULL,
                limit_price REAL,
                filled_avg_price REAL,
                submitted_at TIMESTAMP,
                filled_at TIMESTAMP,
                canceled_at TIMESTAMP,
                asset_class TEXT,
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Alert config table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alert_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                threshold_value REAL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                triggered_at TIMESTAMP,
                notes TEXT
            )
        """)

        # Strategy signal log
        await db.execute("""
            CREATE TABLE IF NOT EXISTS signal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                signal_data TEXT,
                timeframe TEXT,
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Position P&L snapshots
        await db.execute("""
            CREATE TABLE IF NOT EXISTS position_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                qty REAL NOT NULL,
                avg_entry REAL NOT NULL,
                current_price REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                realized_pnl REAL NOT NULL DEFAULT 0.0
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_time
            ON position_snapshots (symbol, timestamp)
        """)

        # App settings / key-value store
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Sprint 5: Alerts table (richer schema with condition_json and message)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                condition_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                triggered_at TIMESTAMP,
                message TEXT
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_status
            ON alerts (status)
        """)

        # Trade journal (Sprint 7)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trade_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                strategy TEXT,
                signal_details TEXT,
                entry_time TEXT NOT NULL,
                exit_time TEXT,
                pnl REAL,
                pnl_pct REAL,
                exit_reason TEXT,
                status TEXT DEFAULT 'open'
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_trade_journal_status
            ON trade_journal (status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_trade_journal_strategy
            ON trade_journal (strategy)
        """)

        # Options fields on trade_journal (Sprint 9) — migration-safe
        _option_columns = [
            ("option_symbol", "TEXT"),
            ("option_type", "TEXT"),
            ("strike_price", "REAL"),
            ("expiry_date", "TEXT"),
            ("premium_paid", "REAL"),
            ("contracts", "INTEGER"),
            ("delta_at_entry", "REAL"),
            ("theta_at_entry", "REAL"),
            ("iv_at_entry", "REAL"),
        ]
        for col_name, col_type in _option_columns:
            try:
                await db.execute(
                    f"ALTER TABLE trade_journal ADD COLUMN {col_name} {col_type}"
                )
            except Exception:
                pass  # Column already exists — safe to ignore

        await db.commit()


# --- Watchlist Operations ---


async def watchlist_add(symbol: str, notes: Optional[str] = None) -> bool:
    """Add a symbol to the watchlist. Returns True if added, False if already exists."""
    try:
        async with aiosqlite.connect(DATABASE_URL) as db:
            await db.execute(
                "INSERT INTO watchlist (symbol, notes) VALUES (?, ?)",
                (symbol.upper(), notes),
            )
            await db.commit()
            return True
    except aiosqlite.IntegrityError:
        return False


async def watchlist_remove(symbol: str) -> bool:
    """Remove a symbol from the watchlist. Returns True if removed."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute(
            "DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),)
        )
        await db.commit()
        return cursor.rowcount > 0


async def watchlist_list() -> list[dict]:
    """Get all watchlist items."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM watchlist ORDER BY added_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# --- Order History Operations ---


async def upsert_order(order_data: dict) -> None:
    """Insert or update an order in local history."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        import json

        await db.execute(
            """
            INSERT INTO order_history (
                id, symbol, side, qty, filled_qty, order_type, status,
                limit_price, filled_avg_price, submitted_at, filled_at,
                canceled_at, asset_class, raw_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                filled_qty=excluded.filled_qty,
                filled_avg_price=excluded.filled_avg_price,
                filled_at=excluded.filled_at,
                canceled_at=excluded.canceled_at,
                raw_json=excluded.raw_json,
                updated_at=excluded.updated_at
        """,
            (
                order_data.get("id"),
                order_data.get("symbol"),
                order_data.get("side"),
                order_data.get("qty"),
                order_data.get("filled_qty"),
                order_data.get("order_type") or order_data.get("type"),
                order_data.get("status"),
                order_data.get("limit_price"),
                order_data.get("filled_avg_price"),
                order_data.get("submitted_at"),
                order_data.get("filled_at"),
                order_data.get("canceled_at"),
                order_data.get("asset_class"),
                json.dumps(order_data),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()


async def get_orders(status: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Get orders from local history cache."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        if status:
            cursor = await db.execute(
                "SELECT * FROM order_history WHERE status = ? ORDER BY submitted_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM order_history ORDER BY submitted_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# --- Alert Config Operations ---


async def alert_add(
    symbol: str,
    alert_type: str,
    threshold_value: Optional[float] = None,
    notes: Optional[str] = None,
) -> int:
    """Add an alert configuration. Returns the new alert ID."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute(
            """INSERT INTO alert_config (symbol, alert_type, threshold_value, notes)
               VALUES (?, ?, ?, ?)""",
            (symbol.upper(), alert_type, threshold_value, notes),
        )
        await db.commit()
        return cursor.lastrowid


async def alert_list(
    symbol: Optional[str] = None, active_only: bool = True
) -> list[dict]:
    """Get alert configurations."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM alert_config WHERE 1=1"
        params = []
        if active_only:
            query += " AND is_active = 1"
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        query += " ORDER BY created_at DESC"
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# --- Position P&L Snapshot Operations ---


async def save_position_snapshot(snapshot: dict) -> int:
    """Save a single position snapshot. Returns the new row ID."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute(
            """INSERT INTO position_snapshots
               (symbol, qty, avg_entry, current_price, unrealized_pnl, realized_pnl)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                snapshot["symbol"].upper(),
                snapshot["qty"],
                snapshot["avg_entry"],
                snapshot["current_price"],
                snapshot["unrealized_pnl"],
                snapshot.get("realized_pnl", 0.0),
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def get_pnl_history(symbol: str, days: int = 30) -> list[dict]:
    """Get P&L snapshots for a symbol over the past N days."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM position_snapshots
               WHERE symbol = ?
                 AND timestamp >= datetime('now', ? || ' days')
               ORDER BY timestamp ASC""",
            (symbol.upper(), f"-{days}"),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def setting_get(key: str) -> Optional[str]:
    """Get a setting value by key."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else None


async def setting_set(key: str, value: str) -> None:
    """Set a setting value (upsert)."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute(
            """INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP""",
            (key, value),
        )
        await db.commit()


# --- Sprint 5: Alerts Operations ---


async def alerts_add(
    alert_type: str,
    symbol: str,
    condition: dict,
    message: Optional[str] = None,
) -> int:
    """Add an alert. Returns the new alert ID."""
    import json

    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute(
            """INSERT INTO alerts (alert_type, symbol, condition_json, status, message)
               VALUES (?, ?, ?, 'active', ?)""",
            (alert_type, symbol.upper(), json.dumps(condition), message),
        )
        await db.commit()
        return cursor.lastrowid


async def alerts_list(
    status: Optional[str] = "active",
    alert_type: Optional[str] = None,
    symbol: Optional[str] = None,
) -> list[dict]:
    """List alerts with optional filters."""
    import json

    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM alerts WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if alert_type:
            query += " AND alert_type = ?"
            params.append(alert_type)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        query += " ORDER BY created_at DESC"
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["condition"] = json.loads(d.pop("condition_json", "{}"))
            except Exception:
                d["condition"] = {}
            result.append(d)
        return result


async def alerts_get(alert_id: int) -> Optional[dict]:
    """Get a single alert by ID."""
    import json

    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["condition"] = json.loads(d.pop("condition_json", "{}"))
        except Exception:
            d["condition"] = {}
        return d


async def alerts_dismiss(alert_id: int) -> bool:
    """Dismiss an alert (set status='dismissed'). Returns True if found."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute(
            "UPDATE alerts SET status='dismissed' WHERE id = ?", (alert_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def alerts_mark_triggered(alert_id: int, message: str) -> None:
    """Mark an alert as triggered with a message."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute(
            """UPDATE alerts SET status='triggered', triggered_at=CURRENT_TIMESTAMP, message=?
               WHERE id = ?""",
            (message, alert_id),
        )
        await db.commit()


async def get_portfolio_pnl_summary() -> dict:
    """Get aggregate portfolio-level P&L stats from the latest snapshots per symbol."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        # Latest snapshot per symbol
        cursor = await db.execute("""
            SELECT s.*
            FROM position_snapshots s
            INNER JOIN (
                SELECT symbol, MAX(timestamp) AS max_ts
                FROM position_snapshots
                GROUP BY symbol
            ) latest ON s.symbol = latest.symbol AND s.timestamp = latest.max_ts
        """)
        rows = await cursor.fetchall()
        snapshots = [dict(row) for row in rows]

    if not snapshots:
        return {
            "total_unrealized_pnl": 0.0,
            "total_realized_pnl": 0.0,
            "total_pnl": 0.0,
            "position_count": 0,
            "winners": 0,
            "losers": 0,
            "win_rate": 0.0,
            "positions": [],
        }

    total_unrealized = sum(s["unrealized_pnl"] for s in snapshots)
    total_realized = sum(s["realized_pnl"] for s in snapshots)
    winners = sum(1 for s in snapshots if s["unrealized_pnl"] > 0)
    losers = sum(1 for s in snapshots if s["unrealized_pnl"] < 0)
    total = winners + losers

    return {
        "total_unrealized_pnl": total_unrealized,
        "total_realized_pnl": total_realized,
        "total_pnl": total_unrealized + total_realized,
        "position_count": len(snapshots),
        "winners": winners,
        "losers": losers,
        "win_rate": winners / total if total > 0 else 0.0,
        "positions": snapshots,
    }
