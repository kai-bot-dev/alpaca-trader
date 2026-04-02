"""Strike selector — filters and scores an options chain to find the best contract.

Can be called two ways:
  1. Self-contained:  ss.select_contract("AAPL", "long", 115000)
     Fetches current price, builds near-money chain internally.
  2. Pre-fetched chain (legacy): ss.select_contract("AAPL", "long", chain_list)
     Same scoring logic; caller is responsible for chain quality.
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Scoring weights (must sum to 1.0)
_W_DELTA = 0.40
_W_THETA = 0.30
_W_OI = 0.20
_W_SPREAD = 0.10

_IDEAL_DELTA = 0.60
_MIN_DELTA = 0.20
_MAX_DELTA = 0.80
_MIN_OI = 1
_MAX_SPREAD_PCT = 0.40
_MIN_DTE = 4
_MAX_DTE = 8
_MAX_THETA_BURN = 0.10
_MAX_CONTRACTS = 10
_MIN_CONTRACTS = 1


def _parse_expiry(expiry_raw):
    if isinstance(expiry_raw, date):
        return expiry_raw
    if not expiry_raw:
        return None
    try:
        return date.fromisoformat(str(expiry_raw)[:10])
    except (ValueError, TypeError):
        return None


def _dte(expiry):
    return (expiry - date.today()).days


def _estimate_delta(option_type, stock_price, strike):
    if stock_price <= 0 or strike <= 0:
        return 0.5 if option_type == "call" else -0.5
    moneyness = (stock_price - strike) / (stock_price * 0.10)
    if option_type == "call":
        return max(0.0, min(1.0, 0.5 + moneyness))
    else:
        return max(-1.0, min(0.0, -0.5 + moneyness))


def _get_current_price(underlying):
    try:
        from alpaca_trader.core import client as alpaca

        bars = alpaca.get_stock_bars(underlying, period="1D", limit=2)
        if bars:
            return float(bars[-1]["close"])
    except Exception as e:
        logger.warning("StrikeSelector: failed to get price for %s: %s", underlying, e)
    return None


def _fetch_chain(underlying, direction, stock_price):
    from alpaca_trader.core import client as alpaca

    option_type = "call" if direction == "long" else "put"
    today = date.today()
    exp_gte = today + timedelta(days=4)
    exp_lte = today + timedelta(days=8)
    if direction == "long":
        strike_gte = stock_price * 0.95
        strike_lte = stock_price * 1.10
    else:
        strike_gte = stock_price * 0.90
        strike_lte = stock_price * 1.05
    try:
        chain = alpaca.get_option_chain(
            underlying_symbol=underlying,
            expiration_date_gte=exp_gte,
            expiration_date_lte=exp_lte,
            option_type=option_type,
            strike_price_gte=strike_gte,
            strike_price_lte=strike_lte,
            limit=50,
        )
        if chain:
            return chain
    except Exception as e:
        logger.warning(
            "StrikeSelector: narrow chain fetch failed for %s: %s", underlying, e
        )
    logger.info("StrikeSelector: trying wider expiry window for %s", underlying)
    exp_gte = today + timedelta(days=3)
    exp_lte = today + timedelta(days=14)
    try:
        chain = alpaca.get_option_chain(
            underlying_symbol=underlying,
            expiration_date_gte=exp_gte,
            expiration_date_lte=exp_lte,
            option_type=option_type,
            strike_price_gte=strike_gte,
            strike_price_lte=strike_lte,
            limit=100,
        )
        return chain or []
    except Exception as e:
        logger.warning(
            "StrikeSelector: wide chain fetch failed for %s: %s", underlying, e
        )
        return []


class StrikeSelector:
    def __init__(self, portfolio_value=110_000.0):
        self.portfolio_value = portfolio_value

    def select_contract(self, underlying, direction, chain_or_budget):
        if isinstance(chain_or_budget, (int, float)):
            portfolio_value = float(chain_or_budget)
            stock_price = _get_current_price(underlying)
            if stock_price is None:
                logger.warning(
                    "StrikeSelector: cannot get price for %s, aborting", underlying
                )
                return None
            logger.info(
                "StrikeSelector: %s price=%.2f, fetching near-money chain",
                underlying,
                stock_price,
            )
            chain_data = _fetch_chain(underlying, direction, stock_price)
        else:
            portfolio_value = self.portfolio_value
            chain_data = list(chain_or_budget)
            stock_price = None

        option_type = "call" if direction == "long" else "put"
        candidates = []

        for contract in chain_data:
            sym = contract.get("symbol", "")

            contract_type = (contract.get("type") or "").lower()
            if contract_type not in ("call", "put"):
                if len(sym) >= 15:
                    cp_char = sym[-9] if len(sym) >= 9 else ""
                    contract_type = (
                        "call" if cp_char == "C" else "put" if cp_char == "P" else ""
                    )
            if contract_type != option_type:
                continue

            expiry = _parse_expiry(contract.get("expiration_date"))
            if expiry is None:
                continue
            days = _dte(expiry)
            if not (_MIN_DTE <= days <= _MAX_DTE):
                continue

            strike_raw = contract.get("strike_price")
            try:
                strike = float(strike_raw) if strike_raw is not None else 0.0
            except (TypeError, ValueError):
                strike = 0.0

            greeks = contract.get("greeks") or {}
            raw_delta = greeks.get("delta")
            raw_theta = greeks.get("theta")
            iv = greeks.get("implied_volatility")

            if raw_delta is None:
                ref_price = stock_price or strike
                delta = _estimate_delta(option_type, ref_price, strike)
                theta = 0.0
            else:
                try:
                    delta = float(raw_delta)
                    theta = float(raw_theta) if raw_theta is not None else 0.0
                except (TypeError, ValueError):
                    delta = _estimate_delta(option_type, stock_price or strike, strike)
                    theta = 0.0

            abs_delta = abs(delta)
            if not (_MIN_DELTA <= abs_delta <= _MAX_DELTA):
                continue

            raw_oi = contract.get("open_interest") or 0
            try:
                oi = int(float(raw_oi))
            except (TypeError, ValueError):
                oi = 0

            try:
                bid = float(contract.get("bid_price") or 0)
                ask = float(contract.get("ask_price") or 0)
            except (TypeError, ValueError):
                bid = ask = 0.0

            last_price = None
            try:
                last_price = (
                    float(
                        contract.get("last_price") or contract.get("close_price") or 0
                    )
                    or None
                )
            except (TypeError, ValueError):
                pass

            if ask <= 0 and bid <= 0:
                if last_price and last_price > 0:
                    bid = last_price * 0.95
                    ask = last_price * 1.05
                else:
                    continue

            if ask <= 0:
                ask = bid * 1.10
            if bid <= 0:
                bid = ask * 0.90

            mid = (bid + ask) / 2.0
            if mid <= 0:
                continue
            spread = ask - bid
            spread_pct = spread / mid
            if spread_pct > _MAX_SPREAD_PCT:
                continue

            theta_burn = abs(theta) / mid if mid > 0 and theta != 0 else 0.0
            if theta_burn > _MAX_THETA_BURN:
                continue

            max_delta_dev = max(_IDEAL_DELTA - _MIN_DELTA, _MAX_DELTA - _IDEAL_DELTA)
            delta_score = max(0.0, 1.0 - abs(abs_delta - _IDEAL_DELTA) / max_delta_dev)
            theta_score = (
                max(0.0, 1.0 - theta_burn / _MAX_THETA_BURN) if theta_burn > 0 else 1.0
            )
            oi_score = min(1.0, oi / 100.0)
            spread_score = max(0.0, 1.0 - spread_pct / _MAX_SPREAD_PCT)
            score = (
                _W_DELTA * delta_score
                + _W_THETA * theta_score
                + _W_OI * oi_score
                + _W_SPREAD * spread_score
            )

            max_premium = portfolio_value * 0.02
            contracts_to_buy = math.floor(max_premium / (ask * 100))
            contracts_to_buy = max(
                _MIN_CONTRACTS, min(_MAX_CONTRACTS, contracts_to_buy)
            )

            candidates.append(
                {
                    "symbol": sym,
                    "strike": strike,
                    "expiry": expiry.isoformat(),
                    "delta": round(delta, 4),
                    "theta": round(theta, 6),
                    "iv": float(iv) if iv is not None else None,
                    "bid": round(bid, 4),
                    "ask": round(ask, 4),
                    "last_price": last_price,
                    "score": round(score, 4),
                    "contracts": contracts_to_buy,
                    "contracts_to_buy": contracts_to_buy,
                    "dte": days,
                }
            )

        if not candidates:
            logger.info(
                "StrikeSelector: no candidates for %s %s after filtering %d contracts",
                underlying,
                direction,
                len(chain_data),
            )
            return None

        best = max(candidates, key=lambda c: c["score"])
        logger.info(
            "StrikeSelector: selected %s score=%.3f delta=%.2f dte=%d ask=%.2f",
            best["symbol"],
            best["score"],
            best["delta"],
            best["dte"],
            best["ask"],
        )
        return best
