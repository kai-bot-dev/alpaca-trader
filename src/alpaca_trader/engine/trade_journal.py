"""Trade journal — logs all trades with entry/exit prices, P&L, and strategy."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Optional

from alpaca_trader.core.database import DATABASE_URL

import aiosqlite

logger = logging.getLogger(__name__)


class TradeJournal:
    """Log all trades with entry/exit prices, timestamps, P&L, strategy used."""

    def __init__(self, db_url: Optional[str] = None) -> None:
        self._db_url = db_url or DATABASE_URL

    async def log_entry(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        strategy: str,
        signal_details: Optional[dict] = None,
        option_symbol: Optional[str] = None,
        option_type: Optional[str] = None,
        strike_price: Optional[float] = None,
        expiry_date: Optional[str] = None,
        premium_paid: Optional[float] = None,
        contracts: Optional[int] = None,
        delta_at_entry: Optional[float] = None,
        theta_at_entry: Optional[float] = None,
        iv_at_entry: Optional[float] = None,
    ) -> int:
        """Log a new trade entry. Returns the trade_id.

        For options trades, pass option-specific kwargs (option_symbol, option_type, etc.).
        """
        entry_time = datetime.now(timezone.utc).isoformat()
        details_json = json.dumps(signal_details or {})
        async with aiosqlite.connect(self._db_url) as db:
            cursor = await db.execute(
                """INSERT INTO trade_journal
                   (symbol, side, qty, entry_price, strategy, signal_details, entry_time, status,
                    option_symbol, option_type, strike_price, expiry_date, premium_paid,
                    contracts, delta_at_entry, theta_at_entry, iv_at_entry)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    symbol.upper(), side.lower(), qty, price, strategy, details_json, entry_time,
                    option_symbol, option_type, strike_price, expiry_date, premium_paid,
                    contracts, delta_at_entry, theta_at_entry, iv_at_entry,
                ),
            )
            await db.commit()
            trade_id = cursor.lastrowid
        logger.info(
            "Trade entry logged",
            extra={"trade_id": trade_id, "symbol": symbol, "side": side, "qty": qty, "price": price},
        )
        return trade_id

    async def log_exit(self, trade_id: int, price: float, reason: str) -> None:
        """Log the exit for an open trade, computing P&L."""
        exit_time = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_url) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trade_journal WHERE id = ? AND status = 'open'", (trade_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                logger.warning("log_exit: trade %d not found or already closed", trade_id)
                return

            entry_price = row["entry_price"]
            qty = row["qty"]
            side = row["side"]

            if side == "buy":
                pnl = (price - entry_price) * qty
                pnl_pct = (price - entry_price) / entry_price if entry_price else 0.0
            else:
                pnl = (entry_price - price) * qty
                pnl_pct = (entry_price - price) / entry_price if entry_price else 0.0

            await db.execute(
                """UPDATE trade_journal
                   SET exit_price=?, exit_time=?, pnl=?, pnl_pct=?, exit_reason=?, status='closed'
                   WHERE id=?""",
                (price, exit_time, pnl, pnl_pct, reason, trade_id),
            )
            await db.commit()
        logger.info(
            "Trade exit logged",
            extra={"trade_id": trade_id, "exit_price": price, "reason": reason, "pnl": pnl},
        )

    async def get_trades(
        self,
        limit: int = 50,
        strategy: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        """Return recent trades, optionally filtered by strategy or status."""
        async with aiosqlite.connect(self._db_url) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM trade_journal WHERE 1=1"
            params: list = []
            if strategy:
                query += " AND strategy = ?"
                params.append(strategy)
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY entry_time DESC LIMIT ?"
            params.append(limit)
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                try:
                    d["signal_details"] = json.loads(d.get("signal_details") or "{}")
                except Exception:
                    d["signal_details"] = {}
                result.append(d)
            return result

    async def get_stats(self) -> dict:
        """Return journal statistics: win_rate, avg_pnl, total_trades, sharpe."""
        async with aiosqlite.connect(self._db_url) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT pnl, pnl_pct FROM trade_journal WHERE status = 'closed'"
            )
            rows = await cursor.fetchall()

        if not rows:
            return {
                "total_trades": 0,
                "open_trades": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "total_pnl": 0.0,
                "sharpe": 0.0,
            }

        pnls = [row["pnl"] for row in rows if row["pnl"] is not None]
        winners = [p for p in pnls if p > 0]
        total = len(pnls)
        win_rate = len(winners) / total if total else 0.0
        avg_pnl = sum(pnls) / total if total else 0.0
        total_pnl = sum(pnls)

        # Sharpe: mean / std of pnl_pcts (annualized approximation skipped; raw ratio)
        if total > 1:
            mean = sum(pnls) / total
            variance = sum((p - mean) ** 2 for p in pnls) / (total - 1)
            std = math.sqrt(variance) if variance > 0 else 0.0
            sharpe = mean / std if std > 0 else 0.0
        else:
            sharpe = 0.0

        # Count open trades
        async with aiosqlite.connect(self._db_url) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM trade_journal WHERE status = 'open'"
            )
            row = await cursor.fetchone()
            open_trades = row[0] if row else 0

        return {
            "total_trades": total,
            "open_trades": open_trades,
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "total_pnl": total_pnl,
            "sharpe": sharpe,
        }

    async def get_trade_count(self) -> int:
        """Return total number of closed trades (for the 50-trade paper lockout)."""
        async with aiosqlite.connect(self._db_url) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM trade_journal WHERE status = 'closed'"
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_open_trade_for_symbol(self, symbol: str) -> Optional[dict]:
        """Return the open trade for a symbol, if any."""
        async with aiosqlite.connect(self._db_url) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trade_journal WHERE symbol = ? AND status = 'open' ORDER BY entry_time DESC LIMIT 1",
                (symbol.upper(),),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            d = dict(row)
            try:
                d["signal_details"] = json.loads(d.get("signal_details") or "{}")
            except Exception:
                d["signal_details"] = {}
            return d
