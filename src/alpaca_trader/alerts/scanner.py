"""ScheduledScanner — runs AlertChecker + watchlist scan and returns formatted results."""

import logging
from datetime import datetime, timezone

from alpaca_trader.alerts.checker import AlertChecker
from alpaca_trader.alerts.delivery import TelegramDeliveryQueue
from alpaca_trader.core import database as db
from alpaca_trader.strategies.scanner import WatchlistScanner

logger = logging.getLogger(__name__)


class ScheduledScanner:
    """Runs a full market scan: alert checks + strategy signals.

    Designed to be called every 15 minutes during market hours.
    Returns a dict with triggered alerts, strategy signals, and metadata.
    """

    async def run(self) -> dict:
        """Execute full scan. Returns results dict."""
        started_at = datetime.now(timezone.utc).isoformat()

        # 1. Check active alerts
        checker = AlertChecker()
        triggered_alerts = await checker.check_all()

        # 2a. Queue triggered alerts for Telegram delivery
        if triggered_alerts:
            delivery = TelegramDeliveryQueue()
            for alert in triggered_alerts:
                delivery.queue_alert(alert, context=alert.get("condition") or {})

        # 2b. Scan watchlist with all strategies
        watchlist_items = await db.watchlist_list()
        symbols = [item["symbol"] for item in watchlist_items]

        strategy_signals = []
        if symbols:
            scanner = WatchlistScanner()
            try:
                for strategy in ("squeeze", "bounce", "trend", "bb_rsi_reversal"):
                    signals = scanner.scan(symbols, strategy=strategy)
                    for sig in signals:
                        if sig.detected:
                            strategy_signals.append({
                                "symbol": sig.symbol,
                                "strategy": sig.strategy,
                                "direction": sig.direction,
                                "strength": sig.strength,
                                "details": sig.details,
                                "timestamp": sig.timestamp,
                            })
            except EnvironmentError:
                raise
            except Exception as e:
                strategy_signals = [{"error": str(e)}]

        completed_at = datetime.now(timezone.utc).isoformat()

        # 3. Store last scan time
        await db.setting_set("monitor_last_run", completed_at)
        await db.setting_set("monitor_last_triggered_count", str(len(triggered_alerts)))

        logger.info("Scheduled scan complete", extra={
            "symbols_scanned": len(symbols),
            "alerts_triggered": len(triggered_alerts),
            "signals_detected": len(strategy_signals),
        })

        return {
            "started_at": started_at,
            "completed_at": completed_at,
            "symbols_scanned": len(symbols),
            "triggered_alerts": triggered_alerts,
            "strategy_signals": strategy_signals,
            "summary": _format_summary(triggered_alerts, strategy_signals),
        }


def _format_summary(triggered_alerts: list, strategy_signals: list) -> str:
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
    if not lines:
        lines.append("✓ No alerts or signals triggered.")
    return "\n".join(lines)
