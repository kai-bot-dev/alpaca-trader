"""TelegramDeliveryQueue — file-based queue for alert delivery via OpenClaw."""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

_QUEUE_FILE = Path(__file__).resolve().parents[3] / "data" / "alert-queue.json"

logger = logging.getLogger(__name__)


def _load_queue() -> list[dict]:
    if not _QUEUE_FILE.exists():
        return []
    try:
        with open(_QUEUE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_queue(queue: list[dict]) -> None:
    _QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2, default=str)


class TelegramDeliveryQueue:
    """File-based queue that buffers triggered alerts for OpenClaw delivery."""

    def queue_alert(
        self, alert: dict, context: dict | None = None, severity: str = "info"
    ) -> str:
        """Write a triggered alert to the queue. Returns the queue entry ID.

        Duplicate prevention: alerts with the same alert_id are not re-queued
        if there is already a pending (undelivered) entry for that alert.
        """
        queue = _load_queue()
        alert_id = str(alert.get("id", ""))

        # Prevent duplicate pending entries for the same alert
        if alert_id:
            for entry in queue:
                if entry.get("alert_id") == alert_id and not entry.get("delivered"):
                    return entry["queue_id"]

        queue_id = str(uuid.uuid4())
        entry: dict = {
            "queue_id": queue_id,
            "alert_id": alert_id,
            "alert_type": alert.get("alert_type", ""),
            "symbol": alert.get("symbol", ""),
            "message": alert.get("message", ""),
            "severity": severity,
            "triggered_at": alert.get("triggered_at")
            or datetime.now(timezone.utc).isoformat(),
            "context": context or {},
            "delivered": False,
        }
        queue.append(entry)
        _save_queue(queue)
        logger.info(
            "Alert queued",
            extra={
                "queue_id": queue_id,
                "symbol": entry["symbol"],
                "alert_type": entry["alert_type"],
            },
        )
        return queue_id

    def get_pending(self) -> list[dict]:
        """Return all undelivered queue entries."""
        return [e for e in _load_queue() if not e.get("delivered")]

    def mark_delivered(self, queue_ids: list[str]) -> int:
        """Mark queue entries as delivered. Returns count of entries updated."""
        if not queue_ids:
            return 0
        id_set = set(queue_ids)
        queue = _load_queue()
        updated = 0
        for entry in queue:
            if entry.get("queue_id") in id_set and not entry.get("delivered"):
                entry["delivered"] = True
                entry["delivered_at"] = datetime.now(timezone.utc).isoformat()
                updated += 1
        _save_queue(queue)
        if updated:
            logger.info("Alerts delivered", extra={"delivered_count": updated})
        return updated
