#!/usr/bin/env python3
"""Cron scanner with automatic alert delivery.

Runs:
1. Scan watchlist for squeeze signals (1D timeframe)
2. Check for new alerts in the database
3. Queue matching alerts for delivery
4. Output SCAN_OK or alert summary

For OpenClaw cron: if output is NOT 'SCAN_OK', it's treated as trading alerts.
If output IS 'SCAN_OK', nothing to report.

Usage:
    python scripts/cron_scan_and_deliver.py
    python scripts/cron_scan_and_deliver.py --dry-run
    python scripts/cron_scan_and_deliver.py --strategy bounce --period 1H
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alpaca_trader.core import database as db
from alpaca_trader.strategies.scanner import WatchlistScanner
from alpaca_trader.alerts.checker import AlertChecker
from alpaca_trader.alerts.delivery import TelegramDeliveryQueue
from alpaca_trader.alerts.formatter import format_alert_telegram


async def main() -> None:
    parser = argparse.ArgumentParser(description="Scan and deliver trading alerts.")
    parser.add_argument("--strategy", default="bb_rsi_reversal", choices=["squeeze", "bounce", "trend", "bb_rsi_reversal"], help="Strategy to use")
    parser.add_argument("--period", default="1D", help="Bar timeframe (1D, 1H, 15Min, 5Min, 1Min)")
    parser.add_argument("--dry-run", action="store_true", help="Scan but don't queue alerts")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    args = parser.parse_args()

    try:
        # Initialize database
        await db.init_db()

        # Get watchlist
        watchlist_items = await db.watchlist_list()
        symbols = [item["symbol"] for item in watchlist_items]

        if not symbols:
            output = "SCAN_OK"  # No watchlist to scan
            if args.format == "json":
                print(json.dumps({"status": "ok", "reason": "empty_watchlist"}))
            else:
                print(output)
            return

        # Run scan
        scanner = WatchlistScanner()
        signals = scanner.scan(symbols, strategy=args.strategy, period=args.period)

        # Check for triggered alerts
        checker = AlertChecker()
        new_alerts = await checker.check_all()

        # Queue alerts for delivery
        if new_alerts:
            if not args.dry_run:
                queue = TelegramDeliveryQueue()
                for alert in new_alerts:
                    queue.add(alert)

            # Output alerts
            if args.format == "json":
                alert_data = []
                for alert in new_alerts:
                    alert_data.append({
                        "alert_id": alert.get("alert_id"),
                        "symbol": alert.get("symbol"),
                        "alert_type": alert.get("alert_type"),
                        "severity": alert.get("severity", "info"),
                        "triggered_at": alert.get("triggered_at"),
                        "signal": alert.get("signal", {}),
                    })
                print(json.dumps({
                    "status": "alerts",
                    "count": len(new_alerts),
                    "alerts": alert_data,
                }, indent=2))
            else:
                # Print alerts as text (for OpenClaw to send to Telegram)
                for alert in new_alerts:
                    text = format_alert_telegram(alert)
                    print(text)

        else:
            # No alerts
            output = "SCAN_OK"
            if args.format == "json":
                print(json.dumps({
                    "status": "ok",
                    "signals_detected": len([s for s in signals if s.detected]),
                    "alerts_generated": 0,
                }))
            else:
                print(output)

    except EnvironmentError as e:
        error_output = f"CONFIG_ERROR: {e}"
        if args.format == "json":
            print(json.dumps({"status": "error", "type": "config", "message": str(e)}))
        else:
            print(error_output)
        sys.exit(1)
    except Exception as e:
        error_output = f"SCAN_ERROR: {e}"
        if args.format == "json":
            print(json.dumps({"status": "error", "type": "scan", "message": str(e)}))
        else:
            print(error_output)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
