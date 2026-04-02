"""OptionsTrader orchestrator — scan signals → select strikes → risk check → execute → journal."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, time as dtime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from alpaca_trader.core import database as db
from alpaca_trader.engine.trade_proposals import queue_proposal
from alpaca_trader.engine.risk_manager import RiskManager, RiskConfig
from alpaca_trader.engine.order_executor import OrderExecutor, ExecutorConfig
from alpaca_trader.engine.options_position_manager import OptionsPositionManager
from alpaca_trader.engine.trade_journal import TradeJournal
from alpaca_trader.engine.strike_selector import StrikeSelector
from alpaca_trader.strategies.scanner import WatchlistScanner
from alpaca_trader.strategies.regime import get_market_regime
from alpaca_trader.strategies.iv_rank import get_iv_rank
from alpaca_trader.strategies.earnings_filter import check_earnings

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_MARKET_OPEN = dtime(9, 30)
_MARKET_CLOSE = dtime(16, 0)

MAX_CONCURRENT_OPTION_POSITIONS = 5
MAX_PREMIUM_PCT = 0.02  # 2% of portfolio per trade
MAX_TOTAL_PREMIUM_PCT = 0.10  # 10% of portfolio total options exposure

# Correlation groups — max 1 position per group
CORRELATION_GROUPS = {
    "mega_tech": {"AAPL", "MSFT", "GOOGL", "META", "AMZN"},
    "semiconductors": {"NVDA", "AMD", "ARM"},
    "index_etfs": {"SPY", "QQQ"},
    "ev_momentum": {"TSLA"},
    "fintech": {"SQ", "SOFI", "COIN"},
    "social_media": {"SNAP", "ROKU"},
    "crypto_adjacent": {"COIN", "MARA"},
    "retail": {"SHOP", "UBER"},
}


def get_correlation_group(symbol: str) -> Optional[str]:
    """Return the correlation group for a symbol, or None if not in any group."""
    for group, members in CORRELATION_GROUPS.items():
        if symbol.upper() in members:
            return group
    return None


def _conviction_size(contracts: int, strength: float) -> int:
    """Scale contract count by signal strength (conviction-based sizing)."""
    if strength >= 0.7:
        factor = 1.0
    elif strength >= 0.4:
        factor = 0.6
    else:
        factor = 0.3
    return max(1, int(contracts * factor))


def is_market_open(now: Optional[datetime] = None) -> bool:
    """Return True if US equities market is currently open (Mon-Fri, 9:30-16:00 ET)."""
    if now is None:
        now = datetime.now(timezone.utc)
    et_now = now.astimezone(_ET)
    if et_now.weekday() >= 5:
        return False
    return _MARKET_OPEN <= et_now.time() < _MARKET_CLOSE


def _get_chain_expiry_range():
    """Return (gte, lte) date range for 4-8 DTE options."""
    from datetime import date

    today = date.today()
    return today + timedelta(days=4), today + timedelta(days=8)


class OptionsTrader:
    """Options auto-trading orchestrator. Designed to run every 5 min during market hours."""

    ENABLED_KEY = "auto_trader_enabled"
    MODE_KEY = "trading_mode"

    def __init__(
        self,
        risk_manager: Optional[RiskManager] = None,
        order_executor: Optional[OrderExecutor] = None,
        position_manager: Optional[OptionsPositionManager] = None,
        trade_journal: Optional[TradeJournal] = None,
        scanner: Optional[WatchlistScanner] = None,
        strike_selector: Optional[StrikeSelector] = None,
        dry_run: bool = False,
    ) -> None:
        self.risk_manager = risk_manager or RiskManager(
            config=RiskConfig(
                max_open_positions=MAX_CONCURRENT_OPTION_POSITIONS,
                max_position_pct=MAX_PREMIUM_PCT,
            )
        )
        if order_executor is None:
            cfg = ExecutorConfig(dry_run=dry_run)
            order_executor = OrderExecutor(config=cfg)
        self.order_executor = order_executor
        self.position_manager = position_manager or OptionsPositionManager()
        self.trade_journal = trade_journal or TradeJournal()
        self.scanner = scanner or WatchlistScanner()
        self.strike_selector = (
            strike_selector  # initialized in run_cycle after fetching portfolio_value
        )
        self._dry_run = dry_run
        self._trades_today: int = 0

    async def enable(self) -> None:
        """Enable auto-trading (persisted to DB settings)."""
        await db.setting_set(self.ENABLED_KEY, "true")
        logger.info("OptionsTrader enabled")

    async def disable(self) -> None:
        """Disable auto-trading."""
        await db.setting_set(self.ENABLED_KEY, "false")
        logger.info("OptionsTrader disabled")

    async def is_enabled(self) -> bool:
        val = await db.setting_get(self.ENABLED_KEY)
        return val == "true"

    async def status(self) -> dict:
        """Return engine status dict."""
        enabled = await self.is_enabled()
        trade_count = await self.trade_journal.get_trade_count()
        stats = await self.trade_journal.get_stats()
        mode = await db.setting_get(self.MODE_KEY) or "stocks"
        return {
            "enabled": enabled,
            "mode": mode,
            "dry_run": self._dry_run,
            "circuit_breaker": self.risk_manager.is_circuit_broken,
            "circuit_breaker_reason": self.risk_manager._circuit_broken_reason,
            "trades_today": self._trades_today,
            "closed_trades": trade_count,
            "market_open": is_market_open(),
            "journal_stats": stats,
        }

    async def run_cycle(self) -> dict:
        """Run one full options auto-trade cycle.

        Steps:
        1. Check enabled + market open
        2. Fetch account info
        3. Check open option positions for exits
        4. Scan watchlist for signals
        5. Risk check + select strike for each signal
        6. Execute option entries
        7. Return summary
        """
        summary: dict = {
            "enabled": False,
            "market_open": False,
            "exits_checked": 0,
            "exits_executed": 0,
            "signals_found": 0,
            "entries_approved": 0,
            "entries_executed": 0,
            "proposals_queued": 0,
            "errors": [],
            "cycle_time": datetime.now(timezone.utc).isoformat(),
            "mode": "options",
        }

        enabled = await self.is_enabled()
        summary["enabled"] = enabled
        market_open = is_market_open()
        summary["market_open"] = market_open

        if not enabled:
            logger.info("OptionsTrader: cycle skipped — not enabled")
            return summary
        if not market_open:
            logger.info("OptionsTrader: cycle skipped — market closed")
            return summary
        if self.risk_manager.is_circuit_broken:
            summary["errors"].append(
                f"Circuit breaker: {self.risk_manager._circuit_broken_reason}"
            )
            return summary

        # Check market regime
        try:
            market_regime = get_market_regime()
            summary["market_regime"] = market_regime.regime
            summary["regime_confidence"] = round(market_regime.confidence, 2)
            logger.info(
                "OptionsTrader: market regime=%s rsi=%.1f confidence=%.2f",
                market_regime.regime,
                market_regime.spy_rsi,
                market_regime.confidence,
            )
        except Exception as e:
            summary["errors"].append(f"Regime check failed: {e}")
            market_regime = None

        # Fetch account
        try:
            from alpaca_trader.core import client as alpaca

            account = alpaca.get_account()
            portfolio_value = float(account.get("portfolio_value") or 0)
            cash = float(account.get("cash") or 0)
            daily_pnl = (
                float(account.get("equity", portfolio_value) or 0) - portfolio_value
            )
        except Exception as e:
            summary["errors"].append(f"Account fetch failed: {e}")
            logger.error("OptionsTrader: account fetch failed: %s", e)
            return summary

        # Initialize StrikeSelector with live portfolio_value
        selector = self.strike_selector or StrikeSelector(
            portfolio_value=portfolio_value
        )

        # Check open option positions for exits
        try:
            from alpaca_trader.core import client as alpaca

            positions = alpaca.get_positions()
        except Exception as e:
            summary["errors"].append(f"Positions fetch failed: {e}")
            positions = []

        open_journal = await self.trade_journal.get_trades(status="open", limit=200)
        exits = self.position_manager.check_exits(
            positions, journal_entries=open_journal
        )
        summary["exits_checked"] = len(positions)

        for exit_pos in exits:
            symbol = exit_pos.get("symbol", "")
            exit_reason = exit_pos.get("exit_reason", "exit_rule")
            try:
                current_price = float(exit_pos.get("current_price") or 0)
                qty = int(float(exit_pos.get("qty") or 0))
                if qty <= 0:
                    continue

                result = self.order_executor.place_market_order(symbol, qty, "sell")
                if result.success:
                    summary["exits_executed"] += 1
                    self._trades_today += 1
                    # Find journal entry by option_symbol
                    open_trade = None
                    for jt in open_journal:
                        if (jt.get("option_symbol") or "").upper() == symbol.upper():
                            open_trade = jt
                            break
                    if open_trade is None:
                        open_trade = await self.trade_journal.get_open_trade_for_symbol(
                            symbol
                        )
                    if open_trade:
                        await self.trade_journal.log_exit(
                            open_trade["id"], current_price, exit_reason
                        )
                    logger.info(
                        "Options exit: %s qty=%d reason=%s", symbol, qty, exit_reason
                    )
                else:
                    summary["errors"].append(
                        f"Exit order failed for {symbol}: {result.error}"
                    )
            except Exception as e:
                summary["errors"].append(f"Exit error for {symbol}: {e}")
                logger.error("OptionsTrader: exit error for %s: %s", symbol, e)

        # Scan for signals
        try:
            watchlist = await db.watchlist_list()
            symbols = [w["symbol"] for w in watchlist]
        except Exception as e:
            summary["errors"].append(f"Watchlist fetch failed: {e}")
            symbols = []

        if not symbols:
            return summary

        best_by_symbol: dict[str, object] = {}
        for strategy in ("bounce", "bb_rsi_reversal", "momentum", "squeeze"):
            try:
                for s in self.scanner.scan(symbols, strategy=strategy, period="1D"):
                    if s.detected:
                        existing = best_by_symbol.get(s.symbol)
                        if existing is None or s.strength > existing.strength:  # type: ignore[union-attr]
                            best_by_symbol[s.symbol] = s
            except Exception as e:
                summary["errors"].append(f"Scanner failed ({strategy}): {e}")

        for strategy in ("bb_rsi_reversal", "bounce"):
            try:
                for s in self.scanner.scan(
                    symbols, strategy=strategy, period="15Min", limit=100
                ):
                    if s.detected:
                        existing = best_by_symbol.get(s.symbol)
                        if existing is None or s.strength > existing.strength:  # type: ignore[union-attr]
                            best_by_symbol[s.symbol] = s
            except Exception as e:
                summary["errors"].append(f"Intraday scanner failed ({strategy}): {e}")

        actionable = list(best_by_symbol.values())
        summary["signals_found"] = len(actionable)

        open_option_symbols = {(p.get("symbol") or "").upper() for p in positions}
        open_positions_count = len(positions)

        # Compute portfolio theta limit (sum of |theta| * 100 per contract across open positions)
        total_daily_theta = 0.0
        for jt in open_journal:
            t = jt.get("theta_at_entry") or 0.0
            c = jt.get("contracts") or 1
            total_daily_theta += abs(float(t)) * 100 * int(c)
        theta_limit = portfolio_value * 0.005  # 0.5% of portfolio per day

        if total_daily_theta > theta_limit:
            logger.info(
                "OptionsTrader: portfolio theta limit reached (%.2f/day > limit %.2f)",
                total_daily_theta,
                theta_limit,
            )
            summary["errors"].append(
                f"portfolio theta limit reached ({total_daily_theta:.2f}/day)"
            )
            return summary

        # Build set of underlying symbols in open positions for correlation checks
        open_underlying_symbols: set[str] = set()
        for p in positions:
            sym = (p.get("symbol") or "").upper()
            # Option symbols are like AAPL251219C00150000 — extract underlying (letters prefix)
            underlying_guess = ""
            for ch in sym:
                if ch.isalpha():
                    underlying_guess += ch
                else:
                    break
            if underlying_guess:
                open_underlying_symbols.add(underlying_guess)

        for signal in actionable:
            underlying = signal.symbol
            if open_positions_count >= MAX_CONCURRENT_OPTION_POSITIONS:
                logger.info(
                    "OptionsTrader: max positions reached (%d)", open_positions_count
                )
                break

            # Skip if we already hold an option on this underlying
            if any(underlying in sym for sym in open_option_symbols):
                continue

            try:
                direction = "long" if signal.direction == "long" else "short"

                # Regime filter: skip entries that don't match market regime
                if market_regime is not None:
                    regime = market_regime.regime
                    if regime == "bearish" and direction == "long":
                        logger.info(
                            "OptionsTrader: skipping %s long — bearish regime",
                            underlying,
                        )
                        continue
                    if regime == "bullish" and direction == "short":
                        logger.info(
                            "OptionsTrader: skipping %s short — bullish regime",
                            underlying,
                        )
                        continue

                # Correlation limiter — skip if already holding a correlated position
                corr_group = get_correlation_group(underlying)
                if corr_group is not None:
                    corr_collision = False
                    for held_sym in open_underlying_symbols:
                        held_group = get_correlation_group(held_sym)
                        if held_group == corr_group:
                            logger.info(
                                "OptionsTrader: skipping %s, already holding correlated position in %s",
                                underlying,
                                corr_group,
                            )
                            corr_collision = True
                            break
                    if corr_collision:
                        continue

                # Earnings filter — skip if near earnings event
                try:
                    earnings_check = await check_earnings(underlying)
                    if earnings_check.should_skip:
                        logger.info(
                            "OptionsTrader: skipping %s — earnings filter: %s",
                            underlying,
                            earnings_check.reason,
                        )
                        continue
                except Exception as _e:
                    logger.warning(
                        "OptionsTrader: earnings check failed for %s: %s",
                        underlying,
                        _e,
                    )

                # IV Rank filter — skip if IV too expensive; reduce size if mid-range
                iv_size_factor = 1.0
                try:
                    iv_result = await get_iv_rank(underlying)
                    if iv_result.is_expensive:
                        logger.info(
                            "OptionsTrader: skipping %s, IV too expensive (rank=%.1f)",
                            underlying,
                            iv_result.iv_rank,
                        )
                        continue
                    elif not iv_result.is_cheap:
                        # IV rank 40-60: proceed with 75% size
                        iv_size_factor = 0.75
                        logger.info(
                            "OptionsTrader: %s IV rank=%.1f (neutral) — reducing size to 75%%",
                            underlying,
                            iv_result.iv_rank,
                        )
                    else:
                        logger.info(
                            "OptionsTrader: %s IV rank=%.1f (cheap) — full size",
                            underlying,
                            iv_result.iv_rank,
                        )
                except Exception as _e:
                    logger.warning(
                        "OptionsTrader: IV rank check failed for %s: %s", underlying, _e
                    )

                # Fix 1: Use self-contained select_contract (pass portfolio_value, not raw chain)
                # This uses direction-aware strike range filtering inside StrikeSelector._fetch_chain
                # so puts get strikes near current price (90%-105%), not 75% OTM junk
                contract = selector.select_contract(
                    underlying, direction, portfolio_value
                )
                if contract is None:
                    logger.info(
                        "OptionsTrader: no suitable contract for %s %s",
                        underlying,
                        direction,
                    )
                    continue

                option_symbol = contract["symbol"]
                ask_price = contract["ask"]
                contracts_qty = contract["contracts_to_buy"]

                # Conviction-based sizing by signal strength
                contracts_qty = _conviction_size(contracts_qty, signal.strength)

                # IV rank size factor (75% if IV rank 40-60)
                contracts_qty = max(1, int(contracts_qty * iv_size_factor))

                # Neutral regime: reduce position size by 50%
                if market_regime is not None and market_regime.regime == "neutral":
                    contracts_qty = max(1, contracts_qty // 2)
                    logger.info(
                        "OptionsTrader: neutral regime — halved contracts to %d for %s",
                        contracts_qty,
                        option_symbol,
                    )

                # Risk check on the premium cost
                risk_result = self.risk_manager.check_order(
                    symbol=option_symbol,
                    qty=contracts_qty,
                    price=ask_price * 100,  # premium per contract
                    side="buy",
                    portfolio_value=portfolio_value,
                    cash=cash,
                    open_positions=open_positions_count,
                    daily_pnl=daily_pnl,
                    trades_today=self._trades_today,
                )
                if risk_result.rejected:
                    logger.info(
                        "OptionsTrader: risk rejected %s: %s",
                        option_symbol,
                        risk_result.reason,
                    )
                    continue

                summary["entries_approved"] += 1

                # Queue proposal for review instead of auto-executing
                try:
                    _iv_for_proposal = None
                    try:
                        _iv_for_proposal = await get_iv_rank(underlying)
                    except Exception:
                        pass

                    proposal = {
                        "symbol": underlying,
                        "option_symbol": contract["symbol"],
                        "direction": signal.direction,
                        "strike": contract["strike"],
                        "expiry": contract["expiry"],
                        "delta": contract["delta"],
                        "premium": contract.get("ask") or contract.get("last_price"),
                        "contracts": contracts_qty,
                        "strategy": signal.strategy,
                        "signal_strength": signal.strength,
                        "signal_details": signal.details,
                        "regime": market_regime.regime if market_regime else None,
                        "iv_rank": _iv_for_proposal.iv_rank
                        if _iv_for_proposal
                        else None,
                        "underlying_price": float(
                            contract.get("underlying_price") or 0
                        ),
                        "reason": f"{signal.strategy} signal on {underlying}: {signal.direction}, strength={signal.strength:.2f}",
                    }
                    proposal_id = await queue_proposal(proposal)
                    summary["proposals_queued"] += 1
                    logger.info(
                        "Options proposal queued: %s %s contracts=%d premium=%.2f proposal_id=%s",
                        underlying,
                        option_symbol,
                        contracts_qty,
                        ask_price,
                        proposal_id,
                    )
                except Exception as _pe:
                    summary["errors"].append(
                        f"Failed to queue proposal for {option_symbol}: {_pe}"
                    )

            except Exception as e:
                summary["errors"].append(f"Entry error for {underlying}: {e}")
                logger.error("OptionsTrader: entry error for %s: %s", underlying, e)

        return summary
