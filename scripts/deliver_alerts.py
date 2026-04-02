#!/usr/bin/env python3
"""Standalone delivery script for OpenClaw cron.

Reads data/alert-queue.json, formats pending alerts, prints JSON to stdout,
then marks them as delivered. OpenClaw cron parses the output and sends to Telegram.

Usage:
    python scripts/deliver_alerts.py
    python scripts/deliver_alerts.py --dry-run
    python scripts/deliver_alerts.py --no-mark-delivered
"""

import argparse
import json
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alpaca_trader.alerts.delivery import TelegramDeliveryQueue
from alpaca_trader.alerts.formatter import format_alert_telegram


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deliver pending alerts to Telegram via OpenClaw."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print alerts without marking delivered"
    )
    parser.add_argument(
        "--no-mark-delivered", action="store_true", help="Skip marking alerts delivered"
    )
    parser.add_argument(
        "--format", choices=["json", "text"], default="json", help="Output format"
    )
    args = parser.parse_args()

    queue = TelegramDeliveryQueue()
    pending = queue.get_pending()

    if not pending:
        if args.format == "json":
            print(json.dumps({"count": 0, "alerts": []}))
        else:
            print("No pending alerts.")
        return

    delivered_ids: list[str] = []
    output_alerts = []

    for entry in pending:
        text = format_alert_telegram(entry)
        output_alerts.append(
            {
                "queue_id": entry["queue_id"],
                "alert_id": entry.get("alert_id"),
                "symbol": entry.get("symbol"),
                "alert_type": entry.get("alert_type"),
                "severity": entry.get("severity", "info"),
                "triggered_at": entry.get("triggered_at"),
                "text": text,
            }
        )
        delivered_ids.append(entry["queue_id"])

    if args.format == "json":
        print(
            json.dumps({"count": len(output_alerts), "alerts": output_alerts}, indent=2)
        )
    else:
        for a in output_alerts:
            print(f"[{a['severity'].upper()}] {a['text']}")

    if not args.dry_run and not args.no_mark_delivered:
        updated = queue.mark_delivered(delivered_ids)
        if args.format != "json":
            print(f"\nMarked {updated} alert(s) as delivered.")


if __name__ == "__main__":
    main()
