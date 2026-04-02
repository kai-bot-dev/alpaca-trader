"""Options position manager — monitors option positions and applies options-specific exit rules."""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


def _dte_from_expiry(expiry_str: str) -> Optional[int]:
    try:
        expiry = date.fromisoformat(str(expiry_str)[:10])
        return (expiry - date.today()).days
    except (ValueError, TypeError):
        return None


def _parse_underlying(option_symbol: str) -> str:
    """Extract underlying ticker from OCC option symbol. E.g. AAPL260410C00255000 -> AAPL"""
    m = re.match(r"^([A-Z]+)\d", option_symbol)
    return m.group(1) if m else option_symbol


def _get_bb_bands(underlying: str, period: int = 20):
    try:
        from alpaca_trader.core import client as alpaca
        from alpaca_trader.strategies.bollinger import BollingerBands

        df = alpaca.get_stock_bars_df(underlying, period="1D", limit=30)
        if df is None or len(df) < period:
            return None, None
        bb = BollingerBands(period=period)
        result = bb.calc(df)
        return float(result["bb_middle"].iloc[-1]), float(result["bb_lower"].iloc[-1])
    except Exception as e:
        logger.debug("BB fetch failed for %s: %s", underlying, e)
        return None, None


def _get_current_stock_price(underlying: str) -> Optional[float]:
    try:
        from alpaca_trader.core import client as alpaca

        bars = alpaca.get_stock_bars(underlying, period="1D", limit=2)
        if bars:
            return float(bars[-1]["close"])
    except Exception as e:
        logger.debug("Stock price fetch failed for %s: %s", underlying, e)
    return None


class OptionsPositionManager:
    """Monitor option positions and enforce exit rules.

    Exit rules (evaluated in priority order):
    1. BB target exit  — underlying reached middle BB (thesis complete)
    2. Underlying price stop — stock broke further below lower BB (thesis broken)
    3. Theta-aware window — days_held > 60% of max_hold and gain < 30% expected
    4. Delta floor — estimated delta dropped below 0.25
    5. Time stop  — close if DTE < 4
    6. Hard stop  — close if option price down >= 20% from premium_paid
    7. Trailing stop — activate at +20% gain; trail 10% below high-water mark
    8. Take profit — close if option price up >= 30% from premium_paid
    """

    def __init__(
        self,
        time_stop_dte: int = 4,
        hard_stop_pct: float = -0.20,
        trailing_trigger_pct: float = 0.20,
        trailing_stop_pct: float = 0.10,
        take_profit_pct: float = 0.30,
        delta_floor: float = 0.25,
        theta_hold_pct: float = 0.60,
        theta_gain_threshold: float = 0.30,
    ) -> None:
        self.time_stop_dte = time_stop_dte
        self.hard_stop_pct = hard_stop_pct
        self.trailing_trigger_pct = trailing_trigger_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.take_profit_pct = take_profit_pct
        self.delta_floor = delta_floor
        self.theta_hold_pct = theta_hold_pct
        self.theta_gain_threshold = theta_gain_threshold
        self._high_water_marks: dict[str, float] = {}

    def update_high_water_mark(self, symbol: str, current_price: float) -> float:
        hwm = self._high_water_marks.get(symbol)
        if hwm is None or current_price > hwm:
            self._high_water_marks[symbol] = current_price
            return current_price
        return hwm

    def should_exit(
        self,
        symbol: str,
        current_price: float,
        premium_paid: float,
        expiry_date=None,
        direction: str = "long",
        days_held: int = 0,
        delta_at_entry=None,
        theta_at_entry=None,
    ) -> tuple[bool, str]:
        if premium_paid <= 0:
            return False, "invalid premium_paid"
        if current_price <= 0:
            return False, "invalid current_price"

        hwm = self.update_high_water_mark(symbol, current_price)
        gain_pct = (current_price - premium_paid) / premium_paid

        # Priority 1 & 2: BB-based exits for long (call) positions
        underlying = _parse_underlying(symbol)
        if underlying and direction == "long":
            stock_price = _get_current_stock_price(underlying)
            if stock_price is not None:
                bb_middle, bb_lower = _get_bb_bands(underlying)
                # BB target exit
                if bb_middle is not None and stock_price >= bb_middle:
                    return (
                        True,
                        f"bb_target_exit (price {stock_price:.2f} >= middle_bb {bb_middle:.2f})",
                    )
                # Underlying price stop
                if bb_lower is not None and stock_price < bb_lower * 0.995:
                    return (
                        True,
                        f"underlying_stop (price {stock_price:.2f} broke below lower_bb {bb_lower:.2f})",
                    )

        # Priority 3: Theta-aware window
        if theta_at_entry is not None and abs(theta_at_entry) > 0 and days_held > 0:
            daily_theta = abs(theta_at_entry)
            expected_gain_dollars = self.take_profit_pct * premium_paid
            max_hold = expected_gain_dollars / daily_theta
            if max_hold > 0 and days_held > self.theta_hold_pct * max_hold:
                if gain_pct < self.theta_gain_threshold * self.take_profit_pct:
                    return True, (
                        f"theta_window (days_held={days_held} > "
                        f"{self.theta_hold_pct:.0%} of max_hold={max_hold:.1f}, "
                        f"gain={gain_pct:.2%} < threshold)"
                    )

        # Priority 4: Delta floor
        if delta_at_entry is not None and current_price < premium_paid:
            estimated_delta = abs(delta_at_entry) * (current_price / premium_paid)
            if estimated_delta < self.delta_floor:
                return (
                    True,
                    f"delta_floor (est_delta={estimated_delta:.2f} < {self.delta_floor})",
                )

        # Priority 5: Time stop
        if expiry_date:
            dte = _dte_from_expiry(expiry_date)
            if dte is not None and dte < self.time_stop_dte:
                return True, f"time_stop (DTE={dte} < {self.time_stop_dte})"

        # Priority 6: Hard stop
        if gain_pct <= self.hard_stop_pct + 1e-9:
            return True, f"hard_stop ({gain_pct:.2%} <= {self.hard_stop_pct:.2%})"

        # Priority 7: Trailing stop
        hwm_gain = (hwm - premium_paid) / premium_paid
        if hwm_gain >= self.trailing_trigger_pct:
            trail_threshold = hwm * (1.0 - self.trailing_stop_pct)
            if current_price <= trail_threshold:
                return True, (
                    f"trailing_stop (price {current_price:.2f} <= "
                    f"trail {trail_threshold:.2f}, hwm={hwm:.2f})"
                )

        # Priority 8: Take profit
        if gain_pct >= self.take_profit_pct:
            return True, f"take_profit ({gain_pct:.2%} >= {self.take_profit_pct:.2%})"

        return False, "hold"

    def check_exits(
        self,
        positions: list[dict],
        journal_entries=None,
    ) -> list[dict]:
        """Check a list of option positions for exit signals."""
        journal_by_symbol: dict[str, dict] = {}
        if journal_entries:
            for entry in journal_entries:
                sym = (entry.get("option_symbol") or entry.get("symbol") or "").upper()
                if sym:
                    journal_by_symbol[sym] = entry

        exits = []
        for pos in positions:
            symbol = (pos.get("symbol") or "").upper()
            try:
                current_price = float(pos.get("current_price") or 0)
                entry_price = float(
                    pos.get("avg_entry_price") or pos.get("avg_cost") or 0
                )
            except (TypeError, ValueError):
                continue

            if current_price <= 0 or entry_price <= 0:
                continue

            journal_entry = journal_by_symbol.get(symbol)
            expiry_date = None
            premium_paid = entry_price
            direction = "long"
            days_held = 0
            delta_at_entry = None
            theta_at_entry = None

            if journal_entry:
                expiry_date = journal_entry.get("expiry_date")
                premium_raw = journal_entry.get("premium_paid") or journal_entry.get(
                    "entry_price"
                )
                if premium_raw is not None:
                    try:
                        premium_paid = float(premium_raw)
                    except (TypeError, ValueError):
                        pass

                opt_type = (journal_entry.get("option_type") or "").lower()
                if opt_type == "put":
                    direction = "short"

                entry_time = journal_entry.get("entry_time") or journal_entry.get(
                    "created_at"
                )
                if entry_time:
                    try:
                        from datetime import datetime, timezone

                        if isinstance(entry_time, str):
                            entry_dt = datetime.fromisoformat(
                                entry_time.replace("Z", "+00:00")
                            )
                        else:
                            entry_dt = entry_time
                        days_held = (datetime.now(timezone.utc) - entry_dt).days
                    except Exception:
                        pass

                delta_raw = journal_entry.get("delta_at_entry")
                theta_raw = journal_entry.get("theta_at_entry")
                if delta_raw is not None:
                    try:
                        delta_at_entry = float(delta_raw)
                    except (TypeError, ValueError):
                        pass
                if theta_raw is not None:
                    try:
                        theta_at_entry = float(theta_raw)
                    except (TypeError, ValueError):
                        pass

            should, reason = self.should_exit(
                symbol=symbol,
                current_price=current_price,
                premium_paid=premium_paid,
                expiry_date=expiry_date,
                direction=direction,
                days_held=days_held,
                delta_at_entry=delta_at_entry,
                theta_at_entry=theta_at_entry,
            )

            if should:
                exit_pos = dict(pos)
                exit_pos["exit_reason"] = reason
                exits.append(exit_pos)
                logger.info(
                    "Options exit signal for %s: %s (price=%.2f, premium=%.2f)",
                    symbol,
                    reason,
                    current_price,
                    premium_paid,
                )

        return exits
