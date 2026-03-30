"""Order execution layer for alpaca-trader.

Wraps the Alpaca client with retry logic, slippage tracking, and a dry-run mode
so the class can be tested without live API access.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass
class ExecutorConfig:
    max_retries: int = 3
    retry_delay_ms: int = 200
    dry_run: bool = False
    limit_order_timeout_s: int = 60
    max_slippage_pct: float = 0.02


@dataclass
class OrderResult:
    success: bool
    order_id: str
    status: OrderStatus
    symbol: str
    qty: int
    side: str
    order_type: str
    limit_price: Optional[float] = None
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: str = ""
    raw: dict = field(default_factory=dict)
    slippage_pct: Optional[float] = None
    retries: int = 0


class OrderExecutor:
    """Submits orders with retry logic, dry-run support, and slippage tracking."""

    def __init__(self, broker_fn: Optional[Callable] = None, config: Optional[ExecutorConfig] = None) -> None:
        self.config = config or ExecutorConfig()
        self._broker_fn = broker_fn
        self._order_history: list[OrderResult] = []

    def place_market_order(self, symbol: str, qty: int, side: str) -> OrderResult:
        return self._submit(symbol=symbol, qty=qty, side=side, order_type="market")

    def place_limit_order(self, symbol: str, qty: int, side: str, limit_price: float) -> OrderResult:
        return self._submit(symbol=symbol, qty=qty, side=side, order_type="limit", limit_price=limit_price)

    def record_fill(self, order_id: str, fill_price: float, signal_price: float) -> Optional[float]:
        slippage = abs(fill_price - signal_price) / signal_price if signal_price > 0 else None
        for result in self._order_history:
            if result.order_id == order_id:
                result.slippage_pct = slippage
                result.status = OrderStatus.FILLED
                if slippage is not None and slippage > self.config.max_slippage_pct:
                    logger.warning("High slippage on %s: %.2f%%", order_id, slippage * 100)
                break
        return slippage

    @property
    def order_history(self) -> list[OrderResult]:
        return list(self._order_history)

    def get_order(self, order_id: str) -> Optional[OrderResult]:
        for result in self._order_history:
            if result.order_id == order_id:
                return result
        return None

    def _submit(self, symbol: str, qty: int, side: str, order_type: str, limit_price: Optional[float] = None) -> OrderResult:
        if self.config.dry_run:
            return self._dry_run_order(symbol, qty, side, order_type, limit_price)

        if self._broker_fn is None:
            try:
                from alpaca_trader.core import client as alpaca_client
                broker_fn = alpaca_client.place_limit_order if order_type == "limit" else alpaca_client.place_market_order
            except ImportError as exc:
                result = OrderResult(success=False, order_id="", status=OrderStatus.FAILED, symbol=symbol, qty=qty, side=side, order_type=order_type, limit_price=limit_price, error=f"Could not import Alpaca client: {exc}")
                self._order_history.append(result)
                return result
        else:
            broker_fn = self._broker_fn

        last_error = ""
        retries = 0
        for attempt in range(self.config.max_retries + 1):
            try:
                kwargs: dict = {"symbol": symbol, "qty": qty, "side": side}
                if order_type == "limit" and limit_price is not None:
                    kwargs["limit_price"] = limit_price
                raw = broker_fn(**kwargs)
                result = OrderResult(success=True, order_id=raw.get("id", ""), status=OrderStatus.SUBMITTED, symbol=symbol, qty=qty, side=side, order_type=order_type, limit_price=limit_price, raw=raw, retries=retries)
                self._order_history.append(result)
                logger.info("Order submitted: %s %d %s @ %s (id=%s)", side, qty, symbol, order_type, raw.get("id"))
                return result
            except Exception as exc:
                last_error = str(exc)
                retries += 1
                if attempt < self.config.max_retries:
                    delay_s = (self.config.retry_delay_ms * (2 ** attempt)) / 1000.0
                    logger.warning("Order submission failed (attempt %d/%d): %s", attempt + 1, self.config.max_retries + 1, exc)
                    time.sleep(delay_s)

        result = OrderResult(success=False, order_id="", status=OrderStatus.FAILED, symbol=symbol, qty=qty, side=side, order_type=order_type, limit_price=limit_price, error=last_error, retries=retries)
        self._order_history.append(result)
        logger.error("Order failed after %d retries: %s", retries, last_error)
        return result

    def _dry_run_order(self, symbol: str, qty: int, side: str, order_type: str, limit_price: Optional[float]) -> OrderResult:
        dry_id = f"dry-run-{len(self._order_history) + 1:04d}"
        logger.info("[DRY RUN] Would submit %s %d %s %s%s", side, qty, symbol, order_type, f" @ ${limit_price}" if limit_price else "")
        result = OrderResult(success=True, order_id=dry_id, status=OrderStatus.SUBMITTED, symbol=symbol, qty=qty, side=side, order_type=order_type, limit_price=limit_price, raw={"id": dry_id, "dry_run": True})
        self._order_history.append(result)
        return result
