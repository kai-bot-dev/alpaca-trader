"""Options position manager — monitors option positions and applies options-specific exit rules."""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


def _dte_from_expiry(expiry_str: str) -> Optional[int]:
    """Return days to expiration given an ISO-format date string."""
    try:
        expiry = date.fromisoformat(str(expiry_str)[:10])
        return (expiry - date.today()).days
    except (ValueError, TypeError):
        return None


class OptionsPositionManager:
    """Monitor option positions and enforce exit rules.

    Exit rules (evaluated in priority order):
    1. Time stop  — close if DTE < 3 (avoid theta crush)
    2. Hard stop  — close if option price down >= 40% from premium_paid
    3. Trailing stop — activate at +30% gain; trail 20% below high-water mark
    4. Take profit — close if option price up >= 50% from premium_paid

    Args:
        time_stop_dte: Close position when DTE falls below this value.
        hard_stop_pct: Close position if loss exceeds this fraction (negative, e.g. -0.40).
        trailing_trigger_pct: Activate trailing stop once gain exceeds this fraction.
        trailing_stop_pct: Trail this fraction below the high-water mark price.
        take_profit_pct: Close position at this gain fraction.
    """

    def __init__(
        self,
        time_stop_dte: int = 3,
        hard_stop_pct: float = -0.40,
        trailing_trigger_pct: float = 0.30,
        trailing_stop_pct: float = 0.20,
        take_profit_pct: float = 0.50,
    ) -> None:
        self.time_stop_dte = time_stop_dte
        self.hard_stop_pct = hard_stop_pct
        self.trailing_trigger_pct = trailing_trigger_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.take_profit_pct = take_profit_pct
        # High-water mark per option symbol: symbol -> highest current price seen
        self._high_water_marks: dict[str, float] = {}

    def update_high_water_mark(self, symbol: str, current_price: float) -> float:
        """Update and return the high-water mark for an option symbol."""
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
        expiry_date: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Check if a single option position meets any exit criteria.

        Args:
            symbol: Option symbol (e.g. "GOOGL260401C00275000").
            current_price: Current per-share option price (mid or last).
            premium_paid: Entry per-share option price (ask at entry).
            expiry_date: ISO date string for the option expiry.

        Returns:
            (should_exit, reason) tuple.
        """
        if premium_paid <= 0:
            return False, "invalid premium_paid"
        if current_price <= 0:
            return False, "invalid current_price"

        # Update high-water mark
        hwm = self.update_high_water_mark(symbol, current_price)

        gain_pct = (current_price - premium_paid) / premium_paid

        # Priority 1: Time stop
        if expiry_date:
            dte = _dte_from_expiry(expiry_date)
            if dte is not None and dte < self.time_stop_dte:
                return True, f"time_stop (DTE={dte} < {self.time_stop_dte})"

        # Priority 2: Hard stop
        if gain_pct <= self.hard_stop_pct + 1e-9:  # epsilon for float boundary
            return True, f"hard_stop ({gain_pct:.2%} <= {self.hard_stop_pct:.2%})"

        # Priority 3: Trailing stop (activates once gain exceeds trigger)
        hwm_gain = (hwm - premium_paid) / premium_paid
        if hwm_gain >= self.trailing_trigger_pct:
            trail_threshold = hwm * (1.0 - self.trailing_stop_pct)
            if current_price <= trail_threshold:
                return True, (
                    f"trailing_stop (price {current_price:.2f} <= "
                    f"trail {trail_threshold:.2f}, hwm={hwm:.2f})"
                )

        # Priority 4: Take profit
        if gain_pct >= self.take_profit_pct:
            return True, f"take_profit ({gain_pct:.2%} >= {self.take_profit_pct:.2%})"

        return False, "hold"

    def check_exits(
        self,
        positions: list[dict],
        journal_entries: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Check a list of option positions for exit signals.

        Args:
            positions: Alpaca position dicts. For options positions the symbol
                       is the OCC option symbol (e.g. "GOOGL260401C00275000").
                       Expects keys: symbol, current_price, avg_entry_price.
            journal_entries: Open journal trades. Used to look up expiry_date and
                             premium_paid (stored as entry_price in journal).

        Returns:
            List of positions that should be exited, each with 'exit_reason' added.
        """
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
                entry_price = float(pos.get("avg_entry_price") or pos.get("avg_cost") or 0)
            except (TypeError, ValueError):
                continue

            if current_price <= 0 or entry_price <= 0:
                continue

            # Look up option-specific journal data
            journal_entry = journal_by_symbol.get(symbol)
            expiry_date: Optional[str] = None
            premium_paid = entry_price  # fallback to Alpaca avg_entry_price

            if journal_entry:
                expiry_date = journal_entry.get("expiry_date")
                premium_raw = journal_entry.get("premium_paid") or journal_entry.get("entry_price")
                if premium_raw is not None:
                    try:
                        premium_paid = float(premium_raw)
                    except (TypeError, ValueError):
                        pass

            should, reason = self.should_exit(
                symbol=symbol,
                current_price=current_price,
                premium_paid=premium_paid,
                expiry_date=expiry_date,
            )

            if should:
                exit_pos = dict(pos)
                exit_pos["exit_reason"] = reason
                exits.append(exit_pos)
                logger.info(
                    "Options exit signal for %s: %s (price=%.2f, premium=%.2f)",
                    symbol, reason, current_price, premium_paid,
                )

        return exits
