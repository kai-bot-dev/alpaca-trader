# Sprint 5 PRD: Alert Engine & Monitoring

## Overview
Add an alert engine and scheduled monitoring system to the alpaca-trader platform. Alerts notify when trading conditions are met (fills, P&L thresholds, expiry warnings, price targets). The system should integrate with the existing strategy engine and CLI.

## Requirements

### 1. Alert Engine (`src/alpaca_trader/alerts/`)

#### Alert Types
- **Fill Alert**: Triggered when an order is filled (buy/sell)
- **P&L Alert**: Triggered when position P&L crosses a threshold (e.g., +10%, -5%)
- **Expiry Alert**: Triggered when an option is within N days of expiration
- **Price Target Alert**: Triggered when underlying price crosses a target
- **Squeeze Alert**: Triggered when Bollinger Band squeeze is detected on a watched symbol
- **Signal Alert**: Triggered when a bounce/trend signal fires from the strategy engine

#### Alert Model
```python
class Alert:
    id: int
    alert_type: str  # fill, pnl, expiry, price, squeeze, signal
    symbol: str
    condition: dict  # type-specific params (threshold, target_price, days_to_expiry, etc.)
    status: str  # active, triggered, dismissed
    created_at: datetime
    triggered_at: Optional[datetime]
    message: str  # human-readable alert message
```

#### Database
- Add `alerts` table to existing SQLite database
- Fields: id, alert_type, symbol, condition_json, status, created_at, triggered_at, message

### 2. Alert Checker (`src/alpaca_trader/alerts/checker.py`)
- `AlertChecker` class that evaluates all active alerts against current market state
- Uses existing Alpaca client for market data
- Uses existing strategy engine for squeeze/signal detection
- Returns list of triggered alerts with messages
- Method: `check_all() -> List[TriggeredAlert]`

### 3. Scanner Cron Integration (`src/alpaca_trader/alerts/scanner.py`)
- `ScheduledScanner` class that:
  1. Runs AlertChecker on all active alerts
  2. Scans watchlist symbols through strategy engine
  3. Generates alert messages for any triggers
  4. Returns formatted results (for Telegram/CLI output)
- Designed to be called every 15 minutes during market hours (9:30 AM - 4:00 PM ET, Mon-Fri)

### 4. CLI Commands

#### `alert` command group
```bash
alpaca-trader alert list                    # List all active alerts
alpaca-trader alert add pnl AAPL --threshold 10  # Add P&L alert
alpaca-trader alert add expiry AAPL --days 7     # Add expiry alert
alpaca-trader alert add price AAPL --target 150  # Add price target alert
alpaca-trader alert add squeeze AAPL             # Add squeeze detection alert
alpaca-trader alert dismiss <id>                  # Dismiss an alert
alpaca-trader alert check                         # Run alert check now (manual)
```

#### `monitor` command
```bash
alpaca-trader monitor run    # Run full scan + alert check (one-shot)
alpaca-trader monitor status # Show last scan time, active alerts count
```

### 5. API Routes (`src/alpaca_trader/api/routes/alerts.py`)
- `GET /api/alerts` - List alerts (filterable by status, type, symbol)
- `POST /api/alerts` - Create alert
- `DELETE /api/alerts/{id}` - Dismiss/delete alert
- `POST /api/alerts/check` - Trigger manual alert check
- `GET /api/monitor/status` - Scanner status (last run, next run, active count)

### 6. Frontend Dashboard Updates (`frontend/`)
- Add "Alerts" section to the Strategy Monitor page
- Show active alerts with status indicators
- Allow dismissing alerts from the UI
- Show last scan timestamp and next scheduled scan

## Technical Notes
- Use existing `src/alpaca_trader/core/database.py` for SQLite operations
- Use existing `src/alpaca_trader/strategies/` for signal detection
- Use existing `src/alpaca_trader/core/client.py` for market data
- All CLI commands should support `--json` flag for machine-readable output
- Alert messages should be concise and Telegram-friendly (will be forwarded via OpenClaw)

## Out of Scope (for this sprint)
- Actual Telegram delivery (handled by OpenClaw cron job externally)
- Real-time WebSocket monitoring (future enhancement)
- Alert history/analytics

## Success Criteria
- All alert types can be created, listed, checked, and dismissed via CLI
- `monitor run` executes a full scan and returns any triggered alerts
- API routes work and frontend shows alert status
- Existing functionality (Sprints 1-4) is not broken
