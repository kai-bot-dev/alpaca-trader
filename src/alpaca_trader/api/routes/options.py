"""Options chain API routes."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from alpaca_trader.core import client as alpaca

router = APIRouter()


@router.get("/chain/{underlying_symbol}")
async def get_options_chain(
    underlying_symbol: str,
    expiry: Optional[date] = Query(None, description="Exact expiration date (YYYY-MM-DD)"),
    expiry_gte: Optional[date] = Query(None, description="Expiration date on or after"),
    expiry_lte: Optional[date] = Query(None, description="Expiration date on or before"),
    option_type: Optional[str] = Query(None, description="call or put"),
    strike_min: Optional[float] = Query(None, description="Minimum strike price"),
    strike_max: Optional[float] = Query(None, description="Maximum strike price"),
    limit: int = Query(100, ge=1, le=500),
):
    """Get options chain for an underlying symbol with optional filters."""
    try:
        contracts = alpaca.get_option_chain(
            underlying_symbol=underlying_symbol.upper(),
            expiration_date=expiry,
            option_type=option_type,
            strike_price_gte=strike_min,
            strike_price_lte=strike_max,
            limit=limit,
        )
        return {
            "underlying_symbol": underlying_symbol.upper(),
            "contracts": contracts,
            "total": len(contracts),
        }
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alpaca API error: {e}")


@router.get("/contracts")
async def list_contracts(
    underlying_symbol: str = Query(..., description="Underlying ticker symbol"),
    expiry: Optional[date] = Query(None),
    option_type: Optional[str] = Query(None, description="call or put"),
    strike_min: Optional[float] = Query(None),
    strike_max: Optional[float] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """List option contracts without snapshot data (faster)."""
    try:
        contracts = alpaca.get_options_contracts(
            underlying_symbol=underlying_symbol.upper(),
            expiration_date=expiry,
            option_type=option_type,
            strike_price_gte=strike_min,
            strike_price_lte=strike_max,
            limit=limit,
        )
        return {
            "underlying_symbol": underlying_symbol.upper(),
            "contracts": contracts,
            "total": len(contracts),
        }
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alpaca API error: {e}")


@router.post("/symbol")
async def build_option_symbol(
    underlying: str,
    expiry: date,
    option_type: str,
    strike: float,
):
    """Build an OCC option symbol from components."""
    if option_type.lower() not in ("call", "put"):
        raise HTTPException(status_code=400, detail="option_type must be 'call' or 'put'")
    symbol = alpaca.build_option_symbol(
        underlying=underlying,
        expiry=expiry,
        option_type=option_type,
        strike=strike,
    )
    return {"symbol": symbol}
