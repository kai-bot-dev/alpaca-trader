#!/usr/bin/env python3
"""Auto-trade cron script — runs every 5 min during market hours."""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alpaca_trader.core import database as db
from alpaca_trader.engine.auto_trader import AutoTrader, is_market_open


async def check_stock_exits(dry_run: bool) -> dict:
    """Always check stock positions for exits, regardless of trading mode."""
    result = {"exits_executed": 0, "exits": [], "errors": []}
    try:
        from alpaca_trader.core import client as alpaca
        from alpaca_trader.engine.position_manager import PositionManager
        from alpaca_trader.engine.trade_journal import TradeJournal
        from alpaca_trader.engine.order_executor import OrderExecutor, ExecutorConfig

        # Load skip list — symbols that failed with "not active" / "not tradable"
        skip_raw = await db.setting_get("exit_skip_symbols") or "[]"
        try:
            skip_symbols: list[str] = json.loads(skip_raw)
        except (json.JSONDecodeError, TypeError):
            skip_symbols = []

        positions = alpaca.get_positions()
        # Stock positions have short symbols (<=5 chars), options are longer
        # Filter out skip_symbols entirely so we don't even evaluate them
        stock_positions = [
            p
            for p in positions
            if len(p.get("symbol", "")) <= 5 and p.get("symbol", "") not in skip_symbols
        ]
        if not stock_positions:
            return result

        pm = PositionManager()
        journal = TradeJournal()
        open_trades = await journal.get_trades(status="open", limit=200)
        stock_exits = pm.check_exits(stock_positions, journal_entries=open_trades)
        executor = OrderExecutor(config=ExecutorConfig(dry_run=dry_run))

        skip_symbols_updated = False
        for exit_pos in stock_exits:
            sym = exit_pos.get("symbol", "")
            qty = int(float(exit_pos.get("qty") or 0))
            reason = exit_pos.get("exit_reason", "")
            if qty <= 0:
                continue
            # Skip symbols known to be inactive/untradable
            if sym in skip_symbols:
                result["errors"].append(
                    f"Skipping {sym}: marked as inactive/not tradable"
                )
                continue
            order = executor.place_market_order(sym, qty, "sell")
            if order.success:
                result["exits_executed"] += 1
                result["exits"].append(f"{sym} ({reason})")
                current_price = float(exit_pos.get("current_price") or 0)
                open_trade = await journal.get_open_trade_for_symbol(sym)
                if open_trade:
                    await journal.log_exit(open_trade["id"], current_price, reason)
            else:
                err_lower = (order.error or "").lower()
                if (
                    "not active" in err_lower
                    or "not tradable" in err_lower
                    or "asset" in err_lower
                ):
                    # Permanently skip this symbol until manually cleared
                    if sym not in skip_symbols:
                        skip_symbols.append(sym)
                        skip_symbols_updated = True
                    result["errors"].append(
                        f"Exit skipped for {sym} (inactive asset — added to skip list): {order.error}"
                    )
                else:
                    result["errors"].append(f"Exit failed for {sym}: {order.error}")

        if skip_symbols_updated:
            await db.setting_set("exit_skip_symbols", json.dumps(skip_symbols))

    except Exception as ex:
        result["errors"].append(f"Stock exit check: {ex}")
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-trade cron job.")
    parser.add_argument("--dry-run", action="store_true", help="Force dry-run mode")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--force", action="store_true", help="Run even if market closed"
    )
    args = parser.parse_args()

    await db.init_db()

    if not args.force and not is_market_open():
        if args.format == "json":
            print(json.dumps({"status": "market_closed"}))
        else:
            print("MARKET_CLOSED")
        return

    trading_mode = await db.setting_get("trading_mode") or "stocks"

    if trading_mode == "options":
        from alpaca_trader.engine.options_trader import OptionsTrader

        trader = OptionsTrader(dry_run=args.dry_run)
    else:
        trader = AutoTrader(dry_run=args.dry_run)

    enabled = await trader.is_enabled()
    if not enabled:
        if args.format == "json":
            print(json.dumps({"status": "disabled"}))
        else:
            print("DISABLED")
        return

    try:
        summary = await trader.run_cycle()
    except Exception as e:
        if args.format == "json":
            print(json.dumps({"status": "error", "message": str(e)}))
        else:
            print(f"ERROR: {e}")
        sys.exit(1)

    # Always manage stock exits even in options mode
    stock_exit_result = await check_stock_exits(dry_run=args.dry_run)
    summary["exits_executed"] = (
        summary.get("exits_executed", 0) + stock_exit_result["exits_executed"]
    )
    summary.setdefault("errors", []).extend(stock_exit_result.get("errors", []))

    # Record equity snapshot
    try:
        from alpaca_trader.core import client as alpaca

        account = alpaca.get_account()
        equity = float(account.get("equity") or 0)
        portfolio_value = float(account.get("portfolio_value") or 0)
        await db.setting_set(
            "last_equity_snapshot",
            json.dumps(
                {
                    "equity": equity,
                    "portfolio_value": portfolio_value,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )
    except Exception:
        pass

    entries = summary.get("entries_executed", 0)
    exits = summary.get("exits_executed", 0)
    proposals = summary.get("proposals_queued", 0)
    errors = summary.get("errors", [])

    if args.format == "json":
        print(json.dumps({"status": "ok", "summary": summary}, indent=2))
        return

    lines = []
    if entries > 0 or exits > 0:
        parts = []
        if entries > 0:
            parts.append(f"{entries} entr{'y' if entries == 1 else 'ies'} executed")
        if exits > 0:
            parts.append(f"{exits} exit{'s' if exits != 1 else ''} executed")
        lines.append(f"AutoTrader [{trading_mode}]: {', '.join(parts)}")
        for ex in stock_exit_result.get("exits", []):
            lines.append(f"  SOLD: {ex}")

    # Report queued proposals (options mode)
    if proposals > 0:
        lines.append(
            f"PROPOSALS: {proposals} new trade proposal{'s' if proposals != 1 else ''} queued"
        )
        # Fetch and display the freshly queued proposals
        try:
            from alpaca_trader.engine.trade_proposals import get_pending_proposals

            pending = await get_pending_proposals()
            # Show up to the most recent `proposals` proposals
            recent = pending[-proposals:] if len(pending) >= proposals else pending
            for p in recent:
                sym = p.get("symbol", "?")
                direction = p.get("direction", "?")
                opt_type = "call" if direction == "long" else "put"
                strike = p.get("strike", "?")
                expiry = str(p.get("expiry", "?"))
                # Format expiry as M/D
                try:
                    from datetime import date

                    exp_date = date.fromisoformat(expiry)
                    expiry_fmt = f"{exp_date.month}/{exp_date.day}"
                except Exception:
                    expiry_fmt = expiry
                premium = p.get("premium")
                premium_str = f"${float(premium):.2f}" if premium else "?"
                strategy = p.get("strategy", "?")
                strength = p.get("signal_strength")
                strength_str = f"{float(strength):.2f}" if strength is not None else "?"
                lines.append(
                    f"  {sym} {opt_type} ${strike} {expiry_fmt} @ {premium_str}"
                    f" ({strategy} signal, strength={strength_str})"
                )
        except Exception as _e:
            lines.append(f"  (could not load proposal details: {_e})")

    if errors:
        for err in errors:
            lines.append(f"WARNING: {err}")

    if lines:
        print("\n".join(lines))
    else:
        print("TRADE_OK")


if __name__ == "__main__":
    asyncio.run(main())
