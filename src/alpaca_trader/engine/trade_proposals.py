"""Trade proposal queue — signals get queued here for review, not auto-executed."""

import json
from datetime import datetime, timezone
from alpaca_trader.core import database as db


async def queue_proposal(proposal: dict) -> str:
    """Queue a trade proposal for review. Returns proposal ID."""
    await db.init_db()
    proposals_raw = await db.setting_get("trade_proposals") or "[]"
    proposals = json.loads(proposals_raw)

    proposal_id = (
        f"prop-{len(proposals)+1:04d}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
    )
    proposal["id"] = proposal_id
    proposal["status"] = "pending"
    proposal["queued_at"] = datetime.now(timezone.utc).isoformat()
    proposals.append(proposal)

    # Keep last 50
    proposals = proposals[-50:]
    await db.setting_set("trade_proposals", json.dumps(proposals))
    return proposal_id


async def get_pending_proposals() -> list[dict]:
    """Get all pending proposals."""
    await db.init_db()
    proposals_raw = await db.setting_get("trade_proposals") or "[]"
    proposals = json.loads(proposals_raw)
    return [p for p in proposals if p.get("status") == "pending"]


async def mark_proposal(proposal_id: str, status: str, notes: str = "") -> bool:
    """Mark a proposal as approved/rejected/expired."""
    await db.init_db()
    proposals_raw = await db.setting_get("trade_proposals") or "[]"
    proposals = json.loads(proposals_raw)
    for p in proposals:
        if p.get("id") == proposal_id:
            p["status"] = status
            p["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            p["notes"] = notes
            await db.setting_set("trade_proposals", json.dumps(proposals))
            return True
    return False


async def get_all_proposals(limit: int = 20) -> list[dict]:
    """Get recent proposals regardless of status."""
    await db.init_db()
    proposals_raw = await db.setting_get("trade_proposals") or "[]"
    proposals = json.loads(proposals_raw)
    return proposals[-limit:]
