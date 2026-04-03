"""AlertChecker — evaluates active alerts against current market state."""

import logging
from datetime import date, datetime, timezone
from typing import Optional

from alpaca_trader.core import client as alpaca
from alpaca_trader.core import database as db
from alpaca_trader.strategies.scanner import WatchlistScanner

logger = logging.getLogger(__name__)


class AlertChecker:
    """Evaluates all active alerts and returns those that triggered."""

    async def check_all(self) -> list[dict]:
        """Check all active alerts. Returns list of triggered alert dicts."""
        alerts = await db.alerts_list(status="active")
        logger.info("Checking alerts", extra={"count": len(alerts)})
        triggered = []
        for alert in alerts:
            result = await self._check_alert(alert)
            if result:
                await db.alerts_mark_triggered(alert["id"], result)
                alert["message"] = result
                alert["status"] = "triggered"
                alert["triggered_at"] = datetime.now(timezone.utc).isoformat()
                triggered.append(alert)
        if triggered:
            logger.info(
                "Alerts triggered",
                extra={"triggered": len(triggered), "total": len(alerts)},
            )
        return triggered

    async def _check_alert(self, alert: dict) -> Optional[str]:
        """Returns a triggered message if the alert condition is met, else None."""
        alert_type = alert.get("alert_type", "")
        symbol = alert.get("symbol", "")
        condition = alert.get("condition", {})

        try:
            if alert_type == "fill":
                return await self._check_fill(symbol, condition)
            elif alert_type == "pnl":
                return await self._check_pnl(symbol, condition)
            elif alert_type == "expiry":
                return await self._check_expiry(symbol, condition)
            elif alert_type == "price":
                return await self._check_price(symbol, condition)
            elif alert_type == "squeeze":
                return await self._check_squeeze(symbol, condition)
            elif alert_type == "signal":
                return await self._check_signal(symbol, condition)
        except EnvironmentError:
            raise
        except Exception:
            return None
        return None

    async def _check_fill(self, symbol: str, condition: dict) -> Optional[str]:
        """Check if any recent orders for symbol are filled."""
        orders = alpaca.get_orders(status="closed", limit=50)
        for order in orders:
            if order.get("symbol") == symbol and order.get("status") == "filled":
                side = order.get("side", "")
                qty = order.get("filled_qty", "?")
                price = order.get("filled_avg_price", "?")
                return f"FILL {symbol}: {side} {qty} @ ${price}"
        return None

    async def _check_pnl(self, symbol: str, condition: dict) -> Optional[str]:
        """Check if position P&L crossed the threshold (in %)."""
        threshold = condition.get("threshold")
        if threshold is None:
            return None
        positions = alpaca.get_positions()
        for pos in positions:
            if pos.get("symbol") == symbol:
                pnl_pct = float(pos.get("unrealized_plpc", 0)) * 100
                if threshold >= 0 and pnl_pct >= threshold:
                    return f"P&L {symbol}: +{pnl_pct:.1f}% ≥ +{threshold}% target"
                elif threshold < 0 and pnl_pct <= threshold:
                    return f"P&L {symbol}: {pnl_pct:.1f}% ≤ {threshold}% stop"
        return None

    async def _check_expiry(self, symbol: str, condition: dict) -> Optional[str]:
        """Check if an option position is within N days of expiry."""
        days_threshold = condition.get("days", 7)
        positions = alpaca.get_positions()
        today = date.today()
        for pos in positions:
            pos_symbol = pos.get("symbol", "")
            # Option symbols are OCC format: AAPL230120C00150000
            # or the underlying might match
            if symbol.upper() not in pos_symbol.upper():
                continue
            # Try to parse expiry from OCC symbol
            # Format: TICKER + YYMMDD + C/P + strike
            try:
                # OCC symbol: underlying(variable) + YYMMDD + type + strike(8 digits)
                # Find the date part by looking for 6-digit date after the letters
                import re

                match = re.search(r"(\d{6})[CP]", pos_symbol)
                if match:
                    date_str = match.group(1)
                    expiry = date(
                        2000 + int(date_str[:2]), int(date_str[2:4]), int(date_str[4:6])
                    )
                    days_to_expiry = (expiry - today).days
                    if 0 <= days_to_expiry <= days_threshold:
                        expiry_str = str(expiry)
                        msg = f"EXPIRY {pos_symbol}: {days_to_expiry}d to expiry ({expiry_str})"
                        return msg
            except Exception:
                continue
        return None

    async def _check_price(self, symbol: str, condition: dict) -> Optional[str]:
        """Check if underlying price crossed target."""
        target = condition.get("target_price")
        direction = condition.get("direction", "above")  # above or below
        if target is None:
            return None
        try:
            df = alpaca.get_stock_bars_df(symbol, period="1D", limit=2)
            if df.empty:
                return None
            current_price = float(df["close"].iloc[-1])
            if direction == "above" and current_price >= target:
                return f"PRICE {symbol}: ${current_price:.2f} ≥ target ${target:.2f}"
            elif direction == "below" and current_price <= target:
                return f"PRICE {symbol}: ${current_price:.2f} ≤ target ${target:.2f}"
        except Exception:
            return None
        return None

    async def _check_squeeze(self, symbol: str, condition: dict) -> Optional[str]:
        """Check if Bollinger Band squeeze is detected."""
        scanner = WatchlistScanner()
        signals = scanner.scan([symbol], strategy="squeeze")
        if signals and signals[0].detected:
            sig = signals[0]
            strength_str = f"{sig.strength:.2f}"
            msg = f"SQUEEZE {symbol}: {sig.direction} signal (strength {strength_str})"
            return msg
        return None

    async def _check_signal(self, symbol: str, condition: dict) -> Optional[str]:
        """Check if bounce or trend signal fires."""
        strategy = condition.get("strategy", "bounce")
        scanner = WatchlistScanner()
        signals = scanner.scan([symbol], strategy=strategy)
        if signals and signals[0].detected:
            sig = signals[0]
            strength_str = f"{sig.strength:.2f}"
            return f"SIGNAL {symbol} [{strategy}]: {sig.direction} (strength {strength_str})"
        return None
