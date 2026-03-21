"""Monitor API routes."""

from fastapi import APIRouter, HTTPException

from alpaca_trader.core import database as db
from alpaca_trader.alerts.scanner import ScheduledScanner

router = APIRouter()


@router.get("/status")
async def monitor_status():
    """Get scanner status: last run time, next scheduled run, active alert count."""
    last_run = await db.setting_get("monitor_last_run")
    last_triggered = await db.setting_get("monitor_last_triggered_count")
    active_alerts = await db.alerts_list(status="active")
    return {
        "last_run": last_run or None,
        "last_triggered_count": int(last_triggered or 0),
        "active_alerts": len(active_alerts),
        "schedule": "Every 15 minutes, 09:30–16:00 ET, Mon–Fri",
    }


@router.post("/run")
async def run_monitor():
    """Trigger a full monitor scan (one-shot)."""
    try:
        scanner = ScheduledScanner()
        result = await scanner.run()
        return result
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Monitor error: {e}")
