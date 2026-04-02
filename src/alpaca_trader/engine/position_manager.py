"""Position manager — monitors open positions and applies exit rules."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

PAPER_TRADE_LOCKOUT = 50  # require N closed paper trades before live


@dataclass
class ExitDecision:
    should_exit: bool
    reason: str
    symbol: str = ""


class PositionManager:
    """Monitor positions and enforce exit rules.

    Exit rules (all configurable):
    - stop_loss_pct: exit if position falls below this % from entry
    - take_profit_pct: exit if position gains above this % from entry
    - trailing_stop_trigger: activate trailing stop once gain exceeds this %
    - trailing_stop_pct: trail by this % from the high-water mark
    - max_hold_days: time-based exit after N days
    """

    def __init__(
        self,
        stop_loss_pct: float = -0.05,
        take_profit_pct: float = 0.08,
        trailing_stop_trigger: float = 0.04,
        trailing_stop_pct: float = 0.02,
        max_hold_days: int = 10,
    ) -> None:
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_trigger = trailing_stop_trigger
        self.trailing_stop_pct = trailing_stop_pct
        self.max_hold_days = max_hold_days
        # Track high-water marks per symbol: symbol -> highest price seen
        self._high_water_marks: dict[str, float] = {}

    def update_high_water_mark(self, symbol: str, current_price: float) -> float:
        """Update and return the high-water mark for a symbol."""
        if symbol not in self._high_water_marks:
            self._high_water_marks[symbol] = current_price
            return current_price
        hwm = self._high_water_marks[symbol]
        if current_price > hwm:
            self._high_water_marks[symbol] = current_price
            return current_price
        return hwm

    def should_exit(
        self,
        symbol: str,
        current_price: float,
        entry_price: float,
        entry_time: str,
        high_water_mark: Optional[float] = None,
    ) -> tuple[bool, str]:
        """Check if a single position meets any exit criteria.

        Returns (should_exit, reason).
        """
        if entry_price <= 0:
            return False, "invalid entry price"

        # Update high-water mark
        hwm = self.update_high_water_mark(symbol, current_price)
        if high_water_mark is not None and high_water_mark > hwm:
            self._high_water_marks[symbol] = high_water_mark
            hwm = high_water_mark

        gain_pct = (current_price - entry_price) / entry_price

        # 1. Stop loss
        if gain_pct <= self.stop_loss_pct:
            return True, f"stop_loss ({gain_pct:.2%} <= {self.stop_loss_pct:.2%})"

        # 2. Take profit
        if gain_pct >= self.take_profit_pct:
            return True, f"take_profit ({gain_pct:.2%} >= {self.take_profit_pct:.2%})"

        # 3. Trailing stop (only active once gain triggers it)
        hwm_gain = (hwm - entry_price) / entry_price
        if hwm_gain >= self.trailing_stop_trigger:
            trail_threshold = hwm * (1.0 - self.trailing_stop_pct)
            if current_price <= trail_threshold:
                return True, (
                    f"trailing_stop (price {current_price:.2f} <= "
                    f"trail {trail_threshold:.2f}, hwm={hwm:.2f})"
                )

        # 4. Time-based exit
        try:
            if entry_time.endswith("Z"):
                entry_time = entry_time[:-1] + "+00:00"
            entry_dt = datetime.fromisoformat(entry_time)
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=timezone.utc)
            hold_days = (datetime.now(timezone.utc) - entry_dt).days
            if hold_days >= self.max_hold_days:
                return True, f"max_hold_days ({hold_days} >= {self.max_hold_days})"
        except (ValueError, TypeError) as e:
            logger.warning("Could not parse entry_time '%s': %s", entry_time, e)

        return False, "hold"

    def check_exits(
        self,
        positions: list[dict],
        journal_entries: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Check a list of positions for exit signals.

        Args:
            positions: Alpaca positions dicts with keys: symbol, current_price,
                       avg_entry_price, unrealized_plpc, etc.
            journal_entries: Optional list of open journal trades for entry_time lookup.

        Returns:
            List of positions that should be exited, with 'exit_reason' added.
        """
        journal_by_symbol: dict[str, dict] = {}
        if journal_entries:
            for entry in journal_entries:
                sym = (entry.get("symbol") or "").upper()
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

            # Get entry_time from journal if available
            entry_time = datetime.now(timezone.utc).isoformat()
            journal_entry = journal_by_symbol.get(symbol)
            if journal_entry:
                entry_time = journal_entry.get("entry_time", entry_time)

            should, reason = self.should_exit(
                symbol=symbol,
                current_price=current_price,
                entry_price=entry_price,
                entry_time=entry_time,
            )
            if should:
                exit_pos = dict(pos)
                exit_pos["exit_reason"] = reason
                exits.append(exit_pos)
                logger.info(
                    "Exit signal for %s: %s (price=%.2f, entry=%.2f)",
                    symbol,
                    reason,
                    current_price,
                    entry_price,
                )

        return exits
