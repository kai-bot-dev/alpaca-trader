"""SQLite database setup and operations for alpaca-trader."""

import os
from datetime import datetime
from pathlib import Path
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

        # App settings / key-value store
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

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
        cursor = await db.execute(
            "SELECT * FROM watchlist ORDER BY added_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# --- Order History Operations ---

async def upsert_order(order_data: dict) -> None:
    """Insert or update an order in local history."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        import json
        await db.execute("""
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
        """, (
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
            datetime.utcnow().isoformat(),
        ))
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


async def alert_list(symbol: Optional[str] = None, active_only: bool = True) -> list[dict]:
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
