"""Enhanced health check endpoint with system status."""

from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter

from alpaca_trader.core.database import DATABASE_URL

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Enhanced health check with DB connectivity and system status.

    Returns:
        JSON with status, version, timestamp, database connectivity,
        and service availability information.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Check database connectivity
    db_status = "ok"
    try:
        async with aiosqlite.connect(DATABASE_URL) as db:
            await db.execute("SELECT 1")
    except Exception:
        db_status = "error"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "version": "0.1.0",
        "timestamp": timestamp,
        "database": db_status,
        "services": {
            "api": "ok",
            "database": db_status,
        },
    }
