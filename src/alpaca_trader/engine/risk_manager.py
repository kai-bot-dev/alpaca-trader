"""Risk management for alpaca-trader."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    max_position_pct: float = 0.10
    max_daily_loss_pct: float = -0.05
    max_open_positions: int = 10
    min_cash_reserve_pct: float = 0.10
    max_order_value: float = 50_000.0
    min_order_value: float = 10.0
    max_trades_per_day: int = 50
    slippage_tolerance_pct: float = 0.02


@dataclass
class RiskCheckResult:
    approved: bool
    reason: str
    adjusted_qty: int = 0
    adjusted_value: float = 0.0

    @property
    def rejected(self) -> bool:
        return not self.approved


class RiskManager:
    def __init__(self, config: Optional[RiskConfig] = None) -> None:
        self.config = config or RiskConfig()
        self._circuit_broken: bool = False
        self._circuit_broken_at: Optional[datetime] = None
        self._circuit_broken_reason: str = ""

    def check_order(
        self,
        symbol: str,
        qty: int,
        price: float,
        side: str,
        portfolio_value: float,
        cash: float,
        open_positions: int,
        daily_pnl: float,
        trades_today: int,
        existing_position_value: float = 0.0,
    ) -> RiskCheckResult:
        if qty <= 0 or price <= 0 or portfolio_value <= 0:
            return RiskCheckResult(approved=False, reason="Invalid order parameters")
        order_value = qty * price
        cb = self._check_circuit_breaker(daily_pnl, portfolio_value)
        if cb is not None:
            return cb
        tc = self._check_trade_count(trades_today)
        if tc is not None:
            return tc
        if side.lower() == "sell":
            return RiskCheckResult(
                approved=True,
                reason="Sell order approved",
                adjusted_qty=qty,
                adjusted_value=order_value,
            )
        mp = self._check_max_positions(open_positions, existing_position_value)
        if mp is not None:
            return mp
        cr = self._check_cash_reserve(cash, order_value, portfolio_value)
        if cr is not None:
            return cr
        qty, order_value, size_msg = self._apply_position_size_limit(
            qty, price, order_value, portfolio_value, existing_position_value
        )
        if qty <= 0:
            return RiskCheckResult(approved=False, reason=size_msg)
        ov = self._check_order_value_bounds(order_value)
        if ov is not None:
            return ov
        return RiskCheckResult(
            approved=True,
            reason=size_msg or "All risk checks passed",
            adjusted_qty=qty,
            adjusted_value=order_value,
        )

    def calculate_position_size(
        self, price: float, portfolio_value: float, existing_position_value: float = 0.0
    ) -> int:
        if price <= 0 or portfolio_value <= 0:
            return 0
        max_position_value = portfolio_value * self.config.max_position_pct
        remaining_budget = max(0.0, max_position_value - existing_position_value)
        return int(remaining_budget / price)

    def trip_circuit_breaker(self, reason: str = "Manual override") -> None:
        self._circuit_broken = True
        self._circuit_broken_at = datetime.now(timezone.utc)
        self._circuit_broken_reason = reason
        logger.warning("Circuit breaker TRIPPED: %s", reason)

    def reset_circuit_breaker(self) -> None:
        self._circuit_broken = False
        self._circuit_broken_at = None
        self._circuit_broken_reason = ""
        logger.info("Circuit breaker RESET")

    @property
    def is_circuit_broken(self) -> bool:
        return self._circuit_broken

    def check_slippage(self, signal_price: float, fill_price: float) -> bool:
        if signal_price <= 0:
            return False
        slippage = abs(fill_price - signal_price) / signal_price
        return slippage <= self.config.slippage_tolerance_pct

    def _check_circuit_breaker(
        self, daily_pnl: float, portfolio_value: float
    ) -> Optional[RiskCheckResult]:
        if self._circuit_broken:
            return RiskCheckResult(
                approved=False,
                reason=f"Circuit breaker is tripped: {self._circuit_broken_reason}",
            )
        daily_pnl_pct = daily_pnl / portfolio_value
        if daily_pnl_pct <= self.config.max_daily_loss_pct:
            self.trip_circuit_breaker(
                f"Daily loss {daily_pnl_pct:.2%} exceeded threshold {self.config.max_daily_loss_pct:.2%}"
            )
            return RiskCheckResult(approved=False, reason=self._circuit_broken_reason)
        return None

    def _check_trade_count(self, trades_today: int) -> Optional[RiskCheckResult]:
        if trades_today >= self.config.max_trades_per_day:
            return RiskCheckResult(
                approved=False,
                reason=f"Daily trade limit reached ({trades_today}/{self.config.max_trades_per_day})",
            )
        return None

    def _check_max_positions(
        self, open_positions: int, existing_position_value: float
    ) -> Optional[RiskCheckResult]:
        if (
            existing_position_value == 0
            and open_positions >= self.config.max_open_positions
        ):
            return RiskCheckResult(
                approved=False,
                reason=f"Max open positions reached ({open_positions}/{self.config.max_open_positions})",
            )
        return None

    def _check_cash_reserve(
        self, cash: float, order_value: float, portfolio_value: float
    ) -> Optional[RiskCheckResult]:
        min_cash = portfolio_value * self.config.min_cash_reserve_pct
        if cash - order_value < min_cash:
            return RiskCheckResult(
                approved=False,
                reason=f"Order would breach minimum cash reserve (need ${min_cash:.2f}, would leave ${cash - order_value:.2f})",
            )
        return None

    def _apply_position_size_limit(
        self,
        qty: int,
        price: float,
        order_value: float,
        portfolio_value: float,
        existing_position_value: float,
    ) -> tuple[int, float, str]:
        max_position_value = portfolio_value * self.config.max_position_pct
        remaining_budget = max(0.0, max_position_value - existing_position_value)
        max_qty = int(remaining_budget / price)
        if qty <= max_qty:
            return qty, order_value, "All risk checks passed"
        if max_qty <= 0:
            return (
                0,
                0.0,
                f"Position already at or exceeds limit (existing ${existing_position_value:.2f} >= max ${max_position_value:.2f})",
            )
        new_value = max_qty * price
        logger.info("Position size reduced: %d -> %d shares", qty, max_qty)
        return (
            max_qty,
            new_value,
            f"Quantity reduced {qty}->{max_qty} to respect position size limit",
        )

    def _check_order_value_bounds(
        self, order_value: float
    ) -> Optional[RiskCheckResult]:
        if order_value > self.config.max_order_value:
            return RiskCheckResult(
                approved=False,
                reason=f"Order value ${order_value:.2f} exceeds max ${self.config.max_order_value:.2f}",
            )
        if order_value < self.config.min_order_value:
            return RiskCheckResult(
                approved=False,
                reason=f"Order value ${order_value:.2f} below minimum ${self.config.min_order_value:.2f}",
            )
        return None
