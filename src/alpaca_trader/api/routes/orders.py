"""Orders API routes."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from alpaca_trader.core import client as alpaca
from alpaca_trader.core.models import PlaceOptionOrderRequest

router = APIRouter()


@router.get("")
async def list_orders(
    status: Optional[str] = Query(None, description="Filter: open, closed, all"),
    limit: int = Query(100, ge=1, le=500),
):
    """Get order history with optional status filter."""
    try:
        return alpaca.get_orders(status=status, limit=limit)
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alpaca API error: {e}")


@router.get("/{order_id}")
async def get_order(order_id: str):
    """Get a specific order by ID."""
    try:
        return alpaca.get_order(order_id)
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Order not found: {e}")


@router.post("")
async def place_order(request: PlaceOptionOrderRequest):
    """Place a new option order."""
    try:
        if request.order_type.value == "market":
            order = alpaca.place_market_order(
                symbol=request.symbol,
                qty=request.qty,
                side=request.side.value,
                time_in_force=request.time_in_force.value,
            )
        else:
            if not request.limit_price:
                raise HTTPException(
                    status_code=400, detail="limit_price required for limit orders"
                )
            order = alpaca.place_limit_order(
                symbol=request.symbol,
                qty=request.qty,
                side=request.side.value,
                limit_price=float(request.limit_price),
                time_in_force=request.time_in_force.value,
            )
        return order
    except HTTPException:
        raise
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Order failed: {e}")


@router.delete("/{order_id}")
async def cancel_order(order_id: str):
    """Cancel an order by ID."""
    try:
        alpaca.cancel_order(order_id)
        return {"success": True, "message": f"Order {order_id} cancelled"}
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cancel failed: {e}")


@router.delete("")
async def cancel_all_orders():
    """Cancel all open orders."""
    try:
        result = alpaca.cancel_all_orders()
        return {"success": True, "cancelled": result}
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cancel all failed: {e}")
