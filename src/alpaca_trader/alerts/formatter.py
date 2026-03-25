"""Alert formatter — produces Telegram-ready messages from queued alert dicts."""

_SEVERITY_EMOJI = {
    "info": "ℹ️",
    "warning": "⚠️",
    "critical": "🚨",
}


def format_alert_telegram(alert: dict) -> str:
    """Format a queued alert entry for Telegram delivery.

    Accepts either a raw alert dict (from AlertChecker) or a queue entry dict
    (from TelegramDeliveryQueue). Both shapes are handled.
    """
    alert_type = alert.get("alert_type", "")
    symbol = alert.get("symbol", "").upper()
    context = alert.get("context") or {}
    severity = alert.get("severity", "info")
    severity_icon = _SEVERITY_EMOJI.get(severity, "ℹ️")

    body = _format_body(alert_type, symbol, context, alert)
    return f"{severity_icon} {body}"


def _format_body(alert_type: str, symbol: str, ctx: dict, alert: dict) -> str:
    if alert_type == "fill":
        side = ctx.get("side", "")
        qty = ctx.get("qty") or ctx.get("filled_qty", "?")
        price = ctx.get("price") or ctx.get("filled_avg_price", "?")
        side_str = f" {side}" if side else ""
        return f"ORDER FILLED: {symbol}{side_str} {qty}x @ ${price}"

    if alert_type == "pnl":
        pct = ctx.get("pct") or ctx.get("pnl_pct", "")
        value = ctx.get("value") or ctx.get("unrealized_pl", "")
        direction = "up" if _is_positive(pct) else "down"
        pct_str = f"{pct}%" if pct != "" else ""
        value_str = f" (${value})" if value != "" else ""
        return f"📊 P&L ALERT: {symbol} is {direction} {pct_str}{value_str}"

    if alert_type == "expiry":
        days = ctx.get("days") or ctx.get("days_to_expiry", "?")
        value = ctx.get("value") or ctx.get("unrealized_pl", "")
        pnl_str = f" — current P&L: ${value}" if value != "" else ""
        return f"⏰ EXPIRING: {symbol} expires in {days}d{pnl_str}"

    if alert_type == "squeeze":
        width = ctx.get("width") or ctx.get("strength", "")
        width_str = f" (width: {width})" if width != "" else ""
        return f"🔥 SQUEEZE DETECTED: {symbol} Bollinger Band squeeze{width_str}"

    if alert_type == "signal":
        strategy = ctx.get("strategy", "")
        direction = ctx.get("direction", "")
        score = ctx.get("score") or ctx.get("strength", "")
        parts = []
        if strategy:
            parts.append(strategy)
        if direction:
            parts.append(direction)
        detail = " ".join(parts)
        score_str = f" (confidence: {score})" if score != "" else ""
        return f"📡 SIGNAL: {symbol} — {detail}{score_str}"

    if alert_type == "price":
        price = ctx.get("price") or ctx.get("current_price", "?")
        target = ctx.get("target") or ctx.get("target_price", "?")
        return f"🎯 PRICE TARGET: {symbol} hit ${price} (target: ${target})"

    # Fallback: use raw message field
    message = alert.get("message", "")
    return message or f"ALERT: {symbol} [{alert_type}]"


def _is_positive(value) -> bool:
    try:
        return float(str(value).replace("%", "")) >= 0
    except (TypeError, ValueError):
        return True
