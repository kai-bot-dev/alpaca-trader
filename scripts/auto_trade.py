#!/usr/bin/env python3
"""Auto-trade cron script.

Runs every 5 minutes during market hours (9:30 AM - 4:00 PM ET / 6:30 AM - 1:00 PM PT).

Steps:
1. Check if market is open (9:30–16:00 ET, Mon-Fri)
2. Run AutoTrader.run_cycle()
3. Output summary for Telegram alert delivery
4. Records equity snapshot

Output convention (for OpenClaw cron):
- "TRADE_OK" → cycle ran, nothing to report
- Alert text lines → queued for Telegram delivery
- "MARKET_CLOSED" → market not open, no action taken
- "DISABLED" → auto-trader not enabled
- "ERROR: ..." → error during cycle

Usage:
    python scripts/auto_trade.py
    python scripts/auto_trade.py --dry-run
    python scripts/auto_trade.py --format json
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alpaca_trader.core import database as db
from alpaca_trader.engine.auto_trader import AutoTrader, is_market_open


async def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-trade cron job.")
    parser.add_argument("--dry-run", action="store_true", help="Force dry-run mode (no real orders)")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    parser.add_argument("--force", action="store_true", help="Run even if market is closed (testing)")
    args = parser.parse_args()

    await db.init_db()

    # Check market hours unless forced
    if not args.force and not is_market_open():
        if args.format == "json":
            print(json.dumps({"status": "market_closed", "time": datetime.now(timezone.utc).isoformat()}))
        else:
            print("MARKET_CLOSED")
        return

    # Determine trading mode
    trading_mode = await db.setting_get("trading_mode") or "stocks"

    if trading_mode == "options":
        from alpaca_trader.engine.options_trader import OptionsTrader
        trader = OptionsTrader(dry_run=args.dry_run)
    else:
        trader = AutoTrader(dry_run=args.dry_run)

    # Quick check: is it enabled?
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

    # Record equity snapshot if we have account access
    try:
        from alpaca_trader.core import client as alpaca
        account = alpaca.get_account()
        equity = float(account.get("equity") or 0)
        portfolio_value = float(account.get("portfolio_value") or 0)
        await db.setting_set("last_equity_snapshot", json.dumps({
            "equity": equity,
            "portfolio_value": portfolio_value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
    except Exception:
        pass  # Non-critical

    # Build output
    entries = summary.get("entries_executed", 0)
    exits = summary.get("exits_executed", 0)
    errors = summary.get("errors", [])

    if args.format == "json":
        print(json.dumps({
            "status": "ok",
            "summary": summary,
        }, indent=2))
        return

    # Text output: only print something actionable for Telegram
    lines = []

    if entries > 0 or exits > 0:
        parts = []
        if entries > 0:
            parts.append(f"{entries} entr{'y' if entries == 1 else 'ies'} executed")
        if exits > 0:
            parts.append(f"{exits} exit{'s' if exits != 1 else ''} executed")
        lines.append(f"AutoTrader cycle: {', '.join(parts)}")

    if errors:
        for err in errors:
            lines.append(f"AutoTrader WARNING: {err}")

    if lines:
        print("\n".join(lines))
    else:
        print("TRADE_OK")


if __name__ == "__main__":
    asyncio.run(main())
