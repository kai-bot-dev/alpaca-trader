"""AutoTrader orchestrator — ties scanner → risk → execution → journal."""

from __future__ import annotations
import json

import logging
from datetime import datetime, timezone, time as dtime
from typing import Optional
from zoneinfo import ZoneInfo

from alpaca_trader.core import database as db
from alpaca_trader.engine.risk_manager import RiskManager
from alpaca_trader.engine.order_executor import OrderExecutor, ExecutorConfig
from alpaca_trader.engine.position_manager import PositionManager
from alpaca_trader.engine.trade_journal import TradeJournal
from alpaca_trader.strategies.scanner import WatchlistScanner

logger = logging.getLogger(__name__)

# US Eastern market hours
_ET = ZoneInfo("America/New_York")
_MARKET_OPEN = dtime(9, 30)
_MARKET_CLOSE = dtime(16, 0)

PAPER_TRADE_LOCKOUT = 50  # require N closed paper trades before live


def is_market_open(now: Optional[datetime] = None) -> bool:
    """Return True if US equities market is currently open (Mon-Fri, 9:30-16:00 ET)."""
    if now is None:
        now = datetime.now(timezone.utc)
    et_now = now.astimezone(_ET)
    if et_now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return _MARKET_OPEN <= et_now.time() < _MARKET_CLOSE


class AutoTrader:
    """Main auto-trading orchestrator. Designed to run every 5 min during market hours."""

    ENABLED_KEY = "auto_trader_enabled"

    def __init__(
        self,
        risk_manager: Optional[RiskManager] = None,
        order_executor: Optional[OrderExecutor] = None,
        position_manager: Optional[PositionManager] = None,
        trade_journal: Optional[TradeJournal] = None,
        scanner: Optional[WatchlistScanner] = None,
        dry_run: bool = False,
    ) -> None:
        self.risk_manager = risk_manager or RiskManager()
        if order_executor is None:
            cfg = ExecutorConfig(dry_run=dry_run)
            order_executor = OrderExecutor(config=cfg)
        self.order_executor = order_executor
        self.position_manager = position_manager or PositionManager()
        self.trade_journal = trade_journal or TradeJournal()
        self.scanner = scanner or WatchlistScanner()
        self._dry_run = dry_run
        self._trades_today: int = 0

    # ------------------------------------------------------------------
    # Enable / Disable
    # ------------------------------------------------------------------

    async def enable(self) -> None:
        """Enable auto-trading (persisted to DB settings)."""
        await db.setting_set(self.ENABLED_KEY, "true")
        logger.info("AutoTrader enabled")

    async def disable(self) -> None:
        """Disable auto-trading (persisted to DB settings)."""
        await db.setting_set(self.ENABLED_KEY, "false")
        logger.info("AutoTrader disabled")

    async def is_enabled(self) -> bool:
        """Return True if auto-trading is enabled in DB settings."""
        val = await db.setting_get(self.ENABLED_KEY)
        return val == "true"

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def status(self) -> dict:
        """Return engine status dict."""
        enabled = await self.is_enabled()
        trade_count = await self.trade_journal.get_trade_count()
        stats = await self.trade_journal.get_stats()
        return {
            "enabled": enabled,
            "dry_run": self._dry_run,
            "circuit_breaker": self.risk_manager.is_circuit_broken,
            "circuit_breaker_reason": self.risk_manager._circuit_broken_reason,
            "trades_today": self._trades_today,
            "closed_trades": trade_count,
            "paper_lockout_remaining": max(0, PAPER_TRADE_LOCKOUT - trade_count),
            "market_open": is_market_open(),
            "journal_stats": stats,
        }

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def run_cycle(self) -> dict:
        """Run one full auto-trade cycle.

        Steps:
        1. Check if enabled + market is open
        2. Check existing positions for exits
        3. Execute any exit orders
        4. Get new signals from scanner
        5. Run risk checks on each signal
        6. Execute approved entry orders
        7. Log everything to journal
        8. Return summary dict
        """
        summary: dict = {
            "enabled": False,
            "market_open": False,
            "exits_checked": 0,
            "exits_executed": 0,
            "signals_found": 0,
            "entries_approved": 0,
            "entries_executed": 0,
            "errors": [],
            "cycle_time": datetime.now(timezone.utc).isoformat(),
        }

        # Step 1: Guard checks
        enabled = await self.is_enabled()
        summary["enabled"] = enabled
        market_open = is_market_open()
        summary["market_open"] = market_open

        if not enabled:
            logger.info("AutoTrader: cycle skipped — not enabled")
            return summary
        if not market_open:
            logger.info("AutoTrader: cycle skipped — market closed")
            return summary
        if self.risk_manager.is_circuit_broken:
            summary["errors"].append(
                f"Circuit breaker tripped: {self.risk_manager._circuit_broken_reason}"
            )
            logger.warning("AutoTrader: cycle skipped — circuit breaker tripped")
            return summary

        # Step 2: Get account info
        try:
            from alpaca_trader.core import client as alpaca

            account = alpaca.get_account()
            portfolio_value = float(account.get("portfolio_value") or 0)
            cash = float(account.get("cash") or 0)
            daily_pnl = (
                float(account.get("equity", portfolio_value) or 0) - portfolio_value
            )
        except Exception as e:
            summary["errors"].append(f"Account fetch failed: {e}")
            logger.error("AutoTrader: account fetch failed: %s", e)
            return summary

        # Step 3 & 4: Check open positions for exits
        # Load skip list for exit filtering
        _skip_raw = await db.setting_get("exit_skip_symbols") or "[]"
        try:
            _exit_skip = set(json.loads(_skip_raw))
        except Exception:
            _exit_skip = set()
        _exit_skip.add("CYBR")  # hard block

        try:
            from alpaca_trader.core import client as alpaca

            positions = alpaca.get_positions()
            # Filter out blocked symbols entirely
            positions = [p for p in positions if p.get("symbol", "") not in _exit_skip]
        except Exception as e:
            summary["errors"].append(f"Positions fetch failed: {e}")
            logger.error("AutoTrader: positions fetch failed: %s", e)
            positions = []

        open_journal = await self.trade_journal.get_trades(status="open", limit=200)
        exits = self.position_manager.check_exits(
            positions, journal_entries=open_journal
        )
        summary["exits_checked"] = len(positions)

        for exit_pos in exits:
            symbol = exit_pos.get("symbol", "")
            exit_reason = exit_pos.get("exit_reason", "exit_rule")
            try:
                current_price = float(exit_pos.get("current_price") or 0)
                qty = int(float(exit_pos.get("qty") or 0))
                if qty <= 0:
                    continue

                # Execute the exit (sell)
                result = self.order_executor.place_market_order(symbol, qty, "sell")
                if result.success:
                    summary["exits_executed"] += 1
                    self._trades_today += 1
                    # Close open journal trade
                    open_trade = await self.trade_journal.get_open_trade_for_symbol(
                        symbol
                    )
                    if open_trade:
                        await self.trade_journal.log_exit(
                            open_trade["id"], current_price, exit_reason
                        )
                    logger.info(
                        "Exit executed: %s qty=%d reason=%s", symbol, qty, exit_reason
                    )
                else:
                    summary["errors"].append(
                        f"Exit order failed for {symbol}: {result.error}"
                    )
            except Exception as e:
                summary["errors"].append(f"Exit error for {symbol}: {e}")
                logger.error("AutoTrader: exit error for %s: %s", symbol, e)

        # Step 5: Scan for new signals
        try:
            watchlist = await db.watchlist_list()
            symbols = [w["symbol"] for w in watchlist]
        except Exception as e:
            summary["errors"].append(f"Watchlist fetch failed: {e}")
            symbols = []

        if not symbols:
            logger.info("AutoTrader: no symbols in watchlist — skipping entry scan")
            return summary

        # Scan all strategies (daily bars) and merge by highest strength per symbol
        best_by_symbol: dict[str, object] = {}
        for strategy in ("bb_rsi_reversal", "bounce", "squeeze"):
            try:
                strat_signals = self.scanner.scan(
                    symbols, strategy=strategy, period="1D"
                )
                for s in strat_signals:
                    if s.detected:
                        existing = best_by_symbol.get(s.symbol)
                        if existing is None or s.strength > existing.strength:  # type: ignore[union-attr]
                            best_by_symbol[s.symbol] = s
            except Exception as e:
                summary["errors"].append(f"Scanner failed ({strategy}): {e}")
                logger.error("AutoTrader: scanner failed for %s: %s", strategy, e)

        # Also scan intraday (15Min) for bb_rsi_reversal and bounce
        for strategy in ("bb_rsi_reversal", "bounce"):
            try:
                intraday = self.scanner.scan(
                    symbols, strategy=strategy, period="15Min", limit=100
                )
                for s in intraday:
                    if s.detected:
                        existing = best_by_symbol.get(s.symbol)
                        if existing is None or s.strength > existing.strength:  # type: ignore[union-attr]
                            best_by_symbol[s.symbol] = s
            except Exception as e:
                summary["errors"].append(f"Intraday scanner failed ({strategy}): {e}")
                logger.error(
                    "AutoTrader: intraday scanner failed for %s: %s", strategy, e
                )

        actionable = list(best_by_symbol.values())
        summary["signals_found"] = len(actionable)

        # Load symbols to skip (inactive assets + hard-blocked symbols)
        skip_raw = await db.setting_get("exit_skip_symbols") or "[]"
        try:
            skip_symbols = set(json.loads(skip_raw))
        except Exception:
            skip_symbols = set()
        skip_symbols.add("CYBR")  # hard block — never trade CYBR

        open_position_symbols = {(p.get("symbol") or "").upper() for p in positions}
        open_positions_count = len(positions)

        # Also check pending orders to avoid duplicate entries
        try:
            pending_orders = alpaca.get_orders(status="open", limit=100)
            pending_symbols = {
                (o.get("symbol") or "").upper()
                for o in pending_orders
                if o.get("side") == "buy"
            }
            open_position_symbols = open_position_symbols | pending_symbols
        except Exception:
            pass  # If we can't check, proceed with just position check

        # Step 6 & 7: Risk check + execute entries
        for signal in actionable:
            symbol = signal.symbol
            # Skip globally blocked symbols
            if symbol in skip_symbols:
                logger.info("AutoTrader: skipping blocked symbol %s", symbol)
                continue
            # Skip if we already hold this symbol
            if symbol in open_position_symbols:
                continue

            try:
                # Estimate price from signal details or use a rough proxy
                # target and stop are not used yet; kept for future enhancement
                _ = signal.details.get("target") or signal.details.get("target_price")
                _ = signal.details.get("stop") or signal.details.get("stop_price")
                # Get current price via bars
                from alpaca_trader.core import client as alpaca

                bars = alpaca.get_stock_bars_df(symbol, period="1D", limit=2)
                if bars.empty:
                    continue
                price = float(bars["close"].iloc[-1])
                if price <= 0:
                    continue

                qty = self.risk_manager.calculate_position_size(price, portfolio_value)
                if qty <= 0:
                    continue

                risk_result = self.risk_manager.check_order(
                    symbol=symbol,
                    qty=qty,
                    price=price,
                    side="buy",
                    portfolio_value=portfolio_value,
                    cash=cash,
                    open_positions=open_positions_count,
                    daily_pnl=daily_pnl,
                    trades_today=self._trades_today,
                )
                if risk_result.rejected:
                    logger.info("Risk rejected %s: %s", symbol, risk_result.reason)
                    continue

                summary["entries_approved"] += 1
                approved_qty = risk_result.adjusted_qty

                # Execute entry
                order_result = self.order_executor.place_market_order(
                    symbol, approved_qty, "buy"
                )
                if order_result.success:
                    summary["entries_executed"] += 1
                    self._trades_today += 1
                    open_positions_count += 1
                    trade_id = await self.trade_journal.log_entry(
                        symbol=symbol,
                        side="buy",
                        qty=approved_qty,
                        price=price,
                        strategy=signal.strategy,
                        signal_details=signal.details,
                    )
                    logger.info(
                        "Entry executed: %s qty=%d price=%.2f trade_id=%d",
                        symbol,
                        approved_qty,
                        price,
                        trade_id,
                    )
                else:
                    summary["errors"].append(
                        f"Entry order failed for {symbol}: {order_result.error}"
                    )
            except Exception as e:
                summary["errors"].append(f"Entry error for {symbol}: {e}")
                logger.error("AutoTrader: entry error for %s: %s", symbol, e)

        return summary
