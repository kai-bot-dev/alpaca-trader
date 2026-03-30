"""Strike selector — filters and scores an options chain to find the best contract."""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# Scoring weights (must sum to 1.0)
_W_DELTA = 0.40
_W_THETA = 0.30
_W_OI = 0.20
_W_SPREAD = 0.10

_IDEAL_DELTA = 0.45
_MIN_DELTA = 0.30
_MAX_DELTA = 0.55
_MIN_OI = 10
_MAX_SPREAD_PCT = 0.15  # 15% of mid
_MIN_DTE = 5
_MAX_DTE = 14
_MAX_THETA_BURN = 0.05  # skip if theta > 5% of price per day
_MAX_CONTRACTS = 10
_MIN_CONTRACTS = 1


def _parse_expiry(expiry_raw) -> Optional[date]:
    """Parse expiry from string or date object. Returns None if unparseable."""
    if isinstance(expiry_raw, date):
        return expiry_raw
    if not expiry_raw:
        return None
    try:
        # Handles "2026-04-04" and "2026-04-04T00:00:00"
        return date.fromisoformat(str(expiry_raw)[:10])
    except (ValueError, TypeError):
        return None


def _dte(expiry: date) -> int:
    """Days to expiration from today."""
    return (expiry - date.today()).days


class StrikeSelector:
    """Score and select the best option contract for a directional signal.

    Args:
        portfolio_value: Current portfolio value used for position sizing.
    """

    def __init__(self, portfolio_value: float = 110_000.0) -> None:
        self.portfolio_value = portfolio_value

    def select_contract(
        self,
        underlying: str,
        direction: str,
        chain_data: list[dict],
    ) -> Optional[dict]:
        """Select the best option contract from a pre-fetched chain.

        Args:
            underlying: Underlying symbol, e.g. "GOOGL".
            direction: "long" to buy calls, "short" to buy puts.
            chain_data: List of enriched contract dicts from client.get_option_chain().
                        Each dict may contain: symbol, expiration_date, open_interest,
                        strike_price, bid_price, ask_price, greeks (dict with delta, theta).

        Returns:
            Dict with keys: symbol, strike, expiry, delta, theta, iv, bid, ask, score,
            contracts_to_buy — or None if no contract passes filters.
        """
        option_type = "call" if direction == "long" else "put"
        candidates = []

        for contract in chain_data:
            sym = contract.get("symbol", "")

            # --- type filter ---
            contract_type = (contract.get("type") or "").lower()
            if contract_type not in ("call", "put"):
                # Some chains embed type in the symbol; fall back to checking the symbol char
                if len(sym) >= 15:
                    cp_char = sym[-9] if len(sym) >= 9 else ""
                    contract_type = "call" if cp_char == "C" else "put" if cp_char == "P" else ""
            if contract_type != option_type:
                continue

            # --- DTE filter ---
            expiry = _parse_expiry(contract.get("expiration_date"))
            if expiry is None:
                continue
            days = _dte(expiry)
            if not (_MIN_DTE <= days <= _MAX_DTE):
                continue

            # --- Greeks ---
            greeks = contract.get("greeks") or {}
            raw_delta = greeks.get("delta")
            raw_theta = greeks.get("theta")
            iv = greeks.get("implied_volatility")
            if raw_delta is None:
                continue
            try:
                delta = float(raw_delta)
                theta = float(raw_theta) if raw_theta is not None else 0.0
            except (TypeError, ValueError):
                continue

            # delta sign: calls positive, puts negative
            abs_delta = abs(delta)
            if not (_MIN_DELTA <= abs_delta <= _MAX_DELTA):
                continue

            # --- OI filter ---
            raw_oi = contract.get("open_interest") or 0
            try:
                oi = int(float(raw_oi))
            except (TypeError, ValueError):
                oi = 0
            if oi < _MIN_OI:
                continue

            # --- Bid/Ask / spread filter ---
            try:
                bid = float(contract.get("bid_price") or 0)
                ask = float(contract.get("ask_price") or 0)
            except (TypeError, ValueError):
                continue
            if ask <= 0:
                continue
            mid = (bid + ask) / 2.0
            if mid <= 0:
                continue
            spread = ask - bid
            spread_pct = spread / mid
            if spread_pct > _MAX_SPREAD_PCT:
                continue

            # --- Theta burn filter ---
            theta_burn = abs(theta) / mid if mid > 0 else 1.0
            if theta_burn > _MAX_THETA_BURN:
                continue

            # --- Score ---
            # Delta proximity: deviation from ideal / max possible deviation
            max_delta_dev = max(_IDEAL_DELTA - _MIN_DELTA, _MAX_DELTA - _IDEAL_DELTA)
            delta_score = max(0.0, 1.0 - abs(abs_delta - _IDEAL_DELTA) / max_delta_dev)

            # Theta: lower burn is better, normalised to [0,1]
            theta_score = max(0.0, 1.0 - theta_burn / _MAX_THETA_BURN)

            # OI: normalised to 100 contracts as reference
            oi_score = min(1.0, oi / 100.0)

            # Spread: tighter is better
            spread_score = max(0.0, 1.0 - spread_pct / _MAX_SPREAD_PCT)

            score = (
                _W_DELTA * delta_score
                + _W_THETA * theta_score
                + _W_OI * oi_score
                + _W_SPREAD * spread_score
            )

            # --- Contracts to buy ---
            max_premium = self.portfolio_value * 0.02
            contracts_to_buy = math.floor(max_premium / (ask * 100))
            contracts_to_buy = max(_MIN_CONTRACTS, min(_MAX_CONTRACTS, contracts_to_buy))

            strike_raw = contract.get("strike_price")
            try:
                strike = float(strike_raw) if strike_raw is not None else 0.0
            except (TypeError, ValueError):
                strike = 0.0

            candidates.append({
                "symbol": sym,
                "strike": strike,
                "expiry": expiry.isoformat(),
                "delta": delta,
                "theta": theta,
                "iv": float(iv) if iv is not None else None,
                "bid": bid,
                "ask": ask,
                "score": score,
                "contracts_to_buy": contracts_to_buy,
                "dte": days,
            })

        if not candidates:
            logger.info(
                "StrikeSelector: no candidates for %s %s after filtering %d contracts",
                underlying, direction, len(chain_data),
            )
            return None

        best = max(candidates, key=lambda c: c["score"])
        logger.info(
            "StrikeSelector: selected %s score=%.3f delta=%.2f dte=%d",
            best["symbol"], best["score"], best["delta"], best["dte"],
        )
        return best
