"""Alerts API routes."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from alpaca_trader.core import database as db
from alpaca_trader.alerts.checker import AlertChecker
from alpaca_trader.alerts.scanner import ScheduledScanner

router = APIRouter()


class CreateAlertRequest(BaseModel):
    alert_type: str  # fill, pnl, expiry, price, squeeze, signal
    symbol: str
    condition: dict = {}
    message: Optional[str] = None


@router.get("")
async def list_alerts(
    status: Optional[str] = Query(None, description="Filter: active, triggered, dismissed"),
    alert_type: Optional[str] = Query(None, description="Filter by type"),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
):
    """List alerts with optional filters."""
    return await db.alerts_list(status=status, alert_type=alert_type, symbol=symbol)


@router.post("")
async def create_alert(request: CreateAlertRequest):
    """Create a new alert."""
    valid_types = ("fill", "pnl", "expiry", "price", "squeeze", "signal")
    if request.alert_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid alert_type. Choose from: {', '.join(valid_types)}")
    alert_id = await db.alerts_add(
        alert_type=request.alert_type,
        symbol=request.symbol,
        condition=request.condition,
        message=request.message,
    )
    return await db.alerts_get(alert_id)


@router.delete("/{alert_id}")
async def dismiss_alert(alert_id: int):
    """Dismiss an alert by ID."""
    ok = await db.alerts_dismiss(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return {"success": True, "id": alert_id}


@router.post("/check")
async def run_alert_check():
    """Trigger a manual alert check. Returns triggered alerts."""
    try:
        checker = AlertChecker()
        triggered = await checker.check_all()
        return {"triggered": triggered, "count": len(triggered)}
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alert check error: {e}")
