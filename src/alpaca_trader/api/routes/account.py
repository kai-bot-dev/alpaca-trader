"""Account API routes."""

from fastapi import APIRouter, HTTPException

from alpaca_trader.core import client as alpaca

router = APIRouter()


@router.get("")
async def get_account():
    """Get account summary including buying power, equity, and cash."""
    try:
        return alpaca.get_account()
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alpaca API error: {e}")


@router.get("/positions")
async def get_positions():
    """Get all open positions with current P&L."""
    try:
        return alpaca.get_positions()
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alpaca API error: {e}")


@router.get("/positions/{symbol_or_id}")
async def get_position(symbol_or_id: str):
    """Get a specific position by symbol or asset ID."""
    try:
        return alpaca.get_position(symbol_or_id)
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Position not found: {e}")
