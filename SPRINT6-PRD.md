# Sprint 6 PRD: Telegram Alert Delivery

## Goal
Connect the existing alert engine (Sprint 5) to Telegram, so alerts are delivered to the 🔨 alpaca-trader topic in the Telegram group via the OpenClaw message tool. Add a lightweight delivery module that the existing ScheduledScanner can call when alerts trigger.

## Context
- Alert engine exists: `AlertChecker` evaluates alerts, `ScheduledScanner` runs 15-min checks
- Telegram group is live: chatId `-1003614733355`, alpaca-trader topic is `topic:14`
- OpenClaw gateway handles Telegram sending — we just need to output alerts in a format that can be picked up

## Architecture

### Approach: File-based Alert Queue
The simplest integration: when alerts trigger, write them to a JSON file. An OpenClaw cron job reads the file and sends alerts to Telegram.

This avoids coupling the Python backend to OpenClaw's message API directly.

### Components

#### 1. Alert Delivery Module (`src/alerts/delivery.py`)
- `TelegramDeliveryQueue` class
  - `queue_alert(alert: Alert, context: dict)` — writes triggered alert to queue file
  - `get_pending() -> list[dict]` — reads pending alerts from queue
  - `mark_delivered(alert_ids: list[str])` — marks alerts as delivered
- Queue file location: `data/alert-queue.json`
- Each queued alert includes:
  - `alert_id`, `alert_type`, `symbol`, `message`, `severity` (info/warning/critical)
  - `triggered_at` (ISO timestamp)
  - `context` (price, P&L value, strategy signal details)
  - `delivered` (bool)

#### 2. Update ScheduledScanner (`src/alerts/scheduler.py`)
- After `AlertChecker.check_all()`, pass triggered alerts to `TelegramDeliveryQueue.queue_alert()`
- No changes to alert evaluation logic

#### 3. Alert Formatter (`src/alerts/formatter.py`)
- `format_alert_telegram(alert: dict) -> str` — formats alert for Telegram
- Format by type:
  - **Fill:** `✅ ORDER FILLED: {symbol} {side} {qty}x @ ${price}`
  - **P&L:** `📊 P&L ALERT: {symbol} is {up/down} {pct}% (${value})`
  - **Expiry:** `⏰ EXPIRING: {symbol} expires in {days}d — current P&L: ${value}`
  - **Squeeze:** `🔥 SQUEEZE DETECTED: {symbol} Bollinger Band squeeze (width: {width})`
  - **Signal:** `📡 SIGNAL: {symbol} — {strategy} {direction} signal (confidence: {score})`
  - **Price Target:** `🎯 PRICE TARGET: {symbol} hit ${price} (target: ${target})`
- Include severity emoji: ℹ️ info, ⚠️ warning, 🚨 critical

#### 4. CLI Command (`src/cli/commands/alert.py`)
- Add `alert send-test` command — queues a test alert to verify delivery pipeline
- Add `alert queue` command — shows pending alerts in queue

#### 5. Cron Delivery Script (`scripts/deliver-alerts.sh`)
- Simple bash script that:
  1. Reads `data/alert-queue.json`
  2. For each undelivered alert, outputs formatted message to stdout
  3. Marks as delivered
- This script is called by an OpenClaw cron job
- Actually: better to make this a Python script (`scripts/deliver_alerts.py`) that:
  1. Reads the queue
  2. Formats each alert
  3. Prints JSON output that OpenClaw cron can parse and send

### OpenClaw Cron Job
After the Python module is built, we'll set up:
```
openclaw cron add --name "alpaca-alerts" \
  --schedule "*/15 9-16 * * 1-5" \
  --command "cd /Users/tonylesmb/claw-workspace/alpaca-trader && .venv/bin/python scripts/deliver_alerts.py" \
  --deliver telegram:-1003614733355:topic:14
```

## File Changes
- NEW: `src/alerts/delivery.py` — TelegramDeliveryQueue
- NEW: `src/alerts/formatter.py` — Alert formatting for Telegram
- NEW: `scripts/deliver_alerts.py` — Standalone delivery script for cron
- NEW: `data/alert-queue.json` — Queue file (gitignored)
- MODIFY: `src/alerts/scheduler.py` — Wire up delivery queue after alert checks
- MODIFY: `src/cli/commands/alert.py` — Add `send-test` and `queue` subcommands
- MODIFY: `.gitignore` — Add `data/alert-queue.json`

## Success Criteria
- [ ] Triggered alerts are queued to `data/alert-queue.json`
- [ ] `alert send-test` queues a test alert
- [ ] `alert queue` shows pending alerts
- [ ] `scripts/deliver_alerts.py` reads queue, formats, outputs for delivery
- [ ] Alert messages are well-formatted with emoji and key data
- [ ] Queue handles duplicate prevention (don't re-queue same alert)

## Non-Goals
- No direct HTTP calls to Telegram API (OpenClaw handles that)
- No real-time WebSocket alerts (that's Sprint 7)
- No alert history/analytics UI (future)
